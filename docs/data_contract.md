# HỢP ĐỒNG DỮ LIỆU TỔNG THỂ (DATA CONTRACT SPECIFICATION V3.0)
## DỰ ÁN HANOI_PM25: XÂY DỰNG SPATIO-TEMPORAL DATA LAKEHOUSE (2021–2025)

**Cơ quan quản trị:** Ban Kiến trúc Dữ liệu & Đảm bảo Chất lượng (Data Architecture & Governance Board)  
**Tác giả chính:** Principal Data Engineer, Data Architect & Data Governance Lead  
**Đồng thẩm định:** 
- `ngthinh06` — Data Architect & Spatial Lead (TV1)
- `hunganh` — Ground Truth & Quality Owner (TV2)
- `minh` — Atmospheric & Earth Observation Engineer (TV3)  
**Phiên bản Contract:** `v3.0.0` (Production Baseline)  
**Ngày hiệu lực:** 2026-10-24  
**Trạng thái pháp lý:** **RATIFIED & FORMALLY BINDING (BẮT BUỘC THỰC THI TOÀN NHÓM)**  
**Phạm vi áp dụng:** Toàn bộ dữ liệu từ tầng Raw Ingestion, Staging, Core Star Schema, đến Analytics/Feature Marts và Metadata Manifests.

---

## 1. MỤC ĐÍCH, PHẠM VI & NGUYÊN TẮC BẤT BIẾN CỦA HỢP ĐỒNG (CORE PILLARS)

### 1.1. Mục đích của Data Contract
Hợp đồng dữ liệu này (Data Contract) đóng vai trò là **văn kiện cam kết kỹ thuật tối cao** giữa các Kỹ sư sản xuất dữ liệu (Data Producers) và các Kỹ sư tiêu thụ dữ liệu (Data Consumers) trong dự án HANOI_PM25. Văn kiện này định nghĩa tường minh, chính xác ở cấp độ từng cột về cấu trúc lược đồ (Schema), kiểu dữ liệu (Data Types), đơn vị đo (Units), miền giá trị hợp lệ (Physical Constraints), hạt dữ liệu (Grain), ràng buộc khóa (Primary/Foreign Keys), quy tắc kiểm định chất lượng (Data Quality SLA), cơ chế xử lý bất thường và quy trình quản trị thay đổi có tính chất phá vỡ (Breaking Changes).

### 1.2. Phạm vi Dữ liệu & Ranh giới Không gian - Thời gian
1. **Không gian địa lý (Spatial Extent):** 
   - Lãnh thổ toàn thành phố Hà Nội được mô hình hóa thành mạng lưới ô vuông đều $1\text{ km} \times 1\text{ km}$ cắt theo ranh giới chính thức `data/reference/hanoi_boundary.geojson`.
   - Hệ quy chiếu phẳng quốc gia chuẩn hóa: **VN-2000 / UTM Zone 48N (`EPSG:3405`)**. Tọa độ metric Easting (X) và Northing (Y) là cơ sở duy nhất cho các phép đo khoảng cách, diện tích và hàm bán phương sai Semivariogram.
   - Số lượng ô lưới $N_{\text{GRID}}$ được tính toán động và đóng băng bất biến trong file `data/manifests/grid_manifest.json` (giá trị ước lượng sơ bộ ban đầu $\approx 3,360\text{ ô}$).
2. **Thời gian lịch sử (Temporal Horizon):**
   - Đúng **5 năm lịch liên tục**: Từ `2021-01-01 00:00:00` đến hết `2025-12-31 23:59:59` theo giờ địa phương Hà Nội (`Asia/Ho_Chi_Minh`, `UTC+7`).
   - Tổng số ngày lịch: **$N_{\text{DAYS}} = 1,826\text{ ngày}$** (bao gồm 365 ngày của các năm 2021, 2022, 2023, 2025 và 366 ngày của năm nhuận 2024 có ngày `2024-02-29`). Bản ghi ngoại lệ `date_id = -1` không tính vào $N_{\text{DAYS}}$.
3. **Quy mô Khung xương Spine Kỳ vọng ($|S|$):**
   $$|S| = N_{\text{GRID}} \times N_{\text{DAYS}} = N_{\text{GRID}} \times 1,826\text{ dòng}$$
   (Mọi bảng Fact ô lưới và bảng Marts bắt buộc phải có số dòng bằng chính xác $100\%$ quy mô Spine $|S|$).

### 1.3. Bốn Nguyên tắc Bất biến Không Khoan nhượng (Zero-Tolerance Invariants)
1. **Nguyên tắc Zero-RDBMS:** Toàn bộ dữ liệu vĩnh cửu được lưu trữ dưới dạng file Apache Parquet (và GeoParquet 1.1.0 cho hình học không gian). In-process DuckDB SQL và Polars là các engine tính toán duy nhất. Cấm phụ thuộc vào server RDBMS/PostGIS bên ngoài.
2. **Nguyên tắc Bức tường Lửa Chống Rò rỉ Nhãn (Label Leakage Firewall):** Bảng Chợ Đặc trưng `data/marts/mart_grid_daily_features.parquet` tuân thủ cơ chế Whitelist columns tuyệt đối. **Nghiêm cấm 100% sự hiện diện của bất kỳ cột nào chứa nồng độ PM2.5 cùng ngày hoặc cờ quan sát từ trạm mặt đất**.
3. **Nguyên tắc Ghi Lũy đẳng (Strict Idempotency):** Toàn bộ pipeline ghi dữ liệu thô và biến đổi phải bảo đảm tính lũy đẳng: Chạy lại $N$ lần trên cùng tập dữ liệu đầu vào cho ra kết quả đồng nhất $100\%$, không làm tăng số dòng, không tạo duplicate hash (`_row_hash`).
4. **Nguyên tắc Trung thực Khoa học Mất dữ liệu Viễn thám (MNAR Invariance):** Dữ liệu sol khí MODIS MAIAC AOD bị khuyết thiếu vào mùa đông do mây che phủ được mô hình hóa theo cơ chế Missing Not At Random (MNAR). **Nghiêm cấm tuyệt đối mọi hình thức nội suy mù quáng** (Linear Interpolation, Mean Imputation) đối với AOD. Giữ nguyên `NULL` và đánh cờ `is_aod_missing_mnar = TRUE`.

---

## 2. KIẾN TRÚC MEDALLION & RANH GIỚI DỮ LIỆU (DATA LAKEHOUSE ARCHITECTURE)

Hệ thống Spatio-Temporal Data Lakehouse tuân thủ mô hình kiến trúc phân tầng Medallion Architecture 4 cấp độ:

```
[EXTERNAL SOURCES: 9 Nguồn Dữ liệu]
  │ (OpenAQ, AirNow, PAM Air, ERA5-Land, ERA5 BLH, CAMS, Sentinel-5P, MODIS, OSM/WorldCover/DEM)
  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. BRONZE / RAW LAYER (data/raw/)                                           │
│  - Định dạng: Apache Parquet phân vùng Hive: source=*/year=*/month=*/*.parquet│
│  - Tính chất: Append-only, Bất biến (Immutable), Bảo toàn phả hệ gốc (Lineage)│
│  - Metadata: _row_hash (SHA-256), _ingested_at_utc, _batch_id, _source_file │
│  - Cửa sổ truy vấn: Mở rộng 2020-12-31T16:00:00Z đến 2026-01-01T08:00:00Z  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. SILVER / STAGING LAYER (data/staging/)                                   │
│  - stg_ground_truth_hourly: Giữ 100% bản ghi sau hòa giải revision tất định  │
│    + Gán múi giờ ICT (UTC+7), phân định cờ cứng (Hard) vs cờ nghi vấn (Adv) │
│  - stg_ground_truth_daily: Lọc khắt khe valid_hours_count >= 18h & <= 24h    │
│    + Hiệu chỉnh ẩm kappa-Köhler (kappa=0.35) cho Tier 2; giữ song song raw   │
│  - stg_meteo_daily & stg_satellite_daily: Khử tích lũy mưa, gió vô hướng    │
│    (V_scalar, Persistence P), cờ mây MNAR, lọc QA Sentinel-5P >= 0.75       │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. GOLD / CORE STAR SCHEMA LAYER (data/core/)                               │
│  - Chuẩn mô hình hóa Kimball Star Schema: 3 Dimensions + 3 Facts            │
│  - Dimensions: dim_grid_1km (GeoParquet 1.1.0), dim_date (1826 ngày), dim_stn│
│  - Facts: fct_ground_truth_daily, fct_grid_meteo_daily, fct_grid_sat_daily │
│  - Khóa ngoại Zero-Orphan: Bắt buộc FK trỏ đúng PK hoặc trỏ vào Unknown row │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. PLATINUM / MARTS LAYER (data/marts/)                                     │
│  - mart_grid_daily_features: Feature Store tĩnh & động sạch nhãn PM2.5 100% │
│    + Quy mô: Đúng |S| dòng (N_GRID x 1826). Khóa chính: (grid_id, date_id) │
│  - mart_grid_daily_eda: Mart trực quan & bản đồ (ghép đặc trưng + nhãn ô)   │
│  - mart_station_matched: Bảng ghép 100% dòng trạm ngày hợp lệ với vector ô  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. MA TRẬN PHÂN CÔNG TRÁCH NHIỆM & QUYỀN SỞ HỮU (RACI MATRIX)

Mọi bảng dữ liệu và artifact trong hồ chứa dữ liệu phải có người sở hữu (Owner) chịu trách nhiệm về tính toàn vẹn và người thẩm định (Reviewer) ký duyệt nghiệm thu:

| Tầng Dữ liệu | Đường dẫn File Dữ liệu / Artifact | Nhà sản xuất (Data Producer) | Đơn vị Tiêu thụ (Data Consumers) | Chủ quản Sở hữu (Data Owner) | Người Ký duyệt (Reviewer) | Chu kỳ Phát hành (SLA) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **Manifest** | `data/manifests/grid_manifest.json` | TV1 (`ngthinh06`) | TV2, TV3, CI, Quality Gate | **TV1** | TV2, TV3 | Đóng băng ở Phase 1 |
| **Manifest** | `data/manifests/sources_audit_manifest.json` | TV2 & TV3 | TV1, Gate Ingestion | **TV2, TV3** | TV1 | Đóng băng ở Phase 1 |
| **Raw** | `data/raw/ground_truth/**/*.parquet` | TV2 (`hunganh`) | TV2 (Staging) | **TV2** | TV1 | Ingestion Phase 2 |
| **Raw** | `data/raw/atmospheric/**/*.parquet` | TV3 (`minh`) | TV3 (Staging), TV2 (RH) | **TV3** | TV1 | Ingestion Phase 2 |
| **Raw** | `data/raw/earth_observation/**/*.parquet` | TV3 (`minh`) | TV3 (Staging), TV1 (Marts)| **TV3** | TV1 | Ingestion Phase 2 |
| **Staging** | `data/staging/stg_ground_truth_hourly.parquet` | TV2 (`hunganh`) | TV2 (Daily Aggregate), EDA| **TV2** | TV1 | Phase 3 Staging |
| **Staging** | `data/staging/stg_ground_truth_daily.parquet` | TV2 (`hunganh`) | TV1 (Core & Marts), EDA | **TV2** | TV1 | Phase 3 Staging |
| **Staging** | `data/staging/stg_meteo_daily.parquet` | TV3 (`minh`) | TV1 (Core), TV2 (RH Join) | **TV3** | TV1, TV2 | Phase 3 Staging |
| **Staging** | `data/staging/stg_satellite_daily.parquet` | TV3 (`minh`) | TV1 (Core), EDA | **TV3** | TV1 | Phase 3 Staging |
| **Core Dim**| `data/core/dim_grid_1km.parquet` | TV1 (Lưới) + TV3 (Tĩnh)| TV1, TV2, TV3, Marts | **TV1** | TV3 | Phase 1 (v1.0 & v1.1) |
| **Core Dim**| `data/core/dim_date.parquet` | TV1 (`ngthinh06`) | Toàn nhóm, Star Schema | **TV1** | TV2 | Phase 1 |
| **Core Dim**| `data/core/dim_station.parquet` | TV1 (`ngthinh06`) | TV2 (Matched), Core Fact | **TV1** | TV2 | Phase 3 |
| **Core Fact**| `data/core/fct_ground_truth_daily.parquet` | TV1 (`ngthinh06`) | TV2, Matched View | **TV1** | TV2 | Phase 4 Core |
| **Core Fact**| `data/core/fct_grid_meteo_daily.parquet` | TV1 (`ngthinh06`) | Feature Mart, EDA Mart | **TV1** | TV3 | Phase 4 Core |
| **Core Fact**| `data/core/fct_grid_satellite_daily.parquet`| TV1 (`ngthinh06`) | Feature Mart, EDA Mart | **TV1** | TV3 | Phase 4 Core |
| **Marts** | `data/marts/mart_grid_daily_features.parquet`| TV1 (`ngthinh06`) | Toàn nhóm, ML Ready | **TV1** | TV2, TV3 | Phase 4 Marts |
| **Marts** | `data/marts/mart_grid_daily_eda.parquet` | TV1 (`ngthinh06`) | TV1, TV2, TV3 (EDA 1-6) | **TV1** | TV2, TV3 | Phase 4 Marts |
| **Marts** | `data/marts/mart_station_matched.parquet` | TV1 & TV2 | TV2 (EDA 1 & 2), EDA 5 | **TV2** | TV1 | Phase 4 Marts |

---

## 4. QUY ĐỊNH VỀ HẠT DỮ LIỆU (GRAIN), KHÓA VÀ CƠ CHẾ KHỬ TRÙNG TẤT ĐỊNH

### 4.1. Ma trận Hạt Dữ liệu & Hệ thống Khóa Nhận diện
Nhằm tránh triệt để hiện tượng phình dòng (Fan-out) do phép nối ghép sai hạt dữ liệu, bảng dưới đây chuẩn hóa Grain, Khóa chính (PK), Khóa ngoại (FK) và Khóa nghiệp vụ (Business Key) cho toàn bộ hệ thống:

| Tên Bảng | Hạt Dữ liệu Chuẩn (Grain) | Khóa Chính (Primary Key) | Khóa Ngoại (Foreign Keys) | Khóa Nghiệp vụ Nhận diện Phép đo (Business Key) |
| :--- | :--- | :--- | :--- | :--- |
| `stg_ground_truth_hourly` | 1 phép đo của 1 cảm biến tại trạm trong 1 giờ UTC | Khóa phức hợp 7 trường | Không áp dụng (Staging) | `(source_id, station_id, COALESCE(sensor_id,'primary'), COALESCE(parameter,'pm25'), COALESCE(averaging_period_hours, 1), COALESCE(measurement_method,'unknown'), timestamp_utc)` |
| `stg_ground_truth_daily` | 1 trạm quan trắc trong 1 ngày lịch địa phương ICT | `(station_id, date_id)` | `grid_id` (nội suy) | `(station_id, date_id)` |
| `stg_meteo_daily` | 1 ô pixel gốc ERA5-Land trong 1 ngày lịch ICT | `(era5_land_cell_id, date_id)` | Không áp dụng | `(era5_land_cell_id, date_id)` |
| `stg_satellite_daily` | 1 ô lưới 1km trong 1 ngày lịch ICT | `(grid_id, date_id)` | Không áp dụng | `(grid_id, date_id)` |
| `dim_grid_1km` | 1 ô lưới vuông $1\text{ km} \times 1\text{ km}$ cắt theo ranh giới Hà Nội | `grid_id` | Không | `grid_id` (dạng `grid_YYYY_XXXX` theo chỉ số hàng/cột EPSG:3405) |
| `dim_date` | 1 ngày lịch dương liên tục trong 5 năm (2021–2025) | `date_id` (INT32) | Không | `date_actual` (`YYYY-MM-DD`) |
| `dim_station` | 1 trạm quan trắc mặt đất đã qua kiểm toán | `station_id` (VARCHAR) | `grid_id` $\rightarrow$ `dim_grid_1km` | `(source_id, native_station_id)` |
| `fct_ground_truth_daily` | 1 trạm quan trắc mặt đất trong 1 ngày lịch địa phương ICT | `(station_id, date_id)` | `station_id` $\rightarrow$ `dim_station`<br>`date_id` $\rightarrow$ `dim_date`<br>`grid_id` $\rightarrow$ `dim_grid_1km` | `(station_id, date_id)` |
| `fct_grid_meteo_daily` | 1 ô lưới 1km trong 1 ngày lịch địa phương ICT | `(grid_id, date_id)` | `grid_id` $\rightarrow$ `dim_grid_1km`<br>`date_id` $\rightarrow$ `dim_date` | `(grid_id, date_id)` |
| `fct_grid_satellite_daily` | 1 ô lưới 1km trong 1 ngày lịch địa phương ICT | `(grid_id, date_id)` | `grid_id` $\rightarrow$ `dim_grid_1km`<br>`date_id` $\rightarrow$ `dim_date` | `(grid_id, date_id)` |
| `mart_grid_daily_features` | 1 ô lưới 1km trong 1 ngày lịch địa phương ICT | `(grid_id, date_id)` | `grid_id`, `date_id` | `(grid_id, date_id)` |
| `mart_grid_daily_eda` | 1 ô lưới 1km trong 1 ngày lịch địa phương ICT | `(grid_id, date_id)` | `grid_id`, `date_id` | `(grid_id, date_id)` |
| `mart_station_matched` | 1 bản ghi trạm ngày hợp lệ ghép với ô lưới tương ứng | `(station_id, date_id)` | `station_id`, `date_id`, `grid_id` | `(station_id, date_id)` |

### 4.2. Cơ chế Ghi Lũy đẳng & Quy tắc Tie-Break Hòa giải Bản ghi (Revision Reconciliation)
1. **Mã băm Phả hệ `_row_hash`:**
   - Được tính toán tự động bằng thuật toán SHA-256 từ chuỗi nối ghép tất định của toàn bộ các cột Business Key và các cột đo lường gốc (Payload).
   - Quy ước nối chuỗi: Phân tách bằng ký tự `||`, các giá trị `NULL` bắt buộc chuyển thành chuỗi `__NULL__`, các số thực dấu chấm động (Float) được làm tròn về 6 chữ số thập phân (`%.6f`) trước khi ghép chuỗi để chống trôi bit.
2. **Cơ chế Ghi Lũy đẳng (Idempotent Append):**
   - Khi chạy script Ingestion, hệ thống kiểm tra các mã `_row_hash` đã tồn tại trong partition đích. Nếu toàn bộ mã băm đã tồn tại $\rightarrow$ Bỏ qua (Skip); Nếu có bản ghi mới $\rightarrow$ Chỉ ghi các bản ghi mới vào file Parquet mới (`data_{batch_id}.parquet`).
3. **Quy tắc Tie-Break Tất định khi Hòa giải Revision ở Staging:**
   Khi cùng một phép đo được truyền về nhiều phiên bản chỉnh lý (Revision) trong Raw Layer, thuật toán Window Function trong Staging bắt buộc xếp hạng và chọn duy nhất 1 bản ghi tối hậu theo trật tự:
   ```sql
   ROW_NUMBER() OVER (
     PARTITION BY 
       source_id, 
       station_id, 
       COALESCE(sensor_id, 'primary'), 
       COALESCE(parameter, 'pm25'), 
       COALESCE(averaging_period_hours, 1), 
       COALESCE(measurement_method, 'unknown'), 
       timestamp_utc
     ORDER BY 
       _ingested_at_utc DESC, 
       _batch_id DESC, 
       _row_hash DESC
   ) AS rev_rank
   ```
   Chỉ giữ các bản ghi có `rev_rank = 1`.

---

## 5. ĐẶC TẢ LƯỢC ĐỒ CHI TIẾT TỚI TỪNG CỘT (EXHAUSTIVE COLUMN-LEVEL SCHEMAS)

---

### 5.1. Tầng Dữ liệu Thô (Bronze Raw Layer): `data/raw/**/*.parquet`
* **Vị trí lưu trữ:** Phân vùng Hive theo cấu trúc `data/raw/{source_category}/source={source_id}/year={YYYY}/month={MM}/*.parquet`
* **Nén:** Snappy hoặc ZSTD Level 3.
* **Cột bắt buộc phải có mặt trong mọi file Raw:**

| Tên Cột | Kiểu Dữ liệu (Arrow/DuckDB) | Cho phép NULL | Đơn vị Đo | Miền Giá trị Hợp lệ | Giá trị Mặc định | Quy ước Múi giờ | Mô tả Nghiệp vụ & Kỹ thuật |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `_row_hash` | `VARCHAR` (64 hex) | **NO** | String | 64 ký tự hex `[0-9a-f]{64}` | Không | N/A | Khóa băm SHA-256 tính từ khóa nghiệp vụ và payload gốc |
| `_ingested_at_utc` | `TIMESTAMP_UTC` | **NO** | Timestamp | `2021-01-01T00:00:00Z` trở đi | Current UTC | UTC | Thời điểm máy chủ ingestion thực thi ghi bản ghi |
| `_batch_id` | `VARCHAR` | **NO** | UUID / String| Chuỗi định danh batch duy nhất | Không | N/A | Mã đợt chạy ingestion (ví dụ: `batch_20261024_150000`) |
| `_source_file` | `VARCHAR` | YES | String | Tên file hoặc endpoint tải về | NULL | N/A | Tên file thô hoặc URL endpoint gốc phục vụ truy vết |
| `timestamp_utc` | `TIMESTAMP_UTC` | **NO** | Timestamp | `2020-12-31 16:00:00` đến `2026-01-01 08:00:00` | Không | UTC | Thời điểm quan sát gốc quy đổi chuẩn về giờ quốc tế UTC |

---

### 5.2. Chuỗi Giờ Quan trắc Trạm (Staging Ground Truth Hourly): `data/staging/stg_ground_truth_hourly.parquet`
* **Hạt dữ liệu (Grain):** 1 phép đo của 1 cảm biến trong 1 giờ UTC.
* **Quy mô dự kiến:** Khoảng 800,000 – 1,500,000 dòng (tùy thuộc số lượng trạm audit thực tế).

| Tên Cột | Kiểu Dữ liệu | Nullable | Đơn vị Đo | Miền Giá trị Hợp lệ | Giá trị Mặc định | Múi giờ | Mô tả Nghiệp vụ & Kỹ thuật |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `source_id` | `VARCHAR` | **NO** | Categorical | `'openaq'`, `'airnow'`, `'pamair'` | Không | N/A | Nguồn thu thập dữ liệu quan trắc mặt đất |
| `station_id` | `VARCHAR` | **NO** | Categorical | Mã định danh trạm chuẩn hóa (ví dụ: `'pamair_123'`) | Không | N/A | Khóa định danh duy nhất của trạm quan trắc |
| `sensor_id` | `VARCHAR` | **NO** | Categorical | Chuỗi ký tự định danh cảm biến | `'primary'` | N/A | Mã cảm biến (trường hợp trạm có nhiều đầu đo song song) |
| `parameter` | `VARCHAR` | **NO** | Categorical | `'pm25'` | `'pm25'` | N/A | Thông số ô nhiễm đo đạc (chuẩn hóa về PM2.5) |
| `averaging_period_hours`| `INT8` | **NO** | Giờ | $1$ | $1$ | N/A | Chu kỳ lấy mẫu trung bình của phép đo (1 giờ) |
| `measurement_method` | `VARCHAR` | YES | Categorical | `'FEM_BAM'`, `'Optical_Scattering'`, `'Unknown'` | `'Unknown'`| N/A | Phương pháp đo vật lý của thiết bị |
| `timestamp_utc` | `TIMESTAMP_UTC`| **NO** | Timestamp | Cửa sổ truy vấn 5 năm mở rộng | Không | UTC | Thời điểm đo theo múi giờ quốc tế UTC |
| `timestamp_local_ict` | `TIMESTAMP` | **NO** | Timestamp | `2021-01-01 00:00:00` đến `2025-12-31 23:59:59` | Không | UTC+7 | Thời điểm đo theo giờ địa phương Hà Nội (`UTC + 7h`) |
| `pm25_raw` | `DOUBLE` | **NO** | $\mu\text{g/m}^3$| $[-100.0, 5000.0]$ (bao gồm cả giá trị lỗi ban đầu) | Không | N/A | Nồng độ PM2.5 nguyên bản chưa qua bất kỳ bộ lọc nào |
| `pm25_calibrated` | `DOUBLE` | YES | $\mu\text{g/m}^3$| $[0.0, 1000.0]$ | NULL | N/A | Nồng độ PM2.5 sau hiệu chỉnh độ ẩm $\kappa$-Köhler (nếu Tier 2) |
| `rh_raw_station` | `DOUBLE` | YES | $\%$ | $[0.0, 100.0]$ | NULL | N/A | Độ ẩm tương đối đo tại chỗ tại trạm (nếu cảm biến có đo) |
| `rh_source` | `VARCHAR` | **NO** | Categorical | `'station'`, `'era5_land'`, `'none'` | `'none'` | N/A | Nguồn dữ liệu độ ẩm dùng cho hiệu chỉnh ẩm Köhler |
| `qc_negative` | `INT8` | **NO** | Binary Flag | $0$ hoặc $1$ | $0$ | N/A | Cờ cứng: $1$ nếu `pm25_raw < 0.0` (giá trị âm phi vật lý) |
| `qc_range_extreme` | `INT8` | **NO** | Binary Flag | $0$ hoặc $1$ | $0$ | N/A | Cờ cứng: $1$ nếu `pm25_raw > 1000.0 \mu\text{g/m}^3` |
| `qc_flatline` | `INT8` | **NO** | Binary Flag | $0$ hoặc $1$ | $0$ | N/A | Cờ cứng: $1$ nếu độ lệch chuẩn 6 giờ liên tiếp $\sigma_6 < 10^{-4}$ |
| `qc_spike_hampel` | `INT8` | **NO** | Binary Flag | $0$ hoặc $1$ | $0$ | N/A | Cờ nghi vấn: $1$ nếu điểm đo vượt ngưỡng lọc ngoại lai Hampel |
| `qc_high_rh` | `INT8` | **NO** | Binary Flag | $0$ hoặc $1$ | $0$ | N/A | Cờ cảnh báo: $1$ nếu độ ẩm tương đối $RH > 85.0\%$ (nồm ẩm) |
| `qc_passed_flag` | `INT8` | **NO** | Binary Flag | $0$ hoặc $1$ | Không | N/A | **Cờ quyết định tổng hợp:** $= 1$ khi 0 dính cờ cứng; $= 0$ nếu dính $\ge 1$ cờ cứng |
| `_ingested_at_utc` | `TIMESTAMP_UTC`| **NO** | Timestamp | Current UTC | Không | UTC | Thời điểm nạp bản ghi |
| `_batch_id` | `VARCHAR` | **NO** | String | Mã batch ingestion | Không | N/A | Mã đợt chạy ingestion |
| `_row_hash` | `VARCHAR` | **NO** | Hex String | 64 ký tự hex | Không | N/A | Khóa băm SHA-256 đối soát phả hệ |

---

### 5.3. Bảng Ngày Quan trắc Trạm (Staging Ground Truth Daily): `data/staging/stg_ground_truth_daily.parquet`
* **Hạt dữ liệu (Grain):** 1 trạm quan trắc mặt đất trong 1 ngày lịch địa phương ICT có từ 18 đến 24 giờ hợp lệ.
* **Điều kiện lọc bắt buộc:** `valid_hours_count >= 18 AND valid_hours_count <= 24`.

| Tên Cột | Kiểu Dữ liệu | Nullable | Đơn vị Đo | Miền Giá trị Hợp lệ | Giá trị Mặc định | Múi giờ | Mô tả Nghiệp vụ & Kỹ thuật |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `station_id` | `VARCHAR` | **NO** | Categorical | Khóa trạm hợp lệ khớp `dim_station` | Không | N/A | Khóa chính trạm quan trắc |
| `date_id` | `INT32` | **NO** | Format Date | $20210101 \dots 20251231$ (1,826 ngày) | Không | UTC+7 | Khóa ngày lịch địa phương định dạng YYYYMMDD |
| `grid_id` | `VARCHAR` | **NO** | Categorical | Khóa ô lưới 1km khớp `dim_grid_1km` | Không | N/A | Khóa ô lưới chứa tọa độ trạm quan trắc |
| `valid_hours_count` | `INT8` | **NO** | Giờ | $[18, 24]$ | Không | N/A | **Số giờ hợp lệ trong ngày:** Bắt buộc $\ge 18$ và $\le 24$ |
| `pm25_raw_mean` | `DOUBLE` | **NO** | $\mu\text{g/m}^3$| $[0.0, 1000.0]$ | Không | N/A | Nồng độ PM2.5 trung bình ngày từ các giờ thô hợp lệ |
| `pm25_calibrated_mean` | `DOUBLE` | **NO** | $\mu\text{g/m}^3$| $[0.0, 1000.0]$ | Không | N/A | Nồng độ PM2.5 trung bình ngày sau hiệu chỉnh $\kappa$-Köhler |
| `pm25_hampel_filtered_mean`| `DOUBLE` | YES | $\mu\text{g/m}^3$| $[0.0, 1000.0]$ | NULL | N/A | PM2.5 ngày trung bình sau khi loại bỏ thêm các giờ dính Hampel |
| `pm25_daily_std` | `DOUBLE` | YES | $\mu\text{g/m}^3$| $\ge 0.0$ | NULL | N/A | Độ lệch chuẩn nồng độ PM2.5 trong 24 giờ của ngày |
| `pm25_daily_min` | `DOUBLE` | **NO** | $\mu\text{g/m}^3$| $[0.0, 1000.0]$ | Không | N/A | Nồng độ PM2.5 thấp nhất ghi nhận trong các giờ hợp lệ |
| `pm25_daily_max` | `DOUBLE` | **NO** | $\mu\text{g/m}^3$| $[0.0, 1000.0]$ | Không | N/A | Nồng độ PM2.5 cao nhất ghi nhận trong các giờ hợp lệ |
| `data_completeness_pct` | `DOUBLE` | **NO** | $\%$ | $[75.0, 100.0]$ | Không | N/A | Tỷ lệ đầy đủ chuỗi giờ trong ngày: `(valid_hours_count / 24.0) * 100` |
| `is_rh_corrected_flag` | `INT8` | **NO** | Binary Flag | $0$ hoặc $1$ | $0$ | N/A | Cờ báo hiệu: $1$ nếu trạm là Tier 2 và đã áp dụng công thức Köhler |
| `exceeds_qcvn_50` | `INT8` | **NO** | Binary Flag | $0$ hoặc $1$ | Không | N/A | Cờ chẩn đoán: $1$ nếu `pm25_calibrated_mean > 50.0 \mu\text{g/m}^3` |
| `exceeds_who_15` | `INT8` | **NO** | Binary Flag | $0$ hoặc $1$ | Không | N/A | Cờ chẩn đoán: $1$ nếu `pm25_calibrated_mean > 15.0 \mu\text{g/m}^3` |

---

### 5.4. Bảng Chiều Không gian Lưới 1km (Core Dimension Grid 1km): `data/core/dim_grid_1km.parquet`
* **Chuẩn định dạng:** GeoParquet 1.1.0 (chuẩn nén WKB geometry, CRS `EPSG:3405`).
* **Hạt dữ liệu (Grain):** 1 ô lưới vuông $1\text{ km} \times 1\text{ km}$ nằm trong địa giới Hà Nội $+ 1$ bản ghi xử lý ngoại lệ `'grid_unknown'`.
* **Số dòng dự kiến:** $N_{\text{GRID}} + 1\text{ dòng}$ (khóa từ `grid_manifest.json`).

| Tên Cột | Kiểu Dữ liệu | Nullable | Đơn vị Đo | Miền Giá trị Hợp lệ | Giá trị Mặc định | Múi giờ | Mô tả Nghiệp vụ & Kỹ thuật |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `grid_id` | `VARCHAR` | **NO** | Identifier | Khóa dạng `grid_YYYY_XXXX` hoặc `'grid_unknown'` | Không | N/A | Khóa chính duy nhất định danh ô lưới 1km |
| `easting_m` | `DOUBLE` | **NO** | Mét (m) | Tọa độ phẳng VN-2000 UTM Zone 48N ($\approx 500,000\dots 650,000$) | $-1.0$ | N/A | Tọa độ tâm ô trục Đông-Tây trên hệ phẳng EPSG:3405 |
| `northing_m` | `DOUBLE` | **NO** | Mét (m) | Tọa độ phẳng VN-2000 UTM Zone 48N ($\approx 2,250,000\dots 2,400,000$) | $-1.0$ | N/A | Tọa độ tâm ô trục Bắc-Nam trên hệ phẳng EPSG:3405 |
| `lon_wgs84` | `DOUBLE` | **NO** | Độ (deg) | $[105.0, 106.5]$ | $-1.0$ | N/A | Tọa độ tâm kinh độ WGS84 phục vụ hiển thị web |
| `lat_wgs84` | `DOUBLE` | **NO** | Độ (deg) | $[20.5, 21.6]$ | $-1.0$ | N/A | Tọa độ tâm vĩ độ WGS84 phục vụ hiển thị web |
| `row_idx` | `INT32` | **NO** | Chỉ số | $\ge 0$ | $-1$ | N/A | Chỉ số hàng không gian tính từ gốc tọa độ BBOX |
| `col_idx` | `INT32` | **NO** | Chỉ số | $\ge 0$ | $-1$ | N/A | Chỉ số cột không gian tính từ gốc tọa độ BBOX |
| `district_name` | `VARCHAR` | YES | Tên quận/huyện | Danh mục 30 quận, huyện, thị xã thuộc Hà Nội | `'Unknown'` | N/A | Tên đơn vị hành chính cấp huyện chứa phần lớn diện tích ô |
| `urban_rural_class` | `VARCHAR` | **NO** | Categorical | `'Urban'`, `'Suburban'`, `'Rural'`, `'Unknown'` | `'Unknown'` | N/A | Phân loại khu vực nội đô, ven đô hoặc nông thôn |
| `area_in_boundary_km2` | `DOUBLE` | **NO** | $\text{km}^2$ | $(0.0, 1.0]$ | $1.0$ | N/A | Diện tích phần giao cắt thực tế của ô với địa giới Hà Nội |
| `osm_primary_road_len_m`| `DOUBLE` | **NO** | Mét (m) | $[0.0, 20000.0]$ | $0.0$ | N/A | Tổng chiều dài các tuyến đường chính (motorway, trunk, primary) trong ô |
| `osm_total_road_density_km_km2`| `DOUBLE`| **NO**| $\text{km/km}^2$| $[0.0, 50.0]$ | $0.0$ | N/A | Mật độ mạng lưới đường giao thông toàn diện trong ô |
| `worldcover_builtup_ratio`| `DOUBLE` | **NO** | Tỷ số | $[0.0, 1.0]$ | $0.0$ | N/A | Tỷ lệ diện tích bề mặt không thấm / công trình xây dựng (Lớp 50) |
| `worldcover_tree_ratio` | `DOUBLE` | **NO** | Tỷ số | $[0.0, 1.0]$ | $0.0$ | N/A | Tỷ lệ diện tích che phủ bởi tán cây xanh (Lớp 10) |
| `worldcover_cropland_ratio`| `DOUBLE`| **NO** | Tỷ số | $[0.0, 1.0]$ | $0.0$ | N/A | Tỷ lệ diện tích đất canh tác nông nghiệp / trồng lúa (Lớp 40) |
| `dem_elevation_mean_m` | `DOUBLE` | **NO** | Mét (m) | $[0.0, 1500.0]$ (Hà Nội: Ba Vì cao nhất ~1280m)| $10.0$ | N/A | Độ cao địa hình trung bình từ Copernicus DEM 30m |
| `dem_slope_deg` | `DOUBLE` | **NO** | Độ (deg) | $[0.0, 90.0]$ | $0.0$ | N/A | Độ dốc địa hình trung bình tính bằng thuật toán Horn |
| `era5_land_cell_id` | `VARCHAR` | YES | Identifier | Mã ô pixel gốc ERA5-Land gần nhất (~9km) | NULL | N/A | Khóa liên kết pixel khí tượng gốc phục vụ kiểm toán |
| `era5_blh_cell_id` | `VARCHAR` | YES | Identifier | Mã ô pixel gốc ERA5 BLH gần nhất (~25km) | NULL | N/A | Khóa liên kết pixel lớp biên khí quyển gốc |
| `cams_native_cell_id` | `VARCHAR` | YES | Identifier | Mã ô pixel gốc CAMS Reanalysis gần nhất (~40km)| NULL | N/A | Khóa liên kết pixel nền ô nhiễm mô hình CAMS |
| `geometry` | `BLOB` (WKB) | **NO** | GeoParquet WKB | Polygon vuông $1000\text{m} \times 1000\text{m}$ hệ EPSG:3405 | Polygon rỗng | N/A | Đối tượng hình học không gian chuẩn GeoParquet 1.1.0 |

---

### 5.5. Bảng Chiều Thời gian 5 Năm (Core Dimension Date): `data/core/dim_date.parquet`
* **Hạt dữ liệu (Grain):** 1 ngày lịch dương liên tục từ `2021-01-01` đến `2025-12-31` $+ 1$ dòng xử lý ngoại lệ `date_id = -1`.
* **Tổng số dòng bất biến:** Đúng **1,827 dòng** (1,826 ngày lịch thực tế + 1 dòng -1).

| Tên Cột | Kiểu Dữ liệu | Nullable | Đơn vị Đo | Miền Giá trị Hợp lệ | Giá trị Mặc định | Múi giờ | Mô tả Nghiệp vụ & Kỹ thuật |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `date_id` | `INT32` | **NO** | Key Format | $20210101 \dots 20251231$ và $-1$ | Không | UTC+7 | Khóa chính ngày định dạng số nguyên YYYYMMDD |
| `date_actual` | `DATE` | **NO** | Date | `2021-01-01` đến `2025-12-31` và `1970-01-01` | Không | UTC+7 | Ngày lịch chuẩn ISO-8601 |
| `year` | `INT16` | **NO** | Năm | $2021, 2022, 2023, 2024, 2025$ và $-1$ | Không | N/A | Năm lịch (xác nhận năm 2024 có 366 ngày) |
| `month` | `INT8` | **NO** | Tháng | $1 \dots 12$ và $-1$ | Không | N/A | Tháng trong năm ($1 \dots 12$) |
| `day_of_year` | `INT16` | **NO** | Ngày | $1 \dots 366$ và $-1$ | Không | N/A | Ngày thứ mấy trong năm ($1 \dots 365/366$) |
| `day_of_week` | `INT8` | **NO** | Thứ | $1 \dots 7$ (1: Thứ Hai, 7: Chủ Nhật) và $-1$ | Không | N/A | Thứ trong tuần theo chuẩn ISO |
| `is_weekend` | `INT8` | **NO** | Binary Flag | $0$ hoặc $1$ (Thứ Bảy, Chủ Nhật = 1) | $0$ | N/A | Cờ xác định ngày cuối tuần |
| `hanoi_season` | `VARCHAR` | **NO** | Categorical | `'Winter'`, `'Spring'`, `'Summer'`, `'Autumn'`, `'Unknown'` | `'Unknown'` | N/A | Mùa khí hậu Hà Nội: Winter (T11-T2), Spring (T3-T4), Summer (T5-T8), Autumn (T9-T10) |
| `is_crop_burning_window`| `INT8`| **NO** | Binary Flag | $0$ hoặc $1$ | $0$ | N/A | Cờ mùa đốt rơm rạ ngoại thành (15/5-15/6 và 15/9-31/10) |
| `is_vietnamese_holiday` | `INT8`| **NO** | Binary Flag | $0$ hoặc $1$ | $0$ | N/A | Cờ ngày lễ quốc gia (30/4, 1/5, Quốc khánh 2/9, Giỗ tổ) |
| `is_tet_holiday` | `INT8` | **NO** | Binary Flag | $0$ hoặc $1$ | $0$ | N/A | Cờ kỳ nghỉ Tết Nguyên Đán (thường kéo dài 7-9 ngày) |
| `is_covid_lockdown_hanoi`| `INT8`| **NO** | Binary Flag | $0$ hoặc $1$ | $0$ | N/A | Cờ giai đoạn giãn cách xã hội Covid-19 tại Hà Nội (Tháng 7 đến Tháng 9/2021) |

---

### 5.6. Bảng Chiều Danh mục Trạm Quan trắc (Core Dimension Station): `data/core/dim_station.parquet`
* **Hạt dữ liệu (Grain):** 1 trạm quan trắc mặt đất đã qua kiểm toán $+ 1$ bản ghi ngoại lệ `'station_unknown'`.

| Tên Cột | Kiểu Dữ liệu | Nullable | Đơn vị Đo | Miền Giá trị Hợp lệ | Giá trị Mặc định | Múi giờ | Mô tả Nghiệp vụ & Kỹ thuật |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `station_id` | `VARCHAR` | **NO** | Identifier | Khóa dạng chuỗi (ví dụ: `'pamair_234'`) | Không | N/A | Khóa chính định danh trạm quan trắc |
| `station_name` | `VARCHAR` | **NO** | Tên trạm | Chuỗi văn bản mô tả vị trí đặt trạm | `'Unknown Station'` | N/A | Tên hiển thị của trạm quan trắc |
| `source_id` | `VARCHAR` | **NO** | Categorical | `'openaq'`, `'airnow'`, `'pamair'`, `'unknown'` | `'unknown'` | N/A | Đơn vị / mạng lưới cung cấp dữ liệu trạm |
| `grid_id` | `VARCHAR` | **NO** | Foreign Key | Khóa ngoại trỏ sang `dim_grid_1km.grid_id` | `'grid_unknown'`| N/A | **Khóa ngoại bắt buộc:** Ô lưới 1km chứa tọa độ trạm |
| `easting_m` | `DOUBLE` | **NO** | Mét (m) | Metric EPSG:3405 | $-1.0$ | N/A | Tọa độ phẳng trạm trục X |
| `northing_m` | `DOUBLE` | **NO** | Mét (m) | Metric EPSG:3405 | $-1.0$ | N/A | Tọa độ phẳng trạm trục Y |
| `lon_wgs84` | `DOUBLE` | **NO** | Độ (deg) | $[105.0, 106.5]$ | $-1.0$ | N/A | Kinh độ WGS84 gốc của trạm |
| `lat_wgs84` | `DOUBLE` | **NO** | Độ (deg) | $[20.5, 21.6]$ | $-1.0$ | N/A | Vĩ độ WGS84 gốc của trạm |
| `sensor_tier` | `VARCHAR` | **NO** | Categorical | `'Tier_1_Reference_FEM'`, `'Tier_2_LowCost_Optical'`, `'Unknown'` | `'Unknown'` | N/A | Phân cấp cảm biến: Tier 1 (Tham chiếu chuẩn) vs Tier 2 (Cảm biến quang giá rẻ) |
| `station_microenv_type` | `VARCHAR`| **NO** | Categorical | `'Roadside'`, `'Urban_Background'`, `'Rural_Background'`, `'Unknown'` | `'Unknown'` | N/A | **Phân loại vi môi trường:** `Roadside` ($\le 50\text{m}$ đường chính), `Urban_Background`, `Rural_Background` |
| `distance_to_primary_road_m`| `DOUBLE`| **NO**| Mét (m) | $\ge 0.0$ | $-1.0$ | N/A | Khoảng cách ngắn nhất từ trạm tới tim đường chính OSM |
| `inlet_height_m` | `DOUBLE` | YES | Mét (m) | $[1.0, 50.0]$ | NULL | N/A | Chiều cao cửa thu mẫu khí so với mặt đất |
| `is_active_flag` | `INT8` | **NO** | Binary Flag | $0$ hoặc $1$ | $1$ | N/A | Cờ trạng thái hoạt động của trạm trong giai đoạn 2021–2025 |

---

### 5.7. Bảng Sự kiện Nồng độ Bụi Trạm Ngày (Core Fact Ground Truth Daily): `data/core/fct_ground_truth_daily.parquet`
* **Hạt dữ liệu (Grain):** 1 trạm quan trắc mặt đất trong 1 ngày lịch địa phương ICT có từ 18 đến 24 giờ hợp lệ.
* **Khóa chính:** Phức hợp `(station_id, date_id)`.
* **Khóa ngoại:** `station_id` $\rightarrow$ `dim_station`, `date_id` $\rightarrow$ `dim_date`, `grid_id` $\rightarrow$ `dim_grid_1km`.

| Tên Cột | Kiểu Dữ liệu | Nullable | Đơn vị Đo | Miền Giá trị Hợp lệ | Giá trị Mặc định | Múi giờ | Mô tả Nghiệp vụ & Kỹ thuật |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `station_id` | `VARCHAR` | **NO** | Foreign Key | Khớp `dim_station.station_id` | Không | N/A | Khóa ngoại xác định trạm quan trắc |
| `date_id` | `INT32` | **NO** | Foreign Key | Khớp `dim_date.date_id` | Không | UTC+7 | Khóa ngoại xác định ngày đo |
| `grid_id` | `VARCHAR` | **NO** | Foreign Key | Khớp `dim_grid_1km.grid_id` | Không | N/A | Khóa ngoại xác định ô lưới chứa trạm |
| `valid_hours_count` | `INT8` | **NO** | Giờ | $[18, 24]$ | Không | N/A | Số giờ quan sát hợp lệ (quy tắc $\ge 18\text{h}$) |
| `pm25_raw_mean` | `DOUBLE` | **NO** | $\mu\text{g/m}^3$| $[0.0, 1000.0]$ | Không | N/A | Giá trị trung bình nồng độ PM2.5 gốc trong ngày |
| `pm25_calibrated_mean` | `DOUBLE` | **NO** | $\mu\text{g/m}^3$| $[0.0, 1000.0]$ | Không | N/A | Giá trị trung bình nồng độ PM2.5 sau hiệu chỉnh $\kappa$-Köhler |
| `pm25_hampel_filtered_mean`| `DOUBLE`| YES | $\mu\text{g/m}^3$| $[0.0, 1000.0]$ | NULL | N/A | Giá trị trung bình ngày sau khi lọc ngoại lai Hampel chuỗi giờ |
| `pm25_daily_std` | `DOUBLE` | YES | $\mu\text{g/m}^3$| $\ge 0.0$ | NULL | N/A | Độ biến thiên nội ngày của nồng độ PM2.5 |
| `pm25_daily_min` | `DOUBLE` | **NO** | $\mu\text{g/m}^3$| $[0.0, 1000.0]$ | Không | N/A | Nồng độ thấp nhất trong ngày |
| `pm25_daily_max` | `DOUBLE` | **NO** | $\mu\text{g/m}^3$| $[0.0, 1000.0]$ | Không | N/A | Nồng độ cao nhất trong ngày |
| `data_completeness_pct` | `DOUBLE` | **NO** | $\%$ | $[75.0, 100.0]$ | Không | N/A | Tỷ lệ hoàn chỉnh chuỗi giờ |
| `is_rh_corrected_flag` | `INT8` | **NO** | Binary Flag | $0$ hoặc $1$ | $0$ | N/A | Cờ đánh dấu bản ghi đã áp dụng hiệu chỉnh độ ẩm |
| `calibrated_kappa_value`| `FLOAT` | **NO** | Hệ số | $0.35$ (hoặc $0.0$ nếu Tier 1) | $0.35$ | N/A | Hệ số giả định Köhler $\kappa$ sử dụng trong hiệu chỉnh |
| `exceeds_qcvn_50` | `INT8` | **NO** | Binary Flag | $0$ hoặc $1$ | Không | N/A | Vượt chuẩn QCVN 05:2023/BTNMT ($50\ \mu\text{g/m}^3$) |
| `exceeds_who_15` | `INT8` | **NO** | Binary Flag | $0$ hoặc $1$ | Không | N/A | Vượt khuyến nghị WHO 2021 ($15\ \mu\text{g/m}^3$) |

---

### 5.8. Bảng Sự kiện Khí tượng Ô Lưới Ngày (Core Fact Grid Meteo Daily): `data/core/fct_grid_meteo_daily.parquet`
* **Hạt dữ liệu (Grain):** 1 ô lưới 1km trong 1 ngày lịch địa phương ICT.
* **Số dòng bất biến:** Bắt buộc bằng đúng $|S| = N_{\text{GRID}} \times 1,826\text{ dòng}$.
* **Khóa chính:** `(grid_id, date_id)`.

| Tên Cột | Kiểu Dữ liệu | Nullable | Đơn vị Đo | Miền Giá trị Hợp lệ | Giá trị Mặc định | Múi giờ | Mô tả Nghiệp vụ & Kỹ thuật |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `grid_id` | `VARCHAR` | **NO** | Foreign Key | Khớp `dim_grid_1km.grid_id` | Không | N/A | Khóa chính ô lưới 1km |
| `date_id` | `INT32` | **NO** | Foreign Key | Khớp `dim_date.date_id` | Không | UTC+7 | Khóa chính ngày lịch địa phương |
| `era5_land_cell_id` | `VARCHAR` | YES | Foreign Key | Mã ô gốc ERA5-Land | NULL | N/A | Pixel gốc khí tượng trước khi broadcast |
| `era5_blh_cell_id` | `VARCHAR` | YES | Foreign Key | Mã ô gốc ERA5 BLH | NULL | N/A | Pixel gốc lớp biên khí quyển |
| `cams_native_cell_id` | `VARCHAR` | YES | Foreign Key | Mã ô gốc CAMS | NULL | N/A | Pixel gốc mô hình CAMS |
| `t2m_mean_c` | `DOUBLE` | YES | $^\circ\text{C}$ | $[-5.0, 50.0]$ | NULL | N/A | Nhiệt độ không khí trung bình ngày ở độ cao 2m |
| `t2m_min_c` | `DOUBLE` | YES | $^\circ\text{C}$ | $[-5.0, 50.0]$ | NULL | N/A | Nhiệt độ không khí thấp nhất trong ngày |
| `t2m_max_c` | `DOUBLE` | YES | $^\circ\text{C}$ | $[-5.0, 50.0]$ | NULL | N/A | Nhiệt độ không khí cao nhất trong ngày |
| `d2m_mean_c` | `DOUBLE` | YES | $^\circ\text{C}$ | $[-10.0, 40.0]$ | NULL | N/A | Điểm sương trung bình ngày ở độ cao 2m |
| `rh_mean_pct` | `DOUBLE` | YES | $\%$ | $[0.0, 100.0]$ | NULL | N/A | Độ ẩm tương đối trung bình ngày tính theo Magnus-Tetens |
| `surface_pressure_hpa` | `DOUBLE` | YES | $\text{hPa}$ | $[900.0, 1050.0]$ | NULL | N/A | Áp suất khí quyển bề mặt trung bình ngày |
| `wind_u10_mean_ms` | `DOUBLE` | YES | $\text{m/s}$ | $[-30.0, 30.0]$ | NULL | N/A | Thành phần gió Đông-Tây trung bình ở độ cao 10m |
| `wind_v10_mean_ms` | `DOUBLE` | YES | $\text{m/s}$ | $[-30.0, 30.0]$ | NULL | N/A | Thành phần gió Bắc-Nam trung bình ở độ cao 10m |
| `wind_speed_scalar_ms` | `DOUBLE` | YES | $\text{m/s}$ | $[0.0, 45.0]$ | NULL | N/A | **Tốc độ gió vô hướng trung bình ngày:** $V_{\text{scalar}} = \frac{1}{24}\sum w_h$ |
| `wind_speed_vector_ms` | `DOUBLE` | YES | $\text{m/s}$ | $[0.0, 45.0]$ | NULL | N/A | **Tốc độ gió vector trung bình ngày:** $V_{\text{vector}} = \sqrt{\bar{u}^2 + \bar{v}^2}$ |
| `wind_persistence_ratio`| `DOUBLE`| YES | Tỷ số | $[0.0, 1.0]$ | NULL | N/A | **Tỷ số bền vững gió:** $P = V_{\text{vector}} / \max(V_{\text{scalar}}, 10^{-4})$ |
| `wind_dir_sin` | `DOUBLE` | YES | Tỷ số | $[-1.0, 1.0]$ | NULL | N/A | Thành phần sin của hướng gió chủ đạo trong ngày |
| `wind_dir_cos` | `DOUBLE` | YES | Tỷ số | $[-1.0, 1.0]$ | NULL | N/A | Thành phần cos của hướng gió chủ đạo trong ngày |
| `total_precip_mm` | `DOUBLE` | YES | $\text{mm}$ | $[0.0, 500.0]$ | NULL | N/A | Tổng lượng mưa ngày địa phương sau khi khử tích lũy từng giờ |
| `is_rain_day_flag` | `INT8` | YES | Binary Flag | $0$ hoặc $1$ | NULL | N/A | Cờ ngày có mưa ($1$ nếu `total_precip_mm >= 0.1 mm`) |
| `blh_mean_m` | `DOUBLE` | YES | Mét (m) | $[10.0, 5000.0]$ | NULL | N/A | Chiều cao lớp biên hành tinh (PBL) trung bình ngày |
| `blh_min_night_m` | `DOUBLE` | YES | Mét (m) | $[10.0, 2000.0]$ | NULL | N/A | Chiều cao lớp biên ban đêm thấp nhất (chỉ số nghịch nhiệt bức xạ) |
| `blh_inversion_flag` | `INT8` | YES | Binary Flag | $0$ hoặc $1$ | NULL | N/A | Cờ nghịch nhiệt: $1$ nếu `blh_min_night_m < 150.0 m` |
| `cams_pm25_bg_ugm3` | `DOUBLE` | YES | $\mu\text{g/m}^3$| $[0.0, 500.0]$ | NULL | N/A | Nồng độ PM2.5 nền khu vực từ mô hình CAMS Reanalysis |
| `cams_aod_550nm` | `DOUBLE` | YES | Không thứ nguyên| $[0.0, 5.0]$ | NULL | N/A | Độ dày quang học sol khí AOD 550nm mô phỏng từ CAMS |

---

### 5.9. Bảng Sự kiện Viễn thám Vệ tinh Ô Lưới Ngày (Core Fact Grid Satellite Daily): `data/core/fct_grid_satellite_daily.parquet`
* **Hạt dữ liệu (Grain):** 1 ô lưới 1km trong 1 ngày lịch địa phương ICT.
* **Số dòng bất biến:** Bắt buộc bằng đúng $|S| = N_{\text{GRID}} \times 1,826\text{ dòng}$.
* **Khóa chính:** `(grid_id, date_id)`.

| Tên Cột | Kiểu Dữ liệu | Nullable | Đơn vị Đo | Miền Giá trị Hợp lệ | Giá trị Mặc định | Múi giờ | Mô tả Nghiệp vụ & Kỹ thuật |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `grid_id` | `VARCHAR` | **NO** | Foreign Key | Khớp `dim_grid_1km.grid_id` | Không | N/A | Khóa chính ô lưới 1km |
| `date_id` | `INT32` | **NO** | Foreign Key | Khớp `dim_date.date_id` | Không | UTC+7 | Khóa chính ngày lịch địa phương |
| `s5p_no2_trop_mol_m2` | `DOUBLE` | YES | $\text{mol/m}^2$| $[0.0, 0.001]$ | NULL | N/A | Mật độ cột đối lưu khí NO2 từ Sentinel-5P TROPOMI ($\ge 0.75$ QA) |
| `s5p_co_total_mol_m2` | `DOUBLE` | YES | $\text{mol/m}^2$| $[0.0, 0.1]$ | NULL | N/A | Mật độ cột tổng số khí CO từ Sentinel-5P TROPOMI |
| `s5p_cloud_fraction` | `DOUBLE` | YES | Tỷ số | $[0.0, 1.0]$ | NULL | N/A | Tỷ lệ che phủ của mây trong ô từ cảm biến Sentinel-5P |
| `s5p_qa_value` | `DOUBLE` | YES | Tỷ số | $[0.0, 1.0]$ | NULL | N/A | Điểm kiểm soát chất lượng QA trung bình của Sentinel-5P |
| `modis_aod_550nm` | `DOUBLE` | YES | Không thứ nguyên| $[-0.05, 5.0]$ | NULL | N/A | Độ dày quang học sol khí MODIS MAIAC AOD 550nm (đã nhân scale $0.001$) |
| `is_aod_missing_mnar` | `INT8` | **NO** | Binary Flag | $0$ hoặc $1$ | $0$ | N/A | **Cờ chẩn đoán MNAR:** $= 1$ khi `modis_aod_550nm IS NULL` (mây mù mùa đông) |
| `viirs_fire_count_25km_buffer`| `INT16`| **NO** | Đếm | $\ge 0$ | $0$ | N/A | Số lượng điểm cháy phát hiện bởi vệ tinh VIIRS trong bán kính 25km |

---

### 5.10. Bảng Chợ Đặc trưng Ô Lưới Ngày (Platinum Mart Features): `data/marts/mart_grid_daily_features.parquet`
* **Hạt dữ liệu (Grain):** 1 ô lưới 1km trong 1 ngày lịch địa phương ICT.
* **Số dòng bất biến:** Bắt buộc bằng đúng $|S| = N_{\text{GRID}} \times 1,826\text{ dòng}$ (đối chiếu `grid_manifest.json`).
* **Khóa chính:** `(grid_id, date_id)`.
* **Ràng buộc an toàn thông tin tối cao:** **TUYỆT ĐỐI KHÔNG CHỨA BẤT KỲ CỘT NÀO CÓ LIÊN QUAN ĐẾN NHÃN PM2.5 CÙNG NGÀY HOẶC QUAN TRẮC TRẠM** (Whitelisted Feature Store).

| Nhóm Đặc trưng | Danh mục Cột Chi tiết | Nguồn Cung cấp | Ràng buộc Toàn vẹn & Chống Rò rỉ Nhãn |
| :--- | :--- | :---: | :--- |
| **Định danh Không gian - Thời gian** | `grid_id`, `date_id` | Khung xương Spine | Khóa chính duy nhất, Zero-NULL, $100\%$ tích Descartes |
| **Tọa độ & Hình học** | `easting_m`, `northing_m`, `lon_wgs84`, `lat_wgs84`, `area_in_boundary_km2` | `dim_grid_1km` | Không chứa thông tin quan trắc |
| **Đặc trưng Tĩnh Đô thị & Địa hình** | `osm_primary_road_len_m`, `osm_total_road_density_km_km2`, `worldcover_builtup_ratio`, `worldcover_tree_ratio`, `worldcover_cropland_ratio`, `dem_elevation_mean_m`, `dem_slope_deg` | `dim_grid_1km` | Tĩnh, độc lập với thời gian, bất biến |
| **Lịch biểu & Mùa vụ** | `date_actual`, `year`, `month`, `day_of_year`, `day_of_week`, `is_weekend`, `hanoi_season`, `is_crop_burning_window`, `is_vietnamese_holiday`, `is_tet_holiday`, `is_covid_lockdown_hanoi` | `dim_date` | Lịch biểu khách quan, không chứa nhãn |
| **Khí quyển & Khí tượng Mặt đất** | `t2m_mean_c`, `t2m_min_c`, `t2m_max_c`, `d2m_mean_c`, `rh_mean_pct`, `surface_pressure_hpa`, `wind_u10_mean_ms`, `wind_v10_mean_ms`, `wind_speed_scalar_ms`, `wind_speed_vector_ms`, `wind_persistence_ratio`, `wind_dir_sin`, `wind_dir_cos`, `total_precip_mm`, `is_rain_day_flag` | `fct_grid_meteo_daily` | Biến dự báo vật lý độc lập |
| **Lớp biên Khí quyển & Nền CAMS** | `blh_mean_m`, `blh_min_night_m`, `blh_inversion_flag`, `cams_pm25_bg_ugm3`, `cams_aod_550nm` | `fct_grid_meteo_daily` | Nền mô phỏng khí quyển, không phải trạm mặt đất |
| **Viễn thám Khí quyển & Điểm cháy** | `s5p_no2_trop_mol_m2`, `s5p_co_total_mol_m2`, `s5p_cloud_fraction`, `s5p_qa_value`, `modis_aod_550nm`, `is_aod_missing_mnar`, `viirs_fire_count_25km_buffer` | `fct_grid_satellite_daily`| Viễn thám khách quan, cấm nội suy AOD |

---

### 5.11. Bảng Chợ Phục vụ Phân tích Khám phá (Platinum Mart EDA): `data/marts/mart_grid_daily_eda.parquet`
* **Hạt dữ liệu (Grain):** 1 ô lưới 1km trong 1 ngày lịch địa phương ICT.
* **Số dòng bất biến:** Bắt buộc bằng đúng $|S| = N_{\text{GRID}} \times 1,826\text{ dòng}$.
* **Mục đích:** Sử dụng cho 6 Chuyên đề Spatio-Temporal EDA, vẽ bản đồ phân bố nồng độ bụi ô lưới, đánh giá tương quan không gian.
* **Cấu trúc:** Gồm **toàn bộ các cột của `mart_grid_daily_features`** kết hợp thêm **3 cột nhãn tổng hợp trạm trong ô**:

| Tên Cột Bổ sung | Kiểu Dữ liệu | Nullable | Đơn vị Đo | Miền Giá trị Hợp lệ | Giá trị Mặc định | Mô tả Nghiệp vụ & Kỹ thuật |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| `active_station_count` | `INT16` | **NO** | Số lượng | $\ge 0$ | $0$ | Số lượng trạm mặt đất hoạt động hợp lệ nằm trong ô lưới vào ngày này |
| `grid_pm25_mean` | `DOUBLE` | YES | $\mu\text{g/m}^3$| $[0.0, 1000.0]$ | NULL | Giá trị trung bình nồng độ PM2.5 hiệu chỉnh của các trạm trong ô (NULL nếu không có trạm) |
| `has_station_observation_flag`| `INT8`| **NO** | Binary Flag | $0$ hoặc $1$ | $0$ | Cờ đánh dấu ô lưới có quan trắc trạm mặt đất tại chỗ ($1$ nếu `active_station_count > 0`) |

---

### 5.12. Bảng Ghép Trạm Thực tế (Platinum Mart Station Matched): `data/marts/mart_station_matched.parquet`
* **Hạt dữ liệu (Grain):** 1 bản ghi trạm ngày hợp lệ ghép nối đầy đủ với vector đặc trưng của ô lưới $1\text{ km}^2$ tương ứng.
* **Số dòng kỳ vọng:** Bằng **chính xác $100\%$ số dòng của `fct_ground_truth_daily.parquet`**.
* **Mục đích:** Phục vụ Chuyên đề EDA 1 (đối chiếu viễn thám - trạm), Chuyên đề EDA 2 (đối chứng phân phối Hampel & Köhler), Chuyên đề EDA 5 (dị biệt vi môi trường Roadside vs Background).
* **Cấu trúc:** Ghép `fct_ground_truth_daily` (nồng độ trạm) + `dim_station` (vi môi trường, khoảng cách đường) + `mart_grid_daily_features` (vector đặc trưng môi trường xung quanh ô 1km).

---

## 6. TIÊU CHUẨN CHẤT LƯỢNG DỮ LIỆU, ĐIỀU KIỆN SLA & CỔNG KIỂM ĐỊNH TỰ ĐỘNG

### 6.1. Tiêu chuẩn Thỏa thuận Mức Dịch vụ Dữ liệu (Data Service Level Agreement - SLA)
1. **Độ đầy đủ Dữ liệu Khí tượng (Meteorology Completeness SLA):**
   - Trên tập hợp các pixel gốc ERA5-Land (~45 điểm tâm): Tỷ lệ đầy đủ 5 năm của các biến nhiệt độ, độ ẩm, tốc độ gió và lượng mưa bắt buộc đạt **$\ge 98.0\%$**.
   - Trên tập hợp các pixel gốc ERA5 BLH (~8 điểm tâm): Tỷ lệ đầy đủ 5 năm của biến chiều cao lớp biên khí quyển bắt buộc đạt **$\ge 95.0\%$**.
2. **Độ đầy đủ Chuỗi giờ Quan trắc Trạm Mặt đất (Ground Truth Completeness SLA):**
   - Để một ngày quan trắc của một trạm được công nhận là đại diện hợp lệ cho ngày địa phương: Bắt buộc phải có **tối thiểu 18 giờ hợp lệ** (`valid_hours_count >= 18`). Các ngày có dưới 18 giờ bị loại khỏi bảng ngày và ghi nhận vào `docs/cleaning_log.md`.
3. **Độ trễ và Tính sẵn sàng:**
   - Dữ liệu Lakehouse phục vụ phân tích khám phá (EDA Batch Lakehouse), toàn bộ quy trình từ Bronze đến Marts có thể tái tạo tự động trong thời gian dưới 30 phút trên môi trường máy trạm tiêu chuẩn bằng lệnh `python run.py all`.

### 6.2. Đặc tả 9 Quy tắc Kiểm định Chất lượng DuckDB SQL (`quality/rules.yml`)
Cổng chất lượng DataOps Quality Gate thực thi 9 quy tắc SQL độc lập trên file Parquet. **Điều kiện PASS của toàn bộ pipeline là $100\%$ các quy tắc trả về `violation_count == 0`**:

1. **`QG_SPINE_01_CARDINALITY_VS_MANIFEST` (CRITICAL - TV1):** Số dòng của `mart_grid_daily_features.parquet` phải bằng đúng $100\%$ giá trị `expected_spine_rows` trong `grid_manifest.json` ($|S| = N_{\text{GRID}} \times 1,826$).
2. **`QG_SPINE_02_GRAIN_UNIQUENESS` (CRITICAL - TV1):** Khóa chính `(grid_id, date_id)` trong cả 2 bảng `mart_grid_daily_features` và `mart_grid_daily_eda` là duy nhất tuyệt đối (Zero Duplicates).
3. **`QG_LEAK_01_NO_LABEL_IN_FEATURE_MART` (CRITICAL - TV1):** Lược đồ cột của `mart_grid_daily_features.parquet` tuyệt đối không chứa bất kỳ cột nào có tên chứa chuỗi `%pm25%`, `%station%` hoặc `%ground_truth%`.
4. **`QG_FK_01_NO_ORPHAN_KEYS` (CRITICAL - TV2):** Toàn bộ các khóa ngoại `station_id`, `grid_id`, `date_id` trong các bảng Fact phải trỏ tới bản ghi hợp lệ trong các bảng Dimension (Zero Orphan FKs).
5. **`QG_NULL_01_SPINE_IDENTITY_MANDATORY` (CRITICAL - TV1):** Các cột định danh `grid_id` và `date_id` có giá trị `NULL` bằng 0 tuyệt đối trong toàn bộ các bảng Fact và Marts.
6. **`QG_COMPLETENESS_01_METEO_CONTRACT_RATE` (HIGH - TV3):** Tỷ lệ đầy đủ trên native cells của ERA5-Land $\ge 98\%$ và BLH $\ge 95\%$.
7. **`QG_SENSOR_01_VALID_HOURS_STRICT` (CRITICAL - TV2):** $100\%$ các dòng trong `stg_ground_truth_daily.parquet` có `valid_hours_count` nằm trong đoạn $[18, 24]$.
8. **`QG_SENSOR_02_HOURLY_QC_FLAGS_CONSISTENCY` (CRITICAL - TV2):** Tính nhất quán của cờ QC: Không có bản ghi nào dính cờ cứng mà `qc_passed_flag == 1`; Không có bản ghi nào chỉ dính cờ nghi vấn Hampel hoặc cờ ẩm mà bị loại oan sai (`qc_passed_flag == 0`).
9. **`QG_PHYSICS_01_DOMAIN_RANGES` (CRITICAL - TV3):** Kiểm tra biên giới hạn vật lý:
   - Nhiệt độ $T_{2m} \in [-5.0, 50.0]^\circ\text{C}$.
   - Độ ẩm $RH \in [0.0, 100.0]\%$.
   - Chiều cao lớp biên $BLH \in (10.0, 5000.0]\text{ m}$.
   - Tốc độ gió vô hướng $V_{\text{scalar}} \in [0.0, 45.0]\text{ m/s}$.
   - **Bất đẳng thức vận tốc gió:** $V_{\text{vector}} \le V_{\text{scalar}} + 10^{-5}$.
   - Tỷ lệ che phủ bề mặt WorldCover $\in [0.0, 1.0]$.
   - AOD MODIS $\in [-0.05, 5.0]$ (cho phép giá trị âm rất nhỏ do thuật toán nghịch đảo phản xạ).

### 6.3. Khung Kiểm thử Đột biến Chống Bù nhìn (Mutation Testing Verification)
Để bảo đảm bộ quy tắc kiểm định chất lượng không bị tê liệt ("bù nhìn"), script `quality/mutation_tester.py` tạo một môi trường sandbox tạm thời độc lập (`tempfile.TemporaryDirectory`) và lần lượt tiêm 4 lỗi đột biến kinh điển:
1. **Đột biến 1 (Xóa 1 ô lưới khỏi Mart):** Cố tình làm giảm số dòng từ $|S|$ xuống $|S| - 1826$ $\rightarrow$ Bắt buộc Gate `QG_SPINE_01` phải kích hoạt báo FAIL.
2. **Đột biến 2 (Tiêm cột nhãn vào Feature Mart):** Thêm cột giả lập `pm25_calibrated_mean` $\rightarrow$ Bắt buộc Gate `QG_LEAK_01` phải kích hoạt báo FAIL.
3. **Đột biến 3 (Tiêm khóa ngoại mồ côi):** Chèn dòng có `station_id = 'station_ghost_999'` $\rightarrow$ Bắt buộc Gate `QG_FK_01` phải kích hoạt báo FAIL.
4. **Đột biến 4 (Làm sai lệch logic cờ QC):** Sửa dòng có cờ cứng `qc_flatline = 1` nhưng gán `qc_passed_flag = 1` $\rightarrow$ Bắt buộc Gate `QG_SENSOR_02` phải kích hoạt báo FAIL.

**Tiêu chuẩn Nghiệm thu Mutation:** $\text{Mutation Score} = 100\%$ (Bắt gọn cả 4/4 đột biến).

---

## 7. QUY CHẾ TIẾN HÓA LƯỢC ĐỒ & QUẢN TRỊ THAY ĐỔI PHÁ VỠ (SCHEMA EVOLUTION & GOVERNANCE)

### 7.1. Phân loại Thay đổi Lược đồ (Change Classification)
Mọi đề xuất chỉnh sửa cấu trúc bảng dữ liệu phải được phân loại theo tiêu chuẩn Semantic Versioning:

1. **Thay đổi Không phá vỡ (Non-Breaking Changes - Minor Version Increment):**
   - Bổ sung một cột mới có tính chất tùy chọn (Nullable = YES) vào bảng Fact hoặc Dimension.
   - Bổ sung thêm dữ liệu phân vùng thời gian mới (ví dụ mở rộng sang năm 2026).
   - Nới lỏng một ngưỡng kiểm định vật lý sau khi có bằng chứng thực địa mới được nhóm đồng thuận.
2. **Thay đổi Phá vỡ (Breaking Changes - Major Version Increment):**
   - Đổi tên hoặc xóa bỏ một cột đang tồn tại.
   - Thay đổi kiểu dữ liệu của một cột (ví dụ từ `DOUBLE` sang `FLOAT` hoặc từ `INT32` sang `VARCHAR`).
   - Thắt chặt điều kiện NULL (từ Nullable = YES sang NO).
   - Thay đổi Hạt dữ liệu (Grain) hoặc định dạng Khóa chính của bảng.
   - Thay đổi Hệ quy chiếu CRS hoặc phương pháp tính khung lưới 1km.

### 7.2. Quy trình 4 Bước Phê duyệt Thay đổi Phá vỡ (RFC Approval Workflow)
Tuyệt đối không một thành viên nào được tự ý thay đổi schema trên branch cá nhân nếu chưa hoàn thành quy trình 4 bước:

```
[BƯỚC 1: TẠO RFC ISSUE]
Thành viên đề xuất tạo GitHub Issue gắn nhãn `schema-change-rfc`, mô tả lý do kỹ thuật,
danh sách bảng/cột bị tác động, phân tích rủi ro và phương án di chuyển dữ liệu (Migration Plan).
       │
       ▼
[BƯỚC 2: HỌP KỸ THUẬT & ĐỐI SOÁT DEPENDENCY]
Họp kỹ thuật 3 thành viên: TV1 đánh giá tác động tới Star Schema & Marts;
TV2 đánh giá tác động tới Cổng chất lượng & QC; TV3 đánh giá tác động tới pipeline GEE/EO.
       │
       ▼
[BƯỚC 3: CẬP NHẬT TÀI LIỆU CONTRACT & SCHEMA REGISTRY]
Nếu được chấp thuận, TV1 cập nhật file `docs/data_contract.md`, nâng số phiên bản (Major version),
đồng thời cập nhật đặc tả kiểu dữ liệu trong `common/schema_registry.py` và `quality/rules.yml`.
       │
       ▼
[BƯỚC 4: TRIỂN KHAI & CHẠY LẠI FULL REGRESSION TEST]
Thực thi di chuyển dữ liệu, chạy lại toàn bộ CI, Cổng chất lượng DuckDB SQL và Mutation Test.
Cả 3 thành viên ký duyệt PR trước khi merge vào `develop`/`main`.
```

---

## 8. BIÊN BẢN KÝ DUYỆT & HIỆU LỰC THI HÀNH (TEAM SIGN-OFF REGISTRY)

Văn bản Data Contract này có hiệu lực ràng buộc pháp lý kỹ thuật kể từ ngày ký. Mọi Pull Request vi phạm bất kỳ điều khoản nào trong hợp đồng này sẽ bị CI và người phụ trách từ chối merge vô điều kiện.

### BẢNG KÝ DUYỆT ĐỒNG THUẬN (3 THÀNH VIÊN)

| Vai trò Kỹ thuật | Thành viên Chịu trách nhiệm | Trách nhiệm Cam kết trong Contract | Chữ ký Trạng thái | Ngày Ký duyệt |
| :--- | :--- | :--- | :---: | :---: |
| **Data Architect & Spatial Lead (TV1)** | `ngthinh06` | - Chịu trách nhiệm về Hệ quy chiếu `EPSG:3405`, lưới 1km và `dim_grid_1km`<br>- Đảm bảo tính toàn vẹn 1,826 ngày của `dim_date`<br>- Bảo đảm Star Schema tầng Core và Feature Mart sạch nhãn 100%<br>- Duy trì quy mô Spine $|S| = N_{\text{GRID}} \times 1,826$ dòng từ manifest | **SIGNED & APPROVED** | 2026-10-24 |
| **Ground Truth & Quality Owner (TV2)** | `hunganh` | - Chịu trách nhiệm về tính toàn vẹn chuỗi giờ `stg_ground_truth_hourly`<br>- Bảo đảm quy tắc $\ge 18\text{h}$ trong `stg_ground_truth_daily`<br>- Kiểm soát hiệu chỉnh độ ẩm $\kappa$-Köhler ($\kappa=0.35$ working hypothesis)<br>- Vận hành 9 quy tắc SQL Quality Gate và đạt Mutation Score 100% | **SIGNED & APPROVED** | 2026-10-24 |
| **Atmospheric & EO Engineer (TV3)** | `minh` | - Chịu trách nhiệm về độ đầy đủ $\ge 98\%$ ERA5 và $\ge 95\%$ BLH<br>- Bảo đảm thuật toán khử tích lũy mưa giờ và tính gió vô hướng $V_{\text{scalar}}$<br>- Tuân thủ nghiêm ngặt chính sách cấm nội suy mù quáng MODIS AOD (MNAR)<br>- Trích xuất đủ 15 biến tĩnh đô thị OSM/WorldCover/DEM vào lưới 1km | **SIGNED & APPROVED** | 2026-10-24 |
| **Principal Data Engineer & Technical Lead** | Ban Kiến trúc Dữ liệu | - Phê duyệt toàn văn Hợp đồng Dữ liệu Data Contract v3.0<br>- Đóng băng kiến trúc Zero-RDBMS và quy chuẩn Medallion Lakehouse | **RATIFIED FOR EXECUTION** | 2026-10-24 |

---
*Tài liệu này được lưu trữ vĩnh viễn tại `docs/data_contract.md` thuộc repository HANOI_PM25 và là căn cứ tối cao cho mọi hoạt động kiểm thử tự động, tích hợp liên tục và nghiệm thu dữ liệu.*
