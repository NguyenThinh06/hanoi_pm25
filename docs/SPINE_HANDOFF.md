# Bàn giao lưới và trục ngày — hợp đồng 2.0

Nguồn cấu hình chung: `data/manifests/grid_manifest.json`.

## Tập phân tích

- N_GRID = `analysis_grid_count` = **3.610**, chọn ô bằng `cell.intersects(boundary_union)`.
- Giữ nguyên hình vuông 1.000 × 1.000 m trong EPSG:3405; không cắt geometry theo ranh giới.
- Gốc lưới (0, 0), đường lưới tại bội số 1.000 m. Bounding box ứng viên được làm tròn ra ngoài và đệm một ô để giữ cả ô chỉ chạm biên nếu biên trùng đường lưới.
- `grid_id = grid_{x}_{y}` dùng góc dưới trái; `easting_m`, `northing_m` là tâm ô.
- 3.363 ô `is_canonical = 1` có tâm nằm nghiêm ngặt trong ranh giới; đây là tập con tùy chọn, **không phải N_GRID**.
- `intersects` bao gồm ô chỉ chạm biên. Manifest ghi `boundary_touch_only_cells`; với file đóng băng hiện tại kỳ vọng bằng 0. Thay nguồn ranh giới phải đánh giá lại quy tắc và tăng phiên bản.
- `area_in_boundary_km2` lưu diện tích giao không làm tròn để tránh nhầm phần giao rất nhỏ với chỉ chạm biên.
- `dim_grid_1km`: **3.611 dòng**, gồm một `grid_unknown` với geometry null. Unknown không phải ô vật lý và không tham gia phân tích.

## Trục ngày và khung ô–ngày

- Ngày thật: 2021-01-01 đến 2025-12-31, liên tục, **1.826 ngày**, gồm 2024-02-29.
- `date_id`: INT32 dạng YYYYMMDD. Cột ngày là `date_actual`.
- `dim_date`: **1.827 dòng**, gồm một dòng `date_id = -1`, `date_actual = 1970-01-01` làm sentinel.
- Khung phân tích: lọc `grid_id != 'grid_unknown'` và `date_id != -1` **trước** tích Descartes.
- Khóa duy nhất `(grid_id, date_id)`; số dòng kỳ vọng **6.591.860 = 3.610 × 1.826**.
- Facts có khóa unknown vẫn được lưu để kiểm tra chất lượng, nhưng không đưa unknown vào tập ô–ngày phân tích.

Ví dụ tạo khóa bằng Polars, đọc số dòng kỳ vọng từ manifest:

```python
import json
import polars as pl

with open("data/manifests/grid_manifest.json", encoding="utf-8") as f:
    manifest = json.load(f)
grids = pl.read_parquet("data/core/dim_grid_1km.parquet").filter(
    pl.col("grid_id") != manifest["grid_unknown_id"]
).select("grid_id")
dates = pl.read_parquet("data/core/dim_date.parquet").filter(
    pl.col("date_id") != manifest["date_unknown_id"]
).select("date_id")
spine = grids.join(dates, how="cross")
assert spine.height == manifest["expected_grid_day_rows"]
```

## Tái tạo và kiểm tra

Chạy tại thư mục gốc dự án, trong môi trường Python >= 3.12 đã kích hoạt. Các phiên bản thư viện được cố định trong `requirements-spine.txt` và CI dùng cùng file này.

```text
python -m pip install -r requirements-spine.txt
python run.py grid
python run.py date
python -m pytest tests/unit/ -v
python -m ruff check .
```

CI hiện chạy `tests/unit/`, vì vậy các test bàn giao được chạy tự động mà không cần thêm job. Tests tạo dữ liệu trong thư mục tạm, đối chiếu manifest đã lưu và kiểm tra khóa ô–ngày thực tế. Parquet sinh ra được gitignore; bàn giao qua code + ranh giới + manifest + môi trường. Không cần commit hàng triệu dòng.

Kiểm tra dùng Python 3.13.5 trên Windows; workflow vẫn dùng Python 3.12 trên Ubuntu. CI đọc ranh giới đã lưu trong Git và kiểm tra checksum, không tải dữ liệu mạng khi chạy test. Kết quả GitHub Actions cần được xác nhận khi mở/cập nhật PR.

Kiểm tra test trước khi chủ động tái sinh manifest nếu đang đánh giá một thay đổi ranh giới. Không tự chấp nhận số ô mới chỉ vì script đã cập nhật manifest.

## Nguồn ranh giới và giới hạn bàn giao

