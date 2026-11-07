"""Parameterized SELECTs against the serving schema owned by Package 1."""

from collections.abc import Callable
from datetime import date
from functools import cached_property

import psycopg

from .errors import DATABASE_MESSAGE, APIError


class Repository:
    def __init__(self, get_connection: Callable[[], psycopg.Connection]):
        self.get_connection = get_connection

    @cached_property
    def connection(self) -> psycopg.Connection:
        # Acquire only after FastAPI validates parameters; invalid requests need no DB.
        return self.get_connection()

    def ready(self) -> None:
        try:
            self.connection.execute("SELECT postgis_version()").fetchone()
            # A live socket alone is insufficient when the serving migrations are missing.
            self.connection.execute(
                """SELECT g.grid_id, g.geom_4326, s.station_id, o.pm25_observed,
                          m.model_id, p.pm25_pred
                   FROM grids g, stations s, station_daily_observations o,
                        model_metadata m, grid_daily_predictions p LIMIT 0"""
            )
        except (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedFunction) as exc:
            # Missing serving tables/PostGIS are readiness failures specifically here.
            raise APIError(503, "DATABASE_UNAVAILABLE", DATABASE_MESSAGE) from exc

    def require_model(self, model_id: str) -> None:
        if self.connection.execute("SELECT 1 FROM model_metadata WHERE model_id = %s", (model_id,)).fetchone() is None:
            raise APIError(404, "MODEL_NOT_FOUND", "Không tìm thấy mô hình trong hệ thống.")

    def require_grid(self, grid_id: str) -> None:
        if self.connection.execute("SELECT 1 FROM grids WHERE grid_id = %s", (grid_id,)).fetchone() is None:
            raise APIError(404, "GRID_NOT_FOUND", "Không tìm thấy ô lưới trong hệ thống.")

    def models(self) -> list[dict]:
        # Test prediction presence without counting every row of each model.
        return self.connection.execute(
            """SELECT m.model_id, m.model_version, m.label, m.is_default, m.feature_count
               FROM model_metadata m
               WHERE EXISTS (SELECT 1 FROM grid_daily_predictions p WHERE p.model_id = m.model_id)
               ORDER BY m.is_default DESC, m.model_id"""
        ).fetchall()

    def dates(self, model_id: str) -> list[date]:
        rows = self.connection.execute(
            "SELECT DISTINCT date FROM grid_daily_predictions WHERE model_id = %s ORDER BY date", (model_id,)
        ).fetchall()
        return [row["date"] for row in rows]

    def grids(self) -> list[dict]:
        return self.connection.execute(
            """SELECT grid_id, centroid_lon, centroid_lat, is_boundary,
                      ST_AsGeoJSON(geom_4326, 9, 0)::json AS geometry
               FROM grids ORDER BY grid_id"""
        ).fetchall()

    def map(self, day: date, model_id: str) -> list[dict]:
        # Matches idx_predictions_date_model; omit geometry, model artifacts and metadata.
        return self.connection.execute(
            """SELECT grid_id, pm25_pred FROM grid_daily_predictions
               WHERE date = %s AND model_id = %s ORDER BY grid_id""",
            (day, model_id),
        ).fetchall()

    def history(self, grid_id: str, model_id: str, start: date, end: date) -> list[dict]:
        return self.connection.execute(
            """SELECT date, pm25_pred FROM grid_daily_predictions
               WHERE grid_id = %s AND model_id = %s AND date BETWEEN %s AND %s ORDER BY date""",
            (grid_id, model_id, start, end),
        ).fetchall()

    def stations(self, day: date) -> list[dict]:
        # is_boundary means the station point is inside Hanoi (build_dims/importer).
        # Put the date condition on the JOIN, preserving stations with no observation.
        return self.connection.execute(
            """SELECT s.station_id, s.station_name, s.grid_id,
                      s.lon AS longitude, s.lat AS latitude,
                      o.pm25_observed, o.pm25_valid_hours, o.is_valid_day
               FROM stations s
               LEFT JOIN station_daily_observations o ON o.station_id = s.station_id AND o.date = %s
               WHERE s.is_boundary = TRUE ORDER BY s.station_id""",
            (day,),
        ).fetchall()
