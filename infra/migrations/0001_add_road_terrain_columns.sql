-- 0001: terrain columns on roads (Phase 2 -- see docs/decisions/0009).
--
-- WHY THIS FILE EXISTS AT ALL
-- Schema so far was created by apps/api/create_tables.py, which calls
-- SQLAlchemy's create_all(). That creates missing TABLES and silently does
-- nothing to a table that already exists -- so adding a column to `roads`
-- appeared to succeed while changing nothing. Every schema change to an
-- existing table needs a statement like this one.
--
-- Written to be safe to run more than once: IF NOT EXISTS throughout, so a
-- re-run is a no-op rather than an error. Same reasoning as the idempotent
-- ingestion in 0004 -- anything that might be run twice should survive it.
--
--   psql "$DATABASE_URL" -f infra/migrations/0001_add_road_terrain_columns.sql

ALTER TABLE roads ADD COLUMN IF NOT EXISTS elevation_m DOUBLE PRECISION;
ALTER TABLE roads ADD COLUMN IF NOT EXISTS slope_pct DOUBLE PRECISION;
ALTER TABLE roads ADD COLUMN IF NOT EXISTS elevation_source VARCHAR;

-- Indexed because the accessibility work filters on low-lying roads, which
-- is the whole reason elevation is here.
CREATE INDEX IF NOT EXISTS ix_roads_elevation_m ON roads (elevation_m);
