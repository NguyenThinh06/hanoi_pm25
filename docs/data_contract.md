# HỢP ĐỒNG DỮ LIỆU TỔNG THỂ (DATA CONTRACT SPECIFICATION)
## DỰ ÁN HANOI_PM25: XÂY DỰNG SPATIO-TEMPORAL DATA LAKEHOUSE (2021–2025)

**Cơ quan quản trị:** Ban Kiến trúc Dữ liệu & Đảm bảo Chất lượng (Data Architecture & Quality Board)  
**Phiên bản Contract:** `v3.1.0-draft`  
**Ngày cập nhật:** 2026-10-26  
**Trạng thái pháp lý:** **DRAFT / UNDER REVIEW (BẢN THẢO ĐỀ XUẤT – CHỜ CÁC THÀNH VIÊN XÁC NHẬN)**  
> [!IMPORTANT]
> **Tuyên bố về Thẩm định và Phê duyệt:**  
> Bản hợp đồng này **CHƯA ĐƯỢC CHÍNH THỨC PHÊ DUYỆT (NOT RATIFIED)**. Tài liệu phản ánh hiện trạng đã hoàn thành của TV1 và thiết lập các điều kiện nghiệm thu kỹ thuật đối với các thành phần dữ liệu đang phát triển của TV2 và TV3.  
> **Người cần thẩm định và ký duyệt (Required Sign-offs):**
> 1. `hunganh` (Thành viên 2 — Static Features & Satellite Owner): Xác nhận hợp đồng bàn giao vệ tinh và đặc trưng tĩnh.
> 2. `minh` (Thành viên 3 — Meteorology Owner): Xác nhận hợp đồng bàn giao tái phân tích khí tượng và bảng độ ẩm tương đối ($RH$).
> 3. `ngthinh06` (Data Architect & Spatial Lead — TV1): Ký duyệt nghiệm thu kỹ thuật toàn diện sau khi TV2 và TV3 hoàn tất phản biện.
>
> Chi tiết cấu trúc lược đồ các bảng: Xem [Đặc tả Lược đồ Dữ liệu (docs/schema.md)](./schema.md).

---

## 1. MỤC TIÊU VÀ NGUYÊN TẮC BẤT BIẾN (INVARIANTS)

### 1.1. Mục tiêu Hợp đồng
Hợp đồng dữ liệu (Data Contract) này xác lập các cam kết chất lượng dịch vụ dữ liệu (SLA), điều kiện nghiệm thu, giới hạn vật lý, hạt dữ liệu và quy tắc kiểm thử tự động giữa các thành viên sản xuất (Producers) và tiêu thụ (Consumers) dữ liệu trong dự án HANOI_PM25.

### 1.2. Các Bất biến Kỹ thuật Cốt lõi (Architectural Invariants)
1. **Kiến trúc Zero-RDBMS:** Toàn bộ dữ liệu hồ chứa được lưu trữ dưới dạng file Apache Parquet (và GeoParquet 1.1.0 cho hình học không gian). Tính toán hoàn toàn bằng DuckDB in-process và Polars. Nghiêm cấm cài đặt hoặc phụ thuộc vào máy chủ RDBMS (PostgreSQL/PostGIS, MySQL).
2. **Khung Không gian Bất biến:**
   - Hệ quy chiếu: **VN-2000 / UTM Zone 48N (`EPSG:3405`)**, đơn vị đo: mét.
   - Ranh giới địa giới: `data/reference/hanoi_boundary.geojson` (nguồn HDX COD-AB v02, GSO Vietnam, đóng băng mã băm SHA-256 `d8194abcc1d89eadd836941a750ae339f398a9b2e5e9d2428d0f96f1f2bd1f77`).
   - Lưới ô vuông $1.000\text{ m} \times 1.000\text{ m}$, thuật toán cắt chọn tất cả ô có phần giao `intersects` với ranh giới.
   - Số ô phân tích thực tế: **$N_{\text{GRID}} = 3.610\text{ ô}$**. Bảng `dim_grid_1km` có đúng **$3.611\text{ dòng}$** (bao gồm 1 ô ngoại lệ `grid_unknown`).
3. **Trục Thời gian Bất biến:**
   - Dải thời gian: 5 năm liên tục từ `2021-01-01` đến `2025-12-31` theo giờ địa phương Hà Nội (`Asia/Ho_Chi_Minh`, `UTC+7`).
   - Định dạng khóa ngày: `date_id` là số nguyên `YYYYMMDD`, giá trị ngoại lệ là `-1`.
   - Số ngày phân tích thực tế: **$N_{\text{DAYS}} = 1.826\text{ ngày}$** (bao gồm ngày nhuận `2024-02-29`). Bảng `dim_date` có đúng **$1.827\text{ dòng}$** (gồm 1 dòng ngoại lệ `date_id = -1`).
