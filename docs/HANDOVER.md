# Bàn giao triển khai hệ thống PM2.5 Hà Nội (Data & Models → Serving Application)

Ngày lập: 04/11/2026 · Hợp đồng dữ liệu & API: **v1** · Trạng thái bàn giao: **Đã hoàn thành Data, 2 Model & Toàn bộ Prediction lưới**

Tài liệu này là **hướng dẫn duy nhất** dành cho nhóm tiếp nhận để triển khai toàn bộ hệ thống phục vụ người dùng cuối: **PostgreSQL/PostGIS → Docker Compose → Backend FastAPI → Frontend React Dashboard**.

> [!IMPORTANT]
> **Toàn bộ dữ liệu prediction trên lưới 1 km (15,15 triệu dòng cho 2 mô hình) đã được tính sẵn và đóng gói trong gói bàn giao.**
> Nhóm tiếp nhận **không cần huấn luyện lại (no training)**, **không cần tinh chỉnh (no tuning)** và **không bắt buộc phải chạy inference** trong luồng triển khai thông thường. Công việc chính của nhóm là nạp dữ liệu vào cơ sở dữ liệu và xây dựng ứng dụng serving.

---

## 1. Những gì đã hoàn thành (Dữ liệu thực tế & Mô hình)

### 1.1. Phạm vi bài toán
- **Mục tiêu:** Ước tính hồi cứu (retrospective estimation) nồng độ bụi mịn PM2.5 trung bình ngày trên toàn bộ lưới không gian chuẩn **1 km × 1 km** bao phủ địa bàn thành phố Hà Nội, đặc biệt tại `3.580` ô lưới không có trạm quan trắc (`99,17%`), phục vụ nghiên cứu và giám sát chất lượng không khí lịch sử.
- **Bản chất khoa học:** Đây là bài toán **tái tạo phân bố không gian lịch sử**, **không phải dự báo ngày mai (forecasting)**. Nồng độ PM2.5 được tính theo đơn vị chuẩn `µg/m³`, **tuyệt đối không gọi là chỉ số AQI**.

### 1.2. Pipeline dữ liệu đã hoàn thành
Pipeline dữ liệu chuẩn Lakehouse (Parquet + DuckDB) đã được xây dựng và kiểm định qua Star Schema:
- **Dữ liệu nguồn:**
  - Nhãn quan trắc: Số đo PM2.5 từ OpenAQ v3 (39 trạm, chuẩn hóa múi giờ Hà Nội `Asia/Ho_Chi_Minh`, UTC+7).
  - Khí tượng: Tái phân tích ERA5-Land (nhiệt độ, điểm sương, độ ẩm, áp suất, gió u/v, tốc độ gió, độ ổn định gió) và ERA5 Boundary Layer Height (BLH mean, min) từ Google Earth Engine.
  - Vệ tinh: Cột nồng độ đối lưu khí Sentinel-5P (NO2, CO, O3, SO2), độ dày quang học sol khí MODIS MAIAC AOD 0.47 µm và độ sáng ban đêm VIIRS hàng tháng.
- **Phạm vi không-thời gian thực tế:**
  - **Khoảng thời gian:** Toàn bộ giai đoạn thực sự có trong mart đặc trưng từ **01/01/2021 đến 30/09/2026** (tổng cộng **2.099 ngày** lịch liên tục).
  - **Lưới không gian:** **3.610 ô lưới** chuẩn 1 km × 1 km theo hệ tọa độ phẳng quốc gia VN-2000 UTM Zone 48N (`EPSG:3405`).
  - **Tổng số ô–ngày toàn lưới:** Đúng **7.577.390 dòng** (`3.610 ô × 2.099 ngày`, độ phủ tích Descartes 100%, không khuyết thiếu ngày).
  - **Tập huấn luyện trạm hợp lệ:** 7.290 bản ghi trạm–ngày (32 trạm, 30 ô lưới có trạm, 1.801 ngày có nhãn hợp lệ thỏa mãn điều kiện QC: `is_valid_day = 1 AND pm25_mean IS NOT NULL`).

### 1.3. Hai mô hình máy học cuối cùng đã huấn luyện & lưu trữ
Hai mô hình XGBoost cuối cùng được huấn luyện trên 100% dữ liệu trạm–ngày hợp lệ (7.290 mẫu, seed `42`), lưu định dạng chuẩn XGBoost Native JSON tại `outputs/models/{baseline1,baseline2}/model.json` kèm metadata và config YAML:
- **Baseline 1 (`Baseline_1_OpenAQ_Meteo:v2.0.0-retrospective`):**
  - **Đặc trưng (27 features):** 7 biến lịch & tọa độ phẳng (`year`, `month`, `day_of_week`, `day_of_year`, `is_weekend`, `easting_m`, `northing_m`) + 20 biến khí tượng ERA5/BLH và cờ nhị phân missing (`temp_2m_c`, `dewpoint_2m_c`, `rh_pct`, `precip_mm`, `wind_speed_10m_ms`, `wind_u_10m_ms`, `wind_v_10m_ms`, `wind_persistence`, `wind_dir_10m_deg`, `surface_pressure_hpa`, `blh_mean_m`, `blh_min_m`, và 8 cờ `*_missing`).
- **Baseline 2 (`Baseline_2_OpenAQ_Meteo_Sat:v2.0.0-retrospective`):**
  - **Đặc trưng (34 features):** Toàn bộ 27 biến của Baseline 1 + 7 biến vệ tinh (`no2_trop_mol_m2`, `co_mol_m2`, `o3_mol_m2`, `so2_mol_m2`, `aod_047`, `aod_047_missing`, `viirs_radiance`).
- **Chính sách xử lý missing & hậu xử lý:**
  - Missing-value policy: Giữ nguyên giá trị `NaN` của các biến liên tục để thuật toán XGBoost (cấu hình `tree_method='hist'`) tự học hướng rẽ nhánh tối ưu, kết hợp với các cờ nhị phân `*_missing` (1 = thiếu, 0 = có).
  - Postprocessing policy: Cắt các giá trị dự đoán âm về 0.0 µg/m³ (`y_pred = np.clip(raw_pred, 0.0, None)`).

### 1.4. Kết quả đánh giá chuẩn hóa (3 phương pháp)
1. **Spatial GroupKFold (`spatial_groupkfold` — Đánh giá chính, GroupKFold 5-fold theo `grid_id`):**
   - Đánh giá khả năng dự đoán tại các ô chưa từng có trạm quan trắc.
   - **Baseline 2 thắng nhất quán trên mọi chỉ số:**
     - MAE: **11,0451 µg/m³** (so với 11,5955 µg/m³ của Baseline 1, giảm 4,7%).
     - RMSE: **15,9541 µg/m³** (so với 16,7911 µg/m³ của Baseline 1).
     - R²: **0,5894** (so với 0,5452 của Baseline 1).
     - Macro-MAE theo ô: **10,6515 µg/m³** (so với 11,1494 µg/m³ của Baseline 1).
     - Baseline 2 thắng ở 4/5 fold và 17/30 ô lưới.
2. **Random KFold (`random_kfold` — Benchmark tham khảo, KFold 5-fold ngẫu nhiên theo dòng):**
   - MAE: Baseline 1 = 6,6247 µg/m³, Baseline 2 = 6,7710 µg/m³; R² đạt ~0,83 – 0,84. Minh họa hiện tượng rò rỉ không-thời gian khi chia ngẫu nhiên khiến metric lạc quan quá mức.
3. **Temporal Split (`temporal_split` — Đánh giá bổ sung theo thời gian, Train < 2026, Val 2026):**
   - Baseline 2 thắng nhẹ trên metric gộp (MAE = 11,0847 so với 11,1443 µg/m³) và **thắng vượt trội ở các ngày có dữ liệu vệ tinh AOD** (MAE = 17,1562 so với 19,5302 µg/m³, giảm 12,2%).

### 1.5. Toàn bộ Prediction toàn lưới đã được sinh sẵn
Toàn bộ suy luận trên toàn bộ 7.577.390 dòng của lưới 1 km qua 2.099 ngày cho cả 2 mô hình đã được thực thi hoàn tất và kiểm tra tự động:
- **Baseline 1:** Đã sinh đủ **7.577.390 dòng**, lưu tại `outputs/predictions/baseline1/v2.0.0-retrospective/` qua 69 partition tháng (`2021-01.parquet` đến `2026-09.parquet`).
- **Baseline 2:** Đã sinh đủ **7.577.390 dòng**, lưu tại `outputs/predictions/baseline2/v2.0.0-retrospective/` qua 69 partition tháng (`2021-01.parquet` đến `2026-09.parquet`).
- **Tổng cộng:** **15.154.780 bản ghi prediction** sẵn sàng nạp trực tiếp vào PostgreSQL.
- **Kết quả kiểm tra dữ liệu 100% đạt chuẩn:**
  - Khóa `(grid_id, date, model_id)` duy nhất tuyệt đối, 0 trùng lặp.
  - Không có giá trị `pm25_pred` nào bị null, NaN hoặc Infinity.
  - Tất cả giá trị `pm25_pred` đều không âm (`>= 0.0 µg/m³`).
  - Khớp 100% tập khóa giữa mart đầu vào và prediction (không thiếu dòng nào, không thừa dòng nào).
  - 100% `grid_id` tồn tại trong bảng geometry `dim_grid_1km`.
  - Mẫu kiểm chứng đối chiếu trực tiếp giữa file parquet đã lưu và model chạy trong RAM có sai lệch lớn nhất bằng **0,00000000 µg/m³**.

---

## 2. Phần nhóm tiếp nhận phải làm

Nhóm tiếp nhận chịu trách nhiệm triển khai hệ thống serving hoàn chỉnh bao gồm các thành phần sau:

```text
Gói bàn giao (tar.gz)
      │
      ├── Geometry (EPSG:4326/3405) ───┐
      ├── Station & Observations ──────┼──► PostgreSQL 16 / PostGIS 3.4
      ├── Model Metadata ──────────────┤      ▲
      └── Predictions (15,15M dòng) ───┘      │
                                               ▼
                                      FastAPI Backend
                                      (Docker Container)
                                               ▲
                                               │ HTTP / REST API
                                               ▼
                                      React Dashboard UI
                                      (Bản đồ tương tác, Lịch sử ô, Trạm)
```

1. **PostgreSQL / PostGIS & Migrations:**
   - Dựng PostgreSQL 16+ có tiện ích mở rộng PostGIS 3.4+.
   - Viết scripts migration tạo bảng: `grids`, `stations`, `station_daily_observations`, `model_metadata`, `grid_daily_predictions`.
   - Viết script import dữ liệu từ các file Parquet trong gói bàn giao vào database bằng kỹ thuật bulk insert / `COPY` / DuckDB PostgreSQL scanner. Đảm bảo tính **idempotent** (chạy import 2 lần không làm tăng số dòng, không tạo bản ghi trùng lặp).
2. **Docker & Orchestration:**
   - Viết `Dockerfile` cho Backend API và `Dockerfile` cho Frontend React.
   - Viết `docker-compose.yml` liên kết 3 services:
     - `db`: PostgreSQL/PostGIS (có named volume để duy trì dữ liệu khi khởi động lại).
     - `api`: FastAPI (phục vụ dữ liệu qua REST endpoints).
     - `frontend`: React/Vite/Nginx (giao diện dashboard).
   - Đảm bảo dữ liệu nguyên vẹn sau khi chạy `docker compose restart`.
3. **Backend API (FastAPI):**
   - Hiện thực đầy đủ 7 endpoints theo đúng Hợp đồng API v1 (đặc tả chi tiết tại Mục 5).
   - Truy vấn tham số hóa (tránh SQL injection), tối ưu hóa index không gian và index thời gian.
   - Xử lý các trường hợp ngoại lệ, mã lỗi HTTP (404, 422, 503) và envelope chuẩn.
4. **Frontend Dashboard (React):**
   - Tích hợp thư viện bản đồ (Leaflet, MapLibre GL hoặc Mapbox).
   - Hiển thị lưới ô 1 km tô màu theo dải nồng độ PM2.5 trung bình ngày (thang màu cố định, đơn vị `µg/m³`).
   - Bộ chọn ngày và bộ chọn mô hình (Baseline 1 hoặc Baseline 2, mặc định chọn Baseline 2).
   - Tương tác click vào ô lưới: Mở panel hoặc popup hiển thị thông tin ô và biểu đồ chuỗi thời gian lịch sử (`/api/grids/{grid_id}/history`).
   - Lớp trạm quan trắc (toggle bật/tắt): Hiển thị vị trí trạm thực tế, phân biệt rõ ràng giá trị đo tại trạm (`pm25_observed`) với giá trị ước tính (`pm25_pred`).
5. **Kiểm thử & Bàn giao vận hành:**
   - Kiểm thử tự động API và kiểm thử giao diện.
   - Thử nghiệm sao lưu và phục hồi database (`pg_dump` và `pg_restore`).
   - Viết tài liệu hướng dẫn khởi động một chạm cho người dùng.

---

## 3. Cách nhận dữ liệu & Xác minh gói bàn giao

### 3.1. Thông tin kho lưu trữ mã nguồn
- **Repository:** `https://github.com/NguyenThinh06/hanoi_pm25.git`
- **Nhánh triển khai:** `handover/end-to-end`

### 3.2. Thông tin gói dữ liệu bàn giao mới
Gói bàn giao duy nhất đã được chuẩn bị sẵn tại thư mục `handover_bundles/` trên máy bàn giao:

| Thuộc tính | Giá trị chi tiết |
|---|---|
| **Tên file gói** | `pm25-handover-2026-11-04.tar.gz` |
| **Dung lượng nén** | **86,41 MB** (86.412.809 bytes) |
| **Mã băm SHA-256** | `0013bae87171042c3822347ff0fc4509ea9da2d95108b41296adc0069dc2b8f0` |
| **Số lượng file trong gói** | **150 file** (138 parquet predictions + 2 manifests + 3 geometry + 2 stations + 5 metadata) |
| **Phạm vi thời gian** | **01/01/2021 đến 30/09/2026** (2.099 ngày) |
| **Số lượng ô lưới** | **3.610 ô** (EPSG:3405 và EPSG:4326) |
| **Số bản ghi Baseline 1** | **7.577.390 dòng** |
| **Số bản ghi Baseline 2** | **7.577.390 dòng** |
| **Tổng số dòng prediction**| **15.154.780 dòng** |
| **Link tải Google Drive** | **`https://drive.google.com/drive/folders/10grr4EY_Pg5YdYtkzR3M44na6NljR5FN?usp=drive_link`** |

> [!NOTE]
> Gói bàn giao đi kèm file băm `pm25-handover-2026-11-04.tar.gz.sha256` và manifest chi tiết `pm25-handover-2026-11-04.tar.gz.manifest.json`.

### 3.3. Hướng dẫn tải, xác minh và giải nén (PowerShell)

```powershell
# Bước 1: Clone đúng nhánh triển khai
git clone --branch handover/end-to-end https://github.com/NguyenThinh06/hanoi_pm25.git
cd hanoi_pm25

# Bước 2: Khởi tạo môi trường ảo Python
$env:PYTHONUTF8 = "1"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Bước 3: Tải gói bàn giao từ Google Drive về thư mục (ví dụ Downloads)
# Sau đó xác minh mã băm SHA-256
Get-FileHash "$HOME\Downloads\pm25-handover-2026-11-04.tar.gz" -Algorithm SHA256

# Bước 4: Kiểm tra toàn diện 150 file và cấu trúc archive bằng CLI có sẵn
.\.venv\Scripts\python.exe scripts/package_handover.py --verify "$HOME\Downloads\pm25-handover-2026-11-04.tar.gz"

# Bước 5: Giải nén gói bàn giao vào thư mục gốc dự án
tar -xzf "$HOME\Downloads\pm25-handover-2026-11-04.tar.gz"
```

Sau khi giải nén, các thư mục sau sẽ xuất hiện sẵn sàng cho việc nạp database:
- `predictions/`: Chứa toàn bộ 138 partition Parquet và manifest của 2 model.
- `geometry/`: Chứa file hình học ô lưới chuẩn `dim_grid_1km_epsg3405.parquet`, `dim_grid_1km_epsg4326.parquet` và `dim_grid_1km_epsg4326.geojson`.
- `stations/`: Chứa danh mục trạm và bảng quan trắc ngày kèm cờ QC.
- `metadata/`: Chứa thông tin cấu hình, feature list và tóm tắt chỉ số mô hình.

---

## 4. Đặc tả Schema dữ liệu bàn giao

Tất cả các file trao đổi đều ở định dạng chuẩn Parquet (nén Zstandard), ép kiểu chặt chẽ.

### 4.1. Bảng Dự đoán ô lưới (`grid_daily_predictions`)
Mỗi dòng là một ô × một ngày × một mô hình phiên bản cụ thể.

| Tên trường | Kiểu dữ liệu Parquet | Kiểu dữ liệu PostgreSQL | Cho phép NULL | Mô tả & Quy ước |
|---|---|---|---|---|
| `grid_id` | string / utf8 | text / varchar(32) | **Không** | Mã ô lưới chuẩn (ví dụ: `grid_584000_2324000`). Khóa ngoại tham chiếu `grids.grid_id`. |
| `date` | date32 | date | **Không** | Ngày lịch Hà Nội (`YYYY-MM-DD`). Không tự dịch sang ngày UTC khác. |
| `model_id` | string / utf8 | text / varchar(64) | **Không** | Định danh đầy đủ của model (ví dụ: `Baseline_2_OpenAQ_Meteo_Sat:v2.0.0-retrospective`). |
| `model_version` | string / utf8 | text / varchar(32) | **Không** | Phiên bản model (`v2.0.0-retrospective`). |
| `pm25_pred` | float64 | double precision | **Không** | Nồng độ PM2.5 ước tính hồi cứu (µg/m³), không âm, không làm tròn khi lưu trong DB. |
| `run_id` | string / utf8 | text / varchar(64) | **Không** | Mã lô suy luận phục vụ truy vết dữ liệu. |

- **Khóa chính duy nhất (Primary Key):** `(grid_id, date, model_id)`.
  - Tuyệt đối không thêm `run_id` vào khóa chính để tránh nhân bản dữ liệu khi nạp lại.
  - Tuyệt đối không dùng riêng `model_version` làm định danh mô hình vì hai mô hình có thể có cùng chuỗi phiên bản.
- **Ánh xạ Model Alias sang Model ID đầy đủ:**
  - Alias `baseline1` ➔ `Baseline_1_OpenAQ_Meteo:v2.0.0-retrospective`
  - Alias `baseline2` ➔ `Baseline_2_OpenAQ_Meteo_Sat:v2.0.0-retrospective`

### 4.2. Bảng Geometry ô lưới (`grids`)
Lưu trữ thông tin hình học không gian của 3.610 ô lưới chuẩn 1 km × 1 km.

| Tên trường | Kiểu dữ liệu Parquet | Kiểu dữ liệu PostgreSQL/PostGIS | Cho phép NULL | Mô tả |
|---|---|---|---|---|
| `grid_id` | string / utf8 | text / varchar(32) | **Không** | Mã định danh ô lưới (Khóa chính PK). |
| `easting_m` | int64 | bigint | **Không** | Tọa độ X tâm ô lưới (m, VN-2000 UTM Zone 48N). |
| `northing_m` | int64 | bigint | **Không** | Tọa độ Y tâm ô lưới (m, VN-2000 UTM Zone 48N). |
| `centroid_lon` | float64 | double precision | **Không** | Kinh độ tâm ô lưới (độ, WGS84). |
| `centroid_lat` | float64 | double precision | **Không** | Vĩ độ tâm ô lưới (độ, WGS84). |
| `is_boundary` | boolean | boolean | **Không** | Cờ đánh dấu ô lưới nằm ở vùng biên hành chính Hà Nội. |
| `geom_3405` | binary / geometry | geometry(Polygon, 3405) | **Không** | Polygon ô lưới hệ VN-2000 UTM Zone 48N (`EPSG:3405`). |
| `geom_4326` | binary / geometry | geometry(Polygon, 4326) | **Không** | Polygon ô lưới hệ tọa độ WGS84 (`EPSG:4326`) dùng cho bản đồ/GeoJSON. |

### 4.3. Bảng Danh mục trạm quan trắc (`stations`)
Lưu danh mục 39 trạm quan trắc trên địa bàn Hà Nội từ OpenAQ.

| Tên trường | Kiểu dữ liệu Parquet | Kiểu dữ liệu PostgreSQL | Cho phép NULL | Mô tả |
|---|---|---|---|---|
| `station_id` | string / utf8 | text / varchar(64) | **Không** | Mã định danh trạm (Khóa chính PK). |
| `station_name` | string / utf8 | text | **Không** | Tên trạm hiển thị. |
| `lon` | float64 | double precision | **Không** | Kinh độ trạm (độ, WGS84). |
| `lat` | float64 | double precision | **Không** | Vĩ độ trạm (độ, WGS84). |
| `grid_id` | string / utf8 | text / varchar(32) | **Có** | Ô lưới 1 km chứa trạm (Khóa ngoại tham chiếu `grids.grid_id`). |
| `provider` | string / utf8 | text | **Có** | Đơn vị cung cấp dữ liệu (ví dụ: `AirNow`, `PAM Air`). |
| `sensor_tier` | string / utf8 | text | **Có** | Phân cấp cảm biến (`reference_grade`, `low_cost`). |
| `is_boundary` | boolean | boolean | **Không** | Cờ vị trí biên. |

### 4.4. Bảng Quan trắc trạm theo ngày (`station_daily_observations`)
Lưu 9.390 chuỗi quan trắc ngày tại trạm phục vụ đối chiếu trực quan với mô hình.

| Tên trường | Kiểu dữ liệu Parquet | Kiểu dữ liệu PostgreSQL | Cho phép NULL | Mô tả & Quy tắc QC |
|---|---|---|---|---|
| `station_id` | string / utf8 | text / varchar(64) | **Không** | Mã trạm (FK `stations.station_id`). |
| `date` | date32 | date | **Không** | Ngày lịch Hà Nội (`YYYY-MM-DD`). |
| `station_name` | string / utf8 | text | **Không** | Tên hiển thị của trạm. |
| `grid_id` | string / utf8 | text / varchar(32) | **Có** | Ô lưới chứa trạm (nếu có). |
| `pm25_observed`| float64 | double precision | **Có** | Nồng độ PM2.5 trung bình ngày đo tại trạm (µg/m³). **NULL nếu ngày đó trạm mất tín hiệu hoặc không có số đo. TUYỆT ĐỐI KHÔNG GÁN THÀNH 0.** |
| `pm25_valid_hours` | int16 | smallint | **Có** | Số giờ hợp lệ có số đo trong ngày (0 – 24). |
| `is_valid_day` | boolean | boolean | **Không** | Cờ chuẩn QC: `true` nếu ngày có ít nhất 18 giờ hợp lệ (`>= 75%`). Nếu `false`, UI phải đánh dấu cảnh báo dữ liệu không đạt chuẩn. |
| `pm25_std` | float64 | double precision | **Có** | Độ lệch chuẩn trong ngày của số đo PM2.5. |
| `pm25_min` | float64 | double precision | **Có** | Giá trị nhỏ nhất trong ngày. |
| `pm25_max` | float64 | double precision | **Có** | Giá trị lớn nhất trong ngày. |

- **Khóa chính duy nhất (Primary Key):** `(station_id, date)`.

---

## 5. Hợp đồng API v1 (API Contract)

### 5.1. Quy ước chung
- **Prefix:** `/api` cho các tài nguyên nghiệp vụ; endpoint `/health` nằm ngoài prefix.
- **Encoding & Kiểu dữ liệu:** JSON UTF-8. Định dạng ngày chuẩn ISO 8601 `YYYY-MM-DD`. Không xuất NaN, Infinity; trường khuyết dùng JSON `null`.
- **Query Parameter:** Mã `model_id` được frontend lấy động từ `/api/models`, URL-encoded khi gọi API (ví dụ: `Baseline_2_OpenAQ_Meteo_Sat%3Av2.0.0-retrospective`).
- **Envelope chuẩn:** Response danh sách có cấu trúc chuẩn `{ "count": <int>, "data": [...] }`.
  - Trong đó `count` là số lượng bản ghi trả về trong mảng `data`, không phải tổng số dòng của toàn bộ database.
  - Ngoại lệ: `/api/grids` trả về cấu trúc chuẩn `FeatureCollection` của GeoJSON để cắm trực tiếp vào Leaflet/MapLibre.
- **Xử lý rỗng:** Trường hợp request hợp lệ nhưng không có dữ liệu: trả HTTP 200 với `{ "count": 0, "data": [] }`.
- **Xử lý lỗi:** Định dạng lỗi thống nhất:
  ```json
  {
    "error": {
      "code": "ERROR_CODE_STRING",
      "message": "Thông điệp mô tả chi tiết bằng tiếng Việt."
    }
  }
  ```
  - `404 Not Found`: Khi `model_id` hoặc `grid_id` không tồn tại trong hệ thống (`MODEL_NOT_FOUND`, `GRID_NOT_FOUND`).
  - `422 Unprocessable Entity`: Khi tham số đầu vào sai định dạng ngày, khoảng thời gian vượt quá 366 ngày (`INVALID_REQUEST`).
  - `503 Service Unavailable`: Khi kết nối cơ sở dữ liệu tạm thời chưa sẵn sàng (`DATABASE_UNAVAILABLE`).

---

### 5.2. Chi tiết 7 Endpoint REST

#### 1. Kiểm tra trạng thái hệ thống
`GET /health`

