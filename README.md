# HANOI_PM25 — Spatial Data Lakehouse Pipeline (01/2021 – 09/2026)

Triển khai trọn gói (Gói 4): xem [Hướng dẫn triển khai 1-chạm Docker Compose, Đối soát 3 điểm & Vận hành](docs/DEPLOYMENT.md).
Backend FastAPI Gói 2: xem [hướng dẫn chạy, API Contract v1 và kiểm thử](docs/BACKEND.md).
Frontend React Dashboard Gói 3: xem [hướng dẫn phát triển giao diện](frontend/README.md).

Pipeline thu thập, chuẩn hóa và kết hợp dữ liệu không-thời gian để **ước tính hồi cứu nồng độ PM2.5 trung bình ngày** trên lưới **1 km × 1 km (EPSG:3405)** tại Hà Nội, trong giai đoạn cấu hình **01/01/2021 – 30/09/2026** (múi giờ `Asia/Ho_Chi_Minh`, UTC+7). Nhãn huấn luyện là số đo trạm OpenAQ; đặc trưng gồm lịch, tọa độ, khí tượng và vệ tinh. Kết quả là ước tính hồi cứu của mô hình, không phải số đo tại từng ô hay dự báo ngày tiếp theo.

## Bài toán và trạng thái hiện tại

- **Mục tiêu**: Ước tính phân bố PM2.5 lịch sử trên toàn bộ `3.610` ô lưới 1 km, đặc biệt tại `3.580` ô lưới không có trạm quan trắc (`99,17%`), và cho phép đối chiếu với quan trắc. Xem [schema](docs/schema.md) và [báo cáo mô hình](docs/model_report.md).
- **Quy trình đánh giá chuẩn hóa (3 phương pháp trên `7.290` dòng hợp lệ, `32` trạm, `30` ô lưới)**:
  1. **Spatial GroupKFold (`spatial_groupkfold` — Đánh giá chính)**: `GroupKFold(n_splits=5)` theo `grid_id`. **Baseline 2 (`OpenAQ + Meteo + Satellite`) thắng nhất quán** trên cả metric gộp (`MAE = 11,0451` so với `11,5955` µg/m³, `RMSE = 15,9541` so với `16,7911` µg/m³, `R² = 0,5894` so với `0,5452`), Macro-MAE theo ô (`10,6515` so với `11,1494` µg/m³), `4/5` fold và `17/30` ô lưới.
  2. **Random KFold (`random_kfold` — Mốc tham chiếu)**: `KFold(n_splits=5, shuffle=True, random_state=42)` theo dòng (`MAE = 6,6247` so với `6,7710` µg/m³, `R² = 0,8382` so với `0,8293`), minh họa mức độ lạc quan khi chia ngẫu nhiên theo dòng có rò rỉ không gian – thời gian.
  3. **Temporal Split (`temporal_split` — Đánh giá bổ sung theo thời gian)**: Train trước `2026-01-01` (`6.280` dòng), validation năm `2026` (`1.010` dòng, `6` trạm). Baseline 2 thắng nhẹ trên metric gộp (`MAE = 11,0847` so với `11,1443` µg/m³) và thắng rõ khi có AOD (`MAE = 17,1562` so với `19,5302` µg/m³), trong khi Baseline 1 nhỉnh nhẹ ở nhóm mất ảnh AOD (`MAE = 10,4814` so với `10,6047` µg/m³).
- **Huấn luyện và lưu trữ mô hình cuối cùng**: Cả hai mô hình (`baseline1` và `baseline2`) được huấn luyện lại trên `100%` dữ liệu hợp lệ (`7.290` dòng, `seed = 42`), lưu định dạng chuẩn XGBoost JSON (`outputs/models/{baseline1,baseline2}/model.json`) kèm kiểm chứng nạp lại trên tập mẫu (`25` dòng) mà không cần chạy lại suy luận 7,57 triệu ô-ngày.
- **Metadata cục bộ**: Kết quả thực nghiệm, model và artifact được đăng ký bằng JSON tại `outputs/registry/`. Bản bàn giao chỉ hoàn thành data/model; PostgreSQL, Docker, API và dashboard là việc tiếp theo trong [HANDOVER](docs/HANDOVER.md).
- **Nhận dữ liệu và model**: xem [hướng dẫn bàn giao](docs/DATA_DELIVERY.md). Data/model cần tải qua gói artifact riêng.

---

## 1. Cấu trúc thư mục

