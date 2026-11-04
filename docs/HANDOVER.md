# Bàn giao triển khai hệ thống PM2.5 Hà Nội

Ngày lập: 04/11/2026. Điểm bắt đầu bàn giao: **đã hoàn thành phần dữ liệu và hai model; nhóm tiếp nhận triển khai ứng dụng end-to-end**.

Tài liệu này phân biệt phần đã có trong repo với phần cần triển khai. Các tên CLI/API đề xuất bên dưới chưa phải chức năng đã chạy được.

## 1. Những gì đã làm

### 1.1. Bài toán và pipeline dữ liệu

Dự án ước tính hồi cứu PM2.5 trung bình ngày trên lưới 1 km tại Hà Nội, đặc biệt ở những ô không có trạm quan trắc. Đây là tái tạo phân bố ô nhiễm lịch sử, không phải dự báo ngày mai. Kết quả tại ô lưới là ước tính của model, không phải số đo trực tiếp.

Pipeline đã tổ chức theo các lớp:

```text
OpenAQ + Google Earth Engine
             ↓
raw → staging → core → marts (Parquet + DuckDB)
             ↓
Đánh giá model → huấn luyện hai model cuối → lưu artifact
```

- OpenAQ cung cấp nhãn PM2.5 quan trắc tại trạm.
- Khí tượng gồm dữ liệu ERA5/ERA5-Land; vệ tinh gồm Sentinel-5P, MODIS AOD và VIIRS.
- Có bảng chiều ô lưới, ngày, trạm; bảng quan trắc ngày; mart đặc trưng toàn lưới và mart huấn luyện tại trạm.
- Ngày dữ liệu theo giờ Hà Nội (`Asia/Ho_Chi_Minh`); `date_id` có dạng `YYYYMMDD`.
- Theo metadata model đã lưu, tập huấn luyện hợp lệ có **7.290 dòng, 32 trạm, 30 ô và 1.801 ngày**, từ **01/01/2021 đến 30/09/2026**. Điều kiện lọc: `is_valid_day = 1 AND pm25_mean IS NOT NULL`.
- Số ngày có nhãn tại trạm khác số ngày của toàn bộ mart lưới. Khi triển khai phải đọc phạm vi và số dòng thực tế từ từng nguồn.

Chi tiết: [schema dữ liệu](schema.md), [báo cáo model](model_report.md), [README](../README.md).

### 1.2. Hai model đã có

| Model cho người dùng chọn | Đặc trưng | Artifact |
|---|---|---|
| Baseline 1 | Lịch, tọa độ, khí tượng và cờ missing hiện có; 27 feature | `outputs/models/baseline1/` |
| Baseline 2 | Toàn bộ Baseline 1 và feature vệ tinh hiện có; 34 feature | `outputs/models/baseline2/` |

`pm25_mean` từ OpenAQ là **nhãn**, không phải đầu vào cần có tại ô không có trạm. Tên model cũ có chữ OpenAQ không có nghĩa phải lấy PM2.5 quan trắc làm feature inference.

Mỗi thư mục model gồm `model.json`, `metadata.json`, `config.yaml` và `sample_verification_predictions.parquet`. Metadata hiện có ghi phiên bản `v2.0.0-retrospective`, seed `42`. Hai model cuối được huấn luyện trên toàn bộ dữ liệu hợp lệ; không dùng model của fold tốt nhất làm model cuối.

Đã tổ chức ba cách đánh giá:

| Phương pháp | Vai trò | Câu hỏi được kiểm tra |
|---|---|---|
| Spatial GroupKFold theo `grid_id`, 5 fold | Chính | Model hoạt động thế nào tại ô chưa có nhãn trong train? |
| Random KFold, 5 fold | Tham khảo | Kết quả khi chia ngẫu nhiên theo dòng ra sao? |
| Temporal: train trước 2026, validation từ 2026 | Bổ sung | Model hoạt động thế nào ở giai đoạn sau? |

Kết quả nằm trong `outputs/evaluation/` và [model_report.md](model_report.md). Temporal 2026 đã được khảo sát trước đó, không gọi là independent test hoàn toàn độc lập. Không cần chạy lại các đánh giá hoặc huấn luyện lại để triển khai ứng dụng.

### 1.3. Metadata và ranh giới bàn giao

- `src/models/registry.py` lưu bốn danh mục JSON: `evaluation_runs`, `fold_metrics`, `model_registry`, `artifact_registry` tại `outputs/registry/`.
- Luồng data/model không kết nối PostgreSQL, không cần driver database hoặc SQL, kể cả khi máy có biến môi trường database.
- PostgreSQL/PostGIS, Docker, API, inference độc lập và dashboard là phần nhóm tiếp nhận triển khai.
- Bản nháp SQL và code đồng bộ cũ được giữ cục bộ ngoài gói bàn giao, không phải dependency của repo.
- Cách nhận và kiểm tra data/model: [DATA_DELIVERY.md](DATA_DELIVERY.md).

## 2. Mục tiêu của phần triển khai

Người dùng mở dashboard, chọn ngày và một trong hai model để xem bản đồ PM2.5 ước tính; chọn một ô để xem lịch sử và bật lớp trạm để đối chiếu quan trắc.

```text
Mart đặc trưng + hai model đã lưu
              ↓ batch inference
Parquet dự đoán + manifest lần chạy
              ↓ nạp dữ liệu
PostgreSQL/PostGIS → FastAPI → React dashboard
```

Phạm vi đã chốt:

- Giữ Parquet/DuckDB cho dữ liệu xử lý và marts; PostgreSQL phục vụ truy vấn ứng dụng và registry.
- Dùng lại cả hai model đã lưu, giữ feature, thứ tự feature, xử lý missing và cắt dự đoán âm theo code hiện tại.
- Chưa bổ sung biến tĩnh, IDW, tuning hoặc thử nghiệm model mới.
- Tính trước kết quả theo batch; chọn ngày/model trên giao diện là truy vấn kết quả, không huấn luyện hay chạy lại toàn bộ inference.
- Triển khai local bằng Docker Compose trước. Triển khai cloud/public là phạm vi riêng cần thống nhất sau.
- Làm một luồng hoàn chỉnh trên vài ngày trước khi mở rộng toàn bộ lịch sử.

## 3. Gói dữ liệu cần bàn giao cho thành viên

| Đầu vào | Đường dẫn | Mục đích |
|---|---|---|
| Mart toàn lưới | `data/marts/mart_grid_daily_features.parquet` | Đầu vào inference |
| Mart tại trạm | `data/marts/mart_station_daily_training.parquet` | Đối chiếu dữ liệu/feature, không cần train lại |
| Ô lưới | `data/core/dim_grid_1km.parquet` | Polygon và mã ô |
| Ngày | `data/core/dim_date.parquet` | Ánh xạ ngày và `date_id` |
| Trạm | `data/core/dim_station.parquet` | Tọa độ, tên và liên kết ô |
| Quan trắc | `data/core/fct_station_daily.parquet` | PM2.5 đo tại trạm, kèm QC |
| Model | `outputs/models/baseline1/`, `outputs/models/baseline2/` | Inference và kiểm tra reload |
| Registry | `outputs/registry/` | Nạp metadata đã có |
| Đánh giá | `outputs/evaluation/` | Tham chiếu báo cáo chất lượng model |

Người bàn giao cung cấp đường dẫn kho chia sẻ, commit code, danh sách file, dung lượng và SHA-256. Các thư mục dữ liệu và `outputs/` đang bị Git ignore; clone repo không tự có các file này. Không đưa API key hoặc mật khẩu vào gói chia sẻ.

Có file `data/marts/pred_grid_daily_pm25.parquet` tại thời điểm kiểm tra. **Chưa xác minh nguồn model, phiên bản, schema và độ phủ của file này**; chỉ tái sử dụng nếu đối chiếu được với hai model cuối. Prediction trong `outputs/evaluation/` là kết quả đánh giá tại trạm, không thay thế prediction toàn lưới.