4. **Quy mô Khung xương Phân tích (Analysis Spine Matrix):**
   - Tích Descartes chính xác giữa các ô phân tích và ngày phân tích:
     $$|S| = N_{\text{GRID}} \times N_{\text{DAYS}} = 3.610 \times 1.826 = 6.591.860\text{ dòng}$$
   - Khung này **loại trừ cả hai dòng ngoại lệ** (`grid_id != 'grid_unknown'` và `date_id != -1`).
   - Bảng Chợ Đặc trưng `mart_grid_daily_features.parquet` bắt buộc phải có **đúng 6.591.860 dòng**.
5. **Rào chắn Chống Rò rỉ Nhãn (Label Leakage Firewall):**
   - Bảng Chợ Đặc trưng `mart_grid_daily_features.parquet` tuyệt đối tuân thủ cơ chế Whitelist. Nghiêm cấm 100% sự hiện diện của các cột nồng độ $PM_{2.5}$ cùng ngày hoặc biến dẫn xuất từ trạm quan trắc mặt đất.

---

## 2. QUY CHUẨN THỜI GIAN VÀ MÚI GIỜ (TEMPORAL & TIMEZONE STANDARDS)

Toàn bộ quy trình nạp, làm sạch và tổng hợp dữ liệu phải tuân thủ nghiêm ngặt các tiêu chuẩn thời gian sau:

### 2.1. Múi giờ Cơ sở: `Asia/Ho_Chi_Minh` (`UTC+7`)
- Mọi quan niệm về "Ngày", "Trung bình ngày", "Mùa", "Cửa sổ đốt rơm rạ" trong dự án đều được tính toán theo múi giờ địa phương Hà Nội (`Asia/Ho_Chi_Minh`, `UTC+7`, không có giờ mùa hè DST).
- Khóa thay thế ngày `date_id = CAST(STRFTIME(date_local, '%Y%m%d') AS INT32)`.

### 2.2. Quy tắc Chuyển đổi UTC và Cửa sổ Nạp Mở rộng (UTC Window Expansion)
Do độ lệch thời gian giữa UTC và Hà Nội là 7 giờ, ngày địa phương `2021-01-01 00:00:00 ICT` bắt đầu từ `2020-12-31 17:00:00 UTC`.
- **Rủi ro mất dữ liệu:** Nếu kịch bản Ingestion chỉ gửi request lấy dữ liệu từ `2021-01-01 00:00:00 UTC`, ngày đầu tiên `2021-01-01` tại Hà Nội sẽ bị thiếu 17 giờ đầu (chỉ còn 7 giờ đo), dẫn đến việc bị loại bỏ hoàn toàn bởi quy tắc kiểm định $\ge 18\text{h}$ hợp lệ.
- **Quy định bắt buộc:** Toàn bộ pipeline nạp dữ liệu thô (OpenAQ, ERA5, Viễn thám) phải áp dụng **cửa sổ truy vấn UTC mở rộng**:
  - Thời điểm bắt đầu truy vấn: `"2020-12-31T16:00:00Z"`
  - Thời điểm kết thúc truy vấn: `"2026-01-01T08:00:00Z"`
- Tầng Staging có trách nhiệm chuyển đổi thời gian sang `datetime_local = datetime_utc + INTERVAL 7 HOUR` trước khi trích xuất `date_id` và lọc đúng cửa sổ ngày từ `20210101` đến `20251231`.

### 2.3. Quy chuẩn Tổng hợp Ngày Địa phương (Daily Aggregation Rules)
1. **Quan trắc trạm mặt đất:**
   - Ngày đo hợp lệ bắt buộc phải có **$\text{valid\_hours\_count} \ge 18\text{ giờ}$** (có `qc_flag = 0`).
   - Các ngày có $< 18\text{h}$ chỉ được lưu ở tầng Staging (`is_valid_day = 0`), **tuyệt đối không được nạp vào `fct_ground_truth_daily`**.
2. **Khí tượng ERA5-Land & BLH:**
   - Lượng mưa: Phải khử tích lũy chuỗi giờ trước: $\text{precip\_h} = \max(0.0, \text{tp}_h - \text{tp}_{h-1})$. Sau đó tính tổng lượng mưa 24 giờ của ngày địa phương: $\text{precip\_daily\_mm} = \sum_{h=1}^{24} \text{precip\_h}$.
   - Tốc độ gió: Tính vận tốc tức thời từng giờ $w_h = \sqrt{u_{10,h}^2 + v_{10,h}^2}$, sau đó lấy trung bình vô hướng 24h: $V_{\text{scalar}} = \frac{1}{24}\sum_{h=1}^{24} w_h$.
   - Độ ẩm tương đối: Tính $RH_h$ từng giờ bằng công thức Magnus-Tetens, sau đó lấy trung bình 24h của ngày địa phương.
