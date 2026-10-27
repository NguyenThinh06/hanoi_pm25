"""
src/common/spatial_spine.py
Tạo Lưới không gian 1km x 1km chuẩn hóa cho Hà Nội trong hệ tọa độ phẳng mét EPSG:3405.
Lọc các ô giao file ranh giới đã lưu (data/reference/hanoi_boundary.geojson).
Đóng băng metadata và mã băm SHA-256 vào data/manifests/grid_manifest.json.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely.geometry as sg

from src.common.io_parquet import atomic_write_parquet
from src.common.spine_contract import GRID_UNKNOWN, REAL_DAYS, date_metadata


def generate_hanoi_grid(
    cell_size_m: int = 1000,
    boundary_path="data/reference/hanoi_boundary.geojson",
    manifest_path="data/manifests/grid_manifest.json",
    output_parquet="data/core/dim_grid_1km.parquet",
):
    if cell_size_m != 1000:
        raise ValueError("The frozen analysis contract requires 1000 metre cells")

    if not os.path.exists(boundary_path):
        raise FileNotFoundError(f"Missing boundary file {boundary_path}!")

    # 1. Tinh ma bam SHA-256 cua file ranh gioi goc
    with open(boundary_path, "rb") as f:
        boundary_sha256 = hashlib.sha256(f.read()).hexdigest()
    reference = Path(__file__).resolve().parents[2] / "data/reference/hanoi_boundary.geojson"
    if Path(boundary_path).resolve() == reference:
        provenance = json.loads(reference.with_suffix(".provenance.json").read_text(encoding="utf-8"))
        if boundary_sha256 != provenance["sha256"]:
            raise ValueError("Boundary checksum differs from the reviewed provenance")
    print(f"[GRID] Loaded Hanoi boundary (SHA-256: {boundary_sha256[:12]}...)")

    # 2. Doc va chuyen he quy chieu sang EPSG:3405 (chuan met Viet Nam)
    gdf_boundary = gpd.read_file(boundary_path)
    if gdf_boundary.crs is None:
        raise ValueError("Boundary CRS is missing; do not guess the source CRS")
    if (gdf_boundary.empty or gdf_boundary.geometry.isna().any()
            or gdf_boundary.geometry.is_empty.any()
            or not gdf_boundary.geometry.is_valid.all()
            or not gdf_boundary.geom_type.isin(["Polygon", "MultiPolygon"]).all()):
        raise ValueError("Boundary must contain valid nonempty polygons")
    if gdf_boundary.crs.to_epsg() != 3405:
        gdf_boundary = gdf_boundary.to_crs("EPSG:3405")

    # Hop nhat da giac dia gioi (dung union_all tranh deprecation)
    if hasattr(gdf_boundary, "union_all"):
        boundary_union = gdf_boundary.union_all()
    else:
        boundary_union = gdf_boundary.unary_union
    xmin, ymin, xmax, ymax = gdf_boundary.total_bounds

    # 3. Chia buoc nhay 1.000m theo boi so tron
    # Pad one cell: intersects includes cells touching an exactly aligned outer edge.
    x_start = np.floor(xmin / cell_size_m) * cell_size_m - cell_size_m
    x_end = np.ceil(xmax / cell_size_m) * cell_size_m + cell_size_m
    y_start = np.floor(ymin / cell_size_m) * cell_size_m - cell_size_m
    y_end = np.ceil(ymax / cell_size_m) * cell_size_m + cell_size_m

    x_coords = np.arange(x_start, x_end, cell_size_m)
    y_coords = np.arange(y_start, y_end, cell_size_m)

    print(f"[GRID] Scanning and clipping bounding box {len(x_coords)} x {len(y_coords)} cells...")
    grid_cells = []
    canonical_count = 0
    boundary_touch_only_cells = 0

    for x in x_coords:
        for y in y_coords:
            poly = sg.box(x, y, x + cell_size_m, y + cell_size_m)
            # Chi giu lai o co giao thoa voi dia phan Ha Noi
            if poly.intersects(boundary_union):
                is_canonical = 1 if poly.centroid.within(boundary_union) else 0
                if is_canonical:
                    canonical_count += 1

                inter_area_km2 = poly.intersection(boundary_union).area / 1e6
                if inter_area_km2 == 0:
                    boundary_touch_only_cells += 1

                grid_cells.append({
                    "grid_id": f"grid_{int(x)}_{int(y)}",
                    "easting_m": int(x + cell_size_m / 2),
                    "northing_m": int(y + cell_size_m / 2),
                    "is_canonical": is_canonical,
                    "area_in_boundary_km2": inter_area_km2,
                    "geometry": poly
                })

    # Them 1 dong ngoai le grid_unknown
    grid_cells.append({
        "grid_id": GRID_UNKNOWN,
        "easting_m": -1,
        "northing_m": -1,
        "is_canonical": 0,
        "area_in_boundary_km2": 0.0,
        "geometry": None
    })

    gdf = gpd.GeoDataFrame(grid_cells, crs="EPSG:3405")
    total_cells = len(gdf)
    real_cells = total_cells - 1
    if real_cells == 0 or gdf.grid_id.isna().any() or not gdf.grid_id.is_unique:
        raise ValueError("Grid dimension must have nonempty, unique real cell IDs")

    print("[GRID] Spatial clipping completed:")
    print(f"  -> Total real grid cells: {real_cells} (plus 1 unknown = {total_cells} cells)")
    print(f"  -> Canonical cells (centroid within): {canonical_count} cells")

    # 4. Dong bang manifest chuan
    manifest_data = {
        "grid_crs": "EPSG:3405",
        "cell_size_m": cell_size_m,
        "total_cells": total_cells,
        "real_cells": real_cells,
        "canonical_cells": canonical_count,
        "analysis_grid_rule": "intersects_boundary",
        "analysis_grid_count": real_cells,
        "analysis_grid_filter": "grid_id != 'grid_unknown'",
        "grid_unknown_id": GRID_UNKNOWN,
        "boundary_touch_only_cells": boundary_touch_only_cells,
        "geometry_policy": "full_1000m_square; unknown_geometry=null",
        "canonical_rule": "centroid.within(boundary_union); excludes boundary points",
        "grid_origin_m": [0, 0],
        "candidate_padding_cells": 1,
        "grid_id_rule": "grid_{lower_left_easting_integer}_{lower_left_northing_integer}",
        "aligned_bounds_utm": [float(x_start), float(y_start), float(x_end), float(y_end)],
        "boundary_file": Path(boundary_path).as_posix(),
        "boundary_sha256": boundary_sha256,
        "boundary_provenance_file": "data/reference/hanoi_boundary.provenance.json",
        **date_metadata(),
        "expected_grid_day_rows": real_cells * REAL_DAYS,
        "bounds_utm": [float(xmin), float(ymin), float(xmax), float(ymax)],
        "created_by": "ngthinh06",
        "version": "2.0"
    }
    # Publish the manifest only after successfully writing the dimension.
    atomic_write_parquet(gdf, output_parquet)
    Path(manifest_path).parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # 5. Xuat file Parquet nguyen tu
    print(f"[GRID] Saved {output_parquet} and froze manifest at {manifest_path}")
    return gdf, manifest_data


if __name__ == "__main__":
    generate_hanoi_grid()
