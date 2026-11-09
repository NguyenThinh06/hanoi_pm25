"""Core Facts: tổng hợp bảng sự kiện cấp ngày chuẩn Star Schema.

  fct_station_daily         (station_id, date_id): PM2.5, các khí trạm (*_aq) và khí tượng trạm (openaq_* + *_missing)
  fct_grid_meteo_daily      (grid_id, date_id): khí tượng ERA5-Land + BLH ERA5 trên lưới Hà Nội kèm cờ *_missing
  fct_grid_satellite_daily  (grid_id, date_id): S5P (NO2, CO, O3, SO2), MODIS AOD (kèm aod_047_missing), VIIRS
"""
from __future__ import annotations

import duckdb

from src.common import config
from src.common.storage import copy_query


def station_daily_sql(
    stg_hourly_path=config.STG_OPENAQ_HOURLY,
    dim_station_path=config.DIM_STATION,
    dim_date_path=config.DIM_DATE,
) -> str:
    """
    1. Lọc các bản ghi giờ hợp lệ (qc_flag = 0) và hợp nhất theo (station_id, parameter, date_id, hour_local)
       để mỗi giờ hợp lệ trong ngày có đúng 1 giá trị đại diện.
    2. Tính nhãn PM2.5 cấp ngày (pm25_mean) bằng trung bình cộng trên đúng số giờ hợp lệ trong ngày
       (sum(hourly_val) / count(hourly_val)).
    3. Các chất ô nhiễm khác từ trạm OpenAQ mang hậu tố `_aq`
       (`pm10_aq`, `no2_aq`, `so2_aq`, `co_aq`, `co2_aq`, `o3_aq`).
    4. Các biến khí tượng từ OpenAQ mang tiền tố `openaq_` kèm cờ thiếu hậu tố `_missing`.
    """
    return f"""
    WITH valid_station_hour AS (
        SELECT
            station_id,
            parameter,
            date_id,
            hour_local,
            avg(value) AS hourly_val
        FROM '{stg_hourly_path.as_posix()}'
        WHERE qc_flag = 0
          AND value IS NOT NULL
          AND NOT isnan(value)
          AND date_id IN (SELECT date_id FROM '{dim_date_path.as_posix()}')
        GROUP BY station_id, parameter, date_id, hour_local
    ),
    daily AS (
        SELECT
            station_id,
            date_id,
            CAST(count(hourly_val) FILTER (WHERE parameter = 'pm25') AS SMALLINT) AS pm25_valid_hours,
            CAST(
                CASE WHEN count(hourly_val) FILTER (WHERE parameter = 'pm25') >= {config.MIN_VALID_HOURS}
                     THEN 1 ELSE 0 END
                AS TINYINT
            ) AS is_valid_day,
            round(
                sum(hourly_val) FILTER (WHERE parameter = 'pm25')
                / nullif(count(hourly_val) FILTER (WHERE parameter = 'pm25'), 0),
                2
            )                                                                       AS pm25_mean,
            round(stddev_samp(hourly_val) FILTER (WHERE parameter = 'pm25'), 2)     AS pm25_std,
            round(min(hourly_val) FILTER (WHERE parameter = 'pm25'), 2)             AS pm25_min,
            round(max(hourly_val) FILTER (WHERE parameter = 'pm25'), 2)             AS pm25_max,
            round(avg(hourly_val) FILTER (WHERE parameter = 'pm10'), 2)             AS pm10_aq,
            round(avg(hourly_val) FILTER (WHERE parameter = 'no2'), 2)              AS no2_aq,
            round(avg(hourly_val) FILTER (WHERE parameter = 'so2'), 2)              AS so2_aq,
            round(avg(hourly_val) FILTER (WHERE parameter = 'co'), 2)               AS co_aq,
            round(avg(hourly_val) FILTER (WHERE parameter = 'co2'), 2)              AS co2_aq,
            round(avg(hourly_val) FILTER (WHERE parameter = 'o3'), 2)               AS o3_aq,
            round(avg(hourly_val) FILTER (WHERE parameter = 'temperature'), 2)      AS openaq_temperature,
            round(avg(hourly_val) FILTER (WHERE parameter = 'relativehumidity'), 2) AS openaq_relativehumidity
        FROM valid_station_hour
        GROUP BY station_id, date_id
    )
    SELECT
        d.station_id,
        st.grid_id,
        d.date_id,
        d.pm25_valid_hours,
        d.is_valid_day,
        d.pm25_mean,
        d.pm25_std,
        d.pm25_min,
        d.pm25_max,
        d.pm10_aq,
        d.no2_aq,
        d.so2_aq,
        d.co_aq,
        d.co2_aq,
        d.o3_aq,
        d.openaq_temperature,
        CAST(
            CASE WHEN d.openaq_temperature IS NULL THEN 1 ELSE 0 END AS TINYINT
        ) AS openaq_temperature_missing,
        d.openaq_relativehumidity,
        CAST(
            CASE WHEN d.openaq_relativehumidity IS NULL THEN 1 ELSE 0 END AS TINYINT
        ) AS openaq_relativehumidity_missing
    FROM daily d
    LEFT JOIN '{dim_station_path.as_posix()}' st USING (station_id)
    ORDER BY d.station_id, d.date_id
    """


