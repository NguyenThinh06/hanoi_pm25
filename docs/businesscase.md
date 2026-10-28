# Business case: Ước tính PM2.5 lịch sử trên lưới 1 km tại Hà Nội

**Chủ đề:** Xây dựng dữ liệu và mô hình ước tính nồng độ PM2.5 trung bình ngày trên lưới 1 km tại Hà Nội, giai đoạn 2021–2025.  
**Trạng thái:** Business case phục vụ nghiên cứu và phát triển phiên bản đầu. Các giả thuyết và tiêu chí đánh giá sẽ được kiểm tra bằng dữ liệu hiện có trước khi đưa ra kết luận về khả năng sử dụng của bản đồ.  
**Kế hoạch phân tích chi tiết:** [analysisplan.md](./analysisplan.md)  
**Hợp đồng dữ liệu:** [data_contract.md](./data_contract.md)

---

## 1. Bài toán nghiệp vụ

Người nghiên cứu môi trường muốn tìm hiểu nồng độ PM2.5 thay đổi như thế nào giữa các khu vực và thời điểm tại Hà Nội. Tuy nhiên, số đo mặt đất chỉ có tại các trạm quan trắc, trong khi trạm phân bố không đều và có thể thiếu dữ liệu theo giờ hoặc theo ngày.

Trong tập dữ liệu hiện tại của dự án (ảnh chụp kiểm tra ngày 2026-10-28):

- Có **7.878 trạm–ngày** có giá trị `pm25_raw_mean` hợp lệ (khác NULL).
- Các nhãn này đến từ **39 trạm**, nằm trên **36 ô lưới** khác nhau (trên tổng số 3.610 ô phân tích của Hà Nội).
- Mỗi năm từ 2021 đến 2023 chỉ có **1 trạm** có nhãn; số trạm có nhãn tăng lên trong các năm sau (35 trạm năm 2024, 18 trạm năm 2025).
- AOD và một số biến vệ tinh khác thiếu nhiều (AOD thiếu 6.707 / 7.878 dòng nhãn; NO₂ thiếu 5.608 / 7.878 dòng nhãn); dữ liệu lớp biên hành tinh (BLH) hiện chưa có trong bảng đặc trưng (thiếu 100%).

> [!NOTE]
> Những con số này mô tả dữ liệu dự án đang có, không khẳng định Hà Nội chỉ có bấy nhiêu trạm trong thực tế. Tỷ lệ 36 / 3.610 ô là tỷ lệ số ô có ít nhất một nhãn, không phải tỷ lệ diện tích chính xác của Hà Nội.

Nếu chỉ xem số đo tại trạm, người dùng khó khảo sát sự thay đổi PM2.5 ở những ô không có quan trắc. Dự án vì vậy xây dựng mô hình kết hợp dữ liệu trạm, khí tượng, vệ tinh và thời gian để ước tính PM2.5 lịch sử theo ô–ngày, đồng thời đánh giá mức độ tin cậy của các ước tính.

---

## 2. Người dùng và nhu cầu

**Người dùng chính:** Nhóm nghiên cứu dữ liệu môi trường và dịch tễ học môi trường.

**Nhu cầu cốt lõi:**

1. **Xem bản đồ PM2.5 ước tính** cho một ngày lịch sử bất kỳ trong giai đoạn 2021–2025.
2. **So sánh sơ bộ** sự khác nhau giữa các khu vực, mùa hoặc giai đoạn (ví dụ: mùa đông vs mùa hè, trước vs sau 2024).
3. **Đối chiếu số đo trạm** cùng thời gian với giá trị ước tính từ mô hình để nhận diện độ lệch.
4. **Nhận biết giới hạn dữ liệu:** Khu vực nào có ít dữ liệu trạm (như vùng ngoại thành), ngày nào thiếu vệ tinh do mây mù, và mô hình sai khác bao nhiêu khi được kiểm thử độc lập.

