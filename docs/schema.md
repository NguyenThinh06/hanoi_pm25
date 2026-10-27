# KIẾN TRÚC VÀ ĐẶC TẢ LƯỢC ĐỒ DỮ LIỆU (DATA SCHEMA SPECIFICATION)
## DỰ ÁN HANOI_PM25: SPATIO-TEMPORAL DATA LAKEHOUSE (2021–2025)

**Cơ quan ban hành:** Ban Kiến trúc Dữ liệu & Quản trị Hồ chứa (Data Architecture Board)  
**Vai trò:** Data Architect & CI/CD Lead (`ngthinh06` - TV1)  
**Phiên bản tài liệu:** `v3.1.0-draft`  
**Ngày cập nhật:** 2026-10-26  
**Trạng thái kiến trúc:** ĐỀ XUẤT CHUẨN HÓA & CHỜ ĐỒNG THUẬN BÀN GIAO (DRAFT FOR TEAM HANDOFF)  
**Tài liệu ràng buộc chất lượng đi kèm:** [Hợp đồng Dữ liệu Tổng thể (Data Contract Specification)](./data_contract.md)

---

## 1. NGUYÊN TẮC KIẾN TRÚC & CÔNG NGHỆ CỐT LÕI (ARCHITECTURE PRINCIPLES)

Dự án HANOI_PM25 xây dựng hồ chứa dữ liệu không-thời gian phục vụ nghiên cứu và mô hình hóa ô nhiễm bụi mịn $PM_{2.5}$ tại Hà Nội giai đoạn 2021–2025. Toàn bộ hệ thống tuân thủ nghiêm ngặt các nguyên tắc kiến trúc sau:

1. **Kiến trúc Zero-RDBMS (Pure Parquet / GeoParquet + In-process DuckDB / Polars):**
   - Tuyệt đối không vận hành cơ sở dữ liệu quan hệ truyền thống (PostgreSQL/PostGIS, MySQL, SQL Server) hay các công cụ điều phối ngoài luồng (như dbt).
   - Mọi bảng dữ liệu từ Bronze (Raw), Silver (Staging), Gold (Core Star Schema) đến Platinum (Marts) được lưu trữ dưới định dạng chuẩn công nghiệp **Apache Parquet** và **GeoParquet 1.1.0** (nén bằng thuật toán `zstd`).
   - Query engine duy nhất là **DuckDB** nhúng và dataframe engine là **Polars**.
2. **Khung Không gian Bất biến (Spatial Grid Spine):**
   - Hệ quy chiếu quốc gia: **VN-2000 / UTM Zone 48N (`EPSG:3405`)**, đơn vị mét thực.
   - Ranh giới địa giới chuẩn: Lấy từ `data/reference/hanoi_boundary.geojson` (nguồn HDX COD-AB v02, GSO Vietnam, đóng băng mã băm SHA-256 `d8194abcc1d89eadd836941a750ae339f398a9b2e5e9d2428d0f96f1f2bd1f77`).
   - Quy tắc tạo lưới: Ô vuông đều kích thước $1.000\text{ m} \times 1.000\text{ m}$. Lựa chọn toàn bộ các ô giao cắt với ranh giới Hà Nội bằng toán tử hình học `intersects`.
   - Quy mô lưới phân tích: **$N_{\text{GRID}} = 3.610\text{ ô}$**. Bảng chiều `dim_grid_1km` có đúng **$3.611\text{ dòng}$** (bao gồm 3.610 ô phân tích thực và 1 dòng ngoại lệ `grid_unknown`).
3. **Khung Thời gian Bất biến (Temporal Spine):**
   - Trục ngày lịch liên tục 5 năm: Từ `2021-01-01` đến `2025-12-31` theo giờ địa phương Hà Nội (`Asia/Ho_Chi_Minh`, `UTC+7`).
   - Khóa ngày: `date_id` định dạng số nguyên `YYYYMMDD`, bản ghi ngoại lệ là `-1`.
   - Số ngày phân tích thực: **$N_{\text{DAYS}} = 1.826\text{ ngày}$** (gồm 366 ngày của năm nhuận 2024). Bảng chiều `dim_date` có đúng **$1.827\text{ dòng}$** (1.826 ngày thật + 1 dòng ngoại lệ `date_id = -1`).
4. **Quy mô Khung xương Phân tích (Analysis Spine):**
   - Tích Descartes thuần túy giữa ô phân tích và ngày phân tích:
     $$|S| = N_{\text{GRID}} \times N_{\text{DAYS}} = 3.610 \times 1.826 = 6.591.860\text{ dòng}$$
   - Khung này **loại trừ cả hai dòng ngoại lệ** (`grid_unknown` và `date_id = -1`).
5. **Phân công Trách nhiệm Rõ ràng (RACI Ownership):**
   - **Thành viên 1 (`ngthinh06` - TV1):** Lưới không gian (`dim_grid_1km` v1.0), Trục ngày (`dim_date`), Danh mục trạm (`dim_station`), Ingestion/QC chuỗi giờ trạm và Dữ liệu quan trắc mặt đất (`fct_ground_truth_daily`).
   - **Thành viên 2 (`hunganh` - TV2):** Trích xuất 15 đặc trưng tĩnh đô thị (`dim_grid_1km` v1.1), Viễn thám vệ tinh MODIS/Sentinel-5P/VIIRS (`fct_grid_satellite_daily`), Đóng gói Star Schema & Feature Marts (`mart_grid_daily_features`).
   - **Thành viên 3 (`minh` - TV3):** Tái phân tích khí tượng ERA5-Land & BLH (`fct_grid_meteo_daily`), Khử tích lũy lượng mưa, Tính gió vô hướng và độ ẩm tương đối ($RH$).

---

## 2. SƠ ĐỒ LUỒNG DỮ LIỆU ĐỒNG BỘ (END-TO-END DATA FLOW)

Dữ liệu luân chuyển qua 4 tầng kiến trúc (Medallion Architecture):

