# Bàn giao Gói 2 — Backend API

Backend phục vụ dữ liệu PostgreSQL/PostGIS theo **API Contract v1**, mục 5 của
[HANDOVER.md](HANDOVER.md). Nồng độ PM2.5 là **µg/m³**, giá trị ước tính hồi cứu.
Backend không train model, không import dữ liệu, không chạy migration khi khởi động.

## Khởi động trên PowerShell

Chạy từ thư mục gốc repository, Python >= 3.11:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-api-dev.txt
# Chỉ chạy dịch vụ: dùng requirements-api.txt.
# Cài cả pipeline và bộ tests cũ: dùng requirements.txt.
```

Dùng `DATABASE_URL` do Gói 1 cung cấp, thông qua biến môi trường của tiến trình
hoặc file `.env` local đã có. API đọc `.env` ở gốc repository và ưu tiên biến môi trường.
Không commit `.env` hay chuỗi kết nối có mật khẩu. Tham khảo các tên biến của Gói 1
trong `.env.example`; Backend không tự tạo mật khẩu hay suy đoán cấu hình kết nối.

```powershell
# Chỉ cần nếu Frontend gọi khác origin; thay bằng origin thực tế của nhóm.
$env:API_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
.\.venv\Scripts\python.exe -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload
```

Swagger: <http://127.0.0.1:8000/docs>. OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>.
`/docs` và `/openapi.json` hoạt động cả khi DB chưa sẵn sàng. Thiếu `DATABASE_URL`,
DB mất kết nối, thiếu PostGIS hoặc bảng serving: `/health` trả 503 theo envelope v1.
Health kiểm tra kết nối, PostGIS và sự tồn tại các bảng phục vụ; **không chứng nhận dữ liệu đã nạp đủ**.

Kiểm tra nhanh khi đã cấu hình DB:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
$models = Invoke-RestMethod http://127.0.0.1:8000/api/models
$model = [uri]::EscapeDataString($models.data[0].model_id)
Invoke-RestMethod "http://127.0.0.1:8000/api/dates?model_id=$model"
Invoke-RestMethod http://127.0.0.1:8000/api/grids
Invoke-RestMethod "http://127.0.0.1:8000/api/map?date=2024-01-15&model_id=$model"
Invoke-RestMethod "http://127.0.0.1:8000/api/grids/grid_584000_2324000/history?model_id=$model&start=2024-01-01&end=2024-01-31"
Invoke-RestMethod "http://127.0.0.1:8000/api/stations?date=2024-01-15"
```

Thay ngày và grid bằng giá trị tồn tại trong DB. Danh sách model rỗng là kết quả hợp lệ;
cần Gói 1 nạp prediction trước khi chạy các ví dụ dùng `$models.data[0]`.

## Thiết kế và cấu hình

`src/api/main.py` tạo app và quản lý lifespan. `config.py` đọc cấu hình, `database.py`
quản lý pool psycopg dùng chung cho mỗi worker. `repository.py` chỉ có SELECT tham số hóa.
`routes.py` điều phối 7 endpoint, `schemas.py` kiểm tra đầu vào/đầu ra và sinh OpenAPI,
`errors.py` chuẩn hóa lỗi. API không phụ thuộc pandas, DuckDB hay XGBoost để khởi động.

Runtime yêu cầu FastAPI >= 0.121 để hỗ trợ dependency `scope="function"` và
`psycopg-pool>=3.2.3,<4` được ràng buộc riêng để bảo đảm có `check_connection`/`check`.
Phiên bản driver `psycopg` và gói pool là hai dependency độc lập.

