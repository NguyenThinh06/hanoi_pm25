"""
src/common/spatial_spine.py
Tạo Lưới không gian 1km x 1km cho Hà Nội trong hệ tọa độ phẳng mét EPSG:3405.
Đóng băng metadata vào data/manifests/grid_manifest.json.
"""
from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import shapely.geometry as sg

from src.common.io_parquet import atomic_write_parquet


def generate_hanoi_grid(cell_size_m: int = 1000):
    manifest_path = "data/manifests/grid_manifest.json"
    output_parquet = "data/core/dim_grid_1km.parquet"

    # Khung toa do phang UTM Zone 48N (EPSG:3405) bao phu toan bo dia gioi Ha Noi
    # Toa do X: 520,000m -> 605,000m (85km)
    # Toa do Y: 2,270,000m -> 2,370,000m (100km)
    xmin, xmax = 520000, 605000
    ymin, ymax = 2270000, 2370000

    x_coords = np.arange(xmin, xmax, cell_size_m)
    y_coords = np.arange(ymin, ymax, cell_size_m)

    grid_cells = []
    for x in x_coords:
        for y in y_coords:
            poly = sg.box(x, y, x + cell_size_m, y + cell_size_m)
            grid_cells.append({
                "grid_id": f"grid_{int(x)}_{int(y)}",
                "easting_m": int(x + cell_size_m / 2),
                "northing_m": int(y + cell_size_m / 2),
                "geometry": poly
            })

    gdf = gpd.GeoDataFrame(grid_cells, crs="EPSG:3405")
    total_cells = len(gdf)
    print(f"[GRID] Successfully generated {total_cells} cells (1km x 1km).")

    # Dong bang manifest de ca nhom dung chung, tuyet doi khong hardcode
    manifest_data = {
        "grid_crs": "EPSG:3405",
        "cell_size_m": cell_size_m,
        "total_cells": total_cells,
        "bounds_utm": [xmin, ymin, xmax, ymax],
        "created_by": "ngthinh06",
        "version": "1.0"
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    # Xuat file Parquet nguyen tu
    atomic_write_parquet(gdf, output_parquet)
    print(f"[GRID] Saved {output_parquet} and froze manifest at {manifest_path}")


if __name__ == "__main__":
    generate_hanoi_grid()
