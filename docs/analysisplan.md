# Kế hoạch EDA và đánh giá PM2.5 lịch sử

**Trạng thái:** Kế hoạch, chưa phải kết quả phân tích.  
**Business case:** [businesscase.md](./businesscase.md). Thực hiện và review từng giả thuyết theo thứ tự; không tự động chuyển sang bước tiếp theo.

## 1. Dữ liệu và kiểm tra đầu vào

| Nguồn | Grain và cột chính | Mục đích |
|---|---|---|
| `data/marts/mart_station_daily_training.parquet` | `(station_id, date_id)`; `grid_id`, `pm25_raw_mean`, thời gian và đặc trưng | Tập có nhãn, chưa chia train/test. |
| `data/marts/mart_grid_daily_features.parquet` | `(grid_id, date_id)`; thời gian và đặc trưng | So sánh với toàn lưới, đầu vào estimate. |
| `data/core/fct_ground_truth_daily.parquet` | `(station_id, date_id)`; `valid_hours_count`, `is_valid_day` | Kiểm tra chất lượng và truy xuất nhãn. |
| `data/core/dim_station.parquet` | `station_id`; tọa độ, `grid_id`, metadata | Không gian và danh mục trạm. |
| `data/core/dim_grid_1km.parquet`, `data/core/dim_date.parquet` | `grid_id`, `date_id` | Khung lưới/ngày và thuộc tính ngày. |
| `data/staging/stg_ground_truth_hourly.parquet` | `(station_id, sensor_id, datetime_utc)`; `datetime_local`, `pm25` | Phân tích giờ và giờ đo chung. |

Trước mỗi phân tích: kiểm tra sự tồn tại, schema, số dòng, null, khóa duy nhất và phạm vi ngày; lưu đường dẫn, thời điểm kiểm tra, phiên bản code và mã băm file dùng trong báo cáo. Kiểm tra khóa phía phải trước mỗi join; báo số dòng không khớp và số dòng trước/sau join. Dữ liệu Parquet không áp đặt khóa vật lý: các quy tắc cần được kiểm tra bằng truy vấn.

**Lưu ý QC giờ:** staging giờ hiện chưa lưu `qc_flag`. Không coi mọi dòng staging là giờ sạch. Với H2/H3 phải chạy lại hàm QC hiện hành trên bản sao/in-memory, áp dụng đúng quy tắc gộp giờ của pipeline, sau đó đối chiếu `valid_hours_count` và `pm25_raw_mean` với fact. Nếu không tái lập được, báo giới hạn và dừng kết luận liên quan giờ sạch.

## 2. Quy ước phân tích

- Múi giờ phân tích là `Asia/Ho_Chi_Minh`; dùng `date_id`/ngày địa phương thống nhất. Không tự chuyển ngày đã được TV3 xác nhận là ngày Hà Nội thêm lần nữa.
- Đơn vị quan sát phải ghi rõ: sensor–giờ, trạm–ngày hay ô–ngày. Không coi các dòng cùng trạm qua nhiều ngày là độc lập hoàn toàn.
- Phân biệt 3 mẫu số: trạm trong danh mục; trạm/ô có ít nhất một nhãn; toàn bộ ô–ngày trong mart. Không diễn giải tỷ lệ số ô như tỷ lệ diện tích.
- Thống kê cả số lượng và tỷ lệ, báo mẫu số, giai đoạn, số trạm và số ô; phân biệt null với giá trị 0. Không tự sửa nguồn hoặc loại ngoại lệ chỉ vì IQR.
- Mô tả tương quan, không suy luận nhân quả. Không kết luận MNAR từ dữ liệu quan sát; `is_aod_missing_mnar` hiện chỉ nên diễn giải là cờ thiếu AOD cho tới khi xác minh.
- Mô hình thống kê/kiểm định nếu áp dụng phải nêu giả định, hiệu ứng và bất định; tính đến quan sát lặp theo trạm và thời gian. Khi số trạm ít, ưu tiên mô tả và báo hạn chế thay vì khẳng định ý nghĩa thống kê.
- Chia train/test trước khi fit preprocessing, chọn đặc trưng theo hiệu năng hoặc dùng test để hiệu chỉnh phương pháp. EDA trên toàn bộ dữ liệu được đánh dấu là mô tả, không dùng để tối ưu trên tập test giữ riêng.

## 3. Giả thuyết và các bước

### H1 — Độ phủ nhãn theo không gian và thời gian

**Câu hỏi:** Dữ liệu có thể hỗ trợ đánh giá tại những năm, mùa và khu vực nào?  
**Giả thuyết:** Số trạm, ô và ngày có nhãn không phân bố đều.

