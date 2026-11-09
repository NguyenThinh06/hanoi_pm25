"""Đánh giá theo 3 phương pháp chuẩn và huấn luyện model cuối cho bài toán ước tính hồi cứu PM2.5 Hà Nội.

Ba phương pháp đánh giá chuẩn:
  A. Spatial GroupKFold (`spatial_groupkfold`) — Đánh giá chính:
       GroupKFold(n_splits=5) theo `grid_id` trên toàn bộ dữ liệu hợp lệ.
       Trả lời câu hỏi chính: mô hình ước tính ra sao tại các ô lưới chưa có nhãn trong tập train.
  B. Random KFold (`random_kfold`) — Benchmark tham khảo:
       KFold(n_splits=5, shuffle=True, random_state=42) chia ngẫu nhiên theo dòng trên cùng tập hợp lệ.
       Cùng `grid_id`, `station_id` và các ngày kế cận có thể xuất hiện ở cả train lẫn validation.
  C. Temporal Split (`temporal_split`) — Đánh giá bổ sung:
       Train `date < 2026-01-01`, Validation `date >= 2026-01-01` đến ngày cuối thực tế trong dữ liệu.
       Giai đoạn năm 2026 đã được khảo sát trong EDA/báo cáo trước đó nên là đánh giá bổ sung,
       không phải independent holdout nguyên vẹn.

Huấn luyện model cuối (`train_final_models`):
  - Sau khi hoàn tất 3 phép đánh giá, huấn luyện riêng Baseline 1 và Baseline 2 trên toàn bộ dữ liệu hợp lệ
    để phục vụ bản đồ ước tính hồi cứu.
  - Lưu model ở định dạng XGBoost native JSON (`outputs/models/baseline1/model.json`,
    `outputs/models/baseline2/model.json`) kèm metadata, cấu hình và kiểm tra tải lại trên sample nhỏ.
"""
from __future__ import annotations

import argparse
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold, KFold
from xgboost import XGBRegressor

from src.common.config import (
    DATA,
    MART_GRID_DAILY,
    MART_STATION_TRAINING,
    OUTPUTS,
    ROOT,
)
from src.common.storage import write_json, write_parquet, write_yaml
from src.models.registry import (
    build_artifact_entry,
    persist_registry_records,
    to_rel_posix,
)

MODEL_VERSION_DEFAULT = "v2.0.0-retrospective"
DEFAULT_SEED = 42
TEMPORAL_SPLIT_CUTOFF = date(2026, 1, 1)

MODEL_B1_CODE = "Baseline_1_OpenAQ_Meteo"
MODEL_B1_NAME = "Baseline 1: OpenAQ + Khí tượng"
MODEL_B2_CODE = "Baseline_2_OpenAQ_Meteo_Sat"
MODEL_B2_NAME = "Baseline 2: OpenAQ + Khí tượng + Vệ tinh"

CALENDAR_SPATIAL_COLS = [
    "year",
    "month",
    "day_of_week",
    "day_of_year",
    "is_weekend",
    "easting_m",
    "northing_m",
]

METEO_COLS = [
    "temp_2m_c",
    "dewpoint_2m_c",
    "rh_pct",
    "precip_mm",
    "wind_speed_10m_ms",
    "wind_u_10m_ms",
    "wind_v_10m_ms",
    "wind_persistence",
    "wind_dir_10m_deg",
    "surface_pressure_hpa",
    "blh_mean_m",
    "blh_min_m",
    "temp_2m_c_missing",
    "dewpoint_2m_c_missing",
    "rh_pct_missing",
    "precip_mm_missing",
    "wind_speed_10m_ms_missing",
    "surface_pressure_hpa_missing",
    "blh_mean_m_missing",
    "blh_min_m_missing",
]

SATELLITE_COLS = [
    "no2_trop_mol_m2",
    "co_mol_m2",
    "o3_mol_m2",
    "so2_mol_m2",
    "aod_047",
    "aod_047_missing",
    "viirs_radiance",
]

BASELINE1_FEATURES = CALENDAR_SPATIAL_COLS + METEO_COLS
BASELINE2_FEATURES = BASELINE1_FEATURES + SATELLITE_COLS

# Danh sách các cột nhãn, thống kê phụ từ nhãn hoặc biến đo tại trạm không được phép lọt vào X
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

XGBOOST_HYPERPARAMS: dict[str, Any] = {
    "n_estimators": 500,
    "learning_rate": 0.05,
    "max_depth": 6,
    "min_child_weight": 5,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.5,
    "reg_lambda": 2.0,
    "objective": "reg:squarederror",
    "tree_method": "hist",
    "n_jobs": 4,
}

MISSING_VALUE_POLICY = (
    "Giữ nguyên giá trị NaN của các biến liên tục để thuật toán XGBoost (tree_method='hist') "
    "tự học hướng rẽ nhánh mặc định, kết hợp các cột cờ nhị phân *_missing (1 = thiếu, 0 = có)."
)
POSTPROCESSING_POLICY = "Cắt các dự đoán âm về 0.0 µg/m³: y_pred = np.clip(raw_pred, 0.0, None)."
RETROSPECTIVE_AVAILABILITY_NOTE = (
    "Đánh giá phục vụ bài toán ước tính hồi cứu (retrospective estimation) sử dụng đặc trưng khí tượng/vệ tinh "
    "cùng ngày và VIIRS theo tháng. Dữ liệu nguồn không kèm metadata thời điểm phát hành từng bản ghi, "
    "nên không khẳng định tính sẵn có thời gian thực (real-time release availability) hay khả năng dự báo ngày mai."
)


