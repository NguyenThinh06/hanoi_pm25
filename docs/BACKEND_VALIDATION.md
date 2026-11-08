# Báo cáo kiểm chứng Gói 2 — 07/11/2026

Nhánh: `feature/package-2-api`. HEAD đầu đợt: `05060ce`
(`feat(api): implement package 2 contract v1 with validated error handling`).
Working tree sạch và không có file staged khi bắt đầu bổ sung CORS/cache/Dockerfile.
Bản bổ sung chỉ cập nhật working tree; người dùng cần tự review, stage và commit.
Không chuyển nhánh, commit, push, merge hay sửa index Git.
Không thay đổi migration, importer, dữ liệu, Frontend, Compose hoặc API Contract v1.

Kết quả cuối toàn dự án: **266 passed, 0 failed, 9 skipped, 1 warning**;
riêng Backend: **253 passed, 1 warning**. Lint, format và dependency check đạt.
Chưa nghiệm thu PostgreSQL/PostGIS thật hay Docker build.

## Bổ sung CORS, RAM cache và Dockerfile

- CORS mặc định đúng hai origin React localhost:5173/3000, environment thay thế mặc
  định (kể cả chuỗi rỗng). Preflight GET, origin được phép và bị từ chối có tests.
- RAM cache riêng mỗi app/worker: dates theo model_id, grids là toàn FeatureCollection.
  JSON đã validate được lưu dạng bytes; giới hạn 129 entry/32 MiB payload và khóa,
  TTL 300 giây (`API_CACHE_TTL_SECONDS=0` để tắt). Không giữ connection/repository,
  không cache lỗi; chỉ publish sau khi transaction kết thúc thành công.
- Clear/restart và TTL làm mới dữ liệu, payload không bị sửa chéo, LRU có Lock,
  request đang tải trước clear không ghi ngược dữ liệu cũ. Không cache 5 endpoint khác.
  Cache hit không lấy connection; DB outage có thể vẫn trả snapshot còn TTL của hai
  endpoint, `/health` vẫn kiểm tra DB. Xem hướng dẫn sau import trong BACKEND.md.
- Dockerfile Python 3.12 slim, runtime requirements riêng, COPY API rõ ràng, non-root,
  Uvicorn 0.0.0.0:8000 không reload. Dockerignore dùng allowlist tránh secret/artifacts.
  Không sửa Compose; chỉ đưa ví dụ cho Gói 4 với hostname DB `db`.

12 file tạo/sửa trong đợt này:

| File | Trạng thái và mục đích |
|---|---|
| `.env.example` | Sửa: CORS mặc định và TTL cache, không thêm secret |
| `.dockerignore` | Mới: giới hạn build context cho Backend |
| `Dockerfile` | Mới: container FastAPI |
| `src/api/cache.py` | Mới: cache TTL/LRU có giới hạn và publication theo request |
| `src/api/config.py` | Sửa: CORS mặc định, ưu tiên env, kiểm tra TTL |
| `src/api/main.py` | Sửa: cache riêng mỗi app, clear theo lifespan |
| `src/api/routes.py` | Sửa: dùng cache cho dates/grids sau validation và DB teardown |
| `tests/unit/test_api.py` | Sửa: gọi route với cache dependency |
| `tests/unit/test_api_cache.py` | Mới: unit cache và cấu hình |
| `tests/integration/test_api_http.py` | Sửa: HTTP CORS/cache/regression |
| `docs/BACKEND.md` | Sửa: Frontend, cache invalidation, Docker/Compose mẫu |
| `docs/BACKEND_VALIDATION.md` | Sửa: bằng chứng kiểm thử và giới hạn hiện tại |

Không thay đổi requirements, schema/SQL, migration, importer hoặc Frontend.

## Các lỗi đã sửa ở đợt review trước (đã có trong HEAD)

1. **Dependency pool:** extra `psycopg[pool]` không ràng buộc phiên bản riêng của pool.
   Thêm `psycopg-pool>=3.2.3,<4` để bảo đảm có `check_connection` và tham số `check`.
   Dependency pipeline vẫn giữ nguyên; tất cả ràng buộc trong cây requirements được
   kiểm tra với phiên bản đã cài và 13 tests cũ tiếp tục đạt.
2. **NUL và phân loại lỗi:** validation dùng chung cho model_id/grid_id chặn NUL
   bằng 422 `INVALID_REQUEST` trước khi lấy kết nối. Lỗi OperationalError/InterfaceError
   và pool trả 503; lỗi SQL/quyền/dữ liệu nội bộ trả 500 `INTERNAL_ERROR` với thông báo
   chung. Không trả SQL, chuỗi kết nối hay chi tiết dữ liệu cho client. Riêng health
   thiếu bảng serving/PostGIS vẫn trả 503 vì đó là kiểm tra readiness.
3. **Lỗi trả 200 quá sớm:** tái hiện được lỗi khi kết thúc giao dịch nhưng HTTP 200
   đã được gửi, do dependency mặc định kết thúc sau response. Đổi sang
   `Depends(..., scope="function")` để trả kết nối trước response; thêm ràng buộc
   FastAPI >= 0.121 cho tính năng này và regression tests trên cả 7 endpoint.

10 file đã thay đổi trong đợt sửa sau review trước:

| File | Thay đổi |
|---|---|
| `requirements-api.txt` | Ràng buộc pool riêng và FastAPI tối thiểu |
| `src/api/schemas.py` | Validator định danh không chứa NUL |
| `src/api/routes.py` | Áp dụng validator, scope dependency, khai báo schema lỗi 500 |
| `src/api/database.py` | Tách lỗi kết nối 503 và lỗi nội bộ 500 |
| `src/api/errors.py` | Dùng thông báo lỗi nội bộ chung |
| `src/api/repository.py` | Giữ xử lý thiếu schema/PostGIS riêng trong health |
| `tests/unit/test_api.py` | Regression tests validation và phân loại lỗi |
| `tests/integration/test_api_http.py` | Regression HTTP, lỗi lúc kết thúc giao dịch, vòng đời kết nối |
| `docs/BACKEND.md` | Cập nhật dependency, vòng đời kết nối và chính sách lỗi |
| `docs/BACKEND_VALIDATION.md` | Kết quả kiểm thử và trạng thái bàn giao hiện tại |

## Đã triển khai

Đủ 7 endpoint GET theo HANDOVER v1, pool psycopg có giới hạn/timeout và session đọc,
SQL tham số hóa, response schema/OpenAPI, lỗi 404/422/503 đồng nhất, lỗi nội bộ 500, CORS cấu hình.
Xử lý đúng khoảng lịch sử bao gồm hai đầu tối đa 366 ngày; không làm tròn prediction,
không gán quan trắc thiếu thành 0, không xuất NaN/Infinity, đơn vị µg/m³.

| Endpoint | Đã triển khai | Unit/HTTP | PostgreSQL thật |
|---|---|---|---|
| `/health` | Có | Đạt; cả nhánh DB unavailable | Chưa xác minh nhánh ready |
| `/api/models` | Có | Đạt | Chưa xác minh |
| `/api/dates` | Có | Đạt | Chưa xác minh |
| `/api/grids` | Có | Đạt GeoJSON WGS84 trên fixture | Chưa xác minh geometry nguồn |
| `/api/map` | Có | Đạt | Chưa xác minh dữ liệu/hiệu năng |
| `/api/grids/{grid_id}/history` | Có | Đạt; mốc 366/367 ngày | Chưa xác minh |
| `/api/stations` | Có | Đạt null/QC/0.0/không hữu hạn | Chưa xác minh |

## File tạo mới trong triển khai ban đầu

