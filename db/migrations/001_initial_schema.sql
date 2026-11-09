CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS grids (
    grid_id text PRIMARY KEY,
    easting_m bigint NOT NULL,
    northing_m bigint NOT NULL,
    centroid_lon double precision NOT NULL,
    centroid_lat double precision NOT NULL,
    is_boundary boolean NOT NULL,
    geom_3405 geometry(Polygon, 3405) NOT NULL,
    geom_4326 geometry(Polygon, 4326) NOT NULL
);

CREATE TABLE IF NOT EXISTS stations (
    station_id text PRIMARY KEY,
    station_name text NOT NULL,
    lon double precision NOT NULL,
    lat double precision NOT NULL,
    grid_id text REFERENCES grids (grid_id),
    provider text,
    sensor_tier text,
    is_boundary boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS station_daily_observations (
    station_id text NOT NULL REFERENCES stations (station_id),
    date date NOT NULL,
    station_name text,
    grid_id text REFERENCES grids (grid_id),
    pm25_observed double precision,
    pm25_valid_hours smallint,
    is_valid_day boolean NOT NULL,
    pm25_std double precision,
    pm25_min double precision,
    pm25_max double precision,
    PRIMARY KEY (station_id, date),
    CHECK (pm25_valid_hours IS NULL OR pm25_valid_hours BETWEEN 0 AND 24)
);

CREATE TABLE IF NOT EXISTS model_metadata (
    model_id text PRIMARY KEY,
    model_version text NOT NULL,
    model_name text NOT NULL,
    label text NOT NULL,
    is_default boolean NOT NULL DEFAULT false,
    feature_count integer NOT NULL,
    metadata_json jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS grid_daily_predictions (
    grid_id text NOT NULL REFERENCES grids (grid_id),
    date date NOT NULL,
    model_id text NOT NULL REFERENCES model_metadata (model_id),
    model_version text NOT NULL,
    pm25_pred double precision NOT NULL,
    run_id text NOT NULL,
    PRIMARY KEY (grid_id, date, model_id)
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
