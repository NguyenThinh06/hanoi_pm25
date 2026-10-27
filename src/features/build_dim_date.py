"""
src/features/build_dim_date.py
Xây dựng chiều thời gian bất biến 5 năm (2021-2025) gồm 1.826 ngày + 1 dòng ngoại lệ = 1.827 dòng.
"""
from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from src.common.io_parquet import atomic_write_parquet
from src.common.spine_contract import DATE_END, DATE_START, DATE_UNKNOWN, REAL_DAYS


def build_dim_date(target_path="data/core/dim_date.parquet"):
    start_date = DATE_START
    end_date = DATE_END

    cur = start_date
    records = []

    # 1. Sinh 1.826 ngay lich
    while cur <= end_date:
        m = cur.month
        # Mua Ha Noi: Dong (T11-T2), Xuan (T3-T4), He (T5-T8), Thu (T9-T10)
        if m in [11, 12, 1, 2]:
            season = "Winter"
        elif m in [3, 4]:
            season = "Spring"
        elif m in [5, 6, 7, 8]:
            season = "Summer"
        else:
            season = "Autumn"

        # Cua so dot rom ra ngoai thanh Ha Noi: Dot 1 (15/5-15/6), Dot 2 (15/9-31/10)
        is_crop = 1 if ((m == 5 and cur.day >= 15) or (m == 6 and cur.day <= 15) or
                        (m == 9 and cur.day >= 15) or (m == 10)) else 0

        records.append({
            "date_id": int(cur.strftime("%Y%m%d")),
            "date_actual": cur,
            "year": cur.year,
            "month": cur.month,
            "day": cur.day,
            "day_of_week": cur.weekday() + 1,  # 1: Thu Hai, ..., 7: Chu Nhat
            "is_weekend": 1 if cur.weekday() >= 5 else 0,
            "hanoi_season": season,
            "is_crop_burning_window": is_crop
        })
        cur += timedelta(days=1)

    # 2. Them dong ngoai le date_id = -1
    records.append({
        "date_id": DATE_UNKNOWN,
        "date_actual": date(1970, 1, 1),
        "year": -1,
        "month": -1,
        "day": -1,
        "day_of_week": -1,
        "is_weekend": 0,
        "hanoi_season": "Unknown",
        "is_crop_burning_window": 0
    })

    df = pl.DataFrame(records).with_columns(pl.col("date_id").cast(pl.Int32))
    real = df.filter(pl.col("date_id") != DATE_UNKNOWN)
    if (len(df) != REAL_DAYS + 1 or len(real) != REAL_DAYS
            or df["date_id"].n_unique() != len(df)
            or real["date_actual"].to_list() != [
                DATE_START + timedelta(days=i) for i in range(REAL_DAYS)
            ]):
        raise ValueError("Daily dimension violates the spine contract")
    atomic_write_parquet(df, target_path)
    print(f"[DATE] Successfully generated {len(df)} rows at {target_path} (Expected: 1827 rows).")
    return df


if __name__ == "__main__":
    build_dim_date()
