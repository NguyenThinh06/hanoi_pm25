"""
src/features/process_meteo_daily.py
Chuẩn hóa chuỗi giờ khí tượng, tính toán các đặc trưng vật lý và ánh xạ sang lưới 1km Hà Nội:
  1. Chuyển đổi múi giờ UTC -> Asia/Ho_Chi_Minh (UTC+7).
  2. Khử tích lũy lượng mưa (hourly de-accumulation) theo đúng quy tắc chu kỳ dự báo ERA5-Land.
  3. Tính các đặc trưng khí quyển:
     - temp_2m_mean_c: Nhiệt độ 2m trung bình ngày (°C)
     - dewpoint_2m_mean_c: Điểm sương 2m trung bình ngày (°C)
     - rh_mean_pct: Độ ẩm tương đối tính theo giờ từ T và Td (Magnus-Tetens) rồi trung bình ngày (%)
     - precip_daily_mm: Tổng lượng mưa ngày đã khử tích lũy (mm)
     - wind_speed_scalar_ms: Tốc độ gió tức thời trung bình ngày (m/s)
     - wind_persistence: Tỷ số bền vững hướng gió P in [0.0, 1.0]
     - surface_pressure_hpa: Khí áp bề mặt trung bình ngày (hPa)
     - blh_mean_m: Chiều cao lớp biên trung bình ngày (m)
     - blh_min_m: Chiều cao lớp biên nhỏ nhất trong ngày (m)
  4. Quản lý chất lượng & số giờ hợp lệ:
     - Ghi nhận valid_hours_count và cờ is_valid_day (>= 18h)
     - Chia đúng cho số giờ hợp lệ N, tuyệt đối không chia mặc định cho 24 khi thiếu giờ
  5. Xuất bản Staging: data/staging/stg_meteo_daily.parquet (Grain: pixel-ngày)
  6. Ánh xạ không gian sang lưới 1km Hà Nội:
     - Đọc dim_grid_1km và dim_date từ TV1
     - Hỗ trợ cả 2 phương pháp: Nearest Neighbor ('nearest', mặc định) và Bilinear Interpolation ('bilinear')
     - Chuyển đổi hệ tọa độ EPSG:3405 -> EPSG:4326 bằng pyproj
     - Zero-Drop & Anti-Fanout: Bảo đảm khung xương phân tích đầy đủ, khóa chính (grid_id, date_id) duy nhất 100%
     - Tuyệt đối không chứa cột PM2.5 hay nhãn học máy
"""
from __future__ import annotations

import argparse
import io
import math
import os
import sys
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
import pyproj

from src.common.io_parquet import atomic_write_parquet

# Bảo vệ Windows console khỏi UnicodeEncodeError
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, io.UnsupportedOperation):
        pass

DEFAULT_RAW_METEO_DIR = "data/raw/meteo"
DEFAULT_DIM_GRID_PATH = "data/core/dim_grid_1km.parquet"
DEFAULT_DIM_DATE_PATH = "data/core/dim_date.parquet"
DEFAULT_STG_METEO_PATH = "data/staging/stg_meteo_daily.parquet"
DEFAULT_FCT_METEO_PATH = "data/core/fct_grid_meteo_daily.parquet"

KELVIN_TO_CELSIUS_OFFSET = 273.15
WIND_EPSILON = 1e-4  # Ngưỡng epsilon xử lý gió lặng


# ==============================================================================
# 1. CÔNG THỨC VẬT LÝ KHÍ TƯỢNG (PHYSICAL & ATMOSPHERIC FORMULAS)
# ==============================================================================

def kelvin_to_celsius(k: float | None) -> float | None:
    """Chuyển nhiệt độ từ Kelvin sang độ C: T_C = T_K - 273.15."""
    if k is None or not math.isfinite(k):
        return None
    return k - KELVIN_TO_CELSIUS_OFFSET


def pa_to_hpa(pa: float | None) -> float | None:
    """Chuyển áp suất từ Pascal sang hectoPascal (hPa): P_hPa = P_Pa / 100.0."""
    if pa is None or not math.isfinite(pa):
        return None
    return pa / 100.0


def compute_magnus_tetens_rh(t_c: float | None, td_c: float | None) -> float | None:
    """
    Tính độ ẩm tương đối (%) theo công thức Magnus-Tetens (Alduchov & Eskridge 1996):
      RH = 100.0 * exp((17.625 * Td) / (243.04 + Td)) / exp((17.625 * T) / (243.04 + T))
    Giới hạn vật lý: RH in [0.0, 100.0]%.
    Nếu Td > T (bất thường nhẹ do làm tròn hoặc sai số mô hình), kẹp tại 100.0%.
    """
    if t_c is None or td_c is None:
        return None
    if not (math.isfinite(t_c) and math.isfinite(td_c)):
        return None

    # Áp suất hơi nước bão hòa e_s và áp suất hơi nước thực tế e
    num = 17.625 * td_c
    den = 243.04 + td_c
    if den == 0.0:
        return None
    vp = math.exp(num / den)

    num_s = 17.625 * t_c
    den_s = 243.04 + t_c
    if den_s == 0.0:
        return None
    svp = math.exp(num_s / den_s)

    if svp <= 0.0:
        return None

    rh = 100.0 * (vp / svp)
    return max(0.0, min(100.0, rh))


def compute_scalar_wind_speed(u: float, v: float) -> float:
    """Tính tốc độ gió tức thời theo giờ w = sqrt(u^2 + v^2)."""
    return math.sqrt(u * u + v * v)


def compute_wind_persistence(
    mean_u: float,
    mean_v: float,
    mean_scalar_speed: float,
    epsilon: float = WIND_EPSILON,
) -> float:
    """
    Tính độ bền vững hướng gió P = V_vector / max(V_scalar, epsilon).
    V_vector = sqrt(mean(u)^2 + mean(v)^2).
    Theo bất đẳng thức tam giác, V_vector <= V_scalar, nên P in [0.0, 1.0].
    Khi gió lặng (mean_scalar_speed < epsilon), quy ước P = 0.0.
    """
    v_vector = math.sqrt(mean_u * mean_u + mean_v * mean_v)
    if mean_scalar_speed < epsilon:
        return 0.0
    ratio = v_vector / mean_scalar_speed
    return max(0.0, min(1.0, ratio))


