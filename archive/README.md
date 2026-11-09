# Lưu trữ Lịch sử (Archive) — HANOI_PM25

## Đợt lưu trữ tài liệu trước bàn giao prediction toàn lưới (04/11/2026)

`archive/docs_before_prediction_handover/` (bản lưu cục bộ trên máy, nằm trong `.gitignore` theo quy tắc chung của thư mục `archive/*`) lưu giữ nguyên vẹn toàn bộ các tài liệu nghiên cứu, EDA, schema chi tiết và báo cáo đánh giá mô hình trước khi hợp nhất thành một tài liệu bàn giao duy nhất:
- `business_case.md`: Khung giả thuyết và bài toán kinh doanh.
- `schema.md`: Đặc tả chi tiết các bảng trong Data Lakehouse.
- `model_report.md`: Báo cáo chi tiết 3 phương pháp đánh giá mô hình.
- `eda_temporal_split.md`: Báo cáo EDA phân chia tập theo thời gian.
- `roadmap.md`: Lộ trình ban đầu của dự án.
- `DATA_DELIVERY.md`: Hướng dẫn nhận dữ liệu cũ.
- `HANDOVER_COMPLETION.md`: Biên bản hoàn thành chuẩn bị dữ liệu cũ.
- `handover_artifacts.json`: Manifest cũ của các gói artifact.
- `GROUP_HANDOVER.md`: Bản thảo bàn giao nội bộ nhóm.

---

## Bản sao trước bàn giao data/model ngày 04/11/2026

`archive/2026-11-04_pre_handover/` giữ bản sao registry, tests và tài liệu trước khi tách đồng bộ PostgreSQL. Các file SQL nháp vẫn ở `sql/` trên máy bàn giao. Cả hai phần này không nằm trong commit/gói data-model; không bị xóa và không phải dependency của code bàn giao. Chỉ README archive được đưa vào Git.

Thư mục này lưu giữ các script và kết quả đánh giá trung gian của các phiên bản trước khi quy trình đánh giá và huấn luyện model được tổ chức lại vào ngày **2026-11-03**.

> **Nguyên tắc:** Không xóa âm thầm lịch sử thực nghiệm và tuyệt đối không di chuyển hay sửa đổi dữ liệu nguồn/marts đầu vào (`data/raw/`, `data/staging/`, `data/core/`, `data/marts/mart_grid_daily_features.parquet`, `data/marts/mart_station_daily_training.parquet`).

---

## Đợt lưu trữ `2026-11-03_legacy_evaluations`

- **Ngày lưu trữ:** `2026-11-03`
- **Lý do lưu trữ:**
  Repository đã hợp nhất và chuẩn hóa toàn bộ quy trình đánh giá và huấn luyện model vào [`src/models/train_baselines.py`](../src/models/train_baselines.py) cùng [`src/models/registry.py`](../src/models/registry.py) theo đúng 3 phương pháp đánh giá chuẩn (`outputs/evaluation/spatial_groupkfold/`, `outputs/evaluation/random_kfold/`, `outputs/evaluation/temporal_split/`) và quy trình huấn luyện model cuối (`outputs/models/baseline1/`, `outputs/models/baseline2/`). Các script tách rời trước đây và các file kết quả đánh giá từng lưu trực tiếp trong `data/marts/` được chuyển vào đây để giữ sạch thư mục `src/models/` và `data/marts/`.

### Danh mục các file được lưu trữ trong `archive/2026-11-03_legacy_evaluations/`

1. **`scripts/` (Mã nguồn đánh giá trung gian đã được hợp nhất vào `src/models/train_baselines.py`):**
   - `evaluate_temporal_baselines.py`: Script đánh giá thử nghiệm chia tập trước 2026 (`Validation 2025`, `Spatial GroupCV trước 2026`, `Test 2026`).
   - `analyze_spatial_groupcv.py`: Script phân tích sâu Spatial GroupCV trước 2026 và xuất biểu đồ.
2. **`marts_outputs/` (Các kết quả đánh giá cũ từng đặt chung trong `data/marts/`):**
   - `model_comparison_metrics.parquet`, `model_feature_importance.parquet`, `oof_station_predictions.parquet`: Đầu ra từ phiên bản `train_baselines.py` cũ.
   - `temporal_baseline_metrics.parquet`, `temporal_evaluation_summary.json`, `val_2025_station_predictions.parquet`, `test_2026_station_predictions.parquet`: Đầu ra từ `evaluate_temporal_baselines.py`.
   - `spatial_pre2026_oof_predictions.parquet`, `spatial_pre2026_fold_metrics.parquet`, `spatial_pre2026_grid_metrics.parquet`, `spatial_pre2026_summary_metrics.parquet`, `spatial_pre2026_stability_summary.json`: Đầu ra từ `analyze_spatial_groupcv.py`.
3. **`figures/` (Biểu đồ phân tích nhánh Spatial trước 2026):**
   - `spatial_pre2026_grid_delta_mae.png`
   - `spatial_pre2026_grid_sample_counts.png`