```mermaid
flowchart TD
    subgraph S_REF ["TẦNG THAM CHIẾU & MANIFEST (Reference & Metadata)"]
        R1["data/reference/hanoi_boundary.geojson<br/>(SHA-256 Verified)"]
        R2["data/manifests/grid_manifest.json<br/>(Frozen N_GRID=3,610, N_DAYS=1,826)"]
        R3["data/reference/station_registry.json<br/>(43 trạm khảo sát + 1 unknown)"]
    end

    subgraph S_RAW ["TẦNG RAW / BRONZE (data/raw/)"]
        RAW_STN["data/raw/ground_truth/source=openaq/<br/>Hive Partitions (Year/Month)<br/>Owner: TV1"]
        RAW_SAT["data/raw/satellite/<br/>MODIS AOD, S5P NO2, VIIRS<br/>Owner: TV2 (Dự kiến)"]
        RAW_MET["data/raw/meteo/<br/>ERA5-Land 45 native cells, BLH 8 cells<br/>Owner: TV3 (Dự kiến)"]
    end

    subgraph S_STG ["TẦNG STAGING / SILVER (data/staging/)"]
        STG_HR["stg_ground_truth_hourly.parquet<br/>Chuẩn hóa thời gian, chưa QC<br/>Owner: TV1"]
        STG_STN_D["stg_ground_truth_daily.parquet<br/>Gom ngày mọi trạm (kèm is_valid_day)<br/>Owner: TV1"]
        STG_SAT_D["stg_satellite_daily.parquet<br/>Lọc QA >= 0.75, cờ MNAR AOD<br/>Owner: TV2 (Đề xuất)"]
        STG_MET_D["stg_meteo_daily.parquet<br/>Khử tích lũy mưa, Gió scalar & P, RH<br/>Owner: TV3 (Đề xuất)"]
    end

    subgraph S_CORE ["TẦNG CORE STAR SCHEMA / GOLD (data/core/)"]
        DIM_G["dim_grid_1km.parquet<br/>3.611 dòng (3.610 thật + 1 unknown)<br/>GeoParquet EPSG:3405<br/>Owner: TV1 (v1.0) / TV2 (v1.1)"]
        DIM_D["dim_date.parquet<br/>1.827 dòng (1.826 thật + 1 unknown)<br/>Mùa Hà Nội & Đốt rơm rạ<br/>Owner: TV1"]
        DIM_S["dim_station.parquet<br/>44 dòng (43 trạm khảo sát + 1 unknown)<br/>Tier, Tọa độ, Grid mapping<br/>Owner: TV1"]
        FCT_GT["fct_ground_truth_daily.parquet<br/>Grain: (station_id, date_id)<br/>Giữ mọi ngày, gắn cờ 18 giờ<br/>Owner: TV1"]
        FCT_SAT["fct_grid_satellite_daily.parquet<br/>Grain đề xuất: (grid_id, date_id)<br/>AOD, NO2, VIIRS, cờ MNAR<br/>Owner: TV2 (Chờ chốt)"]
        FCT_MET["fct_grid_meteo_daily.parquet<br/>Grain đề xuất: (grid_id, date_id)<br/>T2m, RH, Mưa, Gió, Khí áp, BLH<br/>Owner: TV3 (Chờ chốt)"]
    end

    subgraph S_MARTS ["TẦNG MARTS / PLATINUM (data/marts/)"]
        MART_FEAT["mart_grid_daily_features.parquet<br/>ĐÚNG 6.591.860 DÒNG (3.610 x 1.826)<br/>SẠCH NHÃN 100% (KHÔNG CỘT PM2.5)<br/>LEFT JOIN KHÔNG DROP DÒNG<br/>Owner: TV2 / TV1"]
        MART_MATCH["mart_station_matched.parquet<br/>Grain: (station_id, date_id)<br/>Ghép nhãn trạm với vector đặc trưng ô<br/>Owner: TV1 / TV2"]
        MART_EDA["mart_grid_daily_eda.parquet<br/>Khung 6.591.860 dòng kèm nhãn tổng hợp ô<br/>Owner: TV2"]
    end

    %% Pipeline linkages
    R1 --> DIM_G
    R1 --> R2
    DIM_G -.-> R2
    DIM_D -.-> R2

    RAW_STN --> STG_HR --> STG_STN_D --> FCT_GT
    R3 --> DIM_S
    STG_HR -.-> DIM_S

    RAW_SAT --> STG_SAT_D --> FCT_SAT
    RAW_MET --> STG_MET_D --> FCT_MET

    DIM_G --> MART_FEAT
    DIM_D --> MART_FEAT
    FCT_SAT --> MART_FEAT
    FCT_MET --> MART_FEAT

    MART_FEAT --> MART_MATCH
    FCT_GT --> MART_MATCH

    MART_FEAT --> MART_EDA
    FCT_GT -.->|Aggregate by grid_id| MART_EDA
```

---

## 3. DANH MỤC TỔNG THỂ BẢNG VÀ ARTIFACT DỮ LIỆU

| Tên bảng / File Artifact | Tầng dữ liệu | Định dạng lưu trữ | Hạt dữ liệu (Grain) | Khóa chính (PK) | Khóa ngoại (FK) | Đường dẫn vật lý | Trách nhiệm (Owner) | Trạng thái kỹ thuật |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :---: | :---: |
| `grid_manifest.json` | Metadata | JSON | Toàn dự án | N/A | N/A | `data/manifests/grid_manifest.json` | TV1 | **Đã triển khai** |
| `dim_grid_1km` (v1.0) | Core Dim | GeoParquet 1.1.0 | 1 ô lưới 1km | `grid_id` | N/A | `data/core/dim_grid_1km.parquet` | TV1 | **Đã triển khai** |
| `dim_grid_1km` (v1.1) | Core Dim | GeoParquet 1.1.0 | 1 ô lưới 1km | `grid_id` | N/A | `data/core/dim_grid_1km.parquet` | TV2 | **Đang thực hiện** |
| `dim_date` | Core Dim | Parquet | 1 ngày lịch | `date_id` | N/A | `data/core/dim_date.parquet` | TV1 | **Đã triển khai** |
| `dim_station` | Core Dim | Parquet | 1 trạm quan trắc | `station_id` | `grid_id` | `data/core/dim_station.parquet` | TV1 | **Đã triển khai** (44 dòng: 43 trạm khảo sát + 1 unknown) |
| `stg_ground_truth_hourly` | Staging | Parquet | Trạm – Sensor – Giờ UTC | `(station_id, sensor_id, datetime_utc)` | `grid_id` | `data/staging/stg_ground_truth_hourly.parquet` | TV1 | **Đã triển khai** |
| `stg_ground_truth_daily` | Staging | Parquet | Trạm – Ngày | `(station_id, date_id)` | `station_id`, `date_id`, `grid_id` | `data/staging/stg_ground_truth_daily.parquet` | TV1 | **Đã triển khai** |
| `fct_ground_truth_daily` | Core Fact | Parquet | Trạm – Ngày có bản ghi trong 2021–2025 | `(station_id, date_id)` | `station_id`, `date_id`, `grid_id` | `data/core/fct_ground_truth_daily.parquet` | TV1 | **Đã triển khai** (Giữ mọi ngày có quan sát, cờ 18h) |
| `stg_satellite_daily` | Staging | Parquet | Pixel/Ô – Ngày | Chờ TV2 xác nhận | `date_id` | `data/staging/stg_satellite_daily.parquet` | TV2 | *Đề xuất / Chưa có* |
| `fct_grid_satellite_daily`| Core Fact | Parquet | Ô – Ngày (Đề xuất) | `(grid_id, date_id)` | `grid_id`, `date_id` | `data/core/fct_grid_satellite_daily.parquet` | TV2 | *Đề xuất / Chờ TV2 chốt* |
| `stg_meteo_daily` | Staging | Parquet | Pixel/Ô – Ngày | Chờ TV3 xác nhận | `date_id` | `data/staging/stg_meteo_daily.parquet` | TV3 | *Đề xuất / Chưa có* |
| `fct_grid_meteo_daily` | Core Fact | Parquet | Ô – Ngày (Đề xuất) | `(grid_id, date_id)` | `grid_id`, `date_id` | `data/core/fct_grid_meteo_daily.parquet` | TV3 | *Đề xuất / Chờ TV3 chốt* |
| `mart_grid_daily_features`| Platinum Mart | Parquet | Ô – Ngày phân tích | `(grid_id, date_id)` | `grid_id`, `date_id` | `data/marts/mart_grid_daily_features.parquet` | TV2 / TV1 | *Thiết kế chuẩn / Chờ upstream* |
| `mart_station_matched` | Platinum Mart | Parquet | Trạm – Ngày có PM2.5 thô | `(station_id, date_id)` | `station_id`, `date_id`, `grid_id` | `data/marts/mart_station_matched.parquet` | TV1 / TV2 | *Đề xuất / chưa triển khai* |
| `mart_grid_daily_eda` | Platinum Mart | Parquet | Ô – Ngày phân tích | `(grid_id, date_id)` | `grid_id`, `date_id` | `data/marts/mart_grid_daily_eda.parquet` | TV2 | *Đề xuất* |

---

## 4. CHI TIẾT LƯỢC ĐỒ CÁC MÔ HÌNH DỮ LIỆU CỐT LÕI (MODELS SPECIFICATION)

### 4.1. Bảng Chiều Không Gian Lưới 1km: `dim_grid_1km`
- **Đường dẫn:** `data/core/dim_grid_1km.parquet`
- **Định dạng:** GeoParquet 1.1.0 (`EPSG:3405`)
- **Hạt dữ liệu (Grain):** Từng ô lưới vuông $1\text{ km} \times 1\text{ km}$.
- **Khóa chính:** `grid_id` (Không được Null, duy nhất 100%).
- **Số dòng thực tế:** **3.611 dòng** (3.610 ô phân tích thực tế + 1 ô ngoại lệ `grid_unknown`).

