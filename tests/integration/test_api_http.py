"""ASGI/HTTP integration against a synthetic repository; NOT PostgreSQL evidence."""

import json
import socket
from contextlib import contextmanager
from datetime import date
from unittest.mock import Mock
from urllib.parse import quote

import psycopg
import pytest
from fastapi.testclient import TestClient

from src.api.config import Settings
from src.api.errors import DATABASE_MESSAGE, INTERNAL_MESSAGE, APIError
from src.api.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def sql_client():
    """Exercise real routes/repository/error handling with only the SQL connection faked."""
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = {"exists": 1}
    connection.execute.return_value.fetchall.return_value = []
    pool = Mock()
    released = Mock()

    @contextmanager
    def checkout():
        try:
            yield connection
        finally:
            released()

    pool.connection.side_effect = checkout
    with TestClient(create_app(Settings())) as client:
        client.app.state.database.pool = pool
        yield client, connection, pool, released


@pytest.mark.parametrize("endpoint", range(7))
def test_success_contract(client, repo, requests_v1, endpoint, model_id, grid_id):
    path, params = requests_v1[endpoint]
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    if endpoint == 0:
        assert body == {"status": "ok", "database": "ready"}
    elif endpoint == 1:
        assert body == {"count": 1, "data": repo.models.return_value}
    elif endpoint == 2:
        assert body == {
            "model_id": model_id,
            "count": 2,
            "min_date": "2024-01-15",
            "max_date": "2024-01-16",
            "data": ["2024-01-15", "2024-01-16"],
        }
    elif endpoint == 3:
        assert set(body) == {"type", "features"} and body["type"] == "FeatureCollection"
        feature = body["features"][0]
        assert feature["id"] == grid_id and feature["properties"]["grid_id"] == grid_id
        assert feature["geometry"]["type"] == "Polygon"
        ring = feature["geometry"]["coordinates"][0]
        assert ring[0] == ring[-1]
        assert all(105 < lon < 107 and 20 < lat < 22 for lon, lat in ring)
        assert "crs" not in body and set(feature) == {"type", "id", "properties", "geometry"}
    else:
        assert body["count"] == len(body["data"]) == 1 and body["unit"] == "µg/m³"
        if endpoint == 4:
            assert body == {
                "date": params["date"],
                "model_id": model_id,
                "unit": "µg/m³",
                "count": 1,
                "data": [{"grid_id": grid_id, "pm25_pred": 35.723456789}],
            }
        elif endpoint == 5:
            assert body == {
                "grid_id": grid_id,
                "model_id": model_id,
                "start": params["start"],
                "end": params["end"],
                "unit": "µg/m³",
                "count": 1,
                "data": [{"date": "2024-01-15", "pm25_pred": 35.723456789}],
            }
        else:
            assert body == {
                "date": params["date"],
                "unit": "µg/m³",
                "count": 1,
                "data": [{**repo.stations.return_value[0], "has_observation": True}],
            }


@pytest.mark.parametrize(
    "endpoint,method", [(1, "models"), (2, "dates"), (3, "grids"), (4, "map"), (5, "history"), (6, "stations")]
)
def test_empty_contract(client, repo, requests_v1, endpoint, method):
    getattr(repo, method).return_value = []
    path, params = requests_v1[endpoint]
    response = client.get(path, params=params)
    assert response.status_code == 200
    body = response.json()
    if endpoint == 3:
        assert body == {"type": "FeatureCollection", "features": []}
    else:
        assert body["count"] == 0 and body["data"] == []
        if endpoint == 2:
            assert body["min_date"] is None and body["max_date"] is None


@pytest.mark.parametrize("endpoint", range(7))
def test_missing_database_for_all_endpoints(requests_v1, endpoint):
    path, params = requests_v1[endpoint]
    with TestClient(create_app(Settings())) as client:
        response = client.get(path, params=params)
    assert response.status_code == 503
    assert response.json() == {"error": {"code": "DATABASE_UNAVAILABLE", "message": DATABASE_MESSAGE}}