| File | Mục đích |
|---|---|
| `src/api/__init__.py` | Package Backend |
| `src/api/main.py` | App factory, lifespan, Swagger, CORS |
| `src/api/config.py` | Cấu hình môi trường và kiểm tra pool settings |
| `src/api/database.py` | Pool, kết nối chỉ đọc, dịch lỗi DB |
| `src/api/repository.py` | SELECT tham số hóa trên serving schema |
| `src/api/routes.py` | Chính xác 7 endpoint nghiệp vụ/health |
| `src/api/schemas.py` | Schema response, ngày ISO, GeoJSON, số hữu hạn |
| `src/api/errors.py` | Error envelope v1 |
| `tests/conftest.py` | Fixture tổng hợp và repository mock dùng chung |
| `tests/unit/test_api.py` | Unit tests route, SQL, pool, cấu hình, validation |
| `tests/integration/test_api_http.py` | HTTP/ASGI integration với mock và thử lỗi TCP thật |
| `tests/integration/test_api_postgres.py` | 9 tests DB/PostGIS thật, chỉ đọc, DSN tường minh |
| `requirements-api.txt` | Dependency runtime API độc lập pipeline |
| `requirements-api-dev.txt` | Runtime và công cụ kiểm thử API |
| `docs/BACKEND.md` | Hướng dẫn chạy, tích hợp, Git/PR, vấn đề phối hợp |
| `docs/BACKEND_VALIDATION.md` | Báo cáo kiểm chứng này |

File đã sửa trong triển khai ban đầu: `README.md` (liên kết hướng dẫn Backend), `requirements.txt` (include
bộ API/dev và bỏ khai báo dependency trùng), `pyproject.toml` (tìm integration tests,
khai báo markers). Không sửa test cũ hay mã pipeline.

## Môi trường và kết quả thực tế

Windows, Python **3.13.13** trong `.venv` local (được Git ignore).
FastAPI 0.162.0, Pydantic 2.14.3, psycopg 3.3.8, psycopg_pool 3.3.3,
Uvicorn 0.54.0, pytest 9.2.0, httpx 0.28.1.
Đã cài dependencies API và requirements toàn dự án từ lần triển khai trước.
Đợt bổ sung hiện tại không thêm dependency, không đổi dependency đã cài của pipeline.
Chưa chạy riêng trên Python 3.11/3.12 hoặc container Linux.

Lệnh Backend sau sửa:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/unit/test_api.py tests/unit/test_api_cache.py tests/integration/test_api_http.py -q -ra -p no:cacheprovider
```

Log: `253 passed, 1 warning in 7.12s` (212 tests Backend cũ và 41 tests mới).

Regression cuối được gọi bằng `pytest.main` với `-q -ra -p no:cacheprovider` và
`--basetemp` trỏ vào TemporaryDirectory ngoài repository. Đặt `PYTHONDONTWRITEBYTECODE=1`,
`PYTHONUTF8=1`; chạy ngoài sandbox để pytest ghi được thư mục tạm Windows.
Không đặt TEST_DATABASE_URL vì chưa có DB test được cung cấp. Lệnh tương đương
để chạy lại toàn bộ suite trong terminal của người dùng:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -ra -p no:cacheprovider
```

Log:

```text
266 passed, 9 skipped, 1 warning in 77.31s (0:01:17)
SKIPPED: Chưa có TEST_DATABASE_URL; không tuyên bố đã kiểm thử PostgreSQL thật.
WARNING: StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated.
```

Gồm 253 tests Backend và 13 tests cũ của dự án; 9 tests PostgreSQL thật skipped.
Kết quả trước đợt bổ sung này là 225 passed, 9 skipped. Warning còn lại là deprecation
của Starlette TestClient/httpx, không phải test thất bại; không ẩn warning thư viện.

Lần chạy regression đầu trong sandbox: 259 passed, 9 skipped, 7 setup errors do
`PermissionError [WinError 5]` khi pytest tạo thư mục tạm Windows; chưa chạy được 7 test
cũ cần tmp_path. Chạy lại cùng suite ngoài sandbox đã đạt kết quả 266 passed trên,
không sửa test/pipeline để né lỗi. Không chạy lệnh ghi/xóa dữ liệu PostgreSQL.

```powershell
.\.venv\Scripts\python.exe -B -m ruff check --no-cache src tests run.py
# All checks passed!
.\.venv\Scripts\python.exe -B -m ruff format --check --no-cache src/api tests/conftest.py tests/unit/test_api.py tests/unit/test_api_cache.py tests/integration
# 14 files already formatted
.\.venv\Scripts\python.exe -B -m pip check
# No broken requirements found.
git diff --check
# Không có lỗi whitespace
```

Smoke test thực tế tạo tiến trình `python -m uvicorn src.api.main:app` trên port
localhost tạm, gọi bằng HTTP thật, rồi dừng tiến trình:

```text
/docs                  200
/openapi.json          200 (đúng 7 paths)
OPTIONS /api/grids      200 cho hai origin mặc định; 400 cho https://untrusted.test
/health                503 DATABASE_UNAVAILABLE với CORS header cho origin hợp lệ
Uvicorn smoke passed; no database; process stopped.
```

Docker CLI không có (`shutil.which('docker')` trả None). Chỉ kiểm tra tĩnh Dockerfile,
allowlist, đường dẫn COPY và parse 10 file Python nguồn cần copy bằng grammar Python
3.12; không đồng nghĩa với chạy Python 3.12 thực tế. Chưa build image, cài dependency
trong image hay chạy container. Uvicorn smoke ở trên chạy trực tiếp trên Windows.

Tests đã chạy bao gồm response thành công/rỗng cho mọi danh sách, ngày sai/thiếu,
model/grid sai, alias/version không thay model_id, ngày đầu/cuối/366/367 ngày,
DB thiếu cấu hình và mất kết nối, lỗi pool và query, quan trắc null/QC/0.0,
GeoJSON và miền tọa độ, NaN/Infinity, URL encoding, CORS, OpenAPI, bind SQL.
Thử TCP connection-refused dùng psycopg pool thật, không dùng DB đang hoạt động.
Tests mới đi qua route/repository/lớp xử lý lỗi thật với kết nối SQL giả, phân biệt
503 và 500; xác nhận giải phóng kết nối khi lỗi query, dùng chung một kết nối/request
và trả lỗi kết thúc giao dịch trước response. Đây vẫn không phải PostgreSQL thật.

## Chưa thể nghiệm thu trên dữ liệu thật

- Không có `DATABASE_URL`, `TEST_DATABASE_URL` hoặc `.env` local trong phiên khảo sát.
- Khảo sát trước ghi nhận localhost:5432 chưa kết nối được và chưa có lệnh Docker/psql.
- Clone chỉ có source và ranh giới tham chiếu; chưa có bundle geometry/stations/predictions.
- Vì vậy 9 tests PostgreSQL thật SKIPPED; chưa chạy truy vấn PostGIS thành công,
  đối soát Parquet → DB → API → UI, đo SLA `/api/map` <200ms trên 15,15 triệu dòng,
  hoặc kiểm thử end-to-end với React.

Không có số liệu benchmark hay dữ liệu sản xuất giả. Trạng thái sẵn sàng bàn giao mã
Backend để commit/push lên nhánh riêng sau khi người dùng stage bản sửa mới;
nghiệm thu với dữ liệu thật cần Gói 1 cung cấp DB đã nạp. Cần CI xác nhận thêm
trên Linux/Python 3.12; chưa tuyên bố sẵn sàng merge/vận hành toàn hệ thống.

## Phối hợp và bước tiếp theo

- **Gói 1:** xác nhận `grids.is_boundary` (importer đang dùng centroid_in_hanoi),
  cung cấp DB migrated/imported, xác nhận đủ partition và nhãn model. Schema hiện
  không có import-complete marker; `/api/models` chỉ xác nhận có prediction, chưa
  chứng minh hoàn tất import. Chi tiết khác biệt nằm trong BACKEND.md.
- **Gói 3:** dùng model_id động/URL-encoded, join grid_id, đơn vị µg/m³, hiển thị
  quan trắc null và QC đúng cờ. Xác nhận origin để cấu hình CORS.
- **Gói 4:** ghép Docker/Compose, tài khoản SELECT, hostname DB nội bộ, pool/worker,
  chạy bộ PostgreSQL, đo hiệu năng và đối soát dữ liệu cùng Frontend.

Lệnh khởi động, kiểm thử PostgreSQL và lệnh tự commit/push/PR vào `develop` có trong
[BACKEND.md](BACKEND.md). Không có commit/PR nào được tự tạo trong phiên này.
