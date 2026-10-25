"""Shared contract for the spatial and daily analysis dimensions."""
from datetime import date

DATE_START = date(2021, 1, 1)
DATE_END = date(2025, 12, 31)
REAL_DAYS = (DATE_END - DATE_START).days + 1
GRID_UNKNOWN = "grid_unknown"
DATE_UNKNOWN = -1


def date_metadata() -> dict:
    return {
        "date_start": DATE_START.isoformat(),
        "date_end": DATE_END.isoformat(),
        "date_id_format": "YYYYMMDD",
        "date_unknown_id": DATE_UNKNOWN,
        "real_days": REAL_DAYS,
        "dim_date_rows": REAL_DAYS + 1,
    }
