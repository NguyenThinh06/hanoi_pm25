# HANOI_PM25 — Spatial Data Lakehouse Pipeline (01/2021 – 09/2026)

Pipeline thu thập, chuẩn hóa và tổng hợp dữ liệu không-thời gian phục vụ bài toán ước lượng và dự báo bụi mịn **PM2.5** theo ngày trên lưới **1 km × 1 km (EPSG:3405)** tại Hà Nội giai đoạn **01/01/2021 – 30/09/2026** (múi giờ `Asia/Ho_Chi_Minh`, UTC+7).

---

## 1. Cấu trúc thư mục

```text
pm25_hanoi/
├── data/
│   ├── reference/          # Ranh giới hành chính Hà Nội (hanoi_boundary.geojson)
│   ├── raw/                # Dữ liệu gốc từ OpenAQ v3 & Google Earth Engine
│   ├── staging/            # Dữ liệu đã chuẩn hóa kiểu, đơn vị và gắn cờ QC
│   ├── core/               # Star Schema: 3 bảng chiều (dim_*) + 3 bảng sự kiện (fct_*)
│   └── marts/              # Bảng đặc trưng toàn lưới & bảng huấn luyện cấp trạm
├── docs/
│   ├── schema.md           # Đặc tả chi tiết kiến trúc, bảng và cột dữ liệu
│   ├── business_case.md    # Business Case & khung 6 giả thuyết nghiên cứu (H1 - H6)
│   └── model_report.md     # Báo cáo kiểm định giả thuyết bằng XGBoost (H5 - H6) & ước tính 7,57M ô-ngày
├── notebooks/
│   ├── 01_raw_and_initial_eda.ipynb     # EDA ban đầu trên dữ liệu thô & ra quyết định thiết kế/chọn biến
│   └── 02_hypothesis_testing_eda.ipynb  # EDA kiểm định thống kê cho từng giả thuyết (H1 - H4)
├── src/
│   ├── common/
│   │   ├── config.py       # Tham số thời gian, không gian, đường dẫn
│   │   ├── storage.py      # Ghi Parquet/JSON nguyên tử & thực thi SQL DuckDB
│   │   └── gee.py          # Tiện ích tải raster 1 km EPSG:3405 từ Earth Engine
│   ├── ingest/
│   │   ├── fetch_openaq.py     # Tải metadata trạm + giờ (pm25, pm10, no2, so2, co, co2, o3, temp, RH)
│   │   ├── fetch_meteo.py      # Tải ERA5-Land hourly + ERA5 BLH từ GEE
│   │   └── fetch_satellite.py  # Tải Sentinel-5P, MODIS MAIAC AOD, VIIRS từ GEE
│   ├── pipeline/
│   │   ├── build_dims.py       # Tạo dim_grid_1km, dim_date, dim_station (kèm cờ is_boundary)
│   │   ├── build_staging.py    # Tạo stg_openaq_hourly, stg_meteo_daily, stg_satellite_daily, stg_viirs_monthly
│   │   ├── build_facts.py      # Tạo fct_station_daily, fct_grid_meteo_daily, fct_grid_satellite_daily
│   │   └── build_marts.py      # Tạo mart_grid_daily_features, mart_station_daily_training
│   └── models/
│       └── train_baselines.py  # Huấn luyện XGBoost so sánh 2 Baseline & ước tính 7,57 triệu ô-ngày
├── tests/unit/
│   └── test_pipeline.py    # Unit tests kiểm định toàn trình SQL & QC
├── requirements.txt
├── pyproject.toml
└── run.py                  # CLI điều phối duy nhất
```

---

## 2. Cài đặt & Cấu hình

```powershell
python -m pip install -r requirements.txt
```

Tạo file `.env` ở thư mục gốc:

```ini
OPENAQ_API_KEY=<api_key_openaq_v3>
GEE_PROJECT=<google_cloud_project_id_da_bat_earth_engine>
```

Xác thực Google Earth Engine lần đầu trên máy:

```powershell
earthengine authenticate
```

---

## 3. Quy trình vận hành (CLI)

Tất cả thao tác đều chạy qua `run.py`:

```powershell
# Bước 1: Sinh lưới chuẩn 1 km (3.610 ô) và trục ngày (01/01/2021 - 30/09/2026 = 2.099 ngày)
python run.py dims

# Bước 2: Thu thập dữ liệu gốc (có cơ chế resume, bỏ qua file đã tải)
python run.py fetch-openaq                 # Metadata + chuỗi giờ PM2.5, PM10, nhiệt độ, độ ẩm
python run.py fetch-meteo --workers 4      # ERA5-Land + ERA5 BLH (69 tháng: 2021-01 -> 2026-09)
python run.py fetch-satellite --workers 4  # S5P (NO2, CO, O3, SO2), MODIS AOD, VIIRS (69 tháng)

# Bước 3: Xây dựng lại toàn bộ Dims -> Staging -> Core Facts -> Feature Marts
python run.py build

# Bước 4: Huấn luyện XGBoost so sánh 2 Baseline & ước tính PM2.5 trên tập 7,57 triệu ô-ngày
python run.py train
```

Tải thử nghiệm 1 tháng hoặc chỉ cập nhật metadata trạm:

```powershell
python run.py fetch-openaq --metadata-only
python run.py fetch-meteo --month 2026-09
python run.py fetch-satellite --month 2026-09
```

Kiểm tra chất lượng mã nguồn và chạy kiểm thử:

```powershell
python run.py lint
python run.py test
```

Xem chi tiết thiết kế bảng, khóa chính và quy tắc QC tại [`docs/schema.md`](./docs/schema.md).