@pytest.mark.parametrize("endpoint", range(7))
def test_connection_loss_for_all_endpoints(client, repo, requests_v1, endpoint):
    for method in ("ready", "models", "require_model", "grids", "stations"):
        getattr(repo, method).side_effect = APIError(503, "DATABASE_UNAVAILABLE", DATABASE_MESSAGE)
    path, params = requests_v1[endpoint]
    response = client.get(path, params=params)
    assert response.status_code == 503 and response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


@pytest.mark.parametrize("endpoint,key", [(4, "date"), (5, "start"), (5, "end"), (6, "date")])
@pytest.mark.parametrize(
    "value", ["2024-02-30", "15-01-2024", "20240115", "2024-1-15", "2024-01-15T00:00:00Z", "1705276800", "' OR true --"]
)
def test_invalid_dates(client, requests_v1, endpoint, key, value):
    path, params = requests_v1[endpoint]
    params = {**params, key: value}
    response = client.get(path, params=params)
    assert response.status_code == 422 and response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize("endpoint", [2, 4, 5, 6])
def test_missing_required_parameters(client, requests_v1, endpoint):
    response = client.get(requests_v1[endpoint][0])
    assert response.status_code == 422 and set(response.json()) == {"error"}


def test_validation_does_not_require_database(requests_v1):
    with TestClient(create_app(Settings())) as client:
        response = client.get("/api/map", params={"model_id": "x", "date": "bad"})
        assert response.status_code == 422
        path, params = requests_v1[5]
        assert client.get(path, params={**params, "end": "2026-01-01"}).status_code == 422


@pytest.mark.parametrize("endpoint", [2, 4, 5])
@pytest.mark.parametrize("value", ["\x00model", "model\x00id", "model\x00"])
def test_nul_model_is_422_before_database_access(requests_v1, endpoint, value):
    path, params = requests_v1[endpoint]
    with TestClient(create_app(Settings())) as client:
        # No configured DB: reaching the repository would incorrectly return 503.
        response = client.get(path, params={**params, "model_id": value})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert set(response.json()) == {"error"} and "\\u0000" not in response.text


@pytest.mark.parametrize("value", ["\x00grid", "grid\x00id", "grid\x00"])
def test_nul_grid_is_422_before_database_access(requests_v1, value):
    _, params = requests_v1[5]
    with TestClient(create_app(Settings())) as client:
        response = client.get(f"/api/grids/{quote(value, safe='')}/history", params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert "\\u0000" not in response.text


@pytest.mark.parametrize("endpoint", range(7))
@pytest.mark.parametrize(
    "failure,status,code",
    [
        (psycopg.OperationalError, 503, "DATABASE_UNAVAILABLE"),
        (psycopg.errors.SyntaxError, 500, "INTERNAL_ERROR"),
        (psycopg.DataError, 500, "INTERNAL_ERROR"),
    ],
)
def test_query_failure_classification(sql_client, requests_v1, endpoint, failure, status, code, caplog):
    client, connection, pool, released = sql_client
    connection.execute.side_effect = failure("secret DSN SELECT private_data")
    path, params = requests_v1[endpoint]
    response = client.get(path, params=params)
    assert response.status_code == status
    message = DATABASE_MESSAGE if status == 503 else INTERNAL_MESSAGE
    assert response.json() == {"error": {"code": code, "message": message}}
    pool.connection.assert_called_once()
    released.assert_called_once()
    assert "secret" not in response.text + caplog.text
    assert "private_data" not in response.text + caplog.text


@pytest.mark.parametrize("failure", [psycopg.errors.UndefinedTable, psycopg.errors.UndefinedFunction])
def test_health_missing_schema_is_readiness_failure(sql_client, failure):
    client, connection, _, released = sql_client
    # PostGIS failure on the first query; missing serving tables on the second.
    error = failure("private schema details")
    connection.execute.side_effect = error if failure is psycopg.errors.UndefinedFunction else [Mock(), error]
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"error": {"code": "DATABASE_UNAVAILABLE", "message": DATABASE_MESSAGE}}
    released.assert_called_once()


