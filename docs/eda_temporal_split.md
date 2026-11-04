# EDA phục vụ chia tập theo thời gian

## Phạm vi và cách tính

Phân tích trực tiếp `data/marts/mart_station_daily_training.parquet` hiện có. Chỉ giữ dòng `is_valid_day = 1` và `pm25_mean IS NOT NULL`, theo mặc định của `train_baselines.py`. Một dòng là một trạm–ngày; các dòng cùng trạm hoặc cùng ngày không độc lập. Đây là EDA để thiết kế đánh giá, chưa huấn luyện model hay tính sai số trên tập test.

- Mart có 9.207 dòng; sau lọc còn **7.290 dòng**, 32 trạm, 30 ô và khoảng ngày 01/01/2021–30/09/2026.
- Sau lọc không có ngày null hay khóa `(station_id, date_id)` trùng.
- Số trạm và ô này khác với con số 36 ô được ghi trong báo cáo cũ; kết luận trong tài liệu cũ cần đối chiếu lại với đúng phiên bản dữ liệu và lần chạy, không tự giả định nguyên nhân.

## Phân bố theo năm

| Năm | Trạm–ngày hợp lệ | Trạm | Ô | Ngày có quan trắc | AOD thiếu | PM2.5 trung bình (µg/m³) |
|---|---:|---:|---:|---:|---:|---:|
| 2021 | 304 | 1 | 1 | 304 | 92,1% | 42,32 |
| 2022 | 260 | 1 | 1 | 260 | 91,2% | 41,51 |
| 2023 | 263 | 1 | 1 | 263 | 87,8% | 41,57 |
| 2024 | 3.665 | 28 | 26 | 349 | 84,9% | 33,55 |
| 2025 | 1.788 | 18 | 18 | 352 | 85,3% | 42,11 |
| 2026 đến 30/09 | 1.010 | 6 | 6 | 273 | 92,7% | 41,37 |

Các năm 2021–2023 chỉ có một trạm/ô mỗi năm; số trạm thay đổi mạnh giữa các năm. Do đó, so sánh trung bình năm có thể phản ánh cả thay đổi mạng lưới trạm, không riêng sự thay đổi chất lượng không khí. Lưới 1 km và tập trạm được lọc không đại diện đều cho toàn thành phố.

Tỷ lệ null trên 7.290 dòng: NO₂ 71,0%, CO 57,5%, O₃ 0,9%, SO₂ 70,2%, AOD 86,7%, VIIRS 1,2%; nhiệt độ 2 m và BLH trung bình không null trong tập này. Tỷ lệ thiếu chỉ phản ánh training mart, không đại diện mọi ô lưới.

## Các mốc chia ứng viên

Mỗi phép chia dùng các ngày trước mốc để train và từ mốc trở đi để test; số trạm/ô tính riêng trong từng tập. Dòng test thuộc trạm đã biết là dòng có cùng `station_id` trong train.

| Mốc test | Train: dòng / trạm / ô | Test: dòng / trạm / ô | Dòng test từ trạm đã biết | Test có AOD | Test thiếu AOD |
|---|---|---|---:|---:|---:|
| 01/01/2024 | 827 / 1 / 1 | 6.463 / 32 / 30 | 396 | 891 | 5.572 |
| 01/01/2025 | 4.492 / 28 / 26 | 2.798 / 18 / 18 | 1.313 | 336 | 2.462 |
| 01/01/2026 | 6.280 / 32 / 30 | 1.010 / 6 / 6 | 1.010 | 74 | 936 |

Mốc 2024 chỉ có một trạm trong tập train nên không phù hợp làm đánh giá chính cho cấu hình mong muốn. Mốc 2025 có nhiều trạm hơn ở test, nhưng kết quả trộn cả trạm đã biết và chưa biết và bao gồm 2026; nếu dùng để lựa chọn model thì không còn là tập test độc lập với 2026. Mốc 2026 cho phép giữ giai đoạn cuối làm test, nhưng đánh giá chủ yếu khả năng ước tính ở **các trạm đã biết vào thời gian sau**: cả 1.010 dòng test thuộc trạm và ô từng xuất hiện trong train.

## Nhìn kỹ tập test 2026

