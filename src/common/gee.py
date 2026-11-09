"""Tiện ích Google Earth Engine dùng chung cho fetch_meteo và fetch_satellite.

Ý tưởng chính: yêu cầu GEE trả về ảnh raster đúng lưới 1 km EPSG:3405 của dự án
(ee.data.computePixels), nên mỗi pixel trả về chính là một ô `grid_id`.
Tổng hợp theo ngày Hà Nội (00:00–24:00 giờ +07) được thực hiện trên server GEE.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import ee
import numpy as np
import pandas as pd
from dotenv import load_dotenv

from src.common import config
from src.common.storage import write_parquet

NODATA = -9999.0
DAYS_PER_REQUEST = 10         # 3-4 request cho mỗi tháng 30-31 ngày


def init() -> None:
    load_dotenv(config.ROOT / ".env")
    project = (os.getenv("GEE_PROJECT") or "").strip()
    if not project:
        raise SystemExit("Thiếu GEE_PROJECT trong .env (Google Cloud project đã bật Earth Engine)")
    ee.Initialize(project=project)


def grid_extent() -> tuple[int, int, int, int]:
    """(xmin, ymin, xmax, ymax) theo mét của toàn bộ ô trong dim_grid_1km."""
    if not config.DIM_GRID.exists():
        raise FileNotFoundError("Thiếu dim_grid_1km; chạy `python run.py dims` trước.")
    g = pd.read_parquet(config.DIM_GRID, columns=["easting_m", "northing_m"])
    half = config.CELL_M // 2
    return (
        int(g.easting_m.min() - half),
        int(g.northing_m.min() - half),
        int(g.easting_m.max() + half),
        int(g.northing_m.max() + half),
    )


def local_day_window(day: date) -> tuple[ee.Date, ee.Date]:
    """Khoảng UTC của một ngày Hà Nội: [day 00:00+07, day+1 00:00+07)."""
    start = ee.Date(day.isoformat()).advance(-config.UTC_OFFSET_HOURS, "hour")
    return start, start.advance(1, "day")


def safe_reduce(collection: ee.ImageCollection, band: str) -> ee.ImageCollection:
    """Thêm 1 ảnh rỗng (mask toàn bộ) để mean()/count() không lỗi khi ngày không có ảnh."""
    empty = ee.Image.constant(0).toFloat().rename(band).updateMask(0)
    return collection.select([band]).map(lambda i: i.toFloat()).merge(ee.ImageCollection([empty]))


def compute_pixels(image: ee.Image, extent: tuple[int, int, int, int]) -> dict[str, np.ndarray]:
    """Tải ảnh nhiều band về dạng numpy trên đúng lưới 1 km; NODATA -> NaN."""
    xmin, ymin, xmax, ymax = extent
    m = config.CELL_M
    request = {
        "expression": image.toFloat().unmask(NODATA, False),
        "fileFormat": "NUMPY_NDARRAY",
        "grid": {
            "dimensions": {"width": (xmax - xmin) // m, "height": (ymax - ymin) // m},
            "affineTransform": {
                "scaleX": m, "shearX": 0, "translateX": xmin,
                "shearY": 0, "scaleY": -m, "translateY": ymax,
            },
            "crsCode": config.GRID_CRS,
        },
    }
    for attempt in range(6):
        try:
            arr = ee.data.computePixels(request)
            break
        except ee.EEException as e:
            if attempt == 5:
                raise
            print(f"  [gee] thử lại sau lỗi: {e}")
            time.sleep(10 * (attempt + 1))
    return {name: np.where(arr[name] == NODATA, np.nan, arr[name]) for name in arr.dtype.names}


def pixel_grid_ids(extent: tuple[int, int, int, int]) -> np.ndarray:
    """grid_id của từng pixel (hàng 0 là phía Bắc), cùng thứ tự với compute_pixels."""
    xmin, ymin, xmax, ymax = extent
    m = config.CELL_M
    xs = np.arange(xmin, xmax, m)
    ys = np.arange(ymax - m, ymin - 1, -m)      # góc dưới-trái của từng hàng, từ Bắc xuống Nam
    return np.array([[f"grid_{x}_{y}" for x in xs] for y in ys])


def fetch_daily(
    day_image: Callable[[date], ee.Image],
    variables: list[str],
    first_day: date,
    last_day: date,
    extent: tuple[int, int, int, int],
    keep_grid_ids: set[str] | None = None,
) -> pd.DataFrame:
    """Gọi `day_image(day)` cho từng ngày (band = variables), trả về bảng dài grid_id × date."""
    ids = pixel_grid_ids(extent).ravel()
    mask = np.isin(ids, list(keep_grid_ids)) if keep_grid_ids is not None else slice(None)
    kept_ids = ids[mask]

    frames = []
    day = first_day
    while day <= last_day:
        chunk = [day + timedelta(d) for d in range(DAYS_PER_REQUEST) if day + timedelta(d) <= last_day]
        image = ee.Image.cat([day_image(d).select(variables, [f"{v}__{d:%Y%m%d}" for v in variables]) for d in chunk])
        arrays = compute_pixels(image, extent)
        for d in chunk:
            frame = pd.DataFrame({"grid_id": kept_ids, "date": d})
            for v in variables:
                frame[v] = arrays[f"{v}__{d:%Y%m%d}"].ravel()[mask].astype("float32")
            frames.append(frame)
        day = chunk[-1] + timedelta(days=1)
    return pd.concat(frames, ignore_index=True)


def run_monthly(
    name: str,
    out_dir: Path,
    fetch_month: Callable[[date], pd.DataFrame | None],
    overwrite: bool = False,
    workers: int = 4,
    target_months: list[date] | None = None,
) -> None:
    """Chạy song song theo tháng, mỗi tháng một file <name>_YYYY-MM.parquet; bỏ qua tháng đã có."""
    all_months = target_months if target_months is not None else config.months()
    todo = [mo for mo in all_months if overwrite or not (out_dir / f"{name}_{mo:%Y-%m}.parquet").exists()]
    print(f"[{name}] cần tải {len(todo)}/{len(all_months)} tháng", flush=True)
    if not todo:
        return

    def job(month: date) -> str:
        df = fetch_month(month)
        if df is None or df.empty:
            return f"{month:%Y-%m}: nguồn chưa có dữ liệu, bỏ qua"
        write_parquet(df, out_dir / f"{name}_{month:%Y-%m}.parquet")
        return f"{month:%Y-%m}: {len(df):,} dòng"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(job, mo): mo for mo in todo}
        for i, f in enumerate(as_completed(futures), 1):
            mo = futures[f]
            try:
                print(f"[{name}] ({i}/{len(todo)}) {f.result()}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[{name}] ({i}/{len(todo)}) {mo:%Y-%m} LỖI: {exc}", flush=True)


def month_days(month: date) -> tuple[date, date]:
    nxt = date(month.year + month.month // 12, month.month % 12 + 1, 1)
    return month, min(nxt - timedelta(days=1), config.END_DATE)
