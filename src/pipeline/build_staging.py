"""Staging: làm sạch từng nguồn raw, chuẩn hóa kiểu/đơn vị/thời gian, gắn cờ QC.

  stg_openaq_hourly    sensor × giờ, có cờ qc_flag (0 = hợp lệ, 1 = không hợp lệ / ngoài ngưỡng)
  stg_meteo_daily      ô × ngày, đơn vị chuẩn (°C, hPa, mm, m/s)
  stg_satellite_daily  ô × ngày, S5P + AOD đã nhân hệ số 0,001
  stg_viirs_monthly    ô × tháng
"""
from __future__ import annotations

import duckdb

from src.common import config
from src.common.storage import copy_query, glob_sql
from src.ingest.fetch_openaq import load_sensors

# Ngưỡng hợp lệ vật lý theo tham số; trong ngưỡng -> qc_flag = 0 (hợp lệ), ngoài ngưỡng -> qc_flag = 1 (không hợp lệ)
VALID_RANGE = {
    "pm25": (0.0, 1000.0),
    "pm10": (0.0, 2000.0),
    "no2": (0.0, 2000.0),
    "so2": (0.0, 2000.0),
    "co": (0.0, 100000.0),
    "co2": (200.0, 5000.0),
    "o3": (0.0, 1000.0),
    "temperature": (-10.0, 50.0),
    "relativehumidity": (0.0, 100.0),
}


def openaq_hourly_sql(raw_expr: str) -> str:
    ranges = " ".join(
        f"WHEN '{p}' THEN value BETWEEN {lo} AND {hi}"
        for p, (lo, hi) in VALID_RANGE.items()
    )
    return f"""
    WITH raw AS (
        SELECT
            CAST(h.sensor_id AS BIGINT) AS sensor_id,
            s.station_id,
            s.parameter,
            s.units,
            CAST(h.datetime_from_utc AS TIMESTAMPTZ) AT TIME ZONE 'UTC' AS datetime_utc,
            CAST(h.value AS DOUBLE) AS value,
            CAST(h.observed_count AS INTEGER) AS observed_count
        FROM {raw_expr} h
        JOIN sensors s USING (sensor_id)
        WHERE h.datetime_from_utc IS NOT NULL
        QUALIFY row_number() OVER (
            PARTITION BY h.sensor_id, h.datetime_from_utc
            ORDER BY h.datetime_to_utc DESC NULLS LAST
        ) = 1
    )
    SELECT
        station_id,
        sensor_id,
        parameter,
        units,
        datetime_utc,
        datetime_utc + INTERVAL {config.UTC_OFFSET_HOURS} HOUR AS datetime_local,
        CAST(strftime(datetime_utc + INTERVAL {config.UTC_OFFSET_HOURS} HOUR, '%Y%m%d') AS INTEGER) AS date_id,
        CAST(extract('hour' FROM datetime_utc + INTERVAL {config.UTC_OFFSET_HOURS} HOUR) AS TINYINT) AS hour_local,
        value,
        observed_count,
        CAST(
            CASE
                WHEN value IS NULL OR isnan(value) OR NOT (CASE parameter {ranges} ELSE FALSE END) THEN 1
                ELSE 0
            END AS TINYINT
        ) AS qc_flag
    FROM raw
    ORDER BY station_id, parameter, sensor_id, datetime_utc
    """


