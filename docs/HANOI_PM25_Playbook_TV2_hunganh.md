> Hợp đồng bàn giao v2.0: N_GRID = 3.610 ô giao ranh giới (không tính grid_unknown); 3.363 ô có tâm trong ranh giới chỉ là tập con. N_DAYS = 1.826, date_id = YYYYMMDD; khung phân tích = 6.591.860 dòng, loại cả hai unknown. Xem [SPINE_HANDOFF.md](SPINE_HANDOFF.md) và grid_manifest.json. Nguồn ranh giới: GSO / HDX COD-AB v02 (01/07/2025), chọn Ha Noi / VN01; xem provenance đi kèm. Dùng cố định cho chuỗi 2021–2025.

# HANOI_PM25 — ACTION PLAYBOOK: HUNGANH
## Earth Observation, Urban Static Features & Quality Lead
**Dự án:** Spatio-Temporal Data Lakehouse for Hanoi PM2.5 (2021–2025)  
**Phạm vi:** Cẩm nang hành động chuyên sâu và hướng dẫn từng bước dành riêng cho kỹ sư **`hunganh`**.


## 1. HƯỚNG DẪN DÀNH CHO NGƯỜI MỚI: BẢN CHẤT LƯU TRỮ DATABASE KHÔNG SERVER (ZERO-RDBMS LAKEHOUSE)

Nếu bạn là người mới và quen với việc phải cài đặt MySQL, PostgreSQL hay SQL Server để làm database, phần này sẽ giải thích chính xác cách hệ thống của chúng ta hoạt động.

### 1.1. Dự án này có cài Server Database nào không?
> **Câu trả lời là: HOÀN TOÀN KHÔNG CẦN CÀI ĐẶT BẤT KỲ SERVER DATABASE NÀO!**  
> Dự án tuân thủ kiến trúc **Zero-RDBMS**. Bạn không cần cài PostgreSQL, MySQL, SQL Server hay Docker. Máy bạn không phải chạy bất kỳ service ngầm nào.

### 1.2. Vậy dữ liệu được lưu ở đâu?
Database chính là **các file Apache Parquet / GeoParquet** lưu trực tiếp trong thư mục dự án trên ổ cứng:
* `data/raw/`: Dữ liệu thô nguyên bản tải từ mạng về, chia thư mục dạng tổ ong `source=.../year=.../month=...` (Hive Partitioning). Tuyệt đối **không sửa/xóa** dữ liệu ở đây.
* `data/staging/`: Dữ liệu trung gian đã chuẩn hóa giờ Hà Nội (`UTC+7`), sửa lỗi chính tả, gán cờ phát hiện số âm, lọc bớt bản ghi hỏng.
* `data/core/`: Mô hình hình sao (Kimball Star Schema) chuẩn hóa gồm 3 bảng danh mục (**Dimensions**: trạm, lưới, ngày tháng) và 3 bảng số liệu đo đạc (**Facts**: nồng độ PM2.5, khí tượng, vệ tinh).
* `data/marts/`: Bảng thành phẩm cuối cùng. Bảng `mart_grid_daily_features.parquet` là bảng đặc trưng mô hình **sạch nhãn 100% (cấm tuyệt đối có cột PM2.5)** để chống rò rỉ dữ liệu khi làm Machine Learning.

### 1.3. Tại sao dùng Parquet mà không dùng file CSV?
* **Lưu theo cột (Columnar):** Nếu bảng có 50 cột mà bạn chỉ cần tính trung bình cột nhiệt độ, DuckDB chỉ đọc đúng cột đó trên đĩa mà không cần nạp 49 cột còn lại $\rightarrow$ Tốc độ nhanh gấp hàng chục lần.
* **Nén siêu nhỏ (zstd):** File Parquet dung lượng chỉ bằng **1/5 đến 1/10** file CSV tương đương.
* **Không bao giờ lỗi font hay sai ngày tháng:** Kiểu dữ liệu được lưu chuẩn xác (`DATE`, `FLOAT`, `INTEGER`).

### 1.4. Truy vấn SQL bằng cách nào?
Dùng **DuckDB**! DuckDB chạy nhúng trực tiếp trong tiến trình Python:
```python
import duckdb

# Truy vấn trực tiếp file Parquet trên đĩa y hệt như bảng database thông thường:
df = duckdb.query('''
    SELECT station_id, date, pm25_daily_mean 
    FROM "data/staging/stg_ground_truth_daily.parquet"
    WHERE valid_hours_count >= 18 AND pm25_daily_mean > 50.0
''').df()

print(df.head())
```
*Không cần kết nối mạng, không cần username/password, không lo sập server DB!*

### 1.5. Mã băm SHA-256 (`_row_hash`) và Ghi lũy đẳng (Idempotency) là gì?
Mỗi dòng dữ liệu được cấp một "dấu vân tay" SHA-256 duy nhất từ các giá trị của nó. Khi cào dữ liệu mới, nếu gặp dòng có "vân tay" đã tồn tại thì tự động bỏ qua. **Dù bạn chạy script 1 lần hay 100 lần, dữ liệu vẫn không bao giờ bị trùng lặp hay phình to gấp đôi**.


---


## 2. HƯỚNG DẪN THỰC CHIẾN GIT & CI/CD DÀNH CHO TỪNG THÀNH VIÊN

Để 3 người làm việc song song mà không bao giờ bị ghi đè code (conflict) hoặc làm hỏng sản phẩm của nhau, cả nhóm tuân thủ quy trình sau:

### 2.1. Cấu trúc Nhánh Git (Branch Structure)
* **`main`:** Nhánh chính thức, chỉ dành cho sản phẩm đã nghiệm thu hoàn chỉnh và gắn tag phiên bản (ví dụ `v3.0.0`, `v2.1`). **CẤM PUSH TRỰC TIẾP**.
* **`develop`:** Nhánh chung của cả nhóm. Mọi tính năng sau khi test xong sẽ gộp vào đây qua Pull Request (PR).
* **Nhánh cá nhân (Feature branches):** Mỗi người tạo nhánh riêng từ `develop` để làm từng task:
  - **TV1 (`ngthinh06`):** `feat/tv1-<tên-nhiệm-vụ>` (ví dụ: `feat/tv1-ci-platform`, `feat/tv1-ground-truth-openaq`)
  - **TV2 (`hunganh`):** `feat/tv2-<tên-nhiệm-vụ>` (ví dụ: `feat/tv2-satellite-modis`, `feat/tv2-quality-gate`)
  - **TV3 (`minh`):** `feat/tv3-<tên-nhiệm-vụ>` (ví dụ: `feat/tv3-ingest-era5`, `feat/tv3-meteo-rh`)

### 2.2. Vòng lặp 5 Bước Làm việc Hàng ngày (Daily Git SOP)
```bash
# BƯỚC 1: Đầu ngày, cập nhật develop mới nhất về máy
git checkout develop
git pull origin develop

# BƯỚC 2: Tạo nhánh riêng để làm Task của mình
git checkout -b feat/tv1-ci-platform      # Nếu là TV1
# hoặc git checkout -b feat/tv2-satellite-modis # Nếu là TV2
# hoặc git checkout -b feat/tv3-ingest-era5     # Nếu là TV3

# BƯỚC 3: Code và kiểm tra lỗi cục bộ trên máy
python run.py lint           # Kiểm tra cú pháp code sạch sẽ
pytest tests/unit/           # Chạy unit test xem có pass không

# BƯỚC 4: Commit theo chuẩn (Bắt buộc ghi rõ Task ID)
git add <các_file_bạn_sửa>
git commit -m "feat(TASK-TV1-01): hoàn thành thiết lập CI/CD và runner run.py"

# BƯỚC 5: Đẩy lên GitHub và tạo Pull Request (PR)
git push -u origin <nhánh_của_bạn>
```

### 2.3. Quy trình Review & Gộp Code (PR Review RACI)
1. Sau khi push nhánh lên GitHub, bạn bấm nút **New Pull Request** để xin gộp vào `develop`.
2. Gắn người kiểm tra (Reviewer):
   - **TV1 mở PR** $\rightarrow$ Gắn **TV2** hoặc **TV3** review.
   - **TV2 mở PR** $\rightarrow$ Gắn **TV1** review.
   - **TV3 mở PR** $\rightarrow$ Gắn **TV1** review.
3. Chờ GitHub Actions (CI) chạy tự động qua 6 bước kiểm tra.
4. Reviewer đọc code, kiểm tra tính đúng đắn, bấm **Approve**.
5. Bấm nút **Squash and Merge** và xóa nhánh feature vừa gộp.

### 2.4. CI (GitHub Actions) chạy những gì? Xử lý khi CI Báo Đỏ như thế nào?
Mỗi khi bạn mở PR, hệ thống tự động chạy 6 bước kiểm tra:
1. `Lint Check (ruff)`: Kiểm tra xem code có đúng chuẩn định dạng Python không.  
   *(Nếu đỏ: Chạy lệnh `ruff check --fix .` ở máy bạn để tự động sửa lỗi, sau đó commit lại).*
2. `Unit Tests`: Chạy các bài test hàm logic cơ bản.  
   *(Nếu đỏ: Kiểm tra lỗi báo cụ thể ở test nào trong thư mục `tests/unit/`).*
3. `Idempotency Test`: Chạy script 2 lần liên tiếp để xem dữ liệu có bị nhân đôi hay không.  
   *(Nếu đỏ: Xem lại hàm ghi Parquet có dùng mã băm SHA-256 để chống trùng lặp chưa).*
4. `Data Build`: Chạy thử quy trình tạo bảng Staging và Core.
5. `DuckDB Quality Gate`: Chạy 9 câu lệnh SQL kiểm định tính toàn vẹn.
6. `Mutation Test`: Tiêm thử 4 lỗi giả lập vào dữ liệu, xem bộ test có bắt được không (yêu cầu Score = 100%).


---


## 4. MA TRẬN BÀN GIAO THEN CHỐT GIỮA 3 THÀNH VIÊN (REVISED HANDOFF MATRIX)

| Giao điểm | Người Giao | Người Nhận | Dữ liệu Bàn giao | Vị trí File Lưu trữ | Lệnh Tự Kiểm tra Nhanh (One-Liner Assertion) |
| :---: | :---: | :---: | :--- | :--- | :--- |
| **Giao điểm 1** | **TV1** | **TV2, TV3**| Codebase Platform, CI/CD, Hàm băm | `run.py`, `.github/workflows/ci.yml`, `common/hashing.py` | `python run.py lint && pytest tests/unit/` |
| **Giao điểm 2** | **TV1** | **TV2** | Khung Lưới 1km ban đầu (v1.0) | `data/core/dim_grid_1km.parquet` | `python -c "import duckdb; con = duckdb.connect(); cnt = con.execute('SELECT COUNT(*) FROM "data/core/dim_grid_1km.parquet"').fetchone()[0]; assert cnt > 3000"` |
| **Giao điểm 3** | **TV2** | **TV1, TV3**| Lưới 1km đủ 15 biến tĩnh (v1.1) | `data/core/dim_grid_1km.parquet` | `python -c "import duckdb; con = duckdb.connect(); res = con.execute('SELECT AVG(worldcover_builtup_ratio) FROM "data/core/dim_grid_1km.parquet"').fetchone(); assert 0 <= res[0] <= 1"` |
| **Giao điểm 4** *(Quan trọng)* | **TV3** | **TV1** | Bảng RH Khí quyển để hiệu chỉnh Köhler | `data/staging/stg_meteo_daily.parquet` | `python -c "import duckdb; con = duckdb.connect(); cnt = con.execute('SELECT COUNT(*) FROM "data/staging/stg_meteo_daily.parquet" WHERE rh_mean_pct IS NOT NULL').fetchone()[0]; assert cnt > 0"` |
| **Giao điểm 5** | **TV1, TV3**| **TV2** | Dữ liệu Fact Trạm & Fact Khí tượng đã lọc | `fct_ground_truth_daily`, `fct_grid_meteo_daily`| `python -c "import duckdb; con = duckdb.connect(); inv = con.execute('SELECT COUNT(*) FROM "data/core/fct_ground_truth_daily.parquet" WHERE valid_hours_count < 18').fetchone()[0]; assert inv == 0"` |


