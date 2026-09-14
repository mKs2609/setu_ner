"""
Tests for hazard ingestion.

The unit half uses a fake HTTP opener and hand-built table rows, so it needs
neither the network nor a database and runs in CI. That matters more here
than elsewhere: the things most likely to go wrong in a scraper -- retrying
something it shouldn't, ignoring robots.txt, mis-reading a table section --
are exactly the things you cannot test by pointing it at the live site and
seeing that it worked today.

The integration half needs the corridor database and skips without it.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.ingestion import http_client
from app.services.ingestion.districts import normalise_district
from app.services.ingestion.http_client import (
    FetchError,
    PoliteClient,
    RobotsDisallowed,
)
from app.services.ingestion.sources import drims

client = TestClient(app)


# ---------------------------------------------------------------------------
# A fake opener, so the client can be tested without touching the network
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200, url: str = "http://x/", ctype="text/html"):
        self._body, self.status, self._url = body, status, url
        self.headers = {"Content-Type": ctype}

    def read(self, n: int = -1) -> bytes:
        return self._body if n < 0 else self._body[:n]

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Serves queued outcomes and records every URL it was asked for."""

    def __init__(self, script: dict[str, list]):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[str] = []

    def open(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        self.calls.append(url)
        for pattern, outcomes in self.script.items():
            if pattern in url:
                outcome = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        raise AssertionError(f"unexpected request to {url}")


def make_client(script, **kw) -> tuple[PoliteClient, FakeOpener]:
    opener = FakeOpener(script)
    slept: list[float] = []
    c = PoliteClient(
        opener=opener,
        crawl_delay=kw.pop("crawl_delay", 0.0),
        sleep=slept.append,
        **kw,
    )
    c._slept = slept  # type: ignore[attr-defined]
    return c, opener


def http_error(code: int):
    import urllib.error

    return urllib.error.HTTPError("http://x/", code, "err", {}, None)


# ---------------------------------------------------------------------------
# Politeness and safety
# ---------------------------------------------------------------------------


def test_robots_disallow_is_refused_not_fetched():
    """The whole point of checking robots.txt is not fetching the page."""
    c, opener = make_client(
        {
            "/robots.txt": [FakeResponse(b"User-agent: *\nDisallow: /secret")],
            "/secret/report": [FakeResponse(b"should never be read")],
        }
    )
    with pytest.raises(RobotsDisallowed):
        c.fetch("https://example.gov/secret/report")
    assert not any("/secret/report" in u for u in opener.calls)


def test_missing_robots_txt_means_allowed():
    """A 404 robots.txt publishes no rules, which conventionally means
    allow-all. Both cwc.gov.in and asdma.assam.gov.in are in this case."""
    c, _ = make_client(
        {"/robots.txt": [http_error(404)], "/report": [FakeResponse(b"data")]}
    )
    assert c.fetch("https://example.gov/report").content == b"data"


def test_robots_403_is_treated_as_stay_out():
    c, _ = make_client(
        {"/robots.txt": [http_error(403)], "/report": [FakeResponse(b"data")]}
    )
    with pytest.raises(RobotsDisallowed):
        c.fetch("https://example.gov/report")


def test_client_error_is_not_retried():
    """A 404 is a real answer. Retrying it just hammers the server for
    something it has already said it will not give."""
    c, opener = make_client(
        {"/robots.txt": [http_error(404)], "/missing": [http_error(404)]}
    )
    with pytest.raises(FetchError):
        c.fetch("https://example.gov/missing")
    assert sum("/missing" in u for u in opener.calls) == 1


def test_server_error_is_retried_then_gives_up():
    c, opener = make_client(
        {"/robots.txt": [http_error(404)], "/flaky": [http_error(503)]},
        max_retries=2,
    )
    with pytest.raises(FetchError):
        c.fetch("https://example.gov/flaky")
    assert sum("/flaky" in u for u in opener.calls) == 3  # initial + 2 retries


def test_retry_succeeds_after_a_transient_failure():
    c, _ = make_client(
        {
            "/robots.txt": [http_error(404)],
            "/flaky": [http_error(503), FakeResponse(b"finally")],
        },
        max_retries=2,
    )
    assert c.fetch("https://example.gov/flaky").content == b"finally"


def test_oversized_response_is_refused():
    """A redirect to something enormous must not be buffered into memory."""
    c, _ = make_client(
        {"/robots.txt": [http_error(404)], "/big": [FakeResponse(b"x" * 5000)]},
        max_bytes=1000,
    )
    with pytest.raises(FetchError, match="exceeded"):
        c.fetch("https://example.gov/big")


def test_crawl_delay_is_waited_out_between_requests():
    c, _ = make_client(
        {"/robots.txt": [http_error(404)], "/a": [FakeResponse(b"1")]},
        crawl_delay=2.0,
    )
    c.fetch("https://example.gov/a")
    c.fetch("https://example.gov/a")
    assert any(s > 0 for s in c._slept), "second request should have waited"


def test_user_agent_identifies_the_project():
    """An administrator seeing this in their logs should be able to tell what
    it is and that it is not commercial."""
    ua = http_client.USER_AGENT
    assert "SetuNER" in ua and "non-commercial" in ua


# ---------------------------------------------------------------------------
# District normalisation
# ---------------------------------------------------------------------------


def test_sribhumi_maps_to_karimganj():
    """Assam renamed Karimganj to Sribhumi in 2024; the road graph predates
    the rename. Without this the live feed would join to nothing and the
    corridor would look unaffected during a flood."""
    assert normalise_district("Sribhumi") == "Karimganj"
    assert normalise_district(" sribhumi ") == "Karimganj"


def test_north_cachar_hills_maps_to_dima_hasao():
    assert normalise_district("North Cachar Hills") == "Dima Hasao"


def test_district_names_broken_mid_word_by_the_pdf_still_map():
    """Every one of these was found stored with district NULL, which made
    those corridor rows invisible to routing, corroboration and the model."""
    assert normalise_district("Cacha r") == "Cachar"
    assert normalise_district("Hailakand i") == "Hailakandi"
    assert normalise_district("Hailakan di") == "Hailakandi"
    assert normalise_district("Sribhu mi") == "Karimganj"
    assert normalise_district("Dima- Hasao") == "Dima Hasao"


def test_letter_squashing_does_not_invent_a_match():
    assert normalise_district("Cachar West") is None
    assert normalise_district("hemaji") is None


def test_unknown_district_is_none_not_a_guess():
    assert normalise_district("Nagaon") is None
    assert normalise_district("") is None
    assert normalise_district(None) is None


# ---------------------------------------------------------------------------
# Report parsing
# ---------------------------------------------------------------------------


def test_squash_survives_labels_broken_mid_word():
    """The PDF wraps section labels inside words: "Infrastructu re Damaged"."""
    assert drims._squash("Infrastructu re Damaged - Road") == "infrastructuredamaged-road"
    assert drims._squash("Embankme nt Breached") == "embankmentbreached"


def test_relief_camp_inmates_is_not_read_as_camps_opened():
    """Regression: a keyword-matching version matched 'relief' against four
    different sections and produced 52 bogus rows from 6 real ones. Only
    exactly-registered section labels may parse."""
    assert drims._squash("Inmates In Relief Camps") not in drims.SECTION_METRICS
    assert (
        drims._squash("Non Camp Inmates in Relief Distribution Centers")
        not in drims.SECTION_METRICS
    )
    assert drims._squash("Relief Camps / Centres Opened") in drims.SECTION_METRICS


def test_parse_table_reads_district_rows_under_their_section():
    table = [
        ["Villages Affected", "District", "Total", "Revenue Circle"],
        [None, "Cachar", "5", "(Sonai | 5)"],
        [None, "Sribhumi", "0", "(Nilambazar | 0)"],
        [None, "Total", "99", None],
    ]
    out = drims._parse_table(table, "flood")
    by_place = {o.place_name: o for o in out}
    assert by_place["Cachar"].metric == "villages_affected"
    assert by_place["Cachar"].value_num == 5.0
    assert by_place["Sribhumi"].district == "Karimganj"
    assert "Total" not in by_place, "the totals row is not a district"


def test_unregistered_section_clears_state_and_emits_nothing():
    table = [
        ["Villages Affected", "District", "Total"],
        [None, "Cachar", "5"],
        ["Animals Affected", "District", "Total"],
        [None, "Cachar", "999"],
    ]
    out = drims._parse_table(table, "flood")
    assert [o.value_num for o in out] == [5.0], "only the registered section parses"


def test_camp_inmates_are_their_own_metric_not_camps_opened():
    """The original reason sections are registered exactly: an earlier parser
    read inmate counts as relief camps opened."""
    table = [
        ["Relief Camps / Centres Opened", "District", "Total"],
        [None, "Cachar", "27"],
        ["Inmates In Relief Camps", "District", "Total", "Revenue Circlewise", "Male", "Female", "Children"],
        [None, "Cachar", "5066", "(Silchar | 4146), (Udharbond | 626), (Lakhi", "2055", "2299", "710"],
    ]
    out = {(o.metric, o.place_name): o.value_num for o in drims._parse_table(table, "flood")}
    assert out[("relief_camps_opened", "Cachar")] == 27.0
    assert out[("relief_camp_inmates", "Cachar")] == 5066.0
    assert out[("relief_camp_inmates_children", "Cachar")] == 710.0
    assert out[("relief_camp_inmates_circle", "Silchar")] == 4146.0
    assert ("relief_camp_inmates_circle", "Lakhi") not in out, "a truncated entry is not a circle"


def test_2025_population_label_is_recognised():
    """The 2025 template says 'Affected' where 2026 says 'Submerged'; missing
    the alias silently dropped a whole season's population figures."""
    table = [
        ["Population And Crop Area Affected", "District", "Male", "Female", "Children", "Total"],
        [None, "Cachar", "40000", "40000", "23790", "103790", "460", "(Silchar | Population Affected: 57000 | Crop"],
    ]
    out = {(o.metric, o.place_name): o.value_num for o in drims._parse_table(table, "flood")}
    assert out[("population_affected", "Cachar")] == 103790.0
    assert out[("population_affected_circle", "Silchar")] == 57000.0


def test_infrastructure_damage_point_carries_coordinates():
    table = [
        ["Infrastructu re Damaged - Road", "District", "Number", "Revenue"],
        [None, "Cachar", "1", "(Sonai | 1)"],
        [None, None, None, "NH-6 washout", "92.74235 7", "24.83055 8"],
    ]
    out = drims._parse_table(table, "flood")
    points = [o for o in out if o.metric == "infrastructure_damage_point"]
    assert len(points) == 1
    assert points[0].lon == pytest.approx(92.742357)
    assert points[0].lat == pytest.approx(24.830558)
    assert points[0].place_name == "Cachar", "detail row belongs to the district above"


def test_coordinates_split_across_a_line_break_are_recovered():
    """Coordinate cells arrive as '92.74235 7' -- wrapped inside the digits."""
    assert drims._as_decimal_across_linebreak("92.74235 7") == pytest.approx(92.742357)


def test_two_integers_in_one_cell_are_never_joined():
    """The safety limit on that repair: only values with a decimal point are
    joined, so '1 2' can never silently become 12."""
    assert drims._as_decimal_across_linebreak("1 2") is None
    assert drims._as_decimal_across_linebreak("5") is None


def test_coordinates_outside_assam_are_rejected():
    assert drims._scan_coordinates([None, "0.5", "1.5"]) is None
    assert drims._scan_coordinates([None, "150.123456", "45.123456"]) is None


def test_dedupe_keeps_conflicting_values():
    """Repeats collapse only when the value matches. Two different values for
    the same district and metric is a parsing bug we want to see."""
    def obs(value):
        return drims.Observation(
            metric="villages_affected", value_num=value, value_text=None,
            unit="count", place_name="Cachar", district="Cachar", raw={},
        )

    assert len(drims._dedupe([obs(5.0), obs(5.0)])) == 1
    assert len(drims._dedupe([obs(5.0), obs(9.0)])) == 2


def test_unknown_hazard_type_is_rejected_before_any_request():
    c, opener = make_client({"/robots.txt": [http_error(404)]})
    with pytest.raises(ValueError, match="Unknown hazard"):
        drims.fetch_report(c, "volcano", date(2026, 9, 7))
    assert opener.calls == []


def test_html_response_means_no_report_for_that_date():
    """The form re-renders as HTML when a date has no report. That is a
    normal outcome, and must not look like a pipeline failure."""
    form = b'<input type="hidden" name="_token" value="abc123">'
    c, _ = make_client(
        {
            "/robots.txt": [http_error(404)],
            "/dfr/download": [
                FakeResponse(form),
                FakeResponse(b"<html>no report</html>", ctype="text/html"),
            ],
        }
    )
    with pytest.raises(FetchError, match="No flood report published"):
        drims.fetch_report(c, "flood", date(2026, 1, 1))


# ---------------------------------------------------------------------------
# API surface (no database needed)
# ---------------------------------------------------------------------------


def test_freshness_thresholds_are_published():
    """A caller has to be able to see where the fresh/stale boundary is."""
    from app.routers.hazards import _age_status

    now = datetime.now(timezone.utc)
    assert _age_status(now)[1] == "fresh"
    assert _age_status(now - timedelta(hours=48))[1] == "stale"
    assert _age_status(now - timedelta(days=10))[1] == "very_stale"
    assert _age_status(None) == (None, "unknown")


# ---------------------------------------------------------------------------
# Integration -- needs the corridor database
# ---------------------------------------------------------------------------


def _db_available() -> bool:
    try:
        from sqlalchemy import text

        from app.db.session import SessionLocal

        with SessionLocal() as db:
            db.execute(text("SELECT 1 FROM hazard_observations LIMIT 1"))
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(
    not _db_available(), reason="no hazard tables reachable (expected in CI)"
)


@needs_db
def test_freshness_endpoint_reports_age_and_runs():
    r = client.get("/api/v1/hazards/freshness")
    assert r.status_code == 200
    body = r.json()
    assert "sources" in body and "recent_runs" in body
    assert body["thresholds"]["fresh_within_hours"] > 0


@needs_db
def test_hazard_list_carries_freshness_with_the_data():
    """Age travels with the observations, so a caller cannot read a stale
    all-clear without also seeing how old it is."""
    r = client.get("/api/v1/hazards?hazard_type=flood&limit=5")
    assert r.status_code == 200
    body = r.json()
    assert "freshness" in body
    assert body["freshness"]["status"] in {"fresh", "stale", "very_stale", "unknown"}


@needs_db
def test_observation_keys_are_unique():
    """Idempotency is enforced by the database, not just by our checks."""
    from sqlalchemy import func, select

    from app.db.models import HazardObservation
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        total = db.execute(
            select(func.count(HazardObservation.id))
        ).scalar_one()
        distinct = db.execute(
            select(func.count(func.distinct(HazardObservation.observation_key)))
        ).scalar_one()
    assert total == distinct


def test_template_markers_identify_the_disaster_report():
    """A quiet day and an unreadable document both yield zero rows. The
    template markers are what tell them apart -- without this, pointing the
    job at the rainfall type (a different IMD bulletin) would look like a
    permanently quiet hazard rather than a parser that cannot read the file."""
    assert drims._squash("District Affected") in drims.TEMPLATE_MARKERS
    assert drims._squash("Infrastructu re Damaged - Road") in drims.TEMPLATE_MARKERS
    # The rainfall bulletin numbers its sections instead of naming them.
    assert drims._squash("1") not in drims.TEMPLATE_MARKERS
    assert drims._squash("State-wise Cumulated Rainfall Report") not in drims.TEMPLATE_MARKERS


def test_supported_hazards_is_narrower_than_what_the_endpoint_offers():
    """Honesty check: the runner must not imply it can read all nine."""
    from app.services.ingestion.run import SUPPORTED_HAZARDS

    assert SUPPORTED_HAZARDS < set(drims.HAZARD_TYPES)
    assert "rainfall" not in SUPPORTED_HAZARDS


# ---------------------------------------------------------------------------
# Population section -- read by arithmetic, not column position
# ---------------------------------------------------------------------------


def test_population_total_survives_a_shifted_column():
    """A real Cachar row from 6 Sep 2026. Reading column 5 returned 20, a
    component count; the total is 100."""
    from app.services.ingestion.sources.drims import _population_and_crop

    row = [None, "Cachar", "45", None, "35", "20", "100", None, "0"]
    assert _population_and_crop(row) == (100.0, 0.0)


def test_population_total_found_when_columns_are_not_shifted():
    from app.services.ingestion.sources.drims import _population_and_crop

    row = [None, "Nagaon", "4604", "3986", "1385", "9975", None, "4191.61", None, "(Rupahi | ...)"]
    assert _population_and_crop(row) == (9975.0, 4191.61)


def test_population_row_that_does_not_add_up_stores_nothing():
    """No consistent total means no number, never a guessed one."""
    from app.services.ingestion.sources.drims import _population_and_crop

    assert _population_and_crop([None, "X", "1", "2", "3", "7", "9"]) == (None, None)


def test_revenue_circle_breakdown_is_extracted_and_survives_truncation():
    from app.services.ingestion.sources.drims import _parse_population_row

    row = [
        None, "Nagaon", "4604", "3986", "1385", "9975", None, "4191.61", None,
        "(Rupahi | Population Affected: 2,721 | Crop Area Submerged: 428), "
        "(Samaguri | Population Affected: 7254 | Crop Area Submerged: 3673.61), (Nagaon | Popul",
    ]
    obs = _parse_population_row(row, "Nagaon", None, "flood", row)
    circles = {o.place_name: o.value_num for o in obs if o.metric == "population_affected_circle"}
    assert circles == {"Rupahi": 2721.0, "Samaguri": 7254.0}
    total = [o.value_num for o in obs if o.metric == "population_affected"]
    assert total == [9975.0]
