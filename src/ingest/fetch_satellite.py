"""Vệ tinh theo ngày Hà Nội trên lưới 1 km từ Google Earth Engine.

Nguồn hằng ngày (data/raw/satellite/satellite_YYYY-MM.parquet):
  - Sentinel-5P TROPOMI OFFL L3 (~1,1 km): NO2 tầng đối lưu, CO, O3, SO2 (mol/m²).
    Bộ L3 của GEE đã lọc theo qa_value của ESA khi tạo lưới.
  - MODIS MAIAC MCD19A2 (1 km): AOD 0,47 µm (giá trị nguyên, hệ số 0,001), chỉ giữ pixel
    trời quang (cloud mask = clear) và chất lượng AOD tốt nhất.
  Mỗi biến là trung bình các ảnh trong ngày, kèm số ảnh hợp lệ (*_n).

Nguồn hằng tháng (data/raw/viirs/viirs_YYYY-MM.parquet):
  - VIIRS DNB monthly VCMSLCFG: ánh sáng đêm avg_rad (nW/cm²/sr) và số đêm quang cf_cvg.
"""
from __future__ import annotations

import argparse
from datetime import date

import ee
import numpy as np
import pandas as pd

from src.common import config, gee

S5P = {  # tên biến -> (collection, band)
    "no2_trop": ("COPERNICUS/S5P/OFFL/L3_NO2", "tropospheric_NO2_column_number_density"),
    "co": ("COPERNICUS/S5P/OFFL/L3_CO", "CO_column_number_density"),
    "o3": ("COPERNICUS/S5P/OFFL/L3_O3", "O3_column_number_density"),
    "so2": ("COPERNICUS/S5P/OFFL/L3_SO2", "SO2_column_number_density"),
}
MAIAC = "MODIS/061/MCD19A2_GRANULES"
VIIRS = "NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG"
DAILY_VARIABLES = [f"{name}{suffix}" for name in [*S5P, "aod047"] for suffix in ("", "_n")]


def _maiac_clear_best(img: ee.Image) -> ee.Image:
    qa = img.select("AOD_QA")
    clear = qa.bitwiseAnd(0b111).eq(1)                    # bit 0-2: cloud mask = clear
    best = qa.rightShift(8).bitwiseAnd(0b1111).eq(0)       # bit 8-11: AOD QA = best quality
    return img.select("Optical_Depth_047").updateMask(clear.And(best))


def day_image(day: date) -> ee.Image:
    start, end = gee.local_day_window(day)
    region = ee.Geometry.Rectangle(list(config.BBOX_WGS84))
    bands = []
    for name, (collection, band) in S5P.items():
        col = ee.ImageCollection(collection).filterDate(start, end).filterBounds(region)
        col = gee.safe_reduce(col, band)
        bands += [col.mean().rename(name), col.count().rename(f"{name}_n")]
    aod = ee.ImageCollection(MAIAC).filterDate(start, end).filterBounds(region).map(_maiac_clear_best)
    aod = gee.safe_reduce(aod, "Optical_Depth_047")
    bands += [aod.mean().rename("aod047"), aod.count().rename("aod047_n")]
    return ee.Image.cat(bands)


def fetch_daily_month(month: date, extent: tuple[int, int, int, int], keep_grid_ids: set[str]) -> pd.DataFrame:
    first, last = gee.month_days(month)
    df = gee.fetch_daily(day_image, DAILY_VARIABLES, first, last, extent, keep_grid_ids=keep_grid_ids)
    counts = [c for c in df.columns if c.endswith("_n")]
    df[counts] = df[counts].fillna(0).astype("int16")
    return df


def fetch_viirs_month(month: date, extent: tuple[int, int, int, int], keep_grid_ids: set[str]) -> pd.DataFrame | None:
    first, last = gee.month_days(month)
    col = ee.ImageCollection(VIIRS).filterDate(first.isoformat(), last.isoformat() + "T23:59:59")
    if col.size().getInfo() == 0:
        return None                      # VIIRS tháng thường chậm 1–2 tháng
    arrays = gee.compute_pixels(col.first().select(["avg_rad", "cf_cvg"]), extent)
    ids = gee.pixel_grid_ids(extent).ravel()
    mask = np.isin(ids, list(keep_grid_ids))
    return pd.DataFrame(
        {
            "grid_id": ids[mask],
            "month": first,
            "avg_rad": arrays["avg_rad"].ravel()[mask].astype("float32"),
            "cf_cvg": np.nan_to_num(arrays["cf_cvg"].ravel()[mask]).astype("int16"),
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--overwrite", action="store_true", help="Tải lại tháng đã có file")
    parser.add_argument("--workers", type=int, default=4, help="Số luồng tải song song")
    parser.add_argument("--month", type=str, default=None, help="Chỉ tải 1 tháng YYYY-MM (ví dụ: 2026-08)")
    args = parser.parse_args()

    gee.init()
    extent = gee.grid_extent()
    keep_ids = set(pd.read_parquet(config.DIM_GRID, columns=["grid_id"]).grid_id)
    target = [date.fromisoformat(f"{args.month}-01")] if args.month else None
    gee.run_monthly(
        "satellite",
        config.RAW_SATELLITE,
        lambda mo: fetch_daily_month(mo, extent, keep_ids),
        overwrite=args.overwrite,
        workers=args.workers,
        target_months=target,
    )
    gee.run_monthly(
        "viirs",
        config.RAW_VIIRS,
        lambda mo: fetch_viirs_month(mo, extent, keep_ids),
        overwrite=args.overwrite,
        workers=args.workers,
        target_months=target,
    )


if __name__ == "__main__":
    main()
