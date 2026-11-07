"""Contract v1 responses and strict ISO calendar dates."""

import math
import re
from datetime import date
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def parse_day(value: object) -> date:
    if type(value) is date:
        return value
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Ngày phải có định dạng YYYY-MM-DD.")
    return date.fromisoformat(value)


Day = Annotated[date, BeforeValidator(parse_day)]


def validate_identifier(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Định danh không được chứa ký tự NUL.")
    return value


Identifier = Annotated[str, AfterValidator(validate_identifier)]


def finite_or_none(value: float | None) -> float | None:
    return value if value is None or math.isfinite(value) else None


Concentration = Annotated[float | None, BeforeValidator(finite_or_none)]
Longitude = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]
Latitude = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
Position = tuple[Longitude, Latitude]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ErrorDetail(Schema):
    code: str
    message: str


class ErrorResponse(Schema):
    error: ErrorDetail


class HealthResponse(Schema):
    status: Literal["ok"] = "ok"
    database: Literal["ready"] = "ready"


T = TypeVar("T")


class ListResponse(Schema, Generic[T]):
    count: int
    data: list[T]


class Model(Schema):
    model_id: str
    model_version: str
    label: str
    is_default: bool
    feature_count: int


class DatesResponse(ListResponse[date]):
    model_id: str
    min_date: date | None
    max_date: date | None


class GridProperties(Schema):
    grid_id: str
    centroid_lon: Longitude
    centroid_lat: Latitude
    is_boundary: bool


class Polygon(Schema):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[Position]]

    @model_validator(mode="after")
    def closed_rings(self) -> "Polygon":
        if not self.coordinates or any(len(ring) < 4 or ring[0] != ring[-1] for ring in self.coordinates):
            raise ValueError("GeoJSON Polygon phải có các vòng khép kín.")
        return self


class Feature(Schema):
    type: Literal["Feature"] = "Feature"
    id: str
    properties: GridProperties
    geometry: Polygon


class GridsResponse(Schema):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[Feature]


class MapValue(Schema):
    grid_id: str
    pm25_pred: Concentration


class MapResponse(ListResponse[MapValue]):
    date: date
    model_id: str
    unit: Literal["µg/m³"] = "µg/m³"


class HistoryValue(Schema):
    date: date
    pm25_pred: Concentration


class HistoryResponse(ListResponse[HistoryValue]):
    grid_id: str
    model_id: str
    start: date
    end: date
    unit: Literal["µg/m³"] = "µg/m³"


class Station(Schema):
    station_id: str
    station_name: str
    grid_id: str | None
    longitude: Longitude
    latitude: Latitude
    pm25_observed: Concentration
    pm25_valid_hours: int | None = Field(ge=0, le=24)
    is_valid_day: bool
    has_observation: bool


class StationsResponse(ListResponse[Station]):
    date: date
    unit: Literal["µg/m³"] = "µg/m³"
