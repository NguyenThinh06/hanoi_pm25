"""Unit checks for routes, SQL binding, validation and pool failures (no real DB)."""

from contextlib import contextmanager
from datetime import date
from unittest.mock import Mock

import psycopg
import pytest
from psycopg_pool import PoolClosed, PoolTimeout, TooManyRequests
from pydantic import ValidationError

from src.api import routes
from src.api.config import Settings
from src.api.database import Database
from src.api.errors import INTERNAL_MESSAGE, APIError
from src.api.repository import Repository
from src.api.schemas import Polygon, finite_or_none, parse_day, validate_identifier


@pytest.mark.parametrize("endpoint", range(7))
def test_each_route_unit(repo, model_id, grid_id, endpoint):
    day = date(2024, 1, 15)
    calls = [
        lambda: routes.health(repo),
        lambda: routes.models(repo),
        lambda: routes.dates(repo, model_id),
        lambda: routes.grids(repo),
        lambda: routes.map_values(repo, day, model_id),
        lambda: routes.history(repo, grid_id, model_id, day, day),
        lambda: routes.stations(repo, day),
    ]
    result = calls[endpoint]()
    if endpoint == 0:
        assert result.model_dump() == {"status": "ok", "database": "ready"}
        repo.ready.assert_called_once()
    elif endpoint == 3:
        assert result["features"][0]["id"] == grid_id
    else:
        assert result["count"] == len(result["data"]) > 0


@pytest.mark.parametrize("value", ["2024-02-30", "20240115", "1705276800", "2024-1-15", "2024-01-15T00:00:00", ""])
def test_strict_date_rejects_non_iso_or_invalid_day(value):
    with pytest.raises(ValueError):
        parse_day(value)


@pytest.mark.parametrize("value", ["\x00model", "grid\x00id", "model\x00"])
def test_identifier_rejects_nul(value):
    with pytest.raises(ValueError, match="NUL"):
        validate_identifier(value)


@pytest.mark.parametrize(
    "value", ["Baseline_2_OpenAQ_Meteo_Sat:v2.0.0-retrospective", "grid_584000_2324000", "x' OR true --"]
)
def test_identifier_preserves_non_nul_values(value):
    assert validate_identifier(value) == value


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_concentration_is_missing(value):
    assert finite_or_none(value) is None


@pytest.mark.parametrize(
    "coordinates",
    [
        [],
        [[[105, 21]]],
        [[[105, 21], [106, 21], [106, 22], [105, 22]]],
        [[[500000, 2300000]] * 4],
        [[[float("nan"), 21]] * 4],
    ],
)
def test_geojson_rejects_invalid_or_projected_coordinates(coordinates):
    with pytest.raises(ValidationError):
        Polygon(coordinates=coordinates)


@pytest.mark.parametrize(
    "settings",
    [
        {"pool_min_size": 3, "pool_max_size": 2},
        {"pool_max_size": 0},
        {"pool_timeout": 0},
        {"pool_timeout": float("nan")},
        {"connect_timeout": 0},
        {"statement_timeout_ms": 0},
    ],
)
def test_invalid_pool_configuration(settings):
    with pytest.raises(ValueError):
        Settings(**settings)