# ==============================================================================
# 2. KHỬ TÍCH LŨY LƯỢNG MƯA (HOURLY DE-ACCUMULATION)
# ==============================================================================

def deaccumulate_era5_land_precip(df_tp: pl.DataFrame) -> pl.DataFrame:
    """
    Khử tích lũy biến total_precipitation (tp) của ERA5-Land theo chuỗi thời gian UTC:
      - Đơn vị gốc của tp: mét (m). Nhân 1000.0 để quy đổi sang milimét (mm).
      - Quy tắc tích lũy ERA5-Land: Tích lũy từ 00:00 UTC của ngày dự báo.
        + Bước 01:00 UTC: r = tp_1 * 1000.0 (lượng mưa từ 00:00 đến 01:00 UTC).
        + Bước h in [02:00, 23:00] UTC: Delta = (tp_h - tp_{h-1}) * 1000.0.
        + Bước 00:00 UTC của ngày tiếp theo: Là bước 24h của ngày trước: Delta = (tp_00 - tp_23) * 1000.0.
      - Xử lý bất thường:
        + Nếu Delta < 0 và Delta >= -1e-4: Sai số số học dấu phẩy động -> kẹp về 0.0.
        + Nếu Delta < -1e-4: Cảnh báo bất thường nguồn dữ liệu, kẹp về 0.0 và ghi nhận cờ.
      - Đầu ra: DataFrame chứa [latitude, longitude, datetime_utc, precip_h_mm].
    """
    if len(df_tp) == 0:
        return pl.DataFrame(schema={
            "latitude": pl.Float64,
            "longitude": pl.Float64,
            "datetime_utc": pl.Utf8,
            "precip_h_mm": pl.Float64,
        })

    # Đảm bảo sắp xếp đúng thứ tự thời gian cho từng pixel
    df_tp_sorted = df_tp.sort(["latitude", "longitude", "datetime_utc"])

    # Xử lý khử tích lũy theo từng nhóm pixel
    # Sử dụng DuckDB SQL cho logic de-accumulation rõ ràng, minh bạch và hiệu năng cao
    con = duckdb.connect()
    con.register("raw_tp", df_tp_sorted.to_arrow())

    query = """
    WITH parsed AS (
        SELECT 
            latitude,
            longitude,
            datetime_utc,
            CAST(SUBSTRING(datetime_utc, 1, 10) AS DATE) AS date_utc,
            CAST(SUBSTRING(datetime_utc, 12, 2) AS INT32) AS hour_utc,
            value AS tp_m,
            LAG(value) OVER (
                PARTITION BY latitude, longitude 
                ORDER BY datetime_utc
            ) AS prev_tp_m,
            LAG(datetime_utc) OVER (
                PARTITION BY latitude, longitude 
                ORDER BY datetime_utc
            ) AS prev_dt_utc
        FROM raw_tp
    ),
    deaccumulated AS (
        SELECT 
            latitude,
            longitude,
            datetime_utc,
            date_utc,
            hour_utc,
            tp_m,
            CASE 
                -- Mốc 01:00 UTC: Reset bắt đầu chu kỳ tích lũy mới trong ngày UTC
                WHEN hour_utc = 1 THEN GREATEST(0.0, tp_m * 1000.0)
                -- Mốc khác: Trừ đi mốc liền trước
                WHEN prev_tp_m IS NOT NULL THEN
                    CASE 
                        WHEN (tp_m - prev_tp_m) * 1000.0 >= 0.0 THEN (tp_m - prev_tp_m) * 1000.0
                        WHEN (tp_m - prev_tp_m) * 1000.0 >= -1e-4 THEN 0.0 -- Sai số dấu phẩy động
                        ELSE 0.0 -- Bất thường âm kẹp về 0.0
                    END
                -- Điểm bắt đầu chuỗi không có điểm trước: Nếu là hour 1 thì lấy tp, nếu khác thì NULL
                ELSE 
                    CASE WHEN hour_utc = 1 THEN GREATEST(0.0, tp_m * 1000.0) ELSE NULL END
            END AS precip_h_mm
        FROM parsed
    )
    SELECT 
        latitude,
        longitude,
        datetime_utc,
        ROUND(precip_h_mm, 4) AS precip_h_mm
    FROM deaccumulated
    """
    return con.sql(query).pl()


# ==============================================================================
# 3. TỔNG HỢP KHÍ TƯỢNG CẤP NGÀY THEO PIXEL GỐC (STAGING LEVEL)
# ==============================================================================

