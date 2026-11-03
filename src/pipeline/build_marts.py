"""Feature Marts phục vụ EDA và huấn luyện mô hình.

1. mart_grid_daily_features.parquet
   - Grain: (grid_id, date_id).
   - Kết hợp dim_grid_1km, dim_date, fct_grid_meteo_daily, fct_grid_satellite_daily.
   - Các cột báo thiếu có hậu tố `_missing`.
   - Tuyệt đối không chứa nhãn PM2.5 (chống rò rỉ nhãn).
2. mart_station_daily_training.parquet
   - Grain: (station_id, date_id) cho các trạm có tọa độ thực nằm trong ranh giới Hà Nội
     (is_boundary = TRUE) và có pm25_mean IS NOT NULL.
   - Join riêng dim_date và dim_grid_1km để thông tin lịch và tọa độ không bao giờ bị NULL
     kể cả khi ngày đó thiếu dữ liệu lưới.
"""
from __future__ import annotations

import duckdb

from src.common import config
from src.common.storage import copy_query


def _miss(col: str) -> str:
    """Biểu thức SQL gắn cờ thiếu (1 nếu NULL, 0 nếu có giá trị)."""
    return f"CAST(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END AS TINYINT)"


def grid_mart_sql(
    dim_grid_path=config.DIM_GRID,
    dim_date_path=config.DIM_DATE,
    fct_meteo_path=config.FCT_GRID_METEO_DAILY,
    fct_sat_path=config.FCT_GRID_SATELLITE_DAILY,
) -> str:
    return f"""
    WITH active_dates AS (
        SELECT date_id FROM '{fct_meteo_path.as_posix()}'
        UNION
        SELECT date_id FROM '{fct_sat_path.as_posix()}'
    ),
    spine AS (
        SELECT
            g.grid_id,
            g.easting_m,
            g.northing_m,
            d.date_id,
            d.date,
            d.year,
            d.month,
            d.day_of_week,
            d.day_of_year,
            d.is_weekend,
            d.season
        FROM '{dim_grid_path.as_posix()}' g
        CROSS JOIN '{dim_date_path.as_posix()}' d
        WHERE d.date_id IN (SELECT date_id FROM active_dates)
    )
    SELECT
        s.grid_id,
        s.date_id,
        s.date,
        s.year,
        s.month,
        s.day_of_week,
        s.day_of_year,
        s.is_weekend,
        s.season,
        s.easting_m,
        s.northing_m,
        m.temp_2m_c,
        {_miss('m.temp_2m_c')}              AS temp_2m_c_missing,
        m.dewpoint_2m_c,
        {_miss('m.dewpoint_2m_c')}          AS dewpoint_2m_c_missing,
        m.rh_pct,
        {_miss('m.rh_pct')}                 AS rh_pct_missing,
        m.precip_mm,
        {_miss('m.precip_mm')}              AS precip_mm_missing,
        m.wind_speed_10m_ms,
        {_miss('m.wind_speed_10m_ms')}      AS wind_speed_10m_ms_missing,
        m.wind_u_10m_ms,
        m.wind_v_10m_ms,
        m.wind_persistence,
        m.wind_dir_10m_deg,
        m.surface_pressure_hpa,
        {_miss('m.surface_pressure_hpa')}   AS surface_pressure_hpa_missing,
        m.blh_mean_m,
        {_miss('m.blh_mean_m')}             AS blh_mean_m_missing,
        m.blh_min_m,
        {_miss('m.blh_min_m')}              AS blh_min_m_missing,
        sat.no2_trop_mol_m2,
        sat.co_mol_m2,
        sat.o3_mol_m2,
        sat.so2_mol_m2,
        sat.aod_047,
        {_miss('sat.aod_047')}              AS aod_047_missing,
        sat.viirs_radiance
    FROM spine s
    LEFT JOIN '{fct_meteo_path.as_posix()}' m USING (grid_id, date_id)
    LEFT JOIN '{fct_sat_path.as_posix()}' sat USING (grid_id, date_id)
    ORDER BY s.grid_id, s.date_id
    """


