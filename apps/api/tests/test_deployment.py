"""
Tests for deployment readiness: operator tokens, the production guard, the
planner's concurrency limit, readiness, migrations and the image recipe.

Most of these run without a database or Docker, so CI checks them on every
push. The failure they guard against is always the same shape: a deployment
that starts, answers a health check, and is quietly unsafe or broken.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import security
from app.config import DEV_DATABASE_URL, Settings
from app.main import app

client = TestClient(app)
REPO = Path(__file__).resolve().parents[3]

TOKEN = "correct-horse-battery-staple-operator-token"


@pytest.fixture
def enforced(monkeypatch):
    """Tokens configured, as in any real deployment."""
    s = Settings(operator_token_hashes=[security.token_hash(TOKEN)], public_field_reports=False)
    monkeypatch.setattr(security, "get_settings", lambda: s)
    return s


def bearer(token: str = TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


def test_the_right_token_is_accepted(enforced):
    assert security.is_authorised(f"Bearer {TOKEN}")


@pytest.mark.parametrize("header", [None, "", "Bearer", "Bearer wrong", f"Basic {TOKEN}", TOKEN])
def test_anything_else_is_refused(enforced, header):
    assert not security.is_authorised(header)


def test_the_server_never_needs_the_raw_token():
    h = security.token_hash(TOKEN)
    assert len(h) == 64 and TOKEN not in h


def test_development_without_tokens_is_open(monkeypatch):
    monkeypatch.setattr(security, "get_settings", lambda: Settings(environment="development"))
    assert security.is_authorised(None)
    assert security.field_reports_open()


def test_production_without_tokens_is_closed_even_if_it_somehow_started(monkeypatch):
    monkeypatch.setattr(security, "get_settings", lambda: Settings(environment="production"))
    assert not security.is_authorised(None)
    assert not security.field_reports_open()


def test_public_field_reports_must_be_chosen_explicitly(monkeypatch):
    s = Settings(environment="production", operator_token_hashes=["a" * 64], public_field_reports=True)
    monkeypatch.setattr(security, "get_settings", lambda: s)
    assert security.field_reports_open()


# ---------------------------------------------------------------------------
# Endpoints refuse writes without a token -- before touching the database
# ---------------------------------------------------------------------------


def test_override_needs_a_token(enforced):
    r = client.post(
        f"/api/v1/recommendations/{'a' * 32}/overrides",
        json={"operator_id": "operator-1", "action": "rejected", "reason_category": "other",
              "reason": "bridge is out"},
    )
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == "Bearer"


def test_saving_a_plan_needs_a_token_but_planning_does_not(enforced):
    depot = {"name": "Silchar", "place": "Silchar", "stock": {"water": 1, "food": 1}, "trucks": 1}
    r = client.post("/api/v1/logistics/plan", json={"depots": [depot], "save": True})
    assert r.status_code == 401


def test_field_report_needs_a_token_when_not_public(enforced):
    r = client.post(
        "/api/v1/field-reports",
        json={"status": "blocked", "latitude": 24.83, "longitude": 92.78, "reporter_id": "device-xyz"},
    )
    assert r.status_code == 401


def test_planner_turns_requests_away_when_busy():
    from app.routers import logistics

    slots = []
    while logistics._plan_slots.acquire(blocking=False):
        slots.append(1)
    try:
        depot = {"name": "Silchar", "place": "Silchar", "stock": {"water": 1, "food": 1}, "trucks": 1}
        r = client.post("/api/v1/logistics/plan", json={"depots": [depot]})
        assert r.status_code == 429
        assert r.headers.get("retry-after")
    finally:
        for _ in slots:
            logistics._plan_slots.release()


# ---------------------------------------------------------------------------
# Production guard
# ---------------------------------------------------------------------------


def test_a_development_config_is_not_production_safe():
    problems = Settings(environment="production").production_problems()
    text = " ".join(problems)
    assert "OPERATOR_TOKEN_HASHES" in text
    assert "localhost" in text
    assert "DATABASE_URL" in text


@pytest.mark.parametrize(
    "url",
    [
        DEV_DATABASE_URL,
        "postgresql://someone:pw@localhost:5432/anything",
        "postgresql://someone:pw@127.0.0.1:5432/anything",
    ],
)
def test_a_local_database_is_refused_in_production_whatever_it_is_called(url):
    """The guard used to match one exact string, so renaming the development
    database silently switched it off."""
    s = Settings(
        environment="production", database_url=url,
        operator_token_hashes=[security.token_hash(TOKEN)],
        cors_allowed_origins=["https://setuner.example"],
    )
    assert any("DATABASE_URL" in p for p in s.production_problems())


def test_raw_tokens_in_the_hash_list_are_rejected():
    s = Settings(
        environment="production", operator_token_hashes=[TOKEN],
        cors_allowed_origins=["https://setuner.example"], database_url="postgresql://u:p@db/x",
    )
    assert any("SHA-256" in p for p in s.production_problems())


def test_wildcard_cors_is_rejected():
    s = Settings(
        environment="production", operator_token_hashes=[security.token_hash(TOKEN)],
        cors_allowed_origins=["*"], database_url="postgresql://u:p@db/x",
    )
    assert any("'*'" in p for p in s.production_problems())


def test_a_proper_production_config_passes():
    s = Settings(
        environment="production", operator_token_hashes=[security.token_hash(TOKEN)],
        cors_allowed_origins=["https://setuner.vercel.app"], database_url="postgresql://u:p@db/x",
    )
    assert s.production_problems() == []
    assert s.database_url != DEV_DATABASE_URL


# ---------------------------------------------------------------------------
# Migrations and the image recipe (no database, no Docker)
# ---------------------------------------------------------------------------


def test_migrations_are_numbered_and_idempotent_in_form():
    from app.db.migrate import migration_files

    files = migration_files()
    numbers = [int(f.name[:4]) for f in files]
    assert numbers == sorted(numbers) and len(set(numbers)) == len(numbers)
    for f in files:
        sql = f.read_text(encoding="utf-8")
        for stmt in re.findall(r"(CREATE TABLE|CREATE INDEX|ADD COLUMN)(?! IF NOT EXISTS)", sql):
            pytest.fail(f"{f.name}: '{stmt}' without IF NOT EXISTS is not safe to re-run")


def test_every_file_the_dockerfile_copies_exists():
    dockerfile = (REPO / "apps" / "api" / "Dockerfile").read_text(encoding="utf-8")
    sources = [line.split()[1] for line in dockerfile.splitlines() if line.startswith("COPY ")]
    assert sources
    for src in sources:
        matches = list(REPO.glob(src)) if any(c in src for c in "*?") else [REPO / src]
        assert matches and all(m.exists() for m in matches), f"Dockerfile copies missing {src}"


def test_the_image_does_not_run_as_root():
    dockerfile = (REPO / "apps" / "api" / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^USER (?!root)\S+", dockerfile, re.M)


def test_runtime_data_files_are_committed_and_shipped():
    """geo/**/*.json is ignored (most of it is large and rebuildable). The
    files the API reads at runtime must be the exceptions, and both images
    must carry them -- otherwise the deploy builds and then fails on the
    first forecast page, which is what the gazetteer once did."""
    import subprocess

    runtime = ["geo/gazetteer/corridor_places.json", "geo/rainfall/assam_district_points.json"]
    for path in runtime:
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", path], cwd=REPO, capture_output=True
        ).returncode == 0
        assert not ignored, f"{path} is gitignored, so the deploy would not have it"
    render = (REPO / "apps" / "api" / "Dockerfile").read_text(encoding="utf-8")
    space = (REPO / "deploy" / "huggingface" / "Dockerfile").read_text(encoding="utf-8")
    for path in runtime:
        assert path in render, f"apps/api/Dockerfile does not copy {path}"
        assert path in space, f"deploy/huggingface/Dockerfile does not copy {path}"
    assert "SETUNER_DISTRICT_POINTS=" in render and "SETUNER_DISTRICT_POINTS=" in space


def test_database_dumps_can_never_be_committed():
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "data/deploy/" in ignore and "*.dump" in ignore


# ---------------------------------------------------------------------------
# Integration -- needs the corridor database
# ---------------------------------------------------------------------------


def _db_available() -> bool:
    try:
        from sqlalchemy import text

        from app.db.session import SessionLocal

        with SessionLocal() as db:
            db.execute(text("SELECT 1 FROM roads LIMIT 1"))
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(not _db_available(), reason="no corridor database (expected in CI)")


@needs_db
def test_readiness_names_every_check():
    r = client.get("/api/v1/health/ready")
    body = r.json()
    assert r.status_code in (200, 503)
    assert {
        "database", "postgis", "tables", "migrations", "model_artifacts", "gazetteer",
        "rainfall_points", "rainfall_freshness",
    } <= set(body["checks"])
    assert body["ready"] == (r.status_code == 200)


@needs_db
def test_report_freshness_is_the_report_feeds_own_date():
    """A fresh rainfall day must not stand in for a missing report: the
    weekly check is how a dead ASDMA feed gets noticed."""
    from sqlalchemy import text

    from app.db.session import SessionLocal
    from app.services.ingestion.sources import drims

    with SessionLocal() as db:
        report = db.execute(text(
            "SELECT max(target_date) FROM ingest_runs "
            "WHERE status='success' AND source=:s AND hazard_type='flood'"
        ), {"s": drims.SOURCE_NAME}).scalar()
    body = client.get("/api/v1/health/ready").json()
    got = body["checks"]["data_freshness"]["latest_report"]
    assert got == (report.isoformat() if report else None)


@needs_db
def test_local_schema_has_no_pending_migrations():
    from app.db.migrate import run

    assert run(status_only=True) == []


# ---------------------------------------------------------------------------
# List settings accept what people type into hosting dashboards
# ---------------------------------------------------------------------------

HASH_A = "a" * 64
HASH_B = "b" * 64


@pytest.mark.parametrize(
    "raw,expected",
    [
        (f'["{HASH_A}"]', [HASH_A]),                       # JSON, as documented
        (HASH_A, [HASH_A]),                                # a bare hash: the first real deploy
        (f"{HASH_A},{HASH_B}", [HASH_A, HASH_B]),          # comma-separated
        (f" {HASH_A} , {HASH_B} ", [HASH_A, HASH_B]),      # with stray spaces
        (f'["{HASH_A}", "{HASH_B}"]', [HASH_A, HASH_B]),
        ("", []),
    ],
)
def test_token_hashes_accept_every_reasonable_form(monkeypatch, raw, expected):
    monkeypatch.setenv("OPERATOR_TOKEN_HASHES", raw)
    assert Settings().operator_token_hashes == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('["https://a.example"]', ["https://a.example"]),
        ("https://a.example", ["https://a.example"]),
        ("https://a.example,https://b.example", ["https://a.example", "https://b.example"]),
    ],
)
def test_cors_origins_accept_every_reasonable_form(monkeypatch, raw, expected):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", raw)
    assert Settings().cors_allowed_origins == expected


def test_a_bare_hash_still_authorises(monkeypatch):
    """The end-to-end version of the bug: a bare hash in the environment has
    to produce a working deployment, not a stack trace at import time."""
    monkeypatch.setenv("OPERATOR_TOKEN_HASHES", security.token_hash(TOKEN))
    s = Settings()
    monkeypatch.setattr(security, "get_settings", lambda: s)
    assert security.is_authorised(f"Bearer {TOKEN}")
    assert not security.is_authorised("Bearer nope")


# ---------------------------------------------------------------------------
# Daily job: an unreachable portal is skipped quickly, not retried for an hour
# ---------------------------------------------------------------------------


def test_daily_job_skips_ingestion_when_the_portal_does_not_answer(monkeypatch, capsys):
    """The first hosted run spent 17 minutes on one request from GitHub's US
    runners. Unreachable must mean: skip ingestion, still score, report why,
    exit non-zero."""
    import subprocess

    from app.jobs import daily

    ran = []

    class Done:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(daily, "portal_reachable", lambda: (False, "TimeoutError: timed out"))
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: ran.append(args[2]) or Done())

    assert daily.main() == 1
    # Rainfall comes from NASA, not the portal, so it still runs -- and it
    # runs before scoring, which may need it.
    assert ran == [
        "app.services.weather.ingest",
        "app.services.model.damage_matching",
        "app.services.model.score",
    ]
    assert "does not answer from outside India" in capsys.readouterr().out


def test_daily_job_runs_every_step_when_the_portal_answers(monkeypatch):
    import subprocess

    from app.jobs import daily

    ran = []

    class Done:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(daily, "portal_reachable", lambda: (True, "ok"))
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: ran.append(args[2]) or Done())

    assert daily.main() == 0
    assert ran == [
        "app.services.ingestion.run",
        "app.services.ingestion.run",
        "app.services.weather.ingest",
        "app.services.model.damage_matching",
        "app.services.model.score",
    ]


@needs_db
def test_road_map_is_built_by_postgis_and_gzipped():
    """The Cachar map (51,839 roads) ran the 512 MB host out of memory when
    it was built object by object in Python. It must come back gzipped, with
    the same feature shape the web map reads."""
    r = client.get(
        "/api/v1/roads/geojson", params={"district": "Hailakandi"},
        headers={"Accept-Encoding": "gzip"},
    )
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"
    body = r.json()
    assert body["type"] == "FeatureCollection"
    assert body["meta"]["count"] == len(body["features"]) > 0
    f = body["features"][0]
    assert isinstance(f["id"], int)
    assert f["geometry"]["type"] == "LineString"
    assert {
        "road_class", "is_bridge", "district", "baseline_accessibility",
        "current_accessibility", "hazard_exposure", "current_accessibility_as_of",
    } <= set(f["properties"])
    # 5 decimal places at most: the rounding that keeps the payload small.
    lon = str(f["geometry"]["coordinates"][0][0])
    assert len(lon.split(".")[1]) <= 5
