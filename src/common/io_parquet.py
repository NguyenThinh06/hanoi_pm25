"""
src/common/io_parquet.py
Bộ ghi đọc Parquet/GeoParquet nguyên tử (Atomic IO) chống hỏng dữ liệu khi tiến trình bị ngắt.
"""
from __future__ import annotations

import os
from typing import Any

import polars as pl
import pyarrow.parquet as pq


def atomic_write_parquet(df: Any, target_path: str, compression: str = "zstd") -> None:
    """
    Ghi DataFrame (Polars, GeoPandas, Pandas, PyArrow) ra file Parquet nguyên tử.
    Ghi vào file tạm .tmp trước, sau đó đổi tên đè vào target_path.
    """
    target_dir = os.path.dirname(os.path.abspath(target_path))
    os.makedirs(target_dir, exist_ok=True)

    # Đặt file tạm cùng thư mục đích để đảm bảo cùng phân vùng ổ đĩa (atomic rename)
    tmp_path = f"{target_path}.tmp_{os.getpid()}"
    try:
        if isinstance(df, pl.DataFrame):
            df.write_parquet(tmp_path, compression=compression)
        elif hasattr(df, "to_parquet"):
            # GeoPandas GeoDataFrame hoặc Pandas DataFrame
            df.to_parquet(tmp_path, compression=compression)
        else:
            import pyarrow as pa
            if not isinstance(df, pa.Table):
                df = pa.Table.from_pandas(df)
            pq.write_table(df, tmp_path, compression=compression)

        # Atomic replace an toàn tuyệt đối
        os.replace(tmp_path, target_path)
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise OSError(f"Lỗi khi ghi file nguyên tử tại {target_path}: {e}") from e