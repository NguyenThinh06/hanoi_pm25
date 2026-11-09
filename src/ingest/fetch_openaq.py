"""Thu thập OpenAQ v3: metadata trạm trong bbox Hà Nội và chuỗi giờ của từng sensor.

Đầu ra (raw, không biến đổi giá trị):
  data/raw/openaq/locations.json                     – toàn bộ location + sensor trong bbox
  data/raw/openaq/hours/sensor_<id>_<year>.parquet   – số đo giờ của 1 sensor trong 1 năm UTC

Các thông số thu thập: pm25, pm10, temperature, relativehumidity.
Chạy lại an toàn: sensor-năm đã có file sẽ được bỏ qua (dùng --overwrite để tải lại).
File rỗng vẫn được ghi để đánh dấu "đã hỏi, nguồn không có dữ liệu".
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.common import config
from src.common.storage import write_json, write_parquet

BASE_URL = "https://api.openaq.org/v3"
PAGE_LIMIT = 1000
HOURS_COLUMNS = ["sensor_id", "datetime_from_utc", "datetime_to_utc", "value", "observed_count"]

# Khoảng UTC bao trọn các ngày Hà Nội của phạm vi phân tích (01/01/2021 - 30/09/2026)
PERIOD_START_UTC = (
    datetime.combine(config.START_DATE, datetime.min.time(), timezone.utc)
    - timedelta(hours=config.UTC_OFFSET_HOURS)
)
PERIOD_END_UTC = (
    datetime.combine(config.END_DATE + timedelta(days=1), datetime.min.time(), timezone.utc)
    - timedelta(hours=config.UTC_OFFSET_HOURS)
)


class OpenAQ:
    """Client tối giản: tự thử lại lỗi 429/5xx và tôn trọng hạn mức 60 request/phút."""

    def __init__(self, session: requests.Session | None = None) -> None:
        if session is not None:
            self.session = session
            return
        load_dotenv(config.ROOT / ".env")
        key = (os.getenv("OPENAQ_API_KEY") or "").strip()
        if not key:
            raise SystemExit("Thiếu OPENAQ_API_KEY trong .env")
        self.session = requests.Session()
        self.session.headers["X-API-Key"] = key
        retry = Retry(
            total=8,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            respect_retry_after_header=True,
            allowed_methods=["GET"],
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def get(self, path: str, **params) -> list[dict]:
        """Trả về danh sách `results` của mọi trang."""
        results, page = [], 1
        while True:
            for attempt in range(6):
                r = self.session.get(
                    f"{BASE_URL}{path}",
                    params={**params, "limit": PAGE_LIMIT, "page": page},
                    timeout=120,
                )
                if r.status_code == 429:
                    wait = float(r.headers.get("X-Ratelimit-Reset", 60)) + 2
                    print(f"  [openaq] chạm hạn mức 429, đợi {wait:.0f}s...", flush=True)
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                break
            else:
                r.raise_for_status()
            batch = r.json()["results"]
            results.extend(batch)
            if int(r.headers.get("X-Ratelimit-Remaining", 10)) <= 1:
                time.sleep(float(r.headers.get("X-Ratelimit-Reset", 60)) + 1)
            if len(batch) < PAGE_LIMIT:
                return results
            page += 1


def fetch_locations(client: OpenAQ) -> list[dict]:
    """Lấy toàn bộ location kèm danh sách sensor trong bbox Hà Nội."""
    locations = client.get("/locations", bbox=",".join(map(str, config.BBOX_WGS84)))
    write_json(
        {
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "bbox_wgs84": list(config.BBOX_WGS84),
            "locations": locations,
        },
        config.RAW_OPENAQ_LOCATIONS,
    )
    print(f"[openaq] {len(locations)} location trong bbox -> {config.RAW_OPENAQ_LOCATIONS.name}")
    return locations


def load_sensors(locations_path=config.RAW_OPENAQ_LOCATIONS) -> pd.DataFrame:
    """Bảng sensor (sensor_id, station_id, parameter, units) từ locations.json, chỉ các tham số cần dùng."""
    if not locations_path.exists():
        raise FileNotFoundError(f"Thiếu {locations_path}; hãy chạy `python run.py fetch-openaq` trước.")
    locations = json.loads(locations_path.read_text(encoding="utf-8"))["locations"]
    rows = [
        {
            "sensor_id": int(s["id"]),
            "station_id": f"openaq_{loc['id']}",
            "parameter": s["parameter"]["name"].lower(),
            "units": s["parameter"].get("units", ""),
            "datetime_first_utc": (loc.get("datetimeFirst") or {}).get("utc"),
            "datetime_last_utc": (loc.get("datetimeLast") or {}).get("utc"),
        }
        for loc in locations
        for s in loc.get("sensors", [])
        if (s.get("parameter") or {}).get("name", "").lower() in config.OPENAQ_PARAMETERS
    ]
    return pd.DataFrame(rows)


def year_windows(first_utc: str | None, last_utc: str | None) -> list[tuple[int, datetime, datetime]]:
    """Các năm UTC cần tải, cắt theo phạm vi phân tích và thời gian hoạt động của trạm (nếu biết)."""
    lo, hi = PERIOD_START_UTC, PERIOD_END_UTC
    if isinstance(first_utc, str) and first_utc:
        lo = max(lo, datetime.fromisoformat(first_utc.replace("Z", "+00:00")))
    if isinstance(last_utc, str) and last_utc:
        hi = min(hi, datetime.fromisoformat(last_utc.replace("Z", "+00:00")) + timedelta(hours=1))
    out = []
    for year in range(lo.year, hi.year + 1):
        start = max(lo, datetime(year, 1, 1, tzinfo=timezone.utc))
        end = min(hi, datetime(year + 1, 1, 1, tzinfo=timezone.utc))
        if start < end:
            out.append((year, start, end))
    return out


def fetch_sensor_year(client: OpenAQ, sensor_id: int, start: datetime, end: datetime) -> pd.DataFrame:
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    results = client.get(
        f"/sensors/{sensor_id}/hours",
        datetime_from=start.strftime(fmt),
        datetime_to=end.strftime(fmt),
    )
    df = pd.DataFrame(
        [
            {
                "sensor_id": int(sensor_id),
                "datetime_from_utc": r["period"]["datetimeFrom"]["utc"],
                "datetime_to_utc": r["period"]["datetimeTo"]["utc"],
                "value": r.get("value"),
                "observed_count": (r.get("coverage") or {}).get("observedCount"),
            }
            for r in results
        ],
        columns=HOURS_COLUMNS,
    )
    df["sensor_id"] = df["sensor_id"].astype("int64")
    df["datetime_from_utc"] = pd.to_datetime(df["datetime_from_utc"], utc=True)
    df["datetime_to_utc"] = pd.to_datetime(df["datetime_to_utc"], utc=True)
    df["value"] = df["value"].astype("float64")
    df["observed_count"] = df["observed_count"].astype("Int32")
    # API có thể trả cả mốc ngay ngoài khoảng: chỉ giữ giờ bắt đầu trong [start, end)
    keep = (df.datetime_from_utc >= pd.Timestamp(start)) & (df.datetime_from_utc < pd.Timestamp(end))
    return df[keep].drop_duplicates(["sensor_id", "datetime_from_utc"], keep="last").reset_index(drop=True)


def fetch_hours(
    client: OpenAQ,
    overwrite: bool = False,
    limit_sensors: int = 0,
    year_filter: int | None = None,
) -> None:
    sensors = load_sensors()
    if limit_sensors > 0:
        sensors = sensors.head(limit_sensors)
    tasks = [
        (s.sensor_id, s.parameter, *w)
        for s in sensors.itertuples()
        for w in year_windows(s.datetime_first_utc, s.datetime_last_utc)
        if year_filter is None or w[0] == year_filter
    ]
    params_str = ", ".join(config.OPENAQ_PARAMETERS)
    print(f"[openaq] {len(sensors)} sensor ({params_str}), {len(tasks)} sensor-năm", flush=True)
    for i, (sensor_id, param, year, start, end) in enumerate(tasks, 1):
        path = config.RAW_OPENAQ_HOURS / f"sensor_{sensor_id}_{year}.parquet"
        if path.exists() and not overwrite:
            continue
        df = fetch_sensor_year(client, sensor_id, start, end)
        write_parquet(df, path)
        print(f"[openaq] {i}/{len(tasks)} sensor {sensor_id} ({param}) năm {year}: {len(df):,} giờ", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--metadata-only", action="store_true", help="Chỉ tải metadata locations.json")
    parser.add_argument("--overwrite", action="store_true", help="Tải lại cả sensor-năm đã có file")
    parser.add_argument("--limit-sensors", type=int, default=0, help="Giới hạn số sensor (0 = tất cả)")
    parser.add_argument("--year", type=int, default=None, help="Chỉ tải một năm UTC cụ thể")
    args = parser.parse_args()

    client = OpenAQ()
    if args.overwrite or not config.RAW_OPENAQ_LOCATIONS.exists() or args.metadata_only:
        fetch_locations(client)
    if not args.metadata_only:
        fetch_hours(client, overwrite=args.overwrite, limit_sensors=args.limit_sensors, year_filter=args.year)


if __name__ == "__main__":
    main()
