# Nhận bàn giao data và models

Phạm vi: pipeline dữ liệu, đánh giá, hai model cuối và metadata JSON cục bộ. PostgreSQL, Docker, API và dashboard chưa triển khai trong bản này; xem [HANDOVER.md](HANDOVER.md).

## 1. Nhận code

```powershell
git clone --branch handover/end-to-end https://github.com/NguyenThinh06/hanoi_pm25.git
cd hanoi_pm25
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 2. Nhận artifact

Hai gói được tạo tại `handover_bundles/` trên máy bàn giao (không commit vào Git):

| Gói | Nội dung | Người cần |
|---|---|---|
| `pm25-deployment-2026-11-04.tar.gz` | Core, hai marts, reference, hai model, đánh giá và registry | Cả nhóm triển khai |
| `pm25-source-2026-11-04.tar.gz` | Raw và staging | Người tái tạo pipeline từ dữ liệu nguồn |

Mỗi gói có file `.sha256` và `.manifest.json` đi kèm; manifest cũng nằm trong archive. Manifest ghi từng file, dung lượng, checksum, thời điểm và commit đóng gói. Không chứa `.env`, SQL, môi trường Python hoặc prediction toàn lưới cũ chưa xác minh.

**Trạng thái chia sẻ:** gói được chuẩn bị cục bộ; chưa có URL tải được xác nhận. Người bàn giao tải hai gói và checksum lên thư mục dùng chung, cấp quyền tải cho thành viên rồi cập nhật URL vào mục này. Không coi clone Git là đã nhận data/model.

## 3. Kiểm tra và giải nén

Giả sử gói tải về nằm ở Downloads:

```powershell
Get-FileHash "$HOME\Downloads\pm25-deployment-2026-11-04.tar.gz" -Algorithm SHA256
python scripts/package_handover.py --verify "$HOME\Downloads\pm25-deployment-2026-11-04.tar.gz"
tar -xzf "$HOME\Downloads\pm25-deployment-2026-11-04.tar.gz"
```

So SHA-256 với file checksum được bàn giao. Giải nén từ thư mục gốc repo, trên checkout mới hoặc sau khi sao lưu dữ liệu riêng để tránh ghi đè. Gói source dùng cách tương tự nếu cần; `HANDOVER_MANIFEST.json` ở gốc sau giải nén thuộc gói vừa giải nén gần nhất, manifest riêng đi kèm giữ lịch sử từng gói.

Kiểm tra file bắt buộc:

```powershell
Test-Path data/core/dim_grid_1km.parquet
Test-Path data/marts/mart_grid_daily_features.parquet
Test-Path data/marts/mart_station_daily_training.parquet
Test-Path outputs/models/baseline1/model.json
Test-Path outputs/models/baseline2/model.json
```

Tất cả phải là `True`. Có thể chạy `python run.py lint` và `python run.py test`. Không cần chạy `train`, `train-final`, `build` hoặc fetch dữ liệu để bắt đầu làm ứng dụng từ artifact đã nhận.

Registry trong gói là metadata cục bộ, không chứng minh có database. Phiên bản/checksum model lấy từ metadata và manifest; không thay thế model cũ bằng model tự train mà giữ nguyên version.

## 4. Tạo lại gói

```powershell
python scripts/package_handover.py --kind deployment
python scripts/package_handover.py --kind source
```

Script từ chối ghi đè gói đã tồn tại và tự kiểm tra toàn bộ checksum trong archive trước khi công bố file cuối. Khi có bản dữ liệu mới cần dùng tên phiên bản mới và cập nhật hướng dẫn, không ghi đè âm thầm bản đã chia sẻ.
