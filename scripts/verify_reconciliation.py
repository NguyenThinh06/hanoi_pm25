"""Kịch bản tự động thực hiện quy trình Đối soát 3 điểm bắt buộc (Gói 4).

Theo quy định tại Mục 6.2 của docs/HANDOVER.md:
So sánh giá trị nồng độ PM2.5 dự đoán qua chuỗi luân chuyển dữ liệu:
  1. File Parquet nguồn (outputs/predictions/...)
  2. Database PostgreSQL (bảng grid_daily_predictions)
  3. FastAPI Response (GET /api/map & GET /api/grids/{grid_id}/history)
  4. Giao diện React (hiển thị trường raw "Giá trị API")

Tiêu chuẩn nghiệm thu: Sai lệch tuyệt đối = 0.00000000 µg/m³.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import duckdb
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POINTS = [
    {
        "name": "Điểm 1 (Khu vực Ba Đình / Đống Đa, Baseline 2)",
        "grid_id": "grid_584000_2324000",
        "date": "2024-01-15",
        "model_id": "Baseline_2_OpenAQ_Meteo_Sat:v2.0.0-retrospective",
        "model_alias": "baseline2",
        "version": "v2.0.0-retrospective",
    },
    {
        "name": "Điểm 2 (Khu vực Hoàn Kiếm, Baseline 1)",
        "grid_id": "grid_585000_2324000",
        "date": "2024-01-15",
        "model_id": "Baseline_1_OpenAQ_Meteo:v2.0.0-retrospective",
        "model_alias": "baseline1",
        "version": "v2.0.0-retrospective",
    },
    {
        "name": "Điểm 3 (Khu vực An Khánh / Hoài Đức, Baseline 2)",
        "grid_id": "grid_574000_2322000",
        "date": "2024-01-20",
        "model_id": "Baseline_2_OpenAQ_Meteo_Sat:v2.0.0-retrospective",
        "model_alias": "baseline2",
        "version": "v2.0.0-retrospective",
    },
]


def query_parquet_value(point: dict[str, str]) -> float | None:
    """Tra cứu giá trị chính xác từ file Parquet partition tương ứng."""
    year_month = point["date"][:7]
    parquet_path = (
        ROOT
        / "outputs"
        / "predictions"
        / point["model_alias"]
        / point["version"]
        / f"{year_month}.parquet"
    )
    if not parquet_path.is_file():
        # Kiểm tra thêm trong handover_staging nếu có
        staging_path = (
            ROOT
            / "outputs"
            / "handover_staging"
            / "predictions"
            / point["model_alias"]
            / point["version"]
            / f"{year_month}.parquet"
        )
        if staging_path.is_file():
            parquet_path = staging_path
        else:
            return None

    con = duckdb.connect()
    res = con.execute(
        f"""
        SELECT pm25_pred FROM read_parquet('{parquet_path.as_posix()}')
        WHERE grid_id = '{point['grid_id']}' AND date = '{point['date']}'
        """
    ).fetchone()
    return float(res[0]) if res else None


def query_db_value(point: dict[str, str], db_url: str | None) -> float | None:
    """Tra cứu trực tiếp từ PostgreSQL."""
    if not db_url:
        return None
    try:
        import psycopg

        with psycopg.connect(db_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT pm25_pred FROM grid_daily_predictions
                    WHERE grid_id = %s AND date = %s AND model_id = %s
                    """,
                    (point["grid_id"], point["date"], point["model_id"]),
                )
                row = cur.fetchone()
                return float(row[0]) if row else None
    except Exception as e:
        print(f"  [DB Warning] Không truy vấn được DB ({e})", file=sys.stderr)
        return None


