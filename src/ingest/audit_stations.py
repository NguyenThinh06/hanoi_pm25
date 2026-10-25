"""
src/ingest/audit_stations.py
Kiểm toán mạng lưới trạm quan trắc mặt đất PM2.5 tại Hà Nội từ OpenAQ v3 API.
Khớp tọa độ với lưới dim_grid_1km.parquet (EPSG:3405) và phân loại Tier cảm biến.
"""
from __future__ import annotations

import json
import os
from typing import Any

import pyproj
import requests
from dotenv import load_dotenv

# Nạp biến môi trường từ .env
load_dotenv(".env")
OPENAQ_API_KEY = os.getenv("OPENAQ_API_KEY")
BASE_URL = "https://api.openaq.org/v3"

# Bounding box Hà Nội (WGS84: lon_min, lat_min, lon_max, lat_max)
HANOI_BBOX_WGS84 = [105.28, 20.56, 106.02, 21.39]


def fetch_openaq_locations() -> list[dict[str, Any]]:
    """Lấy danh sách các trạm quan trắc tại Hà Nội từ OpenAQ v3 API."""
    if not OPENAQ_API_KEY:
        print("[WARN] Chưa tìm thấy OPENAQ_API_KEY trong .env. Đang gửi request ẩn danh...")
        headers = {}
    else:
        headers = {"X-API-Key": OPENAQ_API_KEY}

    url = f"{BASE_URL}/locations"
    params = {
        "bbox": ",".join(map(str, HANOI_BBOX_WGS84)),
        "limit": 100
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        print(f"[AUDIT] Tim thay {len(results)} tram quan trac trong dia gioi Ha Noi tu OpenAQ v3.")
        return results
    except requests.RequestException as e:
        print(f"[ERROR] Khong the lay du lieu tu OpenAQ API: {e}")
        return []


def audit_and_map_stations(locations: list[dict[str, Any]]) -> None:
    """Chiếu tọa độ trạm sang EPSG:3405 và map vào dim_grid_1km."""
    grid_path = "data/core/dim_grid_1km.parquet"
    if not os.path.exists(grid_path):
        raise FileNotFoundError(f"Chưa tìm thấy file {grid_path}. Hãy chạy `python run.py grid` trước!")

    # Bộ biến đổi tọa độ WGS84 -> VN-2000 UTM Zone 48N (EPSG:3405)
    transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3405", always_xy=True)

    station_records = []
    for loc in locations:
        loc_id = loc.get("id")
        name = loc.get("name", "Unknown")
        coords = loc.get("coordinates", {})
        lon = coords.get("longitude")
        lat = coords.get("latitude")

        if lon is None or lat is None:
            continue

        # Chuyển sang mét EPSG:3405
        easting_m, northing_m = transformer.transform(lon, lat)

        # Xác định grid_id ô lưới 1km chứa trạm (bước nhảy 1000m)
        grid_x = int(easting_m // 1000) * 1000
        grid_y = int(northing_m // 1000) * 1000
        grid_id = f"grid_{grid_x}_{grid_y}"

        # Phân loại Tier cảm biến
        provider_name = loc.get("provider", {}).get("name", "")
        loc_name_lower = name.lower()
        provider_lower = provider_name.lower()
        if "diplomatic" in loc_name_lower or "spartan" in loc_name_lower or "embassy" in provider_lower:
            sensor_tier = "Tier_1_Reference_FEM"
        else:
            sensor_tier = "Tier_2_LowCost_Optical"

        # Phân loại vi môi trường sơ bộ
        if "road" in loc_name_lower or "traffic" in loc_name_lower:
            microenv = "Roadside"
        elif "rural" in loc_name_lower or northing_m > 2350000 or easting_m < 540000:
            microenv = "Rural_Background"
        else:
            microenv = "Urban_Background"

        # Kiểm tra sensor PM2.5
        sensors = loc.get("sensors", [])
        pm25_sensor = next((s for s in sensors if s.get("parameter", {}).get("name") == "pm25"), None)
        pm25_sensor_id = pm25_sensor.get("id") if pm25_sensor else None

        station_records.append({
            "station_id": f"openaq_{loc_id}",
            "source_id": loc_id,
            "station_name": name,
            "provider": provider_name or "Unknown",
            "sensor_tier": sensor_tier,
            "station_microenv_type": microenv,
            "grid_id": grid_id,
            "lon_wgs84": lon,
            "lat_wgs84": lat,
            "easting_m": round(easting_m, 2),
            "northing_m": round(northing_m, 2),
            "pm25_sensor_id": pm25_sensor_id,
            "is_active": loc.get("datetimeLast") is not None
        })

    # Lưu kết quả kiểm toán ra registry json
    registry_path = "data/reference/station_registry.json"
    os.makedirs(os.path.dirname(registry_path), exist_ok=True)
    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(station_records, f, indent=2, ensure_ascii=False)
    print(f"[AUDIT] Da luu danh muc {len(station_records)} tram vao {registry_path}")

    # Xuất báo cáo markdown
    report_path = "docs/ground_truth_audit_report.md"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# BÁO CÁO KIỂM TOÁN MẠNG LƯỚI TRẠM QUAN TRẮC MẶT ĐẤT HÀ NỘI\n\n")
        f.write(f"- **Ngày kiểm toán:** {pyproj.__version__} / OpenAQ v3 API\n")
        f.write(f"- **Tổng số trạm trong địa giới:** {len(station_records)}\n\n")
        f.write("| Mã trạm | Tên trạm | Đơn vị quản lý | Cấp độ (Tier) | Vi môi trường | Grid ID (1km) |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- | :--- |\n")
        f.writelines(f"| `{st['station_id']}` | {st['station_name']} | {st['provider']} | `{st['sensor_tier']}` | {st['station_microenv_type']} | `{st['grid_id']}` |\n" for st in station_records[:20])
    print(f"[AUDIT] Da xuat bao cao kiem toan tram tai {report_path}")


if __name__ == "__main__":
    locs = fetch_openaq_locations()
    if locs:
        audit_and_map_stations(locs)