**Lưu ý CRS:** code dùng `EPSG:3405`. Kiểm tra CRS trong GeoParquet thực tế và chuyển tọa độ đúng sang `EPSG:4326` khi phục vụ bản đồ; không chỉ gán nhãn CRS mới cho tọa độ cũ.

## 4. Phân công đề xuất

Điền tên người nhận vào bảng trước khi bắt đầu. Một người có thể nhận nhiều phần nhưng mỗi phần cần một người chịu trách nhiệm chính.

| Gói | Người nhận | Trách nhiệm | Bàn giao cho |
|---|---|---|---|
| A — Inference | … | Nạp model, suy luận batch, xuất Parquet/manifest | B |
| B — PostgreSQL/PostGIS | … | Migration, registry, import geometry và prediction | C |
| C — Backend | … | FastAPI, truy vấn, validation và API contract | D |
| D — Frontend | … | Bản đồ, bộ lọc, lịch sử ô, trạm quan trắc | Nhóm |
| E — Docker và tích hợp | … | Compose, cấu hình, kiểm tra end-to-end, backup/restore | Nhóm |

Nếu nhóm có bốn người, có thể gộp B và E. Người đang phụ trách data/model hỗ trợ A và giải thích dữ liệu; không cần tự làm toàn bộ ứng dụng.

### A. Inference từ model đã lưu

**Công việc**

- Tạo CLI riêng nhận `baseline1/baseline2/both`, khoảng ngày và thư mục output; đọc metadata để lấy feature theo đúng thứ tự.
- Kiểm tra khóa ô–ngày, cột bắt buộc, kiểu dữ liệu và phạm vi ngày. Thiếu giá trị được xử lý theo model; thiếu hẳn cột bắt buộc phải báo lỗi rõ.
- Chạy theo batch/tháng, tránh nạp toàn bộ mart vào RAM nếu không cần.
- Ghi kết quả nguyên tử và manifest: run ID, checksum model/dữ liệu/cấu hình, khoảng ngày, số dòng, thời điểm và trạng thái hoàn thành.
- Resume chỉ khi nguồn và cấu hình khớp; partition chưa hoàn thành không được nạp vào serving.
- Kiểm tra prediction sau reload với mẫu kiểm chứng hiện có; không dùng `train` hay `train-final` để tạo kết quả triển khai.

**Đầu ra:** module inference, CLI có hướng dẫn thực tế, Parquet theo batch và manifest.

**Nghiệm thu:** cả hai model chạy được; kết quả hữu hạn và không âm; mỗi khóa có đúng một dòng; đếm được số dòng đầu vào/đầu ra; chạy lại không tạo bản sao trùng. Báo riêng số dòng mỗi model.

### B. PostgreSQL/PostGIS và nạp dữ liệu

**Công việc**

- Thiết kế migration mới cho registry và các bảng ứng dụng; bản bàn giao chưa chứa SQL.
- Triển khai đồng bộ đủ bốn bảng registry từ JSON, có CLI độc lập không chạy lại training. Ghi theo thứ tự quan hệ khóa ngoại và kiểm chứng số dòng từng bảng.
- Bổ sung driver PostgreSQL vào dependencies phù hợp. `requirements.txt` hiện chưa khai báo `psycopg`/`psycopg2`.
- Thiết kế `grids`, `stations`, `station_daily`, `grid_daily_predictions` và bảng theo dõi batch import hoặc tên tương đương.
- Lưu geometry một lần trong `grids`; không nhân bản polygon cho từng prediction.
- Dùng bulk load/COPY và transaction theo batch. Kiểm tra batch hoàn tất trước khi công bố cho API.
- Import lại cùng artifact phải không tạo trùng. Nếu checksum thay đổi trên cùng phiên bản/phạm vi, báo xung đột hoặc yêu cầu quy trình thay thế rõ ràng.
- Registry chỉ lưu đường dẫn/checksum model, không lưu binary model trong database. Đường dẫn phải dùng được trong môi trường chạy tương ứng.