def get_git_commit() -> str | None:
    """Lấy mã commit Git hiện tại của repository (nếu có)."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or None
    except Exception:
        return None


def make_xgb_model(random_state: int = DEFAULT_SEED) -> XGBRegressor:
    """Khởi tạo mô hình XGBoost chuẩn cho bài toán ước tính PM2.5."""
    return XGBRegressor(**XGBOOST_HYPERPARAMS, random_state=int(random_state))


def validate_feature_contract(df: pd.DataFrame, feature_list: list[str]) -> pd.DataFrame:
    """
    Kiểm tra hợp đồng đặc trưng (feature contract) và chống rò rỉ nhãn (leakage audit):
      1. Không có cột nhãn `pm25_mean`, thống kê phụ của nhãn hoặc cột cảm biến trạm trong `feature_list`.
      2. Đầy đủ tên cột và giữ nguyên đúng thứ tự cột giữa lúc train và lúc inference.
      3. Ép kiểu `float64` đồng nhất và giữ nguyên `NaN` theo quy tắc xử lý giá trị thiếu.
    """
    if not feature_list:
        raise ValueError("Danh sách đặc trưng (feature_list) không được rỗng.")
    if len(set(feature_list)) != len(feature_list):
        raise ValueError("Danh sách đặc trưng có cột bị lặp tên.")

    leaked = [c for c in feature_list if c in FORBIDDEN_LEAKAGE_COLS or "pm25" in c.lower()]
    if leaked:
        raise ValueError(f"Phát hiện rò rỉ nhãn hoặc cột bị cấm trong feature_list: {leaked}")

    missing_cols = [c for c in feature_list if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Bảng dữ liệu thiếu các cột đặc trưng bắt buộc: {missing_cols}")

    X = df.loc[:, list(feature_list)].astype("float64")
    assert list(X.columns) == list(feature_list), "Thứ tự cột đặc trưng không khớp hợp đồng!"
    return X


def predict_with_contract(
    model: XGBRegressor,
    df: pd.DataFrame,
    feature_list: list[str],
) -> np.ndarray:
    """Tạo dự đoán với kiểm tra chặt tên/thứ tự đặc trưng và cắt giá trị âm về 0.0."""
    X = validate_feature_contract(df, feature_list)
    raw_pred = np.asarray(model.predict(X), dtype="float64")
    return np.clip(raw_pred, 0.0, None)


def prepare_training_dataset(
    df: pd.DataFrame,
    valid_days_only: bool = True,
) -> pd.DataFrame:
    """
    Chuẩn bị và kiểm tra tính toàn vẹn của bảng huấn luyện cấp trạm–ngày:
      - Lọc `is_valid_day == 1` (khi `valid_days_only=True`) và `pm25_mean IS NOT NULL`.
      - Chuẩn hóa cột `date_id` và `date_parsed`.
      - Kiểm tra khóa chính `(station_id, date_id)` không null và không trùng lặp.
      - Sắp xếp tất định theo `(station_id, date_id)` để mọi phép chia tái tạo chính xác 100%.
    """
    required_base = {"station_id", "grid_id", "date", "pm25_mean"}
    missing_base = required_base - set(df.columns)
    if missing_base:
        raise ValueError(f"Bảng huấn luyện thiếu các cột định danh/nhãn cơ bản: {sorted(missing_base)}")

    work = df.copy()
    if valid_days_only and "is_valid_day" in work.columns:
        work = work[work["is_valid_day"] == 1].copy()
    work = work[work["pm25_mean"].notna()].copy()

    if len(work) == 0:
        raise ValueError("Tập dữ liệu huấn luyện sau khi lọc is_valid_day=1 và pm25_mean NOT NULL bị rỗng.")

    work["date_parsed"] = pd.to_datetime(work["date"]).dt.date
    if "date_id" not in work.columns:
        work["date_id"] = pd.to_datetime(work["date"]).dt.strftime("%Y%m%d").astype("int32")
    else:
        work["date_id"] = work["date_id"].astype("int32")

    if work["station_id"].isna().any() or work["date_id"].isna().any() or work["grid_id"].isna().any():
        raise ValueError("Phát hiện giá trị NULL ở các cột khóa (station_id, date_id, grid_id).")

    dup_count = int(work.duplicated(subset=["station_id", "date_id"]).sum())
    if dup_count > 0:
        raise ValueError(f"Phát hiện {dup_count} dòng trùng khóa chính (station_id, date_id).")

    if "station_name" not in work.columns:
        work["station_name"] = work["station_id"].astype(str)
    if "aod_047_missing" not in work.columns:
        work["aod_047_missing"] = work["aod_047"].isna().astype("int8") if "aod_047" in work.columns else 1
    else:
        work["aod_047_missing"] = work["aod_047_missing"].astype("int8")

    # Kiểm tra hợp đồng đặc trưng cho cả 2 baseline ngay từ đầu
    validate_feature_contract(work, BASELINE1_FEATURES)
    validate_feature_contract(work, BASELINE2_FEATURES)

    work = work.sort_values(["station_id", "date_id"], kind="mergesort").reset_index(drop=True)
    return work


def summarize_dataset(sub: pd.DataFrame) -> dict[str, Any]:
    """Tóm tắt số dòng, số trạm, số ô lưới, số ngày riêng biệt và khoảng ngày của một tập dữ liệu."""
    if len(sub) == 0:
        return {
            "n_samples": 0,
            "n_stations": 0,
            "n_grids": 0,
            "n_days": 0,
            "date_min": None,
            "date_max": None,
        }
    dates = pd.to_datetime(sub["date"]).dt.date
    return {
        "n_samples": int(len(sub)),
        "n_stations": int(sub["station_id"].nunique()),
        "n_grids": int(sub["grid_id"].nunique()),
        "n_days": int(dates.nunique()),
        "date_min": str(dates.min()),
        "date_max": str(dates.max()),
    }


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    """
    Tính MAE (µg/m³), RMSE (µg/m³), R² theo sklearn và MAPE (%) chỉ trên các dòng có `pm25_mean > 0`.
    Xử lý rõ nhóm rỗng, nhóm không đủ mẫu/phương sai cho R² và nhóm không có mẫu dương cho MAPE.
    """
    y_t = np.asarray(y_true, dtype="float64")
    y_p = np.asarray(y_pred, dtype="float64")
    mask = ~np.isnan(y_t) & ~np.isnan(y_p)
    yt = y_t[mask]
    yp = y_p[mask]

    if len(yt) == 0:
        return {
            "n_samples": 0,
            "n_mape_samples": 0,
            "rmse": np.nan,
            "mae": np.nan,
            "r2": np.nan,
            "mape_pct": np.nan,
            "null_reason": "empty_group",
        }

    rmse = float(np.sqrt(mean_squared_error(yt, yp)))
    mae = float(mean_absolute_error(yt, yp))

    reasons: list[str] = []
    if len(yt) < 2:
        r2 = np.nan
        reasons.append("insufficient_samples_for_r2 (n < 2)")
    elif np.allclose(yt, yt[0]):
        r2 = np.nan
        reasons.append("zero_variance_in_y_true_for_r2")
    else:
        r2 = round(float(r2_score(yt, yp)), 4)

    pos_mask = yt > 0.0
    n_mape = int(pos_mask.sum())
    if n_mape == 0:
        mape = np.nan
        reasons.append("no_positive_pm25_mean_for_mape")
    else:
        mape = round(float(np.mean(np.abs(yt[pos_mask] - yp[pos_mask]) / yt[pos_mask]) * 100.0), 2)

    return {
        "n_samples": int(len(yt)),
        "n_mape_samples": n_mape,
        "rmse": round(rmse, 4),
        "mae": round(mae, 4),
        "r2": r2,
        "mape_pct": mape,
        "null_reason": "; ".join(reasons) if reasons else None,
    }


def _json_safe_metric_dict(m: dict[str, Any]) -> dict[str, Any]:
    """Chuyển các giá trị NaN sang None để ghi JSON hợp chuẩn."""
    out: dict[str, Any] = {}
    for k, v in m.items():
        if isinstance(v, float) and np.isnan(v):
            out[k] = None
        else:
            out[k] = v
    return out


def _compare_pair(m_b1: dict[str, Any], m_b2: dict[str, Any], tol: float = 1e-12) -> dict[str, Any]:
    """
    So sánh hai baseline theo quy ước:
      delta = Metric(Baseline 2) - Metric(Baseline 1)
      Với MAE và RMSE: delta < 0 nghĩa là Baseline 2 có sai số thấp hơn; delta > 0 nghĩa là Baseline 1 thấp hơn.
    """
    mae1, mae2 = m_b1.get("mae"), m_b2.get("mae")
    rmse1, rmse2 = m_b1.get("rmse"), m_b2.get("rmse")
    r2_1, r2_2 = m_b1.get("r2"), m_b2.get("r2")
    mape1, mape2 = m_b1.get("mape_pct"), m_b2.get("mape_pct")

    def _diff(v2: Any, v1: Any, digits: int = 4) -> float | None:
        if (
            v1 is None
            or v2 is None
            or (isinstance(v1, float) and np.isnan(v1))
            or (isinstance(v2, float) and np.isnan(v2))
        ):
            return None
        return round(float(v2) - float(v1), digits)

    d_mae = _diff(mae2, mae1, 4)
    d_rmse = _diff(rmse2, rmse1, 4)
    d_r2 = _diff(r2_2, r2_1, 4)
    d_mape = _diff(mape2, mape1, 2)

    def _better_err(d: float | None) -> str | None:
        if d is None:
            return None
        if d > tol:
            return MODEL_B1_CODE
        if d < -tol:
            return MODEL_B2_CODE
        return "Tie"

    better_mae = _better_err(d_mae)
    better_rmse = _better_err(d_rmse)
    if better_mae == MODEL_B1_CODE and better_rmse == MODEL_B1_CODE:
        winner = MODEL_B1_CODE
        status = "Baseline_1_Win"
    elif better_mae == MODEL_B2_CODE and better_rmse == MODEL_B2_CODE:
        winner = MODEL_B2_CODE
        status = "Baseline_2_Win"
    elif better_mae == "Tie" and better_rmse == "Tie":
        winner = None
        status = "Tie"
    else:
        winner = None
        status = "Inconclusive"

    return {
        "delta_mae_b2_minus_b1_ug_m3": d_mae,
        "delta_rmse_b2_minus_b1_ug_m3": d_rmse,
        "delta_r2_b2_minus_b1": d_r2,
        "delta_mape_pct_b2_minus_b1": d_mape,
        "better_mae_model": better_mae,
        "better_rmse_model": better_rmse,
        "winner_model_code": winner,
        "comparison_status": status,
    }


def _assert_valid_oof(
    work_df: pd.DataFrame,
    oof_df: pd.DataFrame,
    *,
    require_disjoint_grids_per_fold: bool,
) -> None:
    """
    Leakage & Contract Audit cho dự đoán OOF:
      - Đủ số dòng như tập hợp lệ đầu vào.
      - Mỗi khóa `(station_id, date_id)` xuất hiện đúng 1 lần, không mất và không trùng.
      - Không có giá trị NaN hay dự đoán âm.
      - Nếu là Spatial GroupKFold: mọi dòng của cùng 1 `grid_id` chỉ nằm ở duy nhất 1 `fold_id`
        (tương đương `train_grid_ids ∩ validation_grid_ids = ∅` cho mọi fold).
    """
    if len(oof_df) != len(work_df):
        raise AssertionError(f"Số dòng OOF ({len(oof_df)}) không khớp tập hợp lệ ({len(work_df)}).")

    dup_keys = int(oof_df.duplicated(subset=["station_id", "date_id"]).sum())
    if dup_keys > 0:
        raise AssertionError(f"Phát hiện {dup_keys} khóa (station_id, date_id) bị trùng trong bảng OOF.")

    expected_keys = set(zip(work_df["station_id"], work_df["date_id"]))
    actual_keys = set(zip(oof_df["station_id"], oof_df["date_id"]))
    if expected_keys != actual_keys:
        raise AssertionError("Tập khóa (station_id, date_id) trong OOF không khớp 1-1 với dữ liệu đầu vào.")

    if oof_df[["y_true", "pred_baseline1", "pred_baseline2"]].isna().any().any():
        raise AssertionError("Bảng dự đoán OOF có giá trị NaN.")

    if (oof_df["pred_baseline1"] < 0).any() or (oof_df["pred_baseline2"] < 0).any():
        raise AssertionError("Phát hiện dự đoán âm chưa được cắt về 0.0.")

    if (oof_df["fold_id"] < 0).any():
        raise AssertionError("Phát hiện dòng chưa được gán fold_id hợp lệ.")

    if require_disjoint_grids_per_fold:
        folds_per_grid = oof_df.groupby("grid_id")["fold_id"].nunique()
        leaked_grids = folds_per_grid[folds_per_grid > 1]
        if not leaked_grids.empty:
            raise AssertionError(
                f"Vi phạm Spatial GroupKFold: grid_id xuất hiện ở nhiều hơn 1 fold: {leaked_grids.to_dict()}"
            )


def _compute_cv_breakdown(oof_df: pd.DataFrame, run_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Tính đầy đủ bộ chỉ số cho một phép đánh giá CV (Spatial GroupKFold hoặc Random KFold):
      - Gộp toàn bộ OOF (`overall`)
      - Macro-MAE không trọng số theo `grid_id` (`macro_by_grid`)
      - Theo từng fold (`by_fold`)
      - Theo từng ô lưới `grid_id` (`by_grid`)
      - Theo nhóm có/thiếu AOD (`by_aod`)
    Đồng thời trả về danh sách bản ghi cho bảng `fold_metrics` trong registry.
    """
    y_all = oof_df["y_true"].to_numpy(dtype="float64")
    p1_all = oof_df["pred_baseline1"].to_numpy(dtype="float64")
    p2_all = oof_df["pred_baseline2"].to_numpy(dtype="float64")

    overall_summary = summarize_dataset(oof_df)
    m1_all = _json_safe_metric_dict(compute_metrics(y_all, p1_all))
    m2_all = _json_safe_metric_dict(compute_metrics(y_all, p2_all))
    comp_all = _compare_pair(m1_all, m2_all)

    registry_fold_rows: list[dict[str, Any]] = []

    def _add_reg_row(
        model_code: str,
        scope_type: str,
        scope_id: str,
        sub_sum: dict[str, Any],
        m_dict: dict[str, Any],
        fold_id: int | None = None,
    ) -> None:
        registry_fold_rows.append(
            {
                "run_id": run_id,
                "model_code": model_code,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "fold_id": fold_id,
                "n_samples": sub_sum["n_samples"],
                "n_mape_samples": m_dict["n_mape_samples"],
                "n_stations": sub_sum["n_stations"],
                "n_grids": sub_sum["n_grids"],
                "n_days": sub_sum["n_days"],
                "date_min": sub_sum["date_min"],
                "date_max": sub_sum["date_max"],
                "mae_ug_m3": m_dict["mae"],
                "rmse_ug_m3": m_dict["rmse"],
                "r2": m_dict["r2"],
                "mape_pct": m_dict["mape_pct"],
                "null_reason": m_dict["null_reason"],
            }
        )

    _add_reg_row(MODEL_B1_CODE, "overall", "ALL", overall_summary, m1_all)
    _add_reg_row(MODEL_B2_CODE, "overall", "ALL", overall_summary, m2_all)

    # 1. Theo từng fold
    by_fold: list[dict[str, Any]] = []
    for fid, grp in oof_df.groupby("fold_id", sort=True):
        f_sum = summarize_dataset(grp)
        yf = grp["y_true"].to_numpy(dtype="float64")
        p1f = grp["pred_baseline1"].to_numpy(dtype="float64")
        p2f = grp["pred_baseline2"].to_numpy(dtype="float64")
        m1f = _json_safe_metric_dict(compute_metrics(yf, p1f))
        m2f = _json_safe_metric_dict(compute_metrics(yf, p2f))
        comp_f = _compare_pair(m1f, m2f)
        by_fold.append(
            {
                "fold_id": int(fid),
                **f_sum,
                "grid_ids": sorted(grp["grid_id"].astype(str).unique()),
                "baseline1": m1f,
                "baseline2": m2f,
                "comparison": comp_f,
            }
        )
        _add_reg_row(MODEL_B1_CODE, "fold", f"fold_{int(fid)}", f_sum, m1f, fold_id=int(fid))
        _add_reg_row(MODEL_B2_CODE, "fold", f"fold_{int(fid)}", f_sum, m2f, fold_id=int(fid))

    # 2. Theo từng grid_id (phục vụ tính Macro-MAE không trọng số)
    by_grid_raw: list[dict[str, Any]] = []
    exact_grid_mae_b1: list[float] = []
    exact_grid_mae_b2: list[float] = []

    for gid, grp in oof_df.groupby("grid_id", sort=True):
        g_sum = summarize_dataset(grp)
        yg = grp["y_true"].to_numpy(dtype="float64")
        p1g = grp["pred_baseline1"].to_numpy(dtype="float64")
        p2g = grp["pred_baseline2"].to_numpy(dtype="float64")
        exact_mae1 = float(mean_absolute_error(yg, p1g))
        exact_mae2 = float(mean_absolute_error(yg, p2g))
        exact_grid_mae_b1.append(exact_mae1)
        exact_grid_mae_b2.append(exact_mae2)

        m1g = _json_safe_metric_dict(compute_metrics(yg, p1g))
        m2g = _json_safe_metric_dict(compute_metrics(yg, p2g))
        comp_g = _compare_pair(m1g, m2g)
        fold_vals = sorted(int(x) for x in grp["fold_id"].unique())

        by_grid_raw.append(
            {
                "grid_id": str(gid),
                "fold_ids": fold_vals,
                "fold_id": fold_vals[0] if len(fold_vals) == 1 else None,
                "station_ids": sorted(grp["station_id"].astype(str).unique()),
                "station_names": sorted(grp["station_name"].astype(str).unique()),
                **g_sum,
                "baseline1": m1g,
                "baseline2": m2g,
                "comparison": comp_g,
            }
        )
        _add_reg_row(MODEL_B1_CODE, "grid", str(gid), g_sum, m1g, fold_id=fold_vals[0] if len(fold_vals) == 1 else None)
        _add_reg_row(MODEL_B2_CODE, "grid", str(gid), g_sum, m2g, fold_id=fold_vals[0] if len(fold_vals) == 1 else None)

    by_grid = sorted(by_grid_raw, key=lambda r: (-r["n_samples"], r["grid_id"]))

    macro_mae_b1 = round(float(np.mean(exact_grid_mae_b1)), 4)
    macro_mae_b2 = round(float(np.mean(exact_grid_mae_b2)), 4)
    delta_macro_mae = round(float(np.mean(np.array(exact_grid_mae_b2) - np.array(exact_grid_mae_b1))), 4)
    macro_b1_dict = {
        "n_samples": overall_summary["n_samples"],
        "n_mape_samples": m1_all["n_mape_samples"],
        "mae": macro_mae_b1,
        "rmse": None,
        "r2": None,
        "mape_pct": None,
        "null_reason": "macro_unweighted_grid_average_defined_for_mae_only",
    }
    macro_b2_dict = {
        "n_samples": overall_summary["n_samples"],
        "n_mape_samples": m2_all["n_mape_samples"],
        "mae": macro_mae_b2,
        "rmse": None,
        "r2": None,
        "mape_pct": None,
        "null_reason": "macro_unweighted_grid_average_defined_for_mae_only",
    }
    _add_reg_row(MODEL_B1_CODE, "macro_by_grid", "ALL_GRIDS_UNWEIGHTED", overall_summary, macro_b1_dict)
    _add_reg_row(MODEL_B2_CODE, "macro_by_grid", "ALL_GRIDS_UNWEIGHTED", overall_summary, macro_b2_dict)

    # 3. Theo nhóm có/thiếu AOD
    by_aod: dict[str, Any] = {}
    for aod_key, aod_val in [("aod_available", 0), ("aod_missing", 1)]:
        sub = oof_df[oof_df["aod_047_missing"] == aod_val]
        a_sum = summarize_dataset(sub)
        ya = sub["y_true"].to_numpy(dtype="float64") if len(sub) > 0 else np.array([], dtype="float64")
        p1a = sub["pred_baseline1"].to_numpy(dtype="float64") if len(sub) > 0 else np.array([], dtype="float64")
        p2a = sub["pred_baseline2"].to_numpy(dtype="float64") if len(sub) > 0 else np.array([], dtype="float64")
        m1a = _json_safe_metric_dict(compute_metrics(ya, p1a))
        m2a = _json_safe_metric_dict(compute_metrics(ya, p2a))
        by_aod[aod_key] = {
            **a_sum,
            "aod_047_missing_flag": aod_val,
            "baseline1": m1a,
            "baseline2": m2a,
            "comparison": _compare_pair(m1a, m2a),
        }
        _add_reg_row(MODEL_B1_CODE, "aod_group", aod_key, a_sum, m1a)
        _add_reg_row(MODEL_B2_CODE, "aod_group", aod_key, a_sum, m2a)

    # Đếm thắng/thua/hòa theo fold và theo grid
    fold_b1_mae_wins = sum(1 for f in by_fold if f["comparison"]["better_mae_model"] == MODEL_B1_CODE)
    fold_b2_mae_wins = sum(1 for f in by_fold if f["comparison"]["better_mae_model"] == MODEL_B2_CODE)
    grid_b1_mae_wins = sum(1 for g in by_grid if g["comparison"]["better_mae_model"] == MODEL_B1_CODE)
    grid_b2_mae_wins = sum(1 for g in by_grid if g["comparison"]["better_mae_model"] == MODEL_B2_CODE)
    grid_ties = sum(1 for g in by_grid if g["comparison"]["better_mae_model"] == "Tie")

    metrics_payload = {
        "unit_mae_rmse": "ug/m3",
        "mape_definition": "mean(|y_true - y_pred| / y_true) * 100 on rows with pm25_mean > 0",
        "sign_convention": (
            "delta = Metric(Baseline 2) - Metric(Baseline 1); "
            "for MAE/RMSE, delta < 0 means Baseline 2 is better."
        ),
        "dataset_summary": overall_summary,
        "overall": {
            **overall_summary,
            "baseline1": m1_all,
            "baseline2": m2_all,
            "comparison": comp_all,
        },
        "macro_by_grid": {
            "definition": "Unweighted arithmetic mean of per-grid MAE across all unique grid_ids.",
            "n_grids": len(by_grid),
            "baseline1_macro_mae_ug_m3": macro_mae_b1,
            "baseline2_macro_mae_ug_m3": macro_mae_b2,
            "delta_macro_mae_b2_minus_b1_ug_m3": delta_macro_mae,
            "better_macro_mae_model": (
                MODEL_B1_CODE if delta_macro_mae > 1e-12 else (MODEL_B2_CODE if delta_macro_mae < -1e-12 else "Tie")
            ),
        },
        "win_loss_summary": {
            "by_fold_mae": {
                "total_folds": len(by_fold),
                "baseline1_better": fold_b1_mae_wins,
                "baseline2_better": fold_b2_mae_wins,
                "tie": len(by_fold) - fold_b1_mae_wins - fold_b2_mae_wins,
            },
            "by_grid_mae": {
                "total_grids": len(by_grid),
                "baseline1_better": grid_b1_mae_wins,
                "baseline2_better": grid_b2_mae_wins,
                "tie": grid_ties,
            },
        },
        "by_fold": by_fold,
        "by_grid": by_grid,
        "by_aod": by_aod,
    }
    return metrics_payload, registry_fold_rows