- **Mục đích:** Healthcheck cho Docker Compose và load balancer.
- **Query parameters:** Không.
- **Response thành công (HTTP 200):**
  ```json
  {
    "status": "ok",
    "database": "ready"
  }
  ```
- **Response lỗi DB chưa sẵn sàng (HTTP 503):**
  ```json
  {
    "error": {
      "code": "DATABASE_UNAVAILABLE",
      "message": "Cơ sở dữ liệu tạm thời chưa sẵn sàng."
    }
  }
  ```

---

#### 2. Danh sách mô hình khả dụng
`GET /api/models`

- **Mục đích:** Lấy danh sách các mô hình đã nạp dữ liệu hoàn tất để hiển thị lên dropdown của giao diện.
- **Query parameters:** Không.
- **Response thành công (HTTP 200):**
  ```json
  {
    "count": 2,
    "data": [
      {
        "model_id": "Baseline_2_OpenAQ_Meteo_Sat:v2.0.0-retrospective",
        "model_version": "v2.0.0-retrospective",
        "label": "Baseline 2 — Khí tượng + Vệ tinh (Khuyến nghị)",
        "is_default": true,
        "feature_count": 34
      },
      {
        "model_id": "Baseline_1_OpenAQ_Meteo:v2.0.0-retrospective",
        "model_version": "v2.0.0-retrospective",
        "label": "Baseline 1 — Khí tượng",
        "is_default": false,
        "feature_count": 27
      }
    ]
  }
  ```

---

#### 3. Danh sách ngày có dữ liệu của mô hình
`GET /api/dates?model_id={model_id}`

- **Mục đích:** Lấy toàn bộ danh sách ngày có dữ liệu của mô hình được chọn để điều khiển thanh chọn ngày (Date Picker / Slider).
- **Query parameters:**
  - `model_id` (bắt buộc, string URL-encoded).
- **Quy tắc:** Trả về mảng ngày duy nhất, sắp xếp tăng dần theo thời gian.
- **Response thành công (HTTP 200 - Trích dẫn minh họa):**
  ```json
  {
    "model_id": "Baseline_2_OpenAQ_Meteo_Sat:v2.0.0-retrospective",
    "count": 2099,
    "min_date": "2021-01-01",
    "max_date": "2026-09-30",
    "data": [
      "2021-01-01",
      "2021-01-02",
      "..."
    ]
  }
  ```
- **Response rỗng (HTTP 200 - nếu model chưa có dữ liệu):**
  ```json
  {
    "model_id": "Baseline_2_OpenAQ_Meteo_Sat:v2.0.0-retrospective",
    "count": 0,
    "min_date": null,
    "max_date": null,
    "data": []
  }
  ```

---

#### 4. Toàn bộ hình học lưới ô không gian
`GET /api/grids`

- **Mục đích:** Trả về GeoJSON FeatureCollection của 3.610 ô lưới để frontend tải và cache 1 lần duy nhất trên client.
- **Query parameters:** Không.
- **Quy tắc:** Tọa độ WGS84 (`EPSG:4326`), thứ tự `[longitude, latitude]`.
- **Response thành công (HTTP 200 - GeoJSON chuẩn):**
  ```json
  {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "id": "grid_584000_2324000",
        "properties": {
          "grid_id": "grid_584000_2324000",
          "centroid_lon": 105.8085,
          "centroid_lat": 21.0152,
          "is_boundary": false
        },
        "geometry": {
          "type": "Polygon",
          "coordinates": [
            [
              [105.8037, 21.0107],
              [105.8133, 21.0107],
              [105.8133, 21.0197],
              [105.8037, 21.0197],
              [105.8037, 21.0107]
            ]
          ]
        }
      }
    ]
  }
  ```

---

#### 5. Bản đồ nồng độ ô lưới theo ngày và mô hình
`GET /api/map?date={date}&model_id={model_id}`

- **Mục đích:** Trả về giá trị nồng độ PM2.5 ước tính của tất cả các ô trong ngày đã chọn để tô màu bản đồ (Choropleth map).
- **Query parameters:**
  - `date` (bắt buộc, định dạng `YYYY-MM-DD`).
  - `model_id` (bắt buộc, string URL-encoded).
- **Quy tắc:** Trả tối đa một bản ghi cho mỗi ô, sắp xếp theo `grid_id`. Frontend join `grid_id` với geometry đã tải ở `/api/grids`.
- **Response thành công (HTTP 200 - Trích dẫn minh họa):**
  ```json
  {
    "date": "2024-01-15",
    "model_id": "Baseline_2_OpenAQ_Meteo_Sat:v2.0.0-retrospective",
    "unit": "µg/m³",
    "count": 3610,
    "data": [
      {
        "grid_id": "grid_584000_2324000",
        "pm25_pred": 35.72
      },
      {
        "grid_id": "grid_585000_2324000",
        "pm25_pred": 29.41
      }
    ]
  }
  ```

---

#### 6. Lịch sử chuỗi thời gian của một ô lưới
`GET /api/grids/{grid_id}/history?model_id={model_id}&start={start_date}&end={end_date}`