3. **Viễn thám Vệ tinh (MODIS, Sentinel-5P):**
   - Vệ tinh quỹ đạo cực bay qua Hà Nội vào các khung giờ nhất định trong ngày (ví dụ MODIS Terra ~10:30 sáng, Aqua ~13:30 chiều, Sentinel-5P ~13:30 chiều).
   - Timestamp thời điểm chụp ảnh (Overpass UTC) phải được chuyển đổi sang ngày địa phương Hà Nội tương ứng.

---

## 3. QUẢN TRỊ DỮ LIỆU THIẾU, CỜ QC VÀ RÀNG BUỘC VẬT LÝ

Hệ thống thiết lập sự phân biệt rạch ròi giữa 3 trạng thái của dữ liệu quan trắc:

### 3.1. Phân biệt Rạch ròi 3 Trạng thái Đo đạc (Tri-state Data Logic)
1. **Không có quan trắc (No Observation / Missing):**
   - Xảy ra khi trạm ngừng hoạt động, vệ tinh bị lệch quỹ đạo hoặc dữ liệu chưa được công bố.
   - **Biểu diễn:** Bắt buộc lưu trữ là giá trị `NULL`.
   - **Xử lý:** Tuyệt đối không được thay thế bằng giá trị `0` hay số âm (`-999`, `-1`) trong các cột số đo.
2. **Quan trắc bị loại bỏ qua Kiểm soát Chất lượng (QC Flagged / Rejected):**
   - Xảy ra khi thiết bị ghi nhận số liệu nhưng vi phạm các điều kiện kỹ thuật (số âm vô lý, vượt ngưỡng vật lý $> 1.000\,\mu\text{g}/\text{m}^3$, kẹt cảm biến flatline $\ge 6\text{h}$, hoặc ngoại lai Hampel).
   - **Xử lý ở Staging:** Giữ nguyên bản ghi chuỗi giờ, gắn cờ `qc_flag > 0` và `is_hampel_outlier = 1`.
   - **Xử lý ở Core/Fact:** Loại bỏ các giờ bị gắn cờ khỏi phép tính trung bình ngày. Nếu số giờ sạch $< 18\text{h}$, toàn bộ ngày trạm đó bị loại khỏi `fct_ground_truth_daily`.
3. **Giá trị đo bằng 0 thực tế (True Zero Measurement):**
   - Xảy ra khi hiện tượng tự nhiên bằng không (ví dụ ngày hoàn toàn không có mưa `precip_daily_mm = 0.0`, tốc độ gió lặng `wind_speed_scalar_ms = 0.0`).
   - **Biểu diễn:** Lưu trữ chính xác số `0.0`.
   - **Xử lý:** Nghiêm cấm mọi hành vi chuyển đổi số `0.0` thành `NULL` hoặc ngược lại.

### 3.2. Chính sách Mây che MNAR đối với Viễn thám (Missing Not At Random Policy)
- Mùa đông Hà Nội (tháng 11 đến tháng 2) thường xuyên có mây tầng thấp và sương mù dày đặc che khuất bề mặt, khiến cảm biến MODIS MAIAC không thể đo được sol khí AOD.
- **Quy tắc cấm kỵ:** **NGHIÊM CẤM TUYỆT ĐỐI VIỆC NỘI SUY KHÔNG GIAN HOẶC ĐIỀN TRUNG BÌNH (NO BLIND IMPUTATION)** đối với giá trị AOD trong những ngày bị mây che, vì mây che đi kèm với độ ẩm cao và điều kiện khí tượng tích tụ ô nhiễm đặc thù (vi phạm giả thiết Missing At Random).
- **Quy định:**
  - Cột `aod_047_mean` giữ nguyên giá trị `NULL`.
  - Cột cờ chẩn đoán `is_aod_missing_mnar` gán giá trị `1` (nếu có đo được thì gán `0`).

### 3.3. Bảng Ràng buộc Phạm vi Giá trị Vật lý và Cách Xử lý Vi phạm (Physical Ranges & SLA)

| Tên trường dữ liệu | Bảng mục tiêu | Đơn vị đo | Miền giá trị hợp lệ | Mức độ cảnh báo | Biện pháp xử lý vi phạm |
| :--- | :--- | :---: | :---: | :---: | :--- |
| `valid_hours_count` | `fct_ground_truth_daily` | Giờ | $[18, 24]$ | **BLOCKER** | Drop bản ghi khỏi bảng Fact; ghi nhận lỗi vào log. |
| `pm25_raw_mean` | `fct_ground_truth_daily` | $\mu\text{g}/\text{m}^3$ | $[0.0, 800.0]$ | **CRITICAL** | Nếu $< 0$: Lỗi nạp. Nếu $> 800$: Đánh cờ nghi vấn trạm cháy/sự cố. |
| `pm25_calibrated_mean`| `fct_ground_truth_daily`| $\mu\text{g}/\text{m}^3$ | $[0.0, 800.0]$ | **CRITICAL** | Kiểm tra lại hệ số Köhler $C(RH)$. Bắt buộc $\le \text{pm25\_raw\_mean}$. |
| `temp_2m_mean_c` | `fct_grid_meteo_daily` | $^\circ\text{C}$ | $[-5.0, 50.0]$ | **BLOCKER** | Lỗi chuyển đổi Kelvin ($T - 273.15$); từ chối nhận batch. |
| `dewpoint_2m_mean_c` | `fct_grid_meteo_daily` | $^\circ\text{C}$ | $[-10.0, 40.0]$ | **CRITICAL** | Bắt buộc $\le \text{temp\_2m\_mean\_c} + 0.1$. |
| `rh_mean_pct` | `fct_grid_meteo_daily` | $\%$ | $[0.0, 100.0]$ | **BLOCKER** | Kẹp trần `min(100.0, max(0.0, rh))` và cảnh báo công thức Tetens. |
| `precip_daily_mm` | `fct_grid_meteo_daily` | mm | $[0.0, 600.0]$ | **BLOCKER** | Nếu $< 0$: Lỗi khử tích lũy. Nếu $> 600$: Xác minh bão lịch sử. |
| `wind_speed_scalar_ms`| `fct_grid_meteo_daily` | $\text{m}/\text{s}$ | $[0.0, 45.0]$ | **BLOCKER** | Nếu $< 0$ hoặc $> 45$: Lỗi tính toán vector gió. |
| `wind_persistence` | `fct_grid_meteo_daily` | Tỷ số | $[0.0, 1.0]$ | **BLOCKER** | Tỷ số $V_{\text{vector}} / V_{\text{scalar}}$ bắt buộc nằm trong $[0, 1]$. |
| `surface_pressure_hpa`| `fct_grid_meteo_daily`| hPa | $[900.0, 1050.0]$| **BLOCKER** | Nếu $< 900$: Sai đơn vị Pa sang hPa. |
| `blh_mean_m` | `fct_grid_meteo_daily` | Mét | $[10.0, 4500.0]$ | **CRITICAL** | Lớp biên hành tinh không thể âm hoặc vượt tầng đối lưu thấp. |
| `aod_047_mean` | `fct_grid_satellite_daily` | Vô thứ nguyên| $[0.0, 3.5]$ | **CRITICAL** | Kiểm tra scale factor `0.001` của MODIS MAIAC. |
| `is_aod_missing_mnar`| `fct_grid_satellite_daily`| Cờ (0/1) | $\{0, 1\}$ | **BLOCKER** | Nhất quán: nếu `aod IS NULL` thì cờ bắt buộc $= 1$. |
| `no2_tropospheric_mol_m2`| `fct_grid_satellite_daily`| $\text{mol}/\text{m}^2$| $[0.0, 0.001]$ | **WARNING** | Lọc theo cờ $QA \ge 0.75$ của Sentinel-5P. |
| `worldcover_builtup_ratio`| `dim_grid_1km` | Tỷ lệ | $[0.0, 1.0]$ | **BLOCKER** | Tỷ lệ diện tích bắt buộc thuộc $[0, 1]$. |
| `dem_elevation_mean_m`| `dim_grid_1km` | Mét | $[-10.0, 1400.0]$| **BLOCKER** | Đỉnh Ba Vì cao nhất Hà Nội $\approx 1.281\text{ m}$. |

---

## 4. QUY TRÌNH NẠP LŨY ĐẲNG, KHỬ TRÙNG VÀ TRUY VẾT BẢN GHI (INGESTION & LINEAGE)

### 4.1. Phân biệt Khóa Nghiệp vụ và Mã Băm Nội dung
- **Khóa nghiệp vụ (Business Key):** Xác định thực thể đo lường logic duy nhất:
  - Chuỗi giờ trạm: `(station_id, datetime_utc)`.
  - Chuỗi ngày ô lưới: `(grid_id, date_id)`.
- **Mã băm nội dung (`_row_hash`):** Là chuỗi băm SHA-256 từ toàn bộ các giá trị đo đạc trong dòng:
  $$\text{\_row\_hash} = \text{SHA-256}(\text{col}_1 \parallel "|" \parallel \text{col}_2 \parallel \dots \parallel \text{col}_n)$$
