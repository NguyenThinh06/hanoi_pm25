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
# Hai origin React này đã là mặc định; có thể thay bằng origin triển khai thực tế.
$env:API_CORS_ORIGINS = "http://localhost:5173,http://localhost:3000"
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
| `API_CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Các origin cách nhau bằng dấu phẩy; giá trị khai báo thay thế toàn bộ mặc định, rỗng để tắt CORS |
| `API_CACHE_TTL_SECONDS` | `300` | TTL cache dates/grids theo giây; `0` tắt cache; phải hữu hạn, không âm |

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

## Frontend React và CORS

Frontend chạy tại `http://localhost:5173` hoặc `http://localhost:3000` được phép gọi
API mặc định. CORS chỉ cho GET và các header Accept/Content-Type; preflight OPTIONS
được middleware xử lý, không thêm endpoint nghiệp vụ hay thay OpenAPI v1.
Origin khác không có `Access-Control-Allow-Origin`; preflight bị từ chối bằng 400.
CORS là chính sách trình duyệt, không phải cơ chế đăng nhập/chặn HTTP client.

```javascript
// .env.local của Frontend: VITE_API_BASE_URL=http://localhost:8000
const base = import.meta.env.VITE_API_BASE_URL;
const query = new URLSearchParams({ model_id: selectedModelId });
const response = await fetch(`${base}/api/dates?${query}`);
const body = await response.json();
if (!response.ok) throw new Error(body.error.message);
```

Khi triển khai, đặt `API_CORS_ORIGINS=https://dashboard.example.com` qua environment
của Backend, không dùng wildcard. Biến môi trường ưu tiên hơn `.env`; chuỗi rỗng
tắt middleware. `http://127.0.0.1:5173` khác `http://localhost:5173`, không tự động được
cho phép: nếu nhóm dùng địa chỉ đó, thêm rõ vào danh sách phân cách bằng dấu phẩy.
Origin không có đường dẫn hoặc dấu `/` cuối; khởi động lại API sau khi đổi cấu hình.

## Cache RAM cho dates và grids

`src/api/cache.py` dùng OrderedDict/LRU, Lock và đồng hồ monotonic; không thêm
dependency. Khóa dates là `(dates, model_id)` đầy đủ; grids dùng một khóa chung
cho toàn bộ FeatureCollection. Cache chỉ chứa bytes JSON bất biến đã được kiểm tra
bằng DatesResponse/GridsResponse; không chứa repository, cursor, connection hay
transaction. Mỗi lần trả tạo Response mới, nên header CORS và dữ liệu không bị sửa chéo.

Chọn lớp cache nhỏ thay `@lru_cache` vì cần TTL, giới hạn byte và chỉ công bố cache
sau khi dependency trả connection thành công. Nếu validation, truy vấn hoặc kết thúc
transaction lỗi, dữ liệu chờ ghi bị bỏ. Không cache 404/422/500/503. Kết quả rỗng 200
được cache; `/health`, `/api/models`, `/api/map`, `/history`, `/api/stations` không cache.
Thứ tự kết thúc dependency theo [FastAPI dependencies with yield](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/).

Giới hạn mỗi app/worker: 129 entry (dư chỗ cho một GeoJSON và các model), 32 MiB tổng
payload JSON và khóa UTF-8; overhead đối tượng Python và response đang xử lý không nằm
trong mức 32 MiB này. Entry quá lớn không được lưu, response vẫn trả bình thường.
Entry ít dùng nhất bị loại khi chạm giới hạn. TTL mặc định 300 giây tính từ lúc bắt đầu
load, không kéo dài khi đọc cache. Hết hạn thì request tiếp theo truy vấn lại DB.
Các request đồng thời khi cache chưa có có thể cùng truy vấn; Lock bảo vệ cấu trúc RAM,
không giữ khóa trong lúc chạy SQL. Chưa đo hiệu năng trên 3.610 ô hoặc production.

**Sau import/cập nhật/xóa dữ liệu Gói 1:** chờ import commit xong rồi khởi động lại
**tất cả worker/container API** để bỏ cache ngay, hoặc chấp nhận tối đa TTL dữ liệu cũ
tính từ lần load cuối. Nếu vẫn phục vụ khi import chưa xong, cache có thể chụp dữ liệu
chưa đầy đủ; Gói 4 nên chỉ mở serving sau khi import hoàn tất. Cache riêng mỗi process,
không có Redis/shared cache hay cơ chế tự phát hiện importer. Có thể tắt cache bằng
`API_CACHE_TTL_SECONDS=0` khi đối soát dữ liệu.

`app.state.response_cache.clear()` dùng được **trong process đang phục vụ** (tests hoặc
hook nội bộ); lệnh Python từ terminal khác không xóa cache của Uvicorn đang chạy.
Không thêm endpoint xóa cache. Clear cũng chặn request đang tải dở ghi lại dữ liệu cũ.
Nếu DB mất kết nối khi cache còn hiệu lực, hai endpoint có thể trả dữ liệu đã cache;
`/health` vẫn truy vấn DB và trả 503. Khi cache hết hạn, DB vẫn lỗi thì trả 503,
không kéo dài TTL để phục vụ dữ liệu cũ. Model bị xóa có thể còn trong dates đến lần
làm mới; restart sau thay đổi danh mục nếu cần hiệu lực ngay.

## Container Backend và tích hợp Gói 4

`Dockerfile` dùng Python 3.12 slim, WORKDIR `/app`, chỉ cài `requirements-api.txt` và
copy `src/__init__.py`, `src/api/`. Chạy UID/GID 10001 không phải root, Uvicorn
`0.0.0.0:8000`, không reload. `.dockerignore` dùng allowlist để loại `.git`, `.venv`,
`.env*`, dữ liệu, model, tests và artifacts khỏi build context. Nếu Gói 4 thêm Dockerfile
cho dịch vụ khác, cần dùng context hoặc ignore riêng phù hợp.

```powershell
docker build -t hanoi-pm25-api:local .
# Smoke khi chưa có DB: /docs 200, /health 503 DATABASE_UNAVAILABLE là kết quả dự kiến.
docker run --rm -d --name hanoi-pm25-api-smoke -p 127.0.0.1:8000:8000 hanoi-pm25-api:local
curl.exe -i http://localhost:8000/docs
curl.exe -i http://localhost:8000/health
docker stop hanoi-pm25-api-smoke
```

Khi chạy thật, truyền biến môi trường lúc run; `-e DATABASE_URL` lấy giá trị đã được
đặt trong shell mà không ghi mật khẩu vào lệnh/Dockerfile. Với PostgreSQL trong cùng
Docker network, hostname phải là tên service DB (`db` trong Compose hiện tại), port 5432.

```powershell
# DATABASE_URL đã được cấu hình bằng DSN do nhóm cung cấp, có hostname đúng network.
docker run --rm --name hanoi-pm25-api --network hanoi_pm25_default -p 8000:8000 -e DATABASE_URL -e API_CORS_ORIGINS=http://localhost:5173,http://localhost:3000 -e API_CACHE_TTL_SECONDS=300 hanoi-pm25-api:local
```

Tên network trên chỉ là ví dụ mặc định, cần kiểm tra tên project/network thực tế.
Ví dụ service **để Gói 4 tự ghép**, chưa sửa `docker-compose.yml`:

```yaml
services:
  api:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: ${API_DATABASE_URL:?Set a PostgreSQL DSN using host db}
      API_CORS_ORIGINS: ${API_CORS_ORIGINS:-http://localhost:5173,http://localhost:3000}
      API_CACHE_TTL_SECONDS: ${API_CACHE_TTL_SECONDS:-300}
    depends_on:
      db:
        condition: service_healthy
```

`API_DATABASE_URL` là biến đầu vào cho ví dụ Compose, được ánh xạ sang DATABASE_URL
trong container; đặt local và không commit. `localhost` trong container API là chính
container API, không phải DB. DB healthy chỉ xác nhận DB lên, không xác nhận đã migrate/
import. Sau khi cập nhật dữ liệu, Gói 4 có thể restart service `api` sau khi đã tích hợp.
Máy triển khai hiện chưa có Docker CLI: Dockerfile mới chỉ được kiểm tra tĩnh,
**chưa build image/chạy container**. Cần Gói 4 thực hiện các lệnh smoke trên.

## Kiểm thử

```powershell
# Unit Backend + HTTP integration với repository giả; không cần PostgreSQL
.\.venv\Scripts\python.exe -m pytest tests/unit/test_api.py tests/unit/test_api_cache.py tests/integration/test_api_http.py -q

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
`tests/unit/test_api_cache.py` kiểm tra TTL/LRU, giới hạn byte, concurrency, clear,
payload bất biến và cấu hình. HTTP tests bổ sung CORS preflight, cache hit không lấy
connection, tách model, lỗi query/transaction không cache, refresh và cô lập từng app.
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
git add .env.example .dockerignore Dockerfile src/api/cache.py src/api/config.py src/api/main.py src/api/routes.py tests/unit/test_api.py tests/unit/test_api_cache.py tests/integration/test_api_http.py docs/BACKEND.md docs/BACKEND_VALIDATION.md
git diff --cached --stat
git diff --cached --check
git diff --cached
git commit -m "feat(api): add React CORS defaults, bounded RAM cache and Docker image"
git push -u origin feature/package-2-api
```

Tạo Pull Request từ `feature/package-2-api` vào `develop`; đưa kết quả kiểm thử và
các mục chưa nghiệm thu vào mô tả. Không đưa `.env`, `.venv`, dữ liệu/model vào commit.
