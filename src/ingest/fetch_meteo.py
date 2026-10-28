"""Khí tượng theo ngày Hà Nội trên lưới 1 km từ Google Earth Engine.

Nguồn:
  - ERA5-Land hourly (ECMWF/ERA5_LAND/HOURLY, ~11 km): nhiệt độ, điểm sương, gió 10 m,
    áp suất bề mặt, lượng mưa. Nội suy bilinear xuống 1 km.
  - ERA5 hourly (ECMWF/ERA5/HOURLY, ~31 km): độ cao lớp biên (BLH).

Mỗi biến là thống kê của 24 ảnh giờ trong ngày Hà Nội, giữ đơn vị gốc của nguồn
(K, Pa, m, m/s). Đổi đơn vị và tính độ bền hướng gió nằm ở bước staging,
ngoại trừ RH và tốc độ gió vô hướng phải tính trên từng giờ trước khi lấy trung bình.

Đầu ra: data/raw/meteo/meteo_YYYY-MM.parquet (grid_id, date, các biến bên dưới).
"""
from __future__ import annotations

import argparse
from datetime import date

import ee
import pandas as pd

from src.common import config, gee

VARIABLES = [
    "t2m_k",            # nhiệt độ 2 m trung bình (K)
    "d2m_k",            # điểm sương 2 m trung bình (K)
    "rh_pct",           # độ ẩm tương đối trung bình các giờ (%)
    "u10_ms",           # thành phần gió U 10 m trung bình (m/s)
    "v10_ms",           # thành phần gió V 10 m trung bình (m/s)
    "ws10_ms",          # tốc độ gió vô hướng trung bình các giờ (m/s)
    "sp_pa",            # áp suất bề mặt trung bình (Pa)
    "tp_m",             # tổng lượng mưa ngày (m)
    "era5_land_hours",  # số giờ ERA5-Land có dữ liệu
    "blh_mean_m",       # độ cao lớp biên trung bình (m)
    "blh_min_m",        # độ cao lớp biên nhỏ nhất (m)
]


def _hourly_derived(img: ee.Image) -> ee.Image:
    t = img.select("temperature_2m").subtract(273.15)
    td = img.select("dewpoint_temperature_2m").subtract(273.15)
    # Công thức Magnus (Alduchov & Eskridge 1996)
    rh = (
        td.multiply(17.625)
        .divide(td.add(243.04))
        .exp()
        .divide(t.multiply(17.625).divide(t.add(243.04)).exp())
        .multiply(100)
        .min(100)
    )
    ws = img.expression(
        "sqrt(u*u + v*v)",
        {"u": img.select("u_component_of_wind_10m"), "v": img.select("v_component_of_wind_10m")},
    )
    return img.addBands([rh.rename("rh"), ws.rename("ws")])


def day_image(day: date) -> ee.Image:
    start, end = gee.local_day_window(day)
    land = ee.ImageCollection("ECMWF/ERA5_LAND/HOURLY").filterDate(start, end).map(_hourly_derived)
    blh = ee.ImageCollection("ECMWF/ERA5/HOURLY").filterDate(start, end).select("boundary_layer_height")
    mean = land.select(
        [
            "temperature_2m",
            "dewpoint_temperature_2m",
            "rh",
            "u_component_of_wind_10m",
            "v_component_of_wind_10m",
            "ws",
            "surface_pressure",
        ]
    ).mean()
    image = ee.Image.cat(
        [
            mean.rename(VARIABLES[:7]),
            land.select("total_precipitation_hourly").sum().rename("tp_m"),
            land.select("temperature_2m").count().rename("era5_land_hours"),
            blh.mean().rename("blh_mean_m"),
            blh.min().rename("blh_min_m"),
        ]
    )
    # ERA5-Land ~0.1°: nội suy bilinear để ô 1 km không bị "bậc thang"
    return image.resample("bilinear")


def fetch_month(month: date, extent: tuple[int, int, int, int], keep_grid_ids: set[str]):
    first, last = gee.month_days(month)
    df = gee.fetch_daily(day_image, VARIABLES, first, last, extent, keep_grid_ids=keep_grid_ids)
    return None if df["era5_land_hours"].isna().all() else df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--overwrite", action="store_true", help="Tải lại tháng đã có file")
    parser.add_argument("--workers", type=int, default=4, help="Số luồng tải song song")
    parser.add_argument("--month", type=str, default=None, help="Chỉ tải 1 tháng YYYY-MM (ví dụ: 2026-09)")
    args = parser.parse_args()

    gee.init()
    extent = gee.grid_extent()
    keep_ids = set(pd.read_parquet(config.DIM_GRID, columns=["grid_id"]).grid_id)
    target = [date.fromisoformat(f"{args.month}-01")] if args.month else None
    gee.run_monthly(
        "meteo",
        config.RAW_METEO,
        lambda mo: fetch_month(mo, extent, keep_ids),
        overwrite=args.overwrite,
        workers=args.workers,
        target_months=target,
    )


if __name__ == "__main__":
    main()