**Ví dụ sử dụng:** Người nghiên cứu chọn một ngày mùa đông năm 2024, xem bản đồ dự đoán và các điểm trạm có quan sát. Từ đó, họ chọn một khu vực hoặc khoảng thời gian để nghiên cứu sâu hơn. Bản đồ giúp đặt câu hỏi nghiên cứu; bản thân bản đồ chưa đủ để kết luận nguyên nhân ô nhiễm hoặc tác động của một chính sách.

---

## 3. Mục tiêu dự án

| Mục tiêu | Kết quả cần đạt |
|---|---|
| **Chuẩn hóa dữ liệu** | Tạo bộ dữ liệu ô–ngày có cùng khóa `(grid_id, date_id)` để ghép khí tượng ERA5-Land, vệ tinh Sentinel-5P / MAIAC / VIIRS và thời gian. |
| **Tạo nhãn** | Sử dụng PM2.5 trung bình (`pm25_raw_mean`) từ các giờ hợp lệ tại trạm–ngày sau khi chạy QC chuỗi giờ. |
| **Ước tính lịch sử** | Tạo dự đoán nồng độ trên toàn bộ ma trận không-thời gian ($3.610\text{ ô} \times 1.826\text{ ngày} = 6.591.860\text{ dòng}$) giai đoạn 2021–2025. |
| **Đánh giá mô hình** | So sánh với baseline và kiểm tra sai số theo không gian, thời gian và chất lượng nhãn (đánh giá riêng theo nhóm giờ). |
| **Trình bày kết quả** | Hiển thị dự đoán cùng số đo trạm thực tế và giải thích minh bạch các giới hạn dữ liệu. |

*Hướng phát triển sau:* Nếu mô hình lịch sử được đánh giá phù hợp, nhóm có thể khảo sát bài toán ước tính cho ngày hiện tại (near-real-time). Phần đó cần nguồn cập nhật tự động và quy trình kiểm thử riêng biệt.

---

## 4. Câu hỏi nghiên cứu

| Mã | Câu hỏi nghiên cứu | Dữ liệu phục vụ | Đầu ra dự kiến |
|:---:|---|---|---|
| **Q1** | Các trạm và nhãn PM2.5 phủ được những khu vực và thời gian nào? | Fact trạm–ngày, danh mục trạm, lưới 1km | Bản đồ trạm, số trạm/ô/ngày có nhãn theo năm và mùa. |
| **Q2** | Nhãn PM2.5 ngày thay đổi thế nào khi ngày đó chỉ có ít giờ quan sát hợp lệ? | Dữ liệu giờ, fact trạm–ngày | Sai khác giữa trung bình tính từ một phần giờ và trung bình tính từ nhiều giờ hơn. |
| **Q3** | Các trạm cùng ô–ngày có cho giá trị khác nhau đáng kể không? | Fact trạm–ngày, dữ liệu giờ | Phân bố chênh lệch giữa các trạm và mức trùng nhau của giờ quan sát. |
| **Q4** | Đặc trưng vệ tinh thiếu ở những thời gian và khu vực nào? | Mart ô–ngày, mart trạm–ngày | Tỷ lệ thiếu AOD, NO₂ và các biến vệ tinh theo năm, mùa và trạm. |
| **Q5** | Các ô có trạm có đại diện cho những ô còn lại về đặc trưng môi trường không? | Mart ô–ngày, danh sách ô có nhãn | So sánh phân phối đặc trưng (VIIRS, khí tượng) và bản đồ độ phủ. |
| **Q6** | PM2.5 thay đổi theo mùa và liên hệ với khí tượng, vệ tinh như thế nào trong dữ liệu hiện có? | Mart trạm–ngày | Biểu đồ và thống kê theo mùa, trạm và các biến môi trường. |
| **Q7** | Mô hình có ước tính tốt hơn baseline cho ngày hoặc khu vực chưa dùng để train không? | Mart train, mart đặc trưng | MAE, RMSE và sai số phân rã theo nhóm đánh giá. |

