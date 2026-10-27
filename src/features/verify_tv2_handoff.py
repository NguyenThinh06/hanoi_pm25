"""Check the TV2 handoff artifacts and write a reproducible validation report.

Run after both TV2 pipelines: python -m src.features.verify_tv2_handoff
This checks local data only; it does not approve the project-wide contract.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "data/core"
STAGING = ROOT / "data/staging"
MANIFESTS = ROOT / "data/manifests"
YEARS = range(2021, 2026)
ROAD_COLUMNS = ("osm_primary_road_m", "osm_road_density_km_km2")
FEATURE_COLUMNS = ROAD_COLUMNS + (
    "worldcover_builtup_ratio", "worldcover_tree_ratio",
    "worldcover_cropland_ratio", "worldcover_water_ratio",
    "dem_elevation_mean_m", "dem_slope_mean_deg",
)
EXPECTED_GRID_ROWS = 3_611
EXPECTED_REAL_CELLS = 3_610
EXPECTED_GRID_DAYS = 6_591_860


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sql_path(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def check_grid(grid: gpd.GeoDataFrame, name: str) -> None:
    require(len(grid) == EXPECTED_GRID_ROWS, f"{name}: wrong row count")
    require(grid.grid_id.is_unique and grid.grid_id.notna().all(),
            f"{name}: duplicate or NULL grid_id")
    require(grid.grid_id.eq("grid_unknown").sum() == 1,
            f"{name}: expected one grid_unknown")
    require(grid.crs is not None and grid.crs.to_epsg() == 3405,
            f"{name}: CRS must be EPSG:3405")
    require(set(FEATURE_COLUMNS).issubset(grid.columns),
            f"{name}: missing TV2 feature columns")
    real = grid[grid.grid_id != "grid_unknown"]
    require(len(real) == EXPECTED_REAL_CELLS, f"{name}: wrong real-cell count")
    require(real[list(FEATURE_COLUMNS)].notna().all().all(),
            f"{name}: NULL TV2 feature in a real cell")
    require(grid.loc[grid.grid_id == "grid_unknown", list(FEATURE_COLUMNS)].isna().all().all(),
            f"{name}: grid_unknown TV2 features must be NULL")
    ratio_columns = [column for column in FEATURE_COLUMNS if column.startswith("worldcover_")]
    require(real[ratio_columns].ge(0).all().all() and real[ratio_columns].le(1).all().all(),
            f"{name}: WorldCover ratio outside [0, 1]")
    require(real[list(ROAD_COLUMNS)].ge(0).all().all(),
            f"{name}: negative road length or density")
    require(real["osm_road_density_km_km2"].le(100).all(),
            f"{name}: road density exceeds draft contract range")
    require(real["dem_elevation_mean_m"].between(-10, 1400).all()
            and real["dem_slope_mean_deg"].between(0, 90).all(),
            f"{name}: DEM feature outside expected range")
    require(real.geometry.notna().all() and real.geometry.is_valid.all(),
            f"{name}: invalid real-cell geometry")


def check_osm_yearly() -> dict:
    base = gpd.read_parquet(CORE / "dim_grid_1km.parquet")
    check_grid(base, "dim_grid_1km")
    require(not any(f"{road}_{year}" in base.columns
                    for road in ROAD_COLUMNS for year in YEARS),
            "Canonical grid still has obsolete year-suffixed OSM columns")
    yearly = pd.read_parquet(CORE / "fct_grid_osm_yearly.parquet")
    require(len(yearly) == EXPECTED_REAL_CELLS * len(YEARS),
            "OSM yearly table has wrong row count")
    require(not yearly.duplicated(["grid_id", "year"]).any(),
            "OSM yearly table has duplicate keys")
    expected_ids = set(base.loc[base.grid_id != "grid_unknown", "grid_id"])
    require(set(yearly.columns) == {"grid_id", "year", *ROAD_COLUMNS},
            "OSM yearly table has unexpected columns")
    require(set(yearly.year) == set(YEARS), "OSM yearly table has wrong years")
    require(yearly[list(ROAD_COLUMNS)].notna().all().all()
            and yearly[list(ROAD_COLUMNS)].ge(0).all().all(),
            "OSM yearly table has NULL or negative features")
    summaries = {}
    for year in YEARS:
        source = yearly[yearly.year == year].set_index("grid_id").sort_index()
        require(set(source.index) == expected_ids, f"{year}: OSM grid IDs differ")
        if year == 2021:
            base_by_id = base[base.grid_id != "grid_unknown"].set_index("grid_id")
            for column in ROAD_COLUMNS:
                require(np.array_equal(base_by_id.loc[source.index, column].to_numpy(),
                                       source[column].to_numpy()),
                        f"Canonical grid {column} differs from 2021 OSM baseline")
        summaries[str(year)] = {"rows": len(source),
                                "mean_road_density_km_km2": float(source[ROAD_COLUMNS[1]].mean())}
    return {"canonical_grid_rows": len(base), "osm_grid_year_rows": len(yearly),
            "osm_years": summaries}


def check_satellite() -> dict:
    con = duckdb.connect()
    con.execute(f"CREATE VIEW grid AS SELECT * FROM read_parquet({sql_path(CORE / 'dim_grid_1km.parquet')})")
    con.execute(f"CREATE VIEW dates AS SELECT * FROM read_parquet({sql_path(CORE / 'dim_date.parquet')})")
    con.execute(f"CREATE VIEW sat AS SELECT * FROM read_parquet({sql_path(CORE / 'fct_grid_satellite_daily.parquet')})")
    con.execute(f"CREATE VIEW stg AS SELECT * FROM read_parquet({sql_path(STAGING / 'stg_satellite_daily.parquet')})")
    fact_columns = [column[0] for column in con.execute("DESCRIBE sat").fetchall()]
    require(fact_columns == ["grid_id", "date_id", "aod_047_mean",
                             "is_aod_missing_mnar", "no2_tropospheric_mol_m2",
                             "viirs_nightlight_rad"],
            "Satellite fact schema differs from the TV2 contract")
    date_count = con.execute("SELECT count(*), count(DISTINCT date_id) "
                             "FROM dates WHERE date_id != -1").fetchone()
    require(date_count == (1_826, 1_826), "TV1 date dimension is not 1,826 unique days")
    row = con.execute("""SELECT count(*), count(DISTINCT (grid_id, date_id)),
        count(aod_047_mean), count(no2_tropospheric_mol_m2),
        count(viirs_nightlight_rad),
        count(*) FILTER (WHERE (aod_047_mean IS NULL AND is_aod_missing_mnar != 1)
                         OR (aod_047_mean IS NOT NULL AND is_aod_missing_mnar != 0)
                         OR is_aod_missing_mnar IS NULL),
        count(*) FILTER (WHERE aod_047_mean < 0 OR aod_047_mean > 3.5),
        count(*) FILTER (WHERE no2_tropospheric_mol_m2 > 0.001
                         OR viirs_nightlight_rad < 0 OR viirs_nightlight_rad > 300)
        FROM sat""").fetchone()
    require(row[0] == row[1] == EXPECTED_GRID_DAYS,
            "Satellite fact does not have the dense unique grid-day spine")
    require(row[5] == row[6] == row[7] == 0, "Invalid satellite flag or value")
    missing = con.execute("""SELECT count(*) FROM sat s
        LEFT JOIN grid g ON s.grid_id = g.grid_id
        LEFT JOIN dates d ON s.date_id = d.date_id
        WHERE g.grid_id IS NULL OR d.date_id IS NULL
           OR s.grid_id = 'grid_unknown' OR s.date_id = -1""").fetchone()[0]
    require(missing == 0, "Satellite fact has orphan or sentinel keys")
    con.execute(f"CREATE VIEW osm AS SELECT * FROM read_parquet({sql_path(CORE / 'fct_grid_osm_yearly.parquet')})")
    osm_join = con.execute("""SELECT count(*), count(o.grid_id)
        FROM sat s JOIN dates d ON s.date_id = d.date_id
        LEFT JOIN osm o ON s.grid_id = o.grid_id AND d.year = o.year""").fetchone()
    require(osm_join == (EXPECTED_GRID_DAYS, EXPECTED_GRID_DAYS),
            "Joining yearly OSM features fans out or loses a satellite grid-day")
    stage_row = con.execute("""SELECT count(*), count(DISTINCT (grid_id, date_id)),
        count(*) FILTER (WHERE aod_source_image_count IS NULL
                         OR no2_source_image_count IS NULL
                         OR viirs_source_image_count IS NULL)
        FROM stg""").fetchone()
    require(stage_row == (EXPECTED_GRID_DAYS, EXPECTED_GRID_DAYS, 0),
            "Satellite staging keys or source metadata are incomplete")
    matched, mismatched = con.execute("""SELECT count(*),
        count(*) FILTER (WHERE f.aod_047_mean IS DISTINCT FROM CAST(s.aod_047_mean AS FLOAT)
          OR f.is_aod_missing_mnar IS DISTINCT FROM s.is_aod_missing_mnar
          OR f.no2_tropospheric_mol_m2 IS DISTINCT FROM CAST(s.no2_tropospheric_mol_m2 AS FLOAT)
          OR f.viirs_nightlight_rad IS DISTINCT FROM CAST(s.viirs_nightlight_rad AS FLOAT))
        FROM sat f JOIN stg s USING (grid_id, date_id)""").fetchone()
    require((matched, mismatched) == (EXPECTED_GRID_DAYS, 0),
            "Satellite fact values differ from staging or keys fail to join")
    report = json.loads((MANIFESTS / "satellite_daily_v1.json").read_text(encoding="utf-8"))
    require((row[0], row[2], row[3], row[4]) ==
            (report["rows"], report["aod_non_null"], report["no2_non_null"],
             report["viirs_daily_non_null"]),
            "Satellite fact and coverage manifest disagree")
    return {"grid_days": row[0], "osm_yearly_join_rows": osm_join[0],
            "aod_non_null": row[2],
            "no2_non_null": row[3], "viirs_daily_non_null": row[4]}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    grid = check_osm_yearly()
    satellite = check_satellite()
    report = {"status": "local_artifacts_validated; pending team review",
              "grid": grid, "satellite": satellite}
    report_path = MANIFESTS / "tv2_handoff_validation.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    files = [CORE / "dim_grid_1km.parquet",
             CORE / "fct_grid_osm_yearly.parquet",
             CORE / "fct_grid_satellite_daily.parquet",
             STAGING / "stg_satellite_daily.parquet"]
    files.extend(MANIFESTS / name for name in (
        "satellite_exports_v2.json", "satellite_bronze_v2.json",
        "satellite_daily_v1.json", "static_features_v1_1.json",
        "osm_yearly_v1.json", "tv2_handoff_validation.json",
        "tv2_raw_rasters_sha256.txt"))
    checksums = MANIFESTS / "tv2_checksums_sha256.txt"
    checksums.write_text("".join(f"{sha256(path)}  {path.relative_to(ROOT)}\n"
                                 for path in files), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"[TV2] Checksums: {checksums}")


if __name__ == "__main__":
    main()
