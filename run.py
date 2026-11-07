"""CLI điều phối toàn bộ pipeline dữ liệu và mô hình PM2.5 Hà Nội (01/01/2021 - 30/09/2026).

Các lệnh chính:
  python run.py dims             -> tạo dim_grid_1km, dim_date, dim_station
  python run.py fetch-openaq     -> tải metadata trạm + giờ PM2.5, PM10, temp, RH
  python run.py fetch-meteo      -> tải ERA5-Land + ERA5 BLH từ Google Earth Engine
  python run.py fetch-satellite  -> tải S5P (NO2, CO, O3, SO2), MODIS AOD, VIIRS từ GEE
  python run.py staging          -> làm sạch và chuẩn hóa đơn vị/QC vào data/staging/
  python run.py facts            -> tổng hợp bảng core facts vào data/core/
  python run.py marts            -> ghép bảng mart lưới và mart huấn luyện vào data/marts/
  python run.py build            -> chạy trọn bộ dims -> staging -> facts -> marts
  python run.py evaluate         -> chạy 3 phép đánh giá (Spatial GroupKFold, Random KFold, Temporal Split)
  python run.py train-final      -> huấn luyện & lưu 2 model cuối trên toàn bộ dữ liệu hợp lệ vào outputs/models/
  python run.py train            -> chạy trọn bộ evaluate + train-final (kèm --estimate-grid nếu ước tính lưới)
  python run.py predict          -> sinh dự đoán hồi cứu PM2.5 trên toàn lưới từ hai model đã lưu
  python run.py lint             -> kiểm tra code bằng ruff
  python run.py test             -> chạy unit tests bằng pytest
"""
from __future__ import annotations