METEO_SQL = """
    SELECT
        grid_id,
        CAST(strftime(CAST(date AS DATE), '%Y%m%d') AS INTEGER) AS date_id,
        CAST(date AS DATE)                                      AS date,
        CAST(t2m_k - 273.15 AS DOUBLE)                          AS temp_2m_c,
        CAST(d2m_k - 273.15 AS DOUBLE)                          AS dewpoint_2m_c,
        CAST(rh_pct AS DOUBLE)                                  AS rh_pct,
        CAST(tp_m * 1000.0 AS DOUBLE)                           AS precip_mm,
        CAST(ws10_ms AS DOUBLE)                                 AS wind_speed_10m_ms,
        CAST(u10_ms AS DOUBLE)                                  AS wind_u_10m_ms,
        CAST(v10_ms AS DOUBLE)                                  AS wind_v_10m_ms,
        CAST(
            sqrt(u10_ms * u10_ms + v10_ms * v10_ms) / nullif(ws10_ms, 0)
            AS DOUBLE
        )                                                       AS wind_persistence,
        CAST(
            (degrees(atan2(-u10_ms, -v10_ms)) + 360.0) % 360.0
            AS DOUBLE
        )                                                       AS wind_dir_10m_deg,
        CAST(sp_pa / 100.0 AS DOUBLE)                           AS surface_pressure_hpa,
        CAST(blh_mean_m AS DOUBLE)                              AS blh_mean_m,
        CAST(blh_min_m AS DOUBLE)                               AS blh_min_m,
        CAST(era5_land_hours AS SMALLINT)                       AS era5_land_hours
    FROM {source}
    QUALIFY row_number() OVER (PARTITION BY grid_id, date ORDER BY era5_land_hours DESC NULLS LAST) = 1
    ORDER BY grid_id, date_id
"""


SATELLITE_SQL = """
    SELECT
        grid_id,
        CAST(strftime(CAST(date AS DATE), '%Y%m%d') AS INTEGER) AS date_id,
        CAST(date AS DATE)                                      AS date,
        CAST(no2_trop AS DOUBLE)                                AS no2_trop_mol_m2,
        CAST(no2_trop_n AS SMALLINT)                            AS no2_n,
        CAST(co AS DOUBLE)                                      AS co_mol_m2,
        CAST(co_n AS SMALLINT)                                  AS co_n,
        CAST(o3 AS DOUBLE)                                      AS o3_mol_m2,
        CAST(o3_n AS SMALLINT)                                  AS o3_n,
        CAST(so2 AS DOUBLE)                                     AS so2_mol_m2,
        CAST(so2_n AS SMALLINT)                                 AS so2_n,
        CAST(aod047 * 0.001 AS DOUBLE)                          AS aod_047,
        CAST(aod047_n AS SMALLINT)                              AS aod_n
    FROM {source}
    QUALIFY row_number() OVER (PARTITION BY grid_id, date ORDER BY aod047_n DESC NULLS LAST) = 1
    ORDER BY grid_id, date_id
"""


VIIRS_SQL = """
    SELECT
        grid_id,
        CAST(strftime(CAST(month AS DATE), '%Y%m') AS INTEGER) AS month_id,
        CAST(avg_rad AS DOUBLE)                                AS viirs_radiance,
        CAST(cf_cvg AS SMALLINT)                               AS viirs_cloud_free_nights
    FROM {source}
    QUALIFY row_number() OVER (PARTITION BY grid_id, month ORDER BY cf_cvg DESC NULLS LAST) = 1
    ORDER BY grid_id, month_id
"""


def build_staging() -> None:
    con = duckdb.connect()
    print("[staging]")
    if any(config.RAW_OPENAQ_HOURS.glob("*.parquet")):
        con.register("sensors", load_sensors())
        copy_query(con, openaq_hourly_sql(glob_sql(config.RAW_OPENAQ_HOURS)), config.STG_OPENAQ_HOURLY)
    else:
        print("  (bỏ qua stg_openaq_hourly: chưa có file trong data/raw/openaq/hours)")

    if any(config.RAW_METEO.glob("*.parquet")):
        copy_query(con, METEO_SQL.format(source=glob_sql(config.RAW_METEO)), config.STG_METEO_DAILY)
    else:
        print("  (bỏ qua stg_meteo_daily: chưa có file trong data/raw/meteo)")

    if any(config.RAW_SATELLITE.glob("*.parquet")):
        copy_query(con, SATELLITE_SQL.format(source=glob_sql(config.RAW_SATELLITE)), config.STG_SATELLITE_DAILY)
    else:
        print("  (bỏ qua stg_satellite_daily: chưa có file trong data/raw/satellite)")

    if any(config.RAW_VIIRS.glob("*.parquet")):
        copy_query(con, VIIRS_SQL.format(source=glob_sql(config.RAW_VIIRS)), config.STG_VIIRS_MONTHLY)
    else:
        print("  (bỏ qua stg_viirs_monthly: chưa có file trong data/raw/viirs)")


if __name__ == "__main__":
    build_staging()
