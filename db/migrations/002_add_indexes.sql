CREATE INDEX IF NOT EXISTS idx_predictions_date_model
    ON grid_daily_predictions (date, model_id);

CREATE INDEX IF NOT EXISTS idx_grids_geom_4326
    ON grids USING GIST (geom_4326);

CREATE INDEX IF NOT EXISTS idx_station_obs_date
    ON station_daily_observations (date);