- **Quy tắc:**
  - Nếu bản ghi mới có cùng *Business Key* VÀ cùng `_row_hash`: Đây là bản ghi trùng lặp thuần túy $\rightarrow$ Bỏ qua không nạp lại (Skip).
  - Nếu bản ghi mới có cùng *Business Key* nhưng KHÁC `_row_hash`: Đây là bản ghi **hiệu chỉnh / cập nhật phiên bản (Revision)** từ cơ quan phát hành dữ liệu $\rightarrow$ Không được ghi đè âm thầm, phải xử lý theo quy tắc hòa giải tất định.

### 4.2. Hòa giải Revision Tất định tại Tầng Staging
Tầng Raw lưu trữ append-only mọi revision gửi về. Khi làm sạch tại tầng Staging, hệ thống áp dụng hàm cửa sổ phân hạng xác định duy nhất:
```sql
WITH ranked_revisions AS (
    SELECT *,
        ROW_NUMBER() OVER(
            PARTITION BY station_id, datetime_utc 
            ORDER BY ingested_at DESC, _batch_id DESC, _row_hash DESC
        ) AS rank_order
    FROM read_parquet('data/raw/ground_truth/source=openaq/**/*.parquet')
)
SELECT * EXCLUDE(rank_order)
FROM ranked_revisions
WHERE rank_order = 1;
```
*Tiêu chí chọn bản ghi:* Ưu tiên thời điểm nạp mới nhất (`ingested_at DESC`), nếu trùng thì ưu tiên mã đợt nạp (`_batch_id DESC`), nếu vẫn trùng thì sắp xếp theo mã băm (`_row_hash DESC`) để đảm bảo tính **tất định 100% (Deterministic)**.

### 4.3. Quản lý Trạng thái Đợt Nạp (Ingestion Batch Lifecycle)
Hệ thống quản lý trạng thái nạp dữ liệu theo 3 mức độ, **tuyệt đối không coi có 1 dòng dữ liệu là đã nạp hoàn tất**:
1. `FAILED`: Tiến trình tải dữ liệu gặp lỗi mạng, lỗi timeout hoặc API Key hết hạn; 0 bản ghi được thêm vào.
2. `PARTIAL`: Tiến trình nạp bị ngắt giữa chừng, chỉ tải được một phần các phân vùng thời gian/không gian. Đợt nạp này bị cô lập, không được phép kích hoạt trigger chạy tầng Staging.
3. `SUCCESS`: Toàn bộ các phân vùng theo kế hoạch nạp đã được tải đầy đủ, vượt qua kiểm tra mã băm SHA-256 và kích thước file $> 0$. Chỉ khi đạt `SUCCESS` thì cờ nạp mới chuyển sang sẵn sàng cho Staging.

---

## 5. ĐẶC TẢ NGHIỆM THU CHI TIẾT BÀN GIAO CHO TV2 VÀ TV3

Phần này quy định các cam kết bàn giao đối với hai bảng Fact chưa hoàn thành. Mọi thiết kế ở đây được xây dựng dựa trên tài liệu Playbook và cần được TV2 và TV3 rà soát, phản biện và xác nhận chính thức:

### 5.1. Bàn giao của Thành viên 2 (`hunganh` — Viễn thám & Đặc trưng tĩnh)

#### 1. Bàn giao 1: Bảng chiều Lưới 1km đủ 15 biến tĩnh (`dim_grid_1km` v1.1)
- **Đường dẫn bàn giao:** `data/core/dim_grid_1km.parquet` (phiên bản v1.1).
- **Điều kiện tiên quyết:** TV1 đã bàn giao `dim_grid_1km.parquet` v1.0 (3.611 dòng, GeoParquet EPSG:3405).
- **Tiêu chí nghiệm thu:**
  - Giữ nguyên toàn bộ 3.611 dòng và các cột v1.0 từ TV1.
  - Bổ sung đủ các trường tĩnh: giao thông OSM (`osm_primary_road_m`, `osm_road_density_km_km2`), lớp phủ ESA WorldCover (`worldcover_builtup_ratio`, `worldcover_tree_ratio`, `worldcover_cropland_ratio`, `worldcover_water_ratio`), và địa hình DEM 30m (`dem_elevation_mean_m`, `dem_slope_mean_deg`).
  - 100% các ô phân tích thực tế không được chứa giá trị `NULL` ở các biến tĩnh địa hình/đô thị. Dòng ngoại lệ `grid_unknown` giữ `NULL` hoặc `-1`.
  - Giá trị các trường tỷ lệ bề mặt bắt buộc nằm trong khoảng $[0.0, 1.0]$. Độ cao nằm trong $[-10.0, 1400.0]\text{ m}$.

