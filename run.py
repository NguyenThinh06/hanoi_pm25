"""
run.py — CLI Command Center cho dự án HANOI_PM25
Điều phối toàn bộ vòng đời: lint, test, grid, date, audit, ingest, staging, core-station, predict, contract.
"""
from __future__ import annotations

import argparse
import importlib.util
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
    lint_p = subparsers.add_parser("lint", help="Kiểm tra chất lượng code bằng ruff (không tự động sửa trừ khi có --fix)")
    lint_p.add_argument("--fix", action="store_true", help="Tự động sửa các lỗi lint an toàn")

    # 2. Test
    subparsers.add_parser("test", help="Chạy toàn bộ unit tests")

    # 3. Sinh lưới 1km
    subparsers.add_parser("grid", help="Sinh lưới không gian chuẩn 1km EPSG:3405")

    # 4. Sinh trục ngày 5 năm
    subparsers.add_parser("date", help="Sinh trục thời gian 5 năm dim_date.parquet")

    # 5. Audit trạm
    subparsers.add_parser("audit", help="Kiểm toán danh mục trạm quan trắc mặt đất OpenAQ")

    # 6. Ingest trạm
    ingest_p = subparsers.add_parser("ingest", help="Thu thập dữ liệu trạm quan trắc")
    ingest_p.add_argument("--start-year", type=int, default=2021, help="Năm bắt đầu (mặc định: 2021)")
    ingest_p.add_argument("--end-year", type=int, default=2025, help="Năm kết thúc (mặc định: 2025)")
    ingest_p.add_argument("--start-month", type=int, default=1, help="Tháng bắt đầu (1-12, mặc định: 1)")
    ingest_p.add_argument("--end-month", type=int, default=12, help="Tháng kết thúc (1-12, mặc định: 12)")
    ingest_p.add_argument("--month", type=int, default=None, help="Chỉ định chính xác 1 tháng để thu thập (ví dụ: --month 4)")
    ingest_p.add_argument("--limit-stations", type=int, default=0, help="Giới hạn số trạm (0 = tất cả)")
    ingest_p.add_argument("--force", action="store_true", help="Ép cào lại kể cả khi trạng thái đã ghi nhận hoàn tất")

    # 7. Staging trạm
    subparsers.add_parser("staging", help="Làm sạch chuỗi giờ và gán cờ QC phân tầng")

    # 8. Core trạm
    subparsers.add_parser("core-station", help="Tổng hợp trung bình ngày và tạo bảng Star Schema trạm")

    # 9. Predict toàn lưới
    subparsers.add_parser("predict", help="Suy luận bản đồ bụi mịn PM2.5 toàn Hà Nội")

    # 10. Kiểm định Hợp đồng Dữ liệu (Data Contract)
    contract_p = subparsers.add_parser("contract", help="Kiểm định toàn bộ Lakehouse theo Hợp đồng Dữ liệu ODCS v3.0")
    contract_p.add_argument("--strict", action="store_true", help="Chế độ nghiêm ngặt: Thất bại (exit code 1) nếu thiếu các model bắt buộc")
    contract_p.add_argument("--contract", type=str, default="data/contracts/hanoi_pm25_contract.yaml", help="Đường dẫn file hợp đồng YAML")

    args = parser.parse_args()

    if args.subcommand == "lint":
        fix_flag = " --fix" if args.fix else ""
        run_cmd(f"python -m ruff check{fix_flag} .", "Kiem tra chat luong code bang ruff")

    elif args.subcommand == "test":
        run_cmd("python -m pytest tests/unit/ -v", "Thuc thi toan bo Unit Tests")

    elif args.subcommand == "grid":
        run_cmd("python -m src.common.spatial_spine", "Sinh luoi khong gian 1km EPSG:3405 cho Ha Noi")

    elif args.subcommand == "date":
        run_cmd("python -m src.features.build_dim_date", "Tao truc thoi gian 5 nam dim_date")

    elif args.subcommand == "audit":
        run_cmd("python -m src.ingest.audit_stations", "Kiem toan tram mat dat OpenAQ va map grid 1km")

    elif args.subcommand == "ingest":
        force_flag = " --force" if args.force else ""
        month_flag = f" --month {args.month}" if args.month is not None else f" --start-month {args.start_month} --end-month {args.end_month}"
        run_cmd(
            f"python -m src.ingest.fetch_ground_truth --start-year {args.start_year} --end-year {args.end_year}{month_flag} --limit-stations {args.limit_stations}{force_flag}",
            f"Thu thap du lieu gio tho PM2.5 OpenAQ tu {args.start_year} den {args.end_year}"
        )

    elif args.subcommand == "staging":
        run_cmd("python -m src.features.qc_hourly_stations", "Lam sach chuoi gio va gan co QC stg_ground_truth_hourly")

    elif args.subcommand == "core-station":
        run_cmd("python -m src.features.build_ground_truth_daily", "Tao dim_station va fct_ground_truth_daily")

    elif args.subcommand == "predict":
        if importlib.util.find_spec("src.models.predict_grid") is None:
            print("\n[INFO] Chuc nang 'predict' chua duoc trien khai.")
            print("       Module 'src.models.predict_grid' chua ton tai (du kien o Phase 5/6 sau khi hoan thanh Feature Marts).")
            sys.exit(0)
        else:
            run_cmd("python -m src.models.predict_grid", "Quet toan luoi sinh ban do o nhiem PM2.5")

    elif args.subcommand == "contract":
        strict_flag = " --strict" if args.strict else ""
        run_cmd(
            f"python -m src.common.contract_verifier --contract {args.contract}{strict_flag}",
            "Kiem dinh Lakehouse theo Hop dong Du lieu ODCS v3.0"
        )

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