---

<div class="diagram-wrapper"><div class="diagram-title">SƠ ĐỒ 9: CỔNG KIỂM ĐỊNH CHẤT LƯỢNG DUCKDB SQL & MUTATION TESTING</div><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 460" width="960" height="460">
  <defs>
    <style>
      .bg { fill: #FFFFFF; }
      .title { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; font-size: 18px; fill: #14263D; }
      .subtitle { font-family: 'Segoe UI', Arial, sans-serif; font-size: 12px; fill: #64748B; }
      .q-card { rx: 6; ry: 6; stroke-width: 1.5; fill: #FFFFFF; }
      .q-head { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; font-size: 12.5px; }
      .q-sub { font-family: 'Segoe UI', Arial, sans-serif; font-size: 11px; fill: #475569; }
      .q-crit { fill: #FEF2F2; stroke: #EF4444; }
      .q-pass { fill: #F0FDF4; stroke: #22C55E; }
    </style>
  </defs>

  <rect width="960" height="460" class="bg" />
  <text x="40" y="38" class="title">CỔNG KIỂM ĐỊNH CHẤT LƯỢNG DUCKDB SQL &amp; KIỂM THỬ ĐỘT BIẾN (MUTATION)</text>
  <text x="40" y="56" class="subtitle">Quy trình tự động hóa kiểm soát tính toàn vẹn hồ chứa và kiểm chứng năng lực bắt lỗi trong Sandbox</text>

  <!-- LEFT: 9 SQL QUALITY RULES -->
  <rect x="40" y="80" width="430" height="350" rx="8" ry="8" fill="#F8FAFC" stroke="#CBD5E1" stroke-width="1.5" />
  <text x="55" y="105" font-family="'Segoe UI', sans-serif" font-weight="700" font-size="14px" fill="#1E293B">9 QUY TẮC DUCKDB SQL (quality/rules.yml)</text>
  <text x="55" y="122" font-family="'Segoe UI', sans-serif" font-size="11px" fill="#64748B">Điều kiện Pass: 100% rules có violation_count == 0</text>

  <rect x="55" y="135" width="400" height="40" class="q-card" stroke="#3B82F6" />
  <text x="65" y="152" class="q-head" fill="#1D4ED8">QG_SPINE_01 &amp; 02: Bảo toàn Khung xương Spine</text>
  <text x="65" y="167" class="q-sub">Khớp đúng |S| dòng từ grid_manifest.json; Duy nhất (grid_id, date_id)</text>

  <rect x="55" y="185" width="400" height="40" class="q-card q-crit" />
  <text x="65" y="202" class="q-head" fill="#DC2626">QG_LEAK_01: Chống Rò rỉ Nhãn (Label Leakage)</text>
  <text x="65" y="217" class="q-sub">Feature Mart tuyệt đối không chứa cột %pm25%, %station%, %ground_truth%</text>

  <rect x="55" y="235" width="400" height="40" class="q-card" stroke="#10B981" />
  <text x="65" y="252" class="q-head" fill="#047857">QG_FK_01 &amp; NULL_01: Toàn vẹn Khóa ngoại</text>
  <text x="65" y="267" class="q-sub">Zero Orphan Foreign Keys trỏ Facts -&gt; Dims; Zero NULL grid_id &amp; date_id</text>

  <rect x="55" y="285" width="400" height="40" class="q-card" stroke="#F59E0B" />
  <text x="65" y="302" class="q-head" fill="#B45309">QG_COMPLETENESS_01: Độ đầy đủ Khí tượng</text>
  <text x="65" y="317" class="q-sub">Tỷ lệ đầy đủ pixel gốc ERA5-Land &gt;= 98%, ERA5 BLH &gt;= 95%</text>

  <rect x="55" y="335" width="400" height="40" class="q-card" stroke="#8B5CF6" />
  <text x="65" y="352" class="q-head" fill="#6D28D9">QG_SENSOR_01 &amp; 02: Chuỗi giờ &amp; Giờ hợp lệ</text>
  <text x="65" y="367" class="q-sub">stg_daily 100% dòng có 18..24h; Nhất quán cờ cứng (0) vs cờ nghi vấn (1)</text>

  <rect x="55" y="385" width="400" height="35" class="q-card" stroke="#64748B" />
  <text x="65" y="401" class="q-head" fill="#334155">QG_PHYSICS_01: Miền Giá trị Vật lý</text>
  <text x="65" y="413" class="q-sub">T2m [-5..50]C, RH [0..100]%, BLH (10..5000]m, V_vector &lt;= V_scalar</text>

  <!-- RIGHT: MUTATION TESTING SANDBOX -->
  <rect x="490" y="80" width="430" height="350" rx="8" ry="8" fill="#F8FAFC" stroke="#CBD5E1" stroke-width="1.5" />
  <text x="505" y="105" font-family="'Segoe UI', sans-serif" font-weight="700" font-size="14px" fill="#1E293B">KIỂM THỬ ĐỘT BIẾN (quality/mutation_tester.py)</text>
  <text x="505" y="122" font-family="'Segoe UI', sans-serif" font-size="11px" fill="#64748B">Sandbox tempfile.TemporaryDirectory() · Tiêm 4 lỗi kiểm tra phản xạ Gate</text>

  <rect x="505" y="135" width="400" height="50" class="q-card" stroke="#CBD5E1" />
  <text x="515" y="153" class="q-head" fill="#1E293B">Đột biến 1: Xóa 1 ô lưới khỏi Marts</text>
  <text x="515" y="168" class="q-sub">Số dòng giảm từ |S| xuống |S| - 1826 dòng</text>
  <text x="515" y="180" font-family="'Segoe UI', sans-serif" font-size="10.5px" font-weight="700" fill="#DC2626">Gate QG_SPINE_01 BẮT BUỘC BÁO FAIL</text>

  <rect x="505" y="195" width="400" height="50" class="q-card" stroke="#CBD5E1" />
  <text x="515" y="213" class="q-head" fill="#1E293B">Đột biến 2: Tiêm cột nhãn vào Feature Mart</text>
  <text x="515" y="228" class="q-sub">Thêm cột giả lập pm25_calibrated_mean vào schema</text>
  <text x="515" y="240" font-family="'Segoe UI', sans-serif" font-size="10.5px" font-weight="700" fill="#DC2626">Gate QG_LEAK_01 BẮT BUỘC BÁO FAIL</text>

  <rect x="505" y="255" width="400" height="50" class="q-card" stroke="#CBD5E1" />
  <text x="515" y="273" class="q-head" fill="#1E293B">Đột biến 3: Chèn khóa ngoại mồ côi (Orphan FK)</text>
  <text x="515" y="288" class="q-sub">Thêm dòng station_id = 'station_ghost_999' vào fct_ground_truth</text>
  <text x="515" y="300" font-family="'Segoe UI', sans-serif" font-size="10.5px" font-weight="700" fill="#DC2626">Gate QG_FK_01 BẮT BUỘC BÁO FAIL</text>

  <rect x="505" y="315" width="400" height="50" class="q-card" stroke="#CBD5E1" />
  <text x="515" y="333" class="q-head" fill="#1E293B">Đột biến 4: Làm sai lệch logic cờ QC</text>
  <text x="515" y="348" class="q-sub">Sửa dòng có qc_flatline = 1 nhưng cố tình gán qc_passed_flag = 1</text>
  <text x="515" y="360" font-family="'Segoe UI', sans-serif" font-size="10.5px" font-weight="700" fill="#DC2626">Gate QG_SENSOR_02 BẮT BUỘC BÁO FAIL</text>

  <!-- SCORE BOX -->
  <rect x="505" y="375" width="400" height="45" rx="6" ry="6" class="q-pass" />
  <text x="515" y="395" font-family="'Segoe UI', sans-serif" font-weight="700" font-size="12px" fill="#166534">TIÊU CHUẨN NGHIỆM THU: MUTATION SCORE == 100%</text>
  <text x="515" y="410" font-family="'Segoe UI', sans-serif" font-size="10.5px" fill="#15803D">Chặn đứng 4/4 đột biến; Nếu lọt 1 lỗi =&gt; Exit code 1 đánh trượt PR lập tức</text>
</svg><div class="diagram-caption">Khung kiểm định 5 trụ cột với 9 rules SQL và sandbox tiêm đột biến bắt buộc score 100%</div></div>


## 6. HƯỚNG DẪN THỰC THI CHI TIẾT DÀNH CHO THÀNH VIÊN 2: `hunganh`
**Vai trò:** Earth Observation, Urban Static Features & Quality Lead  
**Trọng tâm:** Thu thập và biến đổi Viễn thám GEE (Sentinel-5P, MODIS MAIAC, VIIRS), trích xuất 15 Biến tĩnh đô thị vào lưới 1km, Thiết lập Cổng chất lượng DuckDB SQL 9 rules, Mutation Testing sandbox và Đóng gói Star Schema & Marts.

---

### Task TV2-01: Trích xuất 15 Đặc trưng Tĩnh Đô thị vào Lưới 1km
* **Mục tiêu:** Tính toán các thuộc tính bề mặt đô thị, giao thông và địa hình cho từng ô lưới 1km.
* **Input:** `dim_grid_1km.parquet` v1.0 (từ TV1), OSM roads shapefile, ESA WorldCover 10m raster, NASA SRTM DEM 30m raster.
* **Output:** `data/core/dim_grid_1km.parquet` v1.1 (đầy đủ 15 biến tĩnh).
* **Cách làm từng bước:**
  1. Đọc `dim_grid_1km.parquet` v1.0 bằng `geopandas`.
  2. Đọc lớp đường OSM trong `EPSG:3405`, dùng `gpd.overlay` hoặc `intersection` để tính tổng chiều dài đường chính (`osm_primary_road_m`) và mật độ đường (`osm_road_density_km_km2`) trong từng ô vuông.
  3. Dùng thư viện `rasterstats` (hàm `zonal_stats`) để tính:
     - Tỷ lệ diện tích đô thị / công trình xây dựng (`worldcover_builtup_ratio`, mã pixel 50).
     - Tỷ lệ cây xanh / rừng (`worldcover_tree_ratio`, mã pixel 10).
     - Tỷ lệ đất nông nghiệp (`worldcover_cropland_ratio`, mã pixel 40) và mặt nước (`worldcover_water_ratio`, mã pixel 80).
     - Độ cao trung bình (`dem_elevation_mean_m`) và độ dốc địa hình trung bình (`dem_slope_mean_deg`) từ DEM 30m.
  4. Nối các cột mới vào GeoDataFrame và xuất `dim_grid_1km.parquet` v1.1. Bàn giao cho TV1 & TV3.
* **Lệnh chạy:** `python -m ingestion.earth_observation.extract_static_grid_features`
* **Lệnh tự kiểm tra:** `python -c "import duckdb; con = duckdb.connect(); res = con.execute('SELECT AVG(worldcover_builtup_ratio), AVG(dem_elevation_mean_m) FROM "data/core/dim_grid_1km.parquet"').fetchone(); assert 0 <= res[0] <= 1; print('Static features OK:', res)"`
* **DoD:** 100% ô lưới có đủ 15 biến tĩnh, giá trị nằm đúng miền vật lý.

---

### Task TV2-02: Kiểm toán Nguồn Viễn thám Vệ tinh trên Google Earth Engine (GEE)
* **Mục tiêu:** Kiểm tra tính sẵn có và vùng bao phủ của 3 tập ảnh viễn thám trên GEE giai đoạn 2021–2025.
* **Input:** Tài khoản GEE (`ee.Initialize()`).
* **Output:** `docs/sources_satellite.md`.
* **Cách làm từng bước:**
  1. Viết script `ingestion/audit/audit_gee_sources.py` sử dụng thư viện `earthengine-api`.
  2. Ping và đếm số lượng ảnh bao phủ Hà Nội từ 3 ImageCollections:
     - Sentinel-5P: `COPERNICUS/S5P/OFFL/L3_NO2` (dải `tropospheric_NO2_column_number_density`).
     - MODIS MAIAC AOD: `MODIS/061/MCD19A2_GRANULES` (dải `Optical_Depth_047`).
     - VIIRS Nightlight: `NOAA/VIIRS/DNB/MONTHLY_V1/VCMCFG` (dải `avg_rad`).
  3. Lập bảng thống kê số ảnh theo từng năm và xuất file `docs/sources_satellite.md`.
* **Lệnh chạy:** `python run.py audit --component satellite`
* **DoD:** Kết nối thành công GEE, xác nhận đủ dữ liệu 5 năm lịch.

---

### Task TV2-03: Thu thập Thô Viễn thám Vệ tinh từ GEE theo Chunks
* **Mục tiêu:** Tải dữ liệu vệ tinh thô 2021–2025 về Bronze mà không bị vượt quá giới hạn bộ nhớ/timeout của GEE.
* **Input:** GEE ImageCollections.
* **Output:** `data/raw/earth_observation/`.
* **Cách làm từng bước:**
  1. Chia thời gian thành các khoảng (chunks) 3 tháng/lần (ví dụ `2021-01-01` đến `2021-03-31`).
  2. Trích xuất giá trị các pixel vệ tinh trong ranh giới Hà Nội.
  3. Tính mã băm `_row_hash` cho từng bản ghi bằng hàm của TV1.
  4. Lưu vào thư mục Bronze theo phân vùng Hive: `data/raw/earth_observation/source=s5p_no2/year=YYYY/quarter=Q/data.parquet` và `source=modis_aod/`.
* **Lệnh chạy:** `python run.py ingest --source satellite`
* **DoD:** Dữ liệu vệ tinh thô được tải về đầy đủ, lưu append lũy đẳng.

---

### Task TV2-04: Biến đổi Staging Viễn thám & Áp dụng Chính sách Mây che MNAR
* **Mục tiêu:** Lọc chất lượng ảnh vệ tinh và xử lý đúng nguyên lý khoa học đối với dữ liệu khuyết do mây che.
* **Input:** Bronze Satellite tại `data/raw/earth_observation/`.
* **Output:** `data/staging/stg_satellite_daily.parquet`.
* **Cách làm từng bước:**
  1. Lọc QA cho Sentinel-5P: Chỉ giữ lại các pixel có cờ chất lượng `qa_value >= 0.75` (loại bỏ ảnh hưởng của mây dày và góc nghiêng lớn).
  2. Chuẩn hóa thang đo MODIS MAIAC AOD: Nhân với hệ số tỷ lệ `scale_factor = 0.001` để đưa về giá trị AOD thực (khoảng `[0.0, 3.5]`).
  3. **Chính sách Mây che MNAR (Missing Not At Random - ADR-007):**
     - Khi vệ tinh bị mây che, giá trị AOD bị khuyết. **Tuyệt đối CẤM nội suy không gian mù quáng** (như KNN hay IDW) vì mây che đi kèm độ ẩm cao và sương mù, nếu nội suy sẽ làm sai lệch bản chất ô nhiễm.
     - Giữ nguyên giá trị `NULL` cho cột `aod_047_mean`.
     - Đồng thời bật cờ: `is_aod_missing_mnar = 1` (nếu có đo được thì `is_aod_missing_mnar = 0`).
  4. Gom ngày theo giờ địa phương Hà Nội và xuất `stg_satellite_daily.parquet`.
* **Lệnh chạy:** `python -m transform.staging.gee.process_satellite_eo`
* **Lệnh tự kiểm tra:** `python -c "import duckdb; con = duckdb.connect(); inv = con.execute('SELECT COUNT(*) FROM "data/staging/stg_satellite_daily.parquet" WHERE aod_047_mean IS NULL AND is_aod_missing_mnar = 0').fetchone()[0]; assert inv == 0; print('MNAR Policy OK: 100% consistent')"`
* **DoD:** Cờ MNAR phản ánh chính xác trạng thái khuyết thiếu do mây che.

---

### Task TV2-05: Broadcast Viễn thám sang Ô lưới 1km & Tạo Fact Vệ tinh
* **Mục tiêu:** Gán dữ liệu viễn thám vào từng ô lưới 1km theo `grid_id`.
* **Input:** `stg_satellite_daily.parquet`, `dim_grid_1km.parquet`, `dim_date.parquet`.
* **Output:** `data/core/fct_grid_satellite_daily.parquet`.
* **Cách làm từng bước:**
  1. Đọc dữ liệu viễn thám ngày. Dùng phép gán không gian (Spatial Overlay) hoặc Nearest-Neighbor để truyền giá trị từ pixel vệ tinh sang ~3,360 ô lưới 1km.
  2. Nối với `dim_date` để lấy `date_id`.
  3. Xuất file `data/core/fct_grid_satellite_daily.parquet`.
* **Lệnh chạy:** `python -m transform.staging.broadcast_satellite_to_grid`
* **DoD:** Mọi ô lưới 1km đều có bản ghi sự kiện vệ tinh hàng ngày kèm cờ MNAR.

---

### Task TV2-06: Soạn thảo 9 Rules DuckDB SQL & Cổng Kiểm định Quality Gate
* **Mục tiêu:** Tự động hóa kiểm tra toàn vẹn chất lượng dữ liệu bằng 9 câu lệnh SQL siêu tốc.
* **Input:** Hợp đồng Dữ liệu Data Contract v3.0, `grid_manifest.json`.
* **Output:** `quality/rules.yml`, `quality/gate_runner.py`.
* **Cách làm từng bước:**
  1. Viết file `quality/rules.yml` chứa 9 câu lệnh SQL kiểm định (xem chi tiết ở Mục 6 của cẩm nang chung).
  2. Viết `quality/gate_runner.py`: Kết nối DuckDB in-process, đọc dữ liệu từ `data/core/` và `data/marts/`, thực thi lần lượt 9 câu SQL.
  3. Nếu câu query trả về 0 bản ghi lỗi $ightarrow$ Đánh dấu **PASS**. Nếu có lỗi $ightarrow$ Báo **FAIL**, in ra 5 dòng vi phạm đầu tiên và dừng pipeline với `exit code 1`.
* **Lệnh chạy:** `python run.py quality`
* **Lệnh tự kiểm tra:** `python quality/gate_runner.py`
* **DoD:** Cổng chất lượng chạy qua 9 quy tắc trong dưới 5 giây.

---

### Task TV2-07: Xây dựng Framework Kiểm thử Đột biến (Sandbox Mutation Testing)
* **Mục tiêu:** Chứng minh bộ kiểm tra chất lượng thực sự bắt được lỗi kiến trúc bằng phương pháp tiêm đột biến.
* **Input:** Bộ dữ liệu Core/Marts hợp lệ, `quality/gate_runner.py`.
* **Output:** `quality/mutation_tester.py`.
* **Cách làm từng bước:**
  1. Tạo thư mục sandbox tạm: `tempfile.mkdtemp(prefix="data_sandbox_")`.
  2. Sao chép dữ liệu thật vào sandbox. Tiêm lần lượt 4 đột biến:
     - *Đột biến 1 (Spine Drop):* Xóa ngẫu nhiên 50 dòng trong Feature Mart $ightarrow$ Bắt buộc Rule 1 phải FAIL.
     - *Đột biến 2 (Label Leak):* Tiêm cột `pm25_ug_m3` vào Feature Mart $ightarrow$ Bắt buộc Rule 3 phải FAIL.
     - *Đột biến 3 (Orphan FK):* Chèn `grid_id = 'cell_999999_999999'` vào Facts $ightarrow$ Bắt buộc Rule 2 phải FAIL.
     - *Đột biến 4 (Relaxed QC):* Chèn bản ghi trạm ngày có 15 giờ hợp lệ $ightarrow$ Bắt buộc Rule 6 phải FAIL.
  3. Tính điểm đột biến: $	ext{Mutation Score} = rac{	ext{Số đột biến bị bắt}}{	ext{Tổng số đột biến}} 	imes 100\%$. Bắt buộc đạt **100%**.
* **Lệnh chạy:** `python run.py test-mutation`
* **DoD:** Mutation Score đạt 100%, dọn dẹp sạch sandbox sau khi chạy.

---

### Task TV2-08: Đóng gói Kimball Star Schema Tầng Core
* **Mục tiêu:** Hoàn thiện liên kết mô hình hình sao, bảo đảm tính toàn vẹn khóa ngoại 100%.
* **Input:** 3 Dims (`dim_grid_1km`, `dim_date`, `dim_station`) và 3 Facts (`fct_ground_truth_daily` từ TV1, `fct_grid_meteo_daily` từ TV3, `fct_grid_satellite_daily`).
* **Output:** Tầng Core hoàn chỉnh, tài liệu đối soát khóa ngoại.
* **Cách làm từng bước:**
  1. Viết `transform/core/build_star_schema.py`.
  2. Dùng DuckDB SQL kiểm tra:
     ```sql
     -- Kiểm tra Zero-Orphan FKs
     SELECT COUNT(*) FROM fct_grid_meteo_daily m 
     WHERE NOT EXISTS (SELECT 1 FROM dim_grid_1km g WHERE g.grid_id = m.grid_id);
     ```
  3. Khẳng định số lượng khóa ngoại mồ côi (Orphan FKs) bằng đúng 0.
* **Lệnh chạy:** `python -m transform.core.build_star_schema`
* **DoD:** 100% khóa ngoại liên kết hoàn hảo giữa Facts và Dims.

---

### Task TV2-09: Xây dựng Feature Mart Sạch Nhãn & EDA Marts Tầng Platinum
* **Mục tiêu:** Tạo sản phẩm dữ liệu thành phẩm phục vụ Machine Learning và phân tích khám phá.
* **Input:** Tầng Core hoàn chỉnh.
* **Output:** `data/marts/mart_grid_daily_features.parquet`, `mart_grid_daily_eda.parquet`, `mart_station_matched.parquet`.
* **Cách làm từng bước:**
  1. Thực hiện tích Descartes giữa `dim_grid_1km` (lọc grid_unknown) và `dim_date` (lọc date_id = -1) (đúng $|S| = N_{	ext{GRID}} 	imes 1,826$ dòng).
  2. `LEFT JOIN` với `fct_grid_meteo_daily` và `fct_grid_satellite_daily`.
  3. **Áp dụng Whitelist 22 cột tuyệt đối sạch nhãn**: Không chứa bất kỳ cột PM2.5 nào. Xuất `mart_grid_daily_features.parquet`.
  4. Tạo `mart_grid_daily_eda.parquet`: Ghép thêm nhãn ô lưới để phục vụ 6 chuyên đề EDA.
  5. Tạo `mart_station_matched.parquet`: Ghép trạm đo mặt đất với đặc trưng ô lưới tương ứng để làm tập đối chứng ground truth.
* **Lệnh chạy:** `python -m transform.marts.build_feature_mart && python -m transform.marts.build_eda_marts`
* **Lệnh tự kiểm tra:** `python -c "import duckdb; con = duckdb.connect(); cnt = con.execute('SELECT COUNT(*) FROM "data/marts/mart_grid_daily_features.parquet"').fetchone()[0]; print('Feature Mart row count:', cnt)"`
* **DoD:** Feature Mart sạch nhãn 100%, số dòng khớp chính xác tích Descartes $|S|$.

---

### Task TV2-10: Thực hiện Spatio-Temporal EDA Chuyên đề 1 & Chuyên đề 6
* **Mục tiêu:** Khám phá cơ chế mất dữ liệu viễn thám và khảo sát địa thống kê tương quan không gian.
* **Input:** `mart_grid_daily_eda.parquet`, `stg_satellite_daily.parquet`.
* **Output:** `notebooks/eda_01_missing_mechanisms.ipynb`, `notebooks/eda_06_geostatistics.ipynb`.
* **Cách làm:**
  - *Chuyên đề 1:* Phân tích tỷ lệ mây che theo tháng, đối sánh tương quan giữa tỷ lệ mất AOD với độ ẩm cao và sương mù mùa đông Hà Nội.
  - *Chuyên đề 6:* Tính toán Semivariogram thực nghiệm không gian - thời gian, xác định bán kính tương quan (Range), hiệu ứng hạt (Nugget) qua các mùa trong năm.
* **Lệnh chạy:** `python run.py eda --topics 1,6`
* **DoD:** 2 notebook chạy mượt, có đồ thị semivariogram và ma trận tương quan mây che.

---

### Task TV2-11: Tổng kết Kiểm định Chất lượng & Báo cáo Sẵn sàng Dữ liệu
* **Mục tiêu:** Lập Báo cáo Đảm bảo Chất lượng Dữ liệu toàn diện trước khi đóng dự án.
* **Output:** `docs/planning_v3/DATA_READINESS_REPORT.md` (Phần Quality & Marts).


---


## 8. HỢP ĐỒNG DỮ LIỆU & SCHEMA BẢNG ĐẶC TRƯNG (`mart_grid_daily_features`)

Bảng đặc trưng thành phẩm tại tầng Platinum được khóa cứng schema 22 cột (Whitelisted):

| Tên Cột | Kiểu Dữ liệu | Nullable | Miền Giá trị / Đơn vị | Người Chịu trách nhiệm Cung cấp |
| :--- | :---: | :---: | :--- | :---: |
| `grid_id` | `VARCHAR` | NO | `cell_X_Y` | **TV1** (Lưới không gian 1km) |
| `date_id` | `INTEGER` | NO | `YYYYMMDD (20210101–20251231); unknown = -1` | **TV1** (Trục ngày 5 năm) |
| `date` | `DATE` | NO | `2021-01-01` đến `2025-12-31` | **TV1** (Trục ngày 5 năm) |
| `temp_2m_mean_c` | `FLOAT` | YES | `[5.0, 48.0]` °C | **TV3** (ERA5-Land) |
| `dewpoint_2m_mean_c`| `FLOAT` | YES | `[0.0, 35.0]` °C | **TV3** (ERA5-Land) |
| `rh_mean_pct` | `FLOAT` | YES | `[10.0, 100.0]` % | **TV3** (Magnus-Tetens) |
| `precip_daily_mm` | `FLOAT` | YES | `[0.0, 500.0]` mm | **TV3** (Khử tích lũy) |
| `wind_speed_scalar_ms`| `FLOAT`| YES | `[0.0, 35.0]` m/s | **TV3** (Gió vô hướng) |
| `wind_persistence` | `FLOAT` | YES | `[0.0, 1.0]` (tỷ số) | **TV3** (Độ bền vững hướng) |
| `surface_pressure_hpa`| `FLOAT`| YES | `[950.0, 1050.0]` hPa | **TV3** (ERA5-Land) |
| `blh_mean_m` | `FLOAT` | YES | `[50.0, 3500.0]` m | **TV3** (ERA5 BLH) |
| `blh_min_m` | `FLOAT` | YES | `[30.0, 2000.0]` m | **TV3** (ERA5 BLH) |
| `aod_047_mean` | `FLOAT` | YES | `[0.0, 3.5]` (không đv) | **TV2** (MODIS MAIAC AOD) |
| `is_aod_missing_mnar`| `TINYINT`| NO | `0` hoặc `1` | **TV2** (Cờ mây che MNAR) |
| `no2_tropospheric_mol_m2`| `FLOAT`| YES| `[0.0, 1e-3]` mol/m² | **TV2** (Sentinel-5P QA≥0.75)|
| `viirs_nightlight_rad`| `FLOAT` | YES | `[0.0, 300.0]` nW/cm²/sr| **TV2** (VIIRS DNB) |
| `osm_primary_road_m`| `FLOAT` | NO | `≥ 0.0` m | **TV2** (OSM Highways) |
| `osm_road_density_km_km2`| `FLOAT`| NO| `≥ 0.0` km/km² | **TV2** (Mật độ đường) |
| `worldcover_builtup_ratio`| `FLOAT`| NO| `[0.0, 1.0]` | **TV2** (WorldCover 10m) |
| `worldcover_tree_ratio`| `FLOAT`| NO | `[0.0, 1.0]` | **TV2** (WorldCover 10m) |
| `dem_elevation_mean_m`| `FLOAT`| NO | `[-5.0, 1300.0]` m | **TV2** (NASA SRTM DEM 30m) |
| `dem_slope_mean_deg` | `FLOAT` | NO | `[0.0, 60.0]` độ | **TV2** (NASA SRTM DEM 30m) |

---

## 9. SỔ TAY ĐIỀU HÀNH 1-CLICK (`run.py`), NGUYÊN TẮC VÀNG & CHECKLIST

### 9.1. Bảng Tra cứu Lệnh Điều hành 1-Click (`run.py Cheat Sheet`)
```powershell
# 1. Cài đặt và kiểm tra cú pháp code (TV1 lead)
python run.py setup
python run.py lint

# 2. Khởi tạo Lưới 1km và Trục ngày 5 năm (TV1)
python run.py grid

# 3. Kiểm toán độ phủ thực tế các nguồn dữ liệu (Cả 3 TV)
python run.py audit

# 4. Thu thập dữ liệu thô (Raw Ingestion)
python run.py ingest --env prod        # Tải dữ liệu thật 5 năm
python run.py ingest --env ci_test     # Sinh dữ liệu mock phục vụ CI

# 5. Chuyển đổi Medallion (Staging -> Core Star Schema -> Marts)
python run.py transform

# 6. Kiểm tra Cổng chất lượng & Kiểm thử Đột biến (TV2 lead)
python run.py quality
python run.py test-mutation

# 7. Chạy 6 Chuyên đề Phân tích Khám phá EDA
python run.py eda

# 8. Chạy toàn bộ pipeline tự động từ đầu đến cuối chỉ với 1 lệnh
python run.py all

# 9. Dọn dẹp cache và file tạm
python run.py clean
```

### 9.2. Ba Nguyên tắc Vàng Bắt buộc Tuân thủ
1. **Nguyên tắc Vàng 1 — Bất biến Khung xương (TV1 & TV2 Lead):** Quy mô hàng của Feature Mart $|S| = N_{\text{GRID}} \times 1,826$ dòng là bất biến tuyệt đối. Cấm mọi thao tác `DROP` dòng trên feature marts.
2. **Nguyên tắc Vàng 2 — Bảo tồn Dữ liệu & QC Phân tầng (TV1 Lead):** Giữ 100% bản ghi chuỗi giờ ở `stg_ground_truth_hourly`. Chỉ lọc khắt khe $18 \le \text{valid\_hours} \le 24$ khi gom ngày vào `stg_ground_truth_daily`.
3. **Nguyên tắc Vàng 3 — Mở khóa Nút thắt Bàn giao RH (TV3 Lead):** Hoàn thành và bàn giao ngay `stg_meteo_daily.parquet` (cột `rh_mean_pct`) cho TV1 để mở khóa thuật toán hiệu chỉnh ẩm $\kappa$-Köhler cho trạm PAM Air.

---

### 9.3. Checklist Nghiệm thu Ngày Đầu tiên (Day-1 DoD)

| Thành viên | Nhiệm vụ Khởi động Ngày 1 | Sản phẩm Bàn giao Cụ thể | Tiêu chuẩn Nghiệm thu Kỹ thuật (DoD) |
| :---: | :--- | :--- | :--- |
| **TV1 (`ngthinh06`)** | CI/CD, Lưới 1km, Trục ngày & Audit trạm | `.github/workflows/ci.yml`, `dim_grid_1km` v1.0, `dim_date.parquet`, Báo cáo audit trạm | CI Actions báo xanh; lưới > 3,000 ô; đúng 1,827 dòng ngày; audit trạm OpenAQ/AirNow/PAM Air 5 năm hoàn tất. |
| **TV2 (`hunganh`)** | Trích xuất 15 biến tĩnh & Audit vệ tinh GEE | `dim_grid_1km.parquet` v1.1, `docs/sources_satellite.md` | Cập nhật đủ 15 biến tĩnh vào lưới 1km; kết nối thành công 3 ImageCollections GEE. |
| **TV3 (`minh`)** | Audit CDS API & Native pixel extraction | `docs/sources_meteo.md`, script `ingest_era5_cams.py` | Kết nối thành công CDS API; xác định đúng 45 tọa độ native cells ERA5-Land. |