def process_hourly_to_daily_pixel(
    raw_land_df: pl.DataFrame | None,
    raw_blh_df: pl.DataFrame | None,
) -> pl.DataFrame:
    """
    Gom chuỗi giờ khí quyển từ raw thành các chỉ số ngày theo từng pixel gốc:
      1. Khử tích lũy lượng mưa tp từ raw_land_df.
      2. Pivot các biến: t2m, d2m, u10, v10, sp từ ERA5-Land và blh từ ERA5.
      3. Chuyển đổi múi giờ datetime_utc -> Asia/Ho_Chi_Minh (UTC+7):
         date_actual, date_id, hour_local.
      4. Tính các biến cấp giờ: T (°C), Td (°C), RH (%), w (m/s), sp (hPa).
      5. Tổng hợp ngày theo Asia/Ho_Chi_Minh:
         - valid_hours_count: số giờ có đủ T, Td, u, v, sp
         - is_valid_day: 1 nếu valid_hours_count >= 18, ngược lại 0
         - Nếu valid_hours_count > 0: tính trung bình chia đúng cho valid_hours_count
         - Nếu valid_hours_count = 0: các chỉ số nhận giá trị NULL
    """
    con = duckdb.connect()

    # 1. Khử tích lũy lượng mưa nếu có
    if raw_land_df is not None and len(raw_land_df) > 0:
        tp_df = raw_land_df.filter(pl.col("variable") == "tp")
        deacc_precip_df = deaccumulate_era5_land_precip(tp_df)
        con.register("deacc_precip_tbl", deacc_precip_df.to_arrow())
        con.register("raw_land_tbl", raw_land_df.to_arrow())
    else:
        con.register("deacc_precip_tbl", pl.DataFrame(schema={
            "latitude": pl.Float64, "longitude": pl.Float64, "datetime_utc": pl.Utf8, "precip_h_mm": pl.Float64
        }).to_arrow())
        con.register("raw_land_tbl", pl.DataFrame(schema={
            "dataset": pl.Utf8, "variable": pl.Utf8, "unit": pl.Utf8,
            "latitude": pl.Float64, "longitude": pl.Float64, "datetime_utc": pl.Utf8, "value": pl.Float64
        }).to_arrow())

    if raw_blh_df is not None and len(raw_blh_df) > 0:
        con.register("raw_blh_tbl", raw_blh_df.to_arrow())
    else:
        con.register("raw_blh_tbl", pl.DataFrame(schema={
            "dataset": pl.Utf8, "variable": pl.Utf8, "unit": pl.Utf8,
            "latitude": pl.Float64, "longitude": pl.Float64, "datetime_utc": pl.Utf8, "value": pl.Float64
        }).to_arrow())

    # SQL tổng hợp kết hợp xử lý timezone và công thức vật lý
    query = """
    WITH land_pivoted AS (
        SELECT 
            latitude,
            longitude,
            datetime_utc,
            -- Chuyển đổi timestamp UTC sang Asia/Ho_Chi_Minh (+7h)
            (CAST(datetime_utc AS TIMESTAMP) + INTERVAL 7 HOUR) AS datetime_local,
            MAX(CASE WHEN variable = 't2m' THEN value END) AS t2m_k,
            MAX(CASE WHEN variable = 'd2m' THEN value END) AS d2m_k,
            MAX(CASE WHEN variable = 'u10' THEN value END) AS u10,
            MAX(CASE WHEN variable = 'v10' THEN value END) AS v10,
            MAX(CASE WHEN variable = 'sp' THEN value END) AS sp_pa
        FROM raw_land_tbl
        WHERE variable IN ('t2m', 'd2m', 'u10', 'v10', 'sp')
        GROUP BY latitude, longitude, datetime_utc
    ),
    land_with_precip AS (
        SELECT 
            l.latitude,
            l.longitude,
            l.datetime_utc,
            l.datetime_local,
            l.t2m_k,
            l.d2m_k,
            l.u10,
            l.v10,
            l.sp_pa,
            p.precip_h_mm
        FROM land_pivoted l
        LEFT JOIN deacc_precip_tbl p
            ON l.latitude = p.latitude 
            AND l.longitude = p.longitude 
            AND l.datetime_utc = p.datetime_utc
    ),
    hourly_features AS (
        SELECT 
            latitude,
            longitude,
            datetime_utc,
            datetime_local,
            CAST(STRFTIME(datetime_local, '%Y-%m-%d') AS DATE) AS date_actual,
            CAST(STRFTIME(datetime_local, '%Y%m%d') AS INT32) AS date_id,
            -- Đơn vị vật lý
            CASE WHEN t2m_k IS NOT NULL THEN t2m_k - 273.15 ELSE NULL END AS t2m_c,
            CASE WHEN d2m_k IS NOT NULL THEN d2m_k - 273.15 ELSE NULL END AS d2m_c,
            CASE 
                WHEN t2m_k IS NOT NULL AND d2m_k IS NOT NULL THEN
                    -- Magnus-Tetens formula: 100.0 * exp(17.625*Td / (243.04+Td)) / exp(17.625*T / (243.04+T))
                    LEAST(100.0, GREATEST(0.0, 
                        100.0 * EXP((17.625 * (d2m_k - 273.15)) / (243.04 + (d2m_k - 273.15))) 
                              / EXP((17.625 * (t2m_k - 273.15)) / (243.04 + (t2m_k - 273.15)))
                    ))
                ELSE NULL 
            END AS rh_pct,
            precip_h_mm,
            u10,
            v10,
            CASE WHEN u10 IS NOT NULL AND v10 IS NOT NULL THEN SQRT(u10 * u10 + v10 * v10) ELSE NULL END AS wind_speed,
            CASE WHEN sp_pa IS NOT NULL THEN sp_pa / 100.0 ELSE NULL END AS sp_hpa,
            -- Cờ giờ hợp lệ: có đủ T, Td, u, v, sp
            CASE 
                WHEN t2m_k IS NOT NULL AND d2m_k IS NOT NULL 
                     AND u10 IS NOT NULL AND v10 IS NOT NULL 
                     AND sp_pa IS NOT NULL 
                THEN 1 ELSE 0 
            END AS is_valid_hour
        FROM land_with_precip
    ),
    -- Tổng hợp cấp ngày cho từng pixel ERA5-Land
    daily_land AS (
        SELECT 
            latitude,
            longitude,
            date_actual,
            date_id,
            COUNT(*) AS total_hours_in_day,
            SUM(is_valid_hour) AS valid_hours_count,
            CASE WHEN SUM(is_valid_hour) >= 18 THEN 1 ELSE 0 END AS is_valid_day,
            -- Trung bình các giờ hợp lệ
            ROUND(AVG(t2m_c) FILTER (WHERE is_valid_hour = 1), 2) AS temp_2m_mean_c,
            ROUND(AVG(d2m_c) FILTER (WHERE is_valid_hour = 1), 2) AS dewpoint_2m_mean_c,
            ROUND(AVG(rh_pct) FILTER (WHERE is_valid_hour = 1), 2) AS rh_mean_pct,
            ROUND(SUM(COALESCE(precip_h_mm, 0.0)) FILTER (WHERE is_valid_hour = 1), 2) AS precip_daily_mm,
            ROUND(AVG(wind_speed) FILTER (WHERE is_valid_hour = 1), 2) AS wind_speed_scalar_ms,
            -- Vector gió trung bình và tỷ số bền vững
            AVG(u10) FILTER (WHERE is_valid_hour = 1) AS mean_u10,
            AVG(v10) FILTER (WHERE is_valid_hour = 1) AS mean_v10,
            ROUND(AVG(sp_hpa) FILTER (WHERE is_valid_hour = 1), 2) AS surface_pressure_hpa
        FROM hourly_features
        GROUP BY latitude, longitude, date_actual, date_id
    ),
    daily_land_with_persistence AS (
        SELECT 
            latitude,
            longitude,
            date_actual,
            date_id,
            total_hours_in_day,
            valid_hours_count,
            is_valid_day,
            temp_2m_mean_c,
            dewpoint_2m_mean_c,
            rh_mean_pct,
            precip_daily_mm,
            wind_speed_scalar_ms,
            CASE 
                WHEN valid_hours_count > 0 AND wind_speed_scalar_ms >= 1e-4 THEN
                    LEAST(1.0, GREATEST(0.0, ROUND(SQRT(mean_u10 * mean_u10 + mean_v10 * mean_v10) / wind_speed_scalar_ms, 4)))
                WHEN valid_hours_count > 0 THEN 0.0 -- Gió lặng
                ELSE NULL 
            END AS wind_persistence,
            surface_pressure_hpa
        FROM daily_land
    )
    SELECT 
        latitude,
        longitude,
        date_actual,
        date_id,
        total_hours_in_day,
        valid_hours_count,
        is_valid_day,
        temp_2m_mean_c,
        dewpoint_2m_mean_c,
        rh_mean_pct,
        precip_daily_mm,
        wind_speed_scalar_ms,
        wind_persistence,
        surface_pressure_hpa
    FROM daily_land_with_persistence
    ORDER BY latitude DESC, longitude ASC, date_id ASC
    """
    df_stg = con.sql(query).pl()
    return df_stg


