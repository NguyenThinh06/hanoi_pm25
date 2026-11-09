# Lưu Trữ Lịch Sử & Tài Liệu Kỹ Thuật Chi Tiết (Archive) — HANOI_PM25

Thư mục `archive/` lưu trữ các tài liệu đặc tả kỹ thuật chi tiết, hợp đồng bàn giao phần mềm, hướng dẫn triển khai phụ trợ và các báo cáo nghiên cứu trước đây. Việc tách các tài liệu này vào `archive/` giúp giữ cho thư mục chính `docs/` luôn tinh gọn, tập trung đúng vào hai trụ cột: **Nghiệp vụ bài toán (`business_case.md`)** và **Kiến trúc dữ liệu (`schema.md`)**.

---

## 1. Tài Liệu Kỹ Thuật Đã Lưu Trữ (Archived Documents)

| Tài liệu | Mô tả nội dung | Lý do lưu trữ |
| :--- | :--- | :--- |
| 📜 **[`archive/HANDOVER.md`](HANDOVER.md)** | **Hợp đồng dữ liệu & API Contract v1:** Đặc tả 6 REST API endpoints, định dạng GeoJSON của 3.610 ô lưới, mã lỗi HTTP và tiêu chuẩn nghiệm thu end-to-end. | Hợp đồng bàn giao phục vụ tích hợp module, nay hệ thống đã hoàn thiện. |
| 🚀 **[`archive/DEPLOYMENT.md`](DEPLOYMENT.md)** | **Sổ tay triển khai 1-chạm & Vận hành:** Cấu hình Docker Compose, quy trình đối soát 3 điểm (`verify_reconciliation.py`), cơ chế Smoke Import 5s và sao lưu cơ sở dữ liệu. | Hướng dẫn kỹ thuật hạ tầng chi tiết; các bước chạy nhanh đã được tóm tắt ở `README.md`. |
| ⚡ **[`archive/BACKEND.md`](BACKEND.md)** | **Tài liệu kỹ thuật FastAPI backend:** Cấu trúc tầng service, cơ chế in-memory caching RAM, CORS middleware và kiểm thử API. | Tài liệu kiến trúc backend chi tiết, tham khảo khi cần mở rộng API. |
| 📄 **[`archive/report.md`](report.md)** | **Báo cáo Khoa học Dữ liệu toàn diện (12 phần):** Trình bày đầy đủ chu trình Data Science theo chuẩn môn học. | Bản báo cáo học thuật đầy đủ, chuyển vào archive để ưu tiên `business_case.md`. |
| 🔬 **[`archive/model_report.md`](model_report.md)** | **Báo cáo chuyên sâu về mô hình học máy:** So sánh chi tiết hiệu năng giữa Baseline 1 và Baseline 2 qua 3 phương pháp kiểm thử chéo. | Báo cáo phân tích thực nghiệm chi tiết cho nhà nghiên cứu. |

---

## 2. Bản Sao Trước Bàn Giao Prediction (04/11/2026)

`archive/docs_before_prediction_handover/` lưu giữ nguyên vẹn toàn bộ các tài liệu nghiên cứu sơ khởi, EDA nháp trước khi hợp nhất.

---

## 3. Bản Sao Đánh Giá Cũ (2026-11-03_legacy_evaluations)

- **Ngày lưu trữ:** `2026-11-03`
- **Lý do:** Repository đã hợp nhất và chuẩn hóa toàn bộ quy trình đánh giá và huấn luyện model vào [`src/models/train_baselines.py`](../src/models/train_baselines.py). Các script tách rời trước đây và các file kết quả đánh giá từng lưu trực tiếp trong `data/marts/` được chuyển vào đây để giữ sạch thư mục `src/models/` và `data/marts/`.
