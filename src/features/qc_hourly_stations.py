"""
src/features/qc_hourly_stations.py
Làm sạch chuỗi giờ trạm mặt đất, chuẩn hóa múi giờ UTC+7 và gán cờ QC phân tầng.
Đầu ra: data/staging/stg_ground_truth_hourly.parquet (Giữ nguyên 100% bản ghi giờ).
"""
from __future__ import annotations

import glob

import duckdb
import numpy as np
import polars as pl

from src.common.io_parquet import atomic_write_parquet


def detect_hampel_outliers(series: np.ndarray, window_size: int = 7, n_sigmas: float = 3.0) -> np.ndarray:
    """
    Bộ lọc ngoại lai Hampel Filter:
    Tính Median và MAD (Median Absolute Deviation) trong cửa sổ trượt window_size giờ.
    Bản ghi lệch > n_sigmas * 1.4826 * MAD sẽ bị gán cờ ngoại lai.
    """
    n = len(series)
    outliers = np.zeros(n, dtype=np.int32)
    k = window_size // 2

    for i in range(n):
        start = max(0, i - k)
        end = min(n, i + k + 1)
        sub = series[start:end]
        sub_valid = sub[~np.isnan(sub)]
        if len(sub_valid) < 3:
            continue

        med = np.median(sub_valid)
        mad = np.median(np.abs(sub_valid - med))
        threshold = n_sigmas * 1.4826 * mad
        if np.abs(series[i] - med) > threshold and mad > 1.0:
            outliers[i] = 1

    return outliers


def process_staging_hourly():
    raw_pattern = "data/raw/ground_truth/source=openaq/**/*.parquet"
    raw_files = glob.glob(raw_pattern, recursive=True)
    if not raw_files:
        raise FileNotFoundError(f"No raw files found at {raw_pattern}. Please run `python run.py ingest` first!")

    target_staging = "data/staging/stg_ground_truth_hourly.parquet"
    print(f"\n[STAGING] Reading {len(raw_files)} raw data partition(s)...")

    # Dùng DuckDB hợp nhất và deduplicate theo bản ghi ingested_at mới nhất
    con = duckdb.connect()
    sql_pattern = raw_pattern.replace("\\", "/")
    query = f"""
    WITH ranked AS (
        SELECT *,
            ROW_NUMBER() OVER(
                PARTITION BY station_id, datetime_utc 
                ORDER BY ingested_at DESC
            ) as rn
        FROM read_parquet('{sql_pattern}')
    )
    SELECT 
        station_id,
        grid_id,
        datetime_utc,
        datetime_local,
        CAST(pm25_ug_m3 AS DOUBLE) AS pm25,
        sensor_tier,
        station_microenv,
        _row_hash
    FROM ranked
    WHERE rn = 1
    ORDER BY station_id, datetime_utc
    """
    df_raw = con.sql(query).pl()
    print(f"[STAGING] Loaded {len(df_raw)} unique hourly records.")

    # Gán cờ QC phân tầng
    processed_dfs = []
    for station_id in df_raw["station_id"].unique().to_list():
        st_df = df_raw.filter(pl.col("station_id") == station_id).sort("datetime_utc")
        pm25_vals = st_df["pm25"].to_numpy()

        qc_flags = np.zeros(len(pm25_vals), dtype=np.int32)
        # 1. Âm
        qc_flags[pm25_vals < 0] = 1
        # 2. Vượt ngưỡng vật lý
        qc_flags[pm25_vals > 1000] = 2

        # 3. Flatline (kẹt số >= 6 giờ liên tiếp)
        is_flatline = np.zeros(len(pm25_vals), dtype=np.int32)
        for i in range(5, len(pm25_vals)):
            window = pm25_vals[i - 5 : i + 1]
            if len(set(window)) == 1 and not np.isnan(window[0]):
                is_flatline[i - 5 : i + 1] = 1
        qc_flags[is_flatline == 1] = 3

        # 4. Ngoại lai Hampel
        hampel_flags = detect_hampel_outliers(pm25_vals, window_size=7, n_sigmas=3.0)

        st_df = st_df.with_columns([
            pl.Series("qc_flag", qc_flags),
            pl.Series("is_hampel_outlier", hampel_flags)
        ])
        processed_dfs.append(st_df)

    final_stg = pl.concat(processed_dfs)

    # Xuất file Staging nguyên tử
    atomic_write_parquet(final_stg, target_staging)
    sql_target = target_staging.replace("\\", "/")
    flagged = con.sql(f"SELECT COUNT(*) FROM '{sql_target}' WHERE qc_flag > 0").fetchall()[0][0]
    clean = len(final_stg) - flagged
    print(f"[STAGING] Saved output to: {target_staging}")
    print(f"  -> Total hourly records: {len(final_stg)}")
    print(f"  -> Clean records (qc_flag = 0): {clean}")
    print(f"  -> Flagged records (qc_flag > 0): {flagged}")


if __name__ == "__main__":
    process_staging_hourly()
