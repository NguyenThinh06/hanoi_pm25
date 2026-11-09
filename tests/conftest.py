"""Synthetic API fixtures. These fixtures never connect to PostgreSQL."""

from datetime import date
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from src.api.config import Settings
from src.api.errors import APIError
from src.api.main import create_app
from src.api.repository import Repository
from src.api.routes import get_repository


@pytest.fixture
def model_id():
    return "Baseline_2_OpenAQ_Meteo_Sat:v2.0.0-retrospective"


@pytest.fixture
def grid_id():
    return "grid_584000_2324000"


@pytest.fixture
def repo(model_id, grid_id):
    repository = Mock(spec=Repository)

    def require_model(value):
        if value not in (model_id, "Baseline_1_OpenAQ_Meteo:v2.0.0-retrospective"):
            raise APIError(404, "MODEL_NOT_FOUND", "Không tìm thấy mô hình trong hệ thống.")

    def require_grid(value):
        if value != grid_id:
            raise APIError(404, "GRID_NOT_FOUND", "Không tìm thấy ô lưới trong hệ thống.")

    repository.require_model.side_effect = require_model
    repository.require_grid.side_effect = require_grid
    repository.models.return_value = [
        {
            "model_id": model_id,
            "model_version": "v2.0.0-retrospective",
            "label": "Baseline 2 — Khí tượng + Vệ tinh",
            "is_default": True,
            "feature_count": 34,
        }
    ]
    repository.dates.return_value = [date(2024, 1, 15), date(2024, 1, 16)]
    repository.grids.return_value = [
        {
            "grid_id": grid_id,
            "centroid_lon": 105.8085,
            "centroid_lat": 21.0152,
            "is_boundary": False,
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [105.8037, 21.0107],
                        [105.8133, 21.0107],
                        [105.8133, 21.0197],
                        [105.8037, 21.0197],
                        [105.8037, 21.0107],
                    ]
                ],
            },
        }
    ]
    repository.map.return_value = [{"grid_id": grid_id, "pm25_pred": 35.723456789}]
    repository.history.return_value = [{"date": date(2024, 1, 15), "pm25_pred": 35.723456789}]
    repository.stations.return_value = [
        {
            "station_id": "openaq_2161290",
            "station_name": "United States Embassy Hanoi",
            "grid_id": grid_id,
            "longitude": 105.8228,
            "latitude": 21.0215,
            "pm25_observed": 33.1,
            "pm25_valid_hours": 24,
            "is_valid_day": True,
        }
    ]
    return repository


@pytest.fixture
def client(repo):
    app = create_app(Settings())
    app.dependency_overrides[get_repository] = lambda: repo
    with TestClient(app) as client:
        yield client


@pytest.fixture
def requests_v1(model_id, grid_id):
    return [
        ("/health", {}),
        ("/api/models", {}),
        ("/api/dates", {"model_id": model_id}),
        ("/api/grids", {}),
        ("/api/map", {"date": "2024-01-15", "model_id": model_id}),
        (f"/api/grids/{grid_id}/history", {"model_id": model_id, "start": "2024-01-15", "end": "2024-01-16"}),
        ("/api/stations", {"date": "2024-01-15"}),
    ]