def evaluate_spatial_groupkfold(
    df: pd.DataFrame,
    *,
    output_dir: Path | None = None,
    n_splits: int = 5,
    seed: int = DEFAULT_SEED,
    valid_days_only: bool = True,
    run_id: str | None = None,
) -> dict[str, Any]:
    """
    Phương pháp A: Spatial GroupKFold (`GroupKFold(n_splits=5)` theo `grid_id`) trên toàn bộ dữ liệu hợp lệ.
    Đây là phép đánh giá chính vì trả lời trực tiếp câu hỏi suy rộng sang các ô lưới không có trạm trong train.
    """
    if n_splits < 2:
        raise ValueError(f"n_splits cho Spatial GroupKFold phải >= 2 (nhận được {n_splits}).")

    work = prepare_training_dataset(df, valid_days_only=valid_days_only)
    unique_grids = int(work["grid_id"].nunique())
    if unique_grids < n_splits:
        raise ValueError(
            f"Không đủ số ô lưới khác nhau ({unique_grids}) để chia Spatial GroupKFold với n_splits={n_splits}."
        )

    out_dir = output_dir or (OUTPUTS / "evaluation" / "spatial_groupkfold")
    out_dir.mkdir(parents=True, exist_ok=True)
    eval_run_id = run_id or f"eval_spatial_groupkfold_s{seed}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    y = work["pm25_mean"].to_numpy(dtype="float64")
    X_b1 = validate_feature_contract(work, BASELINE1_FEATURES)
    X_b2 = validate_feature_contract(work, BASELINE2_FEATURES)
    groups = work["grid_id"].to_numpy()

    gkf = GroupKFold(n_splits=n_splits)
    pred_b1 = np.full(len(work), np.nan, dtype="float64")
    pred_b2 = np.full(len(work), np.nan, dtype="float64")
    fold_ids = np.full(len(work), -1, dtype="int32")
    seen_counts = np.zeros(len(work), dtype="int32")

    for fold_idx, (tr_idx, val_idx) in enumerate(gkf.split(work, y, groups=groups)):
        tr_grids = set(groups[tr_idx])
        val_grids = set(groups[val_idx])
        if not tr_grids.isdisjoint(val_grids):
            raise AssertionError(
                f"Spatial leakage ở fold {fold_idx}: train_grid_ids ∩ validation_grid_ids = {tr_grids & val_grids}"
            )

        m1 = make_xgb_model(seed)
        m1.fit(X_b1.iloc[tr_idx], y[tr_idx])
        pred_b1[val_idx] = np.clip(m1.predict(X_b1.iloc[val_idx]), 0.0, None)

        m2 = make_xgb_model(seed)
        m2.fit(X_b2.iloc[tr_idx], y[tr_idx])
        pred_b2[val_idx] = np.clip(m2.predict(X_b2.iloc[val_idx]), 0.0, None)

        fold_ids[val_idx] = int(fold_idx)
        seen_counts[val_idx] += 1

    assert np.all(seen_counts == 1), "Mỗi dòng phải xuất hiện trong validation đúng 1 lần!"

    pred_df = pd.DataFrame(
        {
            "fold_id": fold_ids,
            "station_id": work["station_id"].to_numpy(),
            "station_name": work["station_name"].to_numpy(),
            "grid_id": work["grid_id"].to_numpy(),
            "date": work["date"].to_numpy(),
            "date_id": work["date_id"].to_numpy(),
            "y_true": y,
            "pm25_mean": y,
            "pred_baseline1": pred_b1,
            "pred_baseline2": pred_b2,
            "aod_047_missing": work["aod_047_missing"].to_numpy(dtype="int8"),
        }
    )
    _assert_valid_oof(work, pred_df, require_disjoint_grids_per_fold=True)

    fold_assign_df = pd.DataFrame(
        {
            "row_index": np.arange(len(work), dtype="int32"),
            "station_id": work["station_id"].to_numpy(),
            "date_id": work["date_id"].to_numpy(),
            "date": work["date"].to_numpy(),
            "grid_id": work["grid_id"].to_numpy(),
            "fold_id": fold_ids,
        }
    )

    metrics_payload, reg_fold_rows = _compute_cv_breakdown(pred_df, eval_run_id)
    metrics_payload["evaluation_method"] = "spatial_groupkfold"
    metrics_payload["method_role"] = "primary"
    metrics_payload["run_id"] = eval_run_id

    config_payload = {
        "evaluation_method": "spatial_groupkfold",
        "method_role": "primary",
        "splitter": {"class": "GroupKFold", "n_splits": int(n_splits), "group_col": "grid_id"},
        "random_seed": int(seed),
        "valid_days_only": bool(valid_days_only),
        "label_col": "pm25_mean",
        "primary_key": ["station_id", "date_id"],
        "baseline1_features": BASELINE1_FEATURES,
        "baseline2_features": BASELINE2_FEATURES,
        "xgboost_params": {**XGBOOST_HYPERPARAMS, "random_state": int(seed)},
        "missing_value_policy": MISSING_VALUE_POLICY,
        "postprocessing_policy": POSTPROCESSING_POLICY,
    }

    metrics_path = out_dir / "metrics.json"
    preds_path = out_dir / "predictions.parquet"
    folds_path = out_dir / "fold_assignments.parquet"
    config_path = out_dir / "config.yaml"
    meta_path = out_dir / "metadata.json"

    write_json(metrics_payload, metrics_path)
    write_parquet(pred_df, preds_path)
    write_parquet(fold_assign_df, folds_path)
    write_yaml(config_payload, config_path)

    git_commit = get_git_commit()
    metadata_payload = {
        "run_id": eval_run_id,
        "evaluation_method": "spatial_groupkfold",
        "method_role": "primary",
        "question_answered": "Mô hình ước tính PM2.5 ra sao ở các ô lưới không có nhãn trạm trong tập huấn luyện?",
        "random_seed": int(seed),
        "n_splits": int(n_splits),
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit,
        "dataset_summary": metrics_payload["dataset_summary"],
        "baseline1_features": BASELINE1_FEATURES,
        "baseline2_features": BASELINE2_FEATURES,
        "xgboost_params": {**XGBOOST_HYPERPARAMS, "random_state": int(seed)},
        "leakage_audit": {
            "disjoint_grid_ids_per_fold_verified": True,
            "unique_station_date_key_verified": True,
            "single_oof_prediction_per_row_verified": True,
            "forbidden_label_and_station_cols_excluded": True,
        },
        "limitations": [
            (
                "GroupKFold theo grid_id không có vùng đệm không gian (spatial buffer); "
                "các ô lân cận và cùng ngày vẫn có tương quan khí tượng/vệ tinh."
            ),
            RETROSPECTIVE_AVAILABILITY_NOTE,
        ],
        "artifacts": {
            "metrics_json": to_rel_posix(metrics_path),
            "predictions_parquet": to_rel_posix(preds_path),
            "fold_assignments_parquet": to_rel_posix(folds_path),
            "config_yaml": to_rel_posix(config_path),
            "metadata_json": to_rel_posix(meta_path),
        },
    }
    write_json(metadata_payload, meta_path)

    run_record = {
        "run_id": eval_run_id,
        "evaluation_method": "spatial_groupkfold",
        "method_role": "primary",
        "random_seed": int(seed),
        "n_splits": int(n_splits),
        **metrics_payload["dataset_summary"],
        "winner_model_code": metrics_payload["overall"]["comparison"]["winner_model_code"],
        "comparison_status": metrics_payload["overall"]["comparison"]["comparison_status"],
        "baseline1_metrics": metrics_payload["overall"]["baseline1"],
        "baseline2_metrics": metrics_payload["overall"]["baseline2"],
        "xgboost_params": {**XGBOOST_HYPERPARAMS, "random_state": int(seed)},
        "baseline1_features": BASELINE1_FEATURES,
        "baseline2_features": BASELINE2_FEATURES,
        "git_commit": git_commit,
        "output_dir": to_rel_posix(out_dir),
        "created_at": metadata_payload["executed_at_utc"],
    }
    artifact_entries = [
        build_artifact_entry(
            artifact_id=f"{eval_run_id}:metrics_json",
            owner_type="evaluation_run",
            evaluation_run_id=eval_run_id,
            artifact_kind="metrics_json",
            artifact_path=metrics_path,
        ),
        build_artifact_entry(
            artifact_id=f"{eval_run_id}:predictions_parquet",
            owner_type="evaluation_run",
            evaluation_run_id=eval_run_id,
            artifact_kind="predictions_parquet",
            artifact_path=preds_path,
            row_count=len(pred_df),
        ),
        build_artifact_entry(
            artifact_id=f"{eval_run_id}:fold_assignments_parquet",
            owner_type="evaluation_run",
            evaluation_run_id=eval_run_id,
            artifact_kind="fold_assignments_parquet",
            artifact_path=folds_path,
            row_count=len(fold_assign_df),
        ),
        build_artifact_entry(
            artifact_id=f"{eval_run_id}:config_yaml",
            owner_type="evaluation_run",
            evaluation_run_id=eval_run_id,
            artifact_kind="config_yaml",
            artifact_path=config_path,
        ),
        build_artifact_entry(
            artifact_id=f"{eval_run_id}:metadata_json",
            owner_type="evaluation_run",
            evaluation_run_id=eval_run_id,
            artifact_kind="metadata_json",
            artifact_path=meta_path,
        ),
    ]

    return {
        "metrics": metrics_payload,
        "predictions": pred_df,
        "fold_assignments": fold_assign_df,
        "metadata": metadata_payload,
        "registry_run": run_record,
        "registry_fold_metrics": reg_fold_rows,
        "registry_artifacts": artifact_entries,
    }


