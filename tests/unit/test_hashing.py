import os

import polars as pl

from src.common.hashing import append_idempotent_raw_parquet, compute_row_hash


def test_compute_row_hash():
    h1 = compute_row_hash(["station_01", "2023-01-01 08:00:00", 45.2])
    h2 = compute_row_hash(["station_01", "2023-01-01 08:00:00", 45.2])
    h3 = compute_row_hash(["station_01", "2023-01-01 09:00:00", 45.2])
    assert h1 == h2, "Cùng giá trị đầu vào phải sinh ra cùng mã băm SHA-256!"
    assert h1 != h3, "Khác giá trị phải sinh ra mã băm khác nhau!"


def test_idempotent_append(tmp_path):
    target_file = os.path.join(tmp_path, "test_append.parquet")

    # Lần 1: Nạp 2 dòng
    df1 = pl.DataFrame({
        "station_id": ["st_1", "st_2"],
        "_row_hash": ["hash_1", "hash_2"]
    })
    added_1 = append_idempotent_raw_parquet(df1, target_file)
    assert added_1 == 2, "Lần đầu phải thêm đúng 2 dòng"

    # Lần 2: Nạp lại đúng 2 dòng cũ kèm 1 dòng mới -> Chỉ thêm đúng 1 dòng
    df2 = pl.DataFrame({
        "station_id": ["st_1", "st_2", "st_3"],
        "_row_hash": ["hash_1", "hash_2", "hash_3"]
    })
    added_2 = append_idempotent_raw_parquet(df2, target_file)
    assert added_2 == 1, "Chạy lại chỉ được thêm đúng 1 dòng mới duy nhất!"