- **Mục đích:** Phục vụ biểu đồ chuỗi thời gian (Time-series chart) khi người dùng bấm vào một ô lưới cụ thể.
- **Path parameter:** `grid_id` (bắt buộc, mã ô lưới).
- **Query parameters:**
  - `model_id` (bắt buộc, string URL-encoded).
  - `start` (bắt buộc, ngày bắt đầu `YYYY-MM-DD`).
  - `end` (bắt buộc, ngày kết thúc `YYYY-MM-DD`).
- **Quy tắc:**
  - Khoảng ngày bao gồm cả hai đầu (`start <= date <= end`).
  - Giới hạn tối đa **366 ngày** cho mỗi request ở phiên bản v1 (vượt quá trả HTTP 422).
  - Sắp xếp tăng dần theo `date`.
- **Response thành công (HTTP 200 - Trích dẫn minh họa):**
  ```json
  {
    "grid_id": "grid_584000_2324000",
    "model_id": "Baseline_2_OpenAQ_Meteo_Sat:v2.0.0-retrospective",
    "start": "2024-01-01",
    "end": "2024-01-03",
    "unit": "µg/m³",
    "count": 3,
    "data": [
      { "date": "2024-01-01", "pm25_pred": 42.15 },
      { "date": "2024-01-02", "pm25_pred": 38.60 },
      { "date": "2024-01-03", "pm25_pred": 31.25 }
    ]
  }
  ```

---

#### 7. Danh sách trạm và số đo quan trắc theo ngày
`GET /api/stations?date={date}`

- **Mục đích:** Lấy thông tin tọa độ và số đo thực tế tại trạm trong ngày để hiển thị lớp điểm quan trắc đè lên bản đồ lưới.
- **Query parameters:**
  - `date` (bắt buộc, định dạng `YYYY-MM-DD`).
- **Quy tắc:**
  - Trả về danh sách trạm quan trắc có tọa độ thuộc phạm vi Hà Nội, kèm thông tin đo của ngày đó.
  - Nếu trạm không có số đo trong ngày: `has_observation: false`, `pm25_observed: null`, `is_valid_day: false`.
  - Nếu trạm có số đo nhưng số giờ hợp lệ < 18 giờ: `has_observation: true`, `is_valid_day: false`. UI hiển thị ký hiệu cảnh báo số đo không đạt chuẩn thống kê ngày.
- **Response thành công (HTTP 200 - Trích dẫn minh họa):**
  ```json
  {
    "date": "2024-01-15",
    "unit": "µg/m³",
    "count": 2,
    "data": [
      {
        "station_id": "openaq_2161290",
        "station_name": "United States Embassy Hanoi",
        "grid_id": "grid_584000_2324000",
        "longitude": 105.8228,
        "latitude": 21.0215,
        "pm25_observed": 33.10,
        "pm25_valid_hours": 24,
        "is_valid_day": true,
        "has_observation": true
      },
      {
        "station_id": "openaq_example_missing",
        "station_name": "Trạm ví dụ mất tín hiệu",
        "grid_id": "grid_585000_2324000",
        "longitude": 105.8300,
        "latitude": 21.0300,
        "pm25_observed": null,
        "pm25_valid_hours": 0,
        "is_valid_day": false,
        "has_observation": false
      }
    ]
  }
  ```

---

## 6. Phân công công việc, thứ tự triển khai & tiêu chí nghiệm thu

### 6.1. Bảng phân công chi tiết (Điền tên trước khi triển khai)

| Gói công việc | Trách nhiệm chính | Nhiệm vụ cụ thể | Đầu ra bàn giao |
|---|---|---|---|
| **Gói 1 — Database & Docker** | *Điền tên* | PostgreSQL 16/PostGIS, migration script, script import Parquet vào DB, Docker Compose cho DB | File migration, script import idempotent, container DB khởi động có dữ liệu |
| **Gói 2 — Backend API** | *Điền tên* | FastAPI, hiện thực 7 endpoint REST chuẩn hợp đồng v1, connection pool, xử lý lỗi | Mã nguồn API, OpenAPI Swagger docs, Unit/Integration tests API |
| **Gói 3 — Frontend Dashboard** | *Điền tên* | React/Vite/Tailwind, Leaflet/MapLibre, dropdown Model/Date, Popup lịch sử ô, lớp trạm | Mã nguồn UI, build production, kết nối API mượt mà |
| **Gói 4 — Tích hợp & Vận hành** | *Điền tên* | Ghép nối Docker Compose 3 dịch vụ, kiểm thử end-to-end, thử backup/restore, viết tài liệu | Docker Compose chạy 1 lệnh, báo cáo đối soát 3 điểm |

### 6.2. Thứ tự triển khai và tiêu chí nghiệm thu

#### Giai đoạn 1: Triển khai luồng nhỏ (Smoke Test trên 1 tháng dữ liệu)
1. Gói 1 giải nén gói bàn giao, nạp `dim_grid_1km_epsg4326.parquet`, `dim_station.parquet` và partition `2024-01.parquet` của 2 model vào database. Chạy script import lần 2 để kiểm chứng không bị trùng bản ghi.
2. Gói 2 dựng FastAPI, kết nối database, gọi thử 7 endpoints và xác nhận response trả về đúng format JSON hợp đồng.
3. Gói 3 dựng giao diện React, kết nối API local, hiển thị bản đồ ngày `2024-01-15`, đổi qua lại giữa Baseline 1 và Baseline 2.
4. **Đối soát 3 điểm bắt buộc:** Chọn 3 cặp ô–ngày bất kỳ, so sánh giá trị số hiển thị:
   `File Parquet nguồn` ➔ `Database PostgreSQL` ➔ `FastAPI Response` ➔ `Giao diện React`. Sai lệch phải bằng 0.

