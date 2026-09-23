"""
Throwaway data-access check: CWC / India-WRIS / National Water Data Portal (NWDP)

WHY THIS EXISTS
----------------
The project's data pipeline assumes rainfall + river-level data is reachable
from CWC's National Water Data Portal. Research turned up that this is real
data, but likely served as periodic CSV batch downloads rather than a live
API, with the Brahmaputra sitting in CWC's more restricted "classified"
river bucket. This script exists to find out, concretely, what we actually
get before we design the ingestion service around an assumption.

RUN THIS LOCALLY (e.g. from your VS Code terminal), not in a restricted
sandbox -- it needs open internet access to reach Indian government domains.

    pip install requests
    python check_cwc_nwdp_access.py

WHAT IT DOES
------------
1. Hits the NWDP dataset catalog and the India-WRIS portal to confirm they're
   reachable at all, and print status codes + response shape (HTML vs JSON).
2. Tries a couple of plausible NWDP dataset/API URL patterns for river water
   level + rainfall, since the exact endpoint shape wasn't confirmed from
   documentation alone.
3. Prints a clear summary: what's reachable, what looks like structured data
   vs an HTML portal page, and what that means for the ingestion design.

This is NOT meant to be production ingestion code. It's meant to answer:
"can we get real Assam/Brahmaputra rainfall + river-level data, and in what
shape, before we lock the corridor and build against it."
"""

import sys
import json
from datetime import datetime

try:
    import requests
except ImportError:
    print("This script needs `requests`. Run: pip install requests")
    sys.exit(1)

TIMEOUT = 15
HEADERS = {"User-Agent": "SetuNER-data-access-check/0.1 (+https://github.com/mKs2609/setu_ner; non-commercial research)"}

CHECKS = [
    {
        "name": "NWDP portal root",
        "url": "https://nwdp.nwic.gov.in/",
        "note": "Should confirm the portal itself is up.",
    },
    {
        "name": "NWDP dataset: River Water Level Telemetry Hourly (CWC)",
        "url": "https://nwdp.nwic.gov.in/dataset/river-water-level-telemetry-hourly-central-water-commission-cwc",
        "note": "Known-good page from research -- confirm it still resolves and see what format the data links are in.",
    },
    {
        "name": "India-WRIS portal root",
        "url": "https://indiawris.gov.in/",
        "note": "Confirm reachability; this is the newer WRIS front end.",
    },
    {
        "name": "India-WRIS time-series wiki (docs on data granularity)",
        "url": "https://indiawris.gov.in/wiki/doku.php?id=wris_time_series_data",
        "note": "Documentation page, not data -- useful to confirm what granularity is even claimed.",
    },
    {
        "name": "CWC flood forecasting portal (used by researchers for NRT scraping)",
        "url": "https://ffs.india-water.gov.in/",
        "note": "This is the portal a published research pipeline scraped for near-real-time data -- may need different handling than a REST client.",
    },
]


def check_url(entry):
    url = entry["url"]
    result = {"name": entry["name"], "url": url, "note": entry["note"]}
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        result["status_code"] = resp.status_code
        result["final_url"] = resp.url
        content_type = resp.headers.get("Content-Type", "")
        result["content_type"] = content_type
        result["bytes"] = len(resp.content)

        if "json" in content_type.lower():
            result["shape"] = "JSON (structured -- good sign for an API-style ingestion)"
            try:
                result["json_preview"] = json.dumps(resp.json(), indent=2)[:500]
            except Exception:
                pass
        elif "csv" in content_type.lower() or url.lower().endswith(".csv"):
            result["shape"] = "CSV (structured, but batch-file style, not a live API)"
        elif "html" in content_type.lower():
            result["shape"] = "HTML (portal page -- likely needs scraping/parsing, not a clean API call)"
        else:
            result["shape"] = f"Unrecognized ({content_type or 'no content-type header'})"

    except requests.exceptions.Timeout:
        result["status_code"] = None
        result["shape"] = "TIMED OUT"
    except requests.exceptions.SSLError as e:
        result["status_code"] = None
        result["shape"] = f"SSL ERROR: {e}"
    except requests.exceptions.RequestException as e:
        result["status_code"] = None
        result["shape"] = f"REQUEST FAILED: {e}"

    return result


def main():
    print(f"CWC / India-WRIS / NWDP data-access check -- {datetime.now().isoformat()}\n")
    results = []
    for entry in CHECKS:
        print(f"-> {entry['name']}")
        r = check_url(entry)
        results.append(r)
        status = r.get("status_code", "N/A")
        print(f"   status: {status}  shape: {r.get('shape')}")
        if r.get("json_preview"):
            print(f"   preview: {r['json_preview'][:200]}...")
        print()

    print("=" * 70)
    print("SUMMARY -- read this before designing the ingestion service")
    print("=" * 70)
    reachable = [r for r in results if r.get("status_code") == 200]
    print(f"Reachable (HTTP 200): {len(reachable)}/{len(results)}")
    for r in reachable:
        print(f"  - {r['name']}: {r['shape']}")

    unreachable = [r for r in results if r.get("status_code") != 200]
    if unreachable:
        print(f"\nNot reachable / non-200:")
        for r in unreachable:
            print(f"  - {r['name']}: status={r.get('status_code')}, {r.get('shape')}")

    print(
        "\nDecision guide:\n"
        "  - If everything comes back HTML -> plan on a scraper + scheduled job,\n"
        "    not a REST client. Budget accordingly.\n"
        "  - If any CSV dataset links resolve -> good, but confirm update\n"
        "    frequency and whether Assam/Brahmaputra stations are actually in it\n"
        "    (open the CSV and check station list, don't assume).\n"
        "  - If ffs.india-water.gov.in resolves with real station data -> that's\n"
        "    likely your best near-real-time source; treat it like the GUARDIAN\n"
        "    paper did (a scrape target, with retry + staleness tracking), not\n"
        "    an official supported API.\n"
        "  - Either way: DO NOT design docstrings/schemas assuming a JSON API\n"
        "    exists until one of these checks actually shows JSON.\n"
    )


if __name__ == "__main__":
    main()