| Tên cột | Kiểu dữ liệu | Đơn vị | Nullable | Giai đoạn (Stage) | Ý nghĩa nghiệp vụ |
| :--- | :--- | :--- | :---: | :---: | :--- |
| `grid_id` | `VARCHAR` | Chuỗi mã | **NO** | v1.0 (TV1) | Mã định danh ô lưới: `grid_{lower_left_easting}_{lower_left_northing}`. Dòng ngoại lệ có giá trị `grid_unknown`. |
| `easting_m` | `DOUBLE` | Mét (m) | YES | v1.0 (TV1) | Tọa độ tâm ô lưới theo trục Đông VN-2000 UTM Zone 48N. Ngoại lệ = `-1.0`. |
| `northing_m` | `DOUBLE` | Mét (m) | YES | v1.0 (TV1) | Tọa độ tâm ô lưới theo trục Bắc VN-2000 UTM Zone 48N. Ngoại lệ = `-1.0`. |
| `is_canonical` | `INT64` | Cờ (0/1) | **NO** | v1.0 (TV1) | `1` nếu trọng tâm ô nằm hoàn toàn trong ranh giới Hà Nội (`centroid.within`); `0` nếu là ô biên cắt ranh giới hoặc ô ngoại lệ. Tổng số ô canonical là 3.363 ô. |
| `area_in_boundary_km2` | `DOUBLE` | $\text{km}^2$ | **NO** | v1.0 (TV1) | Diện tích phần giao giữa ô lưới và đa giác địa giới Hà Nội ($0.0 \le \text{area} \le 1.0$). Ô ngoại lệ = `0.0`. |
| `geometry` | `GEOMETRY` | Polygon | YES | v1.0 (TV1) | Đa giác ô vuông $1.000\text{ m} \times 1.000\text{ m}$ theo `EPSG:3405`. Dòng ngoại lệ là `NULL`. |
| `osm_primary_road_m` | `FLOAT` | Mét (m) | YES | v1.1 (TV2) | *(Đề xuất TV2)* Chiều dài đường quốc lộ / đường chính OpenStreetMap cắt qua ô lưới. |
| `osm_road_density_km_km2`| `FLOAT` | $\text{km}/\text{km}^2$ | YES | v1.1 (TV2) | *(Đề xuất TV2)* Mật độ mạng lưới giao thông đường bộ toàn bộ các cấp trong ô lưới. |
| `worldcover_builtup_ratio`| `FLOAT` | Tỷ lệ [0..1] | YES | v1.1 (TV2) | *(Đề xuất TV2)* Tỷ lệ diện tích bề mặt không thấm / công trình xây dựng (ESA WorldCover mã 50). |
| `worldcover_tree_ratio` | `FLOAT` | Tỷ lệ [0..1] | YES | v1.1 (TV2) | *(Đề xuất TV2)* Tỷ lệ tán che cây xanh / rừng (ESA WorldCover mã 10). |
| `worldcover_cropland_ratio`| `FLOAT` | Tỷ lệ [0..1] | YES | v1.1 (TV2) | *(Đề xuất TV2)* Tỷ lệ đất canh tác nông nghiệp / trồng trọt (ESA WorldCover mã 40). |
| `worldcover_water_ratio` | `FLOAT` | Tỷ lệ [0..1] | YES | v1.1 (TV2) | *(Đề xuất TV2)* Tỷ lệ mặt nước thường trực sông hồ (ESA WorldCover mã 80). |
| `dem_elevation_mean_m` | `FLOAT` | Mét (m) | YES | v1.1 (TV2) | *(Đề xuất TV2)* Độ cao địa hình trung bình so với mực nước biển (NASA SRTM DEM 30m). |
| `dem_slope_mean_deg` | `FLOAT` | Độ (degrees) | YES | v1.1 (TV2) | *(Đề xuất TV2)* Độ dốc sườn địa hình trung bình trong ô lưới ($0^\circ \le \text{slope} \le 90^\circ$). |

---

### 4.2. Bảng Chiều Thời Gian: `dim_date`
- **Đường dẫn:** `data/core/dim_date.parquet`
- **Định dạng:** Apache Parquet
- **Hạt dữ liệu (Grain):** Từng ngày lịch (Daily).
- **Khóa chính:** `date_id` (Không được Null, duy nhất 100%).
- **Số dòng thực tế:** **1.827 dòng** (1.826 ngày lịch thực tế từ 2021-01-01 đến 2025-12-31 + 1 dòng ngoại lệ `date_id = -1`).

| Tên cột | Kiểu dữ liệu | Đơn vị | Nullable | Giai đoạn | Ý nghĩa nghiệp vụ |
| :--- | :--- | :--- | :---: | :---: | :--- |
| `date_id` | `INT32` | Số nguyên | **NO** | v1.0 (TV1) | Khóa thay thế dạng số nguyên `YYYYMMDD` (ví dụ: `20210101`). Dòng ngoại lệ có giá trị `-1`. |
| `date_actual` | `DATE` | Ngày lịch | **NO** | v1.0 (TV1) | Ngày lịch theo chuẩn ISO-8601 (`YYYY-MM-DD`). Ngoại lệ = `1970-01-01`. |
| `year` | `INT64` | Năm | **NO** | v1.0 (TV1) | Năm dương lịch ($2021 \le \text{year} \le 2025$). Dòng ngoại lệ = `-1`. |
| `month` | `INT64` | Tháng | **NO** | v1.0 (TV1) | Tháng trong năm ($1 \le \text{month} \le 12$). Dòng ngoại lệ = `-1`. |
| `day` | `INT64` | Ngày | **NO** | v1.0 (TV1) | Ngày trong tháng ($1 \le \text{day} \le 31$). Dòng ngoại lệ = `-1`. |
| `day_of_week` | `INT64` | Thứ | **NO** | v1.0 (TV1) | Thứ trong tuần theo chuẩn ISO ($1$: Thứ Hai, ..., $7$: Chủ Nhật). Ngoại lệ = `-1`. |
| `is_weekend` | `INT64` | Cờ (0/1) | **NO** | v1.0 (TV1) | `1` nếu là Thứ Bảy hoặc Chủ Nhật; `0` nếu là ngày làm việc. Ngoại lệ = `0`. |
| `hanoi_season` | `VARCHAR` | Tên mùa | **NO** | v1.0 (TV1) | Mùa khí hậu Hà Nội: `Winter` (T11–T2), `Spring` (T3–T4), `Summer` (T5–T8), `Autumn` (T9–T10). Dòng ngoại lệ = `Unknown`. |
| `is_crop_burning_window`| `INT64` | Cờ (0/1) | **NO** | v1.0 (TV1) | Cửa sổ đốt rơm rạ ngoại thành Hà Nội: Đợt 1 (15/5–15/6), Đợt 2 (15/9–31/10). `1` nếu thuộc cửa sổ, `0` nếu không. |

---