def evaluate_random_kfold(
    df: pd.DataFrame,
    *,
    output_dir: Path | None = None,
    n_splits: int = 5,
    seed: int = DEFAULT_SEED,
    valid_days_only: bool = True,
    run_id: str | None = None,
) -> dict[str, Any]:
    """
    Phương pháp B: Random KFold (`KFold(n_splits=5, shuffle=True, random_state=seed)`) trên toàn bộ dữ liệu hợp lệ.
    Đây chỉ là benchmark tham khảo (reference benchmark) vì chia ngẫu nhiên theo dòng: cùng `grid_id`, `station_id`
    và các ngày gần nhau có thể nằm ở cả train lẫn validation.
    """
    if n_splits < 2:
        raise ValueError(f"n_splits cho Random KFold phải >= 2 (nhận được {n_splits}).")

    work = prepare_training_dataset(df, valid_days_only=valid_days_only)
    if len(work) < n_splits:
        raise ValueError(f"Không đủ số dòng ({len(work)}) để chia Random KFold với n_splits={n_splits}.")

    out_dir = output_dir or (OUTPUTS / "evaluation" / "random_kfold")
    out_dir.mkdir(parents=True, exist_ok=True)
    eval_run_id = run_id or f"eval_random_kfold_s{seed}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    y = work["pm25_mean"].to_numpy(dtype="float64")
    X_b1 = validate_feature_contract(work, BASELINE1_FEATURES)
    X_b2 = validate_feature_contract(work, BASELINE2_FEATURES)

    kf = KFold(n_splits=n_splits, shuffle=True, random_state=seed)
    pred_b1 = np.full(len(work), np.nan, dtype="float64")
    pred_b2 = np.full(len(work), np.nan, dtype="float64")
    fold_ids = np.full(len(work), -1, dtype="int32")
    seen_counts = np.zeros(len(work), dtype="int32")

    for fold_idx, (tr_idx, val_idx) in enumerate(kf.split(work)):
        m1 = make_xgb_model(seed)
        m1.fit(X_b1.iloc[tr_idx], y[tr_idx])
        pred_b1[val_idx] = np.clip(m1.predict(X_b1.iloc[val_idx]), 0.0, None)

        m2 = make_xgb_model(seed)
        m2.fit(X_b2.iloc[tr_idx], y[tr_idx])
        pred_b2[val_idx] = np.clip(m2.predict(X_b2.iloc[val_idx]), 0.0, None)

        fold_ids[val_idx] = int(fold_idx)
        seen_counts[val_idx] += 1

    assert np.all(seen_counts == 1), "Mỗi dòng phải xuất hiện trong validation đúng 1 lần!"

    pred_df = pd.DataFrame(
        {
            "fold_id": fold_ids,
            "station_id": work["station_id"].to_numpy(),
            "station_name": work["station_name"].to_numpy(),
            "grid_id": work["grid_id"].to_numpy(),
            "date": work["date"].to_numpy(),
            "date_id": work["date_id"].to_numpy(),
            "y_true": y,
            "pm25_mean": y,
            "pred_baseline1": pred_b1,
            "pred_baseline2": pred_b2,
            "aod_047_missing": work["aod_047_missing"].to_numpy(dtype="int8"),
        }
    )
    _assert_valid_oof(work, pred_df, require_disjoint_grids_per_fold=False)

    fold_assign_df = pd.DataFrame(
        {
            "row_index": np.arange(len(work), dtype="int32"),
            "station_id": work["station_id"].to_numpy(),
            "date_id": work["date_id"].to_numpy(),
            "date": work["date"].to_numpy(),
            "grid_id": work["grid_id"].to_numpy(),
            "fold_id": fold_ids,
        }
    )

    metrics_payload, reg_fold_rows = _compute_cv_breakdown(pred_df, eval_run_id)
    metrics_payload["evaluation_method"] = "random_kfold"
    metrics_payload["method_role"] = "reference_benchmark"
    metrics_payload["run_id"] = eval_run_id

    config_payload = {
        "evaluation_method": "random_kfold",
        "method_role": "reference_benchmark",
        "splitter": {"class": "KFold", "n_splits": int(n_splits), "shuffle": True, "random_state": int(seed)},
        "random_seed": int(seed),
        "valid_days_only": bool(valid_days_only),
        "label_col": "pm25_mean",
        "primary_key": ["station_id", "date_id"],
        "baseline1_features": BASELINE1_FEATURES,
        "baseline2_features": BASELINE2_FEATURES,
        "xgboost_params": {**XGBOOST_HYPERPARAMS, "random_state": int(seed)},
        "missing_value_policy": MISSING_VALUE_POLICY,
        "postprocessing_policy": POSTPROCESSING_POLICY,
    }

    metrics_path = out_dir / "metrics.json"
    preds_path = out_dir / "predictions.parquet"
    folds_path = out_dir / "fold_assignments.parquet"
    config_path = out_dir / "config.yaml"
    meta_path = out_dir / "metadata.json"

    write_json(metrics_payload, metrics_path)
    write_parquet(pred_df, preds_path)
    write_parquet(fold_assign_df, folds_path)
    write_yaml(config_payload, config_path)

    git_commit = get_git_commit()
    metadata_payload = {
        "run_id": eval_run_id,
        "evaluation_method": "random_kfold",
        "method_role": "reference_benchmark",
        "question_answered": (
            "Mô hình khớp/nội suy ra sao khi cho phép các ngày lân cận của cùng trạm/ô xuất hiện trong tập train?"
        ),
        "random_seed": int(seed),
        "n_splits": int(n_splits),
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit,
        "dataset_summary": metrics_payload["dataset_summary"],
        "baseline1_features": BASELINE1_FEATURES,
        "baseline2_features": BASELINE2_FEATURES,
        "xgboost_params": {**XGBOOST_HYPERPARAMS, "random_state": int(seed)},
        "leakage_audit": {
            "disjoint_grid_ids_per_fold_verified": False,
            "unique_station_date_key_verified": True,
            "single_oof_prediction_per_row_verified": True,
            "forbidden_label_and_station_cols_excluded": True,
        },
        "limitations": [
            (
                "Random KFold chia ngẫu nhiên theo từng dòng: cùng grid_id, station_id "
                "và các ngày liền kề nằm ở cả train lẫn validation."
            ),
            (
                "Chỉ dùng làm benchmark tham khảo nội suy trên mạng trạm đã biết; "
                "không phải bằng chứng chính cho ô chưa có trạm."
            ),
            RETROSPECTIVE_AVAILABILITY_NOTE,
        ],
        "artifacts": {
            "metrics_json": to_rel_posix(metrics_path),
            "predictions_parquet": to_rel_posix(preds_path),
            "fold_assignments_parquet": to_rel_posix(folds_path),
            "config_yaml": to_rel_posix(config_path),
            "metadata_json": to_rel_posix(meta_path),
        },
    }
    write_json(metadata_payload, meta_path)

    run_record = {
        "run_id": eval_run_id,
        "evaluation_method": "random_kfold",
        "method_role": "reference_benchmark",
        "random_seed": int(seed),
        "n_splits": int(n_splits),
        **metrics_payload["dataset_summary"],
        "winner_model_code": metrics_payload["overall"]["comparison"]["winner_model_code"],
        "comparison_status": metrics_payload["overall"]["comparison"]["comparison_status"],
        "baseline1_metrics": metrics_payload["overall"]["baseline1"],
        "baseline2_metrics": metrics_payload["overall"]["baseline2"],
        "xgboost_params": {**XGBOOST_HYPERPARAMS, "random_state": int(seed)},
        "baseline1_features": BASELINE1_FEATURES,
        "baseline2_features": BASELINE2_FEATURES,
        "git_commit": git_commit,
        "output_dir": to_rel_posix(out_dir),
        "created_at": metadata_payload["executed_at_utc"],
    }
    artifact_entries = [
        build_artifact_entry(
            artifact_id=f"{eval_run_id}:metrics_json",
            owner_type="evaluation_run",
            evaluation_run_id=eval_run_id,
            artifact_kind="metrics_json",
            artifact_path=metrics_path,
        ),
        build_artifact_entry(
            artifact_id=f"{eval_run_id}:predictions_parquet",
            owner_type="evaluation_run",
            evaluation_run_id=eval_run_id,
            artifact_kind="predictions_parquet",
            artifact_path=preds_path,
            row_count=len(pred_df),
        ),
        build_artifact_entry(
            artifact_id=f"{eval_run_id}:fold_assignments_parquet",
            owner_type="evaluation_run",
            evaluation_run_id=eval_run_id,
            artifact_kind="fold_assignments_parquet",
            artifact_path=folds_path,
            row_count=len(fold_assign_df),
        ),
        build_artifact_entry(
            artifact_id=f"{eval_run_id}:config_yaml",
            owner_type="evaluation_run",
            evaluation_run_id=eval_run_id,
            artifact_kind="config_yaml",
            artifact_path=config_path,
        ),
        build_artifact_entry(
            artifact_id=f"{eval_run_id}:metadata_json",
            owner_type="evaluation_run",
            evaluation_run_id=eval_run_id,
            artifact_kind="metadata_json",
            artifact_path=meta_path,
        ),
    ]

    return {
        "metrics": metrics_payload,
        "predictions": pred_df,
        "fold_assignments": fold_assign_df,
        "metadata": metadata_payload,
        "registry_run": run_record,
        "registry_fold_metrics": reg_fold_rows,
        "registry_artifacts": artifact_entries,
    }


