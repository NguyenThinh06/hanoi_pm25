"""
src/features/build_ground_truth_daily.py
Tổng hợp chuỗi giờ thành trung bình ngày, áp dụng quy tắc lọc nghiêm ngặt >= 18h hợp lệ,
và đóng gói Star Schema:
  1. data/staging/stg_ground_truth_daily.parquet (Tất cả các ngày đo)
  2. data/core/dim_station.parquet (Bảng chiều trạm quan trắc + 1 dòng station_unknown)
  3. data/core/fct_ground_truth_daily.parquet (Bảng Fact ngày trạm đạt chuẩn >= 18h)
"""
from __future__ import annotations

import json
import os

import duckdb
import polars as pl

from src.common.io_parquet import atomic_write_parquet


def build_ground_truth_daily():
    stg_hourly_path = "data/staging/stg_ground_truth_hourly.parquet"
    registry_path = "data/reference/station_registry.json"

    if not os.path.exists(stg_hourly_path):
        raise FileNotFoundError(f"Chua tim thay file {stg_hourly_path}. Hay chay `python run.py staging` truoc!")

    con = duckdb.connect()
    sql_hourly = stg_hourly_path.replace("\\", "/")

    print("\n[CORE] Processing daily aggregation with strict >= 18h validation rule...")

    # 1. Gom trung bình ngày: chỉ lấy bản ghi qc_flag = 0 để tính toán
    query_daily = f"""
    WITH hourly_clean AS (
        SELECT 
            station_id,
            grid_id,
            sensor_tier,
            CAST(STRPTIME(SUBSTRING(datetime_local, 1, 10), '%Y-%m-%d') AS DATE) AS date_actual,
            CAST(STRFTIME(STRPTIME(SUBSTRING(datetime_local, 1, 10), '%Y-%m-%d'), '%Y%m%d') AS INT32) AS date_id,
            pm25,
            qc_flag
        FROM read_parquet('{sql_hourly}')
    ),
    aggregated AS (
        SELECT 
            station_id,
            grid_id,
            sensor_tier,
            date_actual,
            date_id,
            COUNT(*) AS total_hours_count,
            COUNT(*) FILTER (WHERE qc_flag = 0) AS valid_hours_count,
            ROUND(AVG(pm25) FILTER (WHERE qc_flag = 0), 2) AS pm25_raw_mean,
            -- Hieu chuan Kohler: Voi Tier 1 (FEM reference co say kho mau), pm25_calibrated_mean = pm25_raw_mean
            ROUND(AVG(pm25) FILTER (WHERE qc_flag = 0), 2) AS pm25_calibrated_mean,
            ROUND(STDDEV(pm25) FILTER (WHERE qc_flag = 0), 2) AS pm25_daily_std,
            ROUND(MIN(pm25) FILTER (WHERE qc_flag = 0), 2) AS pm25_daily_min,
            ROUND(MAX(pm25) FILTER (WHERE qc_flag = 0), 2) AS pm25_daily_max
        FROM hourly_clean
        GROUP BY station_id, grid_id, sensor_tier, date_actual, date_id
    )
    SELECT *,
        CASE WHEN valid_hours_count >= 18 THEN 1 ELSE 0 END AS is_valid_day
    FROM aggregated
    ORDER BY station_id, date_id
    """
    df_daily = con.sql(query_daily).pl()

    # Xuất file Staging Daily (chứa tất cả các ngày đo)
    stg_daily_path = "data/staging/stg_ground_truth_daily.parquet"
    atomic_write_parquet(df_daily, stg_daily_path)
    print(f"[STAGING] Saved {len(df_daily)} station-days to: {stg_daily_path}")

    # 2. Xuất bảng Fact Core: fct_ground_truth_daily.parquet (chỉ giữ ngày hợp lệ >= 18h)
    fct_df = df_daily.filter(pl.col("is_valid_day") == 1).select([
        "station_id",
        "date_id",
        "grid_id",
        "valid_hours_count",
        "pm25_raw_mean",
        "pm25_calibrated_mean",
        "pm25_daily_std",
        "pm25_daily_min",
        "pm25_daily_max"
    ])
    fct_path = "data/core/fct_ground_truth_daily.parquet"
    atomic_write_parquet(fct_df, fct_path)
    print(f"[CORE] Saved {len(fct_df)} valid station-days (>= 18h) to: {fct_path}")

    # 3. Xuất bảng Chiều Core: dim_station.parquet (+ 1 dòng ngoại lệ station_unknown)
    with open(registry_path, "r", encoding="utf-8") as f:
        stations_meta = json.load(f)

    # Thêm dòng ngoại lệ
    stations_meta.append({
        "station_id": "station_unknown",
        "station_name": "Unknown Station",
        "provider": "Unknown",
        "sensor_tier": "Unknown",
        "station_microenv_type": "Unknown",
        "grid_id": "grid_unknown",
        "lon_wgs84": None,
        "lat_wgs84": None,
        "easting_m": None,
        "northing_m": None,
        "pm25_sensor_id": None,
        "is_active": False
    })

    dim_station_df = pl.DataFrame(stations_meta).select([
        "station_id",
        "station_name",
        "provider",
        "sensor_tier",
        "station_microenv_type",
        "grid_id",
        "lon_wgs84",
        "lat_wgs84",
        "easting_m",
        "northing_m",
        "is_active"
    ])
    dim_station_path = "data/core/dim_station.parquet"
    atomic_write_parquet(dim_station_df, dim_station_path)
    print(f"[CORE] Saved {len(dim_station_df)} stations to: {dim_station_path} (including unknown)")


if __name__ == "__main__":
    build_ground_truth_daily()
