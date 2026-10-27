"""Enrich TV1's frozen 1 km grid with the eight TV2 baseline features.

Run from the repository root: python -m src.features.extract_static_features
The canonical grid's OSM columns use the early-2021 snapshot. Annual OSM grids
are built separately by src.features.build_osm_yearly.
"""
from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pyogrio
import rasterio
from rasterio.windows import from_bounds
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[2]
GRID = ROOT / "data/core/dim_grid_1km.parquet"
OSM = ROOT / "data/raw/static/osm/vietnam-210101-free.shp.zip"
WORLDCOVER = ROOT / "data/raw/static/worldcover/hanoi_worldcover_2021.tif"
ELEVATION = ROOT / "data/raw/static/srtm/hanoi_srtm_elevation.tif"
SLOPE = ROOT / "data/raw/static/srtm/hanoi_srtm_slope.tif"
PROVENANCE = ROOT / "data/manifests/static_features_v1_1.json"
STATIC_COLUMNS = (
    "osm_primary_road_m", "osm_road_density_km_km2",
    "worldcover_builtup_ratio", "worldcover_tree_ratio",
    "worldcover_cropland_ratio", "worldcover_water_ratio",
    "dem_elevation_mean_m", "dem_slope_mean_deg",
)
PRIMARY_CLASSES = {"motorway", "trunk", "primary"}
WORLDCOVER_CLASSES = {50: "worldcover_builtup_ratio", 10: "worldcover_tree_ratio",
                      40: "worldcover_cropland_ratio", 80: "worldcover_water_ratio"}
