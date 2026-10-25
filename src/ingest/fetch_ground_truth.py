"""
src/ingest/fetch_ground_truth.py
Thu thập dữ liệu chuỗi giờ PM2.5 từ OpenAQ v3 API cho các trạm quan trắc Hà Nội.
Lưu trữ dạng Hive Partitioning: data/raw/ground_truth/source=openaq/year=YYYY/month=MM/data.parquet
Đảm bảo tính lũy đẳng (Idempotency) với mã băm SHA-256 _row_hash.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from typing import Any

import polars as pl
import requests
from dotenv import load_dotenv

from src.common.hashing import append_idempotent_raw_parquet, compute_row_hash

load_dotenv(".env")
OPENAQ_API_KEY = os.getenv("OPENAQ_API_KEY")
BASE_URL = "https://api.openaq.org/v3"


class OpenAQClient:
    """Client giao tiếp OpenAQ v3 với cơ chế tự động thử lại khi gặp Rate Limit (HTTP 429)."""
    def __init__(self, api_key: str | None = None):
        self.session = requests.Session()
        if api_key:
            self.session.headers["X-API-Key"] = api_key

    def get(self, path: str, **params) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        for attempt in range(5):
            try:
                r = self.session.get(url, params=params, timeout=30)
                if r.status_code in (429, 503):
                    wait = float(r.headers.get("Retry-After", 2 ** attempt * 2))
                    print(f"  [WAIT] Gặp giới hạn kết nối HTTP {r.status_code}, chờ {wait:.1f}s...", file=sys.stderr)
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                time.sleep(0.5)  # Giữ tốc độ an toàn dưới 60 requests/phút
                return r.json()
            except requests.RequestException as e:
                if attempt == 4:
                    raise OSError(f"Thất bại kết nối OpenAQ API: {e}") from e
                time.sleep(2 ** attempt)
        return {}


def fetch_sensor_hourly(
    client: OpenAQClient,
    station: dict[str, Any],
    year: int,
    month: int
) -> list[dict[str, Any]]:
    """Tải số liệu 1 tháng của một cảm biến cụ thể."""
    sensor_id = station.get("pm25_sensor_id")
    station_id = station.get("station_id")
    if not sensor_id:
        return []

    # Khoảng thời gian đầu và cuối tháng (UTC)
    start_dt = f"{year:04d}-{month:02d}-01T00:00:00Z"
    if month == 12:
        end_dt = f"{year + 1:04d}-01-01T00:00:00Z"
    else:
        end_dt = f"{year:04d}-{month + 1:02d}-01T00:00:00Z"

    records = []
    page = 1
    while True:
        data = client.get(
            f"/sensors/{sensor_id}/hours",
            datetime_from=start_dt,
            datetime_to=end_dt,
            limit=1000,
            page=page
        )
        results = data.get("results", [])
        if not results:
            break

        for item in results:
            period = item.get("period", {})
            dt_from = period.get("datetimeFrom", {})
            dt_to = period.get("datetimeTo", {})
            val = item.get("value")

            if val is None or val < 0:
                continue

            utc_from = dt_from.get("utc")
            utc_to = dt_to.get("utc")
            local_from = dt_from.get("local")

            # Mã băm SHA-256 duy nhất cho từng dòng đo
            row_hash = compute_row_hash([station_id, utc_from, val])

            records.append({
                "station_id": station_id,
                "sensor_id": sensor_id,
                "grid_id": station.get("grid_id"),
                "datetime_utc": utc_from,
                "datetime_to_utc": utc_to,
                "datetime_local": local_from,
                "pm25_ug_m3": float(val),
                "sensor_tier": station.get("sensor_tier"),
                "station_microenv": station.get("station_microenv_type"),
                "_row_hash": row_hash,
                "ingested_at": datetime.now(UTC).isoformat()
            })

        if len(results) < 1000:
            break
        page += 1

    return records


def ingest_ground_truth(year: int = 2024, month: int = 1, station_limit: int = 5):
    """Quy trình thu thập và lưu trữ phân vùng Hive."""
    registry_path = "data/reference/station_registry.json"
    if not os.path.exists(registry_path):
        raise FileNotFoundError(f"Chưa có file {registry_path}. Hãy chạy `python run.py audit` trước!")

    with open(registry_path, "r", encoding="utf-8") as f:
        stations = json.load(f)

    # Lọc các trạm có cảm biến PM2.5
    pm25_stations = [s for s in stations if s.get("pm25_sensor_id") is not None]
    if station_limit > 0:
        pm25_stations = pm25_stations[:station_limit]

    print(f"\n[INGEST] Bắt đầu thu thập dữ liệu tháng {month:02d}/{year} cho {len(pm25_stations)} trạm...")
    client = OpenAQClient(OPENAQ_API_KEY)

    all_month_records = []
    for st in pm25_stations:
        print(f"  -> Đang tải trạm: {st['station_id']} ({st['station_name'][:25]})...", end="", flush=True)
        recs = fetch_sensor_hourly(client, st, year, month)
        print(f" {len(recs)} bản ghi giờ.")
        all_month_records.extend(recs)

    if not all_month_records:
        print(f"[WARN] Không có bản ghi nào trong tháng {month:02d}/{year}.")
        return

    # Đường dẫn phân vùng Hive
    target_parquet = f"data/raw/ground_truth/source=openaq/year={year}/month={month:02d}/data.parquet"
    df = pl.DataFrame(all_month_records)

    # Ghi lũy đẳng (chống trùng lặp bằng _row_hash)
    added = append_idempotent_raw_parquet(df, target_parquet)
    print(f"[SUCCESS] Đã ghi {added} bản ghi mới vào: {target_parquet}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest OpenAQ Ground Truth data")
    parser.add_argument("--year", type=int, default=2024, help="Năm cần cào dữ liệu")
    parser.add_argument("--month", type=int, default=1, help="Tháng cần cào dữ liệu")
    parser.add_argument("--limit-stations", type=int, default=5, help="Giới hạn số trạm cào thử nghiệm")
    args = parser.parse_args()

    ingest_ground_truth(year=args.year, month=args.month, station_limit=args.limit_stations)
