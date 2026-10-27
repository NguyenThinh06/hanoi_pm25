"""Check one GEE export against the TV1 grid and report coverage by month/quarter.

Usage: python src/ingest/audit_gee_csv.py 2023 aod export.csv grid.csv
"""

import csv
import json
import math
import sys
from datetime import date, timedelta


def main():
    year = int(sys.argv[1])
    source = sys.argv[2]
    export_path = sys.argv[3]
    grid_path = sys.argv[4]
    value_column = {
        "aod": "aod_047_mean",
        "no2": "no2_tropospheric_mol_m2",
        "viirs": "viirs_nightlight_rad",
    }[source]
    period_column = "month_id" if source == "viirs" else "date_id"

    with open(grid_path, newline="") as file:
        grid_ids = {row["grid_id"] for row in csv.DictReader(file)}
    grid_index = {grid_id: index for index, grid_id in enumerate(sorted(grid_ids))}

    if source == "viirs":
        periods = [f"{year}{month:02d}" for month in range(1, 13)]
    else:
        start = date(year, 1, 1)
        days = (date(year + 1, 1, 1) - start).days
        periods = [(start + timedelta(days=index)).strftime("%Y%m%d")
                   for index in range(days)]

    by_period = {
        period: {
            "rows": 0,
            "distinct_ids": 0,
            "valid": 0,
            "missing_cf_zero": 0,
            "missing_cf_positive": 0,
            "source_counts": set(),
            "seen": bytearray(len(grid_ids)),
        }
        for period in periods
    }
    total = duplicate = invalid_period = invalid_grid = malformed = negative = 0
    low, high = math.inf, -math.inf
    with open(export_path, newline="") as file:
        reader = csv.DictReader(file)
        columns = reader.fieldnames
        for row in reader:
            total += 1
            period = row[period_column]
            grid_id = row["grid_id"]
            if period not in by_period:
                invalid_period += 1
                continue
            if grid_id not in grid_index:
                invalid_grid += 1
                continue
            current = by_period[period]
            current["rows"] += 1
            current["source_counts"].add(row["source_image_count"])
            index = grid_index[grid_id]
            if current["seen"][index]:
                duplicate += 1
            else:
                current["seen"][index] = 1
                current["distinct_ids"] += 1

            raw = row[value_column]
            if raw:
                try:
                    value = float(raw)
                    if not math.isfinite(value):
                        raise ValueError("nonfinite")
                except ValueError:
                    malformed += 1
                    continue
                current["valid"] += 1
                negative += value < 0
                low, high = min(low, value), max(high, value)
            elif source == "viirs":
                try:
                    coverage = float(row["viirs_cf_cvg_mean"])
                except ValueError:
                    malformed += 1
                    continue
                if coverage > 0:
                    current["missing_cf_positive"] += 1
                else:
                    current["missing_cf_zero"] += 1

    quarters = {}
    months = {}
    for quarter in range(1, 5):
        selected = [(period, result) for period, result in by_period.items()
                    if (int(period[4:6]) - 1) // 3 + 1 == quarter]
        quarters[f"q{quarter}"] = {
            "rows": sum(result["rows"] for _, result in selected),
            "valid": sum(result["valid"] for _, result in selected),
        }
    for month in range(1, 13):
        selected = [(period, result) for period, result in by_period.items()
                    if int(period[4:6]) == month]
        months[f"{year}{month:02d}"] = {
            "rows": sum(result["rows"] for _, result in selected),
            "valid": sum(result["valid"] for _, result in selected),
        }

    print(json.dumps({
        "source": source,
        "year": year,
        "columns": columns,
        "rows": total,
        "expected_rows": len(grid_ids) * len(periods),
        "grid_count": len(grid_ids),
        "period_count": len(periods),
        "duplicate": duplicate,
        "invalid_period": invalid_period,
        "invalid_grid": invalid_grid,
        "malformed": malformed,
        "bad_periods": [period for period, result in by_period.items()
                        if result["rows"] != len(grid_ids)
                        or result["distinct_ids"] != len(grid_ids)],
        "null_periods": [period for period, result in by_period.items()
                         if result["valid"] == 0],
        "nonpositive_source_count_periods": [
            period for period, result in by_period.items()
            if not result["source_counts"]
            or any(not count.isdigit() or int(count) <= 0
                   for count in result["source_counts"])
        ],
        "source_counts": sorted({count for result in by_period.values()
                                 for count in result["source_counts"]}),
        "valid": sum(result["valid"] for result in by_period.values()),
        "negative": negative,
        "range": None if low == math.inf else [low, high],
        "missing_cf_zero": sum(result["missing_cf_zero"]
                               for result in by_period.values()),
        "missing_cf_positive": sum(result["missing_cf_positive"]
                                   for result in by_period.values()),
        "quarters": quarters,
        "months": months,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
