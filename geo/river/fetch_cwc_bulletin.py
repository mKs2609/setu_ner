"""
SUPERSEDED -- AND CURRENTLY BROKEN. Do not rely on this script.

Verified 8 Sep 2026: the dated URL pattern below returns 404 for every
date across a week of checks, and the listing page at
cwc.gov.in/en/fmo/dfsra now renders its publication table with no rows
at all. CWC appears to have stopped publishing these bulletins at this
location, so this script cannot succeed as written.

Live hazard ingestion moved to apps/api/app/services/ingestion/, which
pulls the DRIMS Assam daily report instead. That source is live, covers
nine hazard types, reports road and bridge damage per district, and
quotes the same CWC river danger-level line this script wanted -- so
nothing was lost in the move. See docs/decisions/0004.

Kept in the tree because the URL pattern and the parsing approach are
still the right starting point if CWC resumes publishing.

Original header follows.

Phase 2: real-time flood/river hazard data for the Barak Valley corridor.

Fetches CWC's Daily Flood Situation Report cum Advisory -- a real, dated
bulletin published as a PDF -- and extracts rows for stations relevant to
our corridor (Barak river, Cachar/Karimganj/Hailakandi districts).

Why this approach and not a "clean API": confirmed via research (see
docs/decisions/0001-gap-analysis-and-enhancements.md) that CWC/NWDP has no
live JSON API. ffs.india-water.gov.in is a JavaScript single-page app --
its real data comes from an internal API we don't have documented access
to, so scraping its rendered HTML won't work. The daily bulletin PDF at a
stable, dated URL pattern is the reliable target instead.

URL pattern (confirmed stable across 2021-2023 real bulletins):
    https://cwc.gov.in/en/daily-flood-situation-report-cum-advisory-dated-DDMMYYYY

RUN THIS LOCALLY -- cwc.gov.in isn't reachable from this project's dev
sandbox either (same allowlist restriction as the earlier data-access
checks).

    pip install -r requirements.txt
    python fetch_cwc_bulletin.py

By default fetches TODAY's bulletin, falling back to the previous few days
if today's isn't published yet (bulletins can lag by a day). Prints
whatever it finds for our target stations, and saves the full parsed table
to bulletin_output.json regardless -- useful even if none of our specific
stations show up on a quiet-weather day.
"""

import sys
import re
import json
from datetime import date, timedelta
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
    import pdfplumber
except ImportError:
    print("Missing dependencies. Run: pip install -r requirements.txt")
    sys.exit(1)

HEADERS = {"User-Agent": "SetuNER-hazard-ingestion/0.1 (student project, non-commercial)"}
TIMEOUT = 20

# Stations/rivers/districts relevant to the locked Barak Valley corridor.
# Matched case-insensitively against every cell in the parsed table, so
# this catches the row regardless of which column the match lands in.
TARGET_KEYWORDS = [
    "BARAK", "CACHAR", "KARIMGANJ", "HAILAKANDI", "SILCHAR",
    "ANNAPURNA GHAT", "BADARPUR GHAT",
]

OUTPUT_PATH = Path(__file__).parent / "bulletin_output.json"


def landing_page_url(d: date) -> str:
    return f"https://cwc.gov.in/en/daily-flood-situation-report-cum-advisory-dated-{d.strftime('%d%m%Y')}"


def find_pdf_link(landing_html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(landing_html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".pdf"):
            if href.startswith("http"):
                return href
            if href.startswith("/"):
                return "https://cwc.gov.in" + href
            return base_url.rsplit("/", 1)[0] + "/" + href
    return None


def fetch_bulletin_pdf_bytes(max_days_back: int = 5) -> tuple[bytes, date] | None:
    """Try today, then walk backward -- bulletins can lag a day or two,
    and some days may not have one at all (e.g. off-season)."""
    today = date.today()
    for offset in range(max_days_back):
        d = today - timedelta(days=offset)
        url = landing_page_url(d)
        print(f"-> Checking {url}")
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        except requests.exceptions.RequestException as e:
            print(f"   request failed: {e}")
            continue
        if resp.status_code != 200:
            print(f"   status {resp.status_code}, trying an earlier date")
            continue
        pdf_url = find_pdf_link(resp.text, url)
        if not pdf_url:
            print("   no PDF link found on this page, trying an earlier date")
            continue
        print(f"   found PDF: {pdf_url}")
        pdf_resp = requests.get(pdf_url, headers=HEADERS, timeout=TIMEOUT)
        if pdf_resp.status_code == 200 and pdf_resp.content[:4] == b"%PDF":
            return pdf_resp.content, d
        print(f"   PDF download failed or wasn't a real PDF (status {pdf_resp.status_code})")
    return None


def parse_bulletin_tables(pdf_bytes: bytes) -> list[dict]:
    """Extract every table row from the PDF, keeping only rows that
    mention one of our target keywords anywhere in the row."""
    matches = []
    with pdfplumber.open(__import__("io").BytesIO(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row is None:
                        continue
                    row_text = " ".join(c for c in row if c).upper()
                    if any(kw in row_text for kw in TARGET_KEYWORDS):
                        matches.append({"page": page_num, "row": row})
    return matches


def main():
    result = fetch_bulletin_pdf_bytes()
    if result is None:
        print(
            "\nCouldn't find a bulletin in the last few days. This could mean: "
            "the URL pattern has changed since it was last confirmed (2021-2023 "
            "bulletins), or there's genuinely no bulletin right now. Try opening "
            "https://cwc.gov.in/en/fmo/dfsra by hand to check the current pattern."
        )
        sys.exit(1)

    pdf_bytes, bulletin_date = result
    print(f"\nParsing bulletin dated {bulletin_date.isoformat()}...")
    matches = parse_bulletin_tables(pdf_bytes)

    output = {
        "bulletin_date": bulletin_date.isoformat(),
        "target_keywords": TARGET_KEYWORDS,
        "matched_rows": matches,
    }
    OUTPUT_PATH.write_text(json.dumps(output, indent=2))

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    if matches:
        print(f"Found {len(matches)} row(s) matching our corridor's stations/rivers/districts:")
        for m in matches:
            print(f"  page {m['page']}: {m['row']}")
    else:
        print(
            "No rows matched our target keywords in this bulletin. This can "
            "genuinely happen on a quiet-weather day -- the bulletin only lists "
            "stations with an active forecast, not every station in the network. "
            "The full parsed output is still saved for inspection."
        )
    print(f"\nFull output saved to {OUTPUT_PATH.name}")


if __name__ == "__main__":
    main()