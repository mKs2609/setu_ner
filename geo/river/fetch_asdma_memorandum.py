"""
Phase 2: historical flood-impact data from ASDMA's annual Flood Memorandum.

The Assam Flood Memorandum is ASDMA's official annual report (submitted
for central relief-fund purposes) covering district-wise flood impact --
population affected, area inundated, damage estimates. This is exactly
the kind of source the demand-model calibration and historical-replay
work needs (see docs/decisions/0001-gap-analysis-and-enhancements.md
sections 2.4 and 7).

This is NOT live/real-time data -- it's an annual retrospective document.
Pair it with a live source (field reports, ASDMA Flood Alerts) for
current conditions; use this for calibration and backtesting.

URL pattern -- confirmed stable across 2016, 2018, 2020, 2022, 2023, 2024
(the one real inconsistency: 2024's filename has a trailing underscore
before .pdf that other years don't; this script tries both forms so one
odd year doesn't break the whole fetch):

    https://asdma.assam.gov.in/sites/default/files/swf_utility_folder/
        departments/asdma_revenue_uneecopscloud_com_oid_70/menu/document/
        assam_flood_memorandum_YYYY.pdf   (most years)
        assam_flood_memorandum_YYYY_.pdf  (2024, trailing underscore)

RUN THIS LOCALLY -- same reason as the other fetchers: government sites
aren't reachable from this project's dev sandbox.

    pip install -r requirements.txt
    python fetch_asdma_memorandum.py [year]

If no year is given, fetches the most recent one it can find, trying
backward from this year. We don't know the internal table structure of
these PDFs without seeing a real one (robots.txt blocked the automated
inspection this was built with), so this script extracts EVERYTHING --
full text plus every table found -- rather than guessing at column names
and filtering blindly like the CWC bulletin script could. It also
highlights any page mentioning our corridor's districts as a shortcut,
but the full extraction is what to actually rely on.
"""

import sys
import json
from datetime import date
from pathlib import Path

try:
    import requests
    import pdfplumber
except ImportError:
    print("Missing dependencies. Run: pip install -r requirements.txt")
    sys.exit(1)

HEADERS = {"User-Agent": "SetuNER-hazard-ingestion/0.1 (student project, non-commercial)"}
TIMEOUT = 30

BASE = (
    "https://asdma.assam.gov.in/sites/default/files/swf_utility_folder/"
    "departments/asdma_revenue_uneecopscloud_com_oid_70/menu/document/"
)

TARGET_KEYWORDS = ["CACHAR", "KARIMGANJ", "HAILAKANDI", "SILCHAR", "BARAK"]

OUTPUT_DIR = Path(__file__).parent


def candidate_urls(year: int) -> list[str]:
    return [
        f"{BASE}assam_flood_memorandum_{year}.pdf",
        f"{BASE}assam_flood_memorandum_{year}_.pdf",
    ]


def fetch_memorandum_pdf(start_year: int, years_back: int = 6) -> tuple[bytes, int] | None:
    for year in range(start_year, start_year - years_back, -1):
        for url in candidate_urls(year):
            print(f"-> Trying {url}")
            try:
                resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            except requests.exceptions.RequestException as e:
                print(f"   request failed: {e}")
                continue
            if resp.status_code == 200 and resp.content[:4] == b"%PDF":
                print(f"   found {year} memorandum ({len(resp.content) / 1024:.0f} KB)")
                return resp.content, year
            print(f"   status {resp.status_code}")
    return None


def extract_everything(pdf_bytes: bytes) -> dict:
    import io
    pages_text = []
    all_tables = []
    keyword_hits = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            pages_text.append({"page": page_num, "text": text})

            if any(kw in text.upper() for kw in TARGET_KEYWORDS):
                keyword_hits.append(page_num)

            for table in page.extract_tables():
                all_tables.append({"page": page_num, "table": table})

    return {
        "page_count": len(pages_text),
        "pages_text": pages_text,
        "tables": all_tables,
        "pages_mentioning_corridor_keywords": keyword_hits,
    }


def main():
    year_arg = sys.argv[1] if len(sys.argv) > 1 else None
    start_year = int(year_arg) if year_arg else date.today().year

    result = fetch_memorandum_pdf(start_year)
    if result is None:
        print(
            "\nCouldn't find a memorandum for any recent year at the expected "
            "path. The URL pattern held for 2016-2024 when this was written, "
            "but ASDMA's file structure could have changed since -- check "
            "https://asdma.assam.gov.in/documents-detail/assam-flood-memorandum "
            "by hand if this keeps failing."
        )
        sys.exit(1)

    pdf_bytes, found_year = result
    print(f"\nExtracting content from the {found_year} memorandum...")
    extracted = extract_everything(pdf_bytes)

    out_path = OUTPUT_DIR / f"asdma_memorandum_{found_year}_extracted.json"
    out_path.write_text(json.dumps(extracted, indent=2))

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Year: {found_year}")
    print(f"Pages: {extracted['page_count']}")
    print(f"Tables found: {len(extracted['tables'])}")
    if extracted["pages_mentioning_corridor_keywords"]:
        print(
            f"Pages mentioning our corridor's districts "
            f"({', '.join(TARGET_KEYWORDS)}): "
            f"{extracted['pages_mentioning_corridor_keywords']}"
        )
    else:
        print(
            "No pages matched our corridor keywords by simple text search -- "
            "doesn't necessarily mean the data isn't there (district names "
            "might only appear inside tables, which extract separately, or "
            "the document might use different naming). Check the tables and "
            "full text in the output file directly."
        )
    print(f"\nFull extraction saved to {out_path.name} -- open it and look for "
          f"the Cachar/Karimganj/Hailakandi rows by hand, since we don't yet "
          f"know this document's exact internal table structure.")


if __name__ == "__main__":
    main()