# Lộ trình sau bàn giao data/model

Phần đã hoàn thành: ingestion, marts Parquet/DuckDB, đánh giá ba phương pháp, lưu hai model cuối và metadata JSON cục bộ. Xem [model_report.md](model_report.md).

## Ưu tiên hiện tại

1. Nhận data/model theo [DATA_DELIVERY.md](DATA_DELIVERY.md), kiểm tra checksum và feature contract.
2. Viết inference độc lập từ hai model đã lưu; chạy trên vài ngày trước, xuất Parquet và manifest.
3. Dựng PostgreSQL/PostGIS bằng Docker, thiết kế migration và nạp dữ liệu chống trùng.
4. Viết FastAPI phục vụ bản đồ theo model/ngày, lịch sử ô và quan trắc trạm.
5. Xây React dashboard có bộ chọn ngày/model, chú giải cố định, đơn vị µg/m³ và lớp trạm.
6. Nghiệm thu Parquet → database → API → UI, sau đó mở rộng phạm vi lịch sử và thử backup/restore.

Phân công, hợp đồng dữ liệu, tiêu chí nghiệm thu và mẫu báo cáo nằm trong [HANDOVER.md](HANDOVER.md). Người dùng được chọn cả hai model; không cần train lại để triển khai. Khóa serving phải phân biệt ô, ngày và cả model lẫn phiên bản.

## Để sau phiên bản đầu

Biến tĩnh, IDW, tuning, đánh giá không gian có vùng đệm, cập nhật dữ liệu tự động và triển khai cloud. Những việc này không phải điều kiện nhận bàn giao hiện tại.

Kết quả là PM2.5 ước tính hồi cứu, không phải AQI hay dự báo ngày mai. Độ thiếu feature và chênh lệch hai model không tự tạo thành khoảng bất định.