@pytest.mark.parametrize("endpoint", range(7))
@pytest.mark.parametrize(
    "failure,status,code",
    [
        (psycopg.OperationalError, 503, "DATABASE_UNAVAILABLE"),
        (psycopg.DataError, 500, "INTERNAL_ERROR"),
    ],
)
def test_transaction_exit_failure_precedes_http_response(sql_client, requests_v1, endpoint, failure, status, code):
    client, connection, pool, _ = sql_client

    @contextmanager
    def failing_checkout():
        yield connection
        raise failure("private transaction details")

    pool.connection.side_effect = failing_checkout
    path, params = requests_v1[endpoint]
    response = client.get(path, params=params)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "private transaction" not in response.text


@pytest.mark.parametrize("endpoint", range(7))
def test_request_reuses_and_returns_connection(sql_client, requests_v1, endpoint):
    client, _, pool, released = sql_client
    path, params = requests_v1[endpoint]
    assert client.get(path, params=params).status_code == 200
    pool.connection.assert_called_once()
    released.assert_called_once()


@pytest.mark.parametrize("endpoint", [2, 4, 5])
@pytest.mark.parametrize("model", ["missing", "baseline2", "v2.0.0-retrospective", "' OR true --"])
def test_unknown_model_id_not_alias_or_version(client, requests_v1, endpoint, model):
    path, params = requests_v1[endpoint]
    response = client.get(path, params={**params, "model_id": model})
    assert response.status_code == 404 and response.json()["error"]["code"] == "MODEL_NOT_FOUND"


def test_unknown_grid(client, requests_v1):
    _, params = requests_v1[5]
    response = client.get("/api/grids/missing/history", params=params)
    assert response.status_code == 404 and response.json()["error"]["code"] == "GRID_NOT_FOUND"


@pytest.mark.parametrize(
    "start,end,status",
    [
        ("2024-01-01", "2024-12-31", 200),
        ("2024-01-01", "2025-01-01", 422),
        ("2024-01-15", "2024-01-15", 200),
        ("2024-01-16", "2024-01-15", 422),
    ],
)
def test_inclusive_history_limit(client, requests_v1, repo, start, end, status):
    path, params = requests_v1[5]
    response = client.get(path, params={**params, "start": start, "end": end})
    assert response.status_code == status
    if status == 200:
        args = repo.history.call_args.args
        assert args[2].isoformat() == start and args[3].isoformat() == end
    else:
        assert response.json()["error"]["code"] == "INVALID_REQUEST"
        repo.history.assert_not_called()


@pytest.mark.parametrize(
    "observed,hours,qc,has_observation,is_valid",
    [
        (33.1, 24, True, True, True),
        (33.1, 17, False, True, False),
        (33.1, 17, True, True, False),
        (33.1, 24, False, True, False),
        (None, None, None, False, False),
        (None, 0, False, False, False),
        (float("nan"), 24, True, False, False),
        (float("inf"), 24, True, False, False),
        (-float("inf"), 24, True, False, False),
        (0.0, 18, True, True, True),
    ],
)
def test_station_qc_and_missing(client, repo, observed, hours, qc, has_observation, is_valid):
    repo.stations.return_value[0].update(pm25_observed=observed, pm25_valid_hours=hours, is_valid_day=qc)
    response = client.get("/api/stations", params={"date": "2024-01-15"})
    assert response.status_code == 200
    row = response.json()["data"][0]
    assert row["has_observation"] is has_observation and row["is_valid_day"] is is_valid
    assert row["pm25_valid_hours"] == hours
    assert row["pm25_observed"] == (observed if has_observation else None)
    assert "NaN" not in response.text and "Infinity" not in response.text


@pytest.mark.parametrize("endpoint,method", [(4, "map"), (5, "history")])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), None])
def test_nonfinite_predictions_become_json_null(client, repo, requests_v1, endpoint, method, value):
    getattr(repo, method).return_value[0]["pm25_pred"] = value
    path, params = requests_v1[endpoint]
    response = client.get(path, params=params)
    assert response.status_code == 200 and response.json()["data"][0]["pm25_pred"] is None
    json.loads(response.text, parse_constant=lambda x: pytest.fail(f"Non-standard JSON number: {x}"))


def test_bad_geojson_never_returns_nan(repo):
    repo.grids.return_value[0]["geometry"]["coordinates"][0][0][0] = float("nan")
    app = create_app(Settings())
    from src.api.routes import get_repository

    app.dependency_overrides[get_repository] = lambda: repo
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/grids")
    assert response.status_code == 500 and response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "NaN" not in response.text