def process_blh_daily_pixel(raw_blh_df: pl.DataFrame | None) -> pl.DataFrame:
    """Tổng hợp ngày cho các pixel BLH gốc (~0.25 độ)."""
    if raw_blh_df is None or len(raw_blh_df) == 0:
        return pl.DataFrame(schema={
            "latitude": pl.Float64,
            "longitude": pl.Float64,
            "date_id": pl.Int32,
            "blh_mean_m": pl.Float64,
            "blh_min_m": pl.Float64,
        })

    con = duckdb.connect()
    con.register("raw_blh_tbl", raw_blh_df.to_arrow())
    query = """
    WITH blh_hourly AS (
        SELECT 
            latitude,
            longitude,
            CAST(STRFTIME(CAST(datetime_utc AS TIMESTAMP) + INTERVAL 7 HOUR, '%Y%m%d') AS INT32) AS date_id,
            value AS blh_m
        FROM raw_blh_tbl
        WHERE variable = 'blh' AND value IS NOT NULL
    )
    SELECT 
        latitude,
        longitude,
        date_id,
        COUNT(*) AS blh_valid_hours,
        ROUND(AVG(blh_m), 2) AS blh_mean_m,
        ROUND(MIN(blh_m), 2) AS blh_min_m
    FROM blh_hourly
    GROUP BY latitude, longitude, date_id
    ORDER BY latitude DESC, longitude ASC, date_id ASC
    """
    return con.sql(query).pl()


# ==============================================================================
# 4. ÁNH XẠ KHÔNG GIAN SANG LƯỚI 1KM (SPATIAL INTERPOLATION & MAPPING)
# ==============================================================================

def find_nearest_neighbor_indices(
    target_lats: np.ndarray,
    target_lons: np.ndarray,
    source_lats: np.ndarray,
    source_lons: np.ndarray,
) -> np.ndarray:
    """
    Tìm chỉ số của pixel nguồn gần nhất cho từng ô lưới mục tiêu (Nearest Neighbor).
    Sử dụng khoảng cách Euclid có trọng số cosine vĩ độ:
      dist^2 = (target_lat - source_lat)^2 + ((target_lon - source_lon) * cos(mean_lat))^2
    Vector hóa hoàn toàn bằng NumPy.
    """
    mean_lat_rad = np.radians(np.mean(target_lats))
    cos_lat = np.cos(mean_lat_rad)

    # Broadcast hiệu tọa độ: target (N, 1), source (1, M)
    d_lat = target_lats[:, None] - source_lats[None, :]
    d_lon = (target_lons[:, None] - source_lons[None, :]) * cos_lat

    dist_sq = d_lat * d_lat + d_lon * d_lon
    return np.argmin(dist_sq, axis=1)


def bilinear_interpolation_weights(
    target_lat: float,
    target_lon: float,
    sorted_lats: np.ndarray,  # 1D array tăng dần
    sorted_lons: np.ndarray,  # 1D array tăng dần
) -> tuple[tuple[int, int, int, int] | None, tuple[float, float, float, float] | None]:
    """
    Tính trọng số nội suy song tuyến tính (Bilinear Interpolation) từ 4 pixel lân cận:
      Q11 = (lat1, lon1), Q21 = (lat1, lon2), Q12 = (lat2, lon1), Q22 = (lat2, lon2)
    Nếu điểm nằm ngoài biên của lưới pixel, trả về None để fallback về nearest neighbor.
    """
    if target_lat < sorted_lats[0] or target_lat > sorted_lats[-1]:
        return None, None
    if target_lon < sorted_lons[0] or target_lon > sorted_lons[-1]:
        return None, None

    # Tìm vị trí interval
    i = np.searchsorted(sorted_lats, target_lat) - 1
    j = np.searchsorted(sorted_lons, target_lon) - 1

    i = max(0, min(i, len(sorted_lats) - 2))
    j = max(0, min(j, len(sorted_lons) - 2))

    lat1, lat2 = sorted_lats[i], sorted_lats[i + 1]
    lon1, lon2 = sorted_lons[j], sorted_lons[j + 1]

    d_lat = lat2 - lat1
    d_lon = lon2 - lon1
    if d_lat == 0 or d_lon == 0:
        return None, None

    u = (target_lat - lat1) / d_lat
    t = (target_lon - lon1) / d_lon

    # Trọng số 4 đỉnh
    w11 = (1.0 - t) * (1.0 - u)
    w21 = t * (1.0 - u)
    w12 = (1.0 - t) * u
    w22 = t * u

    return (i, j, i + 1, j + 1), (w11, w21, w12, w22)