Pool chỉ lấy kết nối khi route thực sự truy vấn, sau validation; request sai ngày hoặc
khoảng ngày vẫn trả 422 khi DB offline. Route đồng bộ chạy trong thread pool FastAPI.
Giao dịch đọc kết thúc và kết nối được trả lại pool trước khi gửi response
(`Depends(..., scope="function")`); nếu bước này lỗi, API vẫn có thể trả đúng envelope
thay vì gửi 200 quá sớm. Lỗi truy vấn rollback và lỗi kết nối trả 503.
Session dùng `default_transaction_read_only=on`, timeout truy vấn, múi giờ Hà Nội.
Gói 4 nên cấp tài khoản chỉ có SELECT và USAGE trên schema; thiết lập session đọc là
một lớp bảo vệ bổ sung, không thay cho phân quyền DB.

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `DATABASE_URL` | chưa cấu hình | DSN PostgreSQL giống importer Gói 1 |
| `API_DB_POOL_MIN` | `0` | Số kết nối tối thiểu; không chặn startup khi DB offline |
| `API_DB_POOL_MAX` | `8` | Số kết nối tối đa cho **mỗi worker** |
| `API_DB_POOL_TIMEOUT` | `3` | Giây chờ lấy kết nối |
| `API_DB_CONNECT_TIMEOUT` | `3` | Giây chờ mở kết nối PostgreSQL |
| `API_DB_STATEMENT_TIMEOUT_MS` | `5000` | Giới hạn thời gian mỗi câu SQL |
| `API_CORS_ORIGINS` | rỗng | Các origin cách nhau bằng dấu phẩy; mặc định cùng origin |

Pool giới hạn 64 request đang chờ. Lỗi kết nối/driver (`OperationalError`, `InterfaceError`),
timeout truy vấn và pool cạn/đóng trả 503 `DATABASE_UNAVAILABLE`.
Các lỗi SQL, quyền truy cập hay dữ liệu nội bộ (`ProgrammingError`, `DataError`,
`IntegrityError`...) trả 500 `INTERNAL_ERROR`, không bị gán thành lỗi kết nối.
Riêng `/health`, thiếu bảng serving hoặc hàm PostGIS là điều kiện chưa sẵn sàng và trả 503.
Định danh đầu vào chứa NUL bị từ chối bằng 422 trước khi lấy kết nối.
Log lỗi ứng dụng chỉ ghi loại ngoại lệ; HTTP response không chứa SQL, chuỗi kết nối,
mật khẩu hay chi tiết dữ liệu. Lỗi bất ngờ cũng trả 500 `INTERNAL_ERROR`.