**Schema tối thiểu cần thống nhất**

| Bảng | Khóa và nội dung |
|---|---|
| `grids` | PK `grid_id`, polygon và thông tin tọa độ |
| `stations` | PK `station_id`, tên, điểm tọa độ, `grid_id` nếu có |
| `station_daily` | Khóa `station_id + date`, PM2.5 quan trắc và cờ QC |
| `grid_daily_predictions` | Khóa `grid_id + date + model_id`, `pm25_pred`, `run_id` |
| Bảng import | Run/artifact checksum, phạm vi, số dòng, thời điểm, trạng thái |

Trong schema đề xuất này, `model_id` là khóa registry **đã bao gồm phiên bản**. Nếu triển khai dùng model alias thay cho khóa registry, khóa prediction phải thêm `model_version`.

Tạo index phục vụ truy vấn model–ngày và model–ô–khoảng ngày; index không gian nếu API truy vấn theo vùng bản đồ. Giữ thông tin QC của quan trắc, không biến ngày không hợp lệ thành giá trị bằng 0.

**Nghiệm thu:** đủ registry; khóa ngoại hợp lệ; geometry đúng vị trí Hà Nội; số dòng khớp Parquet; import hai lần không tăng số dòng; lỗi giữa batch không để lại dữ liệu được đánh dấu hoàn tất sai.

### C. Backend FastAPI

**API đề xuất — cần chốt JSON mẫu với frontend trước khi viết hai phía**

| API | Chức năng |
|---|---|
| `GET /health` | Trạng thái ứng dụng và kết nối DB, không lộ thông tin nhạy cảm |
| `GET /api/models` | Model/phiên bản thực sự có dữ liệu phục vụ |
| `GET /api/dates?model_id=...` | Ngày đã import hoàn tất cho model |
| `GET /api/grids` | Geometry ô, có thể cache/tải riêng |
| `GET /api/map?date=...&model_id=...` | PM2.5 theo ô của ngày/model đã chọn |
| `GET /api/grids/{grid_id}/history?model_id=...&start=...&end=...` | Chuỗi thời gian một ô |
| `GET /api/stations?date=...` | Trạm và quan trắc ngày kèm chất lượng dữ liệu |

API nhận ID chuẩn trả từ `/api/models`; frontend không tự ghép ID từ tên hiển thị. Quy định rõ kiểu ngày, `null`, lỗi 4xx và trường hợp không có dữ liệu. Không trả NaN/Infinity trong JSON.

**Công việc:** truy vấn tham số hóa, giới hạn khoảng ngày/phạm vi trả về, CORS đúng môi trường, connection pool và cấu hình qua biến môi trường. Tài khoản API chỉ cần quyền đọc bảng serving. Không chạy inference trong request bản đồ.

**Nghiệm thu:** đọc được dữ liệu thật từ PostgreSQL; hai model trả đúng kết quả; input sai được xử lý; ngày chưa import không xuất hiện như đã có dữ liệu; giá trị mẫu khớp nguồn Parquet.

### D. React dashboard

**Công việc**

- Bộ chọn ngày và model/phiên bản từ API; có thể mặc định Baseline 2 theo đánh giá chính hiện có nhưng luôn cho phép chọn Baseline 1.
- Bản đồ polygon ô lưới, chú giải màu thống nhất giữa ngày và model; đơn vị `µg/m³`.
- Tooltip hiển thị mã ô, ngày, model và PM2.5 ước tính; chọn ô mở biểu đồ lịch sử.
- Lớp trạm quan trắc bật/tắt, phân biệt rõ giá trị đo tại trạm với giá trị ước tính theo ô.
- Có trạng thái đang tải, lỗi, không có dữ liệu; hiển thị tốt trên laptop và màn hình nhỏ.
- Chỉ dùng ngày/model có dữ liệu; tránh response cũ ghi đè lựa chọn mới khi người dùng đổi bộ lọc nhanh.
- Không gọi nồng độ PM2.5 là AQI, không coi chênh lệch hai model là khoảng bất định. Basemap cần attribution và cấu hình token nếu nhà cung cấp yêu cầu.

