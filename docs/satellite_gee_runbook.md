# Xuất viễn thám GEE theo lưới TV1 (2021–2025)

**Trạng thái:** Toàn bộ CSV `v2` giai đoạn 2021–2025 đã nạp thành Bronze, staging và fact trên máy. Xem [bản bàn giao TV2](tv2_handoff.md) cho danh sách file, lệnh kiểm tra và phần cần TV1 review. Tài liệu này lưu cách xuất lại và bằng chứng kiểm toán GEE.

## Kết quả kiểm tra nguồn

Kiểm tra trực tiếp trên GEE cho Hà Nội cho thấy AOD, NO₂ và VIIRS đều có ảnh ở tháng 01/2021 và 12/2025. Band dùng là `Optical_Depth_047` + `AOD_QA`, `tropospheric_NO2_column_number_density`, và `avg_rad` + `cf_cvg`. Số ảnh ở một điểm hoặc trong vùng Hà Nội **không** chứng minh rằng mọi ô lưới đều có pixel hợp lệ mỗi ngày.

Tài liệu GEE: [MODIS MAIAC AOD](https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MCD19A2_GRANULES), [Sentinel-5P NO₂](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S5P_OFFL_L3_NO2), [VIIRS VCMCFG](https://developers.google.com/earth-engine/datasets/catalog/NOAA_VIIRS_DNB_MONTHLY_V1_VCMCFG).

## Chuẩn bị lưới

Chạy từ thư mục gốc repo:

```bash
python -m pip install -r requirements-satellite-grid.txt
python src/ingest/build_gee_grid_csv.py
```

File `data/raw/earth_observation/gee_assets/tv1_grid_1km.csv` gồm đúng 3.610 ô thật của `dim_grid_1km.parquet`, loại `grid_unknown`. Nó có `grid_id` và WKT EPSG:4326 để GEE nhận dạng polygon. Script GEE dựng lại hình vuông 1 km theo tọa độ trong `grid_id` ở EPSG:3405, tránh thay đổi cạnh ô do nhập CSV.

Trong GEE Code Editor, mở **Assets → NEW → Table upload → CSV**, chọn file trên. Kiểm tra trường `geometry` được nhận là WKT và đặt Asset ID, ví dụ `projects/MY_PROJECT/assets/tv1_grid_1km`. Sau khi upload xong, dán Asset ID vào `GRID_ASSET` trong [`fetch_satellite_gee.js`](../src/ingest/fetch_satellite_gee.js). [Tài liệu upload bảng của GEE](https://developers.google.com/earth-engine/guides/table_upload).

## Chạy thử, rồi xuất từng quý

1. Dán toàn bộ `src/ingest/fetch_satellite_gee.js` vào script mới trong Code Editor. Mặc định `YEAR=2021`, `QUARTER=1`, `PILOT_DAYS=7`. Bấm **Run**, kiểm tra Console báo 3.610 ô và có 3 tác vụ AOD, NO₂, VIIRS trong **Tasks**. Bấm **Run** cho các tác vụ này.
2. Tải CSV mẫu từ thư mục Drive `hanoi_pm25_gee`. AOD và NO₂ mỗi file phải có **25.270 dòng dữ liệu** (3.610 × 7); VIIRS có **3.610 dòng**. Mỗi `grid_id` phải thuộc lưới TV1, và `date_id` phải từ `20210101` đến `20210107`. Ô thiếu đo phải để trống, không điền 0. Kiểm tra thêm số giá trị **không trống** ở AOD và NO₂ trước khi chạy toàn quý.
3. Sau khi xem mẫu, đặt `PILOT_DAYS=0`. Chạy với `YEAR=2021..2025`, `QUARTER=1..4` và `QUARTERS_PER_RUN=1..4`. Một lượt tạo ba tác vụ AOD, NO₂, VIIRS; `QUARTER` là quý đầu tiên và script tự xử lý khi batch qua năm mới. Lưu CSV gốc ở `data/raw/earth_observation/` trước khi làm staging; tên file chứa quý bắt đầu và kết thúc để không ghi đè. Khi gộp quý, CSV chứa nhiều quý và phải chia lại theo `date_id`/`month_id` ở bước nạp local.

Ví dụ sau Q2/2021: đặt `YEAR=2021`, `QUARTER=3`, `QUARTERS_PER_RUN=2`, `PILOT_DAYS=0` để xuất Q3–Q4/2021. Mỗi file ngày dự kiến có 664.240 dòng (3.610 ô × 184 ngày), VIIRS có 21.660 dòng (3.610 ô × 6 tháng). Ba task sẽ có hậu tố `2021_q3_to_2021_q4_v2`. Với cả năm 2022, đặt `YEAR=2022`, `QUARTER=1`, `QUARTERS_PER_RUN=4`; hai file ngày có 1.317.650 dòng mỗi file và VIIRS có 43.320 dòng. Batch bốn quý 2022–2025 đã chạy thành công; nếu cần xuất lại và task báo hết bộ nhớ hoặc thời gian, giảm số quý rồi kiểm tra số dòng. Việc gộp không làm tăng số task chạy đồng thời và task có thể phải chờ hàng đợi của GEE.

Các task pilot và toàn bộ giai đoạn 2021–2025 đã xuất CSV thành công. Kết quả kiểm toán từng batch nằm ở các mục dưới.

## Quy tắc đang áp dụng trong script

- Ngày AOD/NO₂ là ngày địa phương `Asia/Ho_Chi_Minh` (`UTC+7`), dùng cửa sổ UTC tương ứng. Ảnh trong cùng ngày được lấy trung bình sau khi áp dụng mask; thống kê trên polygon ô theo lưới pixel gốc của nguồn với `ee.Reducer.mean()`.
- AOD dùng `Optical_Depth_047 × 0.001`, giữ QA tốt nhất (bits 8–11 bằng 0) **và** pixel trời quang (bits 0–2 bằng 1), đồng thời loại giá trị ngoài `[0, 3.5]`. Band, scale và khoảng giá trị nằm trong guide; tổ hợp hai điều kiện QA là **lựa chọn triển khai thận trọng, chưa được hợp đồng dữ liệu chốt**. Catalog GEE giải thích ý nghĩa các mã QA nhưng không bắt buộc tổ hợp này. Giá trị trống được giữ trống. `source_image_count` là số ảnh giao với **toàn vùng**, không phải số pixel hợp lệ trong từng ô.
- Band NO₂ trên GEE đã loại pixel có QA dưới 75% khi chuyển L2 sang L3; collection này không có band `qa_value` để lọc lần nữa. Giữ cả giá trị âm nhỏ do nhiễu thu hồi; tài liệu GEE không khuyến nghị lọc chúng trừ ngoại lai. Draft contract hiện cho phép cận dưới âm; TV1 cần review trước nghiệm thu fact.
- VIIRS xuất một dòng mỗi ô–tháng. Chỉ lấy `avg_rad` tại pixel có `cf_cvg > 0`; giữ `viirs_cf_cvg_mean` để kiểm tra chất lượng. Khi làm fact ngày, phát tán cùng giá trị cho các ngày thuộc chính tháng đó; không xem tháng không có quan trắc là 0.
- CSV là tầng raw gần dạng dense. Cột `is_aod_missing_mnar` ở fact có thể đặt 1 khi AOD trống theo contract, nhưng chỉ riêng giá trị trống **không chứng minh nguyên nhân là mây** (cũng có thể không có ảnh hoặc bị loại QA). Cần giữ metadata quan trắc để mô tả đúng ý nghĩa cờ.

CSV `v2` giai đoạn 2021–2025 đã được kiểm toán cấu trúc và nạp thành fact dạng dày. Bản triển khai giữ `NULL`, NO₂ âm nhỏ và cờ thiếu AOD như mô tả trên; các chính sách này vẫn cần TV1 review trong hợp đồng dữ liệu.

### Kết quả thử 7 ngày đầu (2021-01-01 đến 2021-01-07)

Ba file pilot `v1` xuất đủ khóa và số dòng, nhưng **AOD và NO₂ đều trống 100%**. Nguyên nhân là `reduceRegions()` trên ảnh một band dùng tên output mặc định của reducer (`mean`), còn script `v1` đọc property theo tên band. Bản `v2` đặt tên output bằng `ee.Reducer.mean().setOutputs([band])`; cách này cũng được dùng trong [ví dụ chính thức của GEE](https://developers.google.com/earth-engine/Earth_Engine_REST_API_compute_table). File VIIRS `v1` có đủ 3.610 giá trị bức xạ tháng 01/2021 và `cf_cvg > 0` ở mọi ô, nên không cần xuất lại VIIRS chỉ để sửa lỗi này. Không dùng AOD/NO₂ `v1` cho staging/fact; chạy lại hai tác vụ `_pilot_v2` và xác nhận số giá trị không trống trước khi xuất cả quý.

Hai CSV `_pilot_v2` đã được kiểm tra: mỗi file có 25.270 khóa ô–ngày không trùng, đúng 3.610 `grid_id` của TV1 và đủ ngày 01–07/01/2021. AOD có 9.791 giá trị (38,7%), trong khoảng 0,297–1,130; NO₂ có 8.284 giá trị (32,8%), trong khoảng 2,74×10⁻⁵–3,37×10⁻⁴ mol/m². Cả hai nguồn có giá trị trong ba ngày đầu nhưng trống hoàn toàn ở bốn ngày 04–07/01. `source_image_count` đếm ảnh giao với toàn vùng, không chứng minh pixel hợp lệ ở từng ô. Giữ các ô trống là `NULL`; cần kiểm tra thêm vùng phủ và QA nguồn nếu muốn quy nguyên nhân cụ thể cho bốn ngày này.

### Kết quả xuất cả quý 1/2021

Ba file `_2021_q1_v2.csv` trên Drive đã được kiểm tra ngày 27/10/2026. AOD và NO₂ mỗi file có 324.900 dòng (3.610 ô × 90 ngày); VIIRS có 10.830 dòng (3.610 ô × 3 tháng). Các khóa đều duy nhất, đúng tập `grid_id` của TV1, không thiếu ngày/tháng. Dữ liệu 01–07/01 trong hai file ngày khớp chính xác từng dòng với pilot v2.

| Nguồn | Giá trị có số đo | Tỷ lệ | Khoảng giá trị | Ngày/tháng hoàn toàn trống |
|---|---:|---:|---:|---:|
| AOD | 46.353 / 324.900 | 14,27% | 0,141–3,383 | 65 / 90 ngày |
| NO₂ | 62.501 / 324.900 | 19,24% | 1,79×10⁻⁵–9,05×10⁻⁴ mol/m² | 53 / 90 ngày |
| VIIRS | 10.820 / 10.830 | 99,91% | 0,228–93,077 | 0 / 3 tháng |

Ở VIIRS, 10 ô thiếu thuộc tháng 03/2021 và đều có `cf_cvg = 0`; không đổi thành 0 bức xạ. Có 52 ngày cả AOD lẫn NO₂ đều trống, trong đó đợt dài nhất là 13–22/03/2021 (10 ngày). Mọi ngày trống vẫn có `source_image_count > 0`, nhưng đây là số ảnh giao toàn vùng chứ không phải bằng chứng có pixel hợp lệ ở Hà Nội. Cần kiểm tra riêng mask/QA trên GEE trước khi gán nguyên nhân cho các ngày trống hoặc dùng cờ “do mây”.

Để kiểm tra nhanh, dán [`src/ingest/diagnose_satellite_gee.js`](../src/ingest/diagnose_satellite_gee.js) vào **script mới** trong GEE Code Editor và bấm Run. Script không tạo export task; Console so sánh các ngày đại diện năm 2021 và hai ngày AOD thưa năm 2024 trên bounding box TV1. `aod_raw_pixels > 0` nhưng `aod_accepted_pixels = 0` cho thấy bộ lọc QA/dải đo đã loại hết pixel trong vùng; nếu `aod_raw_pixels = 0` thì collection có ảnh nhưng không có số đo AOD gốc trong vùng. `no2_l3_tropospheric_pixels = 0` cho thấy L3 của GEE không có pixel NO₂ dùng được trong vùng; riêng con số này không phân biệt được swath không phủ với QA đã loại pixel.

Kết quả Console: ngày 01/01 có 7.382 pixel AOD gốc, 7.339 pixel qua QA, và 7.426 pixel NO₂ tầng đối lưu trên bounding box. Ngày 15/03 có 36 ảnh AOD giao vùng nhưng **0 pixel AOD gốc, 0 pixel qua QA**; có 14 ảnh NO₂, 7.006 pixel `cloud_fraction` nhưng **0 pixel NO₂ tầng đối lưu**. Vì vậy dòng trống của hai CSV ngày 15/03 phản ánh mask/khuyết số đo trong nguồn GEE trên toàn bounding box, không phải lỗi nối `grid_id` hay tên cột xuất CSV. Riêng dữ liệu này chưa đủ để gán nguyên nhân cụ thể là mây; cờ `is_aod_missing_mnar` trong fact cần được mô tả như chỉ báo thiếu AOD, không phải nhãn nguyên nhân đã xác minh.

### Kết quả xuất cả quý 2/2021

Ba file `_2021_q2_v2.csv` trên Drive có đủ 3.610 ô TV1 và 91 ngày (01/04–30/06) hoặc ba tháng (04–06), không có khóa trùng. AOD và NO₂ mỗi file có 328.510 dòng; VIIRS có 10.830 dòng.

| Nguồn | Giá trị có số đo | Tỷ lệ | Khoảng giá trị | Ngày hoàn toàn trống |
|---|---:|---:|---:|---:|
| AOD | 23.708 / 328.510 | 7,22% | 0–2,800 | 57 / 91 |
| NO₂ | 101.542 / 328.510 | 30,91% | −9,49×10⁻⁶–5,49×10⁻⁴ mol/m² | 30 / 91 |
| VIIRS | 10.674 / 10.830 | 98,56% | 0,280–56,283 | 0 / 3 tháng |

Có 29 ngày cả AOD và NO₂ đều trống. VIIRS có 156 ô thiếu (69 trong tháng 04, 87 trong tháng 06), tất cả có `cf_cvg = 0`; giữ `NULL`. NO₂ có 109 giá trị âm nhỏ, cần giữ ở tầng raw vì [GEE nêu giá trị cột âm có thể do nhiễu thu hồi và không khuyến nghị lọc trừ ngoại lai](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S5P_OFFL_L3_NO2). Ràng buộc NO₂ không âm trong draft data contract cần được sửa trước khi nghiệm thu fact.

Tỷ lệ AOD quý 2 thấp hơn quý 1; riêng tháng 04 chỉ có 1.481 / 108.300 ô–ngày có số đo (1,37%). Script chẩn đoán đã bổ sung ngày 10/05 (AOD có giá trị ở 2.593 ô) và 20/05 (AOD trống toàn bộ nhưng NO₂ có giá trị ở 3.154 ô). Kết quả `aod_raw_pixels` và `aod_accepted_pixels` của hai ngày này được ghi ở đoạn kế tiếp để phân biệt thiếu thu hồi gốc với việc QA loại pixel.

Kết quả bổ sung: ngày 10/05 có 5.991 pixel AOD gốc trong bounding box TV1, 3.914 pixel qua QA; ngày 20/05 có 310 pixel gốc, 152 pixel qua QA. Tuy nhiên CSV ngày 20/05 trống ở toàn bộ 3.610 ô. Bounding box gồm cả diện tích ngoài tập ô TV1, nên 152 pixel không tự chứng minh lỗi xuất. [`src/ingest/diagnose_aod_grid_gee.js`](../src/ingest/diagnose_aod_grid_gee.js) đếm ô có AOD theo đúng phép giảm vùng của CSV, đồng thời so với lưới EPSG:3405 ở 1 km; script không tạo export task.

Kết quả kiểm tra polygon: ngày 10/05 có **2.593 ô** AOD theo projection gốc, khớp đúng CSV; phép EPSG:3405 1 km có 2.202 ô. Ngày 20/05 có **0 ô** ở cả hai phép. Như vậy 152 pixel qua QA trong bounding box ngày 20/05 không tạo giá trị cho ô TV1 theo cả hai cách lấy mẫu; CSV trống ngày đó là nhất quán với phép giảm vùng, không phải lỗi xuất. Chênh lệch 2.593 so với 2.202 ngày 10/05 cũng cho thấy lựa chọn projection/phương pháp lấy mẫu làm thay đổi độ phủ ô; pipeline hiện dùng projection gốc và cần giữ cố định cách này khi chạy các quý tiếp theo.

### Kết quả batch quý 3–4/2021

Ba file `_2021_q3_to_2021_q4_v2.csv` trên Drive đã được kiểm tra ngày 27/10/2026. AOD và NO₂ mỗi file có 664.240 dòng (3.610 ô × 184 ngày, 01/07–31/12); VIIRS có 21.660 dòng (3.610 ô × 6 tháng). Các khóa ô–ngày/ô–tháng đều duy nhất, đủ mọi ngày/tháng và đúng tập `grid_id` của lưới TV1. Mỗi tháng VIIRS có đúng một ảnh nguồn; mọi ngày AOD/NO₂ đều có `source_image_count > 0`, nhưng đây là số ảnh giao vùng, không bảo đảm từng ô có số đo.

| Nguồn | Q3 có số đo | Q4 có số đo | Tổng batch có số đo | Ngày/tháng hoàn toàn trống |
|---|---:|---:|---:|---:|
| AOD | 33.859 / 332.120 (10,19%) | 78.801 / 332.120 (23,73%) | 112.660 / 664.240 (16,96%) | 86 / 184 |
| NO₂ | 167.407 / 332.120 (50,41%) | 132.836 / 332.120 (40,00%) | 300.243 / 664.240 (45,20%) | 52 / 184 |
| VIIRS | 7.579 / 10.830 (69,98%) | 10.830 / 10.830 (100%) | 18.409 / 21.660 (84,99%) | 0 / 6 tháng |

Có 52 ngày cả AOD lẫn NO₂ đều trống. NO₂ có 136 giá trị âm nhỏ, từ −6,99×10⁻⁶ mol/m²; giữ nguyên ở tầng raw theo quy tắc đã nêu. **VIIRS tháng 08/2021 chỉ có 373/3.610 ô có bức xạ** (10,33%); 3.237 ô còn lại đều có `viirs_cf_cvg_mean = 0` và bức xạ trống. Tháng 07 có 12 ô trống, tháng 09 có 2 ô trống, còn tháng 10–12 đều đủ. [Catalog của GEE](https://developers.google.com/earth-engine/datasets/catalog/NOAA_VIIRS_DNB_MONTHLY_V1_VCMCFG) mô tả `cf_cvg` là số lượt quan sát không mây và cảnh báo vùng nhiệt đới có thể thiếu phủ theo tháng. Dữ liệu này xác nhận không có lượt quan sát không mây theo phép giảm vùng ở các ô trống; không đủ để xác định riêng nguyên nhân khí tượng. Giữ `NULL`, không nội suy hoặc đổi thành 0 khi nạp raw.

### Kết quả batch cả năm 2022

Ba file `_2022_q1_to_2022_q4_v2.csv` trên Drive đã được kiểm tra ngày 27/10/2026. AOD và NO₂ mỗi file có 1.317.650 dòng (3.610 ô × 365 ngày); VIIRS có 43.320 dòng (3.610 ô × 12 tháng). Các khóa đều duy nhất, đúng tập ô TV1, đủ mọi ngày/tháng, không có giá trị số bị lỗi định dạng. `source_image_count > 0` ở mọi ngày và bằng 1 ở từng tháng VIIRS; số ảnh giao vùng không bảo đảm từng ô có số đo.

| Nguồn | Có số đo cả năm | Q1 | Q2 | Q3 | Q4 | Ngày/tháng trống hoàn toàn |
|---|---:|---:|---:|---:|---:|---:|
| AOD | 164.449 / 1.317.650 (12,48%) | 6,87% | 11,36% | 4,66% | 26,91% | 214 / 365 ngày |
| NO₂ | 422.087 / 1.317.650 (32,03%) | 10,37% | 29,96% | 43,03% | 44,28% | 149 / 365 ngày |
| VIIRS | 39.376 / 43.320 (90,90%) | 98,92% | 98,00% | 66,67% | 100% | 1 / 12 tháng |

Có 141 ngày cả AOD lẫn NO₂ đều trống. NO₂ có 200 giá trị âm nhỏ, thấp nhất −2,07×10⁻⁵ mol/m²; fact hiện giữ các giá trị này và draft contract đã bỏ cận dưới không âm, chờ TV1 review. VIIRS thiếu 3.944 ô–tháng, tất cả có `viirs_cf_cvg_mean = 0`: 117 ô tháng 02, 217 ô tháng 06 và **toàn bộ 3.610 ô tháng 07/2022**. Mỗi tháng này có một ảnh VIIRS trong collection; CSV không cho biết riêng nguyên nhân tại sao `cf_cvg` bằng 0. Giữ bức xạ tháng 07 là `NULL`, không đổi thành 0 hoặc tự điền từ tháng khác.

### Kết quả batch cả năm 2023

Ba file `_2023_q1_to_2023_q4_v2.csv` trên Drive đã được kiểm tra ngày 27/10/2026. AOD và NO₂ mỗi file có 1.317.650 dòng (3.610 ô × 365 ngày); VIIRS có 43.320 dòng (3.610 ô × 12 tháng). Mọi ngày/tháng và ô TV1 đều có đúng một khóa; không có giá trị số lỗi định dạng hoặc kỳ có `source_image_count = 0`.

| Nguồn | Có số đo cả năm | Q1 | Q2 | Q3 | Q4 | Ngày/tháng trống hoàn toàn |
|---|---:|---:|---:|---:|---:|---:|
| AOD | 214.391 / 1.317.650 (16,27%) | 19,62% | 13,54% | 10,10% | 21,86% | 179 / 365 ngày |
| NO₂ | 488.216 / 1.317.650 (37,05%) | 28,04% | 37,53% | 40,45% | 42,00% | 132 / 365 ngày |
| VIIRS | 41.810 / 43.320 (96,51%) | 100% | 88,08% | 97,98% | 100% | 0 / 12 tháng |

Có 122 ngày cả AOD lẫn NO₂ đều trống. NO₂ có 100 giá trị âm nhỏ, thấp nhất −1,45×10⁻⁵ mol/m²; tiếp tục giữ ở tầng raw. VIIRS không có tháng trống toàn bộ: tháng 06 thiếu 1.291 ô và tháng 08 thiếu 219 ô; toàn bộ 1.510 ô–tháng thiếu đều có `viirs_cf_cvg_mean = 0`. Các tháng khác đủ 3.610 ô có bức xạ. Giữ các giá trị thiếu là `NULL`.

Sau khi tải CSV về máy, có thể lặp lại kiểm tra từng file bằng [`src/ingest/audit_gee_csv.py`](../src/ingest/audit_gee_csv.py), ví dụ `python src/ingest/audit_gee_csv.py 2023 aod <file_aod.csv> data/raw/earth_observation/gee_assets/tv1_grid_1km.csv`. Script báo số dòng, khóa trùng, ngày/tháng thiếu và độ phủ từng quý/tháng.

### Kết quả batch cả năm 2024

Ba file `_2024_q1_to_2024_q4_v2.csv` trên Drive đã được kiểm tra ngày 27/10/2026. Vì 2024 là năm nhuận, AOD và NO₂ mỗi file có 1.321.260 dòng (3.610 ô × 366 ngày); VIIRS có 43.320 dòng (3.610 ô × 12 tháng). Mọi ô/ngày/tháng đều có đúng một khóa, không có lỗi định dạng số hoặc kỳ có `source_image_count = 0`.

| Nguồn | Có số đo cả năm | Q1 | Q2 | Q3 | Q4 | Ngày/tháng trống hoàn toàn |
|---|---:|---:|---:|---:|---:|---:|
| AOD | 163.357 / 1.321.260 (12,36%) | 4,89% | 9,50% | 4,26% | 30,69% | 218 / 366 ngày |
| NO₂ | 400.332 / 1.321.260 (30,30%) | 13,94% | 29,40% | 33,28% | 44,39% | 147 / 366 ngày |
| VIIRS | 39.831 / 43.320 (91,95%) | 99,94% | 81,75% | 86,09% | 100% | 0 / 12 tháng |

Có 143 ngày cả AOD lẫn NO₂ đều trống. NO₂ có 119 giá trị âm nhỏ, thấp nhất −4,54×10⁻⁶ mol/m²; giữ ở tầng raw. VIIRS thiếu 3.489 ô–tháng, tất cả có `viirs_cf_cvg_mean = 0`: tháng 01 thiếu 6, tháng 06 thiếu 1.977, tháng 09 thiếu 1.506. Không có tháng VIIRS trống toàn bộ.

**AOD tháng 05–07/2024 rất thưa:** lần lượt chỉ 235 / 111.910 (0,21%), 570 / 108.300 (0,53%), 1.141 / 111.910 (1,02%) ô–ngày có số đo. CSV đúng cấu trúc nhưng riêng các tỷ lệ này chưa xác định được bao nhiêu do pixel nguồn đã trống và bao nhiêu do QA loại trên toàn ba tháng. [`diagnose_satellite_gee.js`](../src/ingest/diagnose_satellite_gee.js) so sánh AOD gốc với AOD qua QA trên bounding box TV1 ở hai ngày mẫu.

Console GEE cho ngày 10/05/2024 ghi 70 ảnh AOD giao bounding box TV1, nhưng chỉ **23 pixel AOD gốc** và **0 pixel qua QA**; NO₂ tầng đối lưu có 1.804 pixel. Ngày 15/07/2024 ghi 69 ảnh AOD, **42 pixel gốc** và **1 pixel qua QA**; NO₂ có 1.336 pixel. Hai ngày mẫu cho thấy AOD gốc đã rất thưa trong vùng và QA loại phần còn lại gần như hoàn toàn. Chưa thể suy rộng tỷ lệ loại QA này ra cả ba tháng. [`diagnose_aod_grid_gee.js`](../src/ingest/diagnose_aod_grid_gee.js) dùng đúng polygon TV1 và projection tương ứng batch cả năm: **cả 10/05 và 15/07 đều có 0 ô AOD**, ở cả projection gốc lẫn EPSG:3405 1 km. Vì vậy pixel qua QA trong bounding box ngày 15/07 không tạo giá trị cho ô TV1 theo hai phép giảm vùng; CSV trống hai ngày này là nhất quán với GEE, không phải lỗi xuất.

### So sánh tác động của từng điều kiện AOD QA

Tổ hợp QA hiện tại (`best quality` **và** `clear`) là lựa chọn triển khai thận trọng, chưa được guide chỉ định hoặc kiểm chứng là tối ưu cho Hà Nội. Trước khi đổi chính sách và xuất lại, dán [`diagnose_aod_qa_gee.js`](../src/ingest/diagnose_aod_qa_gee.js) vào **script mới** trong GEE Code Editor, đặt cùng `GRID_ASSET` với script xuất và bấm Run. Script không tạo export task; nó so sánh năm ngày đại diện 10/05, 29/05, 01/06, 15/07 và 16/07/2024 theo đúng polygon TV1 và projection của CSV cả năm.

Console in số ô có AOD ở năm mức: `raw_native` (pixel nguồn không bị mask), `range_only` (thêm `[0, 3.5]`), `best_only` (thêm QA AOD tốt nhất), `clear_only` (thêm trời quang), `best_and_clear` (bộ lọc đang xuất). `expected_best_and_clear_from_csv` lần lượt là 0, 119, 307, 0 và 263 ô; số đếm GEE cần khớp trước khi so sánh. Chênh lệch độ phủ chỉ là bước đầu, chưa chứng minh số đo bổ sung đáng tin cậy; quyết định nới QA cần kiểm tra phân bố giá trị, chất lượng và tác động khi đối chiếu PM₂.₅ trạm. Giữ nguyên CSV `v2` trong lúc đánh giá.

Kết quả Console của cả năm ngày đã khớp `best_and_clear` với CSV:

| Ngày 2024 | Raw | Trong `[0, 3.5]` | Chỉ `best` | Chỉ `clear` | `best` và `clear` |
|---|---:|---:|---:|---:|---:|
| 10/05 | 16 | 16 | 0 | 16 | 0 |
| 29/05 | 848 | 848 | 119 | 845 | 119 |
| 01/06 | 745 | 745 | 307 | 745 | 307 |
| 15/07 | 31 | 31 | 0 | 31 | 0 |
| 16/07 | 1.314 | 1.314 | 263 | 1.311 | 263 |

Đây là **số ô có ít nhất một giá trị qua phép giảm vùng**, không phải số pixel. Ở mức số ô trên năm ngày mẫu, điều kiện `best quality` làm giảm độ phủ lớn nhất; thêm `clear` sau `best` không giảm thêm ô nào. Điều đó chưa bảo đảm giá trị trung bình trong các ô hoàn toàn giống nhau. Nới thành `clear_only` có thể nhận cả các mã QA kém tin cậy. Script chẩn đoán đã bổ sung số ô theo QA code 3, 4, 11 và các mã khác trong nhóm `clear_only`; cần đọc các mã này trước khi đề xuất chính sách QA mới.

Kết quả phân loại QA trong năm ngày mẫu: `clear_qa11 = 0` và `clear_other_qa = 0` ở tất cả các ngày. Số ô có QA 3 lần lượt là **1, 173, 235, 0, 312**; QA 4 là **16, 814, 560, 31, 1.182**. Một ô có thể nhận nhiều mã qua các pixel/ảnh, nên **không cộng các số ô theo mã** để suy ra tổng `clear_only`. [Catalog GEE](https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MCD19A2_GRANULES) mô tả QA 3 là có một pixel mây lân cận, QA 4 là có hơn một pixel mây lân cận. Phần tăng độ phủ trong mẫu phần lớn liên quan QA 4; chuyển toàn bộ sang `clear_only` sẽ đánh đổi chất lượng gần mây mà chưa có kiểm chứng. Giữ QA 0 làm bản tham chiếu chất lượng cao; nếu cần tăng phủ, thử riêng phương án QA 0+3 trên một tập nhỏ và so sánh với số đo trạm trước khi quyết định xuất lại.

### Kết quả batch cả năm 2025

Ba file `_2025_q1_to_2025_q4_v2.csv` trên Drive đã được kiểm tra ngày 27/10/2026. AOD và NO₂ mỗi file có 1.317.650 dòng (3.610 ô × 365 ngày); VIIRS có 43.320 dòng (3.610 ô × 12 tháng). Mọi ô/ngày/tháng đều có đúng một khóa, không có lỗi định dạng số.

| Nguồn | Có số đo cả năm | Q1 | Q2 | Q3 | Q4 | Ngày/tháng trống hoàn toàn |
|---|---:|---:|---:|---:|---:|---:|
| AOD | 191.138 / 1.317.650 (14,51%) | 22,26% | 7,50% | 6,63% | 21,72% | 203 / 365 ngày |
| NO₂ | 409.084 / 1.317.650 (31,05%) | 24,24% | 29,44% | 35,34% | 35,00% | 148 / 365 ngày |
| VIIRS | 42.319 / 43.320 (97,69%) | 95,16% | 99,10% | 96,50% | 100% | 0 / 12 tháng |

Có 139 ngày cả AOD lẫn NO₂ đều trống. NO₂ có 42 giá trị âm nhỏ, thấp nhất −3,98×10⁻⁶ mol/m²; giữ ở tầng raw. Riêng **24/10, 01/11 và 03/11/2025**, mỗi ngày có đủ 3.610 dòng NO₂ nhưng `source_image_count = 0` và toàn bộ giá trị trống: đây là ngày không có ảnh giao vùng trong collection, khác với ngày có ảnh nhưng pixel bị mask. VIIRS thiếu 1.001 ô–tháng, tất cả có `viirs_cf_cvg_mean = 0`: tháng 02 thiếu 524, tháng 05 thiếu 86, tháng 06 thiếu 12, tháng 07 thiếu 379. Không có tháng VIIRS trống toàn bộ.

### Tổng kiểm toán CSV 2021–2025

Tất cả batch `_v2` đã kiểm tra có đủ khóa lưới TV1 và mọi kỳ theo lịch, không trùng khóa. AOD và NO₂ mỗi nguồn có **6.591.860 dòng ô–ngày** (3.610 × 1.826); VIIRS có **216.600 dòng ô–tháng** (3.610 × 60). Số giá trị không trống: AOD **916.056** (13,90%), NO₂ **2.184.005** (33,13%), VIIRS **203.239** (93,83%). Độ phủ thấp là đặc tính quan trắc/QA cần giữ khi dựng staging; không suy diễn các giá trị `NULL` thành 0 hoặc tự điền. Các tỷ lệ là của CSV nguồn, trước khi phát tán VIIRS tháng sang ngày.