### 4.3. Bảng Chiều Trạm Quan Trắc Mặt Đất: `dim_station`
- **Đường dẫn:** `data/core/dim_station.parquet`
- **Định dạng:** Apache Parquet
- **Hạt dữ liệu (Grain):** Từng trạm đo mặt đất vật lý.
- **Khóa chính:** `station_id` (Không được Null, duy nhất 100%).
- **Khóa ngoại:** `grid_id` $\rightarrow$ `dim_grid_1km(grid_id)`.
- **Số dòng thực tế:** **44 dòng** theo ảnh chụp khảo sát hiện tại (43 trạm quan trắc mặt đất khảo sát trong bounding box Hà Nội từ OpenAQ tháng 10/2026 + 1 trạm ngoại lệ `station_unknown`).
> [!NOTE]
> - **Phạm vi địa lý & Phương thức thu thập:** Danh mục trạm được trích xuất bằng truy vấn Bounding Box mở rộng `[105.28, 20.56, 106.02, 21.39]` trên OpenAQ v3 API (`audit_stations.py`). Quy trình nạp hiện tại **chưa thực thi bộ lọc đa giác địa giới tự động** (`point-in-polygon` với `hanoi_boundary.geojson`). Trong tập dữ liệu khảo sát thực tế, toàn bộ 43 trạm đều có tọa độ nằm trong đa giác Hà Nội và rơi vào các ô phân tích thuộc `dim_grid_1km`.
> - **Phân biệt hai khái niệm không gian:** Cần phân biệt giữa việc "tọa độ trạm nằm trong đa giác địa giới Hà Nội" với "trạm rơi vào ô lưới phân tích của `dim_grid_1km`". Do lưới 1km được tạo bằng toán tử `intersects` với ranh giới, các ô lưới biên có thể vươn ra ngoài mép đa giác địa giới.
> - **Quy mô danh mục:** Số lượng 43 trạm mặt đất là ảnh chụp khảo sát (survey snapshot), không phải là hằng số bất biến như lưới không gian (3.610 ô) hay trục ngày (1.826 ngày), và không có kiểm tra số dòng cứng (`expectedRowCount`) trong bộ máy kiểm định hợp đồng. Nếu danh mục OpenAQ mở rộng trong tương lai, bảng này sẽ được cập nhật có kiểm soát.

| Tên cột | Kiểu dữ liệu | Đơn vị | Nullable | Giai đoạn | Ý nghĩa nghiệp vụ |
| :--- | :--- | :--- | :---: | :---: | :--- |
| `station_id` | `VARCHAR` | Mã trạm | **NO** | v1.0 (TV1) | Định danh duy nhất trạm: `openaq_{loc_id}`. Dòng ngoại lệ = `station_unknown`. |
| `station_name` | `VARCHAR` | Chuỗi ký tự | **NO** | v1.0 (TV1) | Tên vị trí trạm quan trắc (ví dụ: *United States Embassy Hanoi*, *Chi cục BVMT Hà Nội*). Ngoại lệ = `Unknown Station`. |
| `provider` | `VARCHAR` | Tên cơ quan | **NO** | v1.0 (TV1) | Đơn vị vận hành và cung cấp dữ liệu trạm (ví dụ: *US Department of State*, *Chi cục BVMT*). |
| `sensor_tier` | `VARCHAR` | Phân tầng Tier| **NO** | v1.0 (TV1) | Phân tầng cấp độ thiết bị: `Tier_1_Reference_FEM` (máy chuẩn tham chiếu sấy mẫu), `Tier_2_LowCost_Optical` (cảm biến tán xạ quang học), hoặc `Unknown`. |
| `station_microenv_type`| `VARCHAR`| Phân loại MT | **NO** | v1.0 (TV1) | Vi môi trường xung quanh trạm: `Urban_Background`, `Roadside`, `Rural_Background`, `Unknown`. |
| `grid_id` | `VARCHAR` | Mã ô lưới | **NO** | v1.0 (TV1) | Khóa ngoại trỏ sang ô vuông $1\text{ km} \times 1\text{ km}$ chứa trạm trong `dim_grid_1km`. Dòng ngoại lệ trỏ sang `grid_unknown`. |
| `lon_wgs84` | `DOUBLE` | Độ kinh | YES | v1.0 (TV1) | Tọa độ kinh độ địa lý theo WGS84 (`EPSG:4326`). Dòng ngoại lệ là `NULL`. |
| `lat_wgs84` | `DOUBLE` | Độ vĩ | YES | v1.0 (TV1) | Tọa độ vĩ độ địa lý theo WGS84 (`EPSG:4326`). Dòng ngoại lệ là `NULL`. |
| `easting_m` | `DOUBLE` | Mét (m) | YES | v1.0 (TV1) | Tọa độ Easting theo VN-2000 UTM Zone 48N (`EPSG:3405`). Dòng ngoại lệ là `NULL`. |
| `northing_m` | `DOUBLE` | Mét (m) | YES | v1.0 (TV1) | Tọa độ Northing theo VN-2000 UTM Zone 48N (`EPSG:3405`). Dòng ngoại lệ là `NULL`. |
| `is_active` | `BOOLEAN` | Đúng/Sai | **NO** | v1.0 (TV1) | Trạng thái trạm còn hoạt động hay không dựa trên lần gửi dữ liệu gần nhất. Ngoại lệ = `false`. |

---

### 4.4. Bảng Dữ Liệu Sự Kiện Quan Trắc Mặt Đất Hàng Ngày: `fct_ground_truth_daily`
- **Đường dẫn:** `data/core/fct_ground_truth_daily.parquet`
- **Định dạng:** Apache Parquet
- **Hạt dữ liệu (Grain):** **Trạm – Ngày** (`station_id`, `date_id`). Mỗi dòng đại diện cho một ngày quan trắc của một trạm cụ thể trong giai đoạn 2021–2025 (kể cả ngày có dưới 18 giờ sạch hoặc 0 giờ sạch). Đây là bảng sự kiện trạm–ngày, **chưa phải bảng nhãn ô–ngày** (việc tổng hợp nhiều trạm về ô hoặc tạo bảng nhãn ô–ngày phục vụ huấn luyện là bước xử lý dự kiến tiếp theo).
- **Khóa chính:** `(station_id, date_id)` (Không được Null, duy nhất 100%).
- **Khóa ngoại:**
  - `station_id` $\rightarrow$ `dim_station(station_id)`
  - `date_id` $\rightarrow$ `dim_date(date_id)`
  - `grid_id` $\rightarrow$ `dim_grid_1km(grid_id)` (Dùng để nối trạm với ô lưới không gian 1km tương ứng; ánh xạ từ tọa độ trạm ghi nhận trong danh mục khảo sát, lưu ý lịch sử di chuyển trạm nếu có chưa được theo dõi theo thời gian).
- **Quy tắc chất lượng:** Fact lưu mọi trạm–ngày có bản ghi giờ trong phạm vi 2021–2025; ngày ngoài phạm vi vẫn giữ ở staging. `is_valid_day = 1` khi có ít nhất 18 giờ sạch duy nhất; mỗi giờ đóng góp một lần vào trung bình ngày. `is_valid_day` là cờ chất lượng, **không phải bộ lọc fact**. Khi ngày không có giờ sạch nào (`valid_hours_count = 0`), `pm25_raw_mean`, `pm25_daily_min`, `pm25_daily_max` và `pm25_daily_std` nhận giá trị `NULL`. Cột `pm25_calibrated_mean` đã được loại bỏ hoàn toàn khỏi staging daily và fact do chưa có phương pháp hiệu chỉnh được nghiệm thu chính thức.

