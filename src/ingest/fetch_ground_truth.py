"""
src/ingest/fetch_ground_truth.py
Thu thập dữ liệu chuỗi giờ PM2.5 từ OpenAQ v3 API cho các trạm quan trắc Hà Nội giai đoạn 2021-2025.
Lưu trữ dạng Hive Partitioning: data/raw/ground_truth/source=openaq/year=YYYY/month=MM/data.parquet
Đảm bảo tính lũy đẳng (Idempotency) với mã băm SHA-256 _row_hash và cơ chế Resume an toàn.
"""
from __future__ import annotations

import argparse
import io
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

# Đảm bảo Windows console không bị UnicodeEncodeError
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, io.UnsupportedOperation):
        pass

load_dotenv(".env")
OPENAQ_API_KEY = os.getenv("OPENAQ_API_KEY")
BASE_URL = "https://api.openaq.org/v3"


class OpenAQClient:
    """REST Client kết nối OpenAQ v3 có cơ chế tự động thử lại khi gặp 429 Rate Limit."""

    def __init__(self, api_key: str | None = None):
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({"X-API-Key": api_key})

    def get(self, path: str, **params) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        for attempt in range(6):
            try:
                r = self.session.get(url, params=params, timeout=30)
                if r.status_code in (429, 503):
                    wait = float(r.headers.get("Retry-After", 2 ** attempt * 2))
                    print(f"  [WAIT] HTTP {r.status_code}, waiting {wait:.1f}s...", file=sys.stderr)
                    time.sleep(wait)
                    continue
                if r.status_code == 404:
                    return {}
                r.raise_for_status()
                time.sleep(0.25)  # Safe request rate
                return r.json()
            except requests.RequestException as e:
                if attempt == 5:
                    print(f"  [ERROR] Connection failed: {e}", file=sys.stderr)
                    return {}
                time.sleep(2 ** attempt)
        return {}


def is_station_active_in_month(station: dict[str, Any], year: int, month: int) -> bool:
    """Kiểm tra trạm có khả năng có dữ liệu trong tháng này không dựa vào metadata kiểm toán."""
    dt_first = station.get("datetime_first_utc")
    dt_last = station.get("datetime_last_utc")

    # Nếu không có metadata ngày hoạt động thì trạm không có số liệu
    if not dt_first or not dt_last:
        return False

    month_start = f"{year:04d}-{month:02d}-01T00:00:00Z"
    if month == 12:
        month_end = f"{year + 1:04d}-01-01T00:00:00Z"
    else:
        month_end = f"{year:04d}-{month + 1:02d}-01T00:00:00Z"

    if month_end < dt_first:
        return False
    return month_start <= dt_last


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


def ingest_ground_truth(
    start_year: int = 2021,
    end_year: int = 2025,
    station_limit: int = 0,
    force_reload: bool = False
):
    """
    Quy trình thu thập toàn diện cho dải năm (mặc định 2021-2025).
    Tự động bỏ qua trạm/tháng đã tải đầy đủ trừ khi bật force_reload.
    """
    registry_path = "data/reference/station_registry.json"
    if not os.path.exists(registry_path):
        raise FileNotFoundError(f"Chua co file {registry_path}. Hay chay `python run.py audit` truoc!")

    with open(registry_path, "r", encoding="utf-8") as f:
        stations = json.load(f)

    # Lọc các trạm có cảm biến PM2.5
    pm25_stations = [s for s in stations if s.get("pm25_sensor_id") is not None]
    if station_limit > 0:
        pm25_stations = pm25_stations[:station_limit]

    print(f"\n[INGEST] Bat dau thu thap du lieu OpenAQ tu {start_year} den {end_year} ({len(pm25_stations)} stations configured)...")
    client = OpenAQClient(OPENAQ_API_KEY)

    total_added_records = 0
    for y in range(start_year, end_year + 1):
        for m in range(1, 13):
            target_parquet = f"data/raw/ground_truth/source=openaq/year={y}/month={m:02d}/data.parquet"

            existing_stations = set()
            if os.path.exists(target_parquet) and not force_reload:
                try:
                    existing_stations = set(
                        pl.read_parquet(target_parquet, columns=["station_id"])["station_id"].unique().to_list()
                    )
                except (pl.exceptions.PolarsError, OSError):
                    pass

            # Lọc các trạm có thời gian hoạt động trùng với tháng này
            active_stations = [st for st in pm25_stations if is_station_active_in_month(st, y, m)]
            needed_stations = [st for st in active_stations if force_reload or st["station_id"] not in existing_stations]

            if not active_stations:
                continue

            if not needed_stations:
                print(f"[SKIP] Month {m:02d}/{y}: All {len(active_stations)} active stations already downloaded.")
                continue

            print(f"\n[INGEST] >>> Month {m:02d}/{y} (fetching {len(needed_stations)}/{len(active_stations)} active stations)...")
            month_records = []
            for st in needed_stations:
                recs = fetch_sensor_hourly(client, st, y, m)
                raw_name = st.get("station_name", "Unknown")
                ascii_name = raw_name.encode("ascii", "ignore").decode("ascii")
                if recs:
                    print(f"  + Station {st['station_id']} ({ascii_name[:20]}): {len(recs)} hours.")
                    month_records.extend(recs)

            if month_records:
                df = pl.DataFrame(month_records)
                added = append_idempotent_raw_parquet(df, target_parquet)
                total_added_records += added
                print(f"[SUCCESS] Month {m:02d}/{y}: Saved {added} new records into {target_parquet}")
            else:
                print(f"[INFO] Month {m:02d}/{y}: No records returned from {len(needed_stations)} stations.")

    print(f"\n[COMPLETE] Ingest finished. Added {total_added_records} new hourly records into Lakehouse!\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest OpenAQ Ground Truth data")
    parser.add_argument("--start-year", type=int, default=2021, help="Năm bắt đầu (mặc định: 2021)")
    parser.add_argument("--end-year", type=int, default=2025, help="Năm kết thúc (mặc định: 2025)")
    parser.add_argument("--limit-stations", type=int, default=0, help="Giới hạn số trạm (0 = toàn bộ các trạm)")
    parser.add_argument("--force", action="store_true", help="Bắt buộc cào lại kể cả khi file đã tồn tại")
    args = parser.parse_args()

    ingest_ground_truth(
        start_year=args.start_year,
        end_year=args.end_year,
        station_limit=args.limit_stations,
        force_reload=args.force
    )