#### 2. Bàn giao 2: Dữ liệu Fact Viễn thám Vệ tinh Hàng ngày (`fct_grid_satellite_daily`)
- **Đường dẫn bàn giao:** `data/core/fct_grid_satellite_daily.parquet`.
- **Hạt dữ liệu đề xuất:** Ô lưới – Ngày (`grid_id`, `date_id`).
- **Danh sách biến dự kiến (theo Playbook TV2):**
  - Khóa: `grid_id`, `date_id`.
  - MODIS MAIAC AOD: `aod_047_mean` (hoặc `aod_550nm_mean`), `is_aod_missing_mnar`.
  - Sentinel-5P: `no2_tropospheric_mol_m2`.
  - VIIRS: `viirs_nightlight_rad`.
- **CÁC QUYẾT ĐỊNH CÒN MỞ (OPEN DECISIONS) CẦN TV2 XÁC NHẬN CHÍNH THỨC:**
  1. *Hình thức biểu diễn Fact:* TV2 cần xác nhận lưu trữ dưới dạng **Thưa (Sparse)** — chỉ lưu các ngày ô lưới thực sự có ảnh vệ tinh quan trắc được, hay dạng **Dày (Dense)** — chứa đủ 6.591.860 dòng kèm các giá trị `NULL`. (Data Architect khuyến nghị: Fact tầng Core nên lưu dạng Thưa để tiết kiệm dung lượng, việc làm đầy ma trận 6.591.860 dòng sẽ do tầng Marts đảm nhiệm khi `LEFT JOIN` với khung Spine).
  2. *Quy chuẩn tên cột AOD:* Thống nhất chọn tên `aod_047_mean` (theo dải đo thực tế $0.47\,\mu\text{m}$ của MODIS Band 3) hay `aod_550nm_mean` (chuẩn hóa về $550\text{ nm}$).
  3. *Phương pháp ánh xạ không gian:* Xác nhận thuật toán gán pixel từ ảnh gốc (độ phân giải 1km đối với AOD, 3.5x5.5km đối với S5P, 500m đối với VIIRS) sang các ô vuông 1km chuẩn của Hà Nội (Nearest Neighbor, Bilinear Interpolation, hay Zonal Statistics Area-weighted).
  4. *Đồng bộ thời gian VIIRS Nightlight:* Dữ liệu VIIRS DNB trên GEE là dạng tổng hợp tháng (`MONTHLY_V1`). TV2 cần xác nhận thuật toán phát tán giá trị tháng (broadcast) cho tất cả các ngày trong tháng đó.
  5. *Ngưỡng lọc cờ QA Sentinel-5P:* Xác nhận việc cố định ngưỡng $QA \ge 0.75$ loại bỏ mây và tuyết.

---

### 5.2. Bàn giao của Thành viên 3 (`minh` — Tái phân tích Khí tượng ERA5)

#### 1. Bàn giao 1: Bảng Độ ẩm Tương đối ($RH$) Giải phóng Nút thắt cho TV1
- **Đường dẫn bàn giao:** `data/staging/stg_meteo_daily.parquet` (kèm cột `rh_mean_pct`).
- **Thời hạn & Mục tiêu:** Bàn giao sớm để TV1 thực hiện hiệu chỉnh ẩm $\kappa$-Köhler cho các trạm quan trắc mặt đất Tier 2 (ADR-011).
- **Tiêu chí nghiệm thu:** Cột `rh_mean_pct` được tính từ $T_{2m}$ và $T_{dew}$ chuỗi giờ theo công thức Magnus-Tetens, gom trung bình ngày địa phương Hà Nội, giá trị đầy đủ không khuyết thiếu, dải đo hợp lệ $[0.0, 100.0]\%$.

#### 2. Bàn giao 2: Dữ liệu Fact Khí tượng Hàng ngày (`fct_grid_meteo_daily`)
- **Đường dẫn bàn giao:** `data/core/fct_grid_meteo_daily.parquet`.
- **Hạt dữ liệu đề xuất:** Ô lưới – Ngày (`grid_id`, `date_id`).
- **Danh sách biến dự kiến (theo Playbook TV3):**
  - Khóa: `grid_id`, `date_id`.
  - ERA5-Land: `temp_2m_mean_c`, `dewpoint_2m_mean_c`, `rh_mean_pct`, `precip_daily_mm`, `wind_speed_scalar_ms`, `wind_persistence`, `surface_pressure_hpa`.
  - ERA5 BLH: `blh_mean_m`, `blh_min_m`.
