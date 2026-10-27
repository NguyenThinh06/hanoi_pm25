# Bàn giao phần TV2: đặc trưng lưới và viễn thám 2021–2025

**Nhánh làm việc:** `feat/tv2-extract-static-grid`  
**Người phụ trách:** TV2 (`hunganh`)  
**Trạng thái:** Đã tạo và kiểm tra trên máy; chờ TV1 review hợp đồng, nhận các file dữ liệu và tích hợp. Chưa có mart hoàn chỉnh.

## 1. TV2 đã làm gì?

TV2 nhận lưới 1 km `EPSG:3405` và trục ngày từ TV1. Có 3.610 ô phân tích, một dòng `grid_unknown`, và 1.826 ngày trong giai đoạn 2021–2025.

1. **Đặc trưng ô lưới:** Tính hai biến đường OpenStreetMap (OSM), bốn tỷ lệ lớp phủ ESA WorldCover 2021 và hai biến địa hình NASA SRTM. OSM có snapshot riêng cho từng năm 2021–2025.
2. **Vệ tinh:** Xuất AOD MODIS MAIAC, NO₂ Sentinel-5P L3 và ánh sáng đêm VIIRS bằng Google Earth Engine (GEE); kiểm tra CSV, nạp Bronze Parquet, rồi ghép vào đủ mọi cặp ô–ngày. Không điền giá trị quan trắc thiếu.
3. **Kiểm tra bàn giao:** Đối chiếu khóa, CRS, OSM theo năm, số dòng fact, cờ thiếu AOD và mã băm file bằng `src.features.verify_tv2_handoff`.

TV1 phụ trách dữ liệu trạm và nhãn PM₂.₅; TV3 phụ trách khí tượng. `mart_grid_daily_features` chỉ được đóng gói sau khi nhận fact khí tượng từ TV3 và chốt hợp đồng với TV1.

## 2. File đầu ra và cách dùng

| File | Hạt dữ liệu và số dòng | Ý nghĩa / cách nối |
|---|---:|---|
| `data/core/dim_grid_1km.parquet` | 3.611 ô | Lưới TV1 cộng 8 biến TV2; hai cột OSM không hậu tố là **mốc 2021** để tương thích lược đồ gốc. Không dùng OSM ở đây cho mọi năm. |
| `data/core/fct_grid_osm_yearly.parquet` | 18.050 ô–năm | Hai cột `osm_primary_road_m`, `osm_road_density_km_km2` đúng năm. Ghép theo `(grid_id, year)` của ngày. |
| `data/core/fct_grid_satellite_daily.parquet` | 6.591.860 ô–ngày | Bảng dùng để ghép mart, khóa `(grid_id, date_id)`; gồm AOD, cờ AOD thiếu, NO₂, VIIRS. Có dòng cho cả ngày thiếu số đo. |
| `data/staging/stg_satellite_daily.parquet` | 6.591.860 ô–ngày | Giữ thêm `month_id`, `source_image_count`, `viirs_cf_cvg_mean` để truy nguyên số đo trước khi rút gọn thành fact. |

Các manifest trong `data/manifests/` ghi danh sách CSV và SHA-256 nguồn (`satellite_exports_v2.json`), báo cáo Bronze (`satellite_bronze_v2.json`), độ phủ fact (`satellite_daily_v1.json`), nguồn WorldCover/DEM/OSM 2021 (`static_features_v1_1.json`), năm snapshot OSM (`osm_yearly_v1.json`), kết quả kiểm tra (`tv2_handoff_validation.json`), mã băm file bàn giao (`tv2_checksums_sha256.txt`) và mã băm ba raster nguồn (`tv2_raw_rasters_sha256.txt`).

**Git không chứa Parquet, CSV, GeoTIFF và OSM ZIP:** `.gitignore` loại các file dữ liệu này. Commit nhánh gồm mã nguồn, tài liệu và manifest JSON/TXT. Chín file Parquet đầu ra cùng checksum dành cho cách tải phẳng đã được tải lên Drive chung; TV1 cần cả Drive và Git để đối chiếu đầy đủ nguồn, quy tắc xử lý và kết quả.

## 3. Quy tắc biến đổi cần TV1 nắm khi review

### Đặc trưng không gian