def station_training_mart_sql(
    fct_station_path=config.FCT_STATION_DAILY,
    dim_station_path=config.DIM_STATION,
    grid_mart_path=config.MART_GRID_DAILY,
    dim_grid_path=config.DIM_GRID,
    dim_date_path=config.DIM_DATE,
) -> str:
    return f"""
    SELECT
        f.station_id,
        st.station_name,
        st.sensor_tier,
        st.is_boundary,
        f.grid_id,
        f.date_id,
        f.pm25_mean,
        f.pm25_valid_hours,
        f.is_valid_day,
        f.pm10_aq,
        f.no2_aq,
        f.so2_aq,
        f.co_aq,
        f.co2_aq,
        f.o3_aq,
        f.openaq_temperature,
        f.openaq_temperature_missing,
        f.openaq_relativehumidity,
        f.openaq_relativehumidity_missing,
        d.date,
        d.year,
        d.month,
        d.day_of_week,
        d.day_of_year,
        d.is_weekend,
        d.season,
        gr.easting_m,
        gr.northing_m,
        g.temp_2m_c,
        {_miss('g.temp_2m_c')}              AS temp_2m_c_missing,
        g.dewpoint_2m_c,
        {_miss('g.dewpoint_2m_c')}          AS dewpoint_2m_c_missing,
        g.rh_pct,
        {_miss('g.rh_pct')}                 AS rh_pct_missing,
        g.precip_mm,
        {_miss('g.precip_mm')}              AS precip_mm_missing,
        g.wind_speed_10m_ms,
        {_miss('g.wind_speed_10m_ms')}      AS wind_speed_10m_ms_missing,
        g.wind_u_10m_ms,
        g.wind_v_10m_ms,
        g.wind_persistence,
        g.wind_dir_10m_deg,
        g.surface_pressure_hpa,
        {_miss('g.surface_pressure_hpa')}   AS surface_pressure_hpa_missing,
        g.blh_mean_m,
        {_miss('g.blh_mean_m')}             AS blh_mean_m_missing,
        g.blh_min_m,
        {_miss('g.blh_min_m')}              AS blh_min_m_missing,
        g.no2_trop_mol_m2,
        g.co_mol_m2,
        g.o3_mol_m2,
        g.so2_mol_m2,
        g.aod_047,
        {_miss('g.aod_047')}                AS aod_047_missing,
        g.viirs_radiance
    FROM '{fct_station_path.as_posix()}' f
    INNER JOIN '{dim_station_path.as_posix()}' st ON f.station_id = st.station_id
    INNER JOIN '{dim_date_path.as_posix()}' d ON f.date_id = d.date_id
    INNER JOIN '{dim_grid_path.as_posix()}' gr ON f.grid_id = gr.grid_id
    LEFT JOIN '{grid_mart_path.as_posix()}' g ON f.grid_id = g.grid_id AND f.date_id = g.date_id
    WHERE f.pm25_mean IS NOT NULL
      AND f.grid_id IS NOT NULL
      AND st.is_boundary = TRUE
    ORDER BY f.station_id, f.date_id
    """


def build_marts() -> None:
    con = duckdb.connect()
    print("[marts]")
    required = [config.DIM_GRID, config.DIM_DATE, config.FCT_GRID_METEO_DAILY, config.FCT_GRID_SATELLITE_DAILY]
    missing = [p.name for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Thiếu bảng nguồn để tạo mart: {missing}")

    copy_query(con, grid_mart_sql(), config.MART_GRID_DAILY)
    if config.FCT_STATION_DAILY.exists() and config.DIM_STATION.exists():
        copy_query(con, station_training_mart_sql(), config.MART_STATION_TRAINING)


if __name__ == "__main__":
    build_marts()
