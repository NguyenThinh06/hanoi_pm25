"""Validate GEE v2 CSV exports and materialize lossless Bronze Parquet partitions.

Run: python -m src.ingest.ingest_satellite_csv
The CSVs are already polygon means, QA masked and AOD scaled by GEE. This step
does not apply further QC, fill missing values, or broadcast monthly VIIRS.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data/manifests/satellite_exports_v2.json"
EXPORTS = ROOT / "data/raw/earth_observation/exports"
RAW = ROOT / "data/raw/earth_observation"
GRID = ROOT / "data/core/dim_grid_1km.parquet"
SOURCE_NAMES = {"aod": "modis_aod", "no2": "s5p_no2", "viirs": "viirs_dnb"}
VALUE_COLUMNS = {"aod": "aod_047_mean", "no2": "no2_tropospheric_mol_m2",
                 "viirs": "viirs_nightlight_rad"}
YEAR_FILE = re.compile(r"hanoi_(aod|no2|viirs)_(20\d\d)_q([1-4])(?:_to_(20\d\d)_q([1-4]))?_v2\.csv$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sql_string(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def quarter_periods(year: int, quarter: int, source: str) -> list[int]:
    first_month = (quarter - 1) * 3 + 1
    if source == "viirs":
        return [year * 100 + month for month in range(first_month, first_month + 3)]
    first = date(year, first_month, 1)
    last_month = first_month + 2
    last = date(year, last_month, calendar.monthrange(year, last_month)[1])
    return [int((first + timedelta(days=offset)).strftime("%Y%m%d"))
            for offset in range((last - first).days + 1)]


def main() -> None:
    exports = json.loads(MANIFEST.read_text(encoding="utf-8"))["exports"]
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.execute("CREATE TEMP TABLE valid_grid AS SELECT grid_id FROM read_parquet(?) WHERE grid_id != 'grid_unknown'", [str(GRID)])
    grid_count = con.execute("SELECT count(*) FROM valid_grid").fetchone()[0]
    if grid_count != 3610:
        raise ValueError("Expected 3,610 real grid IDs")
    reports = []
    partition_keys = set()
    for i, item in enumerate(exports, 1):
        name = item["file"]
        match = YEAR_FILE.fullmatch(name)
        if not match or match.group(1) != item["source"]:
            raise ValueError(f"Unrecognised export name: {name}")
        source, year, first_quarter, last_year, last_quarter = match.groups()
        year, first_quarter = int(year), int(first_quarter)
        if last_year and int(last_year) != year:
            raise ValueError("Cross-year export not supported in this manifest")
        quarters = list(range(first_quarter, int(last_quarter or first_quarter) + 1))
        path = EXPORTS / name
        if not path.exists() or path.stat().st_size != item["size"]:
            raise FileNotFoundError(f"Missing or incomplete CSV: {path}")
        csv_hash = sha256(path)
        if csv_hash != item["sha256"]:
            raise ValueError(f"CSV SHA-256 differs from manifest: {path}")

        con.execute("DROP TABLE IF EXISTS csv_raw")
        con.execute("CREATE TEMP TABLE csv_raw AS SELECT * FROM read_csv(?, header=true, all_varchar=true)", [str(path)])
        columns = [row[1] for row in con.execute("PRAGMA table_info('csv_raw')").fetchall()]
        period = "month_id" if source == "viirs" else "date_id"
        value = VALUE_COLUMNS[source]
        expected_columns = ["grid_id", period, "source_image_count", value]
        if source == "viirs":
            expected_columns.append("viirs_cf_cvg_mean")
        if set(columns) != set(expected_columns):
            raise ValueError(f"Unexpected columns in {name}: {columns}")
        con.execute("DROP TABLE IF EXISTS bronze")
        extra = (", TRY_CAST(viirs_cf_cvg_mean AS DOUBLE) AS viirs_cf_cvg_mean"
                 if source == "viirs" else "")
        con.execute(f"""CREATE TEMP TABLE bronze AS
            SELECT grid_id,
                TRY_CAST({period} AS INTEGER) AS {period},
                TRY_CAST(source_image_count AS INTEGER) AS source_image_count,
                TRY_CAST({value} AS DOUBLE) AS {value}{extra},
                sha256({sql_string(source)} || '|' || grid_id || '|' || {period} || '|' ||
                       source_image_count || '|' || coalesce({value}, '')
                       {"|| '|' || coalesce(viirs_cf_cvg_mean, '')" if source == "viirs" else ""}) AS _row_hash
            FROM csv_raw""")
        con.execute("DROP TABLE IF EXISTS expected_period")
        con.execute("CREATE TEMP TABLE expected_period(period_id INTEGER)")
        expected_periods = [p for q in quarters for p in quarter_periods(year, q, source)]
        con.executemany("INSERT INTO expected_period VALUES (?)", [(p,) for p in expected_periods])
        malformed = con.execute(f"""SELECT
            count(*) FILTER (WHERE {value} IS NOT NULL AND
                (TRY_CAST({value} AS DOUBLE) IS NULL OR
                 NOT isfinite(TRY_CAST({value} AS DOUBLE))))
            {", count(*) FILTER (WHERE viirs_cf_cvg_mean IS NOT NULL AND (TRY_CAST(viirs_cf_cvg_mean AS DOUBLE) IS NULL OR NOT isfinite(TRY_CAST(viirs_cf_cvg_mean AS DOUBLE))))" if source == "viirs" else ""}
            FROM csv_raw""").fetchone()
        row = con.execute(f"""SELECT
                count(*) AS rows,
                count(DISTINCT (b.grid_id, b.{period})) AS unique_keys,
                count(*) FILTER (WHERE g.grid_id IS NULL OR e.period_id IS NULL) AS invalid_keys,
                count(*) FILTER (WHERE b.{period} IS NULL OR b.source_image_count IS NULL
                                  OR b.source_image_count < 0 OR b._row_hash IS NULL) AS invalid_metadata,
                count(b.{value}) AS valid_values,
                count(*) FILTER (WHERE b.{value} < 0) AS negative_values
            FROM bronze b
            LEFT JOIN valid_grid g ON b.grid_id = g.grid_id
            LEFT JOIN expected_period e ON b.{period} = e.period_id""").fetchone()
        expected_rows = grid_count * len(expected_periods)
        if row[0] != expected_rows or row[1] != expected_rows or any(row[j] for j in (2, 3)) or any(malformed):
            raise ValueError(f"Failed CSV validation for {name}: {row}, malformed={malformed}; expected {expected_rows} rows")

        for quarter in quarters:
            periods = quarter_periods(year, quarter, source)
            if source == "viirs":
                destinations = [(month, [month]) for month in periods]
            else:
                destinations = [(quarter, periods)]
            for part, selected in destinations:
                key = (source, year, part)
                if key in partition_keys:
                    raise ValueError(f"Overlapping export partition: {key}")
                partition_keys.add(key)
                part_label = f"month={part % 100:02d}" if source == "viirs" else f"quarter={part}"
                target = (RAW / f"source={SOURCE_NAMES[source]}" / f"year={year}" /
                          part_label / "data.parquet")
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_name(f"data.parquet.tmp_{os.getpid()}")
                try:
                    con.execute(f"""COPY (SELECT * FROM bronze
                        WHERE {period} BETWEEN {min(selected)} AND {max(selected)})
                        TO {sql_string(tmp)} (FORMAT PARQUET, COMPRESSION ZSTD)""")
                    count = con.execute("SELECT count(*) FROM read_parquet(?)", [str(tmp)]).fetchone()[0]
                    if count != grid_count * len(selected):
                        raise ValueError(f"Partition row count mismatch: {target}")
                    os.replace(tmp, target)
                finally:
                    tmp.unlink(missing_ok=True)
        reports.append({"file": name, "source": source, "csv_sha256": csv_hash,
                        "rows": row[0], "non_null_values": row[4], "negative_values": row[5]})
        print(f"[{i}/{len(exports)}] {name}: {row[0]:,} rows, {row[4]:,} values", flush=True)
    expected_partitions = 5 * (4 + 4 + 12)
    if len(partition_keys) != expected_partitions:
        raise ValueError(f"Expected {expected_partitions} Bronze partitions, got {len(partition_keys)}")
    report = {"version": "v2", "grid_cells": grid_count,
              "bronze_partition_count": len(partition_keys), "exports": reports,
              "note": "GEE polygon exports already had AOD QA masking and scale factor applied; missing values retained"}
    report_path = ROOT / "data/manifests/satellite_bronze_v2.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"[BRONZE] Wrote {len(partition_keys)} partitions; report: {report_path}")


if __name__ == "__main__":
    main()