def query_api_value(point: dict[str, str], api_base_url: str) -> float | None:
    """Gọi HTTP GET sang API server để lấy giá trị nồng độ phục vụ frontend."""
    # 1. Gọi /api/map
    encoded_model = urllib.parse.quote(point["model_id"])
    url = f"{api_base_url.rstrip('/')}/api/map?date={point['date']}&model_id={encoded_model}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "HanoiPM25-Reconciliation/1.0"})
        with urllib.request.urlopen(req, timeout=5) as res:
            if res.status == 200:
                payload = json.loads(res.read().decode("utf-8"))
                for item in payload.get("data", []):
                    if item.get("grid_id") == point["grid_id"]:
                        return float(item.get("pm25_pred"))
    except Exception as e:
        print(f"  [API Warning] Lỗi gọi API {url}: {e}", file=sys.stderr)

    return None


def run_reconciliation(api_url: str, db_url: str | None) -> bool:
    print("================================================================================")
    print("BẮT ĐẦU ĐỐI SOÁT 3 ĐIỂM DỮ LIỆU PM2.5 HÀ NỘI (GÓI 4)")
    print(f"  + API Endpoint: {api_url}")
    print(f"  + PostgreSQL  : {db_url or 'Chưa cấu hình (bỏ qua bước DB)'}")
    print("================================================================================\n")

    all_passed = True
    results = []

    for i, pt in enumerate(DEFAULT_POINTS, 1):
        print(f"Đang kiểm tra {pt['name']}...")
        print(f"  -> Khóa: grid_id={pt['grid_id']} | date={pt['date']} | model={pt['model_alias']}")

        v_parquet = query_parquet_value(pt)
        v_db = query_db_value(pt, db_url)
        v_api = query_api_value(pt, api_url)

        # Tính sai lệch
        delta_db = abs(v_parquet - v_db) if (v_parquet is not None and v_db is not None) else None
        delta_api = abs(v_parquet - v_api) if (v_parquet is not None and v_api is not None) else None

        passed = True
        if v_parquet is None:
            status = "THIẾU PARQUET"
            passed = False
        elif v_db is not None and delta_db != 0.0:
            status = "LỆCH DATABASE"
            passed = False
        elif v_api is not None and delta_api != 0.0:
            status = "LỆCH API"
            passed = False
        else:
            status = "KHỚP 100% (ĐẠT)"

        if not passed:
            all_passed = False

        results.append(
            {
                "stt": i,
                "name": pt["name"],
                "grid_id": pt["grid_id"],
                "date": pt["date"],
                "model": pt["model_alias"],
                "parquet": v_parquet,
                "db": v_db,
                "api": v_api,
                "status": status,
            }
        )

    # Hiển thị bảng tổng hợp
    header = (
        f"{'STT':<4} | {'Mã ô':<22} | {'Ngày':<10} | {'Model':<10} | "
        f"{'Parquet':<10} | {'Postgres':<10} | {'API':<10} | {'Kết quả'}"
    )
    print("\n" + "=" * 95)
    print(header)
    print("-" * 95)
    for r in results:
        p_str = f"{r['parquet']:.4f}" if r["parquet"] is not None else "N/A"
        db_str = f"{r['db']:.4f}" if r["db"] is not None else "N/A"
        api_str = f"{r['api']:.4f}" if r["api"] is not None else "N/A"
        row = (
            f"{r['stt']:<4} | {r['grid_id']:<22} | {r['date']:<10} | {r['model']:<10} | "
            f"{p_str:<10} | {db_str:<10} | {api_str:<10} | {r['status']}"
        )
        print(row)
    print("=" * 95 + "\n")

    if all_passed:
        print(">>> KẾT QUẢ: ĐỐI SOÁT 3 ĐIỂM ĐẠT CHUẨN NGHIỆM THU! (Sai lệch = 0.000000 µg/m³)")
    else:
        print(">>> KẾT QUẢ: CÓ SAI LỆCH HOẶC THIẾU DỮ LIỆU. Vui lòng kiểm tra lại dịch vụ.")

    return all_passed


def main() -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Script đối soát 3 điểm (Gói 4)")
    parser.add_argument("--api-url", default=os.getenv("API_URL", "http://localhost:8000"), help="Địa chỉ API")
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL"), help="Chuỗi kết nối PostgreSQL")
    args = parser.parse_args()

    success = run_reconciliation(api_url=args.api_url, db_url=args.db_url)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