def evaluate_temporal_split(
    df: pd.DataFrame,
    *,
    output_dir: Path | None = None,
    cutoff_date: date = TEMPORAL_SPLIT_CUTOFF,
    seed: int = DEFAULT_SEED,
    valid_days_only: bool = True,
    run_id: str | None = None,
) -> dict[str, Any]:
    """
    Phương pháp C: Temporal Split — Đánh giá bổ sung theo thời gian:
      - Train: `date < cutoff_date` (mặc định `2026-01-01`).
      - Validation: `date >= cutoff_date` đến ngày cuối thực tế có trong dữ liệu (tính từ dữ liệu, không hard-code).
      - Kiểm tra nghiêm ngặt `max(train_date) < min(validation_date)`.
      - Tính metric tổng thể, theo nhóm có/thiếu AOD (`aod_047_missing`), theo trạm đã biết/chưa biết và theo từng trạm.
    """
    work = prepare_training_dataset(df, valid_days_only=valid_days_only)
    train_mask = work["date_parsed"] < cutoff_date
    val_mask = work["date_parsed"] >= cutoff_date

    train_df = work[train_mask].reset_index(drop=True)
    val_df = work[val_mask].reset_index(drop=True)

    if len(train_df) == 0:
        raise ValueError(f"Tập train trước {cutoff_date} rỗng.")
    if len(val_df) == 0:
        raise ValueError(f"Tập validation từ {cutoff_date} trở đi rỗng.")

    max_train_date = max(train_df["date_parsed"])
    min_val_date = min(val_df["date_parsed"])
    max_val_date = max(val_df["date_parsed"])
    if not (max_train_date < min_val_date):
        raise AssertionError(
            f"Temporal leakage: max(train_date)={max_train_date} không nhỏ hơn min(validation_date)={min_val_date}!"
        )

    out_dir = output_dir or (OUTPUTS / "evaluation" / "temporal_split")
    out_dir.mkdir(parents=True, exist_ok=True)
    eval_run_id = run_id or f"eval_temporal_split_s{seed}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    y_tr = train_df["pm25_mean"].to_numpy(dtype="float64")
    X_tr_b1 = validate_feature_contract(train_df, BASELINE1_FEATURES)
    X_tr_b2 = validate_feature_contract(train_df, BASELINE2_FEATURES)

    m1 = make_xgb_model(seed)
    m1.fit(X_tr_b1, y_tr)
    pred_b1 = predict_with_contract(m1, val_df, BASELINE1_FEATURES)

    m2 = make_xgb_model(seed)
    m2.fit(X_tr_b2, y_tr)
    pred_b2 = predict_with_contract(m2, val_df, BASELINE2_FEATURES)

    train_stations = set(train_df["station_id"].unique())
    val_stations = set(val_df["station_id"].unique())
    known_val_stations = sorted(str(s) for s in (val_stations & train_stations))
    unseen_val_stations = sorted(str(s) for s in (val_stations - train_stations))
    is_known_station = val_df["station_id"].isin(train_stations).astype("int8").to_numpy()
    aod_missing = val_df["aod_047_missing"].to_numpy(dtype="int8")
    y_val = val_df["pm25_mean"].to_numpy(dtype="float64")

    pred_df = pd.DataFrame(
        {
            "station_id": val_df["station_id"].to_numpy(),
            "station_name": val_df["station_name"].to_numpy(),
            "grid_id": val_df["grid_id"].to_numpy(),
            "date": val_df["date"].to_numpy(),
            "date_id": val_df["date_id"].to_numpy(),
            "y_true": y_val,
            "pm25_mean": y_val,
            "pred_baseline1": pred_b1,
            "pred_baseline2": pred_b2,
            "aod_047_missing": aod_missing,
            "is_known_station": is_known_station,
        }
    )
    assert int(pred_df.duplicated(subset=["station_id", "date_id"]).sum()) == 0, "Trùng khóa trong validation!"

    split_assign_df = pd.DataFrame(
        {
            "row_index": np.arange(len(work), dtype="int32"),
            "station_id": work["station_id"].to_numpy(),
            "date_id": work["date_id"].to_numpy(),
            "date": work["date"].to_numpy(),
            "grid_id": work["grid_id"].to_numpy(),
            "split_role": np.where(val_mask.to_numpy(), "validation", "train"),
        }
    )

    train_sum = summarize_dataset(train_df)
    val_sum = summarize_dataset(val_df)
    full_sum = summarize_dataset(work)

    m1_all = _json_safe_metric_dict(compute_metrics(y_val, pred_b1))
    m2_all = _json_safe_metric_dict(compute_metrics(y_val, pred_b2))
    comp_all = _compare_pair(m1_all, m2_all)

    reg_fold_rows: list[dict[str, Any]] = []

    def _add_reg_row(
        model_code: str,
        scope_type: str,
        scope_id: str,
        sub_sum: dict[str, Any],
        m_dict: dict[str, Any],
    ) -> None:
        reg_fold_rows.append(
            {
                "run_id": eval_run_id,
                "model_code": model_code,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "fold_id": 0,
                "n_samples": sub_sum["n_samples"],
                "n_mape_samples": m_dict["n_mape_samples"],
                "n_stations": sub_sum["n_stations"],
                "n_grids": sub_sum["n_grids"],
                "n_days": sub_sum["n_days"],
                "date_min": sub_sum["date_min"],
                "date_max": sub_sum["date_max"],
                "mae_ug_m3": m_dict["mae"],
                "rmse_ug_m3": m_dict["rmse"],
                "r2": m_dict["r2"],
                "mape_pct": m_dict["mape_pct"],
                "null_reason": m_dict["null_reason"],
            }
        )

    _add_reg_row(MODEL_B1_CODE, "overall", "ALL", val_sum, m1_all)
    _add_reg_row(MODEL_B2_CODE, "overall", "ALL", val_sum, m2_all)

    by_aod: dict[str, Any] = {}
    for aod_key, aod_val in [("aod_available", 0), ("aod_missing", 1)]:
        sub = pred_df[pred_df["aod_047_missing"] == aod_val]
        a_sum = summarize_dataset(sub)
        ya = sub["y_true"].to_numpy(dtype="float64") if len(sub) > 0 else np.array([], dtype="float64")
        p1a = sub["pred_baseline1"].to_numpy(dtype="float64") if len(sub) > 0 else np.array([], dtype="float64")
        p2a = sub["pred_baseline2"].to_numpy(dtype="float64") if len(sub) > 0 else np.array([], dtype="float64")
        m1a = _json_safe_metric_dict(compute_metrics(ya, p1a))
        m2a = _json_safe_metric_dict(compute_metrics(ya, p2a))
        by_aod[aod_key] = {
            **a_sum,
            "aod_047_missing_flag": aod_val,
            "baseline1": m1a,
            "baseline2": m2a,
            "comparison": _compare_pair(m1a, m2a),
        }
        _add_reg_row(MODEL_B1_CODE, "aod_group", aod_key, a_sum, m1a)
        _add_reg_row(MODEL_B2_CODE, "aod_group", aod_key, a_sum, m2a)

    by_station_familiarity: dict[str, Any] = {}
    for fam_key, fam_val in [("known_in_train", 1), ("unseen_in_train", 0)]:
        sub = pred_df[pred_df["is_known_station"] == fam_val]
        f_sum = summarize_dataset(sub)
        yf = sub["y_true"].to_numpy(dtype="float64") if len(sub) > 0 else np.array([], dtype="float64")
        p1f = sub["pred_baseline1"].to_numpy(dtype="float64") if len(sub) > 0 else np.array([], dtype="float64")
        p2f = sub["pred_baseline2"].to_numpy(dtype="float64") if len(sub) > 0 else np.array([], dtype="float64")
        m1f = _json_safe_metric_dict(compute_metrics(yf, p1f))
        m2f = _json_safe_metric_dict(compute_metrics(yf, p2f))
        by_station_familiarity[fam_key] = {
            **f_sum,
            "is_known_station_flag": fam_val,
            "baseline1": m1f,
            "baseline2": m2f,
            "comparison": _compare_pair(m1f, m2f),
        }
        _add_reg_row(MODEL_B1_CODE, "station_familiarity", fam_key, f_sum, m1f)
        _add_reg_row(MODEL_B2_CODE, "station_familiarity", fam_key, f_sum, m2f)

    by_station_raw: list[dict[str, Any]] = []
    for st_id, grp in pred_df.groupby("station_id", sort=True):
        s_sum = summarize_dataset(grp)
        ys = grp["y_true"].to_numpy(dtype="float64")
        p1s = grp["pred_baseline1"].to_numpy(dtype="float64")
        p2s = grp["pred_baseline2"].to_numpy(dtype="float64")
        m1s = _json_safe_metric_dict(compute_metrics(ys, p1s))
        m2s = _json_safe_metric_dict(compute_metrics(ys, p2s))
        by_station_raw.append(
            {
                "station_id": str(st_id),
                "station_name": str(grp["station_name"].iloc[0]),
                "grid_id": str(grp["grid_id"].iloc[0]),
                "is_known_station": bool(int(grp["is_known_station"].iloc[0]) == 1),
                "aod_available_rows": int((grp["aod_047_missing"] == 0).sum()),
                "aod_missing_rows": int((grp["aod_047_missing"] == 1).sum()),
                **s_sum,
                "baseline1": m1s,
                "baseline2": m2s,
                "comparison": _compare_pair(m1s, m2s),
            }
        )
        _add_reg_row(MODEL_B1_CODE, "station", str(st_id), s_sum, m1s)
        _add_reg_row(MODEL_B2_CODE, "station", str(st_id), s_sum, m2s)

    by_station = sorted(by_station_raw, key=lambda r: (-r["n_samples"], r["station_id"]))

    prior_exploration_audit = {
        "was_2026_explored_previously": True,
        "is_independent_untouched_holdout": False,
        "evidence_in_repository": [
            (
                "notebooks/01_raw_and_initial_eda.ipynb và notebooks/02_hypothesis_testing_eda.ipynb "
                "đã khảo sát thống kê trên toàn bộ 7.290 dòng hợp lệ giai đoạn 01/01/2021 - 30/09/2026."
            ),
            (
                "docs/eda_temporal_split.md đã phân tích trực tiếp phân bố năm 2026 "
                "(1.010 dòng, 6 trạm, 74 dòng có AOD trên 30 ngày, 936 dòng thiếu AOD)."
            ),
            "Các lần chạy đánh giá trước trong repository đã tính sai số trên giai đoạn 2026.",
        ],
        "methodological_note": (
            "Phép chia thời gian (train < 2026-01-01, validation >= 2026-01-01) là đánh giá bổ sung "
            "đã được khảo sát (explored supplementary evaluation), KHÔNG phải independent holdout "
            "nguyên vẹn. Tuyệt đối không dùng kết quả này để tinh chỉnh model rồi tuyên bố cùng tập "
            "là kiểm thử độc lập."
        ),
    }

    metrics_payload = {
        "evaluation_method": "temporal_split",
        "method_role": "supplementary",
        "run_id": eval_run_id,
        "unit_mae_rmse": "ug/m3",
        "mape_definition": "mean(|y_true - y_pred| / y_true) * 100 on rows with pm25_mean > 0",
        "sign_convention": (
            "delta = Metric(Baseline 2) - Metric(Baseline 1); "
            "for MAE/RMSE, delta < 0 means Baseline 2 is better."
        ),
        "split_boundary": {
            "cutoff_date": str(cutoff_date),
            "train_rule": f"date < {cutoff_date}",
            "validation_rule": f"date >= {cutoff_date} up to actual max date in dataset ({max_val_date})",
            "max_train_date": str(max_train_date),
            "min_validation_date": str(min_val_date),
            "max_validation_date": str(max_val_date),
            "non_overlapping_dates_verified": True,
        },
        "full_dataset_summary": full_sum,
        "train_summary": train_sum,
        "validation_summary": val_sum,
        "station_overlap_summary": {
            "validation_total_stations": len(val_stations),
            "validation_stations_seen_in_train_count": len(known_val_stations),
            "validation_stations_unseen_in_train_count": len(unseen_val_stations),
            "validation_stations_seen_in_train": known_val_stations,
            "validation_stations_unseen_in_train": unseen_val_stations,
            "validation_rows_from_known_stations": int((is_known_station == 1).sum()),
            "validation_rows_from_unseen_stations": int((is_known_station == 0).sum()),
        },
        "overall": {
            **val_sum,
            "baseline1": m1_all,
            "baseline2": m2_all,
            "comparison": comp_all,
        },
        "by_aod": by_aod,
        "by_station_familiarity": by_station_familiarity,
        "by_station": by_station,
        "prior_exploration_audit": prior_exploration_audit,
    }

    config_payload = {
        "evaluation_method": "temporal_split",
        "method_role": "supplementary",
        "splitter": {
            "type": "temporal_cutoff",
            "cutoff_date": str(cutoff_date),
            "actual_validation_end_date": str(max_val_date),
        },
        "random_seed": int(seed),
        "valid_days_only": bool(valid_days_only),
        "label_col": "pm25_mean",
        "primary_key": ["station_id", "date_id"],
        "baseline1_features": BASELINE1_FEATURES,
        "baseline2_features": BASELINE2_FEATURES,
        "xgboost_params": {**XGBOOST_HYPERPARAMS, "random_state": int(seed)},
        "missing_value_policy": MISSING_VALUE_POLICY,
        "postprocessing_policy": POSTPROCESSING_POLICY,
    }

    metrics_path = out_dir / "metrics.json"
    preds_path = out_dir / "predictions.parquet"
    splits_path = out_dir / "split_assignments.parquet"
    config_path = out_dir / "config.yaml"
    meta_path = out_dir / "metadata.json"

    write_json(metrics_payload, metrics_path)
    write_parquet(pred_df, preds_path)
    write_parquet(split_assign_df, splits_path)
    write_yaml(config_payload, config_path)

    git_commit = get_git_commit()
    metadata_payload = {
        "run_id": eval_run_id,
        "evaluation_method": "temporal_split",
        "method_role": "supplementary",
        "question_answered": (
            "Mô hình huấn luyện trên giai đoạn trước 2026 ước tính ra sao trên giai đoạn thời gian năm 2026 "
            "(tại các trạm quan trắc hoạt động trong năm 2026)?"
        ),
        "random_seed": int(seed),
        "n_splits": 1,
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit,
        "train_summary": train_sum,
        "validation_summary": val_sum,
        "station_overlap_summary": metrics_payload["station_overlap_summary"],
        "baseline1_features": BASELINE1_FEATURES,
        "baseline2_features": BASELINE2_FEATURES,
        "xgboost_params": {**XGBOOST_HYPERPARAMS, "random_state": int(seed)},
        "leakage_audit": {
            "max_train_date_lt_min_val_date_verified": True,
            "max_train_date": str(max_train_date),
            "min_validation_date": str(min_val_date),
            "unique_station_date_key_verified": True,
            "forbidden_label_and_station_cols_excluded": True,
        },
        "prior_exploration_audit": prior_exploration_audit,
        "limitations": [
            prior_exploration_audit["methodological_note"],
            (
                "Toàn bộ 6/6 trạm có dữ liệu năm 2026 đều đã xuất hiện trong tập train trước 2026, "
                "nên phép chia này không đánh giá khả năng suy rộng sang trạm/ô mới."
            ),
            "Nhóm có AOD năm 2026 rất nhỏ (74 dòng trên 30 ngày riêng biệt).",
            RETROSPECTIVE_AVAILABILITY_NOTE,
        ],
        "artifacts": {
            "metrics_json": to_rel_posix(metrics_path),
            "predictions_parquet": to_rel_posix(preds_path),
            "split_assignments_parquet": to_rel_posix(splits_path),
            "config_yaml": to_rel_posix(config_path),
            "metadata_json": to_rel_posix(meta_path),
        },
    }
    write_json(metadata_payload, meta_path)

    run_record = {
        "run_id": eval_run_id,
        "evaluation_method": "temporal_split",
        "method_role": "supplementary",
        "random_seed": int(seed),
        "n_splits": 1,
        **val_sum,
        "winner_model_code": comp_all["winner_model_code"],
        "comparison_status": comp_all["comparison_status"],
        "baseline1_metrics": m1_all,
        "baseline2_metrics": m2_all,
        "xgboost_params": {**XGBOOST_HYPERPARAMS, "random_state": int(seed)},
        "baseline1_features": BASELINE1_FEATURES,
        "baseline2_features": BASELINE2_FEATURES,
        "git_commit": git_commit,
        "output_dir": to_rel_posix(out_dir),
        "created_at": metadata_payload["executed_at_utc"],
    }
    artifact_entries = [
        build_artifact_entry(
            artifact_id=f"{eval_run_id}:metrics_json",
            owner_type="evaluation_run",
            evaluation_run_id=eval_run_id,
            artifact_kind="metrics_json",
            artifact_path=metrics_path,
        ),
        build_artifact_entry(
            artifact_id=f"{eval_run_id}:predictions_parquet",
            owner_type="evaluation_run",
            evaluation_run_id=eval_run_id,
            artifact_kind="predictions_parquet",
            artifact_path=preds_path,
            row_count=len(pred_df),
        ),
        build_artifact_entry(
            artifact_id=f"{eval_run_id}:split_assignments_parquet",
            owner_type="evaluation_run",
            evaluation_run_id=eval_run_id,
            artifact_kind="split_assignments_parquet",
            artifact_path=splits_path,
            row_count=len(split_assign_df),
        ),
        build_artifact_entry(
            artifact_id=f"{eval_run_id}:config_yaml",
            owner_type="evaluation_run",
            evaluation_run_id=eval_run_id,
            artifact_kind="config_yaml",
            artifact_path=config_path,
        ),
        build_artifact_entry(
            artifact_id=f"{eval_run_id}:metadata_json",
            owner_type="evaluation_run",
            evaluation_run_id=eval_run_id,
            artifact_kind="metadata_json",
            artifact_path=meta_path,
        ),
    ]

    return {
        "metrics": metrics_payload,
        "predictions": pred_df,
        "split_assignments": split_assign_df,
        "metadata": metadata_payload,
        "registry_run": run_record,
        "registry_fold_metrics": reg_fold_rows,
        "registry_artifacts": artifact_entries,
    }