| Tên cột | Kiểu dữ liệu | Đơn vị | Nullable | Giai đoạn | Ý nghĩa nghiệp vụ |
| :--- | :--- | :--- | :---: | :---: | :--- |
| `station_id` | `VARCHAR` | Mã trạm | **NO** | v1.0 (TV1) | Khóa ngoại xác định trạm quan trắc mặt đất. |
| `date_id` | `INT32` | Số nguyên | **NO** | v1.0 (TV1) | Khóa ngoại xác định ngày đo theo định dạng `YYYYMMDD`. |
| `grid_id` | `VARCHAR` | Mã ô lưới | **NO** | v1.0 (TV1) | Khóa ngoại ô lưới 1km chứa trạm (được ánh xạ từ `dim_station` để bảo đảm tính toàn vẹn 100%). |
| `valid_hours_count` | `INT64` | Giờ | **NO** | v1.0 (TV1) | Số giờ đo hợp lệ duy nhất trong ngày, từ 0 đến 24. |
| `is_valid_day` | `INT32` | Cờ (0/1) | **NO** | v1.0 (TV1) | 1 nếu có ít nhất 18 giờ sạch; ngược lại 0. |
| `pm25_raw_mean` | `DOUBLE` | $\mu\text{g}/\text{m}^3$ | **YES** | v1.0 (TV1) | Trung bình các giờ sạch; NULL khi không có giờ sạch (`valid_hours_count = 0`). |
| `pm25_daily_std` | `DOUBLE` | $\mu\text{g}/\text{m}^3$ | **YES** | v1.0 (TV1) | Độ lệch chuẩn nồng độ $PM_{2.5}$ trong ngày giữa các giờ hợp lệ; NULL khi số giờ hợp lệ < 2. |
| `pm25_daily_min` | `DOUBLE` | $\mu\text{g}/\text{m}^3$ | **YES** | v1.0 (TV1) | Nồng độ $PM_{2.5}$ thấp nhất trong các giờ hợp lệ của ngày; NULL khi không có giờ sạch. |
| `pm25_daily_max` | `DOUBLE` | $\mu\text{g}/\text{m}^3$ | **YES** | v1.0 (TV1) | Nồng độ $PM_{2.5}$ cao nhất trong các giờ hợp lệ của ngày; NULL khi không có giờ sạch. |

---

### 4.5. Bảng Dữ Liệu Sự Kiện Viễn Thám Vệ Tinh Hàng Ngày: `fct_grid_satellite_daily` *(Đề xuất TV2)*
- **Đường dẫn:** `data/core/fct_grid_satellite_daily.parquet`
- **Định dạng:** Apache Parquet
- **Hạt dữ liệu đề xuất (Proposed Grain):** **Ô lưới – Ngày** (`grid_id`, `date_id`).
- **Khóa chính đề xuất:** `(grid_id, date_id)`.
- **Khóa ngoại:**
  - `grid_id` $\rightarrow$ `dim_grid_1km(grid_id)`
  - `date_id` $\rightarrow$ `dim_date(date_id)`
- **Trạng thái:** **ĐỀ XUẤT THIẾT KẾ (PROPOSED - CHỜ TV2 XÁC NHẬN CHÍNH THỨC)**. TV2 có quyền xác nhận hình thức biểu diễn (dạng thưa chỉ chứa ngày có ảnh hay dạng ma trận đầy đủ kèm NULL).

| Tên cột | Kiểu dữ liệu | Đơn vị | Nullable | Giai đoạn | Ý nghĩa nghiệp vụ dự kiến |
| :--- | :--- | :--- | :---: | :---: | :--- |
| `grid_id` | `VARCHAR` | Mã ô lưới | **NO** | v1.0 (TV2) | Mã ô lưới 1km phân tích. |
| `date_id` | `INT32` | Số nguyên | **NO** | v1.0 (TV2) | Ngày quan trắc vệ tinh (`YYYYMMDD`). |
| `aod_047_mean` *(hoặc `aod_550nm_mean`)* | `FLOAT` | Không thứ nguyên | YES | v1.0 (TV2) | Độ dày quang học sol khí AOD từ MODIS MAIAC (đã nhân scale factor `0.001`, dải $[0.0, 3.5]$). `NULL` khi bị mây che. |
| `is_aod_missing_mnar` | `INT32` | Cờ (0/1) | **NO** | v1.0 (TV2) | Cờ chẩn đoán khuyết thiếu phi ngẫu nhiên do mây che (MNAR): `1` nếu AOD bị khuyết do mây/sương mù; `0` nếu quan trắc được bình thường. |
| `no2_tropospheric_mol_m2` | `FLOAT` | $\text{mol}/\text{m}^2$ | YES | v1.0 (TV2) | Mật độ cột khí tầng đối lưu $NO_2$ từ Sentinel-5P (chỉ lấy pixel có $QA \ge 0.75$, dải $[0.0, 0.001]$). |
| `viirs_nightlight_rad` | `FLOAT` | $\text{nW}/\text{cm}^2/\text{sr}$ | YES | v1.0 (TV2) | Bức xạ ánh sáng ban đêm VIIRS DNB (phản ánh hoạt động kinh tế/đô thị ban đêm, dải $[0.0, 300.0]$). |

---

### 4.6. Bảng Dữ Liệu Sự Kiện Khí Tượng Hàng Ngày: `fct_grid_meteo_daily` *(Đề xuất TV3)*
- **Đường dẫn:** `data/core/fct_grid_meteo_daily.parquet`
- **Định dạng:** Apache Parquet
- **Hạt dữ liệu đề xuất (Proposed Grain):** **Ô lưới – Ngày** (`grid_id`, `date_id`).
- **Khóa chính đề xuất:** `(grid_id, date_id)`.
- **Khóa ngoại:**
  - `grid_id` $\rightarrow$ `dim_grid_1km(grid_id)`
  - `date_id` $\rightarrow$ `dim_date(date_id)`
- **Trạng thái:** **ĐỀ XUẤT THIẾT KẾ (PROPOSED - CHỜ TV3 XÁC NHẬN CHÍNH THỨC)**. Dữ liệu gốc từ ~45 điểm pixel ERA5-Land và ~8 điểm pixel BLH, được TV3 nội suy/broadcast sang 3.610 ô lưới.

| Tên cột | Kiểu dữ liệu | Đơn vị | Nullable | Giai đoạn | Ý nghĩa nghiệp vụ dự kiến |
| :--- | :--- | :--- | :---: | :---: | :--- |
| `grid_id` | `VARCHAR` | Mã ô lưới | **NO** | v1.0 (TV3) | Mã ô lưới 1km phân tích. |
| `date_id` | `INT32` | Số nguyên | **NO** | v1.0 (TV3) | Ngày tổng hợp khí tượng địa phương (`YYYYMMDD`). |
| `temp_2m_mean_c` | `FLOAT` | $^\circ\text{C}$ | YES | v1.0 (TV3) | Nhiệt độ không khí trung bình ngày ở độ cao 2m (đổi từ Kelvin: $T_K - 273.15$, dải $[-5.0, 50.0]$). |
| `dewpoint_2m_mean_c` | `FLOAT` | $^\circ\text{C}$ | YES | v1.0 (TV3) | Nhiệt độ điểm sương trung bình ngày ở độ cao 2m (dải $[-10.0, 40.0]$). |
| `rh_mean_pct` | `FLOAT` | $\%$ | YES | v1.0 (TV3) | Độ ẩm tương đối trung bình ngày tính theo công thức Magnus-Tetens từ chuỗi giờ (dải $[0.0, 100.0]$). |
| `precip_daily_mm` | `FLOAT` | mm | YES | v1.0 (TV3) | Tổng lượng mưa ngày đã khử tích lũy (hourly de-accumulated, dải $[0.0, 500.0]$). |
| `wind_speed_scalar_ms` | `FLOAT` | $\text{m}/\text{s}$ | YES | v1.0 (TV3) | Tốc độ gió vô hướng trung bình 24h: $V_{\text{scalar}} = \frac{1}{24}\sum \sqrt{u_{10}^2 + v_{10}^2}$ (dải $[0.0, 35.0]$). |
| `wind_persistence` | `FLOAT` | Tỷ số [0..1] | YES | v1.0 (TV3) | Tỷ số bền vững hướng gió: $P = V_{\text{vector}} / \max(V_{\text{scalar}}, 10^{-4})$ ($0.0 \le P \le 1.0$). |
| `surface_pressure_hpa` | `FLOAT` | hPa | YES | v1.0 (TV3) | Khí áp bề mặt trung bình ngày (đổi từ Pa sang hPa, dải $[900.0, 1050.0]$). |
| `blh_mean_m` | `FLOAT` | Mét (m) | YES | v1.0 (TV3) | Chiều cao lớp biên hành tinh PBLH trung bình ngày từ ERA5 (dải $[10.0, 4000.0]$). |
| `blh_min_m` | `FLOAT` | Mét (m) | YES | v1.0 (TV3) | Chiều cao lớp biên thấp nhất trong ngày (thường vào ban đêm/nghịch nhiệt bức xạ, dải $[10.0, 2000.0]$). |

