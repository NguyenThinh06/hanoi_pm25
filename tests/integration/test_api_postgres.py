"""Real PostgreSQL/PostGIS checks. Read-only; no schema creation, fixtures or import.

Set TEST_DATABASE_URL explicitly to a migrated, populated serving database. If set,
connection/schema/data failures FAIL tests; they are never silently skipped.
"""

import math
import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from src.api.config import Settings
from src.api.main import create_app

pytestmark = pytest.mark.postgres


def clean(value):
    return value if value is None or math.isfinite(value) else None


@pytest.fixture(scope="module")
def real_db():
    dsn = os.getenv("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Chưa có TEST_DATABASE_URL; không tuyên bố đã kiểm thử PostgreSQL thật.")
    with psycopg.connect(
        dsn,
        row_factory=dict_row,
        connect_timeout=3,
        options="-c default_transaction_read_only=on -c statement_timeout=10000",
    ) as connection:
        yield connection


@pytest.fixture(scope="module")
def real_client(real_db):
    with TestClient(create_app(Settings(database_url=os.environ["TEST_DATABASE_URL"]))) as client:
        yield client


@pytest.fixture(scope="module")
def sample(real_db):
    row = real_db.execute(
        "SELECT grid_id, date, model_id, pm25_pred FROM grid_daily_predictions ORDER BY date, model_id LIMIT 1"
    ).fetchone()
    assert row is not None, "TEST_DATABASE_URL cần dữ liệu Gói 1 đã import; bảng predictions đang rỗng."
    return row


def test_postgres_health(real_client):
    response = real_client.get("/health")
    assert response.status_code == 200 and response.json() == {"status": "ok", "database": "ready"}


def test_postgres_models(real_client, real_db, sample):
    expected = real_db.execute(
        """SELECT m.model_id, m.model_version, m.label, m.is_default, m.feature_count FROM model_metadata m
           WHERE EXISTS (SELECT 1 FROM grid_daily_predictions p WHERE p.model_id=m.model_id)
           ORDER BY m.is_default DESC, m.model_id"""
    ).fetchall()
    response = real_client.get("/api/models")
    assert response.status_code == 200 and response.json() == {"count": len(expected), "data": expected}


def test_postgres_dates(real_client, real_db, sample):
    expected = [
        row["date"].isoformat()
        for row in real_db.execute(
            "SELECT DISTINCT date FROM grid_daily_predictions WHERE model_id=%s ORDER BY date", (sample["model_id"],)
        ).fetchall()
    ]
    response = real_client.get("/api/dates", params={"model_id": sample["model_id"]})
    assert response.status_code == 200
    assert response.json() == {
        "model_id": sample["model_id"],
        "count": len(expected),
        "data": expected,
        "min_date": expected[0],
        "max_date": expected[-1],
    }


def test_postgres_grids(real_client, real_db):
    expected = real_db.execute(
        """SELECT grid_id, centroid_lon, centroid_lat, is_boundary, ST_SRID(geom_4326) AS srid,
                  ST_IsValid(geom_4326) AS valid, ST_AsGeoJSON(geom_4326, 9, 0)::json AS geometry
           FROM grids ORDER BY grid_id"""
    ).fetchall()
    response = real_client.get("/api/grids")
    assert response.status_code == 200
    features = response.json()["features"]
    assert len(features) == len(expected)
    for feature, row in zip(features, expected, strict=True):
        assert row["srid"] == 4326 and row["valid"]
        assert feature["id"] == row["grid_id"] and feature["geometry"] == row["geometry"]
        assert feature["properties"] == {k: row[k] for k in ("grid_id", "centroid_lon", "centroid_lat", "is_boundary")}


def test_postgres_map_no_rounding(real_client, real_db, sample):
    expected = real_db.execute(
        "SELECT grid_id, pm25_pred FROM grid_daily_predictions WHERE date=%s AND model_id=%s ORDER BY grid_id",
        (sample["date"], sample["model_id"]),
    ).fetchall()
    for row in expected:
        row["pm25_pred"] = clean(row["pm25_pred"])
    response = real_client.get("/api/map", params={"date": sample["date"].isoformat(), "model_id": sample["model_id"]})
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == expected and body["count"] == len(expected) and body["unit"] == "µg/m³"


def test_postgres_history_inclusive(real_client, sample):
    day = sample["date"].isoformat()
    response = real_client.get(
        f"/api/grids/{sample['grid_id']}/history", params={"model_id": sample["model_id"], "start": day, "end": day}
    )
    assert response.status_code == 200
    assert response.json()["data"] == [{"date": day, "pm25_pred": clean(sample["pm25_pred"])}]


def test_postgres_stations_and_qc(real_client, real_db, sample):
    expected = real_db.execute(
        """SELECT s.station_id, s.station_name, s.grid_id, s.lon AS longitude, s.lat AS latitude,
                  o.pm25_observed, o.pm25_valid_hours, o.is_valid_day
           FROM stations s LEFT JOIN station_daily_observations o
             ON s.station_id=o.station_id AND o.date=%s WHERE s.is_boundary=TRUE ORDER BY s.station_id""",
        (sample["date"],),
    ).fetchall()
    for row in expected:
        row["pm25_observed"] = clean(row["pm25_observed"])
        row["has_observation"] = row["pm25_observed"] is not None
        row["is_valid_day"] = bool(
            row["has_observation"]
            and row["is_valid_day"]
            and row["pm25_valid_hours"] is not None
            and row["pm25_valid_hours"] >= 18
        )
    response = real_client.get("/api/stations", params={"date": sample["date"].isoformat()})
    assert response.status_code == 200
    assert response.json()["data"] == expected and response.json()["count"] == len(expected)


def test_postgres_unknown_ids_and_injection(real_client, real_db, sample):
    # This string is only ever a bound value; it is never executed as SQL.
    payload = "missing' OR '1'='1'; --"
    before = real_db.execute("SELECT count(*) AS n FROM grids").fetchone()["n"]
    response = real_client.get("/api/dates", params={"model_id": payload})
    assert response.status_code == 404 and response.json()["error"]["code"] == "MODEL_NOT_FOUND"
    day = sample["date"].isoformat()
    response = real_client.get(
        f"/api/grids/{payload}/history", params={"model_id": sample["model_id"], "start": day, "end": day}
    )
    assert response.status_code == 404 and response.json()["error"]["code"] == "GRID_NOT_FOUND"
    assert real_db.execute("SELECT count(*) AS n FROM grids").fetchone()["n"] == before


def test_postgres_pool_is_readonly(real_client):
    with real_client.app.state.database.connection() as connection:
        assert connection.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"] == "on"