1. Từ fact chọn `pm25_raw_mean IS NOT NULL`; kiểm tra trùng `(station_id, date_id)` và đối chiếu mart nhãn.
2. Ghép `dim_date` theo `date_id`, `dim_station` theo `station_id`; kiểm tra khóa, null và số dòng không khớp.
3. Đếm nhãn, trạm, ô và ngày riêng biệt theo năm/tháng/mùa; so sánh danh mục trạm và trạm thực sự có nhãn.
4. Vẽ chuỗi số trạm có nhãn theo tháng và bản đồ vị trí trạm theo năm; nêu trạm/ô có ít quan sát và các tháng không có nhãn.
5. Báo giới hạn theo năm và khu vực; đề xuất phạm vi đánh giá phù hợp, chưa suy ra độ chính xác dự đoán.

**Đầu ra:** Bảng độ phủ, hai biểu đồ, danh sách giới hạn và quyết định về dữ liệu phù hợp cho H2. Khóa thời gian dùng ngày địa phương. Mẫu số bản đồ là số ô; phân biệt điểm nằm trong ô với diện tích phủ.

### H2 — Độ nhạy của nhãn với số giờ hợp lệ

**Câu hỏi:** Nhãn tính từ ít giờ sai khác bao nhiêu so với trung bình từ nhiều giờ sạch hơn trong cùng ngày?  
**Giả thuyết:** Sai khác phụ thuộc số giờ và khoảng thời gian quan sát.

1. Áp dụng lại QC và gộp một giá trị mỗi giờ như pipeline; đối chiếu với fact trước khi phân tích.
2. Chọn các trạm–ngày có đủ 24 giờ sạch làm mẫu chính; báo số ngày/trạm được chọn và mức đại diện. Nếu mẫu quá ít, báo kết quả và đề xuất ngưỡng tham chiếu khác, không tự coi đó là 24 giờ hoàn chỉnh.
3. Trên cùng ngày, thử tập con 1, 6, 12, 17 và 18 giờ, theo các cửa sổ giờ được xác định trước; nếu lấy mẫu ngẫu nhiên, cố định seed và số lần lặp. So với trung bình 24 giờ của chính ngày đó.
4. Báo median sai khác có dấu, MAE, các phân vị sai khác tuyệt đối, số ngày/trạm theo số giờ và cửa sổ. So sánh thêm theo mùa/trạm khi đủ mẫu.

**Quyết định:** Có cần báo riêng chất lượng nhãn hoặc thử nghiệm trọng số theo giờ trong mô hình hay không. Kết quả chỉ áp dụng cho nhóm ngày đủ giờ tham chiếu, không tự chứng minh ngày thiếu giờ có cùng cơ chế thiếu.

### H3 — Nhiều trạm trong cùng ô–ngày

**Câu hỏi:** Các trạm có giá trị khác nhau bao nhiêu khi cùng ô–ngày?  
**Giả thuyết:** Sai khác nhãn thay đổi theo cặp trạm và mức độ trùng giờ quan sát.

Từ fact chọn nhãn không null, lập từng cặp trạm duy nhất theo `(grid_id, date_id)`; báo số cặp trạm và ô–ngày, tránh coi 33 ô–ngày là 33 cặp trạm độc lập. Tính chênh lệch có dấu/tuyệt đối, phân vị và `valid_hours_count`. Nếu tái lập được QC giờ, so sánh thêm trên **giờ chung**; báo ngày không đủ giờ chung. Trực quan hóa theo cặp trạm và ngày.

**Quyết định:** Giữ trạm riêng hay thử nhãn tổng hợp theo ô–ngày trong một thí nghiệm sau. Không kết luận sai số thiết bị hoặc nguyên nhân từ chênh lệch; các ngày lặp cùng cặp trạm không độc lập.

### H4 — Thiếu dữ liệu vệ tinh

**Câu hỏi:** AOD, NO₂, CO, O₃, SO₂ và VIIRS thiếu ở đâu và khi nào?  
**Giả thuyết:** Tỷ lệ thiếu thay đổi theo năm, mùa và ô.

Tính số lượng/tỷ lệ null và mẫu số theo biến, năm, mùa và trạm cho tập có nhãn; tính riêng theo ô–ngày cho toàn lưới. Thống kê các tổ hợp có/thiếu, ví dụ có NO₂ khi AOD thiếu; so sánh theo RH/mưa một cách mô tả. Với ô có nhiều trạm, lưu ý trọng số trạm–ngày khác trọng số ô–ngày.

**Quyết định:** Chọn kịch bản baseline và thí nghiệm có/không vệ tinh. Không xác định nguyên nhân mây hay MNAR chỉ từ bảng null; không điền thiếu trong EDA.

### H5 — Tính đại diện không gian

**Câu hỏi:** Ô có nhãn khác toàn lưới về đặc trưng đến mức nào?  
**Giả thuyết:** Các phân phối không giống nhau.