---

### 4.7. Bảng Chợ Đặc Trưng Không-Thời Gian: `mart_grid_daily_features`
- **Đường dẫn:** `data/marts/mart_grid_daily_features.parquet`
- **Định dạng:** Apache Parquet
- **Hạt dữ liệu (Grain):** **Ô lưới phân tích – Ngày lịch** (`grid_id`, `date_id`).
- **Khóa chính:** `(grid_id, date_id)` (Không được Null, duy nhất 100%).
- **Quy mô ma trận bắt buộc:** **ĐÚNG 6.591.860 DÒNG** ($3.610\text{ ô} \times 1.826\text{ ngày}$).
- **Nguyên tắc Chống Rò rỉ Nhãn (Label Leakage Firewall):**
  > [!IMPORTANT]
  > Bảng này TUYỆT ĐỐI KHÔNG CHỨA bất kỳ cột nào liên quan đến nồng độ bụi $PM_{2.5}$ cùng ngày, số lượng trạm quan trắc mặt đất hay cờ trạm. Cơ chế Whitelist áp dụng nghiêm ngặt trên toàn bộ danh mục cột. Nhãn Ground Truth chỉ được ghép nối riêng rẽ khi huấn luyện mô hình Machine Learning.
- **Quy tắc Ghép nối Không làm rơi dòng (Zero-Drop Left Join):**
  Khung xương được sinh ra từ tích Descartes của các ô thực và các ngày thực:
  $$\text{Spine} = \pi_{\text{grid\_id}}(\sigma_{\text{grid\_id} \neq \text{'grid\_unknown'}}(\text{dim\_grid\_1km})) \times \pi_{\text{date\_id}}(\sigma_{\text{date\_id} \neq -1}(\text{dim\_date}))$$
  Sau đó thực hiện `LEFT JOIN` với bảng đặc trưng tĩnh, `fct_grid_meteo_daily` và `fct_grid_satellite_daily`. Mọi trường thiếu dữ liệu tự động nhận giá trị `NULL`. **Nghiêm cấm mọi thao tác `INNER JOIN` hay lọc `DROP` dòng trên bảng này.**

Danh mục cột chuẩn hóa Whitelist của `mart_grid_daily_features`:
1. **Khóa liên kết:** `grid_id` (`VARCHAR`), `date_id` (`INT32`), `date` (`DATE`).
2. **Khí tượng (từ TV3):** `temp_2m_mean_c`, `dewpoint_2m_mean_c`, `rh_mean_pct`, `precip_daily_mm`, `wind_speed_scalar_ms`, `wind_persistence`, `surface_pressure_hpa`, `blh_mean_m`, `blh_min_m`.
3. **Viễn thám (từ TV2):** `aod_047_mean`, `is_aod_missing_mnar`, `no2_tropospheric_mol_m2`, `viirs_nightlight_rad`.
4. **Đặc trưng tĩnh đô thị & Địa hình (từ TV2):** `osm_primary_road_m`, `osm_road_density_km_km2`, `worldcover_builtup_ratio`, `worldcover_tree_ratio`, `dem_elevation_mean_m`, `dem_slope_mean_deg`.

---

## 5. PHÂN BIỆT HẠT DỮ LIỆU & QUY TẮC GHÉP NỐI CHỐNG NHÂN DÒNG (ANTI-FANOUT)

Trong mô hình hóa không-thời gian, có sự khác biệt căn bản giữa dữ liệu trạm quan trắc mặt đất và dữ liệu ô lưới viễn thám/khí quyển:

```
+---------------------------------------------------------------------------------------+
|  HẠT TRẠM - NGÀY (STATION-DAILY GRAIN)                                                |
|  - Đại diện cho quan trắc điểm (Point measurement) tại một tọa độ vật lý cụ thể.       |
|  - Khóa: (station_id, date_id).                                                       |
|  - Quan hệ Không gian: Nhiều trạm CÓ THỂ cùng nằm trong 1 ô lưới 1km! (1:N)            |
|    Ví dụ: Khu vực nội thành Hoàn Kiếm/Hai Bà Trưng có thể có 2-3 trạm cùng 1 ô lưới.  |
+---------------------------------------------------------------------------------------+
                                         VS
+---------------------------------------------------------------------------------------+
|  HẠT Ô - NGÀY (GRID-DAILY GRAIN)                                                      |
|  - Đại diện cho giá trị trung bình diện tích (Area-averaged surface) trên ô vuông 1km2.|
|  - Khóa: (grid_id, date_id).                                                          |
|  - Quy mô: Đúng 3.610 ô x 1.826 ngày = 6.591.860 bản ghi ma trận toàn cảnh.           |
+---------------------------------------------------------------------------------------+
```

### 5.1. Rủi ro Nhân dòng (Join Fan-out Catastrophe)
Nếu một kỹ sư thiếu cẩn trọng thực hiện phép ghép:
```sql
-- CẢNH BÁO: ĐÂY LÀ PHÉP GHÉP SAI GÂY NHÂN BÙNG NỔ SỐ DÒNG
SELECT m.*, f.pm25_raw_mean
FROM mart_grid_daily_features m
LEFT JOIN fct_ground_truth_daily f 
  ON m.grid_id = f.grid_id AND m.date_id = f.date_id;
```
**Hậu quả:** Đối với các ô lưới có nhiều trạm quan trắc mặt đất cùng hoạt động trong một ngày, phép ghép trên sẽ **nhân đôi hoặc nhân ba số dòng của ô đó**, phá vỡ cấu trúc ma trận 6.591.860 dòng và làm sập toàn bộ các câu lệnh kiểm định toàn vẹn khóa chính.

### 5.2. Hai Kịch bản Ghép nối Chuẩn hóa (Standardized Safe Patterns)

#### Kịch bản A: Tạo Tập Dữ liệu Huấn luyện Máy học (Machine Learning Training View)
Áp dụng cho bảng `mart_station_matched.parquet` **dự kiến**: lấy các trạm–ngày có `pm25_raw_mean IS NOT NULL`, không lọc theo ngưỡng 18 giờ; ghép đặc trưng ô–ngày và thời gian. Không đưa `valid_hours_count`, `is_valid_day` vào tập train; chúng vẫn có trong fact để đối chiếu qua `(station_id, date_id)`. Cột `is_crop_burning_window` không được chọn làm đặc trưng train hoặc estimate.
```sql
-- CHUẨN A: Hạt kết quả bảo toàn đúng theo (station_id, date_id) của trạm
SELECT 
    f.station_id,
    f.date_id,
    f.grid_id,
    f.pm25_raw_mean AS label_pm25,  -- Nhãn thô thử nghiệm; cần lựa chọn ngày và sensor phù hợp
    d.month,
    d.day_of_week,
    d.is_weekend,
    d.hanoi_season,
    m.temp_2m_mean_c,
    m.rh_mean_pct,
    m.wind_speed_scalar_ms,
    m.aod_047_mean,
    m.worldcover_builtup_ratio,
    m.dem_elevation_mean_m
FROM read_parquet('data/core/fct_ground_truth_daily.parquet') f
LEFT JOIN read_parquet('data/marts/mart_grid_daily_features.parquet') m
    ON f.grid_id = m.grid_id AND f.date_id = m.date_id
LEFT JOIN read_parquet('data/core/dim_date.parquet') d
    ON f.date_id = d.date_id
WHERE f.pm25_raw_mean IS NOT NULL;
```
Số dòng đầu ra bằng số trạm–ngày có nhãn khác NULL **nếu** khóa `(grid_id, date_id)` của mart và `date_id` của `dim_date` duy nhất. Cần kiểm tra khóa trước khi ghép và số dòng sau khi ghép. Các đặc trưng có thể NULL sau LEFT JOIN.