def run_all_evaluations(
    *,
    train_path: Path | None = None,
    outputs_root: Path | None = None,
    n_splits: int = 5,
    seed: int = DEFAULT_SEED,
    valid_days_only: bool = True,
    methods: tuple[str, ...] = ("spatial_groupkfold", "random_kfold", "temporal_split"),
) -> dict[str, Any]:
    """Chạy các phương pháp đánh giá được yêu cầu và đồng bộ metadata vào registry."""
    src_path = train_path or MART_STATION_TRAINING
    out_root = outputs_root or OUTPUTS
    eval_root = out_root / "evaluation"
    reg_root = out_root / "registry"

    df = pd.read_parquet(src_path)
    results: dict[str, Any] = {}
    eval_runs_reg: list[dict[str, Any]] = []
    fold_metrics_reg: list[dict[str, Any]] = []
    artifacts_reg: list[dict[str, Any]] = []

    if "spatial_groupkfold" in methods:
        print(f"[evaluate] 1/3 Chạy Spatial GroupKFold (n_splits={n_splits}, seed={seed})...")
        res_sp = evaluate_spatial_groupkfold(
            df,
            output_dir=eval_root / "spatial_groupkfold",
            n_splits=n_splits,
            seed=seed,
            valid_days_only=valid_days_only,
        )
        results["spatial_groupkfold"] = res_sp
        eval_runs_reg.append(res_sp["registry_run"])
        fold_metrics_reg.extend(res_sp["registry_fold_metrics"])
        artifacts_reg.extend(res_sp["registry_artifacts"])

    if "random_kfold" in methods:
        print(f"[evaluate] 2/3 Chạy Random KFold (n_splits={n_splits}, seed={seed})...")
        res_rk = evaluate_random_kfold(
            df,
            output_dir=eval_root / "random_kfold",
            n_splits=n_splits,
            seed=seed,
            valid_days_only=valid_days_only,
        )
        results["random_kfold"] = res_rk
        eval_runs_reg.append(res_rk["registry_run"])
        fold_metrics_reg.extend(res_rk["registry_fold_metrics"])
        artifacts_reg.extend(res_rk["registry_artifacts"])

    if "temporal_split" in methods:
        print(f"[evaluate] 3/3 Chạy Temporal Split (cutoff={TEMPORAL_SPLIT_CUTOFF}, seed={seed})...")
        res_tm = evaluate_temporal_split(
            df,
            output_dir=eval_root / "temporal_split",
            cutoff_date=TEMPORAL_SPLIT_CUTOFF,
            seed=seed,
            valid_days_only=valid_days_only,
        )
        results["temporal_split"] = res_tm
        eval_runs_reg.append(res_tm["registry_run"])
        fold_metrics_reg.extend(res_tm["registry_fold_metrics"])
        artifacts_reg.extend(res_tm["registry_artifacts"])

    reg_status = persist_registry_records(
        registry_dir=reg_root,
        evaluation_runs=eval_runs_reg,
        fold_metrics=fold_metrics_reg,
        artifact_registry=artifacts_reg,
    )
    results["registry_status"] = reg_status
    return results


def load_saved_xgb_model(model_path: Path) -> XGBRegressor:
    """Tải lại mô hình XGBoost đã lưu từ định dạng native JSON/UBJ."""
    if not model_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file model tại {model_path}")
    loaded = XGBRegressor()
    loaded.load_model(model_path)
    return loaded


