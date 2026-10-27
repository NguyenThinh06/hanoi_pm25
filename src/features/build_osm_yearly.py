"""Build yearly Hanoi road features for the canonical grid.

Run after downloading Geofabrik's vietnam-YY0101-free.shp.zip archives for
2021-2025: python -m src.features.build_osm_yearly
The early-January snapshot is held fixed within its calendar year. The grid
remains one row per cell with 2021 baseline roads; the output table carries
the year-specific road values keyed by (grid_id, year).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from src.features.extract_static_features import ROOT, osm_snapshot_time, road_features

GRID = ROOT / "data/core/dim_grid_1km.parquet"
OSM_DIR = ROOT / "data/raw/static/osm"
OUTPUT = ROOT / "data/core/fct_grid_osm_yearly.parquet"
PROVENANCE = ROOT / "data/manifests/osm_yearly_v1.json"
YEARS = range(2021, 2026)
ROAD_COLUMNS = ("osm_primary_road_m", "osm_road_density_km_km2")


def hashes(path: Path) -> tuple[str, str]:
    sha = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            sha.update(block)
            md5.update(block)
    return sha.hexdigest(), md5.hexdigest()


def validate_yearly(yearly: pd.DataFrame, real: gpd.GeoDataFrame) -> None:
    if len(yearly) != 18_050 or yearly.duplicated(["grid_id", "year"]).any():
        raise ValueError("Grid-year keys are incomplete or duplicated")
    if set(yearly.year) != set(YEARS):
        raise ValueError("Unexpected annual OSM years")
    for year in YEARS:
        if set(yearly.loc[yearly.year == year, "grid_id"]) != set(real.grid_id):
            raise ValueError(f"Annual OSM grid IDs differ from TV1 in {year}")
    if yearly[list(ROAD_COLUMNS)].isna().any().any():
        raise ValueError("Missing road feature")
    if (yearly[list(ROAD_COLUMNS)] < 0).any().any():
        raise ValueError("Road lengths/density must be nonnegative")


def main() -> None:
    grid = gpd.read_parquet(GRID)
    if grid.crs is None or grid.crs.to_epsg() != 3405:
        raise ValueError("Grid must be EPSG:3405")
    real = grid[grid.grid_id != "grid_unknown"]
    if len(real) != 3610 or not real.grid_id.is_unique:
        raise ValueError("Expected 3,610 distinct real cells")

    records = []
    sources = []
    for year in YEARS:
        tag = f"{year % 100:02d}0101"
        archive = OSM_DIR / f"vietnam-{tag}-free.shp.zip"
        if not archive.exists():
            raise FileNotFoundError(archive)
        sha256, md5 = hashes(archive)
        sidecar = archive.with_suffix(archive.suffix + ".md5")
        if sidecar.exists() and sidecar.read_text().split()[0].lower() != md5:
            raise ValueError(f"Geofabrik checksum failed: {archive}")
        snapshot = osm_snapshot_time(archive)
        if not snapshot.startswith(str(year)):
            raise ValueError(f"Wrong archive year: {archive}: {snapshot}")
        features = road_features(grid, archive)
        if len(features) != len(real):
            raise ValueError(f"Incomplete road features in {year}")
        for grid_id in real.grid_id:
            records.append({"grid_id": grid_id, "year": year, **features[grid_id]})
        sources.append({"year": year, "archive": str(archive.relative_to(ROOT)),
                        "snapshot_utc": snapshot, "size_bytes": archive.stat().st_size,
                        "sha256": sha256, "geofabrik_md5": md5})
        print(f"[OSM] {year}: {len(features):,} grid cells; snapshot {snapshot}", flush=True)
    yearly = pd.DataFrame.from_records(records)
    yearly["year"] = yearly["year"].astype(np.int32)
    for name in ROAD_COLUMNS:
        yearly[name] = yearly[name].astype(np.float32)
    validate_yearly(yearly, real)
    baseline = yearly[yearly.year == 2021].set_index("grid_id")
    reference = real.set_index("grid_id")
    for name in ROAD_COLUMNS:
        if not np.array_equal(baseline.loc[reference.index, name].to_numpy(),
                              reference[name].to_numpy()):
            raise ValueError(f"Static dim baseline differs from yearly 2021: {name}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT.with_name(OUTPUT.name + f".tmp_{os.getpid()}")
    try:
        yearly.to_parquet(tmp, compression="zstd", index=False)
        if pq.read_metadata(tmp).num_rows != 18_050:
            raise ValueError("Yearly Parquet row count mismatch")
        os.replace(tmp, OUTPUT)
    finally:
        tmp.unlink(missing_ok=True)
    manifest = {
        "grain": "grid_id, year", "rows": len(yearly),
        "grid_crs": "EPSG:3405", "road_columns": list(ROAD_COLUMNS),
        "annual_policy": "early-January OSM snapshot is assigned to its calendar year; approximate annual representation, not exact daily as-of history",
        "cell_policy": "full 1 km TV1 squares; lines clipped to square; density km / 1 km2",
        "primary_classes": ["motorway", "primary", "trunk"],
        "static_dim_policy": "canonical grid has one row per grid_id and 2021 baseline roads",
        "mart_policy": "join canonical grid by grid_id and yearly OSM by (grid_id, date year); WorldCover 2021 and DEM stay fixed",
        "sources": sources,
    }
    PROVENANCE.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[OSM] Wrote {OUTPUT} ({len(yearly):,} grid-years)")


if __name__ == "__main__":
    main()