**Estimate lịch sử dự kiến:** lấy các ô–ngày cần dự đoán từ `mart_grid_daily_features`, nối `dim_date` qua `date_id` để lấy cùng bốn cột thời gian `month`, `day_of_week`, `is_weekend`, `hanoi_season`. Không đưa nhãn hoặc `is_crop_burning_window` vào X; xử lý thiếu và biến đổi đặc trưng nhất quán với train.

#### Kịch bản B: Tạo Bảng Bản Đồ Phân Tích Khám Phá (EDA Surface Grid View)
Áp dụng cho bảng `mart_grid_daily_eda.parquet`: Cần biểu diễn giá trị nồng độ ô lưới trên nền toàn bộ 6.591.860 dòng. Bắt buộc phải **tổng hợp (aggregate) các trạm trong cùng ô trước khi join**:
```sql
-- CHUẨN B: Gom nhóm các trạm cùng ô trước khi LEFT JOIN vào khung xương
WITH station_daily_aggregated AS (
    SELECT 
        grid_id,
        date_id,
        COUNT(DISTINCT station_id) AS active_stations_in_cell,
        ROUND(AVG(pm25_raw_mean), 2) AS grid_cell_pm25_mean
    FROM read_parquet('data/core/fct_ground_truth_daily.parquet')
    GROUP BY grid_id, date_id
)
SELECT 
    m.*,
    COALESCE(s.active_stations_in_cell, 0) AS station_count,
    s.grid_cell_pm25_mean
FROM read_parquet('data/marts/mart_grid_daily_features.parquet') m
LEFT JOIN station_daily_aggregated s
    ON m.grid_id = s.grid_id AND m.date_id = s.date_id;
```
*Số dòng đầu ra luôn được bảo toàn tuyệt đối bằng đúng $|S| = 6.591.860\text{ dòng}$.*

---

## 6. PHÂN TÁCH PHẦN ĐÃ TRIỂN KHAI VÀ THIẾT KẾ ĐỀ XUẤT MỞ RỘNG

Để đảm bảo tính trung thực kỹ thuật cao nhất trong tài liệu kiến trúc, phần này phân định rõ ranh giới giữa những gì **đã chạy thực tế trong mã nguồn** và những gì **đang ở mức đề xuất kiến trúc (Proposed Specifications)**:

### 6.1. Các Thành phần Đã Triển Khai Thực Tế (Implemented Baseline)
1. **Khung xương Lưới 1km:** `dim_grid_1km.parquet` v1.0 (3.611 dòng, 6 cột, thuật toán `intersects` với ranh giới HDX COD-AB 2025, đóng băng SHA-256).
2. **Trục Ngày 5 Năm:** `dim_date.parquet` (1.827 dòng, 9 cột, phân loại mùa Hà Nội và cửa sổ đốt rơm rạ, khóa `-1`).
3. **Danh mục Trạm:** `dim_station.parquet` (44 dòng gồm 43 trạm theo ảnh chụp khảo sát OpenAQ + 1 trạm ngoại lệ `station_unknown`, phân loại Tier 1/Tier 2, ánh xạ tọa độ sang `grid_id`).
4. **Chuỗi Giờ Staging:** `stg_ground_truth_hourly.parquet` (chọn revision, chuẩn hóa thời gian, chưa gắn cờ QC).
5. **Gom Ngày Mặt Đất:** QC từng sensor–giờ trong bộ nhớ, sau đó tính trung bình ngày và gắn cờ `is_valid_day = (valid_hours_count >= 18)`. Cờ QC giờ không được lưu trong staging hourly.
6. **Fact Mặt Đất:** `fct_ground_truth_daily.parquet` (giữ mọi trạm–ngày có bản ghi trong phạm vi 2021–2025, gắn cờ chất lượng 18 giờ, không lọc bỏ ngày thiếu giờ).
7. **Hạ tầng Ghi/Đọc:** `src/common/io_parquet.py` (ghi nguyên tử `atomic_write_parquet`) và `src/common/hashing.py` (băm SHA-256 `compute_row_hash`).

### 6.2. Các Thiết Kế Đề Xuất Mở Rộng Cần Bổ Sung (Proposed Architectural Enhancements)
Các cơ chế sau đã được thiết kế trong tài liệu kiến trúc nhưng **chưa được mã hóa đầy đủ trong code hiện tại**:

1. **Quản trị Lô Nạp (Ingestion Batch Management):**
   - *Đề xuất:* Thiết lập bảng/file manifest ghi nhận từng đợt nạp: `data/manifests/ingestion_batches.json` (chứa `batch_id`, `source_name`, `started_at_utc`, `completed_at_utc`, `status = SUCCESS | PARTIAL | FAILED`, `records_ingested`).
2. **Truy vết Phả hệ Cấp Dòng (Batch-Row Lineage):**
   - *Đề xuất:* Bổ sung vào các bảng Raw và Staging 3 trường siêu dữ liệu chuẩn doanh nghiệp:
     - `_batch_id`: Mã UUID của lần nạp dữ liệu.
     - `_ingested_at_utc`: Thời điểm ghi nhận bản ghi (chuẩn ISO-8601 UTC).
     - `_source_file`: Đường dẫn file gốc hoặc tên phân vùng API.
3. **Lưu trữ Kết Quả Kiểm Định Chất Lượng (Quality Results Logging):**
   - *Đề xuất:* Thay vì chỉ in báo cáo ra màn hình terminal từ `contract_verifier.py`, cần tự động kết xuất kết quả kiểm tra từng lần chạy vào artifact `data/manifests/quality_audit_log.parquet` (hoặc JSON) để lưu trữ lịch sử kiểm định phục vụ đối soát CI/CD.
4. **Bảng Ánh Xạ Khử Trùng & Bản Ghi Bị Thay Thế (Duplicate & Replacement Audit Mapping):**
   - *Đề xuất:* Khi API OpenAQ hoặc Copernicus cập nhật dữ liệu hồi tố (re-analysis revision), hệ thống cần một bảng ghi nhận lịch sử thay thế: `data/staging/stg_revision_audit.parquet` lưu vết cặp `(business_key, old_row_hash, new_row_hash, replaced_at_utc)`.

---

## 7. ĐIỀU HƯỚNG TÀI LIỆU LIÊN QUAN

- Để tra cứu các ràng buộc kiểm định, tiêu chuẩn nghiệm thu từng trường dữ liệu, quy định xử lý bất thường và các quyết định kỹ thuật đang chờ TV2/TV3 chốt, vui lòng đọc:  
  👉 **[Hợp đồng Dữ liệu Tổng thể: docs/data_contract.md](./data_contract.md)**
- Để tra cứu danh mục mã lệnh thực thi của dự án: Xem [run.py](../run.py).
- Để tra cứu phân công công việc chi tiết và cẩm nang hành động của từng thành viên: Xem [Cẩm nang Thực thi & Bàn giao (docs/guide.md)](./guide.md).

---

## 8. BẢN GHI QUYẾT ĐỊNH KIẾN TRÚC (ARCHITECTURAL DECISION RECORDS - ADR)