def grid_meteo_daily_sql(
    stg_meteo_path=config.STG_METEO_DAILY,
    dim_grid_path=config.DIM_GRID,
    dim_date_path=config.DIM_DATE,
) -> str:
    return f"""
    SELECT
        m.grid_id,
        m.date_id,
        m.temp_2m_c,
        CAST(CASE WHEN m.temp_2m_c IS NULL THEN 1 ELSE 0 END AS TINYINT)            AS temp_2m_c_missing,
        m.dewpoint_2m_c,
        CAST(CASE WHEN m.dewpoint_2m_c IS NULL THEN 1 ELSE 0 END AS TINYINT)        AS dewpoint_2m_c_missing,
        m.rh_pct,
        CAST(CASE WHEN m.rh_pct IS NULL THEN 1 ELSE 0 END AS TINYINT)               AS rh_pct_missing,
        m.precip_mm,
        CAST(CASE WHEN m.precip_mm IS NULL THEN 1 ELSE 0 END AS TINYINT)            AS precip_mm_missing,
        m.wind_speed_10m_ms,
        CAST(CASE WHEN m.wind_speed_10m_ms IS NULL THEN 1 ELSE 0 END AS TINYINT)    AS wind_speed_10m_ms_missing,
        m.wind_u_10m_ms,
        m.wind_v_10m_ms,
        m.wind_persistence,
        m.wind_dir_10m_deg,
        m.surface_pressure_hpa,
        CAST(CASE WHEN m.surface_pressure_hpa IS NULL THEN 1 ELSE 0 END AS TINYINT) AS surface_pressure_hpa_missing,
        m.blh_mean_m,
        CAST(CASE WHEN m.blh_mean_m IS NULL THEN 1 ELSE 0 END AS TINYINT)           AS blh_mean_m_missing,
        m.blh_min_m,
        CAST(CASE WHEN m.blh_min_m IS NULL THEN 1 ELSE 0 END AS TINYINT)            AS blh_min_m_missing,
        m.era5_land_hours
    FROM '{stg_meteo_path.as_posix()}' m
    INNER JOIN '{dim_grid_path.as_posix()}' g USING (grid_id)
    INNER JOIN '{dim_date_path.as_posix()}' d USING (date_id)
    ORDER BY m.grid_id, m.date_id
    """


def grid_satellite_daily_sql(
    stg_sat_path=config.STG_SATELLITE_DAILY,
    stg_viirs_path=config.STG_VIIRS_MONTHLY,
    dim_grid_path=config.DIM_GRID,
    dim_date_path=config.DIM_DATE,
) -> str:
    viirs_join = (
        f"LEFT JOIN '{stg_viirs_path.as_posix()}' v ON s.grid_id = v.grid_id AND (s.date_id // 100) = v.month_id"
        if stg_viirs_path.exists()
        else ""
    )
    viirs_cols = (
        "v.viirs_radiance, v.viirs_cloud_free_nights"
        if stg_viirs_path.exists()
        else "CAST(NULL AS DOUBLE) AS viirs_radiance, CAST(NULL AS SMALLINT) AS viirs_cloud_free_nights"
    )
    return f"""
    SELECT
        s.grid_id,
        s.date_id,
        s.no2_trop_mol_m2,
        s.no2_n,
        s.co_mol_m2,
        s.co_n,
        s.o3_mol_m2,
        s.o3_n,
        s.so2_mol_m2,
        s.so2_n,
        s.aod_047,
        s.aod_n,
        CAST(CASE WHEN s.aod_047 IS NULL THEN 1 ELSE 0 END AS TINYINT) AS aod_047_missing,
        {viirs_cols}
    FROM '{stg_sat_path.as_posix()}' s
    INNER JOIN '{dim_grid_path.as_posix()}' g USING (grid_id)
    INNER JOIN '{dim_date_path.as_posix()}' d USING (date_id)
    {viirs_join}
    ORDER BY s.grid_id, s.date_id
    """


def build_facts() -> None:
    con = duckdb.connect()
    print("[facts]")
    if config.STG_OPENAQ_HOURLY.exists() and config.DIM_STATION.exists():
        copy_query(con, station_daily_sql(), config.FCT_STATION_DAILY)
    else:
        print("  (bỏ qua fct_station_daily: thiếu stg_openaq_hourly hoặc dim_station)")

    if config.STG_METEO_DAILY.exists():
        copy_query(con, grid_meteo_daily_sql(), config.FCT_GRID_METEO_DAILY)
    else:
        print("  (bỏ qua fct_grid_meteo_daily: thiếu stg_meteo_daily)")

    if config.STG_SATELLITE_DAILY.exists():
        copy_query(con, grid_satellite_daily_sql(), config.FCT_GRID_SATELLITE_DAILY)
    else:
        print("  (bỏ qua fct_grid_satellite_daily: thiếu stg_satellite_daily)")


if __name__ == "__main__":
    build_facts()
