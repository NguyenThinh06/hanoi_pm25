"""
run.py — CLI Command Center cho dự án HANOI_PM25
Điều phối toàn bộ vòng đời: lint, test, grid, date, ingest, transform, predict.
"""
from __future__ import annotations

import argparse
import subprocess
import sys


def run_cmd(cmd: str, desc: str) -> None:
    print(f"\n[RUNNER] >>> {desc}...")
    print(f"[CMD] {cmd}")
    ret = subprocess.call(cmd, shell=True)
    if ret != 0:
        print(f"[ERROR] That bai khi thuc thi: {desc} (Exit code: {ret})")
        sys.exit(ret)
    print(f"[SUCCESS] {desc} hoan thanh xuat sac.")


def main():
    parser = argparse.ArgumentParser(description="Hanoi PM2.5 Spatial Lakehouse Runner")
    subparsers = parser.add_subparsers(dest="subcommand", help="Lệnh cần chạy")

    # 1. Lint code
    subparsers.add_parser("lint", help="Kiểm tra chất lượng code bằng ruff")

    # 2. Test
    subparsers.add_parser("test", help="Chạy toàn bộ unit tests")

    # 3. Sinh lưới 1km
    subparsers.add_parser("grid", help="Sinh lưới không gian chuẩn 1km EPSG:3405")

    # 4. Sinh trục ngày 5 năm
    subparsers.add_parser("date", help="Sinh trục thời gian 5 năm dim_date.parquet")

    # 5. Ingest
    ingest_p = subparsers.add_parser("ingest", help="Thu thập dữ liệu")
    ingest_p.add_argument("--source", default="all", choices=["all", "openaq", "pamair", "meteo", "satellite"])

    # 6. Predict toàn lưới
    subparsers.add_parser("predict", help="Suy luận bản đồ bụi mịn PM2.5 toàn Hà Nội")

    args = parser.parse_args()

    if args.subcommand == "lint":
        run_cmd("python -m ruff check --fix .", "Kiem tra va tu dong format code bang ruff")

    elif args.subcommand == "test":
        run_cmd("python -m pytest tests/unit/ -v", "Thuc thi toan bo Unit Tests")

    elif args.subcommand == "grid":
        run_cmd("python -m src.common.spatial_spine", "Sinh luoi khong gian 1km EPSG:3405 cho Ha Noi")

    elif args.subcommand == "date":
        run_cmd("python -m src.features.build_dim_date", "Tao truc thoi gian 5 nam dim_date")

    elif args.subcommand == "predict":
        run_cmd("python -m src.models.predict_grid", "Quet toan luoi sinh ban do o nhiem PM2.5")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