> [!NOTE]
> **Q1–Q6** là phạm vi Phân tích Khám phá Dữ liệu (EDA). **Q7** thuộc giai đoạn xây dựng và đánh giá mô hình, chỉ thực hiện sau khi hoàn tất các bước kiểm tra dữ liệu.

---

## 5. Các giả thuyết và kế hoạch kiểm tra

Các giả thuyết dưới đây là câu hỏi cần kiểm chứng bằng thực nghiệm, chưa phải kết luận cuối cùng. Quy trình chi tiết từng bước được quy định tại [analysisplan.md](./analysisplan.md).

| Mã | Giả thuyết | Phương pháp dự kiến | Quyết định hỗ trợ |
|:---:|---|---|---|
| **H1** | Độ phủ nhãn chênh lệch đáng kể giữa các năm và khu vực. | Đếm trạm, ô và ngày có nhãn; trực quan hóa theo tháng, năm và vị trí không gian. | Xác định năm và khu vực nào có đủ dữ liệu để đánh giá độc lập. |
| **H2** | Trung bình ngày tính từ ít giờ có thể khác đáng kể trung bình tính từ nhiều giờ hơn, tùy số giờ và thời điểm quan sát. | Trên cùng trạm–ngày có nhiều giờ sạch, lấy các tập con giờ rồi so sai khác với trung bình của ngày đó. | Quyết định cách báo cáo chất lượng nhãn và có cần thử nghiệm phân nhóm số giờ không. |
| **H3** | Một số trạm cùng ô–ngày có nhãn khác nhau; khác biệt có thể liên quan đến các giờ mà mỗi trạm đo được. | Tính chênh lệch trạm–ngày; đối chiếu số giờ và các giờ đo chung khi có thể. | Cân nhắc giữ riêng trạm hoặc thử tổng hợp nhãn ô–ngày. |
| **H4** | Tỷ lệ thiếu AOD, NO₂ và các biến vệ tinh thay đổi theo thời gian và khu vực. | Thống kê tỷ lệ thiếu theo năm, mùa, ô và trạm; so sánh tập train với toàn lưới. | Chọn cách xử lý thiếu và nhóm biến cần so sánh trong model. |
| **H5** | Phân phối đặc trưng tại các ô có trạm khác với các ô không có trạm. | So sánh phân phối khí tượng, VIIRS và biến không gian có sẵn theo cùng thời gian; vẽ bản đồ. | Xác định rủi ro ngoại suy và thiết kế cách chia test theo không gian. |
| **H6** | PM2.5 có khác biệt theo mùa trong dữ liệu của một số trạm. | Thống kê theo mùa trong từng trạm, kèm số quan sát theo năm; trực quan hóa phân phối. | Đánh giá vai trò của đặc trưng thời gian trong mô hình. |
| **H7** | Một số biến khí tượng hoặc vệ tinh có liên hệ với PM2.5 sau khi xem xét mùa và trạm. | Tương quan, biểu đồ phân tán và phân tầng; báo số mẫu có dữ liệu cho từng phép tính. | Chọn nhóm biến để thử model, không suy diễn nhân quả. |
| **H8** | Dữ liệu hiện có cho phép xây dựng một số cách chia test theo thời gian và không gian, nhưng mức hỗ trợ có thể khác nhau. | Mô phỏng các cách chia, đếm số trạm/ô/ngày ở mỗi tập và kiểm tra trùng nhóm. | Chốt cách chia tập train/test trước preprocessing và train. |

*Thứ tự thực hiện:* **H1 → H2 → H3 → H4 → H5 → H6 → H7 → H8**. Sau mỗi giả thuyết, nhóm xem kết quả thực nghiệm và chốt quyết định kỹ thuật trước khi chuyển tiếp.

---

## 6. Kế hoạch xây dựng và đánh giá mô hình

