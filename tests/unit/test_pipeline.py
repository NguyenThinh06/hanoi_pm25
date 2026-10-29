"""Unit tests cho toàn bộ pipeline dữ liệu PM2.5 Hà Nội."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd
import pyproj
import shapely

from src.common import config
from src.common.storage import copy_query, write_json, write_parquet
from src.ingest.fetch_openaq import load_sensors, year_windows
from src.pipeline.build_dims import (
    build_dim_date,
    build_dim_grid,
    build_dim_station,
    hanoi_season,
    point_to_grid_id,
)
from src.pipeline.build_facts import (
    grid_meteo_daily_sql,
    grid_satellite_daily_sql,
    station_daily_sql,
)
from src.pipeline.build_marts import grid_mart_sql, station_training_mart_sql
from src.pipeline.build_staging import (
    METEO_SQL,
    SATELLITE_SQL,
    VIIRS_SQL,
    openaq_hourly_sql,
)


def test_config_and_months():
    assert config.START_DATE == date(2021, 1, 1)
    assert config.END_DATE == date(2026, 9, 30)
    ms = config.months()
    assert len(ms) == 69  # 5 năm * 12 + 9 tháng năm 2026
    assert ms[0] == date(2021, 1, 1)
    assert ms[-1] == date(2026, 9, 1)
    assert config.OPENAQ_PARAMETERS == {
        "pm25": "pm25",
        "pm10": "pm10_aq",
        "no2": "no2_aq",
        "so2": "so2_aq",
        "co": "co_aq",
        "co2": "co2_aq",
        "o3": "o3_aq",
        "temperature": "openaq_temperature",
        "relativehumidity": "openaq_relativehumidity",
    }


def test_point_to_grid_and_season():
    assert point_to_grid_id(582922.26, 2327776.43) == "grid_582000_2327000"
    assert hanoi_season(1) == "winter"
    assert hanoi_season(4) == "spring"
    assert hanoi_season(7) == "summer"
    assert hanoi_season(9) == "autumn"


def test_year_windows_includes_utc_boundary():
    # 01/01/2021 00:00+07 = 31/12/2020 17:00 UTC -> phải có cửa sổ năm 2020 và tới năm 2026
    wins = year_windows(None, None)
    years = [w[0] for w in wins]
    assert years[0] == 2020
    assert years[-1] == 2026


def test_station_boundary_filter_in_border_cell(tmp_path: Path):
    """
    Ô biên [582000, 583000] x [2327000, 2328000] chỉ có nửa trái [582000, 582500] nằm trong ranh giới.
    - Trạm 101 ở x=582200 (trong ranh giới) -> is_boundary = True, grid_id = 'grid_582000_2327000'.
    - Trạm 102 ở x=582800 (cùng ô 1km nhưng ngoài ranh giới) -> is_boundary = False, grid_id = None.
    """
    boundary_path = tmp_path / "border.geojson"
    poly_utm = shapely.box(582100, 2327100, 582500, 2327900)
    gpd.GeoDataFrame({"name": ["Test"]}, geometry=[poly_utm], crs=config.GRID_CRS).to_crs("EPSG:4326").to_file(
        boundary_path, driver="GeoJSON"
    )

    dim_grid_path = tmp_path / "dim_grid.parquet"
    gdf_grid = build_dim_grid(boundary_path=boundary_path, out_path=dim_grid_path)
    assert list(gdf_grid["grid_id"]) == ["grid_582000_2327000"]

    to_wgs = pyproj.Transformer.from_crs(config.GRID_CRS, "EPSG:4326", always_xy=True)
    lon_in, lat_in = to_wgs.transform(582200, 2327500)
    lon_out, lat_out = to_wgs.transform(582800, 2327500)

    loc_path = tmp_path / "locations.json"
    write_json(
        {
            "locations": [
                {
                    "id": 101,
                    "name": "Inside Hanoi",
                    "isMonitor": True,
                    "coordinates": {"longitude": lon_in, "latitude": lat_in},
                    "sensors": [{"id": 1, "parameter": {"name": "pm25", "units": "ug/m3"}}],
                },
                {
                    "id": 102,
                    "name": "Outside Hanoi But Same Border Cell",
                    "isMonitor": False,
                    "coordinates": {"longitude": lon_out, "latitude": lat_out},
                    "sensors": [{"id": 2, "parameter": {"name": "pm25", "units": "ug/m3"}}],
                },
            ]
        },
        loc_path,
    )

    dim_station_path = tmp_path / "dim_station.parquet"
    df_st = build_dim_station(
        locations_path=loc_path,
        boundary_path=boundary_path,
        dim_grid_path=dim_grid_path,
        out_path=dim_station_path,
    ).set_index("station_id")

    assert bool(df_st.loc["openaq_101", "is_boundary"]) is True
    assert df_st.loc["openaq_101", "grid_id"] == "grid_582000_2327000"
    assert bool(df_st.loc["openaq_102", "is_boundary"]) is False
    assert pd.isna(df_st.loc["openaq_102", "grid_id"])


def test_end_to_end_sql_pipeline(tmp_path: Path):
    # 1. Tạo dim_grid và dim_date giả lập trong tmp_path
    dim_grid_path = tmp_path / "dim_grid_1km.parquet"
    dim_date_path = tmp_path / "dim_date.parquet"
    dim_station_path = tmp_path / "dim_station.parquet"

    write_parquet(
        pd.DataFrame(
            [
                {"grid_id": "grid_582000_2327000", "easting_m": 582500, "northing_m": 2327500},
                {"grid_id": "grid_583000_2327000", "easting_m": 583500, "northing_m": 2327500},
            ]
        ),
        dim_grid_path,
    )
    df_date = build_dim_date(dim_date_path)
    assert len(df_date) == 2099  # 01/01/2021 -> 30/09/2026
    assert int(df_date.date_id.max()) == 20260930

    # 2. Tạo locations.json và kiểm tra load_sensors
    loc_path = tmp_path / "locations.json"
    write_json(
        {
            "locations": [
                {
                    "id": 100,
                    "name": "Station A",
                    "isMonitor": True,
                    "coordinates": {"longitude": 105.8, "latitude": 21.048},
                    "sensors": [
                        {"id": 1, "parameter": {"name": "pm25", "units": "ug/m3"}},
                        {"id": 2, "parameter": {"name": "pm10", "units": "ug/m3"}},
                        {"id": 3, "parameter": {"name": "temperature", "units": "c"}},
                        {"id": 4, "parameter": {"name": "relativehumidity", "units": "%"}},
                        {"id": 5, "parameter": {"name": "no2", "units": "ug/m3"}},
                        {"id": 6, "parameter": {"name": "so2", "units": "ug/m3"}},
                        {"id": 7, "parameter": {"name": "co", "units": "ug/m3"}},
                        {"id": 8, "parameter": {"name": "co2", "units": "ppm"}},
                        {"id": 9, "parameter": {"name": "o3", "units": "ug/m3"}},
                        {"id": 10, "parameter": {"name": "um003", "units": "particles/cm3"}},
                    ],
                }
            ]
        },
        loc_path,
    )
    sensors_df = load_sensors(loc_path)
    assert set(sensors_df["parameter"]) == {
        "pm25", "pm10", "no2", "so2", "co", "co2", "o3", "temperature", "relativehumidity"
    }

    write_parquet(
        pd.DataFrame(
            [
                {
                    "station_id": "openaq_100",
                    "station_name": "Station A",
                    "sensor_tier": "reference",
                    "is_boundary": True,
                    "grid_id": "grid_582000_2327000",
                },
                {
                    "station_id": "openaq_999",
                    "station_name": "Outside Station",
                    "sensor_tier": "low_cost",
                    "is_boundary": False,
                    "grid_id": "grid_582000_2327000",
                },
            ]
        ),
        dim_station_path,
    )

    # 3. Tạo raw OpenAQ hours
    base_utc = datetime(2026, 9, 29, 17, 0, tzinfo=timezone.utc)  # 2026-09-30 00:00+07
    rows = []
    for h in range(20):
        t0 = base_utc + pd.Timedelta(hours=h)
        rows.append(
            {
                "sensor_id": 1,
                "datetime_from_utc": t0,
                "datetime_to_utc": t0 + pd.Timedelta(hours=1),
                "value": float(20 + h),
                "observed_count": 1,
            }
        )
    # 1 giờ âm
    t_neg = base_utc + pd.Timedelta(hours=20)
    rows.append(
        {
            "sensor_id": 1,
            "datetime_from_utc": t_neg,
            "datetime_to_utc": t_neg + pd.Timedelta(hours=1),
            "value": -5.0,
            "observed_count": 1,
        }
    )
    # Ngày 2026-09-29 chỉ có 4 giờ hợp lệ (10, 20, 30, 40) và 1 giờ ngoài ngưỡng (1500), không có dữ liệu lưới
    prev_utc = base_utc - pd.Timedelta(days=1)
    for h, val in [(0, 10.0), (1, 20.0), (2, 30.0), (3, 40.0), (4, 1500.0)]:
        t0 = prev_utc + pd.Timedelta(hours=h)
        rows.append(
            {
                "sensor_id": 1,
                "datetime_from_utc": t0,
                "datetime_to_utc": t0 + pd.Timedelta(hours=1),
                "value": val,
                "observed_count": 1,
            }
        )
    # 6 giờ PM10 kẹt số = 50.0 + 1 giờ PM10 bình thường = 65.0
    for h in range(6):
        t0 = base_utc + pd.Timedelta(hours=h)
        rows.append(
            {
                "sensor_id": 2,
                "datetime_from_utc": t0,
                "datetime_to_utc": t0 + pd.Timedelta(hours=1),
                "value": 50.0,
                "observed_count": 1,
            }
        )
    t_pm10_ok = base_utc + pd.Timedelta(hours=8)
    rows.append(
        {
            "sensor_id": 2,
            "datetime_from_utc": t_pm10_ok,
            "datetime_to_utc": t_pm10_ok + pd.Timedelta(hours=1),
            "value": 65.0,
            "observed_count": 1,
        }
    )
    # Nhiệt độ, độ ẩm và các khí NO2, SO2, CO, CO2, O3 vào ngày 2026-09-30
    for h, temp, rh in [(0, 28.0, 70.0), (1, 30.0, 80.0)]:
        t0 = base_utc + pd.Timedelta(hours=h)
        for sid, val in [(3, temp), (4, rh), (5, 18.0), (6, 4.0), (7, 500.0), (8, 420.0), (9, 32.0)]:
            rows.append(
                {
                    "sensor_id": sid,
                    "datetime_from_utc": t0,
                    "datetime_to_utc": t0 + pd.Timedelta(hours=1),
                    "value": val,
                    "observed_count": 1,
                }
            )

    raw_hours_path = tmp_path / "sensor_all_2026.parquet"
    write_parquet(pd.DataFrame(rows), raw_hours_path)

    con = duckdb.connect()
    con.register("sensors", sensors_df)
    stg_hourly_path = tmp_path / "stg_openaq_hourly.parquet"
    copy_query(con, openaq_hourly_sql(f"'{raw_hours_path.as_posix()}'"), stg_hourly_path)

    stg_df = pd.read_parquet(stg_hourly_path)
    assert set(stg_df.qc_flag.unique()) <= {0, 1}
    assert int((stg_df.qc_flag == 1).sum()) == 2  # 1 giờ âm + 1 giờ vượt ngưỡng 1500 (bỏ qua kẹt số)

    # 4. Tạo staging meteo, satellite, viirs (chỉ cho ngày 2026-09-30, cố tình để ngày 2026-09-29 thiếu lưới)
    raw_meteo_path = tmp_path / "raw_meteo.parquet"
    write_parquet(
        pd.DataFrame(
            [
                {
                    "grid_id": gid,
                    "date": date(2026, 9, 30),
                    "t2m_k": 300.15,
                    "d2m_k": 295.15,
                    "rh_pct": 75.0,
                    "u10_ms": 3.0,
                    "v10_ms": 4.0,
                    "ws10_ms": 5.0,
                    "sp_pa": 101325.0,
                    "tp_m": 0.012,
                    "era5_land_hours": 24,
                    "blh_mean_m": 650.0,
                    "blh_min_m": 180.0,
                }
                for gid in ("grid_582000_2327000", "grid_583000_2327000")
            ]
        ),
        raw_meteo_path,
    )
    stg_meteo_path = tmp_path / "stg_meteo_daily.parquet"
    copy_query(con, METEO_SQL.format(source=f"'{raw_meteo_path.as_posix()}'"), stg_meteo_path)

    raw_sat_path = tmp_path / "raw_sat.parquet"
    write_parquet(
        pd.DataFrame(
            [
                {
                    "grid_id": "grid_582000_2327000",
                    "date": date(2026, 9, 30),
                    "no2_trop": 1e-4,
                    "no2_trop_n": 1,
                    "co": 0.03,
                    "co_n": 1,
                    "o3": 0.12,
                    "o3_n": 1,
                    "so2": 2e-4,
                    "so2_n": 1,
                    "aod047": 450.0,
                    "aod047_n": 1,
                },
                {
                    "grid_id": "grid_583000_2327000",
                    "date": date(2026, 9, 30),
                    "no2_trop": 1.2e-4,
                    "no2_trop_n": 1,
                    "co": 0.03,
                    "co_n": 1,
                    "o3": 0.12,
                    "o3_n": 1,
                    "so2": 2e-4,
                    "so2_n": 1,
                    "aod047": None,
                    "aod047_n": 0,
                },
            ]
        ),
        raw_sat_path,
    )
    stg_sat_path = tmp_path / "stg_sat_daily.parquet"
    copy_query(con, SATELLITE_SQL.format(source=f"'{raw_sat_path.as_posix()}'"), stg_sat_path)

    raw_viirs_path = tmp_path / "raw_viirs.parquet"
    write_parquet(
        pd.DataFrame(
            [
                {"grid_id": "grid_582000_2327000", "month": date(2026, 9, 1), "avg_rad": 25.5, "cf_cvg": 5},
                {"grid_id": "grid_583000_2327000", "month": date(2026, 9, 1), "avg_rad": 18.0, "cf_cvg": 5},
            ]
        ),
        raw_viirs_path,
    )
    stg_viirs_path = tmp_path / "stg_viirs_monthly.parquet"
    copy_query(con, VIIRS_SQL.format(source=f"'{raw_viirs_path.as_posix()}'"), stg_viirs_path)

    # 5. Tạo Core Facts
    fct_station_path = tmp_path / "fct_station_daily.parquet"
    fct_meteo_path = tmp_path / "fct_grid_meteo_daily.parquet"
    fct_sat_path = tmp_path / "fct_grid_satellite_daily.parquet"

    copy_query(con, station_daily_sql(stg_hourly_path, dim_station_path, dim_date_path), fct_station_path)
    copy_query(con, grid_meteo_daily_sql(stg_meteo_path, dim_grid_path, dim_date_path), fct_meteo_path)
    copy_query(
        con,
        grid_satellite_daily_sql(stg_sat_path, stg_viirs_path, dim_grid_path, dim_date_path),
        fct_sat_path,
    )

    fct_st = pd.read_parquet(fct_station_path).sort_values("date_id").reset_index(drop=True)
    assert len(fct_st) == 2

    # 6. Tạo Marts
    mart_grid_path = tmp_path / "mart_grid_daily_features.parquet"
    mart_train_path = tmp_path / "mart_station_daily_training.parquet"
    copy_query(
        con,
        grid_mart_sql(dim_grid_path, dim_date_path, fct_meteo_path, fct_sat_path),
        mart_grid_path,
    )
    copy_query(
        con,
        station_training_mart_sql(
            fct_station_path, dim_station_path, mart_grid_path, dim_grid_path, dim_date_path
        ),
        mart_train_path,
    )

    mart_grid = pd.read_parquet(mart_grid_path).sort_values("grid_id").reset_index(drop=True)
    assert len(mart_grid) == 2
    assert not any("pm25" in c for c in mart_grid.columns)
    assert mart_grid.iloc[0]["aod_047_missing"] == 0
    assert mart_grid.iloc[1]["aod_047_missing"] == 1

    mart_train = pd.read_parquet(mart_train_path).sort_values("date_id").reset_index(drop=True)
    assert len(mart_train) == 2

    # Ngày 29 thiếu dữ liệu lưới nhưng thông tin lịch và tọa độ phải luôn đầy đủ (NOT NULL)
    r29 = mart_train.iloc[0]
    assert r29["pm25_mean"] == 25.0
    assert bool(r29["is_boundary"]) is True
    assert pd.Timestamp(r29["date"]).date() == date(2026, 9, 29)
    assert r29["year"] == 2026
    assert r29["month"] == 9
    assert r29["day_of_week"] == 2
    assert r29["season"] == "autumn"
    assert r29["easting_m"] == 582500
    assert r29["northing_m"] == 2327500
    assert r29["temp_2m_c_missing"] == 1

    # Ngày 30 có đầy đủ cả trạm và lưới
    r30 = mart_train.iloc[1]
    assert r30["pm25_mean"] == 29.5
    assert r30["no2_aq"] == 18.0
    assert r30["openaq_temperature"] == 29.0
    assert r30["temp_2m_c_missing"] == 0
    assert abs(r30["temp_2m_c"] - 27.0) < 1e-4
    assert abs(r30["aod_047"] - 0.45) < 1e-6


def test_xgboost_two_baselines():
    """Kiểm định huấn luyện và đánh giá 2 Baseline XGBoost (OpenAQ+Meteo vs OpenAQ+Meteo+Satellite)."""
    import numpy as np

    from src.models.train_baselines import BASELINE2_FEATURES, evaluate_baselines

    rng = np.random.default_rng(42)
    rows = []
    for d_idx, date_id in enumerate([20260901, 20260902, 20260903, 20260904, 20260905]):
        for g_idx in range(1, 6):
            row = {
                "date_id": date_id,
                "date": date(2026, 9, d_idx + 1),
                "year": 2026,
                "month": 9,
                "day_of_week": (d_idx % 7) + 1,
                "day_of_year": 244 + d_idx,
                "is_weekend": 0,
                "season": "autumn",
                "station_id": g_idx,
                "station_name": f"st_{g_idx}",
                "grid_id": f"grid_{g_idx}",
                "lon": 105.8 + g_idx * 0.01,
                "lat": 21.0 + g_idx * 0.01,
                "easting_m": 580000 + g_idx * 1000,
                "northing_m": 2320000 + g_idx * 1000,
                "is_valid_day": 1,
                "pm25_mean": 25.0 + g_idx * 3.0 + d_idx * 2.0,
            }
            for col in BASELINE2_FEATURES:
                if col not in row:
                    row[col] = 0.0 if col.endswith("_missing") else float(rng.normal(20.0, 2.0))
            rows.append(row)

    syn_df = pd.DataFrame(rows)
    metrics_df, oof_df, fi_df = evaluate_baselines(syn_df, n_splits=5, valid_days_only=True)
    overall_cv = metrics_df[(metrics_df["eval_mode"] == "5Fold_CV") & (metrics_df["scope"] == "ALL")]
    assert len(overall_cv) == 2
    assert set(overall_cv["model_code"]) == {"Baseline_1_OpenAQ_Meteo", "Baseline_2_OpenAQ_Meteo_Sat"}
    assert oof_df["pred_cv_b1_meteo"].notna().all()
    assert oof_df["pred_cv_b2_meteo_sat"].notna().all()
    assert not fi_df.empty
