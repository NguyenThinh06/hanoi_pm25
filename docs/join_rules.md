Tầng 0: Dữ liệu gốc (data/raw/) — Có 4 nguồn độc lập
OpenAQ (raw/openaq/):
locations.json: Danh sách 43 trạm trong khung tọa độ Hà Nội. Mỗi trạm (location_id) chứa danh sách các sensors (mỗi sensor_id đo 1 thông số như pm25, pm10, no2, so2, co, co2, o3, temperature, relativehumidity).
hours/sensor_<id>_<year>.parquet: Chuỗi số đo theo giờ UTC của từng sensor_id. Lưu ý: trong file giờ này chỉ có sensor_id, chưa có station_id hay tên thông số.
Khí tượng GEE (raw/meteo/meteo_YYYY-MM.parquet):
Đã lấy từ Google Earth Engine đúng theo lưới 1 km (EPSG:3405) và ngày Hà Nội. Mỗi dòng là (grid_id, date) với đơn vị gốc của ERA5 (K, Pa, m).
Vệ tinh ngày GEE (raw/satellite/satellite_YYYY-MM.parquet):
Mỗi dòng là (grid_id, date) chứa trung bình ngày của 4 khí S5P (no2_trop, co, o3, so2) và aod047 (MODIS MAIAC nguyên gốc, chưa nhân 0.001).
Đèn đêm tháng GEE (raw/viirs/viirs_YYYY-MM.parquet):
Vì VIIRS là sản phẩm theo tháng, mỗi dòng là (grid_id, month) (ví dụ month = 2026-08-01).
Tầng 1: Bảng chiều — Dimensions (src/pipeline/build_dims.py)

Trước khi ghép bất kỳ dữ liệu nào, pipeline tạo 3 "trục chuẩn":

dim_grid_1km.parquet — Khóa chính: grid_id
Cắt ranh giới hanoi_boundary.geojson thành lưới 1 km × 1 km (EPSG:3405), giữ 3.610 ô có diện tích nằm trong Hà Nội 
>
0
>0.
dim_date.parquet — Khóa chính: date_id (YYYYMMDD)
Sinh 2.099 ngày từ 20210101 đến 20260930 kèm year, month, day_of_week, is_weekend, season.
dim_station.parquet — Khóa chính: station_id
Đọc locations.json, đổi tọa độ (lon, lat) của trạm sang mét (easting_m, northing_m).
Kiểm tra tọa độ thực của trạm có nằm trong đa giác Hà Nội hay không (is_boundary = boundary.covers(Point)).
Tính ô 1 km chứa trạm: nếu is_boundary = TRUE thì gán grid_id của ô đó (đây chính là cầu nối duy nhất giữa trạm mặt đất và ô lưới vệ tinh/khí tượng).
Tầng 2: Làm sạch — Staging (src/pipeline/build_staging.py)

Ở tầng này, mỗi nguồn tự làm sạch riêng, chỉ có duy nhất OpenAQ cần join:

stg_openaq_hourly.parquet — Khóa: (sensor_id, datetime_utc)
Vì file raw hours/*.parquet chỉ có sensor_id, ta lấy bảng danh mục sensors (trích từ locations.json, gồm sensor_id, station_id, parameter) rồi thực hiện:
Kiểu join: raw_hours INNER JOIN sensors USING (sensor_id)
Mục đích: Gắn station_id và tên thông số (pm25, no2, temperature...) vào từng dòng đo giờ, đồng thời loại bỏ các sensor không nằm trong 9 thông số cần lấy.
Đổi datetime_utc sang giờ Hà Nội (+7 giờ) để lấy date_id (YYYYMMDD) và hour_local (0..23), sau đó gắn cờ qc_flag (0: sạch, 1: ngoài ngưỡng vật lý, 2: kẹt số 
≥
6
≥6 giờ liên tiếp).
stg_meteo_daily.parquet — Khóa: (grid_id, date_id)
Gộp 69 file tháng raw/meteo/*.parquet, đổi date thành date_id = YYYYMMDD, đổi K -> °C, Pa -> hPa, m -> mm. (Không join).
stg_satellite_daily.parquet — Khóa: (grid_id, date_id)
Gộp 69 file tháng raw/satellite/*.parquet, đổi date thành date_id = YYYYMMDD, nhân aod047 * 0.001. (Không join).
stg_viirs_monthly.parquet — Khóa: (grid_id, month_id)
Gộp 68 file tháng raw/viirs/*.parquet, đổi month thành month_id = YYYYMM (ví dụ 202608). (Không join).
Tầng 3: Tổng hợp sự kiện cấp ngày — Core Facts (src/pipeline/build_facts.py)

Tầng này đưa mọi nguồn về cùng độ mịn thời gian là cấp ngày (date_id):

fct_station_daily.parquet — Khóa chính: (station_id, date_id)

Từ stg_openaq_hourly:
Bước A (Lọc): Chỉ giữ giờ sạch qc_flag = 0 và date_id nằm trong dim_date.
Bước B (Gộp cấp giờ): GROUP BY (station_id, parameter, date_id, hour_local) lấy avg(value) — để nếu 1 trạm có 2 sensor cùng đo PM2.5 trong 1 giờ thì gộp thành 1 giá trị duy nhất cho giờ đó.
Bước C (Gộp cấp ngày — Pivot các thông số thành cột): GROUP BY (station_id, date_id) để xoay từ dạng dọc (parameter) sang các cột ngang:
pm25_mean = tổng các giờ PM2.5 hợp lệ chia cho pm25_valid_hours.
Các khí khác tại trạm: pm10_aq, no2_aq, so2_aq, co_aq, co2_aq, o3_aq.
Khí tượng tại trạm: openaq_temperature, openaq_relativehumidity.
Bước D (Join lấy grid_id):
Kiểu join: Bảng ngày vừa gộp LEFT JOIN dim_station USING (station_id) để lấy cột grid_id của trạm.

fct_grid_meteo_daily.parquet — Khóa chính: (grid_id, date_id)

Kiểu join: stg_meteo_daily INNER JOIN dim_grid_1km USING (grid_id) INNER JOIN dim_date USING (date_id).
Mục đích: Đảm bảo 100% dòng khí tượng chỉ nằm trong đúng 3.610 ô Hà Nội và 2.099 ngày chuẩn, đồng thời tạo các cột cờ báo thiếu *_missing.

fct_grid_satellite_daily.parquet — Khóa chính: (grid_id, date_id)

Kiểu join 1: stg_satellite_daily s INNER JOIN dim_grid_1km USING (grid_id) INNER JOIN dim_date USING (date_id).
Kiểu join 2 (Ghép đèn đêm tháng vào từng ngày):
LEFT JOIN stg_viirs_monthly v ON s.grid_id = v.grid_id AND (s.date_id // 100) = v.month_id
Giải thích khóa (s.date_id // 100) = v.month_id: Ví dụ ngày 20260815 chia nguyên cho 100 ra 202608, khớp đúng với month_id = 202608 của VIIRS để gắn giá trị ánh sáng đêm tháng 8/2026 cho mọi ngày trong tháng 8/2026 của cùng grid_id đó. Dùng LEFT JOIN vì tháng 9/2026 chưa có ảnh VIIRS tháng thì các cột S5P và AOD của tháng 9 vẫn được giữ nguyên (cột VIIRS sẽ là NULL).
Tầng 4: Ghép bảng đặc trưng & huấn luyện — Marts (src/pipeline/build_marts.py)

Đây là nơi Khí tượng, Vệ tinh và Trạm mặt đất gặp nhau:

1. mart_grid_daily_features.parquet — Khóa chính: (grid_id, date_id) (7.577.390 dòng)

Bảng này dùng để suy luận (predict) bản đồ PM2.5 cho toàn bộ 3.610 ô lưới Hà Nội:

Join 1 (Tạo khung xương spine):
dim_grid_1km g CROSS JOIN dim_date d
Tạo ra mọi cặp (grid_id, date_id) (3.610 ô × 2.099 ngày = 7.577.390 dòng) kèm sẵn tọa độ ô (easting_m, northing_m) và lịch (date, year, month, season...).
Join 2 (Ghép khí tượng vào khung lưới):
spine s LEFT JOIN fct_grid_meteo_daily m USING (grid_id, date_id)
Join 3 (Ghép vệ tinh vào khung lưới):
LEFT JOIN fct_grid_satellite_daily sat USING (grid_id, date_id)
Tại sao dùng LEFT JOIN từ spine? Để không bao giờ bị mất bất kỳ ô–ngày nào kể cả khi một nguồn vệ tinh hay khí tượng bị khuyết dữ liệu ở ngày đó.
2. mart_station_daily_training.parquet — Khóa chính: (station_id, date_id) (9.203 dòng)

Bảng này dùng để huấn luyện mô hình (chứa nhãn pm25_mean của trạm ghép với đặc trưng của ô lưới 1 km chứa trạm đó):

Bắt đầu từ bảng nhãn trạm fct_station_daily f (lọc những ngày trạm có đo được PM2.5: WHERE f.pm25_mean IS NOT NULL AND f.grid_id IS NOT NULL):
INNER JOIN dim_station st ON f.station_id = st.station_id (kèm WHERE st.is_boundary = TRUE):
Lấy tên trạm, loại cảm biến (sensor_tier), và chặn hoàn toàn các trạm nằm ngoài ranh giới hành chính Hà Nội.
INNER JOIN dim_date d ON f.date_id = d.date_id:
Lấy trực tiếp các cột lịch (date, year, month, day_of_week, season...) từ dim_date để không bao giờ bị NULL lịch.
INNER JOIN dim_grid_1km gr ON f.grid_id = gr.grid_id:
Lấy trực tiếp tọa độ tâm ô (easting_m, northing_m) từ dim_grid_1km.
LEFT JOIN mart_grid_daily_features g ON f.grid_id = g.grid_id AND f.date_id = g.date_id:
Đây là phép nối không-thời gian quan trọng nhất: Trạm f nằm ở ô grid_id nào và vào ngày date_id nào thì lấy toàn bộ vector khí tượng (ERA5-Land + BLH) và vệ tinh (S5P + MODIS AOD + VIIRS) của đúng (grid_id, date_id) đó từ mart_grid_daily_features gắn vào dòng của trạm. (Nếu 2 trạm cùng nằm trong 1 ô 1 km vào cùng 1 ngày, cả 2 trạm vẫn được giữ thành 2 dòng riêng theo station_id và cùng nhận đặc trưng của ô đó).