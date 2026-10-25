> Hợp đồng bàn giao v2.0: N_GRID = 3.610 ô giao ranh giới (không tính grid_unknown); 3.363 ô có tâm trong ranh giới chỉ là tập con. N_DAYS = 1.826, date_id = YYYYMMDD; khung phân tích = 6.591.860 dòng, loại cả hai unknown. Xem [SPINE_HANDOFF.md](SPINE_HANDOFF.md) và grid_manifest.json. Nguồn ranh giới: GSO / HDX COD-AB v02 (01/07/2025), chọn Ha Noi / VN01; xem provenance đi kèm. Dùng cố định cho chuỗi 2021–2025.

# HANOI_PM25 — ACTION PLAYBOOK: NGTHINH06
## Data Architect, CI/CD Lead & Ground Truth Stations Owner
**Dự án:** Spatio-Temporal Data Lakehouse for Hanoi PM2.5 (2021–2025)  
**Phạm vi:** Cẩm nang hành động chuyên sâu và hướng dẫn từng bước dành riêng cho kỹ sư **`ngthinh06`**.


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

<div class="diagram-wrapper"><div class="diagram-title">SƠ ĐỒ 4: KHUNG LƯỚI KHÔNG GIAN 1KM & DATE SPINE 5 NĂM</div><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 460" width="960" height="460">
  <defs>
    <style>
      .bg { fill: #FFFFFF; }
      .title { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; font-size: 18px; fill: #14263D; }
      .subtitle { font-family: 'Segoe UI', Arial, sans-serif; font-size: 12px; fill: #64748B; }
      .c-box { rx: 8; ry: 8; stroke-width: 1.5; }
      .b-blue { fill: #EFF6FF; stroke: #3B82F6; }
      .b-green { fill: #ECFDF5; stroke: #10B981; }
      .b-purple { fill: #FAF5FF; stroke: #8B5CF6; }
      .h-txt { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; font-size: 14px; }
      .txt { font-family: 'Segoe UI', Arial, sans-serif; font-size: 11.5px; fill: #334155; }
      .hl { font-weight: 700; fill: #1E293B; }
      .math { font-family: 'Cambria Math', 'Times New Roman', serif; font-size: 14px; font-weight: 700; }
    </style>
  </defs>

  <rect width="960" height="460" class="bg" />
  <text x="40" y="38" class="title">NGUYÊN LÝ KHUNG LƯỚI KHÔNG GIAN &amp; TRỤC THỜI GIAN (SPINE MATRIX)</text>
  <text x="40" y="56" class="subtitle">Tích Descartes giữa Lưới 1km EPSG:3405 và Trục ngày 5 năm lịch định hình quy mô dữ liệu hồ chứa</text>

  <!-- SPATIAL BOX (LEFT) -->
  <rect x="40" y="80" width="260" height="340" class="c-box b-blue" />
  <text x="60" y="110" class="h-txt" fill="#1E40AF">1. CHIỀU KHÔNG GIAN</text>
  <text x="60" y="130" class="txt" font-weight="600">dim_grid_1km.parquet</text>
  
  <rect x="60" y="145" width="220" height="90" rx="5" ry="5" fill="#FFFFFF" stroke="#93C5FD" />
  <text x="70" y="168" class="txt"><tspan class="hl">Hệ quy chiếu:</tspan> VN-2000 / UTM 48N</text>
  <text x="70" y="186" class="txt"><tspan class="hl">Mã EPSG:</tspan> EPSG:3405 (chuẩn mét)</text>
  <text x="70" y="204" class="txt"><tspan class="hl">Độ phân giải:</tspan> 1,000m x 1,000m</text>
  <text x="70" y="222" class="txt"><tspan class="hl">Ranh giới:</tspan> hanoi_boundary.geojson</text>

  <rect x="60" y="250" width="220" height="150" rx="5" ry="5" fill="#FFFFFF" stroke="#93C5FD" />
  <text x="70" y="273" class="txt"><tspan class="hl">Số lượng ô:</tspan> N_GRID ô lưới</text>
  <text x="70" y="291" class="txt">(Ước lượng ban đầu ~3,360 ô)</text>
  <text x="70" y="315" class="txt"><tspan class="hl">Đóng băng metadata:</tspan></text>
  <text x="70" y="333" class="txt" fill="#2563EB">data/manifests/grid_manifest.json</text>
  <text x="70" y="353" class="txt">• Bắt buộc nạp động N_GRID</text>
  <text x="70" y="371" class="txt">• Nghiêm cấm hardcode số ô</text>
  <text x="70" y="389" class="txt">• Có 1 dòng grid_unknown</text>

  <!-- MULTIPLY SYMBOL -->
  <circle cx="340" cy="250" r="24" fill="#F1F5F9" stroke="#94A3B8" stroke-width="1.5" />
  <text x="333" y="258" font-family="'Segoe UI', sans-serif" font-size="24px" font-weight="700" fill="#475569">×</text>

  <!-- TEMPORAL BOX (MIDDLE) -->
  <rect x="380" y="80" width="260" height="340" class="c-box b-green" />
  <text x="400" y="110" class="h-txt" fill="#065F46">2. CHIỀU THỜI GIAN</text>
  <text x="400" y="130" class="txt" font-weight="600">dim_date.parquet</text>

  <rect x="400" y="145" width="220" height="90" rx="5" ry="5" fill="#FFFFFF" stroke="#86EFAC" />
  <text x="410" y="168" class="txt"><tspan class="hl">Phạm vi:</tspan> 2021-01-01 – 2025-12-31</text>
  <text x="410" y="186" class="txt"><tspan class="hl">Thời lượng:</tspan> Đúng 5 năm lịch</text>
  <text x="410" y="204" class="txt"><tspan class="hl">Xử lý nhuận:</tspan> 2024-02-29 (366 ngày)</text>
  <text x="410" y="222" class="txt"><tspan class="hl">Múi giờ:</tspan> Asia/Ho_Chi_Minh (UTC+7)</text>

  <rect x="400" y="250" width="220" height="150" rx="5" ry="5" fill="#FFFFFF" stroke="#86EFAC" />
  <text x="410" y="273" class="txt"><tspan class="hl">Số ngày lịch:</tspan> N_DAYS = 1,826 ngày</text>
  <text x="410" y="291" class="txt">• 2021: 365 | 2022: 365</text>
  <text x="410" y="309" class="txt">• 2023: 365 | 2024: 366 (nhuận)</text>
  <text x="410" y="327" class="txt">• 2025: 365</text>
  <text x="410" y="351" class="txt"><tspan class="hl">Bản ghi ngoại lệ:</tspan></text>
  <text x="410" y="369" class="txt">• date_id = -1 (ngày không xác định)</text>
  <text x="410" y="387" class="txt">• Tổng số dòng dim_date: 1,827</text>

  <!-- EQUALS SYMBOL -->
  <circle cx="680" cy="250" r="24" fill="#F1F5F9" stroke="#94A3B8" stroke-width="1.5" />
  <text x="673" y="258" font-family="'Segoe UI', sans-serif" font-size="24px" font-weight="700" fill="#475569">=</text>

  <!-- RESULT / SPINE BOX (RIGHT) -->
  <rect x="720" y="80" width="200" height="340" class="c-box b-purple" />
  <text x="735" y="110" class="h-txt" fill="#5B21B6">3. KHUNG XƯƠNG SPINE</text>
  <text x="735" y="130" class="txt" font-weight="600">Quy mô Bất biến Marts</text>

  <rect x="735" y="145" width="170" height="135" rx="5" ry="5" fill="#FFFFFF" stroke="#C4B5FD" />
  <text x="745" y="170" class="txt"><tspan class="hl">Tích Descartes:</tspan></text>
  <text x="745" y="190" class="math" fill="#6D28D9">S = G × D</text>
  <text x="745" y="215" class="txt"><tspan class="hl">Quy mô kỳ vọng:</tspan></text>
  <text x="745" y="235" class="math" fill="#DC2626">|S| = N_GRID × 1,826</text>
  <text x="745" y="255" class="txt" font-size="10.5px">(~6,135,360 dòng)</text>
  <text x="745" y="270" class="txt" font-size="10px" fill="#64748B">Khóa chính: (grid_id, date_id)</text>

  <rect x="735" y="295" width="170" height="105" rx="5" ry="5" fill="#FFFFFF" stroke="#C4B5FD" />
  <text x="745" y="318" class="txt"><tspan class="hl">Áp dụng bất biến cho:</tspan></text>
  <text x="745" y="338" class="txt">• fct_grid_meteo_daily</text>
  <text x="745" y="355" class="txt">• fct_grid_satellite_daily</text>
  <text x="745" y="372" class="txt">• mart_grid_daily_features</text>
  <text x="745" y="389" class="txt">• mart_grid_daily_eda</text>
</svg><div class="diagram-caption">Tích Descartes bất biến |S| = N_GRID × 1,826 dòng đảm bảo không drop hàng trên Feature Marts</div></div>


## 5. HƯỚNG DẪN THỰC THI CHI TIẾT DÀNH CHO THÀNH VIÊN 1: `ngthinh06`
**Vai trò:** Data Architect, CI/CD Lead & Ground Truth Stations Owner  
**Trọng tâm:** Xây dựng khung nền tảng CI/CD, Lưới không gian 1km, Trục ngày 5 năm, Thu thập và Tiền xử lý toàn bộ Trạm quan trắc mặt đất (OpenAQ, PAM Air).

---

### Task TV1-01: Thiết lập Codebase nền tảng, Runner `run.py` và CI/CD GitHub Actions
* **Mục tiêu:** Tạo bộ khung dự án và pipeline CI tự động kiểm tra code mỗi khi có Pull Request.
* **Input:** Cấu hình ruff, mypy, pytest.
* **Output:** `run.py`, `.github/workflows/ci.yml`, `common/io_parquet.py`.
* **Cách làm từng bước:**
  1. Viết `run.py` bằng `argparse` hoặc `click`, hỗ trợ các subcommand: `setup`, `lint`, `grid`, `audit`, `ingest`, `transform`, `quality`, `test-mutation`, `eda`, `all`, `clean`.
  2. Viết hàm `atomic_write_parquet(df, path)` trong `common/io_parquet.py`: ghi vào file tạm `.tmp` cùng thư mục rồi đổi tên (`os.replace`) để tránh lỗi hỏng file khi bị ngắt điện.
  3. Viết workflow GitHub Actions `.github/workflows/ci.yml` chạy trên `ubuntu-latest`:
     - Bước 1: `ruff check .`
     - Bước 2: `pytest tests/unit/`
     - Bước 3: `python run.py ingest --env ci_test`
     - Bước 4: `python run.py transform`
     - Bước 5: `python run.py quality`
     - Bước 6: `python run.py test-mutation`
* **Lệnh chạy:** `python run.py setup && python run.py lint`
* **Lệnh tự kiểm tra:** `python -c "import run; print('Runner OK')"`
* **DoD:** GitHub Actions chạy báo xanh 6 bước trên nhánh `develop`.

---

### Task TV1-02: Viết Module Băm SHA-256 Lũy đẳng và Trình sinh Mock Data CI
* **Mục tiêu:** Cung cấp công cụ ghi append không trùng lặp cho cả nhóm và bộ mock data phục vụ CI offline.
* **Input:** Thuật toán băm SHA-256.
* **Output:** `common/hashing.py`, `ingestion/mock_seeder.py`.
* **Cách làm từng bước:**
  1. Trong `common/hashing.py`, viết hàm `compute_row_hash(row_dict)`: ghép các giá trị chính thành chuỗi UTF-8, băm qua `hashlib.sha256().hexdigest()`.
  2. Viết hàm `append_idempotent_raw_parquet(new_df, target_path)`: Đọc file cũ nếu tồn tại, lấy tập hợp mã băm `set(_row_hash)`, lọc bỏ các dòng trong `new_df` có hash đã tồn tại, sau đó nối thêm và ghi đè an toàn.
  3. Viết `ingestion/mock_seeder.py`: Dùng numpy sinh 100 dòng mẫu chuẩn schema cho cả 9 nguồn dữ liệu, lưu vào `data/raw/` khi chạy cờ `--env ci_test`.
* **Lệnh chạy:** `pytest tests/unit/test_hashing.py`
* **Lệnh tự kiểm tra:** `python ingestion/mock_seeder.py && python -c "import os; assert os.path.exists('data/raw')"`
* **DoD:** Hàm ghi lũy đẳng chạy 2 lần liên tiếp không làm tăng số dòng bản ghi.

---

### Task TV1-03: Sinh Lưới Không gian 1km `EPSG:3405` & Đóng băng Manifest
* **Mục tiêu:** Tạo khung lưới 1km bao phủ trọn vẹn Hà Nội và đóng băng metadata.
* **Input:** File ranh giới hành chính Hà Nội `data/reference/hanoi_boundary.geojson` (hoặc GeoJSON).
* **Output:** `data/manifests/grid_manifest.json`, `data/core/dim_grid_1km.parquet` v1.0.
* **Cách làm từng bước:**
  1. Đọc ranh giới bằng `geopandas`, chuyển hệ tọa độ sang `EPSG:3405`: `gdf = gdf.to_crs("EPSG:3405")`.
  2. Lấy `xmin, ymin, xmax, ymax = gdf.total_bounds`. Chia lưới bước nhảy 1,000m: `np.arange(xmin, xmax, 1000)`.
  3. Tạo hình chữ nhật `shapely.geometry.box(x, y, x+1000, y+1000)`. Lấy các ô có giao thoa với ranh giới Hà Nội (`cell.intersects(boundary_union)`).
  4. Đặt mã ô `grid_id = f"cell_{int(x)}_{int(y)}"`, tính tâm ô `centroid_x = x + 500`, `centroid_y = y + 500`.
  5. Tính SHA-256 của file ranh giới gốc. Lưu metadata gồm `grid_crs`, `cell_size_m: 1000`, `total_cells`, `boundary_sha256` vào `grid_manifest.json`.
  6. Xuất GeoParquet 1.1.0 vào `data/core/dim_grid_1km.parquet` v1.0.
* **Lệnh chạy:** `python run.py grid`
* **Lệnh tự kiểm tra:** `python -c "import duckdb; con = duckdb.connect(); cnt = con.execute('SELECT COUNT(*) FROM "data/core/dim_grid_1km.parquet"').fetchone()[0]; assert cnt > 3000; print('Total grid cells:', cnt)"`
* **DoD:** Số ô lưới > 3,000 ô, manifest đóng băng mã băm SHA-256. Bàn giao file cho TV2.

---

### Task TV1-04: Xây dựng Trục Ngày 5 năm `dim_date.parquet`
* **Mục tiêu:** Tạo trục thời gian bất biến cho 5 năm lịch 2021–2025.
* **Input:** Khoảng thời gian `2021-01-01` đến `2025-12-31`.
* **Output:** `data/core/dim_date.parquet` (đúng 1,827 dòng).
* **Cách làm từng bước:**
  1. Dùng `polars` hoặc `pandas` tạo chuỗi ngày từ `2021-01-01` đến `2025-12-31` (1,826 ngày lịch, gồm ngày nhuận `2024-02-29`).
  2. Đánh số khóa thay thế `date_id = YYYYMMDD (ví dụ 20240229); unknown = -1`.
  3. Trích xuất các trường: `year`, `month`, `day`, `day_of_week`, `quarter`, `is_weekend`, `is_leap_year`.
  4. Thêm 1 dòng danh định: `date_id = -1`, `date_actual = 1970-01-01`, `year = -1` (dành cho các bản ghi trôi nổi không khớp ngày).
  5. Xuất file `dim_date.parquet`.
* **Lệnh chạy:** `python run.py date`
* **Lệnh tự kiểm tra:** `python -c "import duckdb; con = duckdb.connect(); cnt = con.execute('SELECT COUNT(*) FROM "data/core/dim_date.parquet"').fetchone()[0]; assert cnt == 1827; print('Date spine OK: 1,827 rows')"`
* **DoD:** Bảng có đúng 1,827 dòng, không khuyết thiếu bất kỳ ngày nào trong 5 năm.

---

### Task TV1-05: Kiểm toán Độ phủ Trạm Mặt đất Thực tế 5 năm (OpenAQ, PAM Air)
* **Mục tiêu:** Đánh giá số lượng trạm, thời gian hoạt động và tỷ lệ khuyết thiếu của các trạm đo thực tế tại Hà Nội.
* **Input:** API OpenAQ v3, AirNow, API PAM Air.
* **Output:** `docs/ground_truth_audit_report.md`.
* **Cách làm từng bước:**
  1. Viết script `ingestion/audit/audit_ground_truth_coverage.py`.
  2. Gửi request lấy danh sách trạm trong bounding box Hà Nội từ OpenAQ (`/v3/locations`) và PAM Air.
  3. Kiểm tra xem timestamp của từng nguồn là thời điểm bắt đầu đo (`period_start`) hay kết thúc đo (`period_end`) để tránh lệch 1 giờ.
  4. Thống kê số trạm đo hoạt động liên tục trên 3 năm và xuất bảng tổng hợp.
* **Lệnh chạy:** `python run.py audit`
* **Lệnh tự kiểm tra:** `python -c "import os; assert os.path.exists('docs/ground_truth_audit_report.md')"`
* **DoD:** Báo cáo kiểm toán xác định rõ danh sách trạm và quy ước timestamp.

---

### Task TV1-06: Thu thập Thô Trạm Chuẩn Tier 1 (OpenAQ v3 & AirNow)
* **Mục tiêu:** Tải chuỗi giờ PM2.5 5 năm từ các trạm đo chuẩn quốc tế / cơ quan môi trường.
* **Input:** API Endpoint OpenAQ v3, API AirNow (Đại sứ quán Mỹ tại Hà Nội).
* **Output:** `data/raw/ground_truth/source=openaq/` và `source=airnow/`.
* **Cách làm từng bước:**
  1. Mở rộng cửa sổ thời gian UTC: từ `2020-12-31T16:00:00Z` đến `2026-01-01T08:00:00Z` (đảm bảo chuyển sang giờ Hà Nội `UTC+7` đủ 24h).
  2. Tải dữ liệu từng tháng để tránh timeout kết nối.
  3. Tính `_row_hash` cho từng bản ghi bằng hàm của TV1-02.
  4. Ghi phân vùng Hive: `data/raw/ground_truth/source=openaq/year=YYYY/month=MM/data.parquet`.
* **Lệnh chạy:** `python run.py ingest --source openaq`
* **Lệnh tự kiểm tra:** `python -c "import glob; files = glob.glob('data/raw/ground_truth/source=openaq/**/*.parquet', recursive=True); assert len(files) > 0; print('OpenAQ Raw files:', len(files))"`
* **DoD:** Dữ liệu được lưu dạng append lũy đẳng theo phân vùng Hive.

---

### Task TV1-07: Thu thập Thô Cảm biến Giá rẻ Tier 2 (PAM Air)
* **Mục tiêu:** Thu thập dữ liệu cảm biến quang học cộng đồng mạng lưới PAM Air 5 năm.
* **Input:** API PAM Air hoặc dữ liệu trích xuất từ nền tảng PAM Air.
* **Output:** `data/raw/ground_truth/source=pamair/`.
* **Cách làm từng bước:**
  1. Đọc danh sách ID các trạm PAM Air trong địa giới Hà Nội.
  2. Tải chuỗi giờ PM2.5 và độ ẩm (nếu trạm có sensor RH).
  3. Gán metadata: `source = 'pamair'`, `tier = 2`, `instrument_type = 'low_cost_optical'`.
  4. Ghi lũy đẳng có mã băm SHA-256 vào `data/raw/ground_truth/source=pamair/year=YYYY/month=MM/data.parquet`.
* **Lệnh chạy:** `python run.py ingest --source pamair`
* **Lệnh tự kiểm tra:** `python -c "import glob; files = glob.glob('data/raw/ground_truth/source=pamair/**/*.parquet', recursive=True); assert len(files) > 0; print('PAM Air Raw files:', len(files))"`
* **DoD:** Dữ liệu thô lưu trữ đầy đủ, phân vùng đúng cấu trúc.

---

### Task TV1-08: Chuẩn hóa Staging Chuỗi giờ Trạm & Gán Cờ QC Phân tầng
* **Mục tiêu:** Chuyển sang giờ địa phương Hà Nội, phát hiện số liệu lỗi, giữ 100% bản ghi chuỗi giờ.
* **Input:** Dữ liệu Bronze tại `data/raw/ground_truth/`.
* **Output:** `data/staging/stg_ground_truth_hourly.parquet`.
* **Cách làm từng bước:**
  1. Chuyển đổi toàn bộ timestamp sang giờ `Asia/Ho_Chi_Minh` (`UTC+7`): `datetime_local = datetime_utc + INTERVAL 7 HOUR`.
  2. Hòa giải các bản ghi trùng giờ bằng DuckDB Window Function: lấy bản ghi cập nhật mới nhất (`ROW_NUMBER() OVER (PARTITION BY station_id, time_local ORDER BY ingested_at DESC) = 1`).
  3. Gán cờ cứng (Hard Exclude Flags):
     - Giá trị âm: `pm25 < 0` $ightarrow$ gán `qc_flag = 1`.
     - Giá trị vượt ngưỡng vật lý: `pm25 > 1000` $ightarrow$ gán `qc_flag = 2`.
     - Kẹt số liên tục (Flatline $\ge 6\text{h}$): gán `qc_flag = 3`.
  4. Gán cờ nghi vấn (Soft Suspicious Flags):
     - Lọc ngoại lai cục bộ Hampel (cửa sổ 7 giờ lệch $> 3\sigma$): gán `is_hampel_outlier = 1`.
     - Độ ẩm không khí cao $RH > 85\%$: gán `is_high_humidity_warning = 1`.
  5. **Giữ nguyên 100% bản ghi** (kể cả bản ghi bị gắn cờ), lưu vào `stg_ground_truth_hourly.parquet`.
* **Lệnh chạy:** `python -m transform.staging.ground_truth.qc_hourly_stations`
* **Lệnh tự kiểm tra:** `python -c "import duckdb; con = duckdb.connect(); cnt = con.execute('SELECT COUNT(*) FROM "data/staging/stg_ground_truth_hourly.parquet" WHERE qc_flag > 0').fetchone()[0]; print('Flagged hourly records:', cnt)"`
* **DoD:** Không dòng nào bị drop ở bảng giờ, cờ QC được gán đầy đủ.

---

### Task TV1-09: Hiệu chỉnh Độ ẩm κ-Köhler & Gom Ngày Lọc Khắt khe 18h
* **Mục tiêu:** Hiệu chỉnh khô cho cảm biến quang học PAM Air và lọc nghiêm ngặt trung bình ngày 24h.
* **Input:** `stg_ground_truth_hourly.parquet`, bảng RH khí quyển `stg_meteo_daily.parquet` từ TV3.
* **Output:** `data/staging/stg_ground_truth_daily.parquet`, `docs/cleaning_log.md`.
* **Cách làm từng bước:**
  1. Đọc bảng RH từ `stg_meteo_daily.parquet`. Nối với bảng giờ theo `grid_id` (hoặc tọa độ trạm).
  2. Với các trạm PAM Air (`tier = 2`), nếu $RH > 70\%$, áp dụng công thức Köhler ($\kappa = 0.35$):
     $$\text{PM}_{2.5,\text{dry}} = \frac{\text{PM}_{2.5,\text{raw}}}{1 + 0.35 \cdot \frac{RH / 100}{1 - RH / 100}}$$
     *(Nếu trạm có cảm biến RH riêng thì dùng RH trạm; nếu thiếu thì lấy RH ERA5 từ TV3).*
  3. Gom ngày theo giờ địa phương Hà Nội:
     ```sql
     SELECT 
         station_id,
         CAST(time_local AS DATE) AS date,
         AVG(pm25_calibrated) AS pm25_daily_mean,
         COUNT(CASE WHEN qc_flag = 0 THEN 1 END) AS valid_hours_count
     FROM stg_ground_truth_hourly
     GROUP BY station_id, CAST(time_local AS DATE)
     HAVING valid_hours_count >= 18; -- LỌC NGHIÊM NGẶT >= 18H
     ```
  4. Các ngày có `< 18` giờ hợp lệ bị loại bỏ và ghi tỷ lệ loại bỏ vào `docs/cleaning_log.md`.
  5. Xuất `stg_ground_truth_daily.parquet`.
* **Lệnh chạy:** `python -m transform.staging.ground_truth.aggregate_daily_stations`
* **Lệnh tự kiểm tra:** `python -c "import duckdb; con = duckdb.connect(); inv = con.execute('SELECT COUNT(*) FROM "data/staging/stg_ground_truth_daily.parquet" WHERE valid_hours_count < 18').fetchone()[0]; assert inv == 0; print('Strict 18h Filter OK: 0 invalid rows')"`
* **DoD:** 100% bản ghi trong bảng ngày có từ 18 đến 24 giờ hợp lệ.

---

### Task TV1-10: Spatial Join Trạm vào Lưới 1km & Phân loại Vi môi trường `dim_station`
* **Mục tiêu:** Xác định tọa độ ô lưới và phân loại trạm ven đường vs nền đô thị.
* **Input:** `stg_ground_truth_daily`, `dim_grid_1km.parquet`, dữ liệu đường OSM.
* **Output:** `data/core/dim_station.parquet`.
* **Cách làm từng bước:**
  1. Lấy danh sách duy nhất các trạm và tọa độ kinh vĩ độ.
  2. Chuyển tọa độ trạm sang `EPSG:3405`: `stations_gdf = stations_gdf.to_crs("EPSG:3405")`.
  3. Thực hiện phép Spatial Join `sjoin` với `dim_grid_1km.parquet` để tìm ra `grid_id` chứa trạm.
  4. Tính khoảng cách Euclidean ngắn nhất từ trạm tới mạng lưới đường chính OSM (`primary`, `trunk`, `motorway`):
     - Nếu `distance <= 50m` $ightarrow$ gán `station_type = 'Roadside'`.
     - Nếu `distance > 50m` $ightarrow$ gán `station_type = 'Background'`.
  5. Xuất `data/core/dim_station.parquet`.
* **Lệnh chạy:** `python -m transform.core.classify_stations`
* **Lệnh tự kiểm tra:** `python -c "import duckdb; con = duckdb.connect(); res = con.execute('SELECT station_type, COUNT(*) FROM "data/core/dim_station.parquet" GROUP BY station_type').fetchall(); print('Station classification:', res)"`
* **DoD:** Mọi trạm đều có `grid_id` hợp lệ và được phân loại Roadside hoặc Background.

---

### Task TV1-11: Đóng gói Fact Trạm Ngày `fct_ground_truth_daily.parquet`
* **Mục tiêu:** Tạo bảng sự kiện trạm ngày chuẩn Star Schema kết nối khóa ngoại với Dims.
* **Input:** `stg_ground_truth_daily`, `dim_station`, `dim_date`.
* **Output:** `data/core/fct_ground_truth_daily.parquet`.
* **Cách làm từng bước:**
  1. Đọc `stg_ground_truth_daily.parquet`.
  2. `JOIN` với `dim_date` trên trường `date_actual` để lấy khóa thay thế `date_id`.
  3. `JOIN` với `dim_station` để lấy `station_id` và `grid_id`.
  4. Lưu các cột: `station_id`, `grid_id`, `date_id`, `pm25_daily_mean`, `valid_hours_count`, `tier`, `instrument_type`.
  5. Xuất file `fct_ground_truth_daily.parquet` bàn giao cho TV2 để tích hợp Star Schema.
* **Lệnh chạy:** `python -m transform.core.build_fct_ground_truth`
* **Lệnh tự kiểm tra:** `python -c "import duckdb; con = duckdb.connect(); cnt = con.execute('SELECT COUNT(*) FROM "data/core/fct_ground_truth_daily.parquet" WHERE date_id IS NULL OR station_id IS NULL').fetchone()[0]; assert cnt == 0; print('Fact ground truth FK integrity: PASS')"`
* **DoD:** Zero-Orphan Foreign Keys, sẵn sàng bàn giao cho TV2.

---

### Task TV1-12: Thực hiện Spatio-Temporal EDA Chuyên đề 2 & Chuyên đề 5
* **Mục tiêu:** Khám phá động học phân phối PM2.5 và so sánh vi môi trường trạm đo.
* **Input:** `fct_ground_truth_daily`, `dim_station`, `dim_date`.
* **Output:** `notebooks/eda_02_pm25_distribution_hampel.ipynb`, `notebooks/eda_05_roadside_background.ipynb`.
* **Cách làm từng bước:**
  1. *Chuyên đề 2:* Vẽ biểu đồ phân phối nồng độ PM2.5, kiểm tra tính log-normal, đánh giá tỷ lệ bản ghi bị gắn cờ Hampel, và phân tích độ nhạy của hệ số $\kappa$ trong khoảng $[0.2, 0.5]$.
  2. *Chuyên đề 5:* Tính nồng độ trung bình theo mùa giữa nhóm trạm Roadside và Background. Tính chênh lệch nồng độ (delta PM2.5) và vẽ biểu đồ suy giảm theo khoảng cách mét tới đường chính.
* **Lệnh chạy:** `python run.py eda --topics 2,5`
* **DoD:** 2 notebook chạy mượt từ đầu đến cuối không lỗi, có diễn giải biểu đồ chi tiết.

---

### Task TV1-13: Kiểm tra Toàn trình CI/CD & Nghiệm thu Báo cáo Sẵn sàng Dữ liệu
* **Mục tiêu:** Chạy kiểm thử toàn bộ hệ thống trên CI và đóng gói phát hành release tag `v2.1`.
* **Input:** Toàn bộ codebase và kết quả kiểm định của TV2, TV3.
* **Output:** Tag `v2.1` trên GitHub, Báo cáo Sẵn sàng Dữ liệu được phê duyệt.
* **Cách làm:** Chạy `python run.py all`, kiểm tra trạng thái xanh trên GitHub Actions, tạo Release Tag `v2.1`.


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