def map_pixel_meteo_to_grid_1km(
    df_stg_land: pl.DataFrame,
    df_stg_blh: pl.DataFrame,
    dim_grid_path: str = DEFAULT_DIM_GRID_PATH,
    dim_date_path: str = DEFAULT_DIM_DATE_PATH,
    method: str = "nearest",  # 'nearest' hoặc 'bilinear'
) -> pl.DataFrame:
    """
    Ánh xạ dữ liệu khí tượng từ pixel gốc sang 3.610 ô lưới 1km:
      - Đọc dim_grid_1km và dim_date.
      - Loại trừ các bản ghi ngoại lệ 'grid_unknown' và 'date_id = -1'.
      - Chuyển đổi tọa độ tâm ô (easting_m, northing_m) từ EPSG:3405 sang WGS84 (lon, lat) bằng pyproj.
      - Ánh xạ theo phương pháp được chỉ định: 'nearest' (mặc định) hoặc 'bilinear'.
      - Xây dựng khung xương phân tích đầy đủ (Spine) bằng Cartesian Product (Cross Join)
        giữa các ô phân tích và các ngày phân tích.
      - LEFT JOIN khung xương với bảng nội suy ô–ngày để bảo đảm 100% không rơi dòng,
        không nhân dòng (Zero-Drop & Anti-Fanout).
      - Đảm bảo các ô hoặc ngày thiếu dữ liệu sẽ nhận giá trị NULL tự nhiên.
      - TUYỆT ĐỐI KHÔNG chứa cột PM2.5, trạm hay nhãn học máy.
    """
    if not os.path.exists(dim_grid_path):
        raise FileNotFoundError(f"Chưa tìm thấy file {dim_grid_path}!")
    if not os.path.exists(dim_date_path):
        raise FileNotFoundError(f"Chưa tìm thấy file {dim_date_path}!")

    print(f"\n[SPATIAL MAPPING] Bắt đầu ánh xạ khí tượng sang lưới 1km (Phương pháp: '{method}')...")

    # 1. Đọc danh mục ô và ngày
    grid_df = pl.read_parquet(dim_grid_path).filter(pl.col("grid_id") != "grid_unknown")
    date_df = pl.read_parquet(dim_date_path).filter(pl.col("date_id") != -1)

    real_cells_count = len(grid_df)
    real_days_count = len(date_df)
    expected_rows = real_cells_count * real_days_count
    print(f"  -> Số ô phân tích thực tế: {real_cells_count} ô")
    print(f"  -> Số ngày phân tích thực tế: {real_days_count} ngày")
    print(f"  -> Quy mô khung phân tích dự kiến: {expected_rows:,} dòng")

    # 2. Chuyển đổi tọa độ tâm ô từ EPSG:3405 sang WGS84 EPSG:4326
    transformer = pyproj.Transformer.from_crs("EPSG:3405", "EPSG:4326", always_xy=True)
    eastings = grid_df["easting_m"].to_numpy()
    northings = grid_df["northing_m"].to_numpy()
    grid_lons, grid_lats = transformer.transform(eastings, northings)
    grid_ids = grid_df["grid_id"].to_list()

    # 3. Chuẩn bị danh sách pixel ERA5-Land
    unique_land_pixels = df_stg_land.select(["latitude", "longitude"]).unique().sort(["latitude", "longitude"])
    land_p_lats = unique_land_pixels["latitude"].to_numpy()
    land_p_lons = unique_land_pixels["longitude"].to_numpy()

    # Chuẩn bị danh sách pixel BLH
    if len(df_stg_blh) > 0:
        unique_blh_pixels = df_stg_blh.select(["latitude", "longitude"]).unique().sort(["latitude", "longitude"])
        blh_p_lats = unique_blh_pixels["latitude"].to_numpy()
        blh_p_lons = unique_blh_pixels["longitude"].to_numpy()
    else:
        unique_blh_pixels = None
        blh_p_lats = np.array([])
        blh_p_lons = np.array([])

    # 4. Xác định mapping cho từng ô 1km
    if method == "nearest" or len(land_p_lats) < 4:
        # Nearest neighbor cho ERA5-Land
        nearest_land_idx = find_nearest_neighbor_indices(
            target_lats=grid_lats,
            target_lons=grid_lons,
            source_lats=land_p_lats,
            source_lons=land_p_lons,
        )
        grid_mapping_records = []
        for g_idx, gid in enumerate(grid_ids):
            p_idx = nearest_land_idx[g_idx]
            grid_mapping_records.append({
                "grid_id": gid,
                "land_pixel_lat": float(land_p_lats[p_idx]),
                "land_pixel_lon": float(land_p_lons[p_idx]),
            })
        grid_mapping_df = pl.DataFrame(grid_mapping_records)

        # Nearest neighbor cho BLH
        if len(blh_p_lats) > 0:
            nearest_blh_idx = find_nearest_neighbor_indices(
                target_lats=grid_lats,
                target_lons=grid_lons,
                source_lats=blh_p_lats,
                source_lons=blh_p_lons,
            )
            blh_mapping_records = []
            for g_idx, gid in enumerate(grid_ids):
                p_idx = nearest_blh_idx[g_idx]
                blh_mapping_records.append({
                    "grid_id": gid,
                    "blh_pixel_lat": float(blh_p_lats[p_idx]),
                    "blh_pixel_lon": float(blh_p_lons[p_idx]),
                })
            blh_mapping_df = pl.DataFrame(blh_mapping_records)
        else:
            blh_mapping_df = None

    elif method == "bilinear":
        # Bilinear interpolation
        # Lấy lưới toạ độ 1D đều
        sorted_lats = np.sort(np.unique(land_p_lats))
        sorted_lons = np.sort(np.unique(land_p_lons))

        grid_mapping_records = []
        # Fallback index cho các điểm ở rìa biên
        fallback_nearest = find_nearest_neighbor_indices(grid_lats, grid_lons, land_p_lats, land_p_lons)

        for g_idx, gid in enumerate(grid_ids):
            glat = grid_lats[g_idx]
            glon = grid_lons[g_idx]
            indices, weights = bilinear_interpolation_weights(glat, glon, sorted_lats, sorted_lons)
            if indices is not None and weights is not None:
                i1, j1, i2, j2 = indices
                w11, w21, w12, w22 = weights
                grid_mapping_records.append({
                    "grid_id": gid,
                    "is_bilinear": True,
                    "lat1": float(sorted_lats[i1]),
                    "lon1": float(sorted_lons[j1]),
                    "lat2": float(sorted_lats[i2]),
                    "lon2": float(sorted_lons[j2]),
                    "w11": float(w11),
                    "w21": float(w21),
                    "w12": float(w12),
                    "w22": float(w22),
                    "land_pixel_lat": None,
                    "land_pixel_lon": None,
                })
            else:
                p_idx = fallback_nearest[g_idx]
                grid_mapping_records.append({
                    "grid_id": gid,
                    "is_bilinear": False,
                    "lat1": None, "lon1": None, "lat2": None, "lon2": None,
                    "w11": 0.0, "w21": 0.0, "w12": 0.0, "w22": 0.0,
                    "land_pixel_lat": float(land_p_lats[p_idx]),
                    "land_pixel_lon": float(land_p_lons[p_idx]),
                })
        grid_mapping_df = pl.DataFrame(grid_mapping_records)
        # BLH dùng nearest neighbor vì số lượng pixel thô (~0.25 độ)
        if len(blh_p_lats) > 0:
            nearest_blh_idx = find_nearest_neighbor_indices(grid_lats, grid_lons, blh_p_lats, blh_p_lons)
            blh_mapping_records = []
            for g_idx, gid in enumerate(grid_ids):
                p_idx = nearest_blh_idx[g_idx]
                blh_mapping_records.append({
                    "grid_id": gid,
                    "blh_pixel_lat": float(blh_p_lats[p_idx]),
                    "blh_pixel_lon": float(blh_p_lons[p_idx]),
                })
            blh_mapping_df = pl.DataFrame(blh_mapping_records)
        else:
            blh_mapping_df = None

    # 5. Thực hiện Broadcast và Ghép nối Khung xương phân tích (Spine Join) bằng DuckDB
    con = duckdb.connect()
    con.register("dim_grid_tbl", grid_df.select(["grid_id"]).to_arrow())
    con.register("dim_date_tbl", date_df.select(["date_id"]).to_arrow())
    con.register("stg_land_tbl", df_stg_land.to_arrow())
    con.register("grid_mapping_tbl", grid_mapping_df.to_arrow())

    if blh_mapping_df is not None and len(df_stg_blh) > 0:
        con.register("blh_mapping_tbl", blh_mapping_df.to_arrow())
        con.register("stg_blh_tbl", df_stg_blh.to_arrow())
        has_blh = True
    else:
        has_blh = False

    if method == "nearest":
        join_query = f"""
        WITH spine AS (
            SELECT g.grid_id, d.date_id
            FROM dim_grid_tbl g
            CROSS JOIN dim_date_tbl d
        ),
        grid_land_daily AS (
            SELECT 
                m.grid_id,
                s.date_id,
                s.temp_2m_mean_c,
                s.dewpoint_2m_mean_c,
                s.rh_mean_pct,
                s.precip_daily_mm,
                s.wind_speed_scalar_ms,
                s.wind_persistence,
                s.surface_pressure_hpa
            FROM grid_mapping_tbl m
            JOIN stg_land_tbl s 
                ON m.land_pixel_lat = s.latitude 
                AND m.land_pixel_lon = s.longitude
        )
        {''',
        grid_blh_daily AS (
            SELECT 
                bm.grid_id,
                bs.date_id,
                bs.blh_mean_m,
                bs.blh_min_m
            FROM blh_mapping_tbl bm
            JOIN stg_blh_tbl bs 
                ON bm.blh_pixel_lat = bs.latitude 
                AND bm.blh_pixel_lon = bs.longitude
        )''' if has_blh else ''}
        SELECT 
            s.grid_id,
            s.date_id,
            ROUND(l.temp_2m_mean_c, 2) AS temp_2m_mean_c,
            ROUND(l.dewpoint_2m_mean_c, 2) AS dewpoint_2m_mean_c,
            ROUND(l.rh_mean_pct, 2) AS rh_mean_pct,
            ROUND(l.precip_daily_mm, 2) AS precip_daily_mm,
            ROUND(l.wind_speed_scalar_ms, 2) AS wind_speed_scalar_ms,
            ROUND(l.wind_persistence, 4) AS wind_persistence,
            ROUND(l.surface_pressure_hpa, 2) AS surface_pressure_hpa,
            {'ROUND(b.blh_mean_m, 2) AS blh_mean_m,' if has_blh else 'NULL AS blh_mean_m,'}
            {'ROUND(b.blh_min_m, 2) AS blh_min_m' if has_blh else 'NULL AS blh_min_m'}
        FROM spine s
        LEFT JOIN grid_land_daily l 
            ON s.grid_id = l.grid_id AND s.date_id = l.date_id
        {'LEFT JOIN grid_blh_daily b ON s.grid_id = b.grid_id AND s.date_id = b.date_id' if has_blh else ''}
        ORDER BY s.grid_id, s.date_id
        """
    else:
        # Bilinear mapping query
        join_query = f"""
        WITH spine AS (
            SELECT g.grid_id, d.date_id
            FROM dim_grid_tbl g
            CROSS JOIN dim_date_tbl d
        ),
        grid_bilinear_daily AS (
            SELECT 
                m.grid_id,
                s11.date_id,
                CASE 
                    WHEN m.is_bilinear THEN 
                        m.w11 * s11.temp_2m_mean_c + m.w21 * s21.temp_2m_mean_c + 
                        m.w12 * s12.temp_2m_mean_c + m.w22 * s22.temp_2m_mean_c
                    ELSE s_near.temp_2m_mean_c
                END AS temp_2m_mean_c,
                CASE 
                    WHEN m.is_bilinear THEN 
                        m.w11 * s11.dewpoint_2m_mean_c + m.w21 * s21.dewpoint_2m_mean_c + 
                        m.w12 * s12.dewpoint_2m_mean_c + m.w22 * s22.dewpoint_2m_mean_c
                    ELSE s_near.dewpoint_2m_mean_c
                END AS dewpoint_2m_mean_c,
                CASE 
                    WHEN m.is_bilinear THEN 
                        m.w11 * s11.rh_mean_pct + m.w21 * s21.rh_mean_pct + 
                        m.w12 * s12.rh_mean_pct + m.w22 * s22.rh_mean_pct
                    ELSE s_near.rh_mean_pct
                END AS rh_mean_pct,
                CASE 
                    WHEN m.is_bilinear THEN 
                        m.w11 * s11.precip_daily_mm + m.w21 * s21.precip_daily_mm + 
                        m.w12 * s12.precip_daily_mm + m.w22 * s22.precip_daily_mm
                    ELSE s_near.precip_daily_mm
                END AS precip_daily_mm,
                CASE 
                    WHEN m.is_bilinear THEN 
                        m.w11 * s11.wind_speed_scalar_ms + m.w21 * s21.wind_speed_scalar_ms + 
                        m.w12 * s12.wind_speed_scalar_ms + m.w22 * s22.wind_speed_scalar_ms
                    ELSE s_near.wind_speed_scalar_ms
                END AS wind_speed_scalar_ms,
                CASE 
                    WHEN m.is_bilinear THEN 
                        m.w11 * s11.wind_persistence + m.w21 * s21.wind_persistence + 
                        m.w12 * s12.wind_persistence + m.w22 * s22.wind_persistence
                    ELSE s_near.wind_persistence
                END AS wind_persistence,
                CASE 
                    WHEN m.is_bilinear THEN 
                        m.w11 * s11.surface_pressure_hpa + m.w21 * s21.surface_pressure_hpa + 
                        m.w12 * s12.surface_pressure_hpa + m.w22 * s22.surface_pressure_hpa
                    ELSE s_near.surface_pressure_hpa
                END AS surface_pressure_hpa
            FROM grid_mapping_tbl m
            LEFT JOIN stg_land_tbl s11 ON m.lat1 = s11.latitude AND m.lon1 = s11.longitude
            LEFT JOIN stg_land_tbl s21 ON m.lat1 = s21.latitude AND m.lon2 = s21.longitude AND s11.date_id = s21.date_id
            LEFT JOIN stg_land_tbl s12 ON m.lat2 = s12.latitude AND m.lon1 = s12.longitude AND s11.date_id = s12.date_id
            LEFT JOIN stg_land_tbl s22 ON m.lat2 = s22.latitude AND m.lon2 = s22.longitude AND s11.date_id = s22.date_id
            LEFT JOIN stg_land_tbl s_near ON m.land_pixel_lat = s_near.latitude AND m.land_pixel_lon = s_near.longitude
        )
        {''',
        grid_blh_daily AS (
            SELECT 
                bm.grid_id,
                bs.date_id,
                bs.blh_mean_m,
                bs.blh_min_m
            FROM blh_mapping_tbl bm
            JOIN stg_blh_tbl bs 
                ON bm.blh_pixel_lat = bs.latitude 
                AND bm.blh_pixel_lon = bs.longitude
        )''' if has_blh else ''}
        SELECT 
            s.grid_id,
            s.date_id,
            ROUND(l.temp_2m_mean_c, 2) AS temp_2m_mean_c,
            ROUND(l.dewpoint_2m_mean_c, 2) AS dewpoint_2m_mean_c,
            ROUND(l.rh_mean_pct, 2) AS rh_mean_pct,
            ROUND(l.precip_daily_mm, 2) AS precip_daily_mm,
            ROUND(l.wind_speed_scalar_ms, 2) AS wind_speed_scalar_ms,
            ROUND(l.wind_persistence, 4) AS wind_persistence,
            ROUND(l.surface_pressure_hpa, 2) AS surface_pressure_hpa,
            {'ROUND(b.blh_mean_m, 2) AS blh_mean_m,' if has_blh else 'NULL AS blh_mean_m,'}
            {'ROUND(b.blh_min_m, 2) AS blh_min_m' if has_blh else 'NULL AS blh_min_m'}
        FROM spine s
        LEFT JOIN grid_bilinear_daily l 
            ON s.grid_id = l.grid_id AND s.date_id = l.date_id
        {'LEFT JOIN grid_blh_daily b ON s.grid_id = b.grid_id AND s.date_id = b.date_id' if has_blh else ''}
        ORDER BY s.grid_id, s.date_id
        """

    df_fact = con.sql(join_query).pl()

    # Kiểm tra kích thước và tính toàn vẹn
    actual_rows = len(df_fact)
    if actual_rows != expected_rows:
        raise ValueError(
            f"Kích thước bảng Fact bị sai lệch! Kỳ vọng: {expected_rows} dòng, thực tế: {actual_rows} dòng."
        )

    # Kiểm tra tính duy nhất của khóa chính (grid_id, date_id)
    unique_keys = df_fact.select(["grid_id", "date_id"]).n_unique()
    if unique_keys != actual_rows:
        raise ValueError(
            f"Phát hiện trùng lặp khóa chính (grid_id, date_id)! Số dòng: {actual_rows}, số khóa duy nhất: {unique_keys}."
        )

    print(f"[SPATIAL MAPPING] Hoàn tất ánh xạ: {actual_rows:,} dòng.")
    print("  -> Kiểm tra tính duy nhất khóa (grid_id, date_id): 100% UNIQUE.")
    return df_fact


