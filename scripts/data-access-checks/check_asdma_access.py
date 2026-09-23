"""
Throwaway data-access check: ASDMA (Assam State Disaster Management
Authority) and NESAC-derived flood alerts / reports.

WHY THIS EXISTS
----------------
ASDMA is a real, active source that publishes Flood Alerts built on NESAC's
hydro-meteorological analysis, plus periodic Flood Reports and Flood
Memoranda. Research suggests these are bulletin/PDF-shaped, not API-shaped.
This script confirms that, and -- if PDFs are involved -- checks what a
document-parsing ingestion path would actually be dealing with.

RUN THIS LOCALLY, not in a restricted sandbox.

    pip install requests
    python check_asdma_access.py
"""

import sys
from datetime import datetime

try:
    import requests
except ImportError:
    print("This script needs `requests`. Run: pip install requests")
    sys.exit(1)

TIMEOUT = 15
HEADERS = {"User-Agent": "SetuNER-data-access-check/0.1 (+https://github.com/mKs2609/setu_ner; non-commercial research)"}

CHECKS = [
    {"name": "ASDMA home", "url": "https://asdma.assam.gov.in/"},
    {"name": "ASDMA Flood Alerts page", "url": "https://asdma.assam.gov.in/resource/flood-alerts"},
    {"name": "ASDMA Assam Flood Report", "url": "https://asdma.assam.gov.in/information-services/assam-flood-report"},
    {"name": "ASDMA Flood Memorandum", "url": "https://asdma.assam.gov.in/documents-detail/assam-flood-memorandum"},
    {"name": "ASDMA NRSC inundation mapping page", "url": "https://asdma.assam.gov.in/resource/inundation-mapping-nrsc"},
]


def check_url(entry):
    url = entry["url"]
    result = {"name": entry["name"], "url": url}
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        result["status_code"] = resp.status_code
        content_type = resp.headers.get("Content-Type", "")
        result["content_type"] = content_type
        result["bytes"] = len(resp.content)

        if "pdf" in content_type.lower():
            result["shape"] = "PDF -- confirms a document-parsing ingestion path is needed"
        elif "html" in content_type.lower():
            # look for obvious PDF links on the page as a cheap signal
            pdf_link_count = resp.text.lower().count(".pdf")
            result["shape"] = f"HTML page ({pdf_link_count} '.pdf' references found in page source)"
        else:
            result["shape"] = f"Unrecognized ({content_type or 'no content-type header'})"

    except requests.exceptions.Timeout:
        result["status_code"] = None
        result["shape"] = "TIMED OUT"
    except requests.exceptions.RequestException as e:
        result["status_code"] = None
        result["shape"] = f"REQUEST FAILED: {e}"

    return result


def main():
    print(f"ASDMA data-access check -- {datetime.now().isoformat()}\n")
    results = []
    for entry in CHECKS:
        print(f"-> {entry['name']}")
        r = check_url(entry)
        results.append(r)
        print(f"   status: {r.get('status_code')}  shape: {r.get('shape')}")
        print()

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    reachable = [r for r in results if r.get("status_code") == 200]
    print(f"Reachable (HTTP 200): {len(reachable)}/{len(results)}")
    for r in results:
        print(f"  - {r['name']}: status={r.get('status_code')}, {r.get('shape')}")

    print(
        "\nDecision guide:\n"
        "  - If pages show PDF references -> build a small scheduled fetcher\n"
        "    + PDF text/table extraction step (this is a document-ingestion\n"
        "    problem, same pattern needed for ASDMA Flood Reports/Memoranda).\n"
        "  - Cross-check whatever you find against the actual PDFs by hand for\n"
        "    the Barak Valley / Cachar / Dima Hasao district specifically --\n"
        "    district-level granularity is what matters for the corridor\n"
        "    decision, not whether the portal exists.\n"
        "  - If ASDMA's contact/data-request page is reachable, consider actually\n"
        "    emailing them -- state disaster authorities sometimes grant more\n"
        "    direct data access to student/research projects than what's public.\n"
    )


if __name__ == "__main__":
    main()