#### Giai đoạn 2: Nạp toàn bộ dữ liệu & Vận hành chính thức
1. Nạp đủ 138 partition Parquet của 2 model (15,15 triệu dòng prediction) vào PostgreSQL.
2. Kiểm tra chỉ mục (Index) trên các cột `(grid_id, date, model_id)` và `(date, model_id)`. Truy vấn `/api/map` cho toàn bộ 3.610 ô trong 1 ngày phải phản hồi dưới **200ms**.
3. Thử nghiệm khởi động lại: Chạy `docker compose restart`, xác nhận toàn bộ dữ liệu vẫn còn nguyên vẹn.
4. Thử nghiệm sao lưu & phục hồi: Chạy `pg_dump` và phục hồi thử trên database phụ.

---

## 7. Các hạn chế và nguyên tắc khoa học bắt buộc

1. **Ước tính hồi cứu (Retrospective Estimation), không phải dự báo (Forecasting):**
   - Mô hình sử dụng các biến khí tượng ERA5 và vệ tinh được đo trong cùng ngày (và VIIRS theo tháng). Không thể dùng để dự báo nồng độ PM2.5 ngày mai khi chưa có các đặc trưng khí tượng/vệ tinh của ngày mai.
2. **Không gọi PM2.5 là chỉ số AQI:**
   - Đơn vị đo và hiển thị là nồng độ khối lượng PM2.5 tính theo microgram trên mét khối (`µg/m³`). AQI là chỉ số không thứ nguyên quy đổi theo công thức từng quốc gia.
3. **Không coi chênh lệch giữa 2 model là khoảng bất định (Uncertainty Interval):**
   - Chênh lệch giữa Baseline 1 và Baseline 2 phản ánh tác động của việc bổ sung dữ liệu vệ tinh, không phải là khoảng tin cậy thống kê (confidence interval).
4. **Phân biệt rõ ràng quan trắc trạm và ước tính ô lưới:**
   - Số đo trạm là giá trị thực tế đo tại một điểm sensor cụ thể. Giá trị ô lưới là ước tính trung bình diện tích 1 km × 1 km từ mô hình máy học. Giao diện phải dán nhãn phân biệt minh bạch.
5. **Prediction từ mô hình full-data không dùng để báo cáo validation:**
   - Kết quả prediction toàn lưới được sinh từ mô hình huấn luyện trên 100% dữ liệu (7.290 dòng) để có độ phủ tốt nhất. Tuyệt đối không dùng sai số khớp (train fit) của mô hình này để công bố thay cho kết quả Spatial GroupKFold đã báo cáo.

---

## 8. Mẫu báo cáo hoàn thành nhiệm vụ thành viên

Mỗi thành viên khi gửi Pull Request hoặc hoàn tất hạng mục phải sao chép và điền đầy đủ mẫu báo cáo sau:

```markdown
### Báo cáo hoàn thành nhiệm vụ
- **Gói công việc / Người thực hiện:** [Ví dụ: Gói 2 - Backend FastAPI / Nguyễn Văn A]
- **Commit / PR:** [Link PR hoặc mã commit]

#### 1. Đã triển khai
- [Mô tả chi tiết những việc đã làm]

#### 2. Danh sách file tạo mới / chỉnh sửa
- Tạo mới: `path/to/file`
- Chỉnh sửa: `path/to/file`

#### 3. Cách chạy và kiểm thử
```powershell
# Lệnh chạy dịch vụ
...
# Lệnh chạy kiểm thử
...
```

#### 4. Bằng chứng kiểm thử thực tế
- Kết quả test: [Ví dụ: 15 tests passed in 2.3s]
- Ảnh chụp màn hình hoặc log output của dịch vụ chạy dữ liệu thật.

#### 5. Vấn đề còn vướng / Lưu ý cho người tiếp theo
- [Ghi rõ nếu có điểm nghẽn hoặc cần thành viên khác phối hợp]
```

---

## 9. Phụ lục lệnh vận hành tái tạo (Khi cần chạy lại)

Các lệnh này được duy trì trong kho mã nguồn phục vụ tái lập quy trình khi có dữ liệu mới:

```powershell
# 1. Chạy lại suy luận độc lập toàn bộ lưới (không train lại)
python run.py predict --model both

# 2. Hoặc chạy suy luận cho một khoảng ngày tùy chọn
python run.py predict --model baseline2 --start-date 2024-01-01 --end-date 2024-03-31

# 3. Kiểm tra tính toàn vẹn 100% của kết quả prediction đã sinh
python scripts/verify_predictions.py

# 4. Đóng gói lại dữ liệu bàn giao mới
python scripts/package_handover.py --build --replace-old

# 5. Xác minh gói bàn giao mà không cần giải nén
python scripts/package_handover.py --verify "handover_bundles/pm25-handover-2026-11-04.tar.gz"

# 6. Kiểm tra chuẩn mã nguồn và chạy toàn bộ unit tests
python run.py lint
python run.py test
```
