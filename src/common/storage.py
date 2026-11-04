"""Ghi file nguyên tử (ghi ra file tạm rồi đổi tên) để không bao giờ để lại file hỏng."""
from __future__ import annotations

import json
import os
from pathlib import Path

import duckdb
import pandas as pd


def _tmp(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.with_name(f"{path.name}.tmp{os.getpid()}")


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    tmp = _tmp(path)
    df.to_parquet(tmp, index=False, compression="zstd")
    os.replace(tmp, path)


def write_json(value, path: Path) -> None:
    tmp = _tmp(path)
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _dump_simple_yaml(value, indent: int = 0) -> list[str]:
    """Chuyển dict/list sang chuỗi YAML khi không có sẵn thư viện PyYAML."""
    prefix = "  " * indent
    lines: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{prefix}{k}:")
                lines.extend(_dump_simple_yaml(v, indent + 1))
            else:
                lines.append(f"{prefix}{k}: {json.dumps(v, ensure_ascii=False)}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{prefix}-")
                lines.extend(_dump_simple_yaml(item, indent + 1))
            else:
                lines.append(f"{prefix}- {json.dumps(item, ensure_ascii=False)}")
    else:
        lines.append(f"{prefix}{json.dumps(value, ensure_ascii=False)}")
    return lines


def write_yaml(value, path: Path) -> None:
    tmp = _tmp(path)
    try:
        import yaml

        text = yaml.safe_dump(value, allow_unicode=True, sort_keys=False)
    except ImportError:
        text = "\n".join(_dump_simple_yaml(value)) + "\n"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def copy_query(con: duckdb.DuckDBPyConnection, sql: str, path: Path) -> int:
    """Ghi kết quả một câu SQL DuckDB ra Parquet, trả về số dòng."""
    tmp = _tmp(path)
    con.execute(f"COPY ({sql}) TO '{tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    os.replace(tmp, path)
    rows = con.execute(f"SELECT count(*) FROM '{path.as_posix()}'").fetchone()[0]
    try:
        rel = path.relative_to(path.parents[2])
    except ValueError:
        rel = path.name
    print(f"  -> {rel}: {rows:,} dòng")
    return rows


def glob_sql(folder: Path, pattern: str = "*.parquet") -> str:
    """Biểu thức read_parquet cho mọi file trong thư mục (báo lỗi nếu rỗng)."""
    if not any(folder.glob(pattern)):
        raise FileNotFoundError(f"Chưa có dữ liệu trong {folder}; hãy chạy bước fetch tương ứng.")
    return f"read_parquet('{(folder / pattern).as_posix()}', union_by_name = true)"
