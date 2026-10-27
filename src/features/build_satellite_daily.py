"""Join the 2021-2025 satellite Bronze exports to every TV1 grid-day.

Run: python -m src.features.build_satellite_daily
Missing measurements remain NULL. VIIRS monthly values are repeated only within
their own calendar month. The legacy field name is_aod_missing_mnar is retained
for the contract, but 1 means AOD is absent; cause/MNAR is unverified.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
GRID = ROOT / "data/core/dim_grid_1km.parquet"
DATE = ROOT / "data/core/dim_date.parquet"
RAW = ROOT / "data/raw/earth_observation"
STAGING = ROOT / "data/staging/stg_satellite_daily.parquet"
FACT = ROOT / "data/core/fct_grid_satellite_daily.parquet"
REPORT = ROOT / "data/manifests/satellite_daily_v1.json"
EXPECTED_ROWS = 6_591_860
EXPECTED_MONTHLY_ROWS = 216_600


def sql_string(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def check_source(con: duckdb.DuckDBPyConnection, name: str,
                 period_column: str, expected: int) -> None:
    count, unique = con.execute(f"""SELECT count(*),
        count(DISTINCT (grid_id, {period_column})) FROM {name}""").fetchone()
    if count != expected or unique != expected:
        raise ValueError(f"{name} has {count} rows and {unique} unique keys; expected {expected}")


def copy_atomic(con: duckdb.DuckDBPyConnection, query: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + f".tmp_{os.getpid()}")
    try:
        con.execute(f"COPY ({query}) TO {sql_string(tmp)} "
                    "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880)")
        rows, unique = con.execute("SELECT count(*), count(DISTINCT (grid_id, date_id)) "
                                   "FROM read_parquet(?)", [str(tmp)]).fetchone()
        if (rows, unique) != (EXPECTED_ROWS, EXPECTED_ROWS):
            raise ValueError(f"Bad grid-day output {target}: {rows} rows, {unique} keys")
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def main() -> None:
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='4GB'")
    for table, source, partition in (
        ("aod", "modis_aod", "quarter"),
        ("no2", "s5p_no2", "quarter"),
        ("viirs", "viirs_dnb", "month"),
    ):
        pattern = RAW / f"source={source}" / "year=*" / f"{partition}=*" / "data.parquet"
        con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet("
                    f"{sql_string(pattern)}, hive_partitioning=false)")
    check_source(con, "aod", "date_id", EXPECTED_ROWS)
    check_source(con, "no2", "date_id", EXPECTED_ROWS)
    check_source(con, "viirs", "month_id", EXPECTED_MONTHLY_ROWS)

    staging_query = f"""
        WITH spine AS (
            SELECT g.grid_id, d.date_id,
                   CAST(d.year * 100 + d.month AS INTEGER) AS month_id
            FROM read_parquet({sql_string(GRID)}) g
            CROSS JOIN read_parquet({sql_string(DATE)}) d
            WHERE g.grid_id != 'grid_unknown' AND d.date_id != -1
        )
        SELECT s.grid_id, s.date_id, s.month_id,
               a.aod_047_mean,
               CAST(a.aod_047_mean IS NULL AS INTEGER) AS is_aod_missing_mnar,
               a.source_image_count AS aod_source_image_count,
               n.no2_tropospheric_mol_m2,
               n.source_image_count AS no2_source_image_count,
               v.viirs_nightlight_rad,
               v.viirs_cf_cvg_mean,
               v.source_image_count AS viirs_source_image_count
        FROM spine s
        LEFT JOIN aod a ON s.grid_id = a.grid_id AND s.date_id = a.date_id
        LEFT JOIN no2 n ON s.grid_id = n.grid_id AND s.date_id = n.date_id
        LEFT JOIN viirs v ON s.grid_id = v.grid_id AND s.month_id = v.month_id
        ORDER BY s.grid_id, s.date_id
    """
    copy_atomic(con, staging_query, STAGING)
    print(f"[SAT] Wrote staging: {STAGING}", flush=True)

    fact_query = f"""
        SELECT grid_id, date_id,
               CAST(aod_047_mean AS FLOAT) AS aod_047_mean,
               is_aod_missing_mnar,
               CAST(no2_tropospheric_mol_m2 AS FLOAT) AS no2_tropospheric_mol_m2,
               CAST(viirs_nightlight_rad AS FLOAT) AS viirs_nightlight_rad
        FROM read_parquet({sql_string(STAGING)})
        ORDER BY grid_id, date_id
    """
    copy_atomic(con, fact_query, FACT)
    print(f"[SAT] Wrote fact: {FACT}", flush=True)

    result = con.execute("""SELECT count(*) AS rows,
        count(aod_047_mean) AS aod_values,
        count(no2_tropospheric_mol_m2) AS no2_values,
        count(viirs_nightlight_rad) AS viirs_daily_values,
        count(*) FILTER (WHERE aod_047_mean IS NULL AND is_aod_missing_mnar != 1
                       OR aod_047_mean IS NOT NULL AND is_aod_missing_mnar != 0) AS bad_aod_flags,
        count(*) FILTER (WHERE aod_source_image_count IS NULL OR no2_source_image_count IS NULL
                       OR viirs_source_image_count IS NULL) AS missing_source_metadata
        FROM read_parquet(?)""", [str(STAGING)]).fetchone()
    if result[0] != EXPECTED_ROWS or result[4] or result[5]:
        raise ValueError(f"Staging quality check failed: {result}")
    report = {
        "grain": "one row for each real TV1 grid cell and local calendar day",
        "rows": result[0], "aod_non_null": result[1], "no2_non_null": result[2],
        "viirs_daily_non_null": result[3],
        "missing_aod_flag_semantics": "1 iff AOD is NULL; the MNAR/cloud cause is not established",
        "no2_negative_policy": "preserved; no post-GEE clipping",
        "viirs_policy": "monthly value repeated within the same calendar month only; NULL stays NULL",
        "source_metadata": "image counts are collection counts for the region, not valid pixels per cell",
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"[SAT] Verified {result[0]:,} grid-days; report: {REPORT}")


if __name__ == "__main__":
    main()