import argparse
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def _exec(cmd: list[str]) -> None:
    ret = subprocess.call(cmd)
    if ret != 0:
        sys.exit(ret)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("dims", help="Tạo dim_grid_1km, dim_date, dim_station")

    p_oaq = sub.add_parser("fetch-openaq", help="Tải metadata và số đo giờ OpenAQ v3")
    p_oaq.add_argument("--metadata-only", action="store_true", help="Chỉ tải locations.json")
    p_oaq.add_argument("--overwrite", action="store_true", help="Tải lại cả sensor-năm đã có")
    p_oaq.add_argument("--limit-sensors", type=int, default=0, help="Giới hạn số sensor (0 = tất cả)")
    p_oaq.add_argument("--year", type=int, default=None, help="Chỉ tải 1 năm UTC")

    p_met = sub.add_parser("fetch-meteo", help="Tải khí tượng ERA5-Land + ERA5 BLH từ GEE")
    p_met.add_argument("--overwrite", action="store_true", help="Tải lại tháng đã có")
    p_met.add_argument("--workers", type=int, default=4, help="Số luồng song song")
    p_met.add_argument("--month", type=str, default=None, help="Chỉ tải 1 tháng YYYY-MM")

    p_sat = sub.add_parser("fetch-satellite", help="Tải vệ tinh S5P, MODIS MAIAC AOD, VIIRS từ GEE")
    p_sat.add_argument("--overwrite", action="store_true", help="Tải lại tháng đã có")
    p_sat.add_argument("--workers", type=int, default=4, help="Số luồng song song")
    p_sat.add_argument("--month", type=str, default=None, help="Chỉ tải 1 tháng YYYY-MM")

    sub.add_parser("staging", help="Xây dựng các bảng staging (QC giờ, đổi đơn vị)")
    sub.add_parser("facts", help="Xây dựng các bảng core facts cấp ngày")
    sub.add_parser("marts", help="Xây dựng bảng feature marts cho mô hình")
    sub.add_parser("build", help="Chạy tuần tự: dims -> staging -> facts -> marts")

    p_eval = sub.add_parser(
        "evaluate",
        help="Đánh giá Baseline 1 & 2 theo 3 phương pháp (Spatial GroupKFold, Random KFold, Temporal Split)",
    )
    p_eval.add_argument(
        "--method",
        choices=["all", "spatial_groupkfold", "random_kfold", "temporal_split"],
        default="all",
        help="Phương pháp đánh giá cần chạy (mặc định: all)",
    )
    p_eval.add_argument("--folds", type=int, default=5, help="Số fold CV (mặc định: 5)")
    p_eval.add_argument("--seed", type=int, default=42, help="Random seed chuẩn (mặc định: 42)")
    p_eval.add_argument("--all-days", action="store_true", help="Dùng cả ngày có < 18 giờ hợp lệ")

    p_tf = sub.add_parser(
        "train-final",
        help="Huấn luyện và lưu Baseline 1 & 2 trên toàn bộ dữ liệu hợp lệ vào outputs/models/",
    )
    p_tf.add_argument("--seed", type=int, default=42, help="Random seed chuẩn (mặc định: 42)")
    p_tf.add_argument(
        "--model-version",
        type=str,
        default="v2.0.0-retrospective",
        help="Phiên bản model cuối (mặc định: v2.0.0-retrospective)",
    )
    p_tf.add_argument("--all-days", action="store_true", help="Dùng cả ngày có < 18 giờ hợp lệ")
    p_tf.add_argument(
        "--estimate-grid",
        action="store_true",
        help="Chạy thêm ước tính trên toàn bộ 7,57 triệu ô-ngày sau khi lưu model cuối",
    )

    p_trn = sub.add_parser(
        "train",
        help="Chạy trọn bộ 3 đánh giá (evaluate) và huấn luyện 2 model cuối (train-final)",
    )
    p_trn.add_argument("--folds", type=int, default=5, help="Số fold CV (mặc định: 5)")
    p_trn.add_argument("--seed", type=int, default=42, help="Random seed chuẩn (mặc định: 42)")
    p_trn.add_argument(
        "--model-version",
        type=str,
        default="v2.0.0-retrospective",
        help="Phiên bản model cuối (mặc định: v2.0.0-retrospective)",
    )
    p_trn.add_argument("--all-days", action="store_true", help="Dùng cả ngày có < 18 giờ hợp lệ")
    p_trn.add_argument(
        "--estimate-grid",
        action="store_true",
        help="Chạy thêm ước tính trên toàn bộ 7,57 triệu ô-ngày",
    )

    p_pred = sub.add_parser(
        "predict",
        help="Sinh dự đoán hồi cứu PM2.5 trên toàn lưới từ hai model đã lưu",
    )
    p_pred.add_argument(
        "--model",
        choices=["baseline1", "baseline2", "both"],
        default="both",
        help="Chọn mô hình suy luận (baseline1, baseline2, both; mặc định: both)",
    )
    p_pred.add_argument("--start-date", type=str, default=None, help="Ngày bắt đầu (YYYY-MM-DD)")
    p_pred.add_argument("--end-date", type=str, default=None, help="Ngày kết thúc (YYYY-MM-DD)")
    p_pred.add_argument("--output-dir", type=str, default=None, help="Thư mục lưu prediction")
    p_pred.add_argument("--no-resume", action="store_true", help="Ghi đè partition đã có")
    p_pred.add_argument("--run-id", type=str, default=None, help="Mã lần chạy run_id")

    p_lint = sub.add_parser("lint", help="Kiểm tra chất lượng code với ruff")
    p_lint.add_argument("--fix", action="store_true", help="Tự động sửa lỗi lint")

    sub.add_parser("test", help="Chạy unit tests với pytest")

    args = parser.parse_args()
    py = sys.executable

    if args.cmd == "dims":
        from src.pipeline.build_dims import build_all_dims

        build_all_dims()

    elif args.cmd == "fetch-openaq":
        cmd = [py, "-m", "src.ingest.fetch_openaq"]
        if args.metadata_only:
            cmd.append("--metadata-only")
        if args.overwrite:
            cmd.append("--overwrite")
        if args.limit_sensors:
            cmd += ["--limit-sensors", str(args.limit_sensors)]
        if args.year is not None:
            cmd += ["--year", str(args.year)]
        _exec(cmd)

    elif args.cmd == "fetch-meteo":
        cmd = [py, "-m", "src.ingest.fetch_meteo", "--workers", str(args.workers)]
        if args.overwrite:
            cmd.append("--overwrite")
        if args.month:
            cmd += ["--month", args.month]
        _exec(cmd)

    elif args.cmd == "fetch-satellite":
        cmd = [py, "-m", "src.ingest.fetch_satellite", "--workers", str(args.workers)]
        if args.overwrite:
            cmd.append("--overwrite")
        if args.month:
            cmd += ["--month", args.month]
        _exec(cmd)

    elif args.cmd == "staging":
        from src.pipeline.build_staging import build_staging

        build_staging()

    elif args.cmd == "facts":
        from src.pipeline.build_facts import build_facts

        build_facts()

    elif args.cmd == "marts":
        from src.pipeline.build_marts import build_marts

        build_marts()

    elif args.cmd == "build":
        from src.pipeline.build_dims import build_all_dims
        from src.pipeline.build_facts import build_facts
        from src.pipeline.build_marts import build_marts
        from src.pipeline.build_staging import build_staging

        build_all_dims()
        build_staging()
        build_facts()
        build_marts()

    elif args.cmd == "evaluate":
        from src.models.train_baselines import run_all_evaluations

        methods = (
            ("spatial_groupkfold", "random_kfold", "temporal_split")
            if args.method == "all"
            else (args.method,)
        )
        run_all_evaluations(
            n_splits=args.folds,
            seed=args.seed,
            valid_days_only=not args.all_days,
            methods=methods,
        )

    elif args.cmd == "train-final":
        from src.common.config import MART_GRID_DAILY, OUTPUTS
        from src.models.train_baselines import estimate_full_grid, train_final_models

        trained = train_final_models(
            seed=args.seed,
            valid_days_only=not args.all_days,
            model_version=args.model_version,
        )
        if args.estimate_grid and MART_GRID_DAILY.exists():
            out_grid = OUTPUTS / "predictions" / "pred_grid_daily_pm25.parquet"
            out_grid.parent.mkdir(parents=True, exist_ok=True)
            estimate_full_grid(
                trained["baseline1"]["model"],
                trained["baseline2"]["model"],
                MART_GRID_DAILY,
                out_grid,
            )

    elif args.cmd == "train":
        from src.models.train_baselines import train_and_evaluate

        train_and_evaluate(
            n_splits=args.folds,
            seed=args.seed,
            valid_days_only=not args.all_days,
            estimate_grid=args.estimate_grid,
            model_version=args.model_version,
        )

    elif args.cmd == "predict":
        from src.models.inference import run_inference

        run_inference(
            model=args.model,
            start_date=args.start_date,
            end_date=args.end_date,
            output_dir=args.output_dir,
            resume=not args.no_resume,
            run_id=args.run_id,
        )

    elif args.cmd == "lint":
        cmd = [py, "-m", "ruff", "check", "src", "tests", "run.py"]
        if args.fix:
            cmd.append("--fix")
        _exec(cmd)

    elif args.cmd == "test":
        _exec([py, "-m", "pytest", "-v"])


if __name__ == "__main__":
    main()