- `osm_primary_road_m`: tổng chiều dài các đường `motorway`, `trunk`, `primary` sau khi cắt theo ô 1 km, đơn vị mét.
- `osm_road_density_km_km2`: tổng chiều dài mọi cấp đường OSM trong ô (km) chia diện tích ô vuông 1 km².
- Bản Geofabrik đầu tháng 01 của năm `YYYY` được gán cho toàn năm đó. Đây là **xấp xỉ theo năm**, không phải mạng đường chính xác cho từng ngày. Thời điểm snapshot trong manifest là khoảng tối 01/01 UTC (sáng 02/01 ở Hà Nội), nên những ngày đầu năm có thể dùng thông tin xuất hiện sau ngày quan trắc. Tăng số đường OSM có thể phản ánh hoạt động vẽ bản đồ, không chỉ đường mới xây.
- Bốn tỷ lệ WorldCover (`builtup`, `tree`, `cropland`, `water`) lấy từ raster **2021**, dùng chung cho cả 2021–2025. Hai biến SRTM (`elevation`, `slope`) cũng dùng chung. WorldCover 2020 đã có trong thư mục raw nhưng **không dùng** để dựng đặc trưng bản này.
- Mỗi file lưới có 3.610 ô thật và một dòng `grid_unknown`. Dòng này có `NULL` ở các đặc trưng mới; geometry ô thật giữ `EPSG:3405`.

### Viễn thám

- `aod_047_mean` là AOD bước sóng **0,47 µm**, nhân hệ số `0.001`. GEE `v2` giữ pixel có QA AOD tốt nhất (`bits 8–11 = 0`), trời quang (`bits 0–2 = 1`) và AOD trong `[0, 3.5]`. Đây là lựa chọn QA thận trọng của TV2, cần TV1 chấp thuận trước khi coi là chính sách cuối.
- `no2_tropospheric_mol_m2` lấy band tầng đối lưu Sentinel-5P **L3**. GEE đã lọc QA khi tạo L3; CSV không có band `qa_value` để lọc thêm. Giá trị thu hồi âm nhỏ được giữ để phân tích sau.
- `viirs_nightlight_rad` là ảnh tổng hợp **tháng**; một giá trị ô–tháng được lặp lại cho các ngày trong đúng tháng đó. `cf_cvg = 0` dẫn đến `NULL`, không phải bức xạ bằng 0.
- `is_aod_missing_mnar = 1` **chỉ có nghĩa** `aod_047_mean IS NULL`. Tên cột giữ theo draft contract; chưa chứng minh nguyên nhân mây hoặc cơ chế MNAR. `source_image_count` là số ảnh giao vùng, không phải số pixel hợp lệ trong ô.
- Không nội suy hoặc điền 0 cho AOD/NO₂/VIIRS thiếu. Ngày vệ tinh được gom theo múi giờ `Asia/Ho_Chi_Minh`.

Manifest fact hiện ghi **916.056** AOD, **2.184.005** NO₂ và **6.184.753** ô–ngày VIIRS có giá trị trên 6.591.860 ô–ngày. Độ phủ AOD thấp là vấn đề cần EDA sau khi toàn bộ nguồn hoàn chỉnh; [runbook GEE](satellite_gee_runbook.md) ghi kiểm toán từng batch và chẩn đoán QA.

## 4. Cách chạy lại và kiểm tra

Cần có `data/core/dim_grid_1km.parquet` v1.0 và `data/core/dim_date.parquet` của TV1. Nguồn thô WorldCover 2021 và hai TIFF SRTM cần được đặt đúng đường dẫn trong `src/features/extract_static_features.py`; repository hiện **không có lệnh tự tải** ba raster này. OSM ZIP có thể tải bằng script; CSV vệ tinh có thể tải từ Drive theo manifest hoặc sao chép từ một thư mục.

```bash
python -m pip install -r requirements-static-features.txt
python -m pip install -r requirements-satellite-grid.txt

python -m src.ingest.download_osm_snapshots
python -m src.features.extract_static_features
python -m src.features.build_osm_yearly

python -m src.ingest.download_satellite_exports
# Hoặc: python -m src.ingest.download_satellite_exports --source-dir /path/to/csvs
python -m src.ingest.ingest_satellite_csv
python -m src.features.build_satellite_daily
python -m src.features.verify_tv2_handoff
sha256sum -c data/manifests/tv2_checksums_sha256.txt
# Nếu nhận kèm ba raster nguồn:
sha256sum -c data/manifests/tv2_raw_rasters_sha256.txt
```