def test_openapi_documents_exactly_seven_routes_and_errors(client):
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert len(schema["paths"]) == 7
    for path, operations in schema["paths"].items():
        assert set(operations) == {"get"}
        responses = operations["get"]["responses"]
        for status in ("500", "503"):
            assert responses[status]["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorResponse")
        if "422" in responses:
            assert responses["422"]["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorResponse")
    params = schema["paths"]["/api/grids/{grid_id}/history"]["get"]["parameters"]
    assert {p["name"] for p in params} == {"grid_id", "model_id", "start", "end"}


def test_configured_cors_and_url_encoded_model(repo, model_id):
    from src.api.routes import get_repository

    app = create_app(Settings(cors_origins=("http://localhost:5173",)))
    app.dependency_overrides[get_repository] = lambda: repo
    with TestClient(app) as client:
        response = client.get("/api/dates", params={"model_id": model_id}, headers={"Origin": "http://localhost:5173"})
        assert (
            response.status_code == 200 and response.headers["access-control-allow-origin"] == "http://localhost:5173"
        )
        assert "%3A" in str(response.request.url)
        repo.require_model.assert_called_with(model_id)
        assert (
            "access-control-allow-origin" not in client.get("/health", headers={"Origin": "https://evil.test"}).headers
        )


def test_real_tcp_connection_refusal_returns_503(requests_v1):
    # Bound but not listening: no live PostgreSQL or external service is touched.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
        settings = Settings(
            database_url=f"postgresql://127.0.0.1:{port}/unavailable",
            pool_timeout=0.1,
            connect_timeout=1,
            pool_max_size=1,
        )
        with TestClient(create_app(settings)) as client:
            for path, params in requests_v1:
                response = client.get(path, params=params)
                assert response.status_code == 503 and response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://localhost:3000"])
def test_default_cors_preflight_and_get(origin):
    with TestClient(create_app(Settings())) as client:
        response = client.options("/api/grids", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["access-control-allow-methods"] == "GET"
        response = client.get("/health", headers={"Origin": origin})
        assert response.status_code == 503
        assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("origin", ["https://untrusted.test", "http://127.0.0.1:5173"])
def test_disallowed_cors_preflight_and_get(client, origin):
    response = client.options("/api/grids", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
    response = client.get("/api/grids", headers={"Origin": origin})
    assert response.status_code == 200  # CORS is a browser policy, not server authentication.
    assert "access-control-allow-origin" not in response.headers


def test_cors_environment_replaces_defaults(monkeypatch):
    monkeypatch.setattr("src.api.config.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("API_CORS_ORIGINS", "https://dashboard.test")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(create_app()) as client:
        for origin, status in [("https://dashboard.test", 200), ("http://localhost:5173", 400)]:
            response = client.options("/api/grids", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
            assert response.status_code == status


@pytest.mark.parametrize("endpoint", [2, 3])
def test_cache_hit_needs_no_database_connection(sql_client, requests_v1, endpoint):
    client, connection, pool, released = sql_client
    path, params = requests_v1[endpoint]
    first = client.get(path, params=params)
    assert first.status_code == 200
    queries = connection.execute.call_count
    # Simulate DB outage after a successful load: existing cache serves until TTL/clear.
    connection.execute.side_effect = psycopg.OperationalError("offline")
    second = client.get(path, params=params)
    assert second.status_code == 200 and second.content == first.content
    assert connection.execute.call_count == queries
    pool.connection.assert_called_once()
    released.assert_called_once()
    client.app.state.response_cache.clear()
    assert client.get(path, params=params).status_code == 503


def test_dates_cache_separates_models_and_refreshes(client, repo, model_id):
    other = "Baseline_1_OpenAQ_Meteo:v2.0.0-retrospective"
    repo.dates.side_effect = lambda value: [date(2024, 1, 1 if value == model_id else 2)]
    first = client.get("/api/dates", params={"model_id": model_id}).json()
    second = client.get("/api/dates", params={"model_id": other}).json()
    assert first["data"] == ["2024-01-01"] and second["data"] == ["2024-01-02"]
    assert first["model_id"] == model_id and second["model_id"] == other
    assert client.get("/api/dates", params={"model_id": model_id}).json() == first
    assert repo.dates.call_count == repo.require_model.call_count == 2
    repo.dates.side_effect = lambda _: [date(2024, 2, 1)]
    client.app.state.response_cache.clear()
    assert client.get("/api/dates", params={"model_id": model_id}).json()["data"] == ["2024-02-01"]
    assert repo.dates.call_count == 3


def test_grids_cache_is_immutable_and_refreshes(client, repo):
    original = client.get("/api/grids").json()
    repo.grids.return_value[0]["centroid_lon"] = 106
    assert client.get("/api/grids").json() == original
    repo.grids.assert_called_once()
    client.app.state.response_cache.clear()
    changed = client.get("/api/grids").json()
    assert changed["features"][0]["properties"]["centroid_lon"] == 106
    assert repo.grids.call_count == 2


@pytest.mark.parametrize("endpoint", [2, 3])
def test_ttl_expiry_loads_new_data(client, repo, requests_v1, endpoint):
    clock = Mock(return_value=0)
    client.app.state.response_cache.clock = clock
    path, params = requests_v1[endpoint]
    assert client.get(path, params=params).status_code == 200
    method = repo.dates if endpoint == 2 else repo.grids
    method.return_value = []
    clock.return_value = 300
    body = client.get(path, params=params).json()
    assert body["data" if endpoint == 2 else "features"] == []
    assert method.call_count == 2


@pytest.mark.parametrize("endpoint", [2, 3])
@pytest.mark.parametrize("during_exit", [False, True])
@pytest.mark.parametrize("failure,status", [(psycopg.OperationalError, 503), (psycopg.DataError, 500)])
def test_failed_cache_load_retries_sql(sql_client, requests_v1, endpoint, during_exit, failure, status):
    client, connection, pool, _ = sql_client
    checkout = pool.connection.side_effect

    @contextmanager
    def failing_checkout():
        yield connection
        raise failure("private details")

    if during_exit:
        pool.connection.side_effect = failing_checkout
    else:
        connection.execute.side_effect = failure("private details")
    path, params = requests_v1[endpoint]
    assert client.get(path, params=params).status_code == status
    pool.connection.side_effect = checkout
    connection.execute.side_effect = None
    assert client.get(path, params=params).status_code == 200
    assert client.get(path, params=params).status_code == 200
    assert pool.connection.call_count == 2  # Error was not cached; third request is a cache hit.


def test_missing_and_invalid_models_are_not_cached(client, repo, model_id):
    for _ in range(2):
        assert client.get("/api/dates", params={"model_id": "missing"}).status_code == 404
        assert client.get("/api/dates", params={"model_id": "bad\x00id"}).status_code == 422
    assert repo.require_model.call_count == 2
    repo.require_model.side_effect = None
    assert client.get("/api/dates", params={"model_id": "missing"}).status_code == 200
    assert repo.require_model.call_count == 3


def test_invalid_geojson_is_never_cached(repo):
    from src.api.routes import get_repository

    original = repo.grids.return_value[0]["centroid_lon"]
    repo.grids.return_value[0]["centroid_lon"] = float("nan")
    app = create_app(Settings())
    app.dependency_overrides[get_repository] = lambda: repo
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/api/grids").status_code == 500
        repo.grids.return_value[0]["centroid_lon"] = original
        assert client.get("/api/grids").status_code == 200
        assert client.get("/api/grids").status_code == 200
    assert repo.grids.call_count == 2


@pytest.mark.parametrize("endpoint", [0, 1, 4, 5, 6])
def test_other_endpoints_never_use_cache(sql_client, requests_v1, endpoint):
    client, _, pool, released = sql_client
    path, params = requests_v1[endpoint]
    for _ in range(2):
        assert client.get(path, params=params).status_code == 200
    assert pool.connection.call_count == released.call_count == 2


def test_cache_does_not_cross_apps_or_lifespans(repo):
    from src.api.routes import get_repository

    first, second = create_app(Settings()), create_app(Settings())
    for app in (first, second, first):
        app.dependency_overrides[get_repository] = lambda: repo
        with TestClient(app) as client:
            assert client.get("/api/grids").status_code == 200
            assert client.get("/api/grids").status_code == 200
    assert repo.grids.call_count == 3
