"""Kiểm tra toàn diện tính toàn vẹn và chất lượng của kết quả prediction toàn lưới.

Bao gồm các kiểm tra bắt buộc:
1. Khóa (grid_id, date) của mart đầu vào không trùng lặp.
2. Mỗi khóa đầu vào có đúng 1 prediction cho mỗi model (khóa duy nhất: grid_id, date, model_id).
3. Không mất dòng, không thêm dòng ngoài nguồn (tổng số dòng khớp tuyệt đối đầu vào).
4. grid_id tồn tại 100% trong bảng geometry (dim_grid_1km.parquet).
5. Không có giá trị pm25_pred bị null, NaN hoặc Infinity.
6. Tất cả prediction đều không âm (pm25_pred >= 0.0 µg/m³).
7. Ngày prediction khớp chính xác phạm vi yêu cầu (min_date, max_date, 2.099 ngày).
8. Đối chiếu một tập mẫu phân bố qua nhiều tháng với mô hình nạp trực tiếp trong RAM.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
from xgboost import XGBRegressor

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
DATA_MART = ROOT / "data" / "marts" / "mart_grid_daily_features.parquet"
DIM_GRID = ROOT / "data" / "core" / "dim_grid_1km.parquet"
PRED_ROOT = ROOT / "outputs" / "predictions"
MODELS_ROOT = ROOT / "outputs" / "models"


def verify_all_predictions() -> dict[str, Any]:
    con = duckdb.connect()

    print("================================================================================")
    print("BẮT ĐẦU KIỂM TRA CHẤT LƯỢNG KẾT QUẢ PREDICTION TOÀN LƯỚI")
    print("================================================================================")

    # 1. Thống kê nguồn mart
    print("\n--- 1. Kiểm tra nguồn mart đầu vào ---")
    mart_stats = con.execute(
        f"""
        SELECT
            min(date) AS min_date,
            max(date) AS max_date,
            count(distinct date) AS num_days,
            count(distinct grid_id) AS num_grids,
            count(*) AS total_rows
        FROM '{DATA_MART.as_posix()}'
        """
    ).fetchone()
    min_date_mart, max_date_mart, days_mart, grids_mart, rows_mart = mart_stats
    print(f"  + Mart ngày: {min_date_mart} -> {max_date_mart} ({days_mart} ngày)")
    print(f"  + Số ô lưới: {grids_mart} ô")
    print(f"  + Tổng số dòng: {rows_mart:,}")
    assert rows_mart == days_mart * grids_mart, "Mart không phải tích Descartes hoàn chỉnh!"

    # Kiểm tra khóa mart không trùng lặp
    dup_mart = con.execute(
        f"""
        SELECT count(*)
        FROM (
            SELECT grid_id, date, count(*) AS c
            FROM '{DATA_MART.as_posix()}'
            GROUP BY grid_id, date
            HAVING count(*) > 1
        )
        """
    ).fetchone()[0]
    print(f"  + Trùng lặp khóa (grid_id, date) trong mart: {dup_mart}")
    assert dup_mart == 0, f"Phát hiện {dup_mart} khóa trùng lặp trong mart đầu vào!"

    # 2. Kiểm tra dim_grid_1km
    print("\n--- 2. Kiểm tra bảng geometry dim_grid_1km ---")
    grid_count = con.execute(f"SELECT count(distinct grid_id) FROM '{DIM_GRID.as_posix()}'").fetchone()[0]
    print(f"  + Số grid_id trong dim_grid_1km: {grid_count}")
    assert grid_count == grids_mart, "Số grid_id trong dim_grid_1km không khớp mart!"

    models = [
        ("baseline1", "Baseline_1_OpenAQ_Meteo:v2.0.0-retrospective", "v2.0.0-retrospective"),
        ("baseline2", "Baseline_2_OpenAQ_Meteo_Sat:v2.0.0-retrospective", "v2.0.0-retrospective"),
    ]

    results: dict[str, Any] = {}

    for alias, expected_model_id, expected_version in models:
        print(f"\n--- 3. Kiểm tra mô hình: {alias} ({expected_model_id}) ---")
        model_dir = PRED_ROOT / alias / expected_version
        part_glob = (model_dir / "*.parquet").as_posix()

        # Kiểm tra file manifest
        manifest_path = model_dir / "manifest.json"
        assert manifest_path.exists(), f"Thiếu file manifest tại {manifest_path}"
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
        assert manifest["status"] == "COMPLETED", f"Status manifest không phải COMPLETED: {manifest['status']}"
        assert manifest["model_id"] == expected_model_id
        assert manifest["model_version"] == expected_version
        print(f"  + Manifest hợp lệ: status={manifest['status']}, partitions={len(manifest['partitions'])}")

        # Kiểm tra tổng số dòng, ngày, ô, null, âm, min, max, mean
        stats = con.execute(
            f"""
            SELECT
                count(*) AS total_rows,
                count(distinct date) AS num_days,
                min(date) AS min_date,
                max(date) AS max_date,
                count(distinct grid_id) AS num_grids,
                count(distinct model_id) AS num_models,
                min(model_id) AS min_model_id,
                max(model_id) AS max_model_id,
                count(distinct model_version) AS num_versions,
                min(model_version) AS min_version,
                max(model_version) AS max_version,
                count(distinct run_id) AS num_runs,
                sum(case when pm25_pred is null or isnan(pm25_pred) or isinf(pm25_pred) then 1 else 0 end) AS bad_preds,
                sum(case when pm25_pred < 0.0 then 1 else 0 end) AS negative_preds,
                min(pm25_pred) AS min_pred,
                max(pm25_pred) AS max_pred,
                avg(pm25_pred) AS avg_pred,
                stddev_samp(pm25_pred) AS std_pred
            FROM read_parquet('{part_glob}')
            """
        ).fetchone()

        (
            tot_rows,
            n_days,
            min_d,
            max_d,
            n_grids,
            n_models,
            min_m,
            max_m,
            n_vers,
            min_v,
            max_v,
            n_runs,
            bad_p,
            neg_p,
            min_p,
            max_p,
            avg_p,
            std_p,
        ) = stats

        print(f"  + Tổng số dòng prediction: {tot_rows:,} (yêu cầu: {rows_mart:,})")
        assert tot_rows == rows_mart, f"Số dòng ({tot_rows}) không khớp mart ({rows_mart})!"

        print(f"  + Phạm vi ngày: {min_d} -> {max_d} ({n_days} ngày; yêu cầu: {days_mart} ngày)")
        assert str(min_d) == str(min_date_mart) and str(max_d) == str(max_date_mart) and n_days == days_mart

        print(f"  + Số grid_id phân biệt: {n_grids} (yêu cầu: {grids_mart})")
        assert n_grids == grids_mart

        print(f"  + Model ID: {min_m} (duy nhất: {n_models == 1})")
        assert n_models == 1 and min_m == expected_model_id and max_m == expected_model_id

        print(f"  + Model Version: {min_v} (duy nhất: {n_vers == 1})")
        assert n_vers == 1 and min_v == expected_version and max_v == expected_version

        print(f"  + Dòng không hợp lệ (null/NaN/inf): {bad_p}")
        assert bad_p == 0, f"Phát hiện {bad_p} giá trị null/NaN/inf trong pm25_pred!"

        print(f"  + Dòng giá trị âm: {neg_p}")
        assert neg_p == 0, f"Phát hiện {neg_p} giá trị âm trong pm25_pred!"

        print(f"  + Thống kê phân bố: min = {min_p:.4f}, avg = {avg_p:.4f}, max = {max_p:.4f}, std = {std_p:.4f}")

        # Kiểm tra tính duy nhất của khóa (grid_id, date, model_id)
        print("  + Kiểm tra tính duy nhất của khóa (grid_id, date, model_id)...")
        dup_keys = con.execute(
            f"""
            SELECT count(*)
            FROM (
                SELECT grid_id, date, model_id, count(*) AS c
                FROM read_parquet('{part_glob}')
                GROUP BY grid_id, date, model_id
                HAVING count(*) > 1
            )
            """
        ).fetchone()[0]
        print(f"    - Khóa trùng lặp: {dup_keys}")
        assert dup_keys == 0, f"Phát hiện {dup_keys} khóa bị trùng lặp!"

        # Kiểm tra đối chiếu khóa tập hợp: tập (grid_id, date) của prediction phải KHỚP 100% với mart
        print("  + Kiểm tra khớp tập khóa với mart đầu vào...")
        diff_keys = con.execute(
            f"""
            SELECT
                sum(case when p.grid_id IS NULL then 1 else 0 end) AS in_mart_not_in_pred,
                sum(case when m.grid_id IS NULL then 1 else 0 end) AS in_pred_not_in_mart
            FROM '{DATA_MART.as_posix()}' m
            FULL OUTER JOIN read_parquet('{part_glob}') p
                ON m.grid_id = p.grid_id AND m.date = p.date
            """
        ).fetchone()
        in_mart_not_pred, in_pred_not_mart = diff_keys
        print(f"    - Có trong mart nhưng thiếu trong pred: {in_mart_not_pred}")
        print(f"    - Có trong pred nhưng không có trong mart: {in_pred_not_mart}")
        assert in_mart_not_pred == 0 and in_pred_not_mart == 0, "Tập khóa không khớp 100% giữa mart và pred!"

        # Kiểm tra grid_id tồn tại 100% trong bảng geometry dim_grid_1km
        print("  + Kiểm tra grid_id tồn tại trong dim_grid_1km...")
        invalid_grids = con.execute(
            f"""
            SELECT count(distinct p.grid_id)
            FROM read_parquet('{part_glob}') p
            LEFT JOIN '{DIM_GRID.as_posix()}' g ON p.grid_id = g.grid_id
            WHERE g.grid_id IS NULL
            """
        ).fetchone()[0]
        print(f"    - grid_id lạ không có trong geometry: {invalid_grids}")
        assert invalid_grids == 0, f"Phát hiện {invalid_grids} grid_id không tồn tại trong dim_grid_1km!"

        # 4. Đối chiếu tập mẫu phân bố qua 6 năm với model load trực tiếp trong RAM
        print("  + Kiểm tra đối chiếu tập mẫu phân bố qua các năm với model load trực tiếp...")
        xgb = XGBRegressor()
        xgb.load_model(MODELS_ROOT / alias / "model.json")
        with (MODELS_ROOT / alias / "metadata.json").open("r", encoding="utf-8") as f:
            meta = json.load(f)
        feat_list = meta["feature_list"]

        # Lấy 60 dòng mẫu phân bố đều qua 6 năm từ mart
        sample_rows = con.execute(
            f"""
            SELECT *
            FROM '{DATA_MART.as_posix()}'
            USING SAMPLE 60 ROWS (RESERVOIR)
            ORDER BY date, grid_id
            """
        ).df()

        sample_X = sample_rows.loc[:, feat_list].astype("float64")
        direct_preds = np.clip(xgb.predict(sample_X), 0.0, None)

        sample_keys = sample_rows[["grid_id", "date"]].copy()
        sample_keys["direct_pred"] = direct_preds

        # Đọc prediction đã lưu cho các sample này
        # Join sample_keys với prediction
        con.register("sample_keys_df", sample_keys)
        compared = con.execute(
            f"""
            SELECT
                s.grid_id,
                s.date,
                s.direct_pred,
                p.pm25_pred AS saved_pred,
                abs(s.direct_pred - p.pm25_pred) AS abs_diff
            FROM sample_keys_df s
            JOIN read_parquet('{part_glob}') p
                ON s.grid_id = p.grid_id AND s.date = p.date
            """
        ).df()

        max_diff = compared["abs_diff"].max()
        print(f"    - Số mẫu đối chiếu: {len(compared)}")
        print(f"    - Sai lệch lớn nhất giữa model load trực tiếp và prediction đã lưu: {max_diff:.8f}")
        assert len(compared) == 60, f"Chỉ tìm thấy {len(compared)}/60 mẫu trong prediction!"
        assert max_diff < 1e-6, f"Sai lệch đối chiếu mẫu ({max_diff}) vượt ngưỡng cho phép!"

        results[alias] = {
            "model_id": expected_model_id,
            "model_version": expected_version,
            "total_rows": tot_rows,
            "num_days": n_days,
            "num_grids": n_grids,
            "min_date": str(min_d),
            "max_date": str(max_d),
            "stats": {
                "min": float(min_p),
                "avg": float(avg_p),
                "max": float(max_p),
                "std": float(std_p),
            },
            "sample_verification_max_diff": float(max_diff),
            "verified": True,
        }

    con.close()
    print("\n================================================================================")
    print("TẤT CẢ KIỂM TRA PREDICTION ĐỀU ĐẠT CHUẨN 100%!")
    print("================================================================================\n")
    return results


if __name__ == "__main__":
    verify_all_predictions()
