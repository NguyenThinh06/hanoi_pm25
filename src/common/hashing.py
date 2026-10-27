"""
src/common/hashing.py
Module băm SHA-256 và ghi nối dữ liệu lũy đẳng (Idempotent Append) cho Lakehouse.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any

import duckdb
import polars as pl

from src.common.io_parquet import atomic_write_parquet


def compute_row_hash(values: list[Any]) -> str:
    """
    Tạo mã băm SHA-256 duy nhất từ danh sách các giá trị định danh của một dòng.
    Ví dụ: values = [station_id, timestamp_utc, value]
    """
    raw_str = "|".join("" if v is None else str(v) for v in values)
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


def append_idempotent_raw_parquet(
    new_df: pl.DataFrame, target_path: str, hash_col: str = "_row_hash"
) -> int:
    """
    Ghi thêm dữ liệu mới vào file Parquet đích mà không bị trùng lặp.
    - Nếu file chưa có: ghi mới hoàn toàn.
    - Nếu file đã có: dùng DuckDB lọc bỏ các dòng có _row_hash đã tồn tại.
    Trả về số lượng dòng mới thực sự được thêm vào.
    """
    if not os.path.exists(target_path):
        atomic_write_parquet(new_df, target_path)
        return len(new_df)

    # Đọc tập hợp hash đã tồn tại bằng DuckDB siêu nhanh
    con = duckdb.connect()
    sql_path = target_path.replace("\\", "/")
    existing_hashes = con.sql(f"SELECT {hash_col} FROM '{sql_path}'").fetchall()
    existing_hash_set = {h[0] for h in existing_hashes}

    # Lọc các dòng chưa từng xuất hiện
    unique_df = new_df.filter(~pl.col(hash_col).is_in(list(existing_hash_set)))

    if len(unique_df) > 0:
        old_df = pl.read_parquet(target_path)
        combined_df = pl.concat([old_df, unique_df])
        atomic_write_parquet(combined_df, target_path)

    return len(unique_df)