def train_final_models(
    df: pd.DataFrame | None = None,
    *,
    train_path: Path | None = None,
    outputs_root: Path | None = None,
    seed: int = DEFAULT_SEED,
    valid_days_only: bool = True,
    model_version: str = MODEL_VERSION_DEFAULT,
    related_evaluation_runs: dict[str, str] | None = None,
    verification_sample_size: int = 25,
) -> dict[str, Any]:
    """
    Huấn luyện riêng Baseline 1 và Baseline 2 trên toàn bộ dữ liệu hợp lệ để phục vụ bản đồ hồi cứu:
      - Không lấy model của fold có điểm tốt nhất làm model cuối.
      - Lưu model dưới dạng XGBoost native JSON (`outputs/models/baseline1/model.json`,
        `outputs/models/baseline2/model.json`).
      - Kiểm tra tải lại model và xác nhận dự đoán khớp tuyệt đối trên một sample nhỏ.
      - Không dùng sai số trên tập train đầy đủ làm validation metric.
    """
    src_path = train_path or MART_STATION_TRAINING
    raw_df = df if df is not None else pd.read_parquet(src_path)
    work = prepare_training_dataset(raw_df, valid_days_only=valid_days_only)

    out_root = outputs_root or OUTPUTS
    models_root = out_root / "models"
    reg_root = out_root / "registry"

    # Nếu chưa truyền related_evaluation_runs, tự động đọc từ outputs/evaluation/*/metadata.json nếu có
    if related_evaluation_runs is None:
        related_evaluation_runs = {}
        eval_root = out_root / "evaluation"
        import json

        for method_name in ("spatial_groupkfold", "random_kfold", "temporal_split"):
            m_file = eval_root / method_name / "metadata.json"
            if m_file.exists():
                try:
                    m_data = json.loads(m_file.read_text(encoding="utf-8"))
                    if "run_id" in m_data:
                        related_evaluation_runs[method_name] = str(m_data["run_id"])
                except Exception:
                    pass

    data_sum = summarize_dataset(work)
    y_full = work["pm25_mean"].to_numpy(dtype="float64")
    sample_df = work.iloc[: min(verification_sample_size, len(work))].copy()
    git_commit = get_git_commit()
    trained_at = datetime.now(timezone.utc).isoformat()

    specs = [
        ("baseline1", MODEL_B1_CODE, MODEL_B1_NAME, BASELINE1_FEATURES),
        ("baseline2", MODEL_B2_CODE, MODEL_B2_NAME, BASELINE2_FEATURES),
    ]

    trained_info: dict[str, Any] = {}
    model_reg_rows: list[dict[str, Any]] = []
    artifact_reg_rows: list[dict[str, Any]] = []

    for folder_name, model_code, model_name, feat_list in specs:
        m_dir = models_root / folder_name
        m_dir.mkdir(parents=True, exist_ok=True)

        X_full = validate_feature_contract(work, feat_list)
        model = make_xgb_model(seed)
        model.fit(X_full, y_full)

        pred_before = predict_with_contract(model, sample_df, feat_list)

        model_path = m_dir / "model.json"
        meta_path = m_dir / "metadata.json"
        config_path = m_dir / "config.yaml"
        sample_path = m_dir / "sample_verification_predictions.parquet"

        model.save_model(model_path)

        # Kiểm tra tải lại model và xác nhận tính nhất quán của dự đoán trên fixture/sample nhỏ
        reloaded_model = load_saved_xgb_model(model_path)
        pred_after = predict_with_contract(reloaded_model, sample_df, feat_list)
        max_abs_diff = float(np.max(np.abs(pred_before - pred_after))) if len(pred_before) > 0 else 0.0
        if not np.allclose(pred_before, pred_after, rtol=1e-6, atol=1e-6):
            raise AssertionError(
                f"Dự đoán sau khi tải lại model {model_code} sai lệch so với trước khi lưu (max_diff={max_abs_diff})!"
            )

        sample_pred_df = pd.DataFrame(
            {
                "station_id": sample_df["station_id"].to_numpy(),
                "date_id": sample_df["date_id"].to_numpy(),
                "grid_id": sample_df["grid_id"].to_numpy(),
                "y_true": sample_df["pm25_mean"].to_numpy(dtype="float64"),
                "pred_before_save": pred_before,
                "pred_after_reload": pred_after,
                "abs_diff": np.abs(pred_before - pred_after),
            }
        )
        write_parquet(sample_pred_df, sample_path)

        model_id = f"{model_code}:{model_version}"
        config_payload = {
            "model_id": model_id,
            "model_code": model_code,
            "model_name": model_name,
            "model_version": model_version,
            "model_format": "xgboost_json",
            "random_seed": int(seed),
            "valid_days_only": bool(valid_days_only),
            "label_col": "pm25_mean",
            "features": feat_list,
            "n_features": len(feat_list),
            "xgboost_params": {**XGBOOST_HYPERPARAMS, "random_state": int(seed)},
            "missing_value_policy": MISSING_VALUE_POLICY,
            "postprocessing_policy": POSTPROCESSING_POLICY,
        }
        write_yaml(config_payload, config_path)

        meta_payload = {
            "model_id": model_id,
            "model_code": model_code,
            "model_name": model_name,
            "model_version": model_version,
            "model_format": "xgboost_json",
            "trained_at_utc": trained_at,
            "git_commit": git_commit,
            "random_seed": int(seed),
            "training_data_source": to_rel_posix(src_path) if src_path.exists() else str(src_path),
            "training_data_summary": data_sum,
            "feature_list": feat_list,
            "n_features": len(feat_list),
            "xgboost_params": {**XGBOOST_HYPERPARAMS, "random_state": int(seed)},
            "missing_value_policy": MISSING_VALUE_POLICY,
            "postprocessing_policy": POSTPROCESSING_POLICY,
            "related_evaluation_runs": related_evaluation_runs,
            "reload_verification": {
                "verified": True,
                "sample_rows": int(len(sample_pred_df)),
                "max_abs_diff_ug_m3": round(max_abs_diff, 8),
            },
            "artifacts": {
                "model_json": to_rel_posix(model_path),
                "metadata_json": to_rel_posix(meta_path),
                "config_yaml": to_rel_posix(config_path),
                "sample_verification_parquet": to_rel_posix(sample_path),
            },
            "usage_note": (
                "Model này được huấn luyện trên 100% dữ liệu trạm-ngày hợp lệ để phục vụ ước tính hồi cứu trên lưới. "
                "Tuyệt đối không dùng sai số khớp trên tập huấn luyện (in-sample train fit) làm chỉ số validation."
            ),
        }
        write_json(meta_payload, meta_path)

        trained_info[folder_name] = {
            "model": reloaded_model,
            "metadata": meta_payload,
            "model_path": model_path,
            "metadata_path": meta_path,
            "sample_predictions": sample_pred_df,
        }

        model_reg_rows.append(
            {
                "model_id": model_id,
                "model_code": model_code,
                "model_name": model_name,
                "model_version": model_version,
                "model_format": "xgboost_json",
                "random_seed": int(seed),
                "n_samples": data_sum["n_samples"],
                "n_stations": data_sum["n_stations"],
                "n_grids": data_sum["n_grids"],
                "n_days": data_sum["n_days"],
                "train_date_min": data_sum["date_min"],
                "train_date_max": data_sum["date_max"],
                "feature_list": feat_list,
                "n_features": len(feat_list),
                "xgboost_params": {**XGBOOST_HYPERPARAMS, "random_state": int(seed)},
                "missing_value_policy": MISSING_VALUE_POLICY,
                "postprocessing_policy": POSTPROCESSING_POLICY,
                "model_artifact_path": to_rel_posix(model_path),
                "metadata_artifact_path": to_rel_posix(meta_path),
                "related_evaluation_runs": related_evaluation_runs,
                "reload_verified": True,
                "git_commit": git_commit,
                "trained_at": trained_at,
            }
        )
        artifact_reg_rows.extend(
            [
                build_artifact_entry(
                    artifact_id=f"{model_id}:model_json",
                    owner_type="model",
                    model_id=model_id,
                    artifact_kind="model_json",
                    artifact_path=model_path,
                ),
                build_artifact_entry(
                    artifact_id=f"{model_id}:metadata_json",
                    owner_type="model",
                    model_id=model_id,
                    artifact_kind="metadata_json",
                    artifact_path=meta_path,
                ),
                build_artifact_entry(
                    artifact_id=f"{model_id}:config_yaml",
                    owner_type="model",
                    model_id=model_id,
                    artifact_kind="config_yaml",
                    artifact_path=config_path,
                ),
                build_artifact_entry(
                    artifact_id=f"{model_id}:sample_verification_parquet",
                    owner_type="model",
                    model_id=model_id,
                    artifact_kind="sample_verification_parquet",
                    artifact_path=sample_path,
                    row_count=len(sample_pred_df),
                ),
            ]
        )

    reg_status = persist_registry_records(
        registry_dir=reg_root,
        model_registry=model_reg_rows,
        artifact_registry=artifact_reg_rows,
    )
    trained_info["registry_status"] = reg_status
    return trained_info