Tham khảo chính thức: [psycopg connection pool](https://www.psycopg.org/psycopg3/docs/advanced/pool.html),
[FastAPI exception handlers](https://fastapi.tiangolo.com/tutorial/handling-errors/).
Thời điểm trả kết nối tuân theo [FastAPI dependency scope](https://fastapi.tiangolo.com/advanced/advanced-dependencies/#dependencies-with-yield-and-scope).

## Hành vi 7 endpoint

| Endpoint GET | Hành vi |
|---|---|
| `/health` | `{"status":"ok","database":"ready"}` hoặc 503 |
| `/api/models` | Model metadata đã có prediction; mặc định trước, rồi `model_id` |
| `/api/dates?model_id=...` | Ngày duy nhất tăng dần; rỗng có min/max `null` |
| `/api/grids` | GeoJSON FeatureCollection, Polygon từ `geom_4326`, `[lon,lat]`, theo `grid_id` |
| `/api/map?date=...&model_id=...` | Một giá trị/ô, theo `grid_id`, không làm tròn, không kèm geometry |
| `/api/grids/{grid_id}/history?model_id=...&start=...&end=...` | Hai đầu bao gồm; tối đa 366 ngày; tăng theo ngày |
| `/api/stations?date=...` | Trạm có `is_boundary=true`, LEFT JOIN số đo ngày; theo `station_id` |

Tên, tham số, trường JSON và đơn vị giữ theo v1. Dùng ID model đầy đủ từ `/api/models`,
URL encode; alias `baseline2` và `model_version` riêng không phải model ID.
Model/grid không tồn tại trả 404 `MODEL_NOT_FOUND`/`GRID_NOT_FOUND`.
Tham số thiếu, `model_id`/`grid_id` chứa NUL, ngày không đúng `YYYY-MM-DD`, ngày không tồn tại, `start > end`
hoặc khoảng tính cả hai đầu vượt 366 ngày trả 422 `INVALID_REQUEST`.
Nếu đồng thời model và grid đều không tồn tại, kiểm tra model trước.

Mọi danh sách rỗng trả 200, `count: 0`, `data: []` và giữ các trường ngữ cảnh riêng
của endpoint. `/api/grids` rỗng trả FeatureCollection với `features: []`.
`count` luôn bằng số phần tử trả về.

Quan trắc thiếu hoặc không hữu hạn trả `pm25_observed: null`, `has_observation: false`,
`is_valid_day: false`; số giờ giữ nguyên giá trị nullable từ DB, không suy ra số giờ giả.
Quan trắc 0.0 có thật vẫn là số đo. Số đo dưới 18 giờ hoặc QC=false vẫn được trả để UI
cảnh báo, với `has_observation: true`, `is_valid_day: false`.
Prediction không hữu hạn chuyển thành `null`, không xuất NaN/Infinity.
Tọa độ không hữu hạn, ngoài miền WGS84 hoặc vòng Polygon không khép kín bị từ chối
ở bước kiểm tra response (500), tránh gửi GeoJSON sai cho UI.

`/api/map` lọc trực tiếp `(date, model_id)` trên index `idx_predictions_date_model`
của Gói 1, chỉ lấy `grid_id, pm25_pred`, không join geometry và không đếm toàn bảng.
Tính duy nhất do PK `(grid_id,date,model_id)` bảo đảm. Không cache prediction để tránh
trả dữ liệu cũ trong thời gian import. Client tải/cache geometry riêng theo contract.
Mốc <200ms phải đo trên DB đã nạp đủ dữ liệu; tests mock không chứng minh hiệu năng.

## Kiểm thử

```powershell
# Unit Backend + HTTP integration với repository giả; không cần PostgreSQL
.\.venv\Scripts\python.exe -m pytest tests/unit/test_api.py tests/integration/test_api_http.py -q

# PostgreSQL thật, DB đã migration và import bởi Gói 1
# Gán TEST_DATABASE_URL bằng DSN test do nhóm cung cấp, không đưa mật khẩu vào Git.
$env:TEST_DATABASE_URL = $env:DATABASE_URL
.\.venv\Scripts\python.exe -m pytest tests/integration/test_api_postgres.py -m postgres -v -ra

# Toàn bộ regression tests (cần requirements.txt)
.\.venv\Scripts\python.exe run.py test
.\.venv\Scripts\python.exe run.py lint
```

`tests/unit/test_api.py`: gọi độc lập 7 route, validation, schema GeoJSON, số không
hữu hạn, cấu hình pool, ngoại lệ DB và SQL dùng bind parameters.
`tests/integration/test_api_http.py`: HTTP/ASGI đủ 7 route với repository mock,
rỗng, validation, model/grid sai, giới hạn ngày, QC, CORS, OpenAPI và lỗi DB.
Có tests qua repository thật với kết nối SQL giả để kiểm tra phân loại lỗi,
kết nối được tái sử dụng/trả lại và lỗi kết thúc giao dịch trước khi gửi response.
Regression tests NUL xác nhận 422 ngay cả khi chưa cấu hình DB.
Có thêm thử kết nối TCP bị từ chối bằng pool psycopg thật trên port local không listen;
đây là bằng chứng nhánh lỗi mạng, **không phải truy vấn thành công PostgreSQL thật**.

`tests/integration/test_api_postgres.py`: dùng DSN test tường minh, pool thật,
SQL/PostGIS thật, so sánh response cả 7 endpoint với SELECT trực tiếp; kiểm tra SRID,
geometry hợp lệ, không làm tròn, QC, input chứa SQL injection và session read-only.
Tests không tạo/xóa bảng, không seed, không import hay sửa dữ liệu. Chưa đặt DSN thì
9 tests được đánh dấu SKIPPED. Đã đặt DSN mà kết nối/schema lỗi thì FAIL;
tests cần prediction cũng FAIL khi bảng prediction rỗng.

Pytest tự phát hiện cả `tests/unit` và `tests/integration` (đã cập nhật pyproject).
Không lấy kết quả mock thay thế nghiệm thu PostgreSQL thật hoặc đối soát 3 điểm.

## Khác biệt tài liệu và việc phối hợp

1. README cũ ghi PostgreSQL/Docker/API là việc tiếp theo, nhưng nhánh hiện tại đã có
   migration, Compose DB và importer. `docs/schema.md` là schema Lakehouse, không
   phải các bảng phục vụ. API dùng schema thực tế trong `db/migrations/` và HANDOVER §4–5.
2. Importer gán `grids.is_boundary = centroid_in_hanoi`, trong khi HANDOVER §4.2
   gọi là cờ ô vùng biên. API trả nguyên cờ DB, không đảo nghĩa hay sửa Gói 1.
   `stations.is_boundary` biểu thị điểm trạm trong Hà Nội theo pipeline; API dùng
   cờ này để không bỏ trạm trong ô biên và không lấy trạm ngoài địa giới.
3. Không có cờ/manifest import-complete trong model_metadata. API chỉ có thể xác nhận
   đã tồn tại prediction, không chứng nhận đủ 138 partition. Gói 1/Gói 4 cần xác minh
   importer hoàn tất trước khi mở serving. Model có metadata nhưng chưa prediction
   không xuất hiện trong dropdown; gọi trực tiếp dates vẫn trả 200 rỗng theo v1.
4. `model_metadata.label` của importer thiếu chữ “(Khuyến nghị)” trong ví dụ v1;
   API giữ label DB và `is_default`, không tự hardcode nhãn mới.
5. Một số lệnh nguồn trong tài liệu không có file tương ứng trong clone này:
   `src/models/inference.py`, `scripts/verify_predictions.py`, `docs/DATA_DELIVERY.md`.
   Backend không phụ thuộc chúng; không sửa các phần pipeline ngoài Gói 2.

Gói 1: cung cấp DB/PostGIS đã migrate, bundle đã import, xác nhận cờ boundary và mức
hoàn tất model. Khi có dữ liệu, chạy bộ postgres và đối soát các cặp ô–ngày với Parquet.
Gói 3: lấy model ID động, encode URL, join map theo grid_id, dùng đơn vị µg/m³,
hiển thị thiếu số đo và QC đúng cờ; tải geometry riêng.
Gói 4: ghép Compose/Dockerfile, DSN nội bộ dùng hostname `db` thay `localhost`,
phân quyền đọc, cấu hình CORS/worker/pool, kiểm tra full-data và đo `/api/map` <200ms,
đối soát 3 điểm, backup/restore và end-to-end. Không thay đổi Compose trong Gói 2.

## Git và Pull Request

```powershell
git branch --show-current
# Phải là feature/package-2-api; dừng nếu đang ở nhánh khác.
git status --short
git diff --check
git diff --stat
git diff
git ls-files --others --exclude-standard

# Sau khi tự xem và xác nhận đúng phạm vi:
git add src/api tests/conftest.py tests/unit/test_api.py tests/integration/test_api_http.py tests/integration/test_api_postgres.py requirements-api.txt requirements-api-dev.txt requirements.txt pyproject.toml README.md docs/BACKEND.md docs/BACKEND_VALIDATION.md
git diff --cached --stat
git diff --cached --check
git diff --cached
git commit -m "feat(api): implement package 2 contract v1 with tests"
git push -u origin feature/package-2-api
```

Tạo Pull Request từ `feature/package-2-api` vào `develop`; đưa kết quả kiểm thử và
các mục chưa nghiệm thu vào mô tả. Không đưa `.env`, `.venv`, dữ liệu/model vào commit.
