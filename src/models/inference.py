"""CLI và engine suy luận độc lập cho hai mô hình PM2.5 Hà Nội (Baseline 1 & Baseline 2).

Mục tiêu:
  - Sinh dự đoán hồi cứu PM2.5 trên toàn bộ lưới 1 km (3.610 ô) từ dữ liệu đặc trưng
    `data/marts/mart_grid_daily_features.parquet`.
  - Không gọi lại quy trình huấn luyện (train/train-final/evaluate).
  - Đọc trực tiếp artifact đã lưu tại `outputs/models/{baseline1,baseline2}/`.
  - Đảm bảo nghiêm ngặt hợp đồng đặc trưng (feature contract, feature order, không rò rỉ).
  - Lưu kết quả theo dạng partition tháng:
      outputs/predictions/<model_alias>/<model_version>/YYYY-MM.parquet
  - Schema bắt buộc:
      grid_id (string), date (date), model_id (string), model_version (string),
      pm25_pred (float64), run_id (string).
  - Khóa duy nhất: (grid_id, date, model_id).
  - Ghi file nguyên tử (.tmp -> .parquet), hỗ trợ resume an toàn và sinh manifest có checksum.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from xgboost import XGBRegressor

from src.common.config import MART_GRID_DAILY, OUTPUTS, ROOT

# Định nghĩa các model alias và thư mục tương ứng
MODEL_ALIASES: dict[str, str] = {
    "baseline1": "outputs/models/baseline1",
    "baseline2": "outputs/models/baseline2",
}

# Cột cấm lọt vào feature list (chống rò rỉ)
FORBIDDEN_LEAKAGE_COLS = {
    "pm25_mean",
    "pm25_valid_hours",
    "pm25_std",
    "pm25_min",
    "pm25_max",
    "is_valid_day",
    "pm10_aq",
    "no2_aq",
    "so2_aq",
    "co_aq",
    "co2_aq",
    "o3_aq",
    "openaq_temperature",
    "openaq_temperature_missing",
    "openaq_relativehumidity",
    "openaq_relativehumidity_missing",
}

# Schema PyArrow chuẩn cho kết quả prediction
PREDICTION_PYARROW_SCHEMA = pa.schema(
    [
        ("grid_id", pa.string()),
        ("date", pa.date32()),
        ("model_id", pa.string()),
        ("model_version", pa.string()),
        ("pm25_pred", pa.float64()),
        ("run_id", pa.string()),
    ]
)


def compute_file_sha256(file_path: Path) -> str:
    """Tính mã SHA-256 của file theo từng block 1MB."""
    hasher = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_model_and_metadata(model_dir: Path) -> tuple[XGBRegressor, dict[str, Any]]:
    """Nạp mô hình XGBoost và metadata từ thư mục model đã lưu."""
    model_json_path = model_dir / "model.json"
    metadata_json_path = model_dir / "metadata.json"

    if not model_json_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file model tại: {model_json_path}")
    if not metadata_json_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file metadata tại: {metadata_json_path}")

    with metadata_json_path.open("r", encoding="utf-8") as f:
        metadata = json.load(f)

    # Kiểm tra hợp đồng đặc trưng từ metadata
    features = metadata.get("feature_list", [])
    if not features:
        raise ValueError(f"feature_list trong {metadata_json_path} bị rỗng!")

    leaked = [c for c in features if c in FORBIDDEN_LEAKAGE_COLS or "pm25" in c.lower()]
    if leaked:
        raise ValueError(f"Phát hiện rò rỉ nhãn trong feature_list: {leaked}")

    model = XGBRegressor()
    model.load_model(model_json_path)

    return model, metadata


def validate_and_prepare_features(df: pd.DataFrame, feature_list: list[str]) -> pd.DataFrame:
    """Kiểm tra sự hiện diện, thứ tự đặc trưng và ép kiểu float64 giữ nguyên NaN."""
    missing = [c for c in feature_list if c not in df.columns]
    if missing:
        raise ValueError(f"Dữ liệu đầu vào thiếu các cột đặc trưng bắt buộc: {missing}")

    X = df.loc[:, list(feature_list)].astype("float64")
    if list(X.columns) != list(feature_list):
        raise ValueError("Thứ tự cột đặc trưng không khớp tuyệt đối với metadata!")
    return X


def predict_batch(
    model: XGBRegressor,
    df: pd.DataFrame,
    feature_list: list[str],
) -> np.ndarray:
    """Tạo dự đoán cho batch dữ liệu và áp dụng chính sách hậu xử lý (clip >= 0.0)."""
    X = validate_and_prepare_features(df, feature_list)
    raw_pred = np.asarray(model.predict(X), dtype="float64")
    # Hậu xử lý: cắt âm về 0.0 µg/m³
    return np.clip(raw_pred, 0.0, None)


def verify_partition_file(
    file_path: Path,
    expected_model_id: str,
    expected_model_version: str,
    expected_dates: list[datetime.date] | None = None,
) -> bool:
    """Kiểm tra tính toàn vẹn của một file partition đã tồn tại để quyết định resume."""
    if not file_path.exists() or file_path.stat().st_size == 0:
        return False
    try:
        parquet_file = pq.ParquetFile(file_path)
        schema = parquet_file.schema_arrow
        expected_cols = {"grid_id", "date", "model_id", "model_version", "pm25_pred", "run_id"}
        if set(schema.names) != expected_cols:
            return False

        if parquet_file.metadata.num_rows == 0:
            return False

        # Đọc thử một batch nhỏ để kiểm tra giá trị
        tbl = parquet_file.read_row_group(0)
        df_sample = tbl.to_pandas()
        if len(df_sample) == 0:
            return False
        if (df_sample["model_id"] != expected_model_id).any():
            return False
        if (df_sample["model_version"] != expected_model_version).any():
            return False
        if df_sample["pm25_pred"].isna().any():
            return False
        if (df_sample["pm25_pred"] < 0.0).any():
            return False

        # Kiểm tra đầy đủ ngày nếu có danh sách ngày kỳ vọng
        if expected_dates:
            col_dates = set(parquet_file.read(columns=["date"])["date"].to_pylist())
            for d in expected_dates:
                if d not in col_dates:
                    return False
        return True
    except Exception:
        return False


def run_single_model_inference(
    model_alias: str,
    model_dir: Path,
    data_path: Path,
    output_root: Path,
    start_date: date | None = None,
    end_date: date | None = None,
    run_id: str | None = None,
    resume: bool = True,
    verify_sample_count: int = 50,
) -> dict[str, Any]:
    """Chạy inference toàn bộ hoặc theo khoảng ngày cho một mô hình cụ thể."""
    start_time_utc = datetime.now(timezone.utc)
    t_start = time.time()

    model, metadata = load_model_and_metadata(model_dir)
    model_id: str = metadata["model_id"]
    model_version: str = metadata["model_version"]
    feature_list: list[str] = metadata["feature_list"]

    if run_id is None:
        run_id = f"inf_{model_alias}_{start_time_utc.strftime('%Y%m%dT%H%M%SZ')}"

    # Thư mục output cho model: outputs/predictions/<model_alias>/<model_version>/
    target_dir = output_root / model_alias / model_version
    target_dir.mkdir(parents=True, exist_ok=True)

    # Checksum model và dữ liệu đầu vào
    model_file_sha256 = compute_file_sha256(model_dir / "model.json")
    metadata_file_sha256 = compute_file_sha256(model_dir / "metadata.json")
    data_file_sha256 = compute_file_sha256(data_path)

    # Đọc danh sách các tháng và năm từ data_path
    pq_data = pq.ParquetFile(data_path)
    # Lấy các cột cần thiết để xác định năm/tháng
    meta_df = pq_data.read(columns=["date", "year", "month"]).to_pandas()
    meta_df["date"] = pd.to_datetime(meta_df["date"]).dt.date

    if start_date is not None:
        meta_df = meta_df[meta_df["date"] >= start_date]
    if end_date is not None:
        meta_df = meta_df[meta_df["date"] <= end_date]

    if len(meta_df) == 0:
        raise ValueError("Không có dữ liệu trong khoảng ngày yêu cầu!")

    min_date_actual = meta_df["date"].min()
    max_date_actual = meta_df["date"].max()
    distinct_dates = sorted(meta_df["date"].unique())
    num_days = len(distinct_dates)

    # Danh sách các tháng cần xử lý: (year, month, yyyy_mm_str)
    months_to_process = (
        meta_df[["year", "month"]]
        .drop_duplicates()
        .sort_values(["year", "month"])
        .to_dict(orient="records")
    )
    del meta_df

    print(f"[{model_alias}] Bắt đầu suy luận:")
    print(f"  + Model ID: {model_id}")
    print(f"  + Model Version: {model_version}")
    print(f"  + Phạm vi ngày: {min_date_actual} -> {max_date_actual} ({num_days} ngày)")
    print(f"  + Số partition tháng cần xử lý: {len(months_to_process)}")
    print(f"  + Thư mục output: {target_dir}")

    partitions_manifest: list[dict[str, Any]] = []
    total_rows_predicted = 0
    total_grids_set: set[str] = set()

    # Lưu mẫu kiểm chứng để đối chiếu với model trực tiếp
    sample_records: list[dict[str, Any]] = []

    # Gom các tháng theo từng năm để tối ưu hóa việc đọc file Parquet
    years = sorted(list({m["year"] for m in months_to_process}))

    # Các cột cần nạp từ Parquet: grid_id, date, year, month + feature_list
    needed_cols = list(dict.fromkeys(["grid_id", "date", "year", "month"] + feature_list))

    for yr in years:
        yr_months = [m["month"] for m in months_to_process if m["year"] == yr]

        # Kiểm tra nếu tất cả các tháng của năm đã hoàn thành và resume=True
        all_done = True
        for m_num in yr_months:
            part_name = f"{yr:04d}-{m_num:02d}.parquet"
            part_path = target_dir / part_name
            if not (resume and verify_partition_file(part_path, model_id, model_version)):
                all_done = False
                break

        if all_done:
            print(f"  + Năm {yr}: Tất cả partition đã hoàn tất hợp lệ. Đang kiểm tra checksum...")
            for m_num in yr_months:
                part_name = f"{yr:04d}-{m_num:02d}.parquet"
                part_path = target_dir / part_name
                tbl_part = pq.read_table(part_path)
                n_rows = len(tbl_part)
                sha = compute_file_sha256(part_path)
                total_rows_predicted += n_rows
                grid_ids = tbl_part.column("grid_id").to_pylist()
                total_grids_set.update(grid_ids)
                partitions_manifest.append(
                    {
                        "partition_file": part_name,
                        "relative_path": f"{model_alias}/{model_version}/{part_name}",
                        "rows": n_rows,
                        "sha256": sha,
                        "size_bytes": part_path.stat().st_size,
                    }
                )
            continue

        # Nạp dữ liệu của năm
        print(f"  -> Đang đọc dữ liệu năm {yr}...")
        df_year = pd.read_parquet(
            data_path,
            columns=needed_cols,
            filters=[("year", "==", yr)],
        )
        df_year["date"] = pd.to_datetime(df_year["date"]).dt.date

        if start_date is not None:
            df_year = df_year[df_year["date"] >= start_date]
        if end_date is not None:
            df_year = df_year[df_year["date"] <= end_date]

        for m_num in yr_months:
            part_name = f"{yr:04d}-{m_num:02d}.parquet"
            part_path = target_dir / part_name

            if resume and verify_partition_file(part_path, model_id, model_version):
                print(f"    - Bỏ qua partition đã hoàn thành: {part_name}")
                tbl_part = pq.read_table(part_path)
                n_rows = len(tbl_part)
                sha = compute_file_sha256(part_path)
                total_rows_predicted += n_rows
                grid_ids = tbl_part.column("grid_id").to_pylist()
                total_grids_set.update(grid_ids)
                partitions_manifest.append(
                    {
                        "partition_file": part_name,
                        "relative_path": f"{model_alias}/{model_version}/{part_name}",
                        "rows": n_rows,
                        "sha256": sha,
                        "size_bytes": part_path.stat().st_size,
                    }
                )
                continue

            chunk = df_year[df_year["month"] == m_num].copy()
            if len(chunk) == 0:
                continue

            # Dự đoán
            t_chunk_start = time.time()
            preds = predict_batch(model, chunk, feature_list)
            t_chunk_pred = time.time() - t_chunk_start

            # Đảm bảo không có NaN, null, Infinity
            if np.isnan(preds).any() or np.isinf(preds).any():
                raise ValueError(f"Dự đoán tại {part_name} chứa giá trị NaN hoặc Infinity!")
            if (preds < 0.0).any():
                raise ValueError(f"Dự đoán tại {part_name} chứa giá trị âm sau khi clip!")

            # Lấy mẫu kiểm chứng ngẫu nhiên (nếu còn cần thu thập)
            if len(sample_records) < verify_sample_count:
                sample_indices = np.random.choice(
                    len(chunk),
                    size=min(5, len(chunk)),
                    replace=False,
                )
                for idx in sample_indices:
                    row_data = chunk.iloc[idx]
                    sample_records.append(
                        {
                            "grid_id": str(row_data["grid_id"]),
                            "date": row_data["date"],
                            "feature_values": {feat: float(row_data[feat]) for feat in feature_list},
                            "saved_pred": float(preds[idx]),
                        }
                    )

            out_df = pd.DataFrame(
                {
                    "grid_id": chunk["grid_id"].astype(str).to_numpy(),
                    "date": chunk["date"].to_numpy(),
                    "model_id": model_id,
                    "model_version": model_version,
                    "pm25_pred": preds,
                    "run_id": run_id,
                }
            )

            # Sắp xếp theo date, grid_id
            out_df = out_df.sort_values(["date", "grid_id"]).reset_index(drop=True)

            # Ghi nguyên tử bằng file .tmp rồi rename
            tmp_path = part_path.with_name(f"{part_name}.tmp")
            out_table = pa.Table.from_pandas(
                out_df,
                schema=PREDICTION_PYARROW_SCHEMA,
                preserve_index=False,
            )
            pq.write_table(out_table, tmp_path, compression="zstd")

            # Xác nhận file tạm hợp lệ trước khi ghi đè
            if not verify_partition_file(tmp_path, model_id, model_version):
                tmp_path.unlink(missing_ok=True)
                raise RuntimeError(f"Ghi file tạm không hợp lệ cho {part_name}!")

            tmp_path.replace(part_path)
            sha = compute_file_sha256(part_path)
            n_rows = len(out_df)
            total_rows_predicted += n_rows
            total_grids_set.update(out_df["grid_id"].unique())

            partitions_manifest.append(
                {
                    "partition_file": part_name,
                    "relative_path": f"{model_alias}/{model_version}/{part_name}",
                    "rows": n_rows,
                    "sha256": sha,
                    "size_bytes": part_path.stat().st_size,
                }
            )
            print(
                f"    + Đã ghi {part_name}: {n_rows:,} ô-ngày "
                f"(suy luận {t_chunk_pred:.2f}s, trung bình = {preds.mean():.2f} µg/m³)"
            )

        del df_year

    # Đối chiếu mẫu kiểm chứng trực tiếp với model
    max_sample_diff = 0.0
    if sample_records:
        df_samples = pd.DataFrame([r["feature_values"] for r in sample_records])
        re_preds = predict_batch(model, df_samples, feature_list)
        saved_preds = np.array([r["saved_pred"] for r in sample_records])
        diffs = np.abs(re_preds - saved_preds)
        max_sample_diff = float(np.max(diffs))
        print(f"  + Kiểm tra đối chiếu mẫu ({len(sample_records)} mẫu): Sai lệch lớn nhất = {max_sample_diff}")
        if max_sample_diff > 1e-6:
            raise ValueError(f"Sai lệch đối chiếu mẫu vượt ngưỡng cho phép: {max_sample_diff}")

    end_time_utc = datetime.now(timezone.utc)
    elapsed_seconds = round(time.time() - t_start, 2)

    manifest_data: dict[str, Any] = {
        "run_id": run_id,
        "model_alias": model_alias,
        "model_id": model_id,
        "model_version": model_version,
        "status": "COMPLETED",
        "started_at_utc": start_time_utc.isoformat(),
        "completed_at_utc": end_time_utc.isoformat(),
        "elapsed_seconds": elapsed_seconds,
        "source_data": {
            "path": str(data_path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": data_file_sha256,
        },
        "source_model": {
            "model_json_path": str((model_dir / "model.json").relative_to(ROOT)).replace("\\", "/"),
            "model_json_sha256": model_file_sha256,
            "metadata_json_path": str((model_dir / "metadata.json").relative_to(ROOT)).replace("\\", "/"),
            "metadata_json_sha256": metadata_file_sha256,
        },
        "inference_configuration": {
            "feature_order": feature_list,
            "n_features": len(feature_list),
            "missing_value_policy": metadata.get("missing_value_policy"),
            "postprocessing_policy": metadata.get("postprocessing_policy"),
            "date_range_requested": {
                "start": str(start_date) if start_date else None,
                "end": str(end_date) if end_date else None,
            },
            "date_range_actual": {
                "min_date": str(min_date_actual),
                "max_date": str(max_date_actual),
                "num_days": num_days,
            },
            "num_grids": len(total_grids_set),
            "total_rows": total_rows_predicted,
        },
        "environment": {
            "python_version": sys.version,
            "platform": platform.platform(),
            "libraries": {
                "xgboost": getattr(sys.modules.get("xgboost"), "__version__", "unknown"),
                "pyarrow": pa.__version__,
                "pandas": pd.__version__,
                "numpy": np.__version__,
            },
        },
        "sample_verification": {
            "sample_count": len(sample_records),
            "max_abs_diff_ug_m3": max_sample_diff,
            "verified": max_sample_diff <= 1e-6,
        },
        "partitions": partitions_manifest,
    }

    manifest_path = target_dir / "manifest.json"
    tmp_manifest = target_dir / "manifest.json.tmp"
    with tmp_manifest.open("w", encoding="utf-8") as f:
        json.dump(manifest_data, f, ensure_ascii=False, indent=2)
    tmp_manifest.replace(manifest_path)

    print(f"[{model_alias}] Hoàn tất suy luận: {total_rows_predicted:,} dòng trong {elapsed_seconds}s.")
    print(f"  + Manifest: {manifest_path}")
    return manifest_data


def run_inference(
    model: str = "both",
    start_date: str | None = None,
    end_date: str | None = None,
    output_dir: Path | str | None = None,
    data_path: Path | str | None = None,
    resume: bool = True,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Hàm chính điều phối suy luận cho baseline1, baseline2 hoặc cả hai."""
    out_root = Path(output_dir) if output_dir else OUTPUTS / "predictions"
    mart_path = Path(data_path) if data_path else MART_GRID_DAILY

    if not mart_path.exists():
        raise FileNotFoundError(f"Không tìm thấy mart dữ liệu tại: {mart_path}")

    d_start = date.fromisoformat(start_date) if start_date else None
    d_end = date.fromisoformat(end_date) if end_date else None

    if d_start and d_end and d_start > d_end:
        raise ValueError(f"start_date ({d_start}) không thể sau end_date ({d_end})!")

    models_to_run: list[str] = []
    if model in ("baseline1", "both"):
        models_to_run.append("baseline1")
    if model in ("baseline2", "both"):
        models_to_run.append("baseline2")

    if not models_to_run:
        raise ValueError(f"Tham số model '{model}' không hợp lệ. Chọn baseline1, baseline2 hoặc both.")

    summary: dict[str, Any] = {}
    for alias in models_to_run:
        model_dir = ROOT / MODEL_ALIASES[alias]
        m_run_id = f"{run_id}_{alias}" if run_id else None
        res = run_single_model_inference(
            model_alias=alias,
            model_dir=model_dir,
            data_path=mart_path,
            output_root=out_root,
            start_date=d_start,
            end_date=d_end,
            run_id=m_run_id,
            resume=resume,
        )
        summary[alias] = res

    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CLI suy luận độc lập PM2.5 trên toàn lưới Hà Nội từ hai mô hình đã lưu."
    )
    parser.add_argument(
        "--model",
        choices=["baseline1", "baseline2", "both"],
        default="both",
        help="Chọn mô hình cần suy luận (baseline1, baseline2, hoặc both; mặc định: both)",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Ngày bắt đầu (YYYY-MM-DD); mặc định: từ ngày đầu tiên có trong mart",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="Ngày kết thúc (YYYY-MM-DD); mặc định: đến ngày cuối cùng có trong mart",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Thư mục lưu kết quả prediction (mặc định: outputs/predictions)",
    )
    parser.add_argument(
        "--data-path",
        type=Path,
        default=None,
        help="Đường dẫn file mart_grid_daily_features.parquet",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Chạy lại từ đầu và ghi đè các partition đã có (mặc định: resume)",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Mã định danh lần chạy (run_id) tùy chọn",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_inference(
        model=args.model,
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=args.output_dir,
        data_path=args.data_path,
        resume=not args.no_resume,
        run_id=args.run_id,
    )


if __name__ == "__main__":
    main()