Chọn rõ tập ô có nhãn theo từng năm, so với ô không có nhãn trong cùng năm và thời gian; so sánh riêng theo ô–ngày với trọng số phù hợp, tránh nhân các ô nhiều trạm. Vẽ phân phối VIIRS, khí tượng có sẵn và bản đồ ô có trạm. Nếu dùng Wasserstein/PSI, ghi cách lấy mẫu, chia bins và tỷ lệ null; đây là mô tả độ khác biệt, không chứng minh mô hình kém chính xác.

**Quyết định:** Vùng và nhóm đặc trưng cần lưu ý khi thử chia test không gian. Lớp phủ/địa hình chỉ phân tích sau khi có file và xác minh.

### H6 — Sự thay đổi PM2.5 theo mùa

**Câu hỏi:** PM2.5 thay đổi ra sao giữa các mùa trong từng trạm?  
**Giả thuyết:** Một số trạm có phân bố PM2.5 khác nhau theo mùa.

Báo count, median, IQR và mean theo trạm–năm–mùa, vẽ phân phối với số mẫu. Phân tích chính trong các trạm có đủ dữ liệu ở nhiều mùa; công bố điều kiện chọn và số trạm bị loại. Không diễn giải chênh lệch toàn tập là nguyên nhân do mùa khi số trạm thay đổi theo năm; lưu ý nhãn có số giờ khác nhau.

**Quyết định:** Cách đưa thời gian vào mô hình và nhóm cần đánh giá riêng.

### H7 — Quan hệ giữa đặc trưng và nhãn

**Câu hỏi:** Khí tượng và vệ tinh có tín hiệu liên hệ với PM2.5 như thế nào?  
**Giả thuyết:** Một số đặc trưng có liên hệ với nhãn trong ít nhất một nhóm trạm/mùa.

Thống kê phân phối, số mẫu hợp lệ từng biến; dùng biểu đồ và tương quan Spearman trên các cặp quan sát đầy đủ, phân tầng theo mùa/trạm khi đủ mẫu. Báo tỷ lệ thiếu, cỡ mẫu và độ nhạy khi thay nhóm; không tự xóa giá trị âm của khí vệ tinh. Các dòng lặp theo trạm/ngày và lựa chọn chỉ các ngày có vệ tinh gây thiên lệch; không suy ra nhân quả hoặc khẳng định hiệu quả dự đoán từ tương quan.

**Quyết định:** Chọn nhóm biến cho các thí nghiệm mô hình so sánh, chưa chọn bằng điểm test cuối.

### H8 — Khả năng chia dữ liệu để đánh giá

**Câu hỏi:** Có thể kiểm tra model theo thời gian và ô/trạm chưa thấy không?  
**Giả thuyết:** Các cách chia khả thi có quy mô và mức đại diện khác nhau.

Mô phỏng chia theo năm và chia theo nhóm ô hoặc vùng; báo số dòng, trạm, ô, ngày, mùa và tỷ lệ thiếu ở mỗi tập. Tất cả dòng cùng ô–ngày ở cùng tập; với đánh giá ô chưa thấy, giữ toàn bộ ngày của ô đó cùng phía và kiểm tra trạm gần nhau/cùng ô. Chia theo trạm riêng không tự bảo đảm độc lập không gian. Chốt một tập test giữ riêng; không điều chỉnh mô hình dựa trên tập đó.

**Quyết định:** Cách chia và phạm vi kết luận. Tập 2021–2023 có ít trạm nên không đại diện đầy đủ cho toàn thành phố.

## 4. Kế hoạch model sau EDA

Trước tiên chốt split và baseline trung bình theo mùa fit trên train. So sánh cùng split giữa: thời gian + khí tượng; thêm O₃/VIIRS; thêm các biến vệ tinh khác và cờ thiếu. Những cột BLH thiếu toàn bộ không chọn cho thử nghiệm đầu. Xử lý null và mã hóa chỉ fit trên train; áp dụng cùng pipeline cho test và toàn lưới.

Báo MAE/RMSE so với baseline, phân tầng theo thời gian, không gian và chất lượng nhãn; không suy ra hiệu quả ngoài phạm vi được kiểm chứng. Dự đoán mart lưới theo batch để kiểm soát bộ nhớ. Độ bất định chỉ công bố sau khi chọn phương pháp và kiểm định độ bao phủ phù hợp.

## 5. Biên bản cho từng giả thuyết

Mỗi lần phân tích cần ghi: câu hỏi, phiên bản dữ liệu/code, phạm vi, bộ lọc, số dòng/trạm/ô, mẫu số và tỷ lệ thiếu; phương pháp, biểu đồ, kết quả, hạn chế và quyết định. Lưu kết quả riêng, không ghi đè Parquet nguồn; review xong mới chuyển sang giả thuyết tiếp theo.