Nguồn được chọn: **General Statistics Office of Vietnam (GSO), Viet Nam — Subnational Administrative Boundaries, COD-AB version 02**, phân phối bởi OCHA ROAP / FIS qua [HDX](https://data.humdata.org/dataset/cod-ab-vnm). Metadata có thể đọc qua [HDX API](https://data.humdata.org/api/3/action/package_show?id=cod-ab-vnm).

- Ranh giới nguồn: **01/07/2025**; OCHA kiểm tra và công bố hợp lệ: **25/09/2025**.
- File nguồn `vnm_admin_boundaries.geojson.zip`, resource `048a6012-a8c2-4fa9-be87-cb6c01e9afbf`; lấy `vnm_admin1.geojson`, chọn duy nhất `adm1_pcode = VN01`, `adm1_name = Ha Noi`.
- Giữ nguyên tọa độ, thứ tự đỉnh và thuộc tính; không simplify, buffer hay tự sửa polygon. GeoJSON lưu EPSG:4326, chỉ chuyển sang EPSG:3405 khi sinh lưới.
- Giấy phép [CC BY 3.0 IGO](https://creativecommons.org/licenses/by/3.0/igo/). Ghi công: General Statistics Office of Vietnam (GSO); OCHA ROAP / FIS, HDX COD-AB v02; nhóm dự án trích riêng Hà Nội, không sửa hình học.
- SHA-256 ZIP, SHA-256 GeoJSON trích xuất, URL tải, ngày tải và metadata nguồn được lưu trong `data/reference/hanoi_boundary.provenance.json`.

Tái tạo file ranh giới đã đóng băng khi cần:

```text
python -m src.ingest.fetch_hanoi_boundary
```

Lệnh dùng bản ZIP cache trong `data/raw/boundary_sources/hdx_2025.zip` hoặc tải từ HDX. Nếu nhà cung cấp thay nội dung ZIP, checksum không khớp thì dừng để đánh giá phiên bản mới; không âm thầm đổi ranh giới. Ranh giới đã trích xuất được lưu cùng dự án để không phụ thuộc việc URL nguồn còn hoạt động.

Đây là nguồn phân tích có xuất xứ chính phủ, đã qua quy trình COD-AB, **không phải hồ sơ đo đạc địa chính hoặc chứng nhận ranh giới pháp lý**. Không có căn cứ để khẳng định đây là dữ liệu chính xác nhất tuyệt đối trong mọi mục đích.

Dự án dùng cố định dấu chân Hà Nội phiên bản 2025 cho toàn chuỗi 2021–2025. Không diễn giải thành ranh giới lịch sử riêng từng năm. [Cổng thông tin Hà Nội](https://hanoi.gov.vn/tin-tuc-su-kien-noi-bat/chu-tich-nuoc-luong-cuong-du-le-cong-bo-sap-xep-don-vi-hanh-chinh-tai-thanh-pho-ha-noi-4250630115244249.htm) xác nhận Hà Nội không sáp nhập cấp tỉnh năm 2025; điều đó không chứng minh mọi tọa độ biên không thay đổi qua các năm.

## Đối chiếu nguồn và chuyển đổi từ v1.2

| Nguồn | Năm đại diện | Diện tích tính trong EPSG:3405 | Đánh giá |
|---|---|---:|---|
| geoBoundaries gbOpen, nguồn Wikipedia | 2008 | 3.212,620 km² | Hình học khớp hoàn toàn file cũ; không chọn làm chuẩn |
| geoBoundaries gbHumanitarian, Government of Viet Nam / HDX | 2020 | 3.354,351 km² | Nguồn lịch sử có xuất xứ rõ, bản lưu tại commit `9469f09` |
| GSO / HDX COD-AB v02 | 2025 | 3.356,232 km² | Chọn: nguồn trực tiếp có metadata kiểm tra, giấy phép và hình học chi tiết |

Metadata hai bản geoBoundaries: [gbOpen](https://www.geoboundaries.org/api/current/gbOpen/VNM/ADM1/), [gbHumanitarian](https://www.geoboundaries.org/api/current/gbHumanitarian/VNM/ADM1/). Hình học đã được so sánh với các file không giản lược tại commit `9469f09`.

Thuộc tính diện tích do nguồn HDX cung cấp là 3.359,77 km²; không ép diện tích hình học trong hệ chiếu EPSG:3405 phải bằng thuộc tính đó. Chênh lệch hình học đối xứng giữa bản 2020 và 2025 khoảng 31,468 km², do đó không coi chúng là cùng một hình học.

- Lưới cũ: 3.442 ô; lưới mới: **3.610 ô**. Chung 2.760 ô, thêm 850 ô, loại 682 ô. Không chỉ nối thêm 168 dòng.
- Hợp đồng và manifest tăng lên **2.0**; khung ô–ngày mới **6.591.860 dòng**.
- Các tập ô–ngày, đặc trưng phủ lưới và dự đoán sinh từ lưới cũ cần tái tạo/join lại theo tập khóa mới, đồng thời kiểm tra dữ liệu thiếu cho 850 ô mới.
- Kiểm tra các dữ liệu hiện có: 43 trạm trong registry và khóa grid trong `dim_station.parquet`, `fct_ground_truth_daily.parquet` đều còn thuộc lưới mới. Việc này không thay thế kiểm tra chất lượng quan trắc.
