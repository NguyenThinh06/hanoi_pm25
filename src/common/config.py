"""Cấu hình chung của pipeline: phạm vi thời gian, không gian và đường dẫn dữ liệu."""
from __future__ import annotations

import io
import sys
from datetime import date
from pathlib import Path

# Đảm bảo console Windows hỗ trợ in tiếng Việt UTF-8 không lỗi
if sys.stdout and getattr(sys.stdout, "encoding", "").lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, io.UnsupportedOperation):
        pass

ROOT = Path(__file__).resolve().parents[2]

# --- Phạm vi phân tích -------------------------------------------------------
START_DATE = date(2021, 1, 1)
END_DATE = date(2026, 9, 30)          # hết tháng 9/2026 (ngày theo giờ Hà Nội)
TIMEZONE = "Asia/Ho_Chi_Minh"
UTC_OFFSET_HOURS = 7                  # Việt Nam không có giờ mùa hè

BBOX_WGS84 = (105.28, 20.56, 106.02, 21.39)   # lon_min, lat_min, lon_max, lat_max
GRID_CRS = "EPSG:3405"                         # VN-2000 / UTM 48N, đơn vị mét
CELL_M = 1000                                  # lưới 1 km

# Tham số OpenAQ cần lấy -> tên cột trong fact
# (khí chất lượng không khí thêm hậu tố _aq, khí tượng mang tiền tố openaq_)
OPENAQ_PARAMETERS = {
    "pm25": "pm25",
    "pm10": "pm10_aq",
    "no2": "no2_aq",
    "so2": "so2_aq",
    "co": "co_aq",
    "co2": "co2_aq",
    "o3": "o3_aq",
    "temperature": "openaq_temperature",
    "relativehumidity": "openaq_relativehumidity",
}
MIN_VALID_HOURS = 18                  # ngày hợp lệ khi có >= 18 giờ PM2.5 sạch

# --- Đường dẫn ---------------------------------------------------------------
DATA = ROOT / "data"
BOUNDARY = DATA / "reference" / "hanoi_boundary.geojson"

RAW_OPENAQ = DATA / "raw" / "openaq"
RAW_OPENAQ_LOCATIONS = RAW_OPENAQ / "locations.json"
RAW_OPENAQ_HOURS = RAW_OPENAQ / "hours"
RAW_METEO = DATA / "raw" / "meteo"
RAW_SATELLITE = DATA / "raw" / "satellite"
RAW_VIIRS = DATA / "raw" / "viirs"

DIM_GRID = DATA / "core" / "dim_grid_1km.parquet"
DIM_DATE = DATA / "core" / "dim_date.parquet"
DIM_STATION = DATA / "core" / "dim_station.parquet"

STG_OPENAQ_HOURLY = DATA / "staging" / "stg_openaq_hourly.parquet"
STG_METEO_DAILY = DATA / "staging" / "stg_meteo_daily.parquet"
STG_SATELLITE_DAILY = DATA / "staging" / "stg_satellite_daily.parquet"
STG_VIIRS_MONTHLY = DATA / "staging" / "stg_viirs_monthly.parquet"

FCT_STATION_DAILY = DATA / "core" / "fct_station_daily.parquet"
FCT_GRID_METEO_DAILY = DATA / "core" / "fct_grid_meteo_daily.parquet"
FCT_GRID_SATELLITE_DAILY = DATA / "core" / "fct_grid_satellite_daily.parquet"

MART_GRID_DAILY = DATA / "marts" / "mart_grid_daily_features.parquet"
MART_STATION_TRAINING = DATA / "marts" / "mart_station_daily_training.parquet"


def months(start: date = START_DATE, end: date = END_DATE) -> list[date]:
    """Danh sách ngày đầu tháng trong [start, end]."""
    out, cur = [], start.replace(day=1)
    while cur <= end:
        out.append(cur)
        cur = date(cur.year + cur.month // 12, cur.month % 12 + 1, 1)
    return out
