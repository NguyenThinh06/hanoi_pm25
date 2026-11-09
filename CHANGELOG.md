# Changelog

Tất cả những thay đổi đáng chú ý của dự án **HANOI_PM25** được ghi nhận trong file này.
Định dạng được xây dựng dựa trên tiêu chuẩn [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), và tuân thủ nguyên tắc [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-11-10

### 🚀 Tính Năng Mới (Added)

#### 1. Data Lakehouse & Xử Lý Không Gian (Gói 1)
- **Thu thập đa nguồn:** Tích hợp dữ liệu từ 43 trạm quan trắc mặt đất (OpenAQ v3), dữ liệu tái phân tích khí tượng ERA5 Reanalysis (0,25°), độ dày quang học sol khí AOD 0,47 µm từ MODIS (Terra/Aqua 1 km), nồng độ cột đối lưu $\text{NO}_2, \text{CO}, \text{O}_3, \text{SO}_2$ từ Sentinel-5P và bức xạ ánh sáng ban đêm hàng tháng từ VIIRS.
- **Tiền xử lý & Kiểm soát chất lượng (QC):** Chuẩn hóa toàn bộ mốc thời gian về múi giờ địa phương Hà Nội (UTC+7); áp dụng ngưỡng kiểm soát chất lượng nghiêm ngặt (chỉ công nhận ngày hợp lệ `is_valid_day = 1` khi có ít nhất 18 giờ quan trắc hợp lệ/ngày).
- **Kiến trúc Data Lakehouse (Star Schema):**
  - Tầng Core với các bảng chiều `dim_grid_1km` (3.610 ô lưới chuẩn hóa hệ tọa độ VN-2000 / UTM Zone 48N `EPSG:3405`), `dim_date` (2.099 ngày từ 2021 đến 2026), và `dim_station` (thông tin các trạm quan trắc).
  - Tầng bảng sự kiện `fct_station_daily_observations`, `fct_grid_meteo_daily`, `fct_grid_satellite_daily`.
  - Tầng Data Marts xuất ra `mart_station_daily_training.parquet` (7.290 mẫu huấn luyện sạch trên 30 ô lưới) và `mart_grid_daily_features.parquet` (hơn 7,57 triệu bản ghi đặc trưng toàn lưới 5 năm).

#### 2. Mô Hình Học Máy & Thẩm Định Khoa Học (Gói 2)
- **Hai mô hình học máy cơ sở (XGBoost Regressor):**
  - `Baseline 1` (27 đặc trưng): Kết hợp lịch, chu kỳ mùa, tọa độ không gian và các biến khí tượng ERA5 (nhiệt độ, độ ẩm, áp suất, tốc độ gió, hướng gió, lượng mưa, độ cao lớp biên BLH).
  - `Baseline 2` (34 đặc trưng): Bổ sung 7 biến viễn thám vệ tinh (AOD MODIS, khí quyển Sentinel-5P, ánh sáng ban đêm VIIRS).
- **Ba phương pháp đánh giá khoa học trung thực:**
  - `Spatial GroupKFold` (5 folds chia theo cụm ô lưới): Tránh hoàn toàn hiện tượng rò rỉ dữ liệu không gian; chứng minh Baseline 2 vượt trội với MAE $11,05\ \mu\text{g/m}^3$, $R^2 = 0,5894$ (giảm $4,7\%$ sai số so với Baseline 1).
  - `Temporal Split` (Huấn luyện 2021–2025, kiểm thử 2026 độc lập): Đánh giá năng lực tổng quát hóa theo dòng thời gian.
  - `Random KFold` (Tham chiếu dòng): Minh họa hiện tượng rò rỉ không gian khiến điểm số bị thổi phồng ảo ($R^2 \approx 0,838$).
- **Engine suy luận batch độc lập (`src/models/inference.py`):**
  - Chạy suy luận trực tiếp từ artifact model đã lưu mà không huấn luyện lại.
  - Hỗ trợ cơ chế resume thông minh dựa trên kiểm tra toàn vẹn partition, ghi file nguyên tử (`.tmp` $\to$ `.parquet`) và sinh `manifest.json` có mã băm SHA-256.

#### 3. Serving Platform & REST API (Gói 2 & 4)
- **Cơ sở dữ liệu không gian PostGIS:**
  - Bảng `grid_daily_predictions` được phân vùng (partitioned) theo tháng; bảng `dim_grid_1km` lưu trữ hình học polygon dạng nhị phân PostGIS Geometry (`SRID=4326`) hỗ trợ truy vấn không gian dưới 50ms.
  - Tự động áp dụng migration DDL khi khởi tạo database.
- **Backend FastAPI chuẩn RESTful:**
  - Cung cấp 6 API endpoints: `/api/models`, `/api/dates`, `/api/grids`, `/api/map`, `/api/history`, `/api/stations`.
  - Bộ nhớ đệm RAM In-Memory Cache sử dụng giải thuật LRU, giới hạn byte và luồng truy cập an toàn.
  - CORS Middleware hỗ trợ cả môi trường production Docker và môi trường dev cục bộ.

#### 4. Giao Diện Bản Đồ React Dashboard (Gói 3)
- **Single Page Application hiện đại:** Xây dựng với React 18, Vite và Tailwind CSS.
- **Bản đồ không gian Leaflet Canvas:** Render mượt mà 3.610 ô lưới polygon trong một khung hình Canvas duy nhất ở tốc độ 60 FPS, không gây giật lag trình duyệt.
- **Trải nghiệm người dùng:** Bộ lọc linh hoạt ngày bất kỳ từ 2021 đến 2026; chuyển đổi tức thời giữa Baseline 1 và Baseline 2; lớp hiển thị số đo trạm thực tế; biểu đồ chuỗi thời gian nồng độ bụi cả năm khi click vào ô lưới.

#### 5. Đóng Gói Docker & Tự Động Hóa Vận Hành (Gói 4)
- **Kiến trúc cụm 4 containers:** Database (`PostGIS 16`), Backend (`FastAPI`), Frontend (`React`), và Nginx Reverse Proxy điều phối tại cổng 80.
- **Khởi động 1-chạm (`run.ps1` / `run.sh`):** Tự động tạo cấu hình môi trường `.env`, build ảnh Docker, khởi động container và tự mở trình duyệt web.
- **Tối ưu hóa khởi động nhanh:** Tích hợp chế độ `IMPORT_SMOKE_MONTH=2024-01`, nạp 1 tháng dữ liệu mẫu trong 5 giây để dashboard sẵn sàng sử dụng ngay lập tức.
- **Bộ công cụ DevOps:** Script import toàn bộ dữ liệu (`import_predictions.py`), script đối soát số liệu 3 điểm (`verify_reconciliation.py`), và công cụ backup/restore database (`backup_restore.ps1`).

#### 6. Hệ Thống Tài Liệu Cốt Lõi
- `docs/business_case.md`: Định vị bài toán thực tế, làm rõ khoảng trống 30 ô có trạm vs 3.580 ô ngoại thành, ranh giới 3 Không và 4 câu hỏi nghiên cứu cốt lõi.
- `docs/schema.md`: Đặc tả chi tiết lược đồ bảng dữ liệu Data Lakehouse.
- `archive/`: Lưu trữ các tài liệu đặc tả kỹ thuật chi tiết (`HANDOVER.md`, `DEPLOYMENT.md`, `BACKEND.md`, `report.md`, `model_report.md`).

---

### 🔧 Thay Đổi & Cải Tiến (Changed)
- Đồng bộ hóa toàn bộ phiên bản dự án lên `v1.0.0` trong `pyproject.toml`, API OpenAPI metadata và giao diện người dùng.
- Tinh gọn thư mục `docs/` để làm nổi bật trọng tâm khoa học dữ liệu và cấu trúc bảng phục vụ thuyết trình và báo cáo đồ án.
- Bổ sung Node.js 22 test & build step vào GitHub Actions CI pipeline.

---

### 🐛 Vá Lỗi (Fixed)
- Khắc phục lỗi `FileNotFoundError` trong `test_model_reload_and_prediction_match` trên GitHub Actions CI khi chạy môi trường không có model artifact local.
- Sửa lỗi schema kiểm tra partition resume trong module inference để đảm bảo khớp số lượng bản ghi và số ngày.
- Chuẩn hóa toàn bộ mã nguồn theo chuẩn linter Ruff, sửa các cảnh báo import thừa và định dạng chuỗi.