```text
pm25_hanoi/
├── archive/                # Lưu trữ các script và kết quả thử nghiệm trung gian cũ (kèm archive/README.md)
├── data/
│   ├── reference/          # Ranh giới hành chính Hà Nội (hanoi_boundary.geojson)
│   ├── raw/                # Dữ liệu gốc từ OpenAQ v3 & Google Earth Engine
│   ├── staging/            # Dữ liệu đã chuẩn hóa kiểu, đơn vị và gắn cờ QC
│   ├── core/               # Star Schema: 3 bảng chiều (dim_*) + 3 bảng sự kiện (fct_*)
│   └── marts/              # Bảng đặc trưng toàn lưới & bảng huấn luyện cấp trạm
├── docs/
│   ├── schema.md           # Đặc tả chi tiết kiến trúc, bảng và cột dữ liệu
│   ├── business_case.md    # Business Case & khung 6 giả thuyết nghiên cứu (H1 - H6)
│   ├── roadmap.md          # Hướng phát triển end-to-end, các hạng mục dự kiến
│   ├── eda_temporal_split.md # EDA phục vụ thiết kế chia tập theo thời gian
│   └── model_report.md     # Báo cáo đánh giá 3 phương pháp & mô hình cuối cùng
├── notebooks/
│   ├── 01_raw_and_initial_eda.ipynb     # EDA ban đầu trên dữ liệu thô & ra quyết định thiết kế/chọn biến
│   └── 02_hypothesis_testing_eda.ipynb  # EDA kiểm định thống kê cho từng giả thuyết (H1 - H4)
├── outputs/
│   ├── evaluation/
│   │   ├── spatial_groupkfold/          # Đánh giá chính: metrics.json, predictions.parquet, fold_assignments.parquet
│   │   ├── random_kfold/                # Mốc tham chiếu: metrics.json, predictions.parquet, fold_assignments.parquet
│   │   └── temporal_split/              # Đánh giá bổ sung 2026: metrics.json, predictions.parquet, split_assignments.parquet
│   ├── models/
│   │   ├── baseline1/                   # model.json, metadata.json, config.yaml, sample_verification_predictions.parquet
│   │   └── baseline2/                   # model.json, metadata.json, config.yaml, sample_verification_predictions.parquet
│   └── registry/                        # Sổ đăng ký thực nghiệm & model (evaluation_runs, fold_metrics, model_registry, artifact_registry)
├── src/
│   ├── common/
│   │   ├── config.py       # Tham số thời gian, không gian, đường dẫn
│   │   ├── storage.py      # Ghi Parquet/JSON/YAML nguyên tử & thực thi SQL DuckDB
│   │   └── gee.py          # Tiện ích tải raster 1 km từ Earth Engine
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
│       ├── train_baselines.py  # Đánh giá 3 phương pháp (Spatial/Random/Temporal) & huấn luyện 2 model cuối cùng
│       └── registry.py         # Quản lý experiment/model/artifact registry (Local JSON, không cần database)
├── tests/unit/
│   ├── test_pipeline.py            # Unit tests kiểm định toàn trình SQL & QC
│   └── test_temporal_evaluation.py # Unit & integration tests cho 3 phương pháp đánh giá, feature contract & model reload
├── requirements.txt
├── pyproject.toml
└── run.py                  # CLI điều phối duy nhất
```

---

## 2. Cài đặt & Cấu hình

```powershell
python -m pip install -r requirements.txt
```

Tạo `.env` khi cần thu thập dữ liệu mới (xem `.env.example`; không commit `.env`):

```ini
OPENAQ_API_KEY=<api_key_openaq_v3>
GEE_PROJECT=<google_cloud_project_id_da_bat_earth_engine>
```

---

## 3. Quy trình vận hành (CLI)

Tất cả thao tác đều chạy qua [`run.py`](run.py):

```powershell
# Bước 1: Sinh lưới chuẩn 1 km (3.610 ô) và trục ngày (01/01/2021 - 30/09/2026 = 2.099 ngày)
python run.py dims

# Bước 2: Thu thập dữ liệu gốc (có cơ chế resume, bỏ qua file đã tải)
python run.py fetch-openaq                 # Metadata + chuỗi giờ PM2.5, PM10, nhiệt độ, độ ẩm
python run.py fetch-meteo --workers 4      # ERA5-Land + ERA5 BLH (69 tháng: 2021-01 -> 2026-09)
python run.py fetch-satellite --workers 4  # S5P (NO2, CO, O3, SO2), MODIS AOD, VIIRS (69 tháng)

# Bước 3: Xây dựng lại toàn bộ Dims -> Staging -> Core Facts -> Feature Marts
python run.py build

# Bước 4: Chạy đánh giá chuẩn hóa theo 3 phương pháp (Spatial GroupKFold, Random KFold, Temporal Split)
python run.py evaluate
# Hoặc chạy riêng từng phương pháp:
python run.py evaluate --method spatial_groupkfold
python run.py evaluate --method random_kfold
python run.py evaluate --method temporal_split

# Bước 5: Huấn luyện và lưu 2 mô hình cuối cùng (Baseline 1 & Baseline 2) trên 100% dữ liệu hợp lệ
python run.py train-final

# Hoặc chạy trọn gói cả đánh giá 3 phương pháp lẫn huấn luyện 2 mô hình cuối cùng:
python run.py train

# Bước 6: Kiểm tra chất lượng mã nguồn (Ruff) và chạy bộ kiểm thử (Pytest)
python run.py lint
python run.py test
```
