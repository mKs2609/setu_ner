-- 0002: Phase 3 accessibility model (see docs/decisions/0010).
--
-- Provenance columns on roads, plus the two new tables. The tables would also
-- be created by create_tables.py; they are here too so one file describes the
-- whole schema change. Safe to run more than once.
--
--   psql "$DATABASE_URL" -f infra/migrations/0002_accessibility_model.sql

-- current_accessibility is never written without these two.
ALTER TABLE roads ADD COLUMN IF NOT EXISTS accessibility_model_version VARCHAR;
ALTER TABLE roads ADD COLUMN IF NOT EXISTS current_accessibility_as_of DATE;

CREATE TABLE IF NOT EXISTS district_flood_forecasts (
    id SERIAL PRIMARY KEY,
    district_key VARCHAR NOT NULL,
    display_name VARCHAR,
    in_corridor BOOLEAN NOT NULL DEFAULT FALSE,
    as_of_date DATE NOT NULL,
    target_date DATE NOT NULL,
    horizon_days INTEGER NOT NULL,
    probability DOUBLE PRECISION NOT NULL,
    persistence_probability DOUBLE PRECISION NOT NULL,
    affected_on_as_of BOOLEAN NOT NULL,
    model_version VARCHAR NOT NULL,
    model_kind VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_forecast_identity UNIQUE (district_key, as_of_date, horizon_days, model_version)
);
CREATE INDEX IF NOT EXISTS ix_district_flood_forecasts_district_key ON district_flood_forecasts (district_key);
CREATE INDEX IF NOT EXISTS ix_district_flood_forecasts_as_of_date ON district_flood_forecasts (as_of_date);
CREATE INDEX IF NOT EXISTS ix_district_flood_forecasts_target_date ON district_flood_forecasts (target_date);
CREATE INDEX IF NOT EXISTS ix_district_flood_forecasts_in_corridor ON district_flood_forecasts (in_corridor);
CREATE INDEX IF NOT EXISTS ix_district_flood_forecasts_model_version ON district_flood_forecasts (model_version);

CREATE TABLE IF NOT EXISTS road_damage_matches (
    id SERIAL PRIMARY KEY,
    observation_id INTEGER NOT NULL UNIQUE REFERENCES hazard_observations (id),
    road_id INTEGER REFERENCES roads (id),
    distance_m DOUBLE PRECISION,
    quality VARCHAR NOT NULL,
    matched_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_road_damage_matches_road_id ON road_damage_matches (road_id);
CREATE INDEX IF NOT EXISTS ix_road_damage_matches_quality ON road_damage_matches (quality);
