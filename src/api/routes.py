"""Exactly seven public business/health GET routes from HANDOVER.md v1."""

from collections.abc import Iterator
from contextlib import ExitStack
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from .errors import APIError
from .repository import Repository
from .schemas import (
    DatesResponse,
    Day,
    ErrorResponse,
    GridsResponse,
    HealthResponse,
    HistoryResponse,
    Identifier,
    ListResponse,
    MapResponse,
    Model,
    StationsResponse,
    finite_or_none,
)

router = APIRouter(responses={500: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
validation = {422: {"model": ErrorResponse}}
not_found = {404: {"model": ErrorResponse}, **validation}


def get_repository(request: Request) -> Iterator[Repository]:
    with ExitStack() as stack:
        yield Repository(lambda: stack.enter_context(request.app.state.database.connection()))


# Finish the read transaction/return the connection before sending a success response.
Repo = Annotated[Repository, Depends(get_repository, scope="function")]
ModelID = Annotated[
    Identifier, Query(min_length=1, description="model_id đầy đủ lấy từ /api/models; không dùng model_version.")
]
GridID = Annotated[Identifier, Path(min_length=1)]
QueryDay = Annotated[Day, Query(description="Ngày lịch Hà Nội, YYYY-MM-DD.")]


@router.get("/health", response_model=HealthResponse)
def health(repo: Repo):
    repo.ready()
    return HealthResponse()


@router.get("/api/models", response_model=ListResponse[Model])
def models(repo: Repo):
    data = repo.models()
    return {"count": len(data), "data": data}


@router.get("/api/dates", response_model=DatesResponse, responses=not_found)
def dates(repo: Repo, model_id: ModelID):
    repo.require_model(model_id)
    data = repo.dates(model_id)
    return {
        "model_id": model_id,
        "count": len(data),
        "data": data,
        "min_date": data[0] if data else None,
        "max_date": data[-1] if data else None,
    }


@router.get("/api/grids", response_model=GridsResponse)
def grids(repo: Repo):
    features = []
    for row in repo.grids():
        features.append(
            {
                "type": "Feature",
                "id": row["grid_id"],
                "geometry": row["geometry"],
                "properties": {key: row[key] for key in ("grid_id", "centroid_lon", "centroid_lat", "is_boundary")},
            }
        )
    return {"type": "FeatureCollection", "features": features}


@router.get("/api/map", response_model=MapResponse, responses=not_found)
def map_values(repo: Repo, date: QueryDay, model_id: ModelID):
    repo.require_model(model_id)
    data = repo.map(date, model_id)
    return {"date": date, "model_id": model_id, "count": len(data), "data": data}


@router.get("/api/grids/{grid_id}/history", response_model=HistoryResponse, responses=not_found)
def history(repo: Repo, grid_id: GridID, model_id: ModelID, start: QueryDay, end: QueryDay):
    if end < start or (end - start).days + 1 > 366:
        raise APIError(422, "INVALID_REQUEST", "Khoảng ngày phải có start <= end và bao gồm tối đa 366 ngày.")
    repo.require_model(model_id)
    repo.require_grid(grid_id)
    data = repo.history(grid_id, model_id, start, end)
    return {
        "grid_id": grid_id,
        "model_id": model_id,
        "start": start,
        "end": end,
        "count": len(data),
        "data": data,
    }


@router.get("/api/stations", response_model=StationsResponse, responses=validation)
def stations(repo: Repo, date: QueryDay):
    data = []
    for row in repo.stations(date):
        observed = finite_or_none(row["pm25_observed"])
        hours = row["pm25_valid_hours"]
        has_observation = observed is not None
        data.append(
            {
                **row,
                "pm25_observed": observed,
                "has_observation": has_observation,
                "is_valid_day": bool(has_observation and row["is_valid_day"] and hours is not None and hours >= 18),
            }
        )
    return {"date": date, "count": len(data), "data": data}