### Dữ liệu sử dụng

| Tập dữ liệu | Grain | Vai trò trong quy trình |
|---|---|---|
| [`mart_station_daily_training.parquet`](../data/marts/mart_station_daily_training.parquet) | Trạm–ngày | Các dòng có nhãn PM2.5 và vector đặc trưng để chia train/test. |
| [`mart_grid_daily_features.parquet`](../data/marts/mart_grid_daily_features.parquet) | Ô–ngày | Đặc trưng toàn bộ lưới ($6.591.860\text{ dòng}$), dùng tạo bản đồ dự đoán. |
| [`fct_ground_truth_daily.parquet`](../data/core/fct_ground_truth_daily.parquet) | Trạm–ngày | Nguồn nhãn và thông tin kiểm toán chất lượng (`valid_hours_count`, `is_valid_day`). |

Theo quyết định hiện tại: Các ngày có `pm25_raw_mean` khác NULL được giữ, kể cả dưới 18 giờ hợp lệ. Cột `valid_hours_count` và `is_valid_day` không đưa vào đầu vào model để tránh rò rỉ chất lượng đo vào X, nhưng vẫn dùng để phân tích chất lượng và báo cáo sai số.

### Baseline và mô hình thử nghiệm

Nhóm so sánh trên cùng một cách chia dữ liệu cố định:

1. **Baseline đơn giản:** Dự đoán theo trung bình mùa tính từ tập train.
2. **Model Thời gian + Khí tượng:** Đánh giá giá trị của dữ liệu khí tượng tái phân tích ERA5-Land (độ phủ 100%, không bị khuyết thiếu).
3. **Model có thêm Vệ tinh:** Đánh giá AOD, NO₂ và các biến viễn thám có thực sự cải thiện kết quả hay gây nhiễu do tỷ lệ khuyết cao.

*Lưu ý về biến:*
- Cột BLH chưa được dùng do hiện đang thiếu 100%.
- Biến OSM tạm thời chưa đưa vào; các đặc trưng tĩnh không gian khác (WorldCover, DEM) sẽ được bổ sung sau khi nhóm nhận và thống nhất dữ liệu bàn giao.

### Nguyên tắc đánh giá học máy

- **Chống rò rỉ (Data Leakage):** Chia train/test trước khi fit bất kỳ bước điền thiếu (imputation), mã hóa (encoding) hoặc chuẩn hóa (scaling) nào.
- **Grouped Split:** Các dòng cùng ô–ngày phải nằm cùng một phía (hoặc toàn bộ ở train, hoặc toàn bộ ở test) để tránh việc cùng một vector đặc trưng $X$ xuất hiện ở cả hai tập.
- **Đánh giá đa chiều:** Thử nghiệm đánh giá theo thời gian (Hold-out year/block) và theo cụm không gian (Spatial Group K-Fold / trạm giữ riêng).
- **Chỉ số báo cáo:** Báo cáo MAE, RMSE, $R^2$, số lượng mẫu và số lượng trạm của mỗi tập; phân rã sai số theo năm, mùa và số giờ hợp lệ.
- **Đối chiếu khách quan:** Đối chiếu trực tiếp với baseline; không tự đặt ngưỡng sai số thành công tùy tiện khi chưa có căn cứ thực nghiệm.

---

## 7. Những điều không được kết luận từ dữ liệu hiện tại

