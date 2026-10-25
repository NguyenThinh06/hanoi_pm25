> Hợp đồng bàn giao v2.0: N_GRID = 3.610 ô giao ranh giới (không tính grid_unknown); 3.363 ô có tâm trong ranh giới chỉ là tập con. N_DAYS = 1.826, date_id = YYYYMMDD; khung phân tích = 6.591.860 dòng, loại cả hai unknown. Xem [SPINE_HANDOFF.md](SPINE_HANDOFF.md) và grid_manifest.json. Nguồn ranh giới: GSO / HDX COD-AB v02 (01/07/2025), chọn Ha Noi / VN01; xem provenance đi kèm. Dùng cố định cho chuỗi 2021–2025.

# HANOI_PM25 — MASTER PROJECT EXECUTION GUIDE v3.0
## Spatio-Temporal Data Lakehouse for Hanoi PM2.5 (2021–2025)
### Cẩm nang Kỹ thuật Thực thi Master · Hướng dẫn Dành cho Người mới & Phân công Nhóm 3 Kỹ sư


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

<div class="diagram-wrapper"><div class="diagram-title">SƠ ĐỒ 1: KIẾN TRÚC TỔNG THỂ SPATIO-TEMPORAL LAKEHOUSE HANOI_PM25</div><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 580" width="1000" height="580">
  <defs>
    <style>
      .bg { fill: #FFFFFF; }
      .title { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; font-size: 20px; fill: #14263D; }
      .subtitle { font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; fill: #64748B; }
      .box { rx: 8; ry: 8; stroke-width: 1.5; }
      .box-raw { fill: #EFF6FF; stroke: #3B82F6; }
      .box-stg { fill: #F0FDF4; stroke: #10B981; }
      .box-core { fill: #FEF3C7; stroke: #F59E0B; }
      .box-marts { fill: #F5F3FF; stroke: #8B5CF6; }
      .box-engine { fill: #F1F5F9; stroke: #64748B; }
      .head-text { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 600; font-size: 15px; fill: #0F172A; }
      .body-text { font-family: 'Segoe UI', Arial, sans-serif; font-size: 11.5px; fill: #334155; }
      .badge { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 600; font-size: 10px; rx: 4; ry: 4; }
      .badge-blue { fill: #DBEAFE; stroke: #93C5FD; }
      .badge-text-blue { fill: #1E40AF; }
      .arrow { stroke: #64748B; stroke-width: 1.5; fill: none; marker-end: url(#arrowhead); }
      .arrow-crit { stroke: #DC2626; stroke-width: 2; fill: none; marker-end: url(#arrowhead-red); }
    </style>
    <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="#64748B" />
    </marker>
    <marker id="arrowhead-red" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="#DC2626" />
    </marker>
  </defs>

  <rect width="1000" height="580" class="bg" />

  <!-- HEADER -->
  <text x="40" y="40" class="title">KIẾN TRÚC TỔNG THỂ HỆ THỐNG SPATIO-TEMPORAL DATA LAKEHOUSE</text>
  <text x="40" y="60" class="subtitle">Mô hình Medallion Architecture 4 tầng: Zero-RDBMS · Pure Parquet / GeoParquet · In-process DuckDB SQL &amp; Polars</text>

  <!-- 1. DATA SOURCES -->
  <rect x="40" y="90" width="180" height="440" class="box box-engine" />
  <text x="55" y="115" class="head-text">NGUỒN DỮ LIỆU (9 NGUỒN)</text>
  <text x="55" y="132" class="body-text">Cửa sổ UTC: 2020-12-31 – 2026-01-01</text>
  
  <rect x="55" y="145" width="150" height="85" rx="6" ry="6" fill="#FFFFFF" stroke="#CBD5E1" />
  <text x="65" y="165" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="12px" fill="#1E293B">Quan trắc Mặt đất</text>
  <text x="65" y="182" class="body-text">• OpenAQ v3 (REST API)</text>
  <text x="65" y="197" class="body-text">• AirNow API (US Embassy)</text>
  <text x="65" y="212" class="body-text">• PAM Air (Optical PMS)</text>

  <rect x="55" y="245" width="150" height="85" rx="6" ry="6" fill="#FFFFFF" stroke="#CBD5E1" />
  <text x="65" y="265" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="12px" fill="#1E293B">Khí tượng &amp; Tái phân tích</text>
  <text x="65" y="282" class="body-text">• ERA5-Land (~9km, CDS)</text>
  <text x="65" y="297" class="body-text">• ERA5 BLH (~25km, CDS)</text>
  <text x="65" y="312" class="body-text">• CAMS EAC4 (~40km, CDS)</text>

  <rect x="55" y="345" width="150" height="85" rx="6" ry="6" fill="#FFFFFF" stroke="#CBD5E1" />
  <text x="65" y="365" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="12px" fill="#1E293B">Viễn thám Vệ tinh</text>
  <text x="65" y="382" class="body-text">• Sentinel-5P TROPOMI (NO2)</text>
  <text x="65" y="397" class="body-text">• MODIS MAIAC AOD (1km)</text>
  <text x="65" y="412" class="body-text">• VIIRS Nighttime / Cháy</text>

  <rect x="55" y="445" width="150" height="70" rx="6" ry="6" fill="#FFFFFF" stroke="#CBD5E1" />
  <text x="65" y="465" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="12px" fill="#1E293B">Dữ liệu Tĩnh Đô thị</text>
  <text x="65" y="482" class="body-text">• OSM Roads, WorldCover 10m</text>
  <text x="65" y="497" class="body-text">• Copernicus DEM 30m</text>

  <!-- ARROWS TO RAW -->
  <path d="M 220 310 L 255 310" class="arrow" />

  <!-- 2. BRONZE / RAW LAYER -->
  <rect x="260" y="90" width="160" height="440" class="box box-raw" />
  <text x="275" y="115" class="head-text">TẦNG RAW (BRONZE)</text>
  <text x="275" y="132" class="body-text">data/raw/ (Append-only)</text>
  
  <rect x="275" y="150" width="130" height="75" rx="6" ry="6" fill="#FFFFFF" stroke="#93C5FD" />
  <text x="285" y="170" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11.5px" fill="#1E40AF">ground_truth/</text>
  <text x="285" y="188" class="body-text">source=*/year=*/</text>
  <text x="285" y="203" class="body-text">month=*/*.parquet</text>
  <text x="285" y="218" class="body-text">+ _row_hash SHA-256</text>

  <rect x="275" y="245" width="130" height="85" rx="6" ry="6" fill="#FFFFFF" stroke="#93C5FD" />
  <text x="285" y="265" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11.5px" fill="#1E40AF">atmospheric/</text>
  <text x="285" y="283" class="body-text">Centroid pixel gốc</text>
  <text x="285" y="298" class="body-text">~45 điểm ERA5-Land</text>
  <text x="285" y="313" class="body-text">~8 điểm ERA5 BLH</text>

  <rect x="275" y="350" width="130" height="85" rx="6" ry="6" fill="#FFFFFF" stroke="#93C5FD" />
  <text x="285" y="370" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11.5px" fill="#1E40AF">earth_observation/</text>
  <text x="285" y="388" class="body-text">Chunking theo quý</text>
  <text x="285" y="403" class="body-text">Raw optical reflectance</text>
  <text x="285" y="418" class="body-text">Lưu vết checkpoint</text>

  <rect x="275" y="455" width="130" height="60" rx="6" ry="6" fill="#FEF3C7" stroke="#F59E0B" />
  <text x="285" y="475" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11px" fill="#B45309">BẢO VỆ PHẢ HỆ</text>
  <text x="285" y="492" class="body-text">Bất biến, cấm update,</text>
  <text x="285" y="507" class="body-text">lũy đẳng khi nạp lại</text>

  <!-- ARROWS TO STAGING -->
  <path d="M 420 310 L 455 310" class="arrow" />

  <!-- 3. SILVER / STAGING LAYER -->
  <rect x="460" y="90" width="160" height="440" class="box box-stg" />
  <text x="475" y="115" class="head-text">TẦNG STAGING (SILVER)</text>
  <text x="475" y="132" class="body-text">data/staging/ (Cleaned)</text>

  <rect x="475" y="150" width="130" height="85" rx="6" ry="6" fill="#FFFFFF" stroke="#86EFAC" />
  <text x="485" y="170" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11px" fill="#166534">stg_ground_truth_hourly</text>
  <text x="485" y="188" class="body-text">• Giữ 100% bản ghi</text>
  <text x="485" y="203" class="body-text">• Hòa giải revision</text>
  <text x="485" y="218" class="body-text">• Phân loại cờ cứng / nghi</text>

  <rect x="475" y="245" width="130" height="90" rx="6" ry="6" fill="#FFFFFF" stroke="#86EFAC" />
  <text x="485" y="265" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11px" fill="#166534">stg_ground_truth_daily</text>
  <text x="485" y="283" class="body-text">• Lọc valid_hours &gt;= 18h</text>
  <text x="485" y="298" class="body-text">• Hiệu chỉnh ẩm Köhler</text>
  <text x="485" y="313" class="body-text">• Lưu song song raw/calib</text>
  <text x="485" y="328" class="body-text">• Giờ địa phương ICT</text>

  <rect x="475" y="345" width="130" height="80" rx="6" ry="6" fill="#FFFFFF" stroke="#86EFAC" />
  <text x="485" y="365" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11px" fill="#166534">stg_meteo_daily</text>
  <text x="485" y="383" class="body-text">• Khử tích lũy mưa</text>
  <text x="485" y="398" class="body-text">• Gió vô hướng V_scalar</text>
  <text x="485" y="413" class="body-text">• Magnus RH 2 bước</text>

  <rect x="475" y="435" width="130" height="80" rx="6" ry="6" fill="#FFFFFF" stroke="#86EFAC" />
  <text x="485" y="455" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11px" fill="#166534">stg_satellite_daily</text>
  <text x="485" y="473" class="body-text">• Sentinel-5P QA &gt;= 0.75</text>
  <text x="485" y="488" class="body-text">• AOD cấm nội suy mây</text>
  <text x="485" y="503" class="body-text">• Cờ chẩn đoán MNAR</text>

  <!-- ARROWS TO CORE -->
  <path d="M 620 310 L 655 310" class="arrow" />

  <!-- 4. GOLD / CORE STAR SCHEMA -->
  <rect x="660" y="90" width="150" height="440" class="box box-core" />
  <text x="675" y="115" class="head-text">TẦNG CORE (GOLD)</text>
  <text x="675" y="132" class="body-text">data/core/ (Star Schema)</text>

  <rect x="675" y="150" width="120" height="150" rx="6" ry="6" fill="#FFFFFF" stroke="#FCD34D" />
  <text x="685" y="170" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11px" fill="#B45309">3 DIMENSIONS</text>
  <text x="685" y="190" class="body-text">• dim_grid_1km</text>
  <text x="695" y="205" font-size="10px" fill="#64748B">(GeoParquet 1.1)</text>
  <text x="685" y="225" class="body-text">• dim_date</text>
  <text x="695" y="240" font-size="10px" fill="#64748B">(1826 ngày + -1)</text>
  <text x="685" y="260" class="body-text">• dim_station</text>
  <text x="695" y="275" font-size="10px" fill="#64748B">(Roadside/Backgrd)</text>

  <rect x="675" y="315" width="120" height="150" rx="6" ry="6" fill="#FFFFFF" stroke="#FCD34D" />
  <text x="685" y="335" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11px" fill="#B45309">3 FACTS</text>
  <text x="685" y="355" class="body-text">• fct_ground_truth</text>
  <text x="695" y="370" font-size="10px" fill="#64748B">PK: (station, date)</text>
  <text x="685" y="390" class="body-text">• fct_grid_meteo</text>
  <text x="695" y="405" font-size="10px" fill="#64748B">PK: (grid, date) |S|</text>
  <text x="685" y="425" class="body-text">• fct_grid_satellite</text>
  <text x="695" y="440" font-size="10px" fill="#64748B">PK: (grid, date) |S|</text>

  <!-- ARROWS TO MARTS -->
  <path d="M 810 310 L 835 310" class="arrow" />

  <!-- 5. PLATINUM / MARTS LAYER -->
  <rect x="840" y="90" width="140" height="440" class="box box-marts" />
  <text x="850" y="115" class="head-text">TẦNG MARTS</text>
  <text x="850" y="132" class="body-text">data/marts/ (Spine |S|)</text>

  <rect x="848" y="150" width="124" height="110" rx="6" ry="6" fill="#FFFFFF" stroke="#C4B5FD" />
  <text x="856" y="170" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11px" fill="#6D28D9">mart_grid_daily_</text>
  <text x="856" y="185" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11px" fill="#6D28D9">features</text>
  <text x="856" y="202" font-size="10px" font-weight="700" fill="#DC2626">SẠCH NHÃN 100%</text>
  <text x="856" y="217" class="body-text">Chỉ chứa biến độc lập</text>
  <text x="856" y="232" class="body-text">Không trạm, không PM</text>
  <text x="856" y="247" class="body-text">Quy mô: Đúng |S| dòng</text>

  <rect x="848" y="275" width="124" height="110" rx="6" ry="6" fill="#FFFFFF" stroke="#C4B5FD" />
  <text x="856" y="295" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11px" fill="#6D28D9">mart_grid_daily_</text>
  <text x="856" y="310" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11px" fill="#6D28D9">eda</text>
  <text x="856" y="327" font-size="10.5px" fill="#1E293B">Phục vụ 6 Chuyên đề</text>
  <text x="856" y="342" class="body-text">Đặc trưng + nhãn ô</text>
  <text x="856" y="357" class="body-text">grid_pm25_mean</text>
  <text x="856" y="372" class="body-text">active_station_count</text>

  <rect x="848" y="400" width="124" height="115" rx="6" ry="6" fill="#FFFFFF" stroke="#C4B5FD" />
  <text x="856" y="420" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11px" fill="#6D28D9">mart_station_</text>
  <text x="856" y="435" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11px" fill="#6D28D9">matched</text>
  <text x="856" y="452" font-size="10.5px" fill="#1E293B">Ghép trạm thực 100%</text>
  <text x="856" y="467" class="body-text">Khớp Fact trạm ngày</text>
  <text x="856" y="482" class="body-text">Nồng độ + Vector ô</text>
  <text x="856" y="497" class="body-text">Phân tích Roadside</text>

  <!-- BOTTOM FOOTER -->
  <line x1="40" y1="545" x2="980" y2="545" stroke="#E2E8F0" stroke-width="1" />
  <text x="40" y="565" font-family="'Segoe UI', sans-serif" font-size="11px" fill="#64748B">Engine tính toán: DuckDB in-process (Vectorized SQL) &amp; Polars (Lazy Dataframe) | Định dạng lưu trữ: Apache Parquet &amp; GeoParquet 1.1.0 (EPSG:3405)</text>
</svg><div class="diagram-caption">Hệ thống Zero-RDBMS xử lý in-process với DuckDB SQL & Polars qua 4 tầng Medallion</div></div>

<div class="diagram-wrapper"><div class="diagram-title">SƠ ĐỒ 2: DÒNG CHẢY BIẾN ĐỔI DỮ LIỆU QUA 4 TẦNG MEDALLION</div><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 480" width="960" height="480">
  <defs>
    <style>
      .bg { fill: #FFFFFF; }
      .title { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; font-size: 18px; fill: #14263D; }
      .subtitle { font-family: 'Segoe UI', Arial, sans-serif; font-size: 12px; fill: #64748B; }
      .flow-box { rx: 8; ry: 8; stroke-width: 1.5; }
      .f-raw { fill: #EFF6FF; stroke: #3B82F6; }
      .f-stg { fill: #ECFDF5; stroke: #10B981; }
      .f-core { fill: #FFFBEB; stroke: #F59E0B; }
      .f-marts { fill: #FAF5FF; stroke: #8B5CF6; }
      .h-title { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; font-size: 14px; }
      .txt { font-family: 'Segoe UI', Arial, sans-serif; font-size: 11px; fill: #334155; }
      .txt-bold { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 600; font-size: 11.5px; fill: #0F172A; }
      .arr { stroke: #475569; stroke-width: 1.5; fill: none; marker-end: url(#ah); }
    </style>
    <marker id="ah" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="#475569" />
    </marker>
  </defs>

  <rect width="960" height="480" class="bg" />
  <text x="40" y="38" class="title">DÒNG CHẢY BIẾN ĐỔI MEDALLION &amp; NGUYÊN TẮC LÀM SẠCH DỮ LIỆU</text>
  <text x="40" y="56" class="subtitle">Quy trình biến đổi từ Dữ liệu thô (Raw) đến Chợ đặc trưng sẵn sàng phân tích (Marts)</text>

  <!-- 4 COLUMNS -->
  <!-- BRONZE -->
  <rect x="40" y="80" width="200" height="370" class="flow-box f-raw" />
  <text x="55" y="105" class="h-title" fill="#1D4ED8">1. BRONZE (RAW)</text>
  <text x="55" y="122" class="txt" font-weight="600">Đặc tính: Bất biến &amp; Phả hệ</text>
  
  <rect x="55" y="135" width="170" height="75" rx="5" ry="5" fill="#FFFFFF" stroke="#BFDBFE" />
  <text x="65" y="153" class="txt-bold">Dữ liệu Chuỗi Giờ Gốc</text>
  <text x="65" y="170" class="txt">• Múi giờ gốc UTC</text>
  <text x="65" y="185" class="txt">• Ghi lũy đẳng (Idempotent)</text>
  <text x="65" y="200" class="txt">• Sinh mã _row_hash</text>

  <rect x="55" y="225" width="170" height="85" rx="5" ry="5" fill="#FFFFFF" stroke="#BFDBFE" />
  <text x="65" y="243" class="txt-bold">Cửa sổ UTC Mở rộng</text>
  <text x="65" y="260" class="txt">Từ 2020-12-31T16:00:00Z</text>
  <text x="65" y="275" class="txt">đến 2026-01-01T08:00:00Z</text>
  <text x="65" y="290" class="txt">• Bảo toàn ngày 2021-01-01 ICT</text>
  <text x="65" y="303" class="txt">• Không mất giờ địa phương</text>

  <rect x="55" y="325" width="170" height="110" rx="5" ry="5" fill="#FFFFFF" stroke="#BFDBFE" />
  <text x="65" y="343" class="txt-bold">Centroid Pixel Gốc</text>
  <text x="65" y="360" class="txt">• ERA5: ~45 điểm tâm</text>
  <text x="65" y="375" class="txt">• BLH: ~8 điểm tâm</text>
  <text x="65" y="390" class="txt">• Sentinel-5P: QA &gt;= 0.75</text>
  <text x="65" y="405" class="txt">• MODIS: Giữ nguyên NULL</text>
  <text x="65" y="420" class="txt">• Giảm tải GEE 70 lần</text>

  <!-- ARROW 1 -> 2 -->
  <path d="M 240 265 L 275 265" class="arr" />

  <!-- SILVER -->
  <rect x="280" y="80" width="200" height="370" class="flow-box f-stg" />
  <text x="295" y="105" class="h-title" fill="#047857">2. SILVER (STAGING)</text>
  <text x="295" y="122" class="txt" font-weight="600">Đặc tính: Chuẩn hóa &amp; QC</text>

  <rect x="295" y="135" width="170" height="85" rx="5" ry="5" fill="#FFFFFF" stroke="#A7F3D0" />
  <text x="305" y="153" class="txt-bold">Hòa giải Revision Giờ</text>
  <text x="305" y="170" class="txt">• Window ROW_NUMBER()</text>
  <text x="305" y="185" class="txt">• Chuyển sang ICT (UTC+7)</text>
  <text x="305" y="200" class="txt">• Phân cờ cứng / nghi vấn</text>
  <text x="305" y="213" class="txt">• Giữ 100% stg_hourly</text>

  <rect x="295" y="235" width="170" height="95" rx="5" ry="5" fill="#FFFFFF" stroke="#A7F3D0" />
  <text x="305" y="253" class="txt-bold">Quy tắc &gt;= 18h &amp; Köhler</text>
  <text x="305" y="270" class="txt">• Chỉ tính ngày có &gt;=18h</text>
  <text x="305" y="285" class="txt">• Hiệu chỉnh kappa=0.35 Tier 2</text>
  <text x="305" y="300" class="txt">• Dùng RH trạm hoặc ERA5</text>
  <text x="305" y="315" class="txt">• Lưu song song raw/calib</text>

  <rect x="295" y="345" width="170" height="90" rx="5" ry="5" fill="#FFFFFF" stroke="#A7F3D0" />
  <text x="305" y="363" class="txt-bold">Khử Tích lũy &amp; Gió</text>
  <text x="305" y="380" class="txt">• Mưa giờ: tp_h - tp_{h-1}</text>
  <text x="305" y="395" class="txt">• Gió vô hướng: V_scalar</text>
  <text x="305" y="410" class="txt">• Bền vững: P = V_vec / V_sca</text>
  <text x="305" y="425" class="txt">• Cờ mây: is_aod_missing_mnar</text>

  <!-- ARROW 2 -> 3 -->
  <path d="M 480 265 L 515 265" class="arr" />

  <!-- GOLD -->
  <rect x="520" y="80" width="200" height="370" class="flow-box f-core" />
  <text x="535" y="105" class="h-title" fill="#B45309">3. GOLD (CORE)</text>
  <text x="535" y="122" class="txt" font-weight="600">Kimball Star Schema</text>

  <rect x="535" y="135" width="170" height="135" rx="5" ry="5" fill="#FFFFFF" stroke="#FDE68A" />
  <text x="545" y="153" class="txt-bold">3 Bảng Chiều (Dimensions)</text>
  <text x="545" y="172" class="txt">• dim_grid_1km:</text>
  <text x="555" y="187" class="txt">EPSG:3405, 15 biến tĩnh</text>
  <text x="545" y="205" class="txt">• dim_date:</text>
  <text x="555" y="220" class="txt">1,826 ngày + dòng -1</text>
  <text x="545" y="238" class="txt">• dim_station:</text>
  <text x="555" y="253" class="txt">Roadside vs Background</text>

  <rect x="535" y="285" width="170" height="150" rx="5" ry="5" fill="#FFFFFF" stroke="#FDE68A" />
  <text x="545" y="303" class="txt-bold">3 Bảng Sự kiện (Facts)</text>
  <text x="545" y="322" class="txt">• fct_ground_truth_daily</text>
  <text x="555" y="337" class="txt">Grain: (station, date)</text>
  <text x="545" y="355" class="txt">• fct_grid_meteo_daily</text>
  <text x="555" y="370" class="txt">Grain: (grid, date) |S|</text>
  <text x="545" y="388" class="txt">• fct_grid_satellite_daily</text>
  <text x="555" y="403" class="txt">Grain: (grid, date) |S|</text>
  <text x="545" y="423" font-size="10px" font-weight="600" fill="#B45309">Zero-Orphan Foreign Keys</text>

  <!-- ARROW 3 -> 4 -->
  <path d="M 720 265 L 755 265" class="arr" />

  <!-- PLATINUM -->
  <rect x="760" y="80" width="170" height="370" class="flow-box f-marts" />
  <text x="775" y="105" class="h-title" fill="#6D28D9">4. PLATINUM (MARTS)</text>
  <text x="775" y="122" class="txt" font-weight="600">Khung Spine &amp; Chống Leak</text>

  <rect x="770" y="135" width="150" height="95" rx="5" ry="5" fill="#FFFFFF" stroke="#DDD6FE" />
  <text x="778" y="153" class="txt-bold">mart_grid_daily_features</text>
  <text x="778" y="170" font-size="10.5px" font-weight="700" fill="#DC2626">CẤM NHÃN 100%</text>
  <text x="778" y="185" class="txt">• Whitelist biến độc lập</text>
  <text x="778" y="200" class="txt">• Khớp đúng |S| dòng</text>
  <text x="778" y="215" class="txt">• Sẵn sàng mô hình ML</text>

  <rect x="770" y="245" width="150" height="90" rx="5" ry="5" fill="#FFFFFF" stroke="#DDD6FE" />
  <text x="778" y="263" class="txt-bold">mart_grid_daily_eda</text>
  <text x="778" y="280" class="txt">• Phục vụ vẽ bản đồ EDA</text>
  <text x="778" y="295" class="txt">• Ghép nhãn ô tổng hợp</text>
  <text x="778" y="310" class="txt">• grid_pm25_mean</text>
  <text x="778" y="325" class="txt">• active_station_count</text>

  <rect x="770" y="350" width="150" height="85" rx="5" ry="5" fill="#FFFFFF" stroke="#DDD6FE" />
  <text x="778" y="368" class="txt-bold">mart_station_matched</text>
  <text x="778" y="385" class="txt">• Ghép trạm thực 100%</text>
  <text x="778" y="400" class="txt">• Khớp Fact trạm ngày</text>
  <text x="778" y="415" class="txt">• EDA CĐ 1, CĐ 2, CĐ 5</text>
</svg><div class="diagram-caption">Từ Raw bất biến, qua Staging chuẩn hóa múi giờ và QC phân tầng, đến Core Star Schema và Marts sạch nhãn</div></div>

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

<div class="diagram-wrapper"><div class="diagram-title">SƠ ĐỒ 10: QUY TRÌNH QUẢN TRỊ NHÁNH GIT, CI/CD & PULL REQUEST REVIEW</div><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 460" width="960" height="460">
  <defs>
    <style>
      .bg { fill: #FFFFFF; }
      .title { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; font-size: 18px; fill: #14263D; }
      .subtitle { font-family: 'Segoe UI', Arial, sans-serif; font-size: 12px; fill: #64748B; }
      .br-main { stroke: #DC2626; stroke-width: 3; fill: none; }
      .br-dev { stroke: #2563EB; stroke-width: 2.5; fill: none; }
      .br-feat { stroke: #059669; stroke-width: 2; fill: none; }
      .commit { fill: #FFFFFF; stroke-width: 2; r: 5; }
      .c-main { stroke: #DC2626; }
      .c-dev { stroke: #2563EB; }
      .c-feat { stroke: #059669; }
      .g-txt { font-family: 'Segoe UI', Arial, sans-serif; font-size: 11px; fill: #334155; }
      .g-bold { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; font-size: 11.5px; fill: #0F172A; }
    </style>
  </defs>

  <rect width="960" height="460" class="bg" />
  <text x="40" y="38" class="title">QUY TRÌNH QUẢN TRỊ NHÁNH GIT, CI/CD &amp; PULL REQUEST REVIEW</text>
  <text x="40" y="56" class="subtitle">Chiến lược phân nhánh GitFlow thu nhỏ: main · develop · feature/* · fix/* và kiểm soát chất lượng tự động</text>

  <!-- BRANCH LINES -->
  <!-- MAIN BRANCH -->
  <line x1="80" y1="120" x2="880" y2="120" class="br-main" />
  <text x="80" y="105" font-family="'Consolas', monospace" font-weight="700" font-size="13px" fill="#DC2626">main (Khóa cứng - Protected)</text>
  <text x="80" y="140" class="g-txt">Chỉ chứa mã nguồn ổn định đã nghiệm thu Gate; Gắn Release Tags (v3.0.0, v2.1)</text>

  <!-- DEVELOP BRANCH -->
  <line x1="80" y1="210" x2="880" y2="210" class="br-dev" />
  <text x="80" y="195" font-family="'Consolas', monospace" font-weight="700" font-size="13px" fill="#2563EB">develop (Tích hợp - Protected)</text>
  <text x="80" y="230" class="g-txt">Nhánh tích hợp chính; Chạy CI 6 bước tự động; Bắt buộc &gt;= 1 Review phê duyệt</text>

  <!-- FEATURE BRANCHES -->
  <line x1="160" y1="310" x2="400" y2="310" class="br-feat" />
  <line x1="420" y1="310" x2="660" y2="310" class="br-feat" />
  <line x1="680" y1="310" x2="840" y2="310" class="br-feat" />
  <text x="80" y="295" font-family="'Consolas', monospace" font-weight="700" font-size="13px" fill="#059669">feature/* &amp; fix/*</text>

  <!-- BRANCH CONNECTORS -->
  <!-- develop fork to feature 1 -->
  <path d="M 160 210 Q 160 310 200 310" fill="none" stroke="#059669" stroke-width="1.8" />
  <!-- feature 1 merge to develop -->
  <path d="M 360 310 Q 400 310 400 210" fill="none" stroke="#2563EB" stroke-width="1.8" />

  <!-- develop fork to feature 2 -->
  <path d="M 420 210 Q 420 310 460 310" fill="none" stroke="#059669" stroke-width="1.8" />
  <!-- feature 2 merge to develop -->
  <path d="M 620 310 Q 660 310 660 210" fill="none" stroke="#2563EB" stroke-width="1.8" />

  <!-- develop merge to main -->
  <path d="M 780 210 Q 820 210 820 120" fill="none" stroke="#DC2626" stroke-width="2" />

  <!-- COMMITS -->
  <!-- Main commits -->
  <circle cx="120" cy="120" class="commit c-main" />
  <circle cx="820" cy="120" class="commit c-main" />
  <!-- Develop commits -->
  <circle cx="120" cy="210" class="commit c-dev" />
  <circle cx="400" cy="210" class="commit c-dev" />
  <circle cx="660" cy="210" class="commit c-dev" />
  <circle cx="780" cy="210" class="commit c-dev" />
  <!-- Feature commits -->
  <circle cx="240" cy="310" class="commit c-feat" />
  <circle cx="320" cy="310" class="commit c-feat" />
  <circle cx="500" cy="310" class="commit c-feat" />
  <circle cx="580" cy="310" class="commit c-feat" />

  <!-- PR BADGES -->
  <rect x="250" y="325" width="140" height="40" rx="4" ry="4" fill="#EFF6FF" stroke="#3B82F6" />
  <text x="258" y="342" class="g-bold" fill="#1D4ED8">PR #12: arch/spine</text>
  <text x="258" y="356" class="g-txt">Reviewer: hunganh (TV2)</text>

  <rect x="510" y="325" width="140" height="40" rx="4" ry="4" fill="#ECFDF5" stroke="#10B981" />
  <text x="518" y="342" class="g-bold" fill="#065F46">PR #15: ground-truth/qc</text>
  <text x="518" y="356" class="g-txt">Reviewer: ngthinh06 (TV1)</text>

  <!-- CI CHECKLIST BOX (BOTTOM) -->
  <rect x="80" y="380" width="800" height="65" rx="6" ry="6" fill="#F8FAFC" stroke="#CBD5E1" />
  <text x="95" y="400" class="g-bold" fill="#0F172A">CHECKLIST 6 BƯỚC CI BẮT BUỘC TRÊN GITHUB ACTIONS (.github/workflows/ci.yml):</text>
  <text x="95" y="418" class="g-txt">1. Setup env &amp; deps  |  2. Lint &amp; Format (ruff)  |  3. Idempotent Ingestion Test  |  4. Build Staging -&gt; Core -&gt; Marts  |  5. DuckDB SQL Quality Gate (9/9 Pass)  |  6. Mutation Testing (4/4 Caught)</text>
  <text x="95" y="433" font-size="10.5px" font-weight="700" fill="#DC2626">QUY TẮC: CẤM TỰ MERGE TRÊN BRANCH BẢO VỆ · BẮT BUỘC SQUASH &amp; MERGE · MỌI PR PHẢI CÓ CODEOWNERS PHÊ DUYỆT</text>
</svg><div class="diagram-caption">Phân nhánh GitFlow thu nhỏ: main · develop · feature branches với cổng kiểm tra tự động 6 bước</div></div>

---


## 3. PHÂN CHIA LẠI TRÁCH NHIỆM NHÓM 3 THÀNH VIÊN (REVISED TEAM BREAKDOWN)

Theo yêu cầu điều chỉnh chính thức của dự án:
* **👤 THÀNH VIÊN 1 (`ngthinh06`) — Data Architect, CI/CD Lead & Ground Truth Stations Owner:**
  - **Hạ tầng Codebase & CI/CD Toàn đội:** Thiết lập `run.py`, GitHub Actions CI 6 bước, hàm ghi an toàn `io_parquet.py`, module băm `hashing.py`, trình sinh mock data `mock_seeder.py`.
  - **Khung không gian & Thời gian:** Sinh lưới 1km `EPSG:3405`, `grid_manifest.json`, Trục ngày 5 năm `dim_date.parquet` (1,827 dòng).
  - **Toàn bộ Dữ liệu Trạm Mặt đất (Ground Truth):** Audit độ phủ 5 năm; thu thập thô OpenAQ v3, AirNow, PAM Air; QC chuỗi giờ `stg_ground_truth_hourly`; hiệu chỉnh độ ẩm $\kappa$-Köhler ($\kappa=0.35$); gom ngày lọc khắt khe $18 \le \text{valid\_hours} \le 24$ (`stg_ground_truth_daily`); bảng trạm `dim_station` (Roadside vs Background) và Fact trạm `fct_ground_truth_daily`.
  - **EDA Chuyên đề:** EDA 2 (Động học phân phối PM2.5, Hampel, độ nhạy $\kappa$) & EDA 5 (Vi môi trường Roadside vs Background theo khoảng cách đường OSM).
* **👤 THÀNH VIÊN 2 (`hunganh`) — Earth Observation, Urban Static Features & Quality Lead:**
  - **Viễn thám Vệ tinh GEE:** Kiểm toán, thu thập thô Sentinel-5P NO2, MODIS MAIAC AOD (1km), VIIRS Nightlight; biến đổi Staging vệ tinh lọc QA, áp dụng chính sách mây che MNAR (giữ `NULL`, cờ `is_aod_missing_mnar = 1`, cấm nội suy mù) $\rightarrow$ `fct_grid_satellite_daily`.
  - **15 Biến tĩnh Đô thị:** Trích xuất từ OSM (đường chính, mật độ), WorldCover 10m (tỷ lệ built-up, cây xanh, nông nghiệp), DEM 30m (độ cao, độ dốc) cập nhật vào `dim_grid_1km.parquet` v1.1.
  - **Cổng Kiểm định Chất lượng & Mutation Testing:** Soạn thảo 9 rules DuckDB SQL (`quality/rules.yml`), xây dựng runner kiểm thử, framework kiểm thử đột biến Sandbox (tiêm 4 lỗi, Score = 100%).
  - **Đóng gói Kimball Core & Marts:** Tích hợp Star Schema (Zero-Orphan FKs), xây dựng Feature Mart sạch nhãn 100% `mart_grid_daily_features.parquet` và `mart_grid_daily_eda` / `mart_station_matched`.
  - **EDA Chuyên đề:** EDA 1 (Cơ chế mất dữ liệu viễn thám MNAR) & EDA 6 (Địa thống kê Semivariogram không gian - thời gian).
* **👤 THÀNH VIÊN 3 (`minh`) — Atmospheric Reanalysis & Meteorological Physics Engineer:**
  - **Khí quyển Tái phân tích GEE & Copernicus CDS:** Thu thập thô ERA5-Land (~9km), CAMS khí quyển, ERA5 BLH chiều cao lớp biên hành tinh (~31km) theo tọa độ tâm pixel gốc (tránh cạn kiệt quota API).
  - **Biến đổi Khí tượng Chuyên sâu:** Khử tích lũy lượng mưa giờ, tính tốc độ gió vô hướng, tỷ số bền vững gió $P$, tính độ ẩm tương đối Magnus-Tetens ($RH$). **Bàn giao ngay bảng RH cho TV1 để mở khóa hiệu chỉnh ẩm Köhler cho trạm PAM Air**.
  - **Tạo Fact Khí tượng Lưới 1km:** Broadcast khí tượng sang ~3,360 ô lưới 1km $\rightarrow$ `fct_grid_meteo_daily.parquet` bàn giao cho TV2.
  - **EDA Chuyên đề:** EDA 3 (Phân rã chuỗi thời gian STL & Nghịch nhiệt PBL/BLH) & EDA 4 (Tương quan đa nguồn & cỡ mẫu hiệu dụng $n_{\text{eff}}$).


---

<div class="diagram-wrapper"><div class="diagram-title">SƠ ĐỒ 3: KIMBALL STAR SCHEMA TẦNG CORE (3 DIMS + 3 FACTS)</div><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 560" width="960" height="560">
  <defs>
    <style>
      .bg { fill: #FFFFFF; }
      .title { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; font-size: 18px; fill: #14263D; }
      .subtitle { font-family: 'Segoe UI', Arial, sans-serif; font-size: 12px; fill: #64748B; }
      .dim-card { fill: #EFF6FF; stroke: #3B82F6; stroke-width: 1.5; rx: 6; ry: 6; }
      .fact-card { fill: #FEF3C7; stroke: #F59E0B; stroke-width: 1.5; rx: 6; ry: 6; }
      .dim-head { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; font-size: 13px; fill: #1E40AF; }
      .fact-head { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; font-size: 13px; fill: #B45309; }
      .pk { font-family: 'Consolas', monospace; font-size: 11px; font-weight: 700; fill: #DC2626; }
      .fk { font-family: 'Consolas', monospace; font-size: 11px; font-weight: 700; fill: #2563EB; }
      .col { font-family: 'Consolas', monospace; font-size: 10.5px; fill: #334155; }
      .rel-line { stroke: #64748B; stroke-width: 1.5; stroke-dasharray: 4 3; fill: none; }
      .rel-marker { fill: #64748B; font-family: 'Segoe UI', sans-serif; font-size: 10px; font-weight: 600; }
    </style>
  </defs>

  <rect width="960" height="560" class="bg" />
  <text x="40" y="38" class="title">KIMBALL STAR SCHEMA TẦNG CORE (3 DIMENSIONS + 3 FACTS)</text>
  <text x="40" y="56" class="subtitle">Liên kết quan hệ giữa Bảng Chiều (Không gian, Thời gian, Danh mục) và Bảng Sự kiện (Quan trắc, Khí tượng, Viễn thám)</text>

  <!-- DIMENSION 1: dim_grid_1km (TOP-LEFT) -->
  <rect x="40" y="80" width="260" height="190" class="dim-card" />
  <text x="55" y="105" class="dim-head">DIMENSION: dim_grid_1km</text>
  <text x="55" y="123" class="pk">PK  grid_id [VARCHAR]</text>
  <text x="55" y="140" class="col">    geometry [BLOB WKB 3405]</text>
  <text x="55" y="155" class="col">    easting_m, northing_m [DOUBLE]</text>
  <text x="55" y="170" class="col">    lon_wgs84, lat_wgs84 [DOUBLE]</text>
  <text x="55" y="185" class="col">    osm_primary_road_len_m [DOUBLE]</text>
  <text x="55" y="200" class="col">    worldcover_builtup_ratio [0..1]</text>
  <text x="55" y="215" class="col">    dem_elevation_mean_m [DOUBLE]</text>
  <text x="55" y="230" class="col">    era5_land_cell_id [VARCHAR]</text>
  <text x="55" y="250" font-family="'Segoe UI', sans-serif" font-size="10px" fill="#64748B">Số dòng: N_GRID thực + 1 unknown</text>

  <!-- DIMENSION 2: dim_date (TOP-RIGHT) -->
  <rect x="660" y="80" width="260" height="190" class="dim-card" />
  <text x="675" y="105" class="dim-head">DIMENSION: dim_date</text>
  <text x="675" y="123" class="pk">PK  date_id [INT32 YYYYMMDD]</text>
  <text x="675" y="140" class="col">    date_actual [DATE 2021..2025]</text>
  <text x="675" y="155" class="col">    year, month, day_of_year</text>
  <text x="675" y="170" class="col">    day_of_week, is_weekend</text>
  <text x="675" y="185" class="col">    hanoi_season [Winter/Spr/Sum/Aut]</text>
  <text x="675" y="200" class="col">    is_crop_burning_window [0/1]</text>
  <text x="675" y="215" class="col">    is_tet_holiday, is_covid_lockdown</text>
  <text x="675" y="250" font-family="'Segoe UI', sans-serif" font-size="10px" fill="#64748B">Số dòng: Đúng 1,827 dòng (1826 ngày + -1)</text>

  <!-- DIMENSION 3: dim_station (MIDDLE-LEFT) -->
  <rect x="40" y="330" width="260" height="190" class="dim-card" />
  <text x="55" y="355" class="dim-head">DIMENSION: dim_station</text>
  <text x="55" y="373" class="pk">PK  station_id [VARCHAR]</text>
  <text x="55" y="390" class="fk">FK  grid_id -&gt; dim_grid_1km</text>
  <text x="55" y="405" class="col">    station_name [VARCHAR]</text>
  <text x="55" y="420" class="col">    source_id [openaq/airnow/pamair]</text>
  <text x="55" y="435" class="col">    sensor_tier [Tier_1_FEM / Tier_2_Opt]</text>
  <text x="55" y="450" class="col">    station_microenv_type [Roadside/..]</text>
  <text x="55" y="465" class="col">    distance_to_primary_road_m</text>
  <text x="55" y="480" class="col">    is_active_flag [0/1]</text>
  <text x="55" y="500" font-family="'Segoe UI', sans-serif" font-size="10px" fill="#64748B">Số dòng: Trạm thực tế + station_unknown</text>

  <!-- FACT 1: fct_ground_truth_daily (MIDDLE-CENTER) -->
  <rect x="350" y="330" width="260" height="190" class="fact-card" />
  <text x="365" y="355" class="fact-head">FACT: fct_ground_truth_daily</text>
  <text x="365" y="373" class="pk">PK  (station_id, date_id)</text>
  <text x="365" y="390" class="fk">FK  station_id -&gt; dim_station</text>
  <text x="365" y="405" class="fk">FK  date_id -&gt; dim_date</text>
  <text x="365" y="420" class="fk">FK  grid_id -&gt; dim_grid_1km</text>
  <text x="365" y="435" class="col">    valid_hours_count [18..24]</text>
  <text x="365" y="450" class="col">    pm25_raw_mean [DOUBLE]</text>
  <text x="365" y="465" class="col">    pm25_calibrated_mean (Köhler)</text>
  <text x="365" y="480" class="col">    is_rh_corrected_flag, kappa_used</text>
  <text x="365" y="500" font-family="'Segoe UI', sans-serif" font-size="10px" fill="#B45309">Grain: (station_id, date_id) có &gt;=18h</text>

  <!-- FACT 2: fct_grid_meteo_daily (CENTER-TOP) -->
  <rect x="350" y="80" width="260" height="105" class="fact-card" />
  <text x="365" y="103" class="fact-head">FACT: fct_grid_meteo_daily</text>
  <text x="365" y="120" class="pk">PK  (grid_id, date_id)</text>
  <text x="365" y="135" class="col">    t2m, d2m, rh_mean_pct, total_precip</text>
  <text x="365" y="150" class="col">    wind_speed_scalar_ms, wind_persistence_P</text>
  <text x="365" y="165" class="col">    blh_mean_m, cams_pm25_bg_ugm3</text>
  <text x="365" y="178" font-family="'Segoe UI', sans-serif" font-size="9.5px" fill="#B45309">Quy mô: Đúng |S| = N_GRID x 1,826 dòng</text>

  <!-- FACT 3: fct_grid_satellite_daily (CENTER-BOTTOM) -->
  <rect x="350" y="200" width="260" height="105" class="fact-card" />
  <text x="365" y="223" class="fact-head">FACT: fct_grid_satellite_daily</text>
  <text x="365" y="240" class="pk">PK  (grid_id, date_id)</text>
  <text x="365" y="255" class="col">    s5p_no2_trop_mol_m2 (QA&gt;=0.75)</text>
  <text x="365" y="270" class="col">    modis_aod_550nm (scale 0.001)</text>
  <text x="365" y="285" class="col">    is_aod_missing_mnar [0/1]</text>
  <text x="365" y="298" font-family="'Segoe UI', sans-serif" font-size="9.5px" fill="#B45309">Quy mô: Đúng |S| = N_GRID x 1,826 dòng</text>

  <!-- MARTS PREVIEW (RIGHT-BOTTOM) -->
  <rect x="660" y="330" width="260" height="190" rx="6" ry="6" fill="#F5F3FF" stroke="#8B5CF6" stroke-width="1.5" />
  <text x="675" y="355" font-family="'Segoe UI', sans-serif" font-weight="700" font-size="13px" fill="#6D28D9">TẦNG MARTS LIÊN KẾT</text>
  <text x="675" y="375" font-weight="700" font-size="11px" fill="#DC2626">• mart_grid_daily_features</text>
  <text x="685" y="390" class="col">Tích Descartes dim_grid x dim_date</text>
  <text x="685" y="405" class="col">+ Left join fct_meteo &amp; fct_satellite</text>
  <text x="685" y="420" font-weight="700" font-size="10.5px" fill="#DC2626">CẤM CỘT NHÃN PM2.5 (100% SẠCH)</text>
  <text x="675" y="445" font-weight="700" font-size="11px" fill="#2563EB">• mart_grid_daily_eda</text>
  <text x="685" y="460" class="col">Features + grid_pm25_mean</text>
  <text x="675" y="485" font-weight="700" font-size="11px" fill="#059669">• mart_station_matched</text>
  <text x="685" y="500" class="col">Khớp Fact trạm ngày với vector ô 1km</text>

  <!-- RELATION LINES -->
  <!-- dim_grid to dim_station -->
  <line x1="170" y1="270" x2="170" y2="330" class="rel-line" />
  <!-- dim_station to fct_gt -->
  <line x1="300" y1="410" x2="350" y2="410" class="rel-line" />
  <!-- dim_date to fct_gt -->
  <path d="M 720 270 L 720 315 L 560 315 L 560 330" class="rel-line" />
  <!-- dim_grid to fct_meteo & sat -->
  <path d="M 300 130 L 350 130" class="rel-line" />
  <path d="M 300 240 L 350 240" class="rel-line" />
  <!-- dim_date to fct_meteo & sat -->
  <path d="M 660 130 L 610 130" class="rel-line" />
  <path d="M 660 240 L 610 240" class="rel-line" />
</svg><div class="diagram-caption">Mô hình hình sao chuẩn hóa: dim_grid_1km, dim_date, dim_station kết nối 3 bảng sự kiện ngày</div></div>

<div class="diagram-wrapper"><div class="diagram-title">SƠ ĐỒ 5: PHẢ HỆ DỮ LIỆU TỪ 9 NGUỒN TỚI CORE (SOURCE-TO-CORE LINEAGE)</div><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 480" width="960" height="480">
  <defs>
    <style>
      .bg { fill: #FFFFFF; }
      .title { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; font-size: 18px; fill: #14263D; }
      .subtitle { font-family: 'Segoe UI', Arial, sans-serif; font-size: 12px; fill: #64748B; }
      .node { rx: 6; ry: 6; stroke-width: 1.5; fill: #FFFFFF; }
      .n-gt { stroke: #3B82F6; }
      .n-met { stroke: #10B981; }
      .n-sat { stroke: #F59E0B; }
      .n-core { stroke: #8B5CF6; fill: #FAF5FF; }
      .txt-h { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; font-size: 12px; }
      .txt-b { font-family: 'Segoe UI', Arial, sans-serif; font-size: 10.5px; fill: #475569; }
      .edge { stroke: #94A3B8; stroke-width: 1.5; fill: none; marker-end: url(#ah); }
    </style>
    <marker id="ah" markerWidth="6" markerHeight="5" refX="5" refY="2.5" orient="auto">
      <polygon points="0 0, 6 2.5, 0 5" fill="#94A3B8" />
    </marker>
  </defs>

  <rect width="960" height="480" class="bg" />
  <text x="40" y="38" class="title">BẢN ĐỒ PHẢ HỆ DỮ LIỆU TỪ NGUỒN TỚI CORE (SOURCE-TO-CORE LINEAGE)</text>
  <text x="40" y="56" class="subtitle">Đường truyền dẫn dữ liệu từ 9 nhà cung cấp ngoại vi qua kiểm toán, làm sạch và hội tụ tại Star Schema</text>

  <!-- COLUMN 1: NGUỒN NGOẠI VI -->
  <text x="50" y="85" font-family="'Segoe UI', sans-serif" font-weight="700" font-size="12px" fill="#64748B">NGUỒN NGOẠI VI (9)</text>

  <rect x="40" y="100" width="140" height="45" class="node n-gt" />
  <text x="50" y="120" class="txt-h" fill="#1D4ED8">OpenAQ &amp; AirNow</text>
  <text x="50" y="135" class="txt-b">US Embassy / Reference</text>

  <rect x="40" y="155" width="140" height="45" class="node n-gt" />
  <text x="50" y="175" class="txt-h" fill="#1D4ED8">PAM Air Network</text>
  <text x="50" y="190" class="txt-b">Plantower PMS (Tier 2)</text>

  <rect x="40" y="210" width="140" height="45" class="node n-met" />
  <text x="50" y="230" class="txt-h" fill="#047857">ERA5-Land (CDS)</text>
  <text x="50" y="245" class="txt-b">~9km T2m, D2m, Wind, TP</text>

  <rect x="40" y="265" width="140" height="45" class="node n-met" />
  <text x="50" y="285" class="txt-h" fill="#047857">ERA5 BLH &amp; CAMS</text>
  <text x="50" y="300" class="txt-b">PBL Height / Background</text>

  <rect x="40" y="320" width="140" height="45" class="node n-sat" />
  <text x="50" y="340" class="txt-h" fill="#B45309">Sentinel-5P</text>
  <text x="50" y="355" class="txt-b">TROPOMI NO2, CO, Clouds</text>

  <rect x="40" y="375" width="140" height="45" class="node n-sat" />
  <text x="50" y="395" class="txt-h" fill="#B45309">MODIS MAIAC AOD</text>
  <text x="50" y="410" class="txt-b">MCD19A2 1km Optical</text>

  <rect x="40" y="430" width="140" height="40" class="node" stroke="#64748B" />
  <text x="50" y="448" class="txt-h" fill="#334155">OSM / WC / DEM</text>
  <text x="50" y="462" class="txt-b">Tĩnh 15 thuộc tính</text>

  <!-- COLUMN 2: RAW INGESTION -->
  <text x="240" y="85" font-family="'Segoe UI', sans-serif" font-weight="700" font-size="12px" fill="#64748B">RAW INGESTION</text>

  <rect x="230" y="110" width="150" height="75" class="node n-gt" />
  <text x="240" y="130" class="txt-h" fill="#1D4ED8">raw/ground_truth/</text>
  <text x="240" y="148" class="txt-b">• UTC window mở rộng</text>
  <text x="240" y="163" class="txt-b">• Hash _row_hash SHA-256</text>
  <text x="240" y="178" class="txt-b">• Idempotent append</text>

  <rect x="230" y="225" width="150" height="75" class="node n-met" />
  <text x="240" y="245" class="txt-h" fill="#047857">raw/atmospheric/</text>
  <text x="240" y="263" class="txt-b">• Native cell centroid</text>
  <text x="240" y="278" class="txt-b">• ~45 ERA5, ~8 BLH pts</text>
  <text x="240" y="293" class="txt-b">• Backoff HTTP 429</text>

  <rect x="230" y="340" width="150" height="75" class="node n-sat" />
  <text x="240" y="360" class="txt-h" fill="#B45309">raw/earth_obs/</text>
  <text x="240" y="378" class="txt-b">• Chunking quý (3 tháng)</text>
  <text x="240" y="393" class="txt-b">• Checkpointing an toàn</text>
  <text x="240" y="408" class="txt-b">• Raw bands reflectance</text>

  <!-- COLUMN 3: STAGING TRANSFORMS -->
  <text x="440" y="85" font-family="'Segoe UI', sans-serif" font-weight="700" font-size="12px" fill="#64748B">STAGING CLEANING</text>

  <rect x="430" y="100" width="160" height="55" class="node n-gt" />
  <text x="440" y="120" class="txt-h" fill="#1D4ED8">stg_ground_truth_hourly</text>
  <text x="440" y="135" class="txt-b">Giờ ICT, revision ranking</text>
  <text x="440" y="148" class="txt-b">Cờ cứng vs cờ nghi vấn</text>

  <rect x="430" y="165" width="160" height="60" class="node n-gt" />
  <text x="440" y="183" class="txt-h" fill="#1D4ED8">stg_ground_truth_daily</text>
  <text x="440" y="198" class="txt-b">Lọc &gt;= 18h hợp lệ</text>
  <text x="440" y="211" class="txt-b">Köhler kappa=0.35 Tier 2</text>

  <rect x="430" y="240" width="160" height="65" class="node n-met" />
  <text x="440" y="258" class="txt-h" fill="#047857">stg_meteo_daily</text>
  <text x="440" y="273" class="txt-b">Khử tích lũy mưa giờ</text>
  <text x="440" y="286" class="txt-b">Gió vô hướng V_scalar</text>
  <text x="440" y="299" class="txt-b">Tỷ số bền vững P</text>

  <rect x="430" y="325" width="160" height="65" class="node n-sat" />
  <text x="440" y="343" class="txt-h" fill="#B45309">stg_satellite_daily</text>
  <text x="440" y="358" class="txt-b">Lọc QA S5P &gt;= 0.75</text>
  <text x="440" y="371" class="txt-b">Nhân scale AOD 0.001</text>
  <text x="440" y="384" class="txt-b">Bật cờ mây MNAR</text>

  <!-- COLUMN 4: CORE STAR SCHEMA -->
  <text x="660" y="85" font-family="'Segoe UI', sans-serif" font-weight="700" font-size="12px" fill="#64748B">CORE STAR SCHEMA</text>

  <rect x="650" y="100" width="130" height="50" class="node n-core" />
  <text x="660" y="120" class="txt-h" fill="#6D28D9">dim_station</text>
  <text x="660" y="135" class="txt-b">Phân loại vi môi trường</text>
  <text x="660" y="146" class="txt-b">Roadside vs Background</text>

  <rect x="650" y="165" width="130" height="60" class="node n-core" />
  <text x="660" y="183" class="txt-h" fill="#6D28D9">fct_ground_truth</text>
  <text x="660" y="198" class="txt-b">Nồng độ bụi trạm</text>
  <text x="660" y="211" class="txt-b">PK: (station, date)</text>

  <rect x="650" y="240" width="130" height="65" class="node n-core" />
  <text x="660" y="258" class="txt-h" fill="#6D28D9">fct_grid_meteo</text>
  <text x="660" y="273" class="txt-b">Khí tượng ô 1km</text>
  <text x="660" y="286" class="txt-b">PK: (grid, date)</text>
  <text x="660" y="299" class="txt-b">Quy mô: Đúng |S|</text>

  <rect x="650" y="325" width="130" height="65" class="node n-core" />
  <text x="660" y="343" class="txt-h" fill="#6D28D9">fct_grid_satellite</text>
  <text x="660" y="358" class="txt-b">Viễn thám ô 1km</text>
  <text x="660" y="371" class="txt-b">PK: (grid, date)</text>
  <text x="660" y="384" class="txt-b">Quy mô: Đúng |S|</text>

  <rect x="650" y="405" width="130" height="55" class="node n-core" />
  <text x="660" y="423" class="txt-h" fill="#6D28D9">dim_grid_1km</text>
  <text x="660" y="438" class="txt-b">Lưới EPSG:3405</text>
  <text x="660" y="451" class="txt-b">15 biến tĩnh đô thị</text>

  <!-- COLUMN 5: MARTS -->
  <text x="825" y="85" font-family="'Segoe UI', sans-serif" font-weight="700" font-size="12px" fill="#64748B">PLATINUM MARTS</text>

  <rect x="815" y="150" width="130" height="85" rx="6" ry="6" fill="#FDF2F8" stroke="#EC4899" stroke-width="1.5" />
  <text x="825" y="170" class="txt-h" fill="#BE185D">mart_features</text>
  <text x="825" y="185" font-size="10px" font-weight="700" fill="#DC2626">SẠCH NHÃN 100%</text>
  <text x="825" y="200" class="txt-b">Chỉ biến độc lập</text>
  <text x="825" y="215" class="txt-b">Khớp |S| dòng</text>
  <text x="825" y="228" class="txt-b">Sẵn sàng ML</text>

  <rect x="815" y="260" width="130" height="85" rx="6" ry="6" fill="#F5F3FF" stroke="#8B5CF6" stroke-width="1.5" />
  <text x="825" y="280" class="txt-h" fill="#6D28D9">mart_eda</text>
  <text x="825" y="295" class="txt-b">Đặc trưng +</text>
  <text x="825" y="310" class="txt-b">Nhãn ô tổng hợp</text>
  <text x="825" y="325" class="txt-b">grid_pm25_mean</text>
  <text x="825" y="338" class="txt-b">6 Chuyên đề EDA</text>

  <rect x="815" y="370" width="130" height="75" rx="6" ry="6" fill="#EFF6FF" stroke="#3B82F6" stroke-width="1.5" />
  <text x="825" y="390" class="txt-h" fill="#1D4ED8">mart_matched</text>
  <text x="825" y="405" class="txt-b">Ghép trạm 100%</text>
  <text x="825" y="420" class="txt-b">Fact trạm ngày +</text>
  <text x="825" y="433" class="txt-b">Vector đặc trưng ô</text>

  <!-- CONNECTIONS -->
  <path d="M 180 120 L 230 130" class="edge" />
  <path d="M 180 175 L 230 160" class="edge" />
  <path d="M 180 230 L 230 250" class="edge" />
  <path d="M 180 285 L 230 270" class="edge" />
  <path d="M 180 340 L 230 360" class="edge" />
  <path d="M 180 395 L 230 380" class="edge" />
  
  <path d="M 380 145 L 430 125" class="edge" />
  <path d="M 430 135 L 430 175" class="edge" />
  <path d="M 380 260 L 430 270" class="edge" />
  <path d="M 380 375 L 430 355" class="edge" />

  <path d="M 590 125 L 650 125" class="edge" />
  <path d="M 590 195 L 650 195" class="edge" />
  <path d="M 590 270 L 650 270" class="edge" />
  <path d="M 590 355 L 650 355" class="edge" />
  <path d="M 180 445 L 650 435" class="edge" />

  <path d="M 780 270 L 815 190" class="edge" />
  <path d="M 780 355 L 815 200" class="edge" />
  <path d="M 780 435 L 815 210" class="edge" />
  <path d="M 815 190 L 815 260" class="edge" />
  <path d="M 780 195 L 815 400" class="edge" />
</svg><div class="diagram-caption">Phả hệ truy vết nguồn gốc dòng dữ liệu qua các bước biến đổi trung gian</div></div>

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

<div class="diagram-wrapper"><div class="diagram-title">SƠ ĐỒ 8: MA TRẬN PHÂN CÔNG RACI & GIAO THỨC BÀN GIAO LIÊN THÀNH VIÊN</div><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 460" width="960" height="460">
  <defs>
    <style>
      .bg { fill: #FFFFFF; }
      .title { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; font-size: 18px; fill: #14263D; }
      .subtitle { font-family: 'Segoe UI', Arial, sans-serif; font-size: 12px; fill: #64748B; }
      .eng-box { rx: 8; ry: 8; stroke-width: 1.5; fill: #FFFFFF; }
      .eng-tv1 { stroke: #2563EB; }
      .eng-tv2 { stroke: #059669; }
      .eng-tv3 { stroke: #D97706; }
      .eng-h { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; font-size: 13px; }
      .eng-b { font-family: 'Segoe UI', Arial, sans-serif; font-size: 11px; fill: #334155; }
      .h-flow { stroke: #64748B; stroke-width: 1.5; fill: none; marker-end: url(#ah-c); }
      .badge-raci { font-family: 'Segoe UI', sans-serif; font-weight: 700; font-size: 9px; rx: 3; ry: 3; }
    </style>
    <marker id="ah-c" markerWidth="6" markerHeight="5" refX="5" refY="2.5" orient="auto">
      <polygon points="0 0, 6 2.5, 0 5" fill="#64748B" />
    </marker>
  </defs>

  <rect width="960" height="460" class="bg" />
  <text x="40" y="38" class="title">MA TRẬN PHÂN CÔNG RACI &amp; GIAO THỨC BÀN GIAO LIÊN THÀNH VIÊN</text>
  <text x="40" y="56" class="subtitle">Phối hợp nhịp nhàng giữa 3 Kỹ sư: Phá vỡ bế tắc phụ thuộc (ADR-011) và hợp đồng bàn giao artifacts</text>

  <!-- 3 ENGINEERS -->
  <!-- TV1 -->
  <rect x="40" y="85" width="270" height="350" class="eng-box eng-tv1" />
  <rect x="40" y="85" width="270" height="32" rx="8" ry="8" fill="#EFF6FF" />
  <text x="55" y="106" class="eng-h" fill="#1E40AF">TV1: ngthinh06</text>
  <text x="180" y="105" font-family="'Segoe UI', sans-serif" font-size="10.5px" fill="#3B82F6">Architect &amp; Spatial</text>
  
  <text x="55" y="135" class="eng-b" font-weight="700">Trách nhiệm Cốt lõi (14 Tasks):</text>
  <text x="55" y="153" class="eng-b">• Kiến trúc Zero-RDBMS, Git &amp; CI/CD</text>
  <text x="55" y="170" class="eng-b">• Lưới 1km EPSG:3405 &amp; grid_manifest</text>
  <text x="55" y="187" class="eng-b">• Trục ngày 5 năm dim_date (1826 ngày)</text>
  <text x="55" y="204" class="eng-b">• Common io_parquet, hashing, runner</text>
  <text x="55" y="221" class="eng-b">• Spatial Join trạm vào ô lưới 1km</text>
  <text x="55" y="238" class="eng-b">• Phân loại vi môi trường trạm (Roadside)</text>
  <text x="55" y="255" class="eng-b">• Star Schema tầng Core (3 Dims + 3 Facts)</text>
  <text x="55" y="272" class="eng-b">• Feature Mart (SẠCH NHÃN 100%)</text>
  <text x="55" y="289" class="eng-b">• EDA Mart &amp; Matched View</text>
  <text x="55" y="306" class="eng-b">• EDA Chuyên đề 5 (OSM) &amp; CĐ 6 (Variogram)</text>
  <text x="55" y="323" class="eng-b">• Tổng hợp Báo cáo Sẵn sàng Dữ liệu</text>

  <rect x="55" y="340" width="240" height="80" rx="6" ry="6" fill="#F8FAFC" stroke="#CBD5E1" />
  <text x="65" y="360" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11px" fill="#1E293B">Bàn giao cho Đồng đội:</text>
  <text x="65" y="378" class="eng-b">→ TV3: Khung lưới 1km v1.0, trục ngày</text>
  <text x="65" y="393" class="eng-b">→ TV2: Hàm băm SHA-256, dim_station</text>
  <text x="65" y="408" class="eng-b">→ Toàn nhóm: Runner run.py, CI Actions</text>

  <!-- TV2 -->
  <rect x="345" y="85" width="270" height="350" class="eng-box eng-tv2" />
  <rect x="345" y="85" width="270" height="32" rx="8" ry="8" fill="#ECFDF5" />
  <text x="360" y="106" class="eng-h" fill="#065F46">TV2: hunganh</text>
  <text x="475" y="105" font-family="'Segoe UI', sans-serif" font-size="10.5px" fill="#10B981">Ground Truth &amp; QC</text>

  <text x="360" y="135" class="eng-b" font-weight="700">Trách nhiệm Cốt lõi (12 Tasks):</text>
  <text x="360" y="153" class="eng-b">• Feasibility Audit trạm (OpenAQ, PAM Air)</text>
  <text x="360" y="170" class="eng-b">• Raw Ingestion trạm mặt đất 5 năm</text>
  <text x="360" y="187" class="eng-b">• QC chuỗi giờ: Cờ cứng vs cờ nghi vấn</text>
  <text x="360" y="204" class="eng-b">• Hòa giải revision trạm bằng Window Func</text>
  <text x="360" y="221" class="eng-b">• Hiệu chỉnh độ ẩm Köhler (kappa=0.35)</text>
  <text x="360" y="238" class="eng-b">• Tổng hợp ngày: Bắt buộc &gt;= 18h hợp lệ</text>
  <text x="360" y="255" class="eng-b">• 9 Quy tắc DuckDB SQL (quality/rules.yml)</text>
  <text x="360" y="272" class="eng-b">• Mutation testing framework (sandbox 4 lỗi)</text>
  <text x="360" y="289" class="eng-b">• Sổ cái làm sạch docs/cleaning_log.md</text>
  <text x="360" y="306" class="eng-b">• EDA Chuyên đề 1 (Khuyết thiếu MNAR)</text>
  <text x="360" y="323" class="eng-b">• EDA Chuyên đề 2 (Độ nhạy Köhler/Hampel)</text>

  <rect x="360" y="340" width="240" height="80" rx="6" ry="6" fill="#F8FAFC" stroke="#CBD5E1" />
  <text x="370" y="360" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11px" fill="#1E293B">Bàn giao cho Đồng đội:</text>
  <text x="370" y="378" class="eng-b">→ TV1: stg_ground_truth_daily (&gt;=18h)</text>
  <text x="370" y="393" class="eng-b">→ TV1: Cổng chất lượng quality/rules.yml</text>
  <text x="370" y="408" class="eng-b">← TV3: Nhận RH ERA5 để hiệu chỉnh ẩm</text>

  <!-- TV3 -->
  <rect x="650" y="85" width="270" height="350" class="eng-box eng-tv3" />
  <rect x="650" y="85" width="270" height="32" rx="8" ry="8" fill="#FFFBEB" />
  <text x="665" y="106" class="eng-h" fill="#B45309">TV3: minh</text>
  <text x="760" y="105" font-family="'Segoe UI', sans-serif" font-size="10.5px" fill="#F59E0B">Atmospheric &amp; EO</text>

  <text x="665" y="135" class="eng-b" font-weight="700">Trách nhiệm Cốt lõi (10 Tasks):</text>
  <text x="665" y="153" class="eng-b">• Feasibility Audit GEE / CDS Vệ tinh</text>
  <text x="665" y="170" class="eng-b">• Trích xuất 15 biến tĩnh đô thị (OSM/WC/DEM)</text>
  <text x="665" y="187" class="eng-b">• Ingest ERA5-Land (~9km) &amp; BLH (~25km)</text>
  <text x="665" y="204" class="eng-b">• Ingest Sentinel-5P, MODIS AOD, VIIRS</text>
  <text x="665" y="221" class="eng-b">• Khử tích lũy lượng mưa giờ ERA5-Land</text>
  <text x="665" y="238" class="eng-b">• Tính gió vô hướng V_scalar &amp; Bền vững P</text>
  <text x="665" y="255" class="eng-b">• Tính Magnus RH, xuất bảng hỗ trợ cho TV2</text>
  <text x="665" y="272" class="eng-b">• Cờ mây MNAR viễn thám mùa đông</text>
  <text x="665" y="289" class="eng-b">• EDA Chuyên đề 3 (STL 5 năm &amp; BLH)</text>
  <text x="665" y="306" class="eng-b">• EDA Chuyên đề 4 (Tương quan đa nguồn n_eff)</text>

  <rect x="665" y="340" width="240" height="80" rx="6" ry="6" fill="#F8FAFC" stroke="#CBD5E1" />
  <text x="675" y="360" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11px" fill="#1E293B">Bàn giao cho Đồng đội:</text>
  <text x="675" y="378" class="eng-b">→ TV1: Lưới 1km v1.1 (đủ 15 biến tĩnh)</text>
  <text x="675" y="393" class="eng-b">→ TV1: stg_meteo_daily, stg_satellite_daily</text>
  <text x="675" y="408" class="eng-b">→ TV2: stg_meteo_daily (RH cho Köhler)</text>
</svg><div class="diagram-caption">5 điểm bàn giao then chốt giữa 3 kỹ sư kèm câu lệnh xác minh tự động</div></div>

<div class="diagram-wrapper"><div class="diagram-title">SƠ ĐỒ 6: ĐỒ THỊ PHỤ THUỘC TÁC VỤ & ĐƯỜNG GĂNG CRITICAL PATH (116H)</div><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 480" width="960" height="480">
  <defs>
    <style>
      .bg { fill: #FFFFFF; }
      .title { font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; font-size: 18px; fill: #14263D; }
      .subtitle { font-family: 'Segoe UI', Arial, sans-serif; font-size: 12px; fill: #64748B; }
      .t-node { rx: 5; ry: 5; stroke-width: 1.5; fill: #FFFFFF; }
      .t-crit { fill: #FEF2F2; stroke: #DC2626; stroke-width: 2; }
      .t-norm { fill: #F8FAFC; stroke: #94A3B8; }
      .lbl-id { font-family: 'Consolas', monospace; font-size: 10px; font-weight: 700; }
      .lbl-name { font-family: 'Segoe UI', Arial, sans-serif; font-size: 9.5px; fill: #334155; }
      .e-crit { stroke: #DC2626; stroke-width: 2; fill: none; marker-end: url(#ah-red); }
      .e-norm { stroke: #94A3B8; stroke-width: 1.2; stroke-dasharray: 3 2; fill: none; marker-end: url(#ah-gray); }
    </style>
    <marker id="ah-red" markerWidth="6" markerHeight="5" refX="5" refY="2.5" orient="auto">
      <polygon points="0 0, 6 2.5, 0 5" fill="#DC2626" />
    </marker>
    <marker id="ah-gray" markerWidth="6" markerHeight="5" refX="5" refY="2.5" orient="auto">
      <polygon points="0 0, 6 2.5, 0 5" fill="#94A3B8" />
    </marker>
  </defs>

  <rect width="960" height="480" class="bg" />
  <text x="40" y="38" class="title">ĐỒ THỊ PHỤ THUỘC TÁC VỤ &amp; ĐƯỜNG GĂNG (CRITICAL PATH DAG - 116H)</text>
  <text x="40" y="56" class="subtitle">Đường màu đỏ: Chuỗi công việc găng quyết định tiến độ toàn dự án · Đường nét đứt: Tác vụ chạy song song</text>

  <!-- PHASE 1 -->
  <rect x="40" y="90" width="130" height="40" class="t-node t-crit" />
  <text x="48" y="105" class="lbl-id" fill="#DC2626">TASK-ARCH-01 (8h)</text>
  <text x="48" y="120" class="lbl-name">Sinh Lưới &amp; Manifest</text>

  <rect x="40" y="150" width="130" height="35" class="t-node t-norm" />
  <text x="48" y="165" class="lbl-id" fill="#2563EB">TASK-ARCH-02 (4h)</text>
  <text x="48" y="178" class="lbl-name">Trục ngày dim_date</text>

  <rect x="40" y="200" width="130" height="35" class="t-node t-norm" />
  <text x="48" y="215" class="lbl-id" fill="#059669">TASK-GT-01 (8h)</text>
  <text x="48" y="228" class="lbl-name">Audit Trạm mặt đất</text>

  <rect x="40" y="250" width="130" height="35" class="t-node t-norm" />
  <text x="48" y="265" class="lbl-id" fill="#D97706">TASK-MET-01 (8h)</text>
  <text x="48" y="278" class="lbl-name">Audit GEE/CDS Vệ tinh</text>

  <!-- PHASE 1 CRIT TO MET-02 -->
  <rect x="195" y="90" width="130" height="40" class="t-node t-crit" />
  <text x="203" y="105" class="lbl-id" fill="#DC2626">TASK-MET-02 (10h)</text>
  <text x="203" y="120" class="lbl-name">15 Biến Tĩnh Đô thị</text>

  <!-- PHASE 2 CRIT TO ARCH-04 -->
  <rect x="350" y="90" width="130" height="40" class="t-node t-crit" />
  <text x="358" y="105" class="lbl-id" fill="#DC2626">TASK-ARCH-04 (6h)</text>
  <text x="358" y="120" class="lbl-name">Hàm Băm &amp; Ghi Idemp</text>

  <rect x="350" y="150" width="130" height="35" class="t-node t-norm" />
  <text x="358" y="165" class="lbl-id" fill="#2563EB">TASK-ARCH-05 (8h)</text>
  <text x="358" y="178" class="lbl-name">Mock Seeder CI/CD</text>

  <!-- INGESTION PARALLEL (CRIT) -->
  <rect x="505" y="90" width="130" height="40" class="t-node t-crit" />
  <text x="513" y="105" class="lbl-id" fill="#DC2626">TASK-GT-04 (12h)</text>
  <text x="513" y="120" class="lbl-name">Ingest PAM Air 5 năm</text>

  <rect x="505" y="145" width="130" height="40" class="t-node t-crit" />
  <text x="513" y="160" class="lbl-id" fill="#DC2626">TASK-MET-04 (12h)</text>
  <text x="513" y="175" class="lbl-name">Ingest GEE Vệ tinh 5n</text>

  <rect x="505" y="200" width="130" height="35" class="t-node t-norm" />
  <text x="513" y="215" class="lbl-id" fill="#059669">TASK-GT-03 (6h)</text>
  <text x="513" y="228" class="lbl-name">Ingest OpenAQ/AirNow</text>

  <rect x="505" y="250" width="130" height="35" class="t-node t-norm" />
  <text x="513" y="265" class="lbl-id" fill="#D97706">TASK-MET-03 (8h)</text>
  <text x="513" y="278" class="lbl-name">Ingest ERA5 / CAMS</text>

  <!-- PHASE 3 STAGING CRIT -->
  <rect x="660" y="90" width="130" height="40" class="t-node t-crit" />
  <text x="668" y="105" class="lbl-id" fill="#DC2626">TASK-MET-05 (10h)</text>
  <text x="668" y="120" class="lbl-name">Meteo &amp; Xuất RH ERA5</text>

  <rect x="660" y="145" width="130" height="40" class="t-node t-crit" />
  <text x="668" y="160" class="lbl-id" fill="#DC2626">TASK-GT-06 (10h)</text>
  <text x="668" y="175" class="lbl-name">Köhler &amp; Daily &gt;=18h</text>

  <rect x="660" y="200" width="130" height="35" class="t-node t-norm" />
  <text x="668" y="215" class="lbl-id" fill="#059669">TASK-GT-05 (12h)</text>
  <text x="668" y="228" class="lbl-name">QC Giờ &amp; Staging hourly</text>

  <!-- PHASE 4 CORE & MARTS CRIT -->
  <rect x="810" y="90" width="125" height="35" class="t-node t-crit" />
  <text x="818" y="105" class="lbl-id" fill="#DC2626">TASK-ARCH-08 (8h)</text>
  <text x="818" y="118" class="lbl-name">Đóng gói Star Schema</text>

  <rect x="810" y="135" width="125" height="35" class="t-node t-crit" />
  <text x="818" y="150" class="lbl-id" fill="#DC2626">TASK-ARCH-09 (8h)</text>
  <text x="818" y="163" class="lbl-name">Feature Mart (Sạch nhãn)</text>

  <!-- PHASE 5 QUALITY GATE CRIT -->
  <rect x="660" y="310" width="130" height="35" class="t-node t-crit" />
  <text x="668" y="325" class="lbl-id" fill="#DC2626">TASK-GT-08 (8h)</text>
  <text x="668" y="338" class="lbl-name">Thiết kế 9 Rules SQL</text>

  <rect x="505" y="310" width="130" height="35" class="t-node t-crit" />
  <text x="513" y="325" class="lbl-id" fill="#DC2626">TASK-GT-10 (10h)</text>
  <text x="513" y="338" class="lbl-name">Mutation Tester 4 lỗi</text>

  <rect x="350" y="310" width="130" height="35" class="t-node t-crit" />
  <text x="358" y="325" class="lbl-id" fill="#DC2626">TASK-ARCH-11 (4h)</text>
  <text x="358" y="338" class="lbl-name">Tích hợp CI/CD &amp; CLI</text>

  <!-- PHASE 6 EDA & FINAL -->
  <rect x="195" y="310" width="130" height="35" class="t-node t-crit" />
  <text x="203" y="325" class="lbl-id" fill="#DC2626">6 CHUYÊN ĐỀ EDA (12h)</text>
  <text x="203" y="338" class="lbl-name">TV1, TV2, TV3 song song</text>

  <rect x="40" y="310" width="130" height="45" class="t-node t-crit" fill="#FEF3C7" stroke="#F59E0B" />
  <text x="48" y="328" class="lbl-id" fill="#B45309">TASK-ARCH-14 (10h)</text>
  <text x="48" y="343" class="lbl-name">Data Readiness Report</text>
  <text x="48" y="353" font-size="9px" font-weight="700" fill="#DC2626">RELEASE TAG v2.1</text>

  <!-- CRITICAL PATH LINES -->
  <path d="M 170 110 L 195 110" class="e-crit" />
  <path d="M 325 110 L 350 110" class="e-crit" />
  <path d="M 480 110 L 505 110" class="e-crit" />
  <path d="M 480 110 L 505 160" class="e-crit" />
  <path d="M 635 160 L 660 110" class="e-crit" />
  <path d="M 725 130 L 725 145" class="e-crit" />
  <path d="M 790 155 L 810 110" class="e-crit" />
  <path d="M 872 125 L 872 135" class="e-crit" />
  <path d="M 872 170 L 872 290 L 725 290 L 725 310" class="e-crit" />
  <path d="M 660 327 L 635 327" class="e-crit" />
  <path d="M 505 327 L 480 327" class="e-crit" />
  <path d="M 350 327 L 325 327" class="e-crit" />
  <path d="M 195 327 L 170 327" class="e-crit" />

  <!-- LEGEND -->
  <rect x="40" y="420" width="895" height="45" rx="6" ry="6" fill="#F8FAFC" stroke="#E2E8F0" />
  <line x1="60" y1="442" x2="90" y2="442" stroke="#DC2626" stroke-width="2.5" />
  <text x="100" y="446" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11px" fill="#DC2626">ĐƯỜNG GĂNG (CRITICAL PATH): 116 GIỜ KỸ THUẬT</text>
  <line x1="380" y1="442" x2="410" y2="442" stroke="#94A3B8" stroke-width="1.5" stroke-dasharray="4 2" />
  <text x="420" y="446" font-family="'Segoe UI', sans-serif" font-size="11px" fill="#475569">Nhánh công việc chạy song song (Non-critical)</text>
  <text x="730" y="446" font-family="'Segoe UI', sans-serif" font-weight="600" font-size="11px" fill="#1E293B">Tổng cộng: 36 Tasks · 6 Phases</text>
</svg><div class="diagram-caption">Phân tích đường găng dài nhất từ hạ tầng lưới, thu thập dữ liệu đến EDA tổng hợp</div></div>

---


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

---


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

---


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

