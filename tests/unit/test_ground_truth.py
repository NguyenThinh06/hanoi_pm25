"""
tests/unit/test_ground_truth.py
Kiểm thử quy tắc làm sạch QC chuỗi giờ, gom ngày nghiêm ngặt >= 18h,
và tính toàn vẹn của mô hình Star Schema Ground Truth.
"""
from __future__ import annotations

import os

import duckdb
import numpy as np
import polars as pl
import pytest

from src.features.qc_hourly_stations import detect_hampel_outliers

LAKEHOUSE_FACT_PATH = "data/core/fct_ground_truth_daily.parquet"
HAS_LAKEHOUSE_DATA = os.path.exists(LAKEHOUSE_FACT_PATH) and (os.getenv("CI") != "true")


# =====================================================================
# 1. UNIT TESTS: Kiểm thử logic làm sạch với Mock Data (Chạy trên mọi môi trường / CI)
# =====================================================================

def test_hampel_outlier_detection_logic():
    """Kiểm tra bộ lọc Hampel phát hiện chính xác ngoại lai cục bộ."""
    # Chuỗi đo bình thường quanh 30 µg/m³, có 1 đột biến 180 µg/m³ ở vị trí index 4
    series = np.array([25.0, 32.0, 28.0, 35.0, 180.0, 30.0, 27.0, 34.0], dtype=np.float64)
    outliers = detect_hampel_outliers(series, window_size=5, n_sigmas=3.0)
    assert outliers[4] == 1, "Điểm đột biến 180.0 phải bị gán cờ ngoại lai Hampel!"
    assert outliers[0] == 0, "Điểm bình thường 30.0 không được bị gán cờ ngoại lai!"


def test_qc_hourly_flag_rules():
    """Kiểm thử quy tắc phân tầng cờ QC giờ: âm (1), cực trị (2), kẹt số (3)."""
    vals = np.array([-5.0, 1200.0, 45.0, 45.0, 45.0, 45.0, 45.0, 45.0, 30.0])
    flags = np.zeros(len(vals), dtype=np.int32)

    # 1. Âm
    flags[vals < 0] = 1
    # 2. Vượt ngưỡng vật lý
    flags[vals > 1000] = 2
    # 3. Flatline >= 6 giờ
    for i in range(5, len(vals)):
        window = vals[i - 5 : i + 1]
        if len(set(window)) == 1 and not np.isnan(window[0]):
            flags[i - 5 : i + 1] = 3

    assert flags[0] == 1, "Giá trị âm phải có cờ qc_flag = 1"
    assert flags[1] == 2, "Giá trị > 1000 phải có cờ qc_flag = 2"
    assert flags[5] == 3, "Kẹt số liên tục >= 6h phải có cờ qc_flag = 3"
    assert flags[8] == 0, "Bản ghi hợp lệ phải có cờ qc_flag = 0"


def test_strict_18h_aggregation_logic(tmp_path):
    """Kiểm thử quy tắc Quality Gate nghiêm ngặt >= 18h hợp lệ/ngày."""
    con = duckdb.connect()

    # Giả lập 2 trạm-ngày:
    # Trạm A: Ngày 2024-01-01 có 20 giờ hợp lệ (qc_flag=0) và 4 giờ lỗi (qc_flag=1) -> ĐẠT
    # Trạm B: Ngày 2024-01-01 chỉ có 12 giờ hợp lệ (qc_flag=0) và 12 giờ lỗi (qc_flag=1) -> RỚT
    records = []
    for h in range(24):
        # Station A
        flag_a = 0 if h < 20 else 1
        records.append({
            "station_id": "st_A", "date_actual": "2024-01-01", "date_id": 20240101,
            "pm25": 40.0, "qc_flag": flag_a
        })
        # Station B
        flag_b = 0 if h < 12 else 1
        records.append({
            "station_id": "st_B", "date_actual": "2024-01-01", "date_id": 20240101,
            "pm25": 50.0, "qc_flag": flag_b
        })

    mock_df = pl.DataFrame(records)
    mock_file = str(tmp_path / "mock_hourly.parquet").replace("\\", "/")
    mock_df.write_parquet(mock_file)

    query = f"""
    SELECT 
        station_id,
        date_id,
        COUNT(*) FILTER (WHERE qc_flag = 0) AS valid_hours_count,
        CASE WHEN COUNT(*) FILTER (WHERE qc_flag = 0) >= 18 THEN 1 ELSE 0 END AS is_valid_day
    FROM read_parquet('{mock_file}')
    GROUP BY station_id, date_id
    ORDER BY station_id
    """
    res = con.sql(query).pl()
    st_a = res.filter(pl.col("station_id") == "st_A").to_dicts()[0]
    st_b = res.filter(pl.col("station_id") == "st_B").to_dicts()[0]

    assert st_a["valid_hours_count"] == 20
    assert st_a["is_valid_day"] == 1, "Trạm A có 20h hợp lệ phải được công nhận (is_valid_day = 1)"

    assert st_b["valid_hours_count"] == 12
    assert st_b["is_valid_day"] == 0, "Trạm B chỉ có 12h hợp lệ phải bị loại (is_valid_day = 0)"