> [!CAUTION]
> **Ranh giới khoa học và đạo đức dữ liệu bắt buộc tuân thủ:**
> 1. **Dự đoán không phải số đo trực tiếp:** Giá trị ở ô không có trạm là kết quả ước tính của mô hình thống kê/học máy và luôn có sai số kèm theo.
> 2. **Không suy diễn nhân quả:** Tương quan giữa PM2.5 và nhiệt độ/mùa/khí áp không chứng minh đó là nguyên nhân trực tiếp gây ra ô nhiễm.
> 3. **Không tự kết luận cơ chế thiếu AOD là MNAR:** Tỷ lệ khuyết thiếu cao do mây chưa đủ để khẳng định cơ chế MNAR tuyệt đối; cần thêm bằng chứng vật lý trước khi kết luận.
> 4. **Không coi phân cấp Tier là chứng nhận:** Nhãn phân loại `sensor_tier` trong metadata không tự xác minh chất lượng phần cứng thực tế của cảm biến nếu chưa có hồ sơ kiểm định phòng lab.
> 5. **Không đồng nhất số ô với diện tích:** Tỷ lệ số ô có trạm (36/3.610 ô) là con số trên lưới rời rạc, không phản ánh tỷ lệ diện tích chính xác của toàn bộ địa giới hành chính.
> 6. **Không giả định chất lượng đồng nhất:** Mô hình không thể dự đoán tốt như nhau trên mọi vùng và mọi năm; giai đoạn 2021–2023 có rất ít trạm đo để kiểm chứng.
> 7. **Không dùng thay thế quan trắc pháp lý hoặc cảnh báo y tế:** Bản đồ ước tính trong phiên bản đầu tuyệt đối không được dùng như số liệu quan trắc pháp lý hay làm công cụ phát cảnh báo sức khỏe thời gian thực.

---

## 8. Phạm vi và quyết định kỹ thuật hiện tại

| Nội dung | Quyết định hiện tại | Căn cứ kỹ thuật |
|---|---|---|
| **Không gian** | Lưới phân tích 1 km của Hà Nội (EPSG:3405). | 3.610 ô phân tích thực trong `dim_grid_1km` (loại `grid_unknown`). |
| **Thời gian** | 01/01/2021 – 31/12/2025. | Trục 1.826 ngày lịch Hà Nội (`Asia/Ho_Chi_Minh`) trong `dim_date`. |
| **Hạt dự đoán** | Ô–ngày, khóa `(grid_id, date_id)`. | Quy mô ma trận bất biến 6.591.860 dòng tại `mart_grid_daily_features`. |
| **Hạt nhãn** | Trạm–ngày, khóa `(station_id, date_id)`. | 7.878 dòng quan sát tại `mart_station_daily_training`. |
| **Nhãn mục tiêu** | `pm25_raw_mean`. | Trung bình các giờ hợp lệ; chưa coi là giá trị đã hiệu chuẩn. |
| **Ngày ít giờ** | Giữ nếu `pm25_raw_mean IS NOT NULL`. | Không tự ý lọc bỏ ngày $<18\text{h}$; phân tích riêng ảnh hưởng chất lượng nhãn ở H2. |
| **Nhiều trạm cùng ô** | Tạm giữ riêng từng trạm. | Chưa gộp nhãn ô–ngày để bảo toàn thông tin biến thiên nội ô (khảo sát ở H3). |
| **Khí tượng & Vệ tinh** | Ghép từ các bảng fact hiện có. | NO₂ chọn từ TV3 (đã chuẩn hóa giờ địa phương); AOD/VIIRS từ TV2. |
| **Cột BLH** | Chưa dùng trong mô hình. | Hiện đang khuyết 100% trong dữ liệu nguồn. |
| **Biến OSM** | Tạm chưa dùng. | Chờ thống nhất phương pháp trích xuất đặc trưng tĩnh đô thị. |
| **Ước tính hôm nay** | Ngoài phạm vi phiên bản đầu. | Nghiên cứu sau khi mô hình lịch sử đạt độ tin cậy và có pipeline dữ liệu thời gian thực. |

---

*Mọi thay đổi về phạm vi, cách tạo nhãn, lựa chọn biến hoặc chiến lược đánh giá bắt buộc phải được ghi nhận vào decision log của dự án. Kế hoạch và kết quả kiểm định của từng giả thuyết EDA (H1–H8) được lưu trữ độc lập tại [analysisplan.md](./analysisplan.md).*