Quy trình xuất lại CSV từ GEE nằm ở [runbook GEE](satellite_gee_runbook.md); các file CSV `v1` pilot AOD/NO₂ không được dùng.

`verify_tv2_handoff` kiểm tra riêng các đầu ra TV2; nó **không phải** kiểm định hợp đồng toàn dự án. Hiện repo không có module `src.common.contract_verifier`, nên `python run.py contract` chưa chạy được. Không nên ghi nhận trạng thái “toàn bộ lakehouse đã nghiệm thu” dựa trên kết quả kiểm tra TV2.

## 5. Nội dung cần TV1 review

1. Chấp nhận một lưới `dim_grid_1km` có OSM mốc 2021 và bảng `fct_grid_osm_yearly` ghép theo `(grid_id, year)` trong mart.
2. Chấp nhận WorldCover 2021 dùng cố định và OSM snapshot đầu năm dùng cho cả năm, cùng giới hạn diễn giải của chúng.
3. Chốt bộ lọc AOD QA, tên `aod_047_mean`, và tên cờ `is_aod_missing_mnar` trong hợp đồng. Bản hiện tại là dữ liệu tham chiếu QA nghiêm ngặt; chưa nới QA hoặc xuất lại.
4. Chấp nhận fact vệ tinh dạng dày, NO₂ âm nhỏ và quy tắc VIIRS tháng → ngày.
5. Nhận Parquet và checksum qua Drive, manifest xử lý qua Git, rồi kiểm SHA-256; sau khi có `fct_grid_meteo_daily` của TV3 mới cùng đóng gói mart và EDA.

**Kết quả kiểm tra tại máy:** Lưới có 3.611 khóa và `EPSG:3405`; bảng OSM có 18.050 khóa ô–năm, mốc 2021 khớp lưới; phép ghép OSM theo năm với fact vệ tinh giữ 6.591.860 khóa ô–ngày, không nhân dòng. Xem số liệu có thể chạy lại trong `data/manifests/tv2_handoff_validation.json`.

## 6. Nộp dữ liệu vào Drive chung

Đã tải trực tiếp bốn file Parquet vào [thư mục TV2 đang chờ review](https://drive.google.com/drive/folders/1RL477-lT2wN4F3P-m0T7WRZiQw65uKQr) trong `data_v1/submissions/`. Bản lưới v1.0 của TV1 trong `shared_dimensions` giữ nguyên.

```text
tv2_v1_1_2021_2025/
├── dim_grid_1km.parquet
├── fct_grid_osm_yearly.parquet
├── fct_grid_satellite_daily.parquet
├── stg_satellite_daily.parquet
└── tv2_parquet_upload_sha256.txt
```

Drive chứa các đầu ra nhị phân và file checksum tương ứng; manifest JSON/TXT, mã nguồn và tài liệu bàn giao nằm trong nhánh Git để bạn push cho TV1 review. Các CSV GEE gốc nằm ở [thư mục nguồn vệ tinh](https://drive.google.com/drive/folders/114qTj-7KaPOAL2B7-jG62iJltSKWLJlK). Ba raster WorldCover 2021/SRTM và OSM ZIP chưa nằm trong thư mục bàn giao này; muốn chạy lại toàn bộ bước tạo đặc trưng tĩnh cần cung cấp hoặc tải các nguồn đó theo mục 4.

Drive đã hiển thị đủ bốn Parquet và một checksum với tên và kích thước khớp file tại máy. Sau khi tải tất cả file về **cùng một thư mục**, TV1 kiểm tra bằng `sha256sum -c tv2_parquet_upload_sha256.txt`. Để dùng theo đường dẫn trong repository, đặt `dim_grid_1km.parquet`, `fct_grid_osm_yearly.parquet` và `fct_grid_satellite_daily.parquet` vào `data/core/`; đặt `stg_satellite_daily.parquet` vào `data/staging/`. Bản này tiếp tục nằm trong `submissions` cho đến khi trưởng nhóm review và chấp nhận chính sách dữ liệu.
