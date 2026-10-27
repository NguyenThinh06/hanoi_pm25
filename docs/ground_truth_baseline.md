# Khảo sát dữ liệu trạm trước khi sửa và xây dựng nhãn ô–ngày

Ngày khảo sát: 2026-10-27. Số liệu dưới đây đọc từ Parquet hiện có; đây là
baseline, chưa chứng minh dữ liệu nguồn đã được tải đầy đủ hoặc QC đã đúng.
Các file Parquet này được tạo bởi phiên bản pipeline trước các thay đổi hiện
có trong workspace.

| Chỉ số | Kết quả |
| --- | ---: |
| Bản ghi staging giờ | 162.543 |
| Giờ có qc_flag = 0 | 162.514 |
| Giờ có qc_flag = 3 | 29 |
| Trạm–ngày staging không đạt ngưỡng theo pipeline cũ | 1.606 |
| Trạm–ngày trong fact | 6.276 |
| Cặp (station_id, date_id) trùng trong fact | 0 |
| Trạm–giờ trùng trong staging hourly | 0 |
| Fact không nối được dim_station / dim_grid / dim_date | 0 / 0 / 0 |

## Số trạm theo ô

Trong danh mục hiện tại, 34 ô có 1 trạm, 3 ô có 2 trạm và 1 ô có 3 trạm.
Trong fact, 6.274 ô–ngày có 1 trạm và 1 ô–ngày có 2 trạm. Ô–ngày có hai trạm
là `grid_584000_2324000`, 2024-02-26: giá trị trạm–ngày là 32,74 và
53,22 µg/m³; mean và median đều bằng 42,98 µg/m³. Thống kê chỉ tính những
ô–ngày có quan sát, không bao gồm ô–ngày không có trạm.

## Số trạm–ngày theo năm trong fact

| Năm | Trạm–ngày | Số trạm |
| --- | ---: | ---: |
| 2021 | 302 | 1 |
| 2022 | 260 | 1 |
| 2023 | 262 | 1 |
| 2024 | 3.664 | 28 |
| 2025 | 1.788 | 18 |

Số trạm trong bảng trên là trạm có ít nhất một dòng fact trong năm, không phải
số trạm hoạt động đầy đủ cả năm. Không có file raw tháng 04/2022 trong workspace;
điều đó chưa xác định được nguồn không có dữ liệu hay việc thu thập chưa đầy đủ.
Bản baseline trước đây có cột hiệu chỉnh chưa được xác minh; không dùng cột đó làm bằng chứng đã hiệu chỉnh.