- **CÁC QUYẾT ĐỊNH CÒN MỞ (OPEN DECISIONS) CẦN TV3 XÁC NHẬN CHÍNH THỨC:**
  1. *Hình thức biểu diễn Fact:* Xác nhận Fact khí tượng là dạng Đầy đủ (Dense 6.591.860 dòng) hay dạng Thưa. Do ERA5-Land là mô hình tái phân tích liên tục không bị gián đoạn bởi mây che, TV3 có thể cung cấp đầy đủ 100% tọa độ cho 5 năm.
  2. *Thuật toán nội suy từ Pixel gốc sang Lưới 1km:* Dữ liệu thô ERA5-Land có độ phân giải ~9km (chỉ có ~45 điểm pixel gốc trên toàn Hà Nội) và BLH có độ phân giải ~31km (chỉ có ~8 điểm pixel gốc). TV3 cần xác nhận thuật toán nội suy sang 3.610 ô lưới:
     - Phương án A: Gán điểm láng giềng gần nhất (Nearest Neighbor) $\rightarrow$ Đơn giản, giữ nguyên giá trị gốc nhưng tạo ranh giới bậc thang giữa các ô.
     - Phương án B: Nội suy song tuyến tính (Bilinear Interpolation) hoặc IDW $\rightarrow$ Bề mặt khí tượng liên tục, mượt mà hơn nhưng làm biến đổi giá trị pixel gốc.
  3. *Quy tắc nghiệm thu tỷ lệ khuyết thiếu (Null Rate Tolerance):* Xác nhận tỷ lệ khuyết thiếu tối đa cho phép đối với ERA5-Land là $\le 2\%$ và đối với ERA5 BLH là $\le 5\%$.
  4. *Ràng buộc động học gió:* Xác nhận kiểm thử vật lý bắt buộc: Tốc độ gió có hướng vector không bao giờ được lớn hơn tốc độ gió vô hướng: $V_{\text{vector}} \le V_{\text{scalar}} + 10^{-5}$.

---

## 6. MA TRẬN PHÂN LOẠI VÀ THỰC THI CÁC BÀI KIỂM THỬ HỢP ĐỒNG (TESTING & VERIFICATION SUITE)

Để đảm bảo tính khách quan và minh bạch tối đa, bảng dưới đây phân định rõ ràng giữa **những bài kiểm tra ĐÃ ĐƯỢC CODE THỰC THI trong `contract_verifier.py`** và **những bài kiểm tra CẦN BỔ SUNG TRONG TƯƠNG LAI**:

### 6.1. Chi tiết Ma trận Kiểm định Chất lượng

