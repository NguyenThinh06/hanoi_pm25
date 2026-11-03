"""Huấn luyện XGBoost so sánh 2 Baseline và ước tính PM2.5 trên tập 7,57 triệu ô-ngày Hà Nội.

Thiết kế 2 Baseline (không dùng nội suy IDW):
  - Baseline 1 (OpenAQ + Khí tượng):
      Huấn luyện trên nhãn trạm OpenAQ (`pm25_mean` từ `mart_station_daily_training.parquet`)
      kết hợp đặc trưng Lịch + Tọa độ không gian + Khí tượng (ERA5-Land & ERA5 BLH).
  - Baseline 2 (OpenAQ + Khí tượng + Vệ tinh):
      Toàn bộ đặc trưng của Baseline 1 + Đặc trưng Vệ tinh (Sentinel-5P NO2/CO/O3/SO2, MODIS AOD, VIIRS).

Sau khi đánh giá chéo (5-Fold CV & Spatial GroupKFold) để xem mô hình học Baseline nào tốt hơn,
script huấn luyện mô hình trên toàn bộ tập trạm và chạy ước tính (estimate) trực tiếp trên
toàn bộ 7.577.390 dòng (3.610 ô × 2.099 ngày) của bảng `mart_grid_daily_features.parquet`.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold, KFold
from xgboost import XGBRegressor

from src.common.config import DATA, MART_GRID_DAILY, MART_STATION_TRAINING
from src.common.storage import write_parquet

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


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """Tính RMSE, MAE, R2 và MAPE (%) trên các cặp dự báo hợp lệ."""
    mask = ~np.isnan(y_true) & ~np.isnan(y_pred)
    yt = y_true[mask]
    yp = y_pred[mask]
    if len(yt) == 0:
        return {"n_samples": 0, "rmse": np.nan, "mae": np.nan, "r2": np.nan, "mape_pct": np.nan}
    rmse = float(np.sqrt(mean_squared_error(yt, yp)))
    mae = float(mean_absolute_error(yt, yp))
    r2 = float(r2_score(yt, yp)) if len(yt) > 1 else np.nan
    denom = np.maximum(np.abs(yt), 1.0)
    mape = float(np.mean(np.abs(yt - yp) / denom) * 100.0)
    return {
        "n_samples": int(len(yt)),
        "rmse": round(rmse, 4),
        "mae": round(mae, 4),
        "r2": round(r2, 4),
        "mape_pct": round(mape, 2),
    }


def make_xgb_model(random_state: int = 42) -> XGBRegressor:
    """Khởi tạo mô hình XGBoost chuẩn cho bài toán ước tính PM2.5."""
    return XGBRegressor(
        n_estimators=500,
        learning_rate=0.05,
        max_depth=6,
        min_child_weight=5,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.5,
        reg_lambda=2.0,
        objective="reg:squarederror",
        tree_method="hist",
        random_state=random_state,
        n_jobs=4,
    )


def evaluate_baselines(
    df: pd.DataFrame,
    n_splits: int = 5,
    valid_days_only: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Đánh giá Baseline 1 (OpenAQ + Khí tượng) và Baseline 2 (OpenAQ + Khí tượng + Vệ tinh)
    theo 3 chế độ:
      1. Train Fit (khả năng học trên tập huấn luyện)
      2. 5-Fold Cross-Validation chuẩn (KFold ngẫu nhiên cố định seed)
      3. 5-Fold Spatial Cross-Validation (GroupKFold theo `grid_id` - kiểm tra khả năng suy rộng sang ô không có trạm)
    """
    work = df.copy()
    if valid_days_only and "is_valid_day" in work.columns:
        work = work[work["is_valid_day"] == 1].copy()
    work = work[work["pm25_mean"].notna()].reset_index(drop=True)

    y = work["pm25_mean"].to_numpy(dtype="float64")
    X_b1 = work[BASELINE1_FEATURES].astype("float64")
    X_b2 = work[BASELINE2_FEATURES].astype("float64")

    records: list[dict[str, object]] = []

    # --- 1. Đánh giá 5-Fold KFold chuẩn ---
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=42)
    oof_kf_b1 = np.zeros(len(work), dtype="float64")
    oof_kf_b2 = np.zeros(len(work), dtype="float64")
    fi_b1_list: list[np.ndarray] = []
    fi_b2_list: list[np.ndarray] = []

    for fold_idx, (tr_idx, val_idx) in enumerate(kf.split(work)):
        m1 = make_xgb_model(42 + fold_idx)
        m1.fit(X_b1.iloc[tr_idx], y[tr_idx])
        oof_kf_b1[val_idx] = np.clip(m1.predict(X_b1.iloc[val_idx]), 0.0, None)
        fi_b1_list.append(m1.feature_importances_)

        m2 = make_xgb_model(42 + fold_idx)
        m2.fit(X_b2.iloc[tr_idx], y[tr_idx])
        oof_kf_b2[val_idx] = np.clip(m2.predict(X_b2.iloc[val_idx]), 0.0, None)
        fi_b2_list.append(m2.feature_importances_)

    records.append(
        {
            "eval_mode": "5Fold_CV",
            "scope": "ALL",
            "model_code": "Baseline_1_OpenAQ_Meteo",
            "model_name": "Baseline 1: OpenAQ + Khí tượng",
            **compute_metrics(y, oof_kf_b1),
        }
    )
    records.append(
        {
            "eval_mode": "5Fold_CV",
            "scope": "ALL",
            "model_code": "Baseline_2_OpenAQ_Meteo_Sat",
            "model_name": "Baseline 2: OpenAQ + Khí tượng + Vệ tinh",
            **compute_metrics(y, oof_kf_b2),
        }
    )

    for season_name, s_grp in work.groupby("season", sort=True):
        s_idx = s_grp.index.to_numpy()
        records.append(
            {
                "eval_mode": "5Fold_CV",
                "scope": f"season:{season_name}",
                "model_code": "Baseline_1_OpenAQ_Meteo",
                "model_name": "Baseline 1: OpenAQ + Khí tượng",
                **compute_metrics(y[s_idx], oof_kf_b1[s_idx]),
            }
        )
        records.append(
            {
                "eval_mode": "5Fold_CV",
                "scope": f"season:{season_name}",
                "model_code": "Baseline_2_OpenAQ_Meteo_Sat",
                "model_name": "Baseline 2: OpenAQ + Khí tượng + Vệ tinh",
                **compute_metrics(y[s_idx], oof_kf_b2[s_idx]),
            }
        )

    # --- 2. Đánh giá 5-Fold Spatial CV (GroupKFold theo grid_id) ---
    unique_grids = work["grid_id"].nunique()
    actual_splits = min(n_splits, unique_grids)
    oof_sp_b1 = np.full(len(work), np.nan, dtype="float64")
    oof_sp_b2 = np.full(len(work), np.nan, dtype="float64")

    if actual_splits >= 2:
        gkf = GroupKFold(n_splits=actual_splits)
        groups = work["grid_id"].to_numpy()
        for fold_idx, (tr_idx, val_idx) in enumerate(gkf.split(work, y, groups=groups)):
            m1 = make_xgb_model(100 + fold_idx)
            m1.fit(X_b1.iloc[tr_idx], y[tr_idx])
            oof_sp_b1[val_idx] = np.clip(m1.predict(X_b1.iloc[val_idx]), 0.0, None)

            m2 = make_xgb_model(100 + fold_idx)
            m2.fit(X_b2.iloc[tr_idx], y[tr_idx])
            oof_sp_b2[val_idx] = np.clip(m2.predict(X_b2.iloc[val_idx]), 0.0, None)

        records.append(
            {
                "eval_mode": "Spatial_GroupCV",
                "scope": "ALL",
                "model_code": "Baseline_1_OpenAQ_Meteo",
                "model_name": "Baseline 1: OpenAQ + Khí tượng",
                **compute_metrics(y, oof_sp_b1),
            }
        )
        records.append(
            {
                "eval_mode": "Spatial_GroupCV",
                "scope": "ALL",
                "model_code": "Baseline_2_OpenAQ_Meteo_Sat",
                "model_name": "Baseline 2: OpenAQ + Khí tượng + Vệ tinh",
                **compute_metrics(y, oof_sp_b2),
            }
        )

    oof_df = work[
        ["date_id", "date", "year", "month", "season", "station_id", "station_name", "grid_id", "pm25_mean"]
    ].copy()
    oof_df["pred_cv_b1_meteo"] = oof_kf_b1
    oof_df["pred_cv_b2_meteo_sat"] = oof_kf_b2
    oof_df["pred_spatial_b1_meteo"] = oof_sp_b1
    oof_df["pred_spatial_b2_meteo_sat"] = oof_sp_b2

    fi_rows = []
    for feat, imp in zip(BASELINE1_FEATURES, np.mean(fi_b1_list, axis=0)):
        fi_rows.append({"model_code": "Baseline_1_OpenAQ_Meteo", "feature": feat, "importance": float(imp)})
    for feat, imp in zip(BASELINE2_FEATURES, np.mean(fi_b2_list, axis=0)):
        fi_rows.append({"model_code": "Baseline_2_OpenAQ_Meteo_Sat", "feature": feat, "importance": float(imp)})

    fi_df = (
        pd.DataFrame(fi_rows)
        .sort_values(["model_code", "importance"], ascending=[True, False])
        .reset_index(drop=True)
    )
    return pd.DataFrame(records), oof_df, fi_df