def test_environment_configuration(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@localhost/db")
    monkeypatch.setenv("API_DB_POOL_MAX", "4")
    monkeypatch.setenv("API_CORS_ORIGINS", "http://localhost:5173, https://example.test ")
    settings = Settings.from_env()
    assert settings.pool_max_size == 4
    assert settings.cors_origins == ("http://localhost:5173", "https://example.test")
    assert "secret" not in repr(settings)


def test_pool_is_bounded_readonly_and_closed(monkeypatch):
    factory = Mock()
    monkeypatch.setattr("src.api.database.ConnectionPool", factory)
    db = Database(Settings(database_url="postgresql://localhost/db"))
    kwargs = factory.call_args.kwargs
    assert kwargs["max_size"] == 8 and kwargs["max_waiting"] == 64
    assert kwargs["open"] is False
    assert "default_transaction_read_only=on" in kwargs["kwargs"]["options"]
    db.open()
    db.close()
    factory.return_value.open.assert_called_once_with(wait=False)
    factory.return_value.close.assert_called_once()


@pytest.mark.parametrize(
    "failure",
    [
        psycopg.OperationalError,
        psycopg.InterfaceError,
        psycopg.errors.QueryCanceled,
        PoolTimeout,
        PoolClosed,
        TooManyRequests,
    ],
)
def test_pool_errors_do_not_leak_credentials(failure):
    db = Database(Settings())
    db.pool = Mock()
    db.pool.connection.side_effect = failure("secret DSN SQL")
    with pytest.raises(APIError) as caught:
        with db.connection():
            pytest.fail("must not acquire connection")
    assert caught.value.status == 503 and caught.value.code == "DATABASE_UNAVAILABLE"
    assert "secret" not in caught.value.message


@pytest.mark.parametrize(
    "failure",
    [
        psycopg.DataError,
        psycopg.errors.SyntaxError,
        psycopg.errors.UndefinedTable,
        psycopg.errors.UndefinedFunction,
        psycopg.errors.InsufficientPrivilege,
        psycopg.IntegrityError,
    ],
)
def test_database_internal_errors_are_not_outages(failure, caplog):
    db = Database(Settings())
    db.pool = Mock()
    db.pool.connection.side_effect = failure("secret DSN SELECT private_data")
    with pytest.raises(APIError) as caught:
        with db.connection():
            pytest.fail("must not acquire connection")
    assert caught.value.status == 500 and caught.value.code == "INTERNAL_ERROR"
    assert caught.value.message == INTERNAL_MESSAGE
    assert "secret" not in caplog.text and "private_data" not in caplog.text


def test_error_during_query_is_translated():
    db = Database(Settings())
    db.pool = Mock()

    @contextmanager
    def connection():
        yield Mock()

    db.pool.connection = connection
    with pytest.raises(APIError, match="Cơ sở dữ liệu"):
        with db.connection():
            raise psycopg.OperationalError("connection lost during request")


@pytest.mark.parametrize(
    "method, arguments, order",
    [
        ("require_model", ("x'; DROP TABLE grids; --",), None),
        ("require_grid", ("x' OR '1'='1",), None),
        ("dates", ("x' OR true --",), "ORDER BY date"),
        ("map", (date(2024, 1, 15), "x' OR true --"), "ORDER BY grid_id"),
        ("history", ("x' OR true --", "version-is-not-id", date(2024, 1, 1), date(2024, 1, 2)), "ORDER BY date"),
        ("stations", (date(2024, 1, 15),), "ORDER BY s.station_id"),
    ],
)
def test_sql_uses_bound_parameters(method, arguments, order):
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = []
    repository = Repository(lambda: connection)
    getattr(repository, method)(*arguments)
    sql, bound = connection.execute.call_args.args
    assert bound == arguments
    assert sql.count("%s") == len(arguments)
    for value in arguments:
        assert str(value) not in sql
    if order:
        assert order in sql


@pytest.mark.parametrize("method,code", [("require_model", "MODEL_NOT_FOUND"), ("require_grid", "GRID_NOT_FOUND")])
def test_repository_missing_resource(method, code):
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = None
    with pytest.raises(APIError) as caught:
        getattr(Repository(lambda: connection), method)("missing")
    assert caught.value.code == code and caught.value.status == 404


def test_sql_joins_and_availability():
    connection = Mock()
    repository = Repository(lambda: connection)
    repository.models()
    sql = connection.execute.call_args.args[0]
    assert "EXISTS" in sql and "m.is_default DESC, m.model_id" in sql
    repository.grids()
    sql = connection.execute.call_args.args[0]
    assert "ST_AsGeoJSON(geom_4326, 9, 0)" in sql and "geom_3405" not in sql
    repository.stations(date(2024, 1, 15))
    sql = connection.execute.call_args.args[0]
    assert "LEFT JOIN" in sql and "AND o.date = %s" in sql and "s.is_boundary = TRUE" in sql
    assert "COALESCE(o.pm25_observed" not in sql