# =====================================================================
# 2. INTEGRATION TESTS: Kiểm thử Lakehouse thực tế (Chạy khi có file dữ liệu cục bộ)
# =====================================================================

@pytest.mark.skipif(not HAS_LAKEHOUSE_DATA, reason="Lakehouse Parquet data not in Git (Offline CI mode)")
def test_fact_ground_truth_exists_and_populated():
    con = duckdb.connect()
    count = con.sql("SELECT COUNT(*) FROM 'data/core/fct_ground_truth_daily.parquet'").fetchall()[0][0]
    assert count >= 5000, f"Bảng fact ground truth phải có ít nhất 5,000 dòng, thực tế: {count}"


@pytest.mark.skipif(not HAS_LAKEHOUSE_DATA, reason="Lakehouse Parquet data not in Git (Offline CI mode)")
def test_strict_18h_filter():
    con = duckdb.connect()
    invalid_days = con.sql(
        "SELECT COUNT(*) FROM 'data/core/fct_ground_truth_daily.parquet' WHERE valid_hours_count < 18"
    ).fetchall()[0][0]
    assert invalid_days == 0, f"Phải có 0 ngày dưới 18 giờ hợp lệ lọt vào bảng fact, thực tế: {invalid_days}"


@pytest.mark.skipif(not HAS_LAKEHOUSE_DATA, reason="Lakehouse Parquet data not in Git (Offline CI mode)")
def test_zero_orphan_dates():
    con = duckdb.connect()
    orphans = con.sql("""
        SELECT COUNT(*)
        FROM 'data/core/fct_ground_truth_daily.parquet' f
        LEFT JOIN 'data/core/dim_date.parquet' d ON f.date_id = d.date_id
        WHERE d.date_id IS NULL
    """).fetchall()[0][0]
    assert orphans == 0, f"Tất cả các bản ghi fact phải khớp với dim_date (0 orphans), thực tế: {orphans}"


@pytest.mark.skipif(not HAS_LAKEHOUSE_DATA, reason="Lakehouse Parquet data not in Git (Offline CI mode)")
def test_zero_orphan_grids():
    con = duckdb.connect()
    orphans = con.sql("""
        SELECT COUNT(*)
        FROM 'data/core/fct_ground_truth_daily.parquet' f
        LEFT JOIN 'data/core/dim_grid_1km.parquet' g ON f.grid_id = g.grid_id
        WHERE g.grid_id IS NULL
    """).fetchall()[0][0]
    assert orphans == 0, f"Tất cả các trạm đo phải map đúng vào ô lưới 1km dim_grid_1km, thực tế: {orphans}"


@pytest.mark.skipif(not HAS_LAKEHOUSE_DATA, reason="Lakehouse Parquet data not in Git (Offline CI mode)")
def test_zero_orphan_stations():
    con = duckdb.connect()
    orphans = con.sql("""
        SELECT COUNT(*)
        FROM 'data/core/fct_ground_truth_daily.parquet' f
        LEFT JOIN 'data/core/dim_station.parquet' s ON f.station_id = s.station_id
        WHERE s.station_id IS NULL
    """).fetchall()[0][0]
    assert orphans == 0, f"Tất cả các trạm trong bảng fact phải tồn tại trong dim_station, thực tế: {orphans}"


@pytest.mark.skipif(not HAS_LAKEHOUSE_DATA, reason="Lakehouse Parquet data not in Git (Offline CI mode)")
def test_temporal_coverage_5_years():
    con = duckdb.connect()
    dates = con.sql("""
        SELECT MIN(date_id), MAX(date_id)
        FROM 'data/core/fct_ground_truth_daily.parquet'
    """).fetchall()[0]
    min_date, max_date = dates[0], dates[1]
    assert min_date <= 20210131, f"Ngày bắt đầu phải trong tháng 01/2021, thực tế: {min_date}"
    assert max_date >= 20251201, f"Ngày kết thúc phải trong tháng 12/2025, thực tế: {max_date}"