**Nghiệm thu:** thao tác với API thật; chọn ngày/model đổi đúng dữ liệu; lịch sử đúng ô; cùng giá trị dùng cùng màu; không còn dữ liệu giả trong luồng nghiệm thu.

### E. Docker, vận hành và tích hợp

**Công việc**

- Tạo Compose cho `db` (PostgreSQL/PostGIS), `api`, `frontend`; tác vụ inference/import chạy một lần khi gọi, không tự train mỗi lần khởi động.
- Tạo Dockerfile cần thiết, `.dockerignore`, file cấu hình mẫu không chứa secret và hướng dẫn PowerShell.
- Database có named volume, healthcheck; backend xử lý DB chưa sẵn sàng. Mount artifact/dữ liệu đầu vào read-only khi phù hợp.
- Ghi rõ kết nối từ Windows (`localhost:<cổng host>`) và từ container (`db:5432`). Trình duyệt phải gọi URL API truy cập được từ máy người dùng, không gọi hostname nội bộ `api` của Docker.
- Cài dependencies với phiên bản được ghi nhận; không đóng gói cả data lake, `.env` hoặc `.git` vào image.
- Tạo quy trình migration rõ ràng, backup bằng `pg_dump` và kiểm tra restore trên database riêng.
- Kiểm tra lại dữ liệu sau khi restart/recreate container với cùng named volume. Không dùng `down -v` trong hướng dẫn khởi động thông thường.

**Lưu ý repo:** `.env.example` đã có placeholder cho ingestion; bổ sung cấu hình mẫu khi triển khai dịch vụ. Compose đọc `.env` cho nội suy cấu hình không đồng nghĩa mọi process Python tự đọc file này; cần cấu hình truyền biến hoặc nạp dotenv rõ ràng.

**Đầu ra:** Compose/Dockerfile, cấu hình mẫu, hướng dẫn khởi động/dừng, import, backup/restore và URL truy cập thực tế.

**Nghiệm thu:** thành viên khác chạy lại được từ repo và gói dữ liệu bàn giao; DB → API → UI hoạt động; dữ liệu còn sau restart; restore đã được thử và ghi kết quả.

## 5. Hợp đồng dữ liệu giữa các phần

Parquet prediction đề xuất:

| Trường | Quy ước |
|---|---|
| `grid_id` | Mã ô nguyên gốc, không tự tạo lại |
| `date` | Ngày lịch địa phương, không tự dịch thành ngày UTC khác |
| `model_id` | ID đầy đủ lấy từ metadata registry |
| `model_version` | Phiên bản từ metadata, kiểm tra nhất quán với ID |
| `pm25_pred` | Số hữu hạn không âm, đơn vị µg/m³ |
| `run_id` | Lần inference để truy vết |

ID hiện có:

```text
Baseline_1_OpenAQ_Meteo:v2.0.0-retrospective
Baseline_2_OpenAQ_Meteo_Sat:v2.0.0-retrospective
```

`baseline1` và `baseline2` có thể làm alias CLI/giao diện, nhưng phải ánh xạ tường minh sang ID đầy đủ. Hai model cùng chuỗi phiên bản nên không được chỉ dùng `model_version` làm khóa model.

Nhóm A và B chốt schema prediction; B và C chốt schema truy vấn; C và D chốt JSON mẫu gồm cả dữ liệu hợp lệ, rỗng và lỗi. Ghi hợp đồng đã thống nhất vào repo trước khi triển khai song song.

## 6. Thứ tự triển khai và mốc nghiệm thu

### Mốc 0 — Nhận bàn giao

- [ ] Điền người phụ trách, thống nhất commit code và nơi chia sẻ artifact.
- [ ] Kiểm tra đủ mart, geometry, hai model, metadata và checksum.
- [ ] Chốt schema prediction, ID model và JSON API mẫu.
- [ ] Chọn vài ngày thực sự có trong mart làm phạm vi tích hợp ban đầu.

