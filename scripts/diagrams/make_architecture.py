"""Generate the README architecture diagram, light and dark, from one definition.

Run it from anywhere:  python scripts/diagrams/make_architecture.py

Re-run whenever a figure in the diagram changes. The numbers are stated once,
here, rather than redrawn by hand in two files that then disagree.

Two files are needed because GitHub picks between them with <picture> and a
prefers-color-scheme media query; generating both from the same structure is
the only way they stay in step.

Box heights are measured from the content in a first pass rather than guessed,
because a hand-set height is wrong the moment a line of text changes.
"""

import pathlib

OUT = pathlib.Path(__file__).resolve().parents[2] / "docs" / "images"

LIGHT = {
    "bg": "#fbfaff", "surface": "#ffffff", "ink": "#100f12", "muted": "#6f6b7a",
    "line": "#e7e3f0", "accent": "#8d6fde", "wash": "#f4f1fd", "arrow": "#b9b2cc",
}
DARK = {
    "bg": "#131118", "surface": "#1c1926", "ink": "#f1eff7", "muted": "#9d97ad",
    "line": "#302a40", "accent": "#a98ae8", "wash": "#231f30", "arrow": "#4a4259",
}

W = 1000
COLS = [(24, 180), (240, 172), (448, 150), (634, 180), (850, 126)]

COLUMNS = [
    ("Sources", "FOUR FEEDS", [
        ("ASDMA DRIMS", "daily flood PDF — the one scraped source"),
        ("NASA GPM IMERG", "satellite rainfall over OPeNDAP"),
        ("OpenStreetMap", "road graph via Overpass · one-off"),
        ("Copernicus DEM", "elevation by range request · one-off"),
    ]),
    ("Ingestion", "DATA ENGINEERING", [
        ("Polite client", "robots.txt, crawl delay, size caps"),
        ("PDF parser", "pdfplumber + district-name repair"),
        ("Grid alignment check", "refuses a grid whose axes moved"),
        ("Run log", "written before each attempt starts"),
    ]),
    ("Store", "DATA MODELLING", [
        ("PostgreSQL 16", "+ PostGIS 3.3 · Neon, Singapore"),
        ("110,266 roads", "graph, terrain, gazetteer"),
        ("336 daily reports", "observations, runs, forecasts"),
        ("Idempotent migrations", "re-runnable, applied on boot"),
    ]),
    ("Model & planning", "ML + OPTIMISATION", [
        ("Flood-state model", "logistic at 1 day, persistence at 3"),
        ("Shadow challenger", "with rainfall · frozen, not served"),
        ("Per-road scoring", "terrain exposure prior · 71,520 roads"),
        ("Relief planner", "OR-Tools lexicographic LP"),
    ]),
    ("Serve", "BACKEND + FRONTEND", [
        ("FastAPI", "31 endpoints · Render"),
        ("Next.js 14", "MapLibre GL · Vercel"),
        ("Every number", "carries its source and age"),
        ("Readiness endpoint", "ten checks · what Render gates on"),
        ("Field reports in", "public POST · corroborated, never overwrite"),
    ]),
]

FOOT = [
    ("Daily job — 07:30 IST, on a machine in India",
     "ASDMA does not answer hosts outside India, so the scheduler cannot live "
     "in the cloud. Catch-up fetches the oldest owed day first."),
    ("Watcher — GitHub Actions, four times a day",
     "Asks four questions and fails if any answer is wrong, so the failure is "
     "the alert. Deliberately not on the machine it watches."),
]

TOP = 78
BODY_TOP = TOP + 46
ROW_GAP = 26
LINE_H = 11


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def wrap(text, limit):
    words, line, lines = text.split(), "", []
    for word in words:
        trial = f"{line} {word}".strip()
        if len(trial) > limit and line:
            lines.append(line)
            line = word
        else:
            line = trial
    lines.append(line)
    return lines


def column_height(w, rows):
    """How tall this column's content actually is."""
    h = 8
    for _, detail in rows:
        h += ROW_GAP + LINE_H * len(wrap(detail, int((w - 30) / 4.55)))
    return h + 6


