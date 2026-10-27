"""Export the TV1 analysis grid as a WGS84 WKT table for Earth Engine.

Run: python src/ingest/build_gee_grid_csv.py
Requires: pyarrow, shapely, pyproj.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pyarrow.parquet as pq
from pyproj import Transformer
from shapely import from_wkb
from shapely.ops import transform

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/core/dim_grid_1km.parquet"
TARGET = ROOT / "data/raw/earth_observation/gee_assets/tv1_grid_1km.csv"


def main() -> None:
    table = pq.read_table(SOURCE, columns=["grid_id", "geometry"])
    project = Transformer.from_crs("EPSG:3405", "EPSG:4326", always_xy=True).transform
    rows = []
    for row in table.to_pylist():
        if row["grid_id"] == "grid_unknown":
            continue
        geometry = from_wkb(row["geometry"])
        if geometry.is_empty or geometry.area != 1_000_000:
            raise ValueError(f"Not a full 1 km square: {row['grid_id']}")
        rows.append((row["grid_id"], transform(project, geometry).wkt))

    if len(rows) != 3610 or len({grid_id for grid_id, _ in rows}) != 3610:
        raise ValueError("Expected exactly 3,610 distinct analysis grid cells")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with TARGET.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(["grid_id", "geometry"])
        writer.writerows(rows)
    print(f"Wrote {len(rows)} TV1 cells to {TARGET}")


if __name__ == "__main__":
    main()