### Mốc 1 — Luồng nhỏ chạy hoàn chỉnh

- [ ] A xuất prediction cho cả hai model trên khoảng ngày đã chọn.
- [ ] B/E dựng DB, áp dụng migration, nạp registry, geometry và prediction.
- [ ] C truy vấn được dữ liệu thật qua API.
- [ ] D hiển thị được bản đồ và lịch sử ô từ API.
- [ ] Đối chiếu một số khóa ô–ngày–model xuyên suốt Parquet → DB → API → UI.
- [ ] Thử import lại, input sai, ngày rỗng và restart container.

B/E có thể dựng DB trong lúc A làm inference. C làm theo schema/fixture đã chốt; D làm theo JSON mẫu. Khi tích hợp phải thay fixture bằng dữ liệu thật.

### Mốc 2 — Mở rộng dữ liệu và bàn giao vận hành

- [ ] Chạy batch cho phạm vi lịch sử thống nhất, có resume và thống kê độ phủ.
- [ ] Đối soát số dòng riêng từng model; không mặc định số dòng lý thuyết là số dòng thực tế.
- [ ] Kiểm tra tốc độ truy vấn/render với lượng dữ liệu thật, ghi thời gian và cấu hình máy.
- [ ] Thử backup/restore, hoàn thiện tài liệu và báo cáo cuối.

## 7. Kiểm thử và phối hợp Git

- Mỗi gói một issue và nhánh riêng; PR nêu đầu vào, đầu ra, cách chạy và bằng chứng kiểm thử.
- Chỉ định người tổng hợp thay đổi ở `run.py`, dependencies, Compose và README để tránh sửa đè.
- Giữ các thay đổi chưa commit của người khác; không xóa dữ liệu nguồn hoặc artifact cũ để làm sạch repo.
- Kiểm thử có ý nghĩa: inference/reload, feature order, import idempotent, transaction thất bại, hai model cùng version, API ngày rỗng, geometry/CRS và UI đổi bộ lọc.
- Dùng database kiểm thử riêng; không rollback/xóa bảng dữ liệu làm việc để chạy test.
- Chạy `python run.py lint` và `python run.py test` cho phần Python; thêm và ghi rõ lệnh integration test/frontend test thực tế khi được triển khai.
- Các lệnh `train`, `train-final`, `evaluate` đang có nhưng không thuộc luồng triển khai thông thường. Lệnh inference/import/registry sync độc lập cần được bổ sung và tài liệu hóa.

## 8. Báo cáo bắt buộc khi hoàn thành

Mỗi người cập nhật issue/PR theo mẫu:

```text
Gói công việc / Người thực hiện:
Commit hoặc PR:

1. Đã triển khai:
2. File tạo mới / chỉnh sửa:
3. Đầu vào và đầu ra thực tế:
4. Cách cấu hình và lệnh chạy:
5. Kiểm thử đã chạy, kết quả và bằng chứng:
6. Phần chưa làm / lỗi còn lại / phụ thuộc:
7. Hướng dẫn cho người nhận tích hợp:
```

Người phụ trách tích hợp tạo `docs/end_to_end_report.md` sau khi triển khai, gồm:

- Kiến trúc cuối cùng, chức năng hoạt động và URL truy cập.
- Phạm vi ngày, số ô, số prediction từng model, model ID/version và checksum nguồn.
- Migration đã áp dụng, số bản ghi từng bảng registry và serving.
- Lệnh khởi động, inference, import, kiểm tra, backup/restore đã dùng thực tế.
- Kết quả đối soát, kiểm thử tích hợp và ảnh giao diện chạy với dữ liệu thật.
- Danh sách file thay đổi, hạn chế còn lại và cách tái tạo trên máy khác.

**Không đánh dấu end-to-end hoàn thành chỉ vì có code hoặc unit test chạy qua.** Cần chứng minh dữ liệu từ model đã lưu đi qua database và API đến giao diện; phần chưa kiểm tra phải ghi rõ.