VALID_WORLDCOVER_CLASSES = {10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pixel_values(dataset: rasterio.io.DatasetReader, geometry):
    """Return raster pixels whose centres are inside the full TV1 square."""
    left, bottom, right, top = geometry.bounds
    window = from_bounds(left, bottom, right, top, dataset.transform)
    window = window.round_offsets().round_lengths()
    window = window.intersection(rasterio.windows.Window(0, 0, dataset.width, dataset.height))
    if window.width <= 0 or window.height <= 0:
        return np.empty(0, dtype=np.float32)
    values = dataset.read(1, window=window, masked=True)
    if dataset.res[0] == 10 and dataset.res[1] == 10:
        return values.compressed()
    from rasterio.features import geometry_mask
    mask = geometry_mask([geometry], out_shape=values.shape,
                         transform=dataset.window_transform(window), invert=True)
    return values[mask].compressed()


def osm_snapshot_time(archive: Path) -> str:
    with zipfile.ZipFile(archive) as source:
        readme = source.read("README").decode("utf-8")
    marker = "data as of "
    if marker not in readme:
        raise ValueError(f"OSM archive lacks snapshot timestamp: {archive}")
    return readme.split(marker, 1)[1].split(".", 1)[0].strip()


def road_features(grid: gpd.GeoDataFrame, archive: Path) -> dict[str, dict[str, float]]:
    """Clip all OSM road lines to each full 1 km square in EPSG:3405."""
    real = grid[grid.grid_id != "grid_unknown"]
    bbox_wgs84 = real.to_crs(4326).total_bounds
    zip_layer = f"/vsizip/{archive}/gis_osm_roads_free_1.shp"
    roads = pyogrio.read_dataframe(zip_layer, bbox=tuple(bbox_wgs84),
                                   columns=["fclass"])
    if roads.crs is None or "fclass" not in roads:
        raise ValueError("OSM roads need a CRS and fclass")
    roads = roads.to_crs(grid.crs)
    roads = roads[roads.geometry.notna() & ~roads.geometry.is_empty]
    print(f"[STATIC] OSM roads near Hanoi ({archive.name}): {len(roads):,}", flush=True)
    road_index = roads.sindex
    result = {}
    for count, (_, row) in enumerate(real.iterrows(), 1):
        cell = row.geometry
        road_lengths = [(roads.iloc[position].fclass,
                         roads.geometry.iloc[position].intersection(cell).length)
                        for position in road_index.query(cell, predicate="intersects")]
        total_m = sum(length for _, length in road_lengths)
        primary_m = sum(length for road_class, length in road_lengths
                        if road_class in PRIMARY_CLASSES)
        result[row.grid_id] = {"osm_primary_road_m": primary_m,
                               "osm_road_density_km_km2": total_m / 1000.0}
        if count % 1000 == 0:
            print(f"[STATIC] Roads processed {count:,}/3,610 cells", flush=True)
    return result


def build() -> None:
    grid = gpd.read_parquet(GRID)
    if grid.crs is None or grid.crs.to_epsg() != 3405:
        raise ValueError("TV1 grid must be GeoParquet EPSG:3405")
    if len(grid) != 3611 or not grid.grid_id.is_unique or grid.grid_id.isna().any():
        raise ValueError("TV1 grid must contain 3610 distinct real cells plus grid_unknown")
    if grid.grid_id.eq("grid_unknown").sum() != 1:
        raise ValueError("Missing or duplicate grid_unknown")
    existing = set(STATIC_COLUMNS).intersection(grid.columns)
    if existing and existing != set(STATIC_COLUMNS):
        raise ValueError(f"Grid has only some static features: {sorted(existing)}")
    if existing:
        grid = grid.drop(columns=list(STATIC_COLUMNS))

    real = grid[grid.grid_id != "grid_unknown"]
    if real.geometry.isna().any() or not real.geometry.is_valid.all():
        raise ValueError("Invalid real grid geometry")
    roads_by_grid = road_features(grid, OSM)

    result = {column: [None] * len(grid) for column in STATIC_COLUMNS}
    with rasterio.open(WORLDCOVER) as cover, rasterio.open(ELEVATION) as dem, rasterio.open(SLOPE) as slope:
        for dataset in (cover, dem, slope):
            if dataset.crs.to_epsg() != 3405:
                raise ValueError(f"Raster CRS differs from grid: {dataset.name}")
        for count, (index, row) in enumerate(real.iterrows(), 1):
            cell = row.geometry
            if not cell.equals(box(*cell.bounds)) or abs(cell.area - 1_000_000) > 0.01:
                raise ValueError(f"Invalid 1 km square: {row.grid_id}")
            road_values = roads_by_grid[row.grid_id]
            result["osm_primary_road_m"][index] = road_values["osm_primary_road_m"]
            result["osm_road_density_km_km2"][index] = road_values["osm_road_density_km_km2"]

            cover_pixels = pixel_values(cover, cell)
            valid = np.isin(cover_pixels, list(VALID_WORLDCOVER_CLASSES))
            valid_count = int(valid.sum())
            for class_code, name in WORLDCOVER_CLASSES.items():
                result[name][index] = (float(np.count_nonzero(cover_pixels[valid] == class_code))
                                       / valid_count if valid_count else None)
            for dataset, name in ((dem, "dem_elevation_mean_m"),
                                  (slope, "dem_slope_mean_deg")):
                pixels = pixel_values(dataset, cell)
                pixels = pixels[np.isfinite(pixels)]
                result[name][index] = float(pixels.mean()) if len(pixels) else None
            if count % 500 == 0:
                print(f"[STATIC] Processed {count:,}/3,610 cells", flush=True)

    for column, values in result.items():
        grid[column] = np.array(values, dtype=np.float32)
    for column in WORLDCOVER_CLASSES.values():
        valid_values = grid.loc[grid.grid_id != "grid_unknown", column].dropna()
        if not valid_values.between(0, 1).all():
            raise ValueError(f"Invalid ratio in {column}")
    if any(grid.loc[grid.grid_id != "grid_unknown", name].isna().any()
           for name in STATIC_COLUMNS):
        raise ValueError("Some real cells lack a static feature; check source coverage")

    source_hashes = {str(path.relative_to(ROOT)): sha256(path)
                     for path in (OSM, WORLDCOVER, ELEVATION, SLOPE)}
    provenance = {
        "version": "v1.1-tv2", "grid_rows": len(grid),
        "grid_crs": "EPSG:3405", "static_columns": list(STATIC_COLUMNS),
        "source_sha256": source_hashes,
        "worldcover_epoch": 2021,
        "worldcover_ratio_denominator": "all valid classified 2021 pixels in full 1 km cell",
        "raster_pixel_rule": "pixel centre inside full 1 km cell; no boundary-area weighting",
        "osm_snapshot_utc": osm_snapshot_time(OSM),
        "osm_temporal_note": "Canonical grid is the early-2021 baseline; fct_grid_osm_yearly carries OSM values for each calendar year",
        "osm_primary_classes": sorted(PRIMARY_CLASSES),
        "osm_primary_road_m": "sum of clipped lengths in metres",
        "osm_road_density_km_km2": "sum of all clipped road lengths (km) / full cell area (1 km2)",
        "grid_unknown_rule": "all new feature columns NULL",
    }
    tmp = GRID.with_name(GRID.name + f".tmp_{os.getpid()}")
    try:
        grid.to_parquet(tmp, compression="zstd")
        written = gpd.read_parquet(tmp)
        if len(written) != 3611 or not written.grid_id.equals(grid.grid_id):
            raise ValueError("Round-trip grid verification failed")
        os.replace(tmp, GRID)
    finally:
        tmp.unlink(missing_ok=True)
    PROVENANCE.parent.mkdir(parents=True, exist_ok=True)
    PROVENANCE.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(f"[STATIC] Wrote {GRID} ({len(grid):,} rows, {len(STATIC_COLUMNS)} features)")


if __name__ == "__main__":
    build()
