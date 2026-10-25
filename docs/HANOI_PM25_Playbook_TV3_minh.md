> Hợp đồng bàn giao v2.0: N_GRID = 3.610 ô giao ranh giới (không tính grid_unknown); 3.363 ô có tâm trong ranh giới chỉ là tập con. N_DAYS = 1.826, date_id = YYYYMMDD; khung phân tích = 6.591.860 dòng, loại cả hai unknown. Xem [SPINE_HANDOFF.md](SPINE_HANDOFF.md) và grid_manifest.json. Nguồn ranh giới: GSO / HDX COD-AB v02 (01/07/2025), chọn Ha Noi / VN01; xem provenance đi kèm. Dùng cố định cho chuỗi 2021–2025.

# HANOI_PM25 — ACTION PLAYBOOK: MINH
## Atmospheric Reanalysis & Meteorological Physics Engineer
**Dự án:** Spatio-Temporal Data Lakehouse for Hanoi PM2.5 (2021–2025)  
**Phạm vi:** Cẩm nang hành động chuyên sâu và hướng dẫn từng bước dành riêng cho kỹ sư **`minh`**.


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

<div class="diagram-wrapper"><div class="diagram-title">SƠ ĐỒ 7: LỘ TRÌNH THỰC THI 6 GIAI ĐOẠN & CỔNG NGHIỆM THU (GATE 1..6)</div><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 460" width="960" height="460">
  <defs>
    <style>
      .bg { fill: #FFFFFF; }
      .title { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; font-size: 18px; fill: #14263D; }
      .subtitle { font-family: 'Segoe UI', Arial, sans-serif; font-size: 12px; fill: #64748B; }
      .p-card { rx: 6; ry: 6; stroke-width: 1.5; fill: #FFFFFF; }
      .p-gate { rx: 12; ry: 12; fill: #FEF3C7; stroke: #F59E0B; stroke-width: 1.5; }
      .gate-txt { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; font-size: 10.5px; fill: #B45309; }
      .p-title { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; font-size: 12px; }
      .p-desc { font-family: 'Segoe UI', Arial, sans-serif; font-size: 10px; fill: #475569; }
      .p-arr { stroke: #94A3B8; stroke-width: 1.5; fill: none; marker-end: url(#ah-b); }
    </style>
    <marker id="ah-b" markerWidth="6" markerHeight="5" refX="5" refY="2.5" orient="auto">
      <polygon points="0 0, 6 2.5, 0 5" fill="#94A3B8" />
    </marker>
  </defs>

  <rect width="960" height="460" class="bg" />
  <text x="40" y="38" class="title">LỘ TRÌNH THỰC THI 6 GIAI ĐOẠN &amp; CỔNG NGHIỆM THU (ACCEPTANCE GATES)</text>
  <text x="40" y="56" class="subtitle">Điều kiện tiên quyết mở cổng (Definition of Done) từ Phase 1 đến Phase 6</text>

  <!-- ROW 1: PHASES 1, 2, 3 -->
  <!-- PHASE 1 -->
  <rect x="40" y="85" width="260" height="150" class="p-card" stroke="#3B82F6" />
  <rect x="40" y="85" width="260" height="28" rx="6" ry="6" fill="#EFF6FF" />
  <text x="50" y="104" class="p-title" fill="#1D4ED8">PHASE 1: FOUNDATION &amp; AUDIT</text>
  <text x="50" y="128" class="p-desc">• Sinh lưới 1km EPSG:3405 &amp; manifest</text>
  <text x="50" y="143" class="p-desc">• Trục ngày 5 năm (1,826 ngày + -1)</text>
  <text x="50" y="158" class="p-desc">• Audit độ phủ 9 nguồn (2021–2025)</text>
  <text x="50" y="173" class="p-desc">• Trích xuất 15 biến tĩnh vào lưới 1km</text>
  <!-- GATE 1 -->
  <rect x="50" y="195" width="240" height="28" class="p-gate" />
  <text x="60" y="213" class="gate-txt">GATE 1: N_GRID đóng băng, Audit Pass</text>

  <!-- ARROW 1 -> 2 -->
  <path d="M 300 160 L 340 160" class="p-arr" />

  <!-- PHASE 2 -->
  <rect x="350" y="85" width="260" height="150" class="p-card" stroke="#10B981" />
  <rect x="350" y="85" width="260" height="28" rx="6" ry="6" fill="#ECFDF5" />
  <text x="360" y="104" class="p-title" fill="#047857">PHASE 2: RAW INGESTION</text>
  <text x="360" y="128" class="p-desc">• Mở rộng cửa sổ UTC ICT</text>
  <text x="360" y="143" class="p-desc">• Ghi lũy đẳng append_idempotent_raw</text>
  <text x="360" y="158" class="p-desc">• Tâm pixel gốc (~45 ERA5, ~8 BLH)</text>
  <text x="360" y="173" class="p-desc">• Mock seeder 5 năm tất định cho CI</text>
  <!-- GATE 2 -->
  <rect x="360" y="195" width="240" height="28" class="p-gate" />
  <text x="370" y="213" class="gate-txt">GATE 2: Đủ 5 năm, Duplicate Hash == 0</text>

  <!-- ARROW 2 -> 3 -->
  <path d="M 610 160 L 650 160" class="p-arr" />

  <!-- PHASE 3 -->
  <rect x="660" y="85" width="260" height="150" class="p-card" stroke="#F59E0B" />
  <rect x="660" y="85" width="260" height="28" rx="6" ry="6" fill="#FFFBEB" />
  <text x="670" y="104" class="p-title" fill="#B45309">PHASE 3: STAGING &amp; QC</text>
  <text x="670" y="128" class="p-desc">• Giữ 100% chuỗi giờ, hòa giải revision</text>
  <text x="670" y="143" class="p-desc">• Lọc &gt;= 18h hợp lệ, Köhler kappa=0.35</text>
  <text x="670" y="158" class="p-desc">• Khử tích lũy mưa, gió V_scalar &amp; P</text>
  <text x="670" y="173" class="p-desc">• Cờ chẩn đoán MNAR AOD mùa đông</text>
  <!-- GATE 3 -->
  <rect x="670" y="195" width="240" height="28" class="p-gate" />
  <text x="680" y="213" class="gate-txt">GATE 3: 100% ngày &gt;=18h, V_vec &lt;= V_sca</text>

  <!-- ARROW 3 -> 4 (DOWN & LEFT) -->
  <path d="M 790 235 L 790 270 L 610 270 L 610 305" class="p-arr" />

  <!-- ROW 2: PHASES 4, 5, 6 -->
  <!-- PHASE 4 -->
  <rect x="40" y="270" width="260" height="150" class="p-card" stroke="#8B5CF6" />
  <rect x="40" y="270" width="260" height="28" rx="6" ry="6" fill="#FAF5FF" />
  <text x="50" y="289" class="p-title" fill="#6D28D9">PHASE 4: CORE &amp; MARTS</text>
  <text x="50" y="313" class="p-desc">• Star Schema: 3 Dims + 3 Facts</text>
  <text x="50" y="328" class="p-desc">• Feature Mart: SẠCH NHÃN 100%</text>
  <text x="50" y="343" class="p-desc">• EDA Mart: Khớp đúng |S| dòng Spine</text>
  <text x="50" y="358" class="p-desc">• Matched View: Ghép trạm 100%</text>
  <!-- GATE 4 -->
  <rect x="50" y="380" width="240" height="28" class="p-gate" />
  <text x="60" y="398" class="gate-txt">GATE 4: Marts khớp |S|, 0 rò rỉ nhãn</text>

  <!-- ARROW 4 -> 5 -->
  <path d="M 300 345 L 340 345" class="p-arr" />

  <!-- PHASE 5 -->
  <rect x="350" y="270" width="260" height="150" class="p-card" stroke="#EC4899" />
  <rect x="350" y="270" width="260" height="28" rx="6" ry="6" fill="#FDF2F8" />
  <text x="360" y="289" class="p-title" fill="#BE185D">PHASE 5: QUALITY GATES</text>
  <text x="360" y="313" class="p-desc">• 9 quy tắc SQL đối chiếu manifest động</text>
  <text x="360" y="328" class="p-desc">• Mutation testing tiêm 4 lỗi trong sandbox</text>
  <text x="360" y="343" class="p-desc">• Bắt gọn Spine drop, Leak, FK, QC</text>
  <text x="360" y="358" class="p-desc">• Tích hợp CI/CD tự động trên GitHub</text>
  <!-- GATE 5 -->
  <rect x="360" y="380" width="240" height="28" class="p-gate" />
  <text x="370" y="398" class="gate-txt">GATE 5: 9/9 SQL Pass, Mutation 100%</text>

  <!-- ARROW 5 -> 6 -->
  <path d="M 610 345 L 650 345" class="p-arr" />

  <!-- PHASE 6 -->
  <rect x="660" y="270" width="260" height="150" class="p-card" stroke="#14263D" />
  <rect x="660" y="270" width="260" height="28" rx="6" ry="6" fill="#F1F5F9" />
  <text x="670" y="289" class="p-title" fill="#0F172A">PHASE 6: SPATIO-TEMPORAL EDA</text>
  <text x="670" y="313" class="p-desc">• 6 Chuyên đề phân tích không-thời gian</text>
  <text x="670" y="328" class="p-desc">• Bootstrap, STL 5n, Moran's I, Variogram</text>
  <text x="670" y="343" class="p-desc">• Xuất bản biểu đồ vào docs/figures/</text>
  <text x="670" y="358" class="p-desc">• Báo cáo Sẵn sàng Dữ liệu được ký duyệt</text>
  <!-- GATE 6 -->
  <rect x="670" y="380" width="240" height="28" class="p-gate" fill="#D1FAE5" stroke="#10B981" />
  <text x="680" y="398" class="gate-txt" fill="#065F46">GATE 6 (FINAL): Tag v2.1 Ratified</text>
</svg><div class="diagram-caption">Lộ trình từ Foundation, Ingestion, Staging, Core, Quality đến hoàn thiện 6 Chuyên đề EDA</div></div>


## 7. HƯỚNG DẪN THỰC THI CHI TIẾT DÀNH CHO THÀNH VIÊN 3: `minh`
**Vai trò:** Atmospheric Reanalysis & Meteorological Physics Engineer  
**Trọng tâm:** Thu thập khí quyển ERA5/CAMS/BLH từ GEE/CDS, Khử tích lũy lượng mưa, Tính gió vô hướng & độ bền vững, Tính độ ẩm tương đối Magnus-Tetens bàn giao mở khóa TV1, Broadcast lưới 1km.

---

### Task TV3-01: Kiểm toán Kết nối Copernicus CDS API & GEE Khí quyển
* **Mục tiêu:** Kiểm tra tài khoản, API key và vùng bao phủ của ERA5-Land, CAMS và ERA5 BLH.
* **Input:** File cấu hình `~/.cdsapirc` chứa CDS API key, tài khoản GEE.
* **Output:** `docs/sources_meteo.md`.
* **Cách làm từng bước:**
  1. Viết script `ingestion/audit/audit_meteo_sources.py` sử dụng thư viện `cdsapi`.
  2. Gửi test request tải 1 ngày mẫu của biến `2m_temperature`, `total_precipitation`, `10m_u_component_of_wind`, `10m_v_component_of_wind`, `surface_pressure` từ dataset `reanalysis-era5-land`.
  3. Gửi test request lấy biến `boundary_layer_height` từ dataset `reanalysis-era5-single-levels`.
  4. Lập bảng từ điển nguồn, ghi rõ đơn vị gốc (Kelvin, mét, Pa) và hệ số quy đổi.
* **Lệnh chạy:** `python run.py audit --component meteo`
* **DoD:** Kết nối thành công CDS API và GEE, xuất từ điển nguồn khí quyển.

---

### Task TV3-02: Thu thập Thô Khí quyển theo Tọa độ Native Pixel Cells (Tránh Quá tải Quota)
* **Mục tiêu:** Tải toàn bộ chuỗi giờ khí quyển 5 năm 2021–2025 về Bronze mà không làm sập quota API.
* **Input:** Tọa độ ranh giới Hà Nội.
* **Output:** `data/raw/atmospheric/`.
* **Cách làm từng bước:**
  1. **Kỹ thuật trích xuất Native Cells:**
     - Độ phân giải ERA5-Land là ~9 km $ightarrow$ Chỉ có đúng **~45 điểm pixel gốc** bao phủ toàn bộ Hà Nội.
     - Độ phân giải BLH là ~31 km $ightarrow$ Chỉ có đúng **~8 điểm pixel gốc**.
     - Thay vì truy vấn 3,360 ô lưới 1km (làm gửi hàng triệu request gây cạn kiệt quota), TV3 chỉ tải đúng 45 tọa độ tâm pixel ERA5-Land và 8 tọa độ tâm pixel BLH.
  2. Tải chuỗi giờ từ `2020-12-31T16:00:00Z` đến `2026-01-01T08:00:00Z` (đủ 24h giờ Hà Nội).
  3. Lưu append lũy đẳng vào `data/raw/atmospheric/source=era5_land/year=YYYY/month=MM/data.parquet` và `source=era5_blh/`.
* **Lệnh chạy:** `python run.py ingest --source meteo`
* **DoD:** Dữ liệu thô khí quyển được lưu trữ đầy đủ theo pixel gốc.

---

### Task TV3-03: Khử Tích lũy Lượng mưa Giờ ERA5-Land
* **Mục tiêu:** Chuyển đổi lượng mưa tích lũy của mô hình dự báo thành lượng mưa thực tế từng giờ.
* **Input:** Biến `total_precipitation` (`tp`, đơn vị mét) trong Bronze ERA5-Land.
* **Output:** Cột lượng mưa giờ `precip_h` (đơn vị mm).
* **Cách làm từng bước:**
  1. Chuyển đổi đơn vị từ mét sang milimét: `tp_mm = tp * 1000.0`.
  2. ERA5-Land tích lũy mưa từ đầu chu kỳ dự báo (reset về 0 tại mốc 00:00 UTC). Áp dụng công thức khử tích lũy:
     $$\text{precip\_h} = \begin{cases} \text{tp}_h - \text{tp}_{h-1} & \text{nếu } h > 0 \\ \text{tp}_h & \text{nếu } h = 0 \text{ (mốc reset)} \end{cases}$$
  3. Nếu do sai số làm tròn số học mà $\text{precip\_h} < 0$, gán bằng 0: `precip_h = max(0.0, precip_h)`.
* **Lệnh chạy:** `python -m transform.staging.gee.process_meteo_precip`
* **DoD:** Lượng mưa giờ không bị tích lũy dồn, giá trị $\ge 0$.

---

### Task TV3-04: Tính Vận tốc Gió Vô hướng & Tỷ số Bền vững Hướng Gió
* **Mục tiêu:** Tính toán độ lớn gió thực tế và mức độ ổn định hướng gió ảnh hưởng tới khuếch tán bụi PM2.5.
* **Input:** Hai thành phần vận tốc gió $u_{10}$ (đông-tây) và $v_{10}$ (bắc-nam) hàng giờ.
* **Output:** Cột `wind_speed_scalar_ms` và `wind_persistence`.
* **Cách làm từng bước:**
  1. Tính độ lớn gió từng giờ: $w_h = \sqrt{u_{10,h}^2 + v_{10,h}^2}$.
  2. Tốc độ gió vô hướng trung bình 24h:
     $$V_{\text{scalar}} = \frac{1}{24} \sum_{h=1}^{24} w_h$$
  3. Tốc độ gió có hướng trung bình 24h:
     $$V_{\text{vector}} = \sqrt{\left(\frac{1}{24}\sum u_{10,h}\right)^2 + \left(\frac{1}{24}\sum v_{10,h}\right)^2}$$
  4. Tính tỷ số bền vững hướng gió (Wind Persistence Ratio):
     $$P = \frac{V_{\text{vector}}}{\max(V_{\text{scalar}}, 10^{-4})} \in [0, 1]$$
* **Lệnh chạy:** `python -m transform.staging.gee.process_meteo_wind`
* **DoD:** Tốc độ gió vô hướng và tỷ số bền vững nằm trong miền vật lý $[0, 1]$.

---

### Task TV3-05: Tính Độ ẩm Tương đối Magnus-Tetens & Bàn giao Ngay Bảng RH cho TV1
* **Mục tiêu:** Tính toán độ ẩm tương đối $RH$ chính xác và bàn giao ngay để mở khóa nút thắt hiệu chỉnh ẩm PAM Air cho TV1 (ADR-011).
* **Input:** Nhiệt độ 2m ($T$) và Điểm sương 2m ($T_d$) từ ERA5-Land.
* **Output:** `data/staging/stg_meteo_daily.parquet` (chứa cột `rh_mean_pct`).
* **Cách làm từng bước:**
  1. Chuyển đổi nhiệt độ từ Kelvin sang độ C: $T_{^\circ\text{C}} = T_{\text{K}} - 273.15$, $T_{d,^\circ\text{C}} = T_{d,\text{K}} - 273.15$.
  2. Áp dụng công thức Magnus-Tetens tính độ ẩm tương đối từng giờ:
     $$RH_h = 100 \times \frac{\exp\left(\frac{17.625 \cdot T_{d,^\circ\text{C}}}{243.04 + T_{d,^\circ\text{C}}}\right)}{\exp\left(\frac{17.625 \cdot T_{^\circ\text{C}}}{243.04 + T_{^\circ\text{C}}}\right)}$$
  3. Giới hạn giá trị $RH_h = \min(100.0, \max(0.0, RH_h))$.
  4. Gom trung bình 24h theo giờ địa phương Hà Nội, xuất cột `rh_mean_pct` vào `data/staging/stg_meteo_daily.parquet`.
  5. **BÀN GIAO NGAY CHO TV1:** Báo cho TV1 biết file đã sẵn sàng để TV1 chạy task `TASK-TV1-09` (Köhler calibration).
* **Lệnh chạy:** `python -m transform.staging.gee.process_meteo_eo`
* **Lệnh tự kiểm tra:** `python -c "import duckdb; con = duckdb.connect(); cnt = con.execute('SELECT COUNT(*) FROM "data/staging/stg_meteo_daily.parquet" WHERE rh_mean_pct IS NOT NULL').fetchone()[0]; assert cnt > 0; print('RH Table for TV1 unblocked! Total rows:', cnt)"`
* **DoD:** Xuất bảng Staging Meteo thành công, cột RH đầy đủ, giải phóng nút thắt liên thành viên.

---

### Task TV3-06: Broadcast Dữ liệu Khí tượng sang Ô lưới 1km & Tạo Fact Khí tượng
* **Mục tiêu:** Gán các biến khí tượng từ 45 pixel gốc sang ~3,360 ô lưới 1km theo `grid_id`.
* **Input:** `stg_meteo_daily.parquet`, `dim_grid_1km.parquet`, `dim_date.parquet`.
* **Output:** `data/core/fct_grid_meteo_daily.parquet`.
* **Cách làm từng bước:**
  1. Dùng thuật toán Nearest-Neighbor (k láng giềng gần nhất) hoặc Spatial Join trong `EPSG:3405` để gán giá trị khí tượng của pixel gốc gần nhất cho từng ô lưới 1km.
  2. Nối với `dim_date` để lấy khóa thay thế `date_id`.
  3. Xuất file `data/core/fct_grid_meteo_daily.parquet` bàn giao cho TV2 để đóng gói Star Schema.
* **Lệnh chạy:** `python -m transform.staging.broadcast_meteo_to_grid`
* **DoD:** Toàn bộ ô lưới có đủ thông tin nhiệt độ, độ ẩm, lượng mưa, gió và BLH.

---

### Task TV3-07: Kiểm tra Tỷ lệ Đầy đủ Khí tượng trên Native Cells
* **Mục tiêu:** Xác nhận độ bao phủ dữ liệu khí tượng đạt chuẩn nghiệm thu.
* **Input:** `fct_grid_meteo_daily.parquet`.
* **Output:** Báo cáo kiểm định độ đầy đủ khí tượng.
* **Cách làm:** Kiểm tra tỷ lệ đầy đủ: $\ge 98\%$ đối với ERA5-Land và $\ge 95\%$ đối với BLH trong suốt 5 năm.
* **Lệnh chạy:** `python quality/check_meteo_completeness.py`
* **DoD:** Độ đầy đủ khí tượng vượt ngưỡng quy định.

---

### Task TV3-08: Thực hiện Spatio-Temporal EDA Chuyên đề 3 (STL & PBL/BLH Inversion)
* **Mục tiêu:** Phân rã chuỗi thời gian 5 năm và phân tích hiện tượng nghịch nhiệt mùa đông gây ô nhiễm không khí.
* **Input:** `fct_grid_meteo_daily`, `fct_ground_truth_daily`.
* **Output:** `notebooks/eda_03_stl_pbl_inversion.ipynb`.
* **Cách làm:**
  1. Áp dụng kỹ thuật phân rã chuỗi thời gian STL (Seasonal-Trend decomposition using LOESS) trên chuỗi nồng độ PM2.5 5 năm để tách xu hướng (Trend), mùa vụ (Seasonal) và phần dư (Residual).
  2. Khảo sát hiện tượng nghịch nhiệt: Vẽ tương quan giữa chiều cao lớp biên ban đêm (`blh_min_m`) với nồng độ PM2.5. Chỉ ra hiện tượng khi BLH co hẹp xuống dưới 300m vào mùa đông Hà Nội, bụi mịn bị bẫy sát mặt đất gây ra các đợt ô nhiễm nghiêm trọng.
* **Lệnh chạy:** `python run.py eda --topics 3`
* **DoD:** Notebook hoàn thành với biểu đồ STL và phân tích nghịch nhiệt lớp biên rõ nét.

---

### Task TV3-09: Thực hiện Spatio-Temporal EDA Chuyên đề 4 (Tương quan Đa nguồn & $n_{\text{eff}}$)
* **Mục tiêu:** Đo lường mức độ tương quan giữa PM2.5 với các biến môi trường và khử tự tương quan chuỗi.
* **Input:** `mart_grid_daily_features`, `mart_grid_daily_eda`.
* **Output:** `notebooks/eda_04_multisource_correlation.ipynb`.
* **Cách làm:**
  1. Tính ma trận tương quan hạng Spearman giữa PM2.5 với nhiệt độ, độ ẩm, tốc độ gió, lượng mưa, BLH, AOD, NO2 và mật độ đường.
  2. Chuỗi thời gian môi trường có tính tự tương quan (autocorrelation) cao, làm phồng mức ý nghĩa thống kê p-value. Áp dụng công thức cỡ mẫu hiệu dụng:
     $$n_{\text{eff}} = N \frac{1 - \rho_1}{1 + \rho_1}$$
     *(với $\rho_1$ là hệ số tự tương quan bậc 1 của chuỗi số liệu).*
* **Lệnh chạy:** `python run.py eda --topics 4`
* **DoD:** Notebook hoàn thành với ma trận tương quan Spearman và bảng cỡ mẫu hiệu dụng $n_{\text{eff}}$.

---

### Task TV3-10: Đóng góp Diễn giải Khí quyển cho Báo cáo Sẵn sàng Dữ liệu
* **Mục tiêu:** Hoàn thiện góc nhìn vật lý khí quyển trong báo cáo nghiệm thu dự án.
* **Output:** Phần Khí quyển & Lớp biên trong `docs/planning_v3/DATA_READINESS_REPORT.md`.


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

