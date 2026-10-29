"""Bảng chiều: dim_grid_1km, dim_date, dim_station.

- dim_grid_1km: ô 1 km (EPSG:3405) giao với ranh giới Hà Nội.
  grid_id = grid_{easting góc dưới-trái}_{northing góc dưới-trái}.
- dim_date: mỗi ngày Hà Nội trong phạm vi phân tích (01/01/2021 - 30/09/2026).
- dim_station: metadata trạm OpenAQ, kiểm tra tọa độ thực nằm trong đa giác ranh giới Hà Nội (is_boundary).
"""
from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import shapely

from src.common import config
from src.common.storage import write_parquet


def grid_id(easting_ll: float | int, northing_ll: float | int) -> str:
    return f"grid_{int(easting_ll)}_{int(northing_ll)}"


def point_to_grid_id(easting: float, northing: float) -> str:
    """Ô chứa một điểm (tọa độ mét EPSG:3405)."""
    m = config.CELL_M
    return grid_id(np.floor(easting / m) * m, np.floor(northing / m) * m)


def build_dim_grid(boundary_path=config.BOUNDARY, out_path=config.DIM_GRID) -> gpd.GeoDataFrame:
    m = config.CELL_M
    boundary = gpd.read_file(boundary_path).to_crs(config.GRID_CRS).union_all()
    xmin, ymin, xmax, ymax = boundary.bounds
    xs = np.arange(np.floor(xmin / m) * m, np.ceil(xmax / m) * m, m)
    ys = np.arange(np.floor(ymin / m) * m, np.ceil(ymax / m) * m, m)
    xx, yy = (a.ravel() for a in np.meshgrid(xs, ys))
    cells = shapely.box(xx, yy, xx + m, yy + m)

    keep = shapely.intersects(cells, boundary)
    cells, xx, yy = cells[keep], xx[keep], yy[keep]
    inside_area = shapely.area(shapely.intersection(cells, boundary)) / 1e6
    keep = inside_area > 0  # bỏ ô chỉ chạm cạnh
    cells, xx, yy, inside_area = cells[keep], xx[keep], yy[keep], inside_area[keep]

    cx, cy = xx + m / 2, yy + m / 2
    lon, lat = pyproj.Transformer.from_crs(config.GRID_CRS, "EPSG:4326", always_xy=True).transform(cx, cy)
    gdf = gpd.GeoDataFrame(
        {
            "grid_id": [grid_id(x, y) for x, y in zip(xx, yy)],
            "easting_m": cx.astype(int),
            "northing_m": cy.astype(int),
            "lon": np.round(lon, 6),
            "lat": np.round(lat, 6),
            "area_in_hanoi_km2": np.round(inside_area, 6),
            "centroid_in_hanoi": shapely.contains_xy(boundary, cx, cy),
        },
        geometry=cells,
        crs=config.GRID_CRS,
    ).sort_values("grid_id", ignore_index=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    gdf.to_parquet(tmp, index=False)
    tmp.replace(out_path)
    print(f"  -> dim_grid_1km: {len(gdf):,} ô")
    return gdf


def hanoi_season(month: int) -> str:
    if month in (11, 12, 1, 2):
        return "winter"
    if month in (3, 4):
        return "spring"
    if month in (5, 6, 7, 8):
        return "summer"
    return "autumn"


def build_dim_date(out_path=config.DIM_DATE) -> pd.DataFrame:
    days = pd.date_range(config.START_DATE, config.END_DATE, freq="D")
    df = pd.DataFrame(
        {
            "date_id": (days.year * 10000 + days.month * 100 + days.day).astype("int32"),
            "date": days.date,
            "year": days.year.astype("int16"),
            "month": days.month.astype("int8"),
            "day": days.day.astype("int8"),
            "day_of_week": (days.day_of_week + 1).astype("int8"),   # 1 = Thứ Hai
            "day_of_year": days.day_of_year.astype("int16"),
            "is_weekend": days.day_of_week >= 5,
            "season": [hanoi_season(mo) for mo in days.month],
        }
    )
    write_parquet(df, out_path)
    print(f"  -> dim_date: {len(df):,} ngày ({config.START_DATE} -> {config.END_DATE})")
    return df


def build_dim_station(
    locations_path=config.RAW_OPENAQ_LOCATIONS,
    boundary_path=config.BOUNDARY,
    dim_grid_path=config.DIM_GRID,
    out_path=config.DIM_STATION,
) -> pd.DataFrame:
    """Một dòng mỗi location OpenAQ; kiểm tra tọa độ trạm nằm trong ranh giới Hà Nội (is_boundary)."""
    if not locations_path.exists():
        raise FileNotFoundError("Thiếu metadata OpenAQ; chạy `python run.py fetch-openaq` trước.")
    if not dim_grid_path.exists():
        build_dim_grid(boundary_path=boundary_path, out_path=dim_grid_path)

    locations = json.loads(locations_path.read_text(encoding="utf-8"))["locations"]
    boundary = gpd.read_file(boundary_path).to_crs(config.GRID_CRS).union_all()
    grid_ids = set(pd.read_parquet(dim_grid_path, columns=["grid_id"]).grid_id)
    to_utm = pyproj.Transformer.from_crs("EPSG:4326", config.GRID_CRS, always_xy=True)

    rows = []
    for loc in locations:
        coords = loc.get("coordinates") or {}
        lon, lat = coords.get("longitude"), coords.get("latitude")
        if lon is None or lat is None:
            continue
        easting, northing = to_utm.transform(lon, lat)
        gid = point_to_grid_id(easting, northing)
        # Kiểm tra điểm tọa độ thực của trạm có nằm trong (hoặc trên biên) đa giác Hà Nội không
        is_boundary = bool(boundary.covers(shapely.Point(easting, northing)))
        params = sorted(
            {
                (s.get("parameter") or {}).get("name", "").lower()
                for s in loc.get("sensors", [])
                if (s.get("parameter") or {}).get("name")
            }
        )
        rows.append(
            {
                "station_id": f"openaq_{loc['id']}",
                "openaq_location_id": int(loc["id"]),
                "station_name": loc.get("name"),
                "provider": (loc.get("provider") or {}).get("name"),
                "owner": (loc.get("owner") or {}).get("name"),
                "sensor_tier": "reference" if loc.get("isMonitor") else "low_cost",
                "lon": float(lon),
                "lat": float(lat),
                "easting_m": round(float(easting), 1),
                "northing_m": round(float(northing), 1),
                "is_boundary": is_boundary,
                "grid_id": gid if (is_boundary and gid in grid_ids) else None,
                "parameters": ",".join(params),
                "datetime_first_utc": (loc.get("datetimeFirst") or {}).get("utc"),
                "datetime_last_utc": (loc.get("datetimeLast") or {}).get("utc"),
            }
        )
    df = pd.DataFrame(rows).sort_values("openaq_location_id", ignore_index=True)
    write_parquet(df, out_path)
    in_hanoi = int(df.is_boundary.sum()) if not df.empty else 0
    print(f"  -> dim_station: {len(df)} trạm ({in_hanoi} trạm có tọa độ nằm trong ranh giới Hà Nội)")
    return df


def build_all_dims() -> None:
    print("[dims]")
    build_dim_grid()
    build_dim_date()
    if config.RAW_OPENAQ_LOCATIONS.exists():
        build_dim_station()
    else:
        print("  (bỏ qua dim_station vì chưa có locations.json; sẽ tạo sau khi chạy fetch-openaq)")


if __name__ == "__main__":
    build_all_dims()