| Mã bài kiểm tra | Mục tiêu kiểm tra | Model áp dụng | Tiêu chuẩn đánh giá | Trạng thái hỗ trợ trong Code Verifier | Biện pháp khi phát hiện vi phạm |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `CHK_SCHEMA_01` | Sự tồn tại của File và Thư mục | Mọi model | File Parquet tồn tại trên đĩa | **ĐÃ HỖ TRỢ** (`contract_verifier.py`) | Báo `PENDING` nếu upstream chưa giao; Báo `FAILED` nếu model bắt buộc bị thiếu. |
| `CHK_SCHEMA_02` | Sự hiện diện của các cột bắt buộc v1.0 | `dim_grid_1km`, `dim_date`, `dim_station`, `fct_ground_truth_daily` | 100% cột giai đoạn v1.0 phải có trong file | **ĐÃ HỖ TRỢ** (`contract_verifier.py`) | Báo `FAILED`. Chặn commit Git ngay lập tức. |
| `CHK_SCHEMA_03` | Kiểm tra đúng kiểu dữ liệu (Data Types) | Mọi model | Khớp chính xác kiểu Parquet (INT32, DOUBLE, VARCHAR...) | *CHƯA HỖ TRỢ TRONG CODE* (Verifier hiện chỉ check tên cột) | Cần cập nhật verifier để so sánh kiểu DuckDB DESCRIBE với YAML. |
| `CHK_SCHEMA_04` | Cột Enrichment v1.1 từ TV2 | `dim_grid_1km` | Đủ 8-15 cột đặc trưng tĩnh đô thị | **ĐÃ HỖ TRỢ** (`contract_verifier.py`) | Báo `PENDING` do đang chờ TV2 bàn giao. |
| `CHK_PK_NULL` | Tính Không-Null của Khóa chính | Mọi model | $0\%$ dòng có giá trị NULL ở các cột khóa chính | **ĐÃ HỖ TRỢ** (`contract_verifier.py`) | Báo `FAILED`. Dừng pipeline. |
| `CHK_PK_UNIQUE` | Tính Duy nhất 100% của Khóa chính | `dim_grid_1km`, `dim_date`, `dim_station`, `fct_ground_truth_daily` | `COUNT(*) == COUNT(DISTINCT PK)` | *HỖ TRỢ MỘT PHẦN* (Chỉ mới viết SQL cho `mart_grid_daily_features`) | Bổ sung kiểm tra tính duy nhất cho tất cả các bảng Dims và Facts. |
| `CHK_FK_ORPHAN` | Toàn vẹn Khóa ngoại (Zero Orphan FK) | `fct_ground_truth_daily` $\rightarrow$ `dim_station` | 100% khóa ngoại phải tồn tại ở bảng danh mục tương ứng | **ĐÃ HỖ TRỢ QUA SQL ASSERTION** (`assert_zero_orphan_station_join`) | Báo `FAILED`. Không cho phép có bản ghi mồ côi. |
| `CHK_VOLUME_SPINE`| Khớp đúng quy mô Ma trận Spine $|S|$ | `mart_grid_daily_features` | Số dòng phải bằng chính xác $6.591.860\text{ dòng}$ | **ĐÃ HỖ TRỢ QUA SQL ASSERTION** (`assert_exact_spine_mart_volume`) | Báo `PENDING` (chờ hoàn thiện Marts). Báo `FAILED` nếu sai lệch dù chỉ 1 dòng. |
| `CHK_ANTI_LEAK` | Rào chắn Chống Rò rỉ Nhãn (Label Firewall)| `mart_grid_daily_features` | Schema không được chứa cột khớp mẫu `*pm25*`, `*label*`, `*ground_truth*` | **ĐÃ HỖ TRỢ** (`contract_verifier.py`) | Báo `FAILED`. Hủy bỏ build Mart ngay lập tức. |
| `CHK_QC_18H` | Ràng buộc nghiệp vụ ngày trạm hợp lệ | `fct_ground_truth_daily` | 100% bản ghi phải có `valid_hours_count >= 18` | **ĐÃ HỖ TRỢ QUA SQL ASSERTION** (`assert_ground_truth_strict_18h_rule`) | Báo `FAILED`. Kiểm tra lại bước tổng hợp Staging. |
| `CHK_PHYSICS_RANGE`| Miền giá trị vật lý của các chỉ số | Mọi cột số đo | Nằm trong dải hợp lệ quy định tại Mục 3.3 | *CHƯA HỖ TRỢ TỰ ĐỘNG* (Verifier chưa đọc trường `range` trong YAML) | Cần bổ sung logic quét min/max theo cấu hình YAML. |
| `CHK_NULL_TOLERANCE`| Tỷ lệ khuyết thiếu tối đa cho phép | `mart_grid_daily_features` (cột nhiệt độ) | Tỷ lệ `NULL` của `temp_2m_mean_c` $\le 5\%$ | **ĐÃ HỖ TRỢ QUA SQL ASSERTION** (`assert_meteo_null_rate_tolerance`) | Báo `PENDING` (chờ hoàn thiện Marts). |
| `CHK_SPATIAL_CRS` | Kiểm tra Hệ quy chiếu GeoParquet | `dim_grid_1km` | Metadata GeoParquet phải ghi nhận `EPSG:3405` | *CHƯA HỖ TRỢ TRONG CODE* | Cần bổ sung kiểm tra cấu trúc metadata GeoParquet 1.1.0. |

### 6.2. Phân biệt Báo Cáo Nghiệm thu: Hiện hữu vs Chưa bàn giao
> [!WARNING]
> **Quy định nghiêm cấm Báo cáo Sai lệch:**  
> Hệ thống kiểm định `contract_verifier.py` và runner `run.py contract` **TUYỆT ĐỐI KHÔNG ĐƯỢC BÁO TRẠNG THÁI "PASSED" cho toàn bộ hồ chứa** khi mà các bảng của TV2 và TV3 chưa được bàn giao.  
> - Các model hiện hữu của TV1 (`dim_grid_1km` v1.0, `dim_date`, `dim_station`, `fct_ground_truth_daily`) được xác nhận **PASSED (ĐẠT CHUẨN NỀN TẢNG)**.  
> - Các model chưa bàn giao (`fct_grid_satellite_daily`, `fct_grid_meteo_daily`, `mart_grid_daily_features`) bắt buộc phải hiển thị trạng thái **PENDING (CHỜ BÀN GIAO UPSTREAM)**.  
> - Chỉ khi toàn bộ 6 model đều tồn tại và 100% checks đạt chuẩn, bản báo cáo tổng kết mới được phép công bố kết quả **ALL MODELS PASSED**.

---

## 7. ĐIỀU HƯỚNG TÀI LIỆU VÀ BƯỚC TIẾP THEO

- Xem chi tiết kiến trúc và luồng dữ liệu 4 tầng Medallion tại:  
  👉 **[Đặc tả Lược đồ Dữ liệu: docs/schema.md](./schema.md)**
- Mã nguồn kiểm tra hợp đồng tự động: Xem [contract_verifier.py](../src/common/contract_verifier.py).
- Kế hoạch phân công nhiệm vụ và lộ trình 6 giai đoạn: Xem [03_MASTER_EXECUTION_PLAN.md](./planning_v3/03_MASTER_EXECUTION_PLAN.md).