### ADR-01: Phân tầng cờ QC chuỗi giờ và xử lý dữ liệu không hợp lệ
- **Ngữ cảnh:** Chuỗi giờ PM2.5 từ OpenAQ có thể chứa giá trị âm, cực trị do lỗi phần cứng, giá trị kẹt số liên tục (flatline), dữ liệu thiếu (`NULL`, `NaN`), giá trị vô hạn (`Inf`, `-Inf`) hoặc mốc thời gian hỏng.
- **Quyết định:**
  1. Phân tầng cờ QC theo độ ưu tiên:
     - `qc_flag = 1`: Giá trị âm (`pm25 < 0`), không hữu hạn (`NaN`, `Inf`, `-Inf`), Null hoặc timestamp không hợp lệ. Tuyệt đối không được tính là giờ sạch.
     - `qc_flag = 2`: Vượt ngưỡng vật lý (`pm25 > 1000 ug/m3`).
     - `qc_flag = 3`: Kẹt số liên tục thực tế $\ge 6$ giờ liên tiếp (khoảng cách giữa các mốc đo nằm trong khoảng 3480–3720s). Nếu có khoảng cách thời gian gãy đoạn (> 1h), chuỗi đếm flatline bị ngắt để tránh gán cờ nhầm.
     - `qc_flag = 0`: Hợp lệ (Passed).
  2. Bộ lọc Hampel (`is_hampel_outlier`) được tính trong bộ nhớ khi tạo daily; không tự động loại giờ. QC và cờ Hampel không được ghi vào staging hourly.
- **Trạng thái:** Đã triển khai và có Unit Test chứng minh.

### ADR-02: PM2.5 trung bình theo các giờ hợp lệ trong ngày
- **Ngày quyết định:** 2026-10-27. **Trạng thái:** Đã triển khai cho fact; lựa chọn nhãn train được ghi tại ADR-05.
- **Ngữ cảnh:** Dự án xây dựng bản đồ PM2.5 lịch sử theo ngày Hà Nội. Một ngày trạm có thể thiếu giờ; cần giữ dữ liệu đó để kiểm toán và tránh nhầm giá trị của một phần ngày với trung bình đầy đủ 24 giờ.
- **Quyết định:**
  1. Thời điểm đo được lưu theo UTC; xác định ngày và giờ phân tích theo `Asia/Ho_Chi_Minh`.
  2. Với mỗi `(station_id, date_id, hour_local)`, chỉ sử dụng phép đo có `qc_flag = 0` và PM2.5 hữu hạn; nếu có nhiều phép đo sạch cùng giờ, implementation hiện tại lấy trung bình chúng thành một giá trị giờ. Chưa có quy tắc ưu tiên sensor được phê duyệt.
  3. `pm25_raw_mean` là trung bình cộng các giá trị giờ sạch trong ngày, mỗi giờ một trọng số, làm tròn 2 chữ số thập phân. Đây là giá trị thô sau QC, không phải giá trị đã hiệu chỉnh. `valid_hours_count` là số giờ sạch duy nhất dùng trong phép tính.
  4. Ngày có 1–17 giờ sạch vẫn có trung bình các giờ quan sát và được giữ trong staging và fact. Không tự ngoại suy thành trung bình đủ 24 giờ. Ngày có bản ghi nhưng không có giờ sạch được giữ với `valid_hours_count = 0` và `pm25_raw_mean = NULL`. Ngày hoàn toàn không có bản ghi giờ không tự tạo dòng.
  5. `is_valid_day = 1` khi có ít nhất 18 giờ sạch, ngược lại bằng `0`. Đây là cờ chất lượng, không phải điều kiện lọc fact hoặc bộ lọc nhãn train theo ADR-05.
  6. Fact giữ các trạm-ngày có bản ghi trong phạm vi dự án 2021–2025; ngày ngoài phạm vi vẫn ở staging. Khóa fact là `(station_id, date_id)`, `grid_id` được ánh xạ từ danh mục trạm hiện tại.
- **Hệ quả:** Trung bình dựa trên ít giờ có thể lệch so với trung bình 24 giờ, nhất là khi giờ thiếu không phân bố đều. Cần giữ số giờ và cờ chất lượng khi phân tích. Vị trí trạm theo lịch sử cần được xác minh nếu trạm di chuyển.
- **Tham chiếu triển khai:** `src/features/build_ground_truth_daily.py`; kiểm thử trong `tests/unit/test_qc_and_aggregation.py`.

### ADR-03: Ngữ nghĩa hiệu chuẩn PM2.5 (Calibration Semantics)
- **Ngữ cảnh:** Trước đây, code gán cào bằng toàn bộ Tier 1 hoặc gán `openaq_2539` là trạm tham chiếu FEM. Tuy nhiên, `openaq_2539` đã ngừng hoạt động từ năm 2016, và trong giai đoạn 2021–2025 chưa có trạm nào có bằng chứng kiểm định thiết bị FEM và khoảng thời gian áp dụng mô hình hiệu chuẩn được nghiệm thu chính thức trong repo.
- **Quyết định:**
  1. Bỏ cột hiệu chỉnh khỏi staging daily và fact vì chưa có phương pháp hiệu chỉnh được xác minh.
  2. Giữ `pm25_raw_mean` là trung bình thô sau QC; không coi là đã hiệu chỉnh.
  3. Có thể bổ sung dữ liệu hiệu chỉnh sau khi xác minh phương pháp, phiên bản và phạm vi sensor; lựa chọn nhãn train chính thức cần nhóm phê duyệt.
- **Trạng thái:** Đã triển khai trong code và cập nhật đồng bộ trong Data Contract.

### ADR-04: Khóa tệp đồng thời và cơ chế nạp lại an toàn (Safe Re-run & Idempotency)
- **Ngữ cảnh:** Quá trình tải dữ liệu OpenAQ có thể bị ngắt giữa chừng, hoặc cần chạy lại khi nguồn OpenAQ cập nhật dữ liệu lịch sử ($A \rightarrow B \rightarrow A$).
- **Quyết định:**
  1. Thứ tự nạp: Ingestion bắt buộc phải ghi dữ liệu thành công vào file Parquet đích trước khi cập nhật trạng thái `SUCCESS` vào manifest. Nếu ghi file thất bại, manifest lập tức ghi nhận `FAILED` và re-raise lỗi.
  2. Cơ chế khóa file: `file_concurrency_lock` ghi nhận PID của tiến trình và kiểm tra trạng thái sống của tiến trình (`is_process_alive`). Tuyệt đối không tự ý bẻ khóa nếu tiến trình sở hữu vẫn đang hoạt động. Giới hạn: Đây là advisory lock đơn máy, quy trình ingestion thiết kế tối ưu cho chạy tuần tự (single-process / sequential).
  3. Khử trùng revision: Nhận diện bộ khóa nghiệp vụ `(station_id, sensor_id, datetime_utc)` và so khớp với mã băm nội dung `_row_hash` của phiên bản mới nhất hiện tại. Hỗ trợ đầy đủ chuỗi revision $A \rightarrow B \rightarrow A$ mà không làm mất bản cập nhật và không gây trùng lặp khi chạy lại với cờ `--force`.
- **Trạng thái:** Đã triển khai và có Unit Test chứng minh.

### ADR-05: Chọn nhãn trạm–ngày và ghép thuộc tính ngày
- **Trạng thái:** Quyết định của TV1 cho thiết kế train và estimate; các mart chưa triển khai.
- **Nhãn train:** Từ fact chọn `pm25_raw_mean IS NOT NULL`, kể cả ngày dưới 18 giờ; giữ `station_id`, `grid_id`, `date_id` để truy xuất. Không đưa `valid_hours_count`, `is_valid_day` vào tập train; khi cần đánh giá chất lượng, nối lại fact theo `(station_id, date_id)`.
- **Đặc trưng thời gian:** Nối `dim_date` qua `date_id` để lấy `month`, `day_of_week`, `is_weekend`, `hanoi_season` cho cả train và estimate. Không chọn `is_crop_burning_window` làm đầu vào mô hình; cột này vẫn tồn tại trong `dim_date`.
- **Ghép đặc trưng:** Nối mart đặc trưng qua `(grid_id, date_id)`, kiểm tra khóa duy nhất trước join; không đưa PM2.5 làm đặc trưng đầu vào.
- **Giới hạn:** Dòng có ít giờ chỉ phản ánh các giờ quan sát, không bảo đảm đại diện đủ 24 giờ. Báo cáo độ đầy đủ và chất lượng sensor khi đánh giá mô hình.
