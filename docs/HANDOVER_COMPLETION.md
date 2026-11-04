# Kết quả chuẩn bị bàn giao data/model — 04/11/2026

## Đã thực hiện

- Dùng nhánh có sẵn `handover/end-to-end`.
- Tách hoàn toàn việc kết nối PostgreSQL khỏi registry của training/evaluation; metadata tiếp tục lưu JSON cục bộ.
- Giữ các SQL nháp trên máy, bỏ khỏi staging và thêm ignore; code/tests không cần các file này.
- Giữ bản sao code/tài liệu trước khi thay đổi tại `archive/2026-11-04_pre_handover/` trên máy bàn giao.
- Cập nhật README, handover, roadmap, hướng dẫn nhận data, cấu hình môi trường mẫu và CLI đánh giá trong tài liệu.
- Sửa CRS trong README/model report thành EPSG:3405, khớp code và GeoParquet hiện có. Không thay đổi số liệu đánh giá model.
- Thêm công cụ đóng gói/kiểm tra artifact theo danh sách file tường minh, có SHA-256 từng file và toàn bộ archive.
- Không thay đổi dữ liệu nguồn, mart, model cuối hoặc chạy lại các đánh giá trên dữ liệu thật.

## Kiểm tra thực tế

| Kiểm tra | Kết quả |
|---|---|
| `python run.py lint` | All checks passed |
| `python run.py test` | 13 passed, 157,18 giây |
| Registry khi có biến môi trường database | Vẫn lưu local, không kết nối database |
| Model Baseline 1 | Load thành công, 27 feature đúng thứ tự |
| Model Baseline 2 | Load thành công, 34 feature đúng thứ tự |
| Dự đoán lại 25 mẫu kiểm chứng mỗi model | Sai lệch tuyệt đối lớn nhất = 0,0 |
| Mart training trước lọc | 9.207 dòng |
| Mart toàn lưới | 7.577.390 dòng |
| CRS GeoParquet ô lưới | EPSG:3405 |
| CLI evaluate với UTF-8 | Help hoạt động, tên method đúng tài liệu |

Lần chạy tests trong sandbox ban đầu bị chặn truy cập thư mục tạm Windows; chạy lại ngoài sandbox đã qua đầy đủ. Tests dùng dữ liệu tổng hợp/tạm, không train lại hai model bàn giao. Với PowerShell gặp lỗi xuất tiếng Việt, bật `$env:PYTHONUTF8 = "1"` hoặc dùng `python -X utf8`.

## Artifact bàn giao

Xem `handover_artifacts.json` để lấy tên gói, commit đóng gói, dung lượng, số file và checksum. Các gói nằm ở `handover_bundles/` trên máy bàn giao, không nằm trong Git. Đã kiểm tra toàn bộ nội dung archive với manifest trước khi hoàn tất mỗi gói.

File prediction toàn lưới cũ chưa xác minh `data/marts/pred_grid_daily_pm25.parquet` không được đóng gói. Nhóm triển khai cần tạo prediction từ hai model cuối theo phạm vi đã thống nhất.

## Việc còn lại

1. Chủ dự án tự upload các gói, `.sha256` và `.manifest.json` lên Drive, cấp quyền cho nhóm rồi điền link vào `DATA_DELIVERY.md`.
2. Một thành viên tải gói trên máy khác, kiểm tra checksum, giải nén và xác nhận nhận đủ artifact.
3. Triển khai inference, PostgreSQL/PostGIS, Docker, API và dashboard theo `HANDOVER.md`.

Bản này hoàn tất chuẩn bị code và gói dữ liệu cục bộ; chưa tuyên bố ứng dụng end-to-end đã hoạt động hoặc nhóm đã tải dữ liệu thành công.
