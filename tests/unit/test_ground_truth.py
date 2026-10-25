"""
tests/unit/test_ground_truth.py
Kiểm thử tính toàn vẹn của chuỗi Ground Truth PM2.5 5 năm và mô hình Star Schema.
"""
import duckdb


def test_fact_ground_truth_exists_and_populated():
    con = duckdb.connect()
    count = con.sql("SELECT COUNT(*) FROM 'data/core/fct_ground_truth_daily.parquet'").fetchall()[0][0]
    assert count >= 5000, f"Bảng fact ground truth phải có ít nhất 5,000 dòng, thực tế: {count}"


def test_strict_18h_filter():
    con = duckdb.connect()
    invalid_days = con.sql(
        "SELECT COUNT(*) FROM 'data/core/fct_ground_truth_daily.parquet' WHERE valid_hours_count < 18"
    ).fetchall()[0][0]
    assert invalid_days == 0, f"Phải có 0 ngày dưới 18 giờ hợp lệ lọt vào bảng fact, thực tế: {invalid_days}"


def test_zero_orphan_dates():
    con = duckdb.connect()
    orphans = con.sql("""
        SELECT COUNT(*)
        FROM 'data/core/fct_ground_truth_daily.parquet' f
        LEFT JOIN 'data/core/dim_date.parquet' d ON f.date_id = d.date_id
        WHERE d.date_id IS NULL
    """).fetchall()[0][0]
    assert orphans == 0, f"Tất cả các bản ghi fact phải khớp với dim_date (0 orphans), thực tế: {orphans}"


def test_zero_orphan_grids():
    con = duckdb.connect()
    orphans = con.sql("""
        SELECT COUNT(*)
        FROM 'data/core/fct_ground_truth_daily.parquet' f
        LEFT JOIN 'data/core/dim_grid_1km.parquet' g ON f.grid_id = g.grid_id
        WHERE g.grid_id IS NULL
    """).fetchall()[0][0]
    assert orphans == 0, f"Tất cả các trạm đo phải map đúng vào ô lưới 1km dim_grid_1km, thực tế: {orphans}"


def test_zero_orphan_stations():
    con = duckdb.connect()
    orphans = con.sql("""
        SELECT COUNT(*)
        FROM 'data/core/fct_ground_truth_daily.parquet' f
        LEFT JOIN 'data/core/dim_station.parquet' s ON f.station_id = s.station_id
        WHERE s.station_id IS NULL
    """).fetchall()[0][0]
    assert orphans == 0, f"Tất cả các trạm trong bảng fact phải tồn tại trong dim_station, thực tế: {orphans}"


def test_temporal_coverage_5_years():
    con = duckdb.connect()
    dates = con.sql("""
        SELECT MIN(date_id), MAX(date_id)
        FROM 'data/core/fct_ground_truth_daily.parquet'
    """).fetchall()[0]
    min_date, max_date = dates[0], dates[1]
    assert min_date <= 20210131, f"Ngày bắt đầu phải trong tháng 01/2021, thực tế: {min_date}"
    assert max_date >= 20251201, f"Ngày kết thúc phải trong tháng 12/2025, thực tế: {max_date}"
