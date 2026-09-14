-- 0003: Phase 6 audit trail (see docs/decisions/0012).
--
-- Saved recommendations are immutable; overrides are append-only. Safe to
-- run more than once.
--
--   psql "$DATABASE_URL" -f infra/migrations/0003_recommendations_audit.sql

CREATE TABLE IF NOT EXISTS recommendations (
    id VARCHAR PRIMARY KEY,
    kind VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    data_as_of DATE NOT NULL,
    is_replay BOOLEAN NOT NULL,
    example_inputs BOOLEAN NOT NULL,
    model_versions JSON NOT NULL,
    inputs JSON NOT NULL,
    outputs JSON NOT NULL,
    explanation JSON NOT NULL,
    label VARCHAR
);
CREATE INDEX IF NOT EXISTS ix_recommendations_kind ON recommendations (kind);
CREATE INDEX IF NOT EXISTS ix_recommendations_created_at ON recommendations (created_at);
CREATE INDEX IF NOT EXISTS ix_recommendations_data_as_of ON recommendations (data_as_of);

CREATE TABLE IF NOT EXISTS recommendation_overrides (
    id SERIAL PRIMARY KEY,
    recommendation_id VARCHAR NOT NULL REFERENCES recommendations (id),
    created_at TIMESTAMPTZ NOT NULL,
    operator_id VARCHAR NOT NULL,
    action VARCHAR NOT NULL,
    target VARCHAR,
    reason_category VARCHAR NOT NULL,
    reason TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_recommendation_overrides_recommendation_id ON recommendation_overrides (recommendation_id);
CREATE INDEX IF NOT EXISTS ix_recommendation_overrides_created_at ON recommendation_overrides (created_at);
CREATE INDEX IF NOT EXISTS ix_recommendation_overrides_operator_id ON recommendation_overrides (operator_id);
CREATE INDEX IF NOT EXISTS ix_recommendation_overrides_action ON recommendation_overrides (action);
CREATE INDEX IF NOT EXISTS ix_recommendation_overrides_reason_category ON recommendation_overrides (reason_category);