def estimate_full_grid(
    model_b1: XGBRegressor,
    model_b2: XGBRegressor,
    grid_path: Path,
    out_path: Path,
) -> dict[str, float]:
    """
    Ước tính PM2.5 trên toàn bộ 7.577.390 dòng (3.610 ô × 2.099 ngày) của `mart_grid_daily_features.parquet`.
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

    total_rows = 0
    for yr in years:
        chunk = pd.read_parquet(grid_path, filters=[("year", "==", int(yr))])
        pred_b1 = np.clip(model_b1.predict(chunk[BASELINE1_FEATURES].astype("float64")), 0.0, None)
        pred_b2 = np.clip(model_b2.predict(chunk[BASELINE2_FEATURES].astype("float64")), 0.0, None)

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
        total_rows += len(out_chunk)
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


def train_and_evaluate(
    marts_dir: Path | None = None,
    n_splits: int = 5,
    valid_days_only: bool = True,
    estimate_grid: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Đánh giá 2 Baseline và ước tính PM2.5 cho toàn bộ 7,57 triệu dòng lưới Hà Nội."""
    m_dir = marts_dir or (DATA / "marts")
    train_path = m_dir / "mart_station_daily_training.parquet" if marts_dir else MART_STATION_TRAINING
    grid_path = m_dir / "mart_grid_daily_features.parquet" if marts_dir else MART_GRID_DAILY

    df = pd.read_parquet(train_path)
    print(f"[models] Đánh giá 2 Baseline XGBoost trên {len(df):,} dòng (valid_days_only={valid_days_only})...")
    metrics_df, oof_df, fi_df = evaluate_baselines(df, n_splits=n_splits, valid_days_only=valid_days_only)

    # Huấn luyện mô hình cuối trên toàn bộ dữ liệu hợp lệ để kiểm tra Train metrics và ước tính 7.57M ô-ngày
    work = df[df["is_valid_day"] == 1].copy() if (valid_days_only and "is_valid_day" in df.columns) else df.copy()
    work = work[work["pm25_mean"].notna()].reset_index(drop=True)
    y_full = work["pm25_mean"].to_numpy(dtype="float64")

    model_b1 = make_xgb_model(42)
    model_b1.fit(work[BASELINE1_FEATURES].astype("float64"), y_full)
    pred_tr_b1 = np.clip(model_b1.predict(work[BASELINE1_FEATURES].astype("float64")), 0.0, None)

    model_b2 = make_xgb_model(42)
    model_b2.fit(work[BASELINE2_FEATURES].astype("float64"), y_full)
    pred_tr_b2 = np.clip(model_b2.predict(work[BASELINE2_FEATURES].astype("float64")), 0.0, None)

    train_records = pd.DataFrame(
        [
            {
                "eval_mode": "Train_Fit",
                "scope": "ALL",
                "model_code": "Baseline_1_OpenAQ_Meteo",
                "model_name": "Baseline 1: OpenAQ + Khí tượng",
                **compute_metrics(y_full, pred_tr_b1),
            },
            {
                "eval_mode": "Train_Fit",
                "scope": "ALL",
                "model_code": "Baseline_2_OpenAQ_Meteo_Sat",
                "model_name": "Baseline 2: OpenAQ + Khí tượng + Vệ tinh",
                **compute_metrics(y_full, pred_tr_b2),
            },
        ]
    )
    metrics_df = pd.concat([train_records, metrics_df], ignore_index=True)

    write_parquet(metrics_df, m_dir / "model_comparison_metrics.parquet")
    write_parquet(oof_df, m_dir / "oof_station_predictions.parquet")
    write_parquet(fi_df, m_dir / "model_feature_importance.parquet")

    print("\n=== KẾT QUẢ SO SÁNH 2 BASELINE XGBOOST ===")
    for _, row in metrics_df[metrics_df["scope"] == "ALL"].iterrows():
        print(
            f"  [{row['eval_mode']:<15}] {row['model_name']:<42} | "
            f"N={int(row['n_samples']):5d} | RMSE={row['rmse']:6.3f} | "
            f"MAE={row['mae']:6.3f} | R2={row['r2']:6.4f} | MAPE={row['mape_pct']:5.2f}%"
        )

    if estimate_grid and grid_path.exists():
        out_grid_pred = m_dir / "pred_grid_daily_pm25.parquet"
        print(f"\n[models] Bắt đầu ước tính PM2.5 trên tập 7,57 triệu ô-ngày ({grid_path.name})...")
        stats = estimate_full_grid(model_b1, model_b2, grid_path, out_grid_pred)
        print(
            f"[models] Hoàn tất ước tính {stats['total_rows']:,} dòng -> {out_grid_pred.name}\n"
            f"  - Baseline 1 (OpenAQ+Meteo)     : mean={stats['b1_mean']:.2f}, std={stats['b1_std']:.2f}, "
            f"min={stats['b1_min']:.2f}, max={stats['b1_max']:.2f} ug/m3\n"
            f"  - Baseline 2 (OpenAQ+Meteo+Sat) : mean={stats['b2_mean']:.2f}, std={stats['b2_std']:.2f}, "
            f"min={stats['b2_min']:.2f}, max={stats['b2_max']:.2f} ug/m3"
        )

    return metrics_df, oof_df, fi_df


def main() -> None:
    parser = argparse.ArgumentParser(description="So sánh 2 Baseline XGBoost và ước tính PM2.5 cho 7.57M ô-ngày.")
    parser.add_argument("--folds", type=int, default=5, help="Số fold CV (mặc định: 5)")
    parser.add_argument("--all-days", action="store_true", help="Dùng cả ngày có < 18 giờ hợp lệ")
    parser.add_argument("--no-grid-estimate", action="store_true", help="Bỏ qua bước ước tính 7,57 triệu dòng lưới")
    args = parser.parse_args()
    train_and_evaluate(
        n_splits=args.folds,
        valid_days_only=not args.all_days,
        estimate_grid=not args.no_grid_estimate,
    )


if __name__ == "__main__":
    main()