# ==============================================================================
# 5. PIPELINE THỰC THI CHÍNH (MAIN PIPELINE ORCHESTRATION)
# ==============================================================================

def run_meteo_processing_pipeline(
    raw_dir: str = DEFAULT_RAW_METEO_DIR,
    dim_grid_path: str = DEFAULT_DIM_GRID_PATH,
    dim_date_path: str = DEFAULT_DIM_DATE_PATH,
    stg_output_path: str = DEFAULT_STG_METEO_PATH,
    fct_output_path: str = DEFAULT_FCT_METEO_PATH,
    method: str = "nearest",
    date_filter: list[int] | None = None,
    grid_filter: list[str] | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """
    Điều phối toàn bộ quy trình: Đọc raw -> Staging -> Fact 1km.
    Cho phép truyền output paths tùy chọn để chạy thử nghiệm an toàn không ghi đè Lakehouse.
    """
    raw_path = Path(raw_dir)
    print(f"\n[PIPELINE] Bắt đầu xử lý dữ liệu khí quyển từ: {raw_dir}")

    # Đọc dữ liệu ERA5-Land
    land_files = list(raw_path.glob("dataset=reanalysis-era5-land/**/*.parquet"))
    if not land_files:
        # Tìm file parquet trực tiếp
        land_files = list(raw_path.glob("**/reanalysis-era5-land*.parquet"))

    if land_files:
        print(f"  -> Đã tìm thấy {len(land_files)} file raw ERA5-Land.")
        raw_land_df = pl.concat([pl.read_parquet(f) for f in land_files])
    else:
        print(f"  [WARN] Không tìm thấy file raw ERA5-Land tại {raw_dir}.")
        raw_land_df = None

    # Đọc dữ liệu ERA5 BLH
    blh_files = list(raw_path.glob("dataset=reanalysis-era5-single-levels/**/*.parquet"))
    if not blh_files:
        blh_files = list(raw_path.glob("**/reanalysis-era5-single-levels*.parquet"))

    if blh_files:
        print(f"  -> Đã tìm thấy {len(blh_files)} file raw ERA5 BLH.")
        raw_blh_df = pl.concat([pl.read_parquet(f) for f in blh_files])
    else:
        print(f"  [WARN] Không tìm thấy file raw ERA5 BLH tại {raw_dir}.")
        raw_blh_df = None

    if raw_land_df is None and raw_blh_df is None:
        raise FileNotFoundError(f"Không có dữ liệu khí tượng nào tại thư mục: {raw_dir}")

    # 1. Tổng hợp cấp pixel (Staging)
    df_stg_land = process_hourly_to_daily_pixel(raw_land_df, raw_blh_df)
    df_stg_blh = process_blh_daily_pixel(raw_blh_df)

    # Lưu Staging Parquet nguyên tử
    atomic_write_parquet(df_stg_land, stg_output_path)
    print(f"[STAGING] Đã lưu {len(df_stg_land):,} pixel-days tại: {stg_output_path}")

    # 2. Ánh xạ không gian sang lưới 1km (Core Fact)
    df_fct = map_pixel_meteo_to_grid_1km(
        df_stg_land=df_stg_land,
        df_stg_blh=df_stg_blh,
        dim_grid_path=dim_grid_path,
        dim_date_path=dim_date_path,
        method=method,
    )

    # Lọc mẫu kiểm thử nếu được yêu cầu
    if date_filter is not None:
        df_fct = df_fct.filter(pl.col("date_id").is_in(date_filter))
    if grid_filter is not None:
        df_fct = df_fct.filter(pl.col("grid_id").is_in(grid_filter))

    # Lưu Fact Parquet nguyên tử
    atomic_write_parquet(df_fct, fct_output_path)
    print(f"[CORE FACT] Đã lưu {len(df_fct):,} grid-days tại: {fct_output_path}")

    return df_stg_land, df_fct


def main():
    parser = argparse.ArgumentParser(
        description="Chuan hoa, tinh dac trung khi tuong va anh xa sang luoi 1km Ha Noi",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--raw-dir", type=str, default=DEFAULT_RAW_METEO_DIR, help="Thu muc raw Parquet")
    parser.add_argument("--dim-grid", type=str, default=DEFAULT_DIM_GRID_PATH, help="File dim_grid_1km.parquet")
    parser.add_argument("--dim-date", type=str, default=DEFAULT_DIM_DATE_PATH, help="File dim_date.parquet")
    parser.add_argument("--stg-output", type=str, default=DEFAULT_STG_METEO_PATH, help="File staging output")
    parser.add_argument("--fct-output", type=str, default=DEFAULT_FCT_METEO_PATH, help="File core fact output")
    parser.add_argument(
        "--method",
        choices=["nearest", "bilinear"],
        default="nearest",
        help="Phuong phap anh xa khong gian: 'nearest' (Nearest Neighbor) hoac 'bilinear' (Bilinear Interpolation)",
    )

    args = parser.parse_args()
    try:
        run_meteo_processing_pipeline(
            raw_dir=args.raw_dir,
            dim_grid_path=args.dim_grid,
            dim_date_path=args.dim_date,
            stg_output_path=args.stg_output,
            fct_output_path=args.fct_output,
            method=args.method,
        )
        print("\n[SUCCESS] Pipeline xu ly khi tuong da hoan thanh xuat sac.")
    except Exception as e:  # noqa: BLE001
        print(f"\n[ERROR] Pipeline that bai: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