- Có dữ liệu trong cả 273 ngày từ 01/01 đến 30/09, nhưng không phải trạm nào cũng có dữ liệu hàng ngày. Sáu trạm có lần lượt 266, 259, 254, 154, 59 và 18 dòng; ba trạm đầu chiếm 779/1.010 dòng (77,1%).
- Có AOD: 74 dòng, 4 trạm, 4 ô, chỉ 30 ngày riêng biệt. Thiếu AOD: 936 dòng, 6 trạm, 6 ô, 260 ngày riêng biệt. Số ngày hai nhóm có thể chồng nhau.
- Nhóm có AOD phân bố theo mùa: đông 25 dòng, xuân 23, hạ 10, thu 16; mỗi nhóm mùa chỉ có 6–8 ngày riêng biệt. Chia tiếp theo mùa và trạm sẽ làm cỡ mẫu rất nhỏ.
- PM2.5 trung bình của nhóm có AOD là 70,45 µg/m³, nhóm thiếu là 39,07 µg/m³. Hai nhóm còn khác mức thiếu các biến vệ tinh khác; khác biệt này là mô tả dữ liệu, không chứng minh thiếu AOD gây ra khác biệt PM2.5 hoặc sai số model.

## Đề xuất thiết kế đánh giá

1. **Giữ 2026 làm test thời gian cuối:** train trên 2021–2025, test từ 01/01 đến 30/09/2026. Mốc có thể thực hiện với dữ liệu hiện tại và giúp trả lời câu hỏi về thời gian mới tại các trạm đã biết; nó không kiểm tra độc lập khả năng suy rộng sang địa điểm mới.
2. **Lựa chọn model chỉ bằng dữ liệu trước 2026:** dùng các phép chia theo thời gian mở rộng bên trong train, chẳng hạn train 2021–2023 → validation 2024 và train 2021–2024 → validation 2025. Fold đầu chỉ có một trạm trong train nên ghi rõ đây là tình huống khắc nghiệt, không xem hai fold là đại diện đồng đều. Dùng Spatial GroupCV trên phần trước 2026 để bổ sung góc nhìn ô chưa thấy; các ô lân cận vẫn có thể tương quan, cân nhắc spatial block hoặc vùng đệm nếu đủ dữ liệu.
3. Chốt feature, tham số và quy tắc chọn model trước khi xem kết quả trên 2026. Các con số phân bố đầu vào và nhãn ở trên đã được xem để xác định tính khả thi; tập 2026 vì vậy không còn hoàn toàn nguyên vẹn cho quyết định thiết kế dựa trên phân bố. Không dùng sai số test để chỉnh model rồi báo cùng test như độc lập; nếu lặp lại cần giữ một tập ngoài mẫu khác, khi có thêm dữ liệu.
4. So sánh hai baseline trên cùng dòng test: MAE, RMSE, R², số dòng, trạm, ô và ngày; báo cáo theo trạm và theo tháng hoặc mùa để nhận diện tập trung. Xem thêm hai nhóm AOD cùng tập test, nêu rõ nhóm có AOD chỉ gồm 30 ngày. Xem mức thiếu các biến khác và sự khác nhau về mùa/trạm; không diễn giải chênh lệch giữa nhóm là tác động nhân quả.
5. Nếu muốn đánh giá đồng thời thời gian mới và địa điểm mới, bổ sung kiểm thử riêng với cả trạm/ô và ngày được giữ ngoài train. Với chỉ 6 trạm năm 2026, phân tích này hạn chế và không nên diễn giải quá mức. Model dùng đặc trưng của chính ngày ước tính và VIIRS theo tháng: chỉ kết luận về ước tính hồi cứu khi các nguồn đã có; không coi là dự báo ngày mai hay near-real-time nếu chưa kiểm tra thời điểm phát hành từng nguồn.

## Tái tạo thống kê

Ví dụ chạy từ thư mục gốc dự án với môi trường Python đã cài dependencies:

```python
import pandas as pd

df = pd.read_parquet("data/marts/mart_station_daily_training.parquet")
df = df[(df["is_valid_day"] == 1) & df["pm25_mean"].notna()].copy()
df["date"] = pd.to_datetime(df["date"])
summary = df.groupby(df["date"].dt.year).agg(
    rows=("pm25_mean", "size"),
    stations=("station_id", "nunique"),
    grids=("grid_id", "nunique"),
    days=("date", "nunique"),
    aod_missing_fraction=("aod_047_missing", "mean"),
    pm25_mean=("pm25_mean", "mean"),
)
print(summary)
```

Thống kê phụ thuộc snapshot Parquet và sẽ thay đổi nếu chạy lại pipeline hoặc cập nhật nguồn.