def build(p):
    # --- pass one: how tall must the boxes be?
    col_h = max(column_height(w, COLUMNS[i][2]) for i, (_, w) in enumerate(COLS))
    foot_lines = max(len(wrap(d, 64)) for _, d in FOOT)
    # Last baseline sits at fy + 55 + (n-1)*LINE_H; the box must clear it.
    foot_h = 48 + LINE_H * foot_lines
    fy = BODY_TOP - 12 + col_h + 34
    H = int(fy + foot_h + 20)

    o = []
    a = o.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
      f'width="{W}" height="{H}" font-family="Segoe UI, Helvetica, Arial, sans-serif" '
      f'role="img" aria-label="SetuNER architecture in five stages: data sources, '
      f'ingestion, a PostGIS store, the model and relief planner, and the API and map '
      f'that serve them — with a daily job and an independent watcher underneath.">')
    a(f'<rect width="{W}" height="{H}" fill="{p["bg"]}"/>')

    a(f'<text x="24" y="34" font-size="17" font-weight="700" fill="{p["ink"]}">'
      f'SetuNER — how a government PDF becomes a route</text>')
    a(f'<text x="24" y="54" font-size="11.5" fill="{p["muted"]}">'
      f'Every stage records what it did, so a failure shows up as a failure rather '
      f'than as an empty map.</text>')

    for i, (x, w) in enumerate(COLS):
        title, discipline, rows = COLUMNS[i]

        a(f'<text x="{x}" y="{TOP + 12}" font-size="9" font-weight="700" '
          f'fill="{p["accent"]}">{i + 1}</text>')
        a(f'<text x="{x + 14}" y="{TOP + 12}" font-size="12.5" font-weight="700" '
          f'fill="{p["ink"]}">{esc(title)}</text>')
        a(f'<text x="{x}" y="{TOP + 29}" font-size="8.6" letter-spacing="0.7" '
          f'fill="{p["muted"]}">{esc(discipline)}</text>')

        a(f'<rect x="{x}" y="{BODY_TOP - 12}" width="{w}" height="{col_h}" rx="7" '
          f'fill="{p["surface"]}" stroke="{p["line"]}"/>')

        y = BODY_TOP + 8
        for bold, detail in rows:
            lines = wrap(detail, int((w - 30) / 4.55))
            a(f'<rect x="{x + 9}" y="{y - 11}" width="2.5" '
              f'height="{13 + LINE_H * len(lines)}" rx="1.2" '
              f'fill="{p["accent"]}" opacity="0.55"/>')
            a(f'<text x="{x + 19}" y="{y}" font-size="10.8" font-weight="600" '
              f'fill="{p["ink"]}">{esc(bold)}</text>')
            for k, ln in enumerate(lines):
                a(f'<text x="{x + 19}" y="{y + 13 + k * LINE_H}" font-size="9.3" '
                  f'fill="{p["muted"]}">{esc(ln)}</text>')
            y += ROW_GAP + LINE_H * len(lines)

        if i < len(COLS) - 1:
            nx = COLS[i + 1][0]
            mid = BODY_TOP - 12 + col_h / 2
            a(f'<path d="M {x + w + 6} {mid} L {nx - 8} {mid}" stroke="{p["arrow"]}" '
              f'stroke-width="1.6" fill="none" marker-end="url(#ar)"/>')

    # Scores do not flow one way: the model writes them back into the store,
    # which is where the API reads them from.
    sx, sw = COLS[2]
    mx = COLS[3][0]
    by = BODY_TOP - 12 + col_h + 11
    a(f'<path d="M {mx + 40} {BODY_TOP - 12 + col_h} L {mx + 40} {by} '
      f'L {sx + sw / 2} {by} L {sx + sw / 2} {BODY_TOP - 12 + col_h}" '
      f'stroke="{p["arrow"]}" stroke-width="1.3" fill="none" '
      f'stroke-dasharray="3 2.5" marker-end="url(#ar)"/>')
    # Break the dashed line around its own label rather than drawing over it.
    label = "scores and forecasts written back"
    lx = (sx + sw / 2 + mx + 40) / 2
    half = len(label) * 2.25
    a(f'<rect x="{lx - half - 5}" y="{by - 8}" width="{half * 2 + 10}" height="15" '
      f'fill="{p["bg"]}"/>')
    a(f'<text x="{lx}" y="{by + 3}" font-size="8.8" text-anchor="middle" '
      f'fill="{p["muted"]}">{label}</text>')

    a(f'<rect x="24" y="{fy}" width="{W - 48}" height="{foot_h}" rx="7" '
      f'fill="{p["wash"]}" stroke="{p["line"]}"/>')
    a(f'<text x="40" y="{fy + 20}" font-size="8.6" letter-spacing="0.7" '
      f'fill="{p["muted"]}">OPERATIONS</text>')
    for j, (head, detail) in enumerate(FOOT):
        bx = 40 + j * 472
        a(f'<text x="{bx}" y="{fy + 40}" font-size="10.8" font-weight="600" '
          f'fill="{p["ink"]}">{esc(head)}</text>')
        for k, ln in enumerate(wrap(detail, 64)):
            a(f'<text x="{bx}" y="{fy + 55 + k * LINE_H}" font-size="9.3" '
              f'fill="{p["muted"]}">{esc(ln)}</text>')

    a(f'<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" '
      f'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
      f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{p["arrow"]}"/></marker></defs>')
    a('</svg>')
    return "\n".join(o), H


OUT.mkdir(parents=True, exist_ok=True)
light, h = build(LIGHT)
dark, _ = build(DARK)
(OUT / "architecture.svg").write_text(light, encoding="utf-8")
(OUT / "architecture-dark.svg").write_text(dark, encoding="utf-8")
print(f"wrote both at {W}x{h}")