def estimate_full_grid(
    model_b1: XGBRegressor,
    model_b2: XGBRegressor,
    grid_path: Path,
    out_path: Path,
) -> dict[str, float]:
    """
    Ước tính hồi cứu PM2.5 trên toàn bộ 7.577.390 dòng (3.610 ô × 2.099 ngày) của `mart_grid_daily_features.parquet`.
    Chia batch theo từng năm để tối ưu bộ nhớ RAM và tốc độ.
    """
    con = duckdb.connect()
    years = [
        r[0]
        for r in con.execute(f"SELECT DISTINCT year FROM '{grid_path.as_posix()}' ORDER BY year").fetchall()
    ]

    part_files: list[Path] = []
    tmp_dir = out_path.parent / "_tmp_grid_preds"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    for yr in years:
        chunk = pd.read_parquet(grid_path, filters=[("year", "==", int(yr))])
        pred_b1 = predict_with_contract(model_b1, chunk, BASELINE1_FEATURES)
        pred_b2 = predict_with_contract(model_b2, chunk, BASELINE2_FEATURES)

        out_chunk = pd.DataFrame(
            {
                "grid_id": chunk["grid_id"].to_numpy(),
                "date_id": chunk["date_id"].to_numpy(),
                "date": chunk["date"].to_numpy(),
                "year": chunk["year"].to_numpy(),
                "month": chunk["month"].to_numpy(),
                "season": chunk["season"].to_numpy(),
                "easting_m": chunk["easting_m"].to_numpy(),
                "northing_m": chunk["northing_m"].to_numpy(),
                "pm25_pred_b1_meteo": np.round(pred_b1, 2).astype("float32"),
                "pm25_pred_b2_meteo_sat": np.round(pred_b2, 2).astype("float32"),
            }
        )
        part_path = tmp_dir / f"pred_{yr}.parquet"
        out_chunk.to_parquet(part_path, index=False, compression="zstd")
        part_files.append(part_path)
        print(f"  + Đã ước tính năm {yr}: {len(out_chunk):,} ô-ngày")

    glob_expr = (tmp_dir / "pred_*.parquet").as_posix()
    tmp_final = out_path.with_name(f"{out_path.name}.tmp")
    con.execute(
        f"""
        COPY (
            SELECT * FROM read_parquet('{glob_expr}')
            ORDER BY date_id, grid_id
        ) TO '{tmp_final.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    tmp_final.replace(out_path)
    for pf in part_files:
        pf.unlink(missing_ok=True)
    tmp_dir.rmdir()

    stats_row = con.execute(
        f"""
        SELECT
            count(*) AS total_rows,
            round(avg(pm25_pred_b1_meteo), 3) AS b1_mean,
            round(stddev_samp(pm25_pred_b1_meteo), 3) AS b1_std,
            round(min(pm25_pred_b1_meteo), 3) AS b1_min,
            round(max(pm25_pred_b1_meteo), 3) AS b1_max,
            round(avg(pm25_pred_b2_meteo_sat), 3) AS b2_mean,
            round(stddev_samp(pm25_pred_b2_meteo_sat), 3) AS b2_std,
            round(min(pm25_pred_b2_meteo_sat), 3) AS b2_min,
            round(max(pm25_pred_b2_meteo_sat), 3) AS b2_max
        FROM '{out_path.as_posix()}'
        """
    ).fetchone()
    con.close()

    return {
        "total_rows": int(stats_row[0]),
        "b1_mean": float(stats_row[1]),
        "b1_std": float(stats_row[2]),
        "b1_min": float(stats_row[3]),
        "b1_max": float(stats_row[4]),
        "b2_mean": float(stats_row[5]),
        "b2_std": float(stats_row[6]),
        "b2_min": float(stats_row[7]),
        "b2_max": float(stats_row[8]),
    }


def evaluate_baselines(
    df: pd.DataFrame,
    n_splits: int = 5,
    valid_days_only: bool = True,
    seed: int = DEFAULT_SEED,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Hàm tương thích ngược phục vụ kiểm thử nhanh KFold & Spatial GroupKFold trên DataFrame bất kỳ
    (không ghi đè dữ liệu nguồn).
    """
    work = prepare_training_dataset(df, valid_days_only=valid_days_only)
    y = work["pm25_mean"].to_numpy(dtype="float64")
    X_b1 = validate_feature_contract(work, BASELINE1_FEATURES)
    X_b2 = validate_feature_contract(work, BASELINE2_FEATURES)

    records: list[dict[str, object]] = []

    kf = KFold(n_splits=n_splits, shuffle=True, random_state=seed)
    oof_kf_b1 = np.zeros(len(work), dtype="float64")
    oof_kf_b2 = np.zeros(len(work), dtype="float64")
    fi_b1_list: list[np.ndarray] = []
    fi_b2_list: list[np.ndarray] = []

    for tr_idx, val_idx in kf.split(work):
        m1 = make_xgb_model(seed)
        m1.fit(X_b1.iloc[tr_idx], y[tr_idx])
        oof_kf_b1[val_idx] = np.clip(m1.predict(X_b1.iloc[val_idx]), 0.0, None)
        fi_b1_list.append(m1.feature_importances_)

        m2 = make_xgb_model(seed)
        m2.fit(X_b2.iloc[tr_idx], y[tr_idx])
        oof_kf_b2[val_idx] = np.clip(m2.predict(X_b2.iloc[val_idx]), 0.0, None)
        fi_b2_list.append(m2.feature_importances_)

    records.append(
        {
            "eval_mode": "5Fold_CV",
            "scope": "ALL",
            "model_code": MODEL_B1_CODE,
            "model_name": MODEL_B1_NAME,
            **compute_metrics(y, oof_kf_b1),
        }
    )
    records.append(
        {
            "eval_mode": "5Fold_CV",
            "scope": "ALL",
            "model_code": MODEL_B2_CODE,
            "model_name": MODEL_B2_NAME,
            **compute_metrics(y, oof_kf_b2),
        }
    )

    unique_grids = work["grid_id"].nunique()
    actual_splits = min(n_splits, unique_grids)
    oof_sp_b1 = np.full(len(work), np.nan, dtype="float64")
    oof_sp_b2 = np.full(len(work), np.nan, dtype="float64")

    if actual_splits >= 2:
        gkf = GroupKFold(n_splits=actual_splits)
        groups = work["grid_id"].to_numpy()
        for tr_idx, val_idx in gkf.split(work, y, groups=groups):
            m1 = make_xgb_model(seed)
            m1.fit(X_b1.iloc[tr_idx], y[tr_idx])
            oof_sp_b1[val_idx] = np.clip(m1.predict(X_b1.iloc[val_idx]), 0.0, None)

            m2 = make_xgb_model(seed)
            m2.fit(X_b2.iloc[tr_idx], y[tr_idx])
            oof_sp_b2[val_idx] = np.clip(m2.predict(X_b2.iloc[val_idx]), 0.0, None)

        records.append(
            {
                "eval_mode": "Spatial_GroupCV",
                "scope": "ALL",
                "model_code": MODEL_B1_CODE,
                "model_name": MODEL_B1_NAME,
                **compute_metrics(y, oof_sp_b1),
            }
        )
        records.append(
            {
                "eval_mode": "Spatial_GroupCV",
                "scope": "ALL",
                "model_code": MODEL_B2_CODE,
                "model_name": MODEL_B2_NAME,
                **compute_metrics(y, oof_sp_b2),
            }
        )

    oof_df = work[
        ["date_id", "date", "year", "month", "station_id", "station_name", "grid_id", "pm25_mean"]
    ].copy()
    oof_df["pred_cv_b1_meteo"] = oof_kf_b1
    oof_df["pred_cv_b2_meteo_sat"] = oof_kf_b2
    oof_df["pred_spatial_b1_meteo"] = oof_sp_b1
    oof_df["pred_spatial_b2_meteo_sat"] = oof_sp_b2

    fi_rows = []
    for feat, imp in zip(BASELINE1_FEATURES, np.mean(fi_b1_list, axis=0)):
        fi_rows.append({"model_code": MODEL_B1_CODE, "feature": feat, "importance": float(imp)})
    for feat, imp in zip(BASELINE2_FEATURES, np.mean(fi_b2_list, axis=0)):
        fi_rows.append({"model_code": MODEL_B2_CODE, "feature": feat, "importance": float(imp)})

    fi_df = (
        pd.DataFrame(fi_rows)
        .sort_values(["model_code", "importance"], ascending=[True, False])
        .reset_index(drop=True)
    )
    return pd.DataFrame(records), oof_df, fi_df


def train_and_evaluate(
    marts_dir: Path | None = None,
    outputs_root: Path | None = None,
    n_splits: int = 5,
    seed: int = DEFAULT_SEED,
    valid_days_only: bool = True,
    estimate_grid: bool = False,
    model_version: str = MODEL_VERSION_DEFAULT,
) -> dict[str, Any]:
    """
    Chạy trọn bộ 3 phương pháp đánh giá (`spatial_groupkfold`, `random_kfold`, `temporal_split`)
    và huấn luyện lưu 2 model cuối (`baseline1`, `baseline2`) vào `outputs/`.
    Mặc định `estimate_grid=False` để không chạy inference toàn bộ 7,57 triệu ô-ngày khi chỉ đánh giá và lưu model.
    """
    m_dir = marts_dir or (DATA / "marts")
    train_path = m_dir / "mart_station_daily_training.parquet" if marts_dir else MART_STATION_TRAINING
    grid_path = m_dir / "mart_grid_daily_features.parquet" if marts_dir else MART_GRID_DAILY
    out_root = outputs_root or OUTPUTS

    eval_res = run_all_evaluations(
        train_path=train_path,
        outputs_root=out_root,
        n_splits=n_splits,
        seed=seed,
        valid_days_only=valid_days_only,
    )

    related_runs = {
        k: eval_res[k]["metadata"]["run_id"]
        for k in ("spatial_groupkfold", "random_kfold", "temporal_split")
        if k in eval_res
    }

    print(f"[train-final] Huấn luyện và lưu 2 model cuối (version={model_version}, seed={seed})...")
    final_models = train_final_models(
        train_path=train_path,
        outputs_root=out_root,
        seed=seed,
        valid_days_only=valid_days_only,
        model_version=model_version,
        related_evaluation_runs=related_runs,
    )

    print("\n=== TÓM TẮT KẾT QUẢ 3 PHƯƠNG PHÁP ĐÁNH GIÁ ===")
    for method_key, label in [
        ("spatial_groupkfold", "A. Spatial GroupKFold (Main)"),
        ("random_kfold", "B. Random KFold (Benchmark)"),
        ("temporal_split", "C. Temporal Split (>=2026)"),
    ]:
        if method_key not in eval_res:
            continue
        ov = eval_res[method_key]["metrics"]["overall"]
        b1, b2, cmp = ov["baseline1"], ov["baseline2"], ov["comparison"]
        print(
            f"  {label:<30} | N={ov['n_samples']:4d} (MAPE N={b1['n_mape_samples']:4d}) | "
            f"B1 MAE={b1['mae']:.4f}, RMSE={b1['rmse']:.4f}, R2={b1['r2']:.4f}, MAPE={b1['mape_pct']:.2f}% | "
            f"B2 MAE={b2['mae']:.4f}, RMSE={b2['rmse']:.4f}, R2={b2['r2']:.4f}, MAPE={b2['mape_pct']:.2f}% | "
            f"Status={cmp['comparison_status']}"
        )

    grid_stats = None
    if estimate_grid and grid_path.exists():
        out_grid_pred = out_root / "predictions" / "pred_grid_daily_pm25.parquet"
        out_grid_pred.parent.mkdir(parents=True, exist_ok=True)
        print(f"\n[models] Ước tính PM2.5 trên toàn bộ lưới 7,57 triệu ô-ngày -> {to_rel_posix(out_grid_pred)}...")
        grid_stats = estimate_full_grid(
            final_models["baseline1"]["model"],
            final_models["baseline2"]["model"],
            grid_path,
            out_grid_pred,
        )

    return {
        "evaluations": eval_res,
        "final_models": final_models,
        "grid_estimation": grid_stats,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Đánh giá 3 phương pháp chuẩn và huấn luyện model cuối cho bài toán PM2.5 Hà Nội."
    )
    parser.add_argument(
        "--mode",
        choices=["all", "evaluate", "train-final"],
        default="all",
        help=(
            "Chế độ chạy: all (cả đánh giá và train-final), "
            "evaluate (chỉ 3 đánh giá), train-final (chỉ train 2 model cuối)"
        ),
    )
    parser.add_argument(
        "--method",
        choices=["all", "spatial_groupkfold", "random_kfold", "temporal_split"],
        default="all",
        help="Phương pháp đánh giá cần chạy khi ở chế độ evaluate/all (mặc định: all)",
    )
    parser.add_argument("--folds", type=int, default=5, help="Số fold CV (mặc định: 5)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Random seed chuẩn (mặc định: 42)")
    parser.add_argument("--model-version", type=str, default=MODEL_VERSION_DEFAULT, help="Phiên bản model cuối")
    parser.add_argument("--all-days", action="store_true", help="Dùng cả ngày có < 18 giờ hợp lệ")
    parser.add_argument(
        "--estimate-grid",
        action="store_true",
        help="Chạy thêm ước tính trên toàn bộ 7,57 triệu ô-ngày sau khi lưu model cuối",
    )
    args = parser.parse_args()

    valid_only = not args.all_days
    methods = (
        ("spatial_groupkfold", "random_kfold", "temporal_split")
        if args.method == "all"
        else (args.method,)
    )

    if args.mode == "evaluate":
        run_all_evaluations(
            n_splits=args.folds,
            seed=args.seed,
            valid_days_only=valid_only,
            methods=methods,
        )
    elif args.mode == "train-final":
        train_final_models(
            seed=args.seed,
            valid_days_only=valid_only,
            model_version=args.model_version,
        )
    else:
        train_and_evaluate(
            n_splits=args.folds,
            seed=args.seed,
            valid_days_only=valid_only,
            estimate_grid=args.estimate_grid,
            model_version=args.model_version,
        )


if __name__ == "__main__":
    main()
