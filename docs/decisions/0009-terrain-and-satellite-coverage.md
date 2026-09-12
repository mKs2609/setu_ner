# 0009 — Terrain, and the Honest Limit of Sentinel-1

**Status:** Terrain BUILT. Sentinel-1 **coverage** built; **flood extent
NOT built**, for reasons recorded below. 12 Sep 2026.

Phase 2's two remaining items were DEM/terrain and Sentinel-1 flood extent.
One is done. The other is not, and this document exists mostly to say why
rather than to leave it as an absence somebody discovers during a demo.

## Terrain — built

### Why it matters

Two roads with identical district flood severity are not equally at risk if
one sits on the valley floor and the other on a ridge. Until now nothing in
the data could tell them apart: the baseline accessibility score assigns
every road in a district the same severity, which is exactly the crudeness
terrain fixes.

### The source

**Copernicus DEM GLO-30**, 30 m, from the AWS Open Data bucket — public, no
credentials. The tiles are Cloud Optimized GeoTIFFs, so `rasterio` reads the
corridor window over HTTP range requests rather than downloading the 288 MB
of full tiles the corridor spans.

### What it produced

**110,260 of 110,266 roads sampled** (6 had no usable pixel), 5.5 m to
1481 m, mean 80 m. Gradient computed for 103,520 — the rest are shorter than
~30 m, where both endpoints land in the same DEM pixel and the "gradient"
would be noise divided by a tiny number.

Sanity: Silchar samples at **24.5 m**, Haflong at **660 m**. Both correct.

### What it immediately explained

| District | Mean elevation | Mean slope | 2025 flood severity |
|---|---|---|---|
| Karimganj | 20 m | 2.08% | 0.416 |
| Hailakandi | 25 m | 2.35% | **0.668** (worst) |
| Cachar | 29 m | 2.38% | 0.286 |
| Dima Hasao | **527 m** | **5.31%** | **0.024** (lowest) |

Dima Hasao sits twenty times higher and floods twenty-eight times less. The
baseline score already *knew* Dima Hasao floods least, because ASDMA said so
— but it could not say why, and could not distinguish a hill road in Cachar
from a valley road beside it. Now the data can.

This is four districts, so it is a pattern consistent with physics, not a
fitted relationship. It is a feature for Phase 3 to use, not a finding to
put in a pitch.

### The caveat that matters

**GLO-30 is a surface model, not a terrain model.** It records the top of
whatever is there — tree canopy, buildings — not bare ground. Over an open
road that is the road surface. Under dense canopy or in a built-up street it
can sit several metres high.

That barely affects the comparison this feature exists to make (valley
versus hillside is a 700 m difference, not a 5 m one), but it does affect
gradient on short narrow segments, where a canopy gap can manufacture a
slope that is not there. `slope_pct` on short residential roads deserves
scepticism. A hydrologically conditioned DEM such as MERIT would be better
for flood reasoning specifically, at 90 m instead of 30 m; swapping it in
means changing one URL template.

### A schema gotcha worth recording

`create_tables.py` calls SQLAlchemy's `create_all()`, which creates missing
**tables** and silently does nothing to a table that already exists. Adding
columns to `roads` appeared to succeed and changed nothing. Every schema
change to an existing table now needs a statement in `infra/migrations/`;
`0001_add_road_terrain_columns.sql` is the first, written to be safe to run
twice.

## Sentinel-1 — coverage built, flood extent not

### What was tested, not assumed

| | Result |
|---|---|
| Catalogue search, anonymous | **Works** — 22 usable GRD scenes over the corridor in 60 days |
| Scene download, anonymous | **401** — needs a registered Copernicus account |
| GRD → flood extent | Needs calibration, speckle filtering, terrain correction, water thresholding |

### Why flood extent was not built

`0001` section 1 already concluded that the bottleneck for Sentinel-1 is SAR
processing expertise rather than access, and said to keep it optional rather
than let it block the vertical slice. Testing confirms both halves: download
needs credentials nobody has set up, and a 1.7 GB IW GRD scene becomes flood
polygons only through a real processing pipeline.

Thresholding an unprocessed scene would have produced flood boundaries
quickly, and they would have been indefensible — a shape on a map that looks
authoritative and means nothing. That is the failure this project has
avoided everywhere else, and it would be worst here, because a flood polygon
is the single most believable-looking output the system could emit.

### What was built instead, and why it is not a consolation prize

Coverage: **when radar actually looked at the corridor**, from the catalogue
that does answer anonymously. 22 products across 11 distinct passes, with an
observed revisit of 2.5 and 9.5 days alternating — the ascending/descending
pattern of Sentinel-1's 12-day repeat.

That answers a real operational question. *"Could anything independent have
confirmed this report?"* has a genuine answer, and if the last pass was nine
days ago that answer is no, regardless of how good a flood pipeline might
eventually be. It is also the discovery half of the pipeline, so adding
download and processing later is an extension rather than a rewrite.

The cadence is measured from passes actually recorded, not predicted from
orbital elements — we cannot do the latter, and the response says so.

### What it would take to finish

1. A free Copernicus Data Space account and OAuth token handling.
2. A SAR pipeline — SNAP/`pyroSAR` or `sentinel1-flood-mapping` — for
   calibration, speckle filtering, terrain correction (the DEM above is
   already in place for that step) and thresholding.
3. Validation against a known flood, otherwise the polygons are unfalsifiable.

That is genuine multi-day specialist work, and it is honest to call it that.

## Phase 2 status

Not complete, and it should not be claimed as complete:

| | |
|---|---|
| Live hazard ingestion (`0004`) | ✅ |
| Field reports + fusion (`0005`) | ✅ |
| Corroboration (`0006`) | ✅ |
| Scheduling (`0008`) | ✅ |
| **DEM / terrain** | ✅ |
| **Sentinel-1 coverage** | ✅ |
| **Sentinel-1 flood extent** | ❌ — needs credentials and a SAR pipeline |

## Testing

15 new tests, 145 in the suite. Catalogue parsing runs without network.
Terrain tests assert the data is physically plausible for *this* corridor —
a misread raster transform typically lands values in the thousands or below
sea level, both obviously wrong here and both completely silent.

## Next

Phase 3. Terrain is the first genuinely per-road feature the model will
have, which changes what is possible: elevation and gradient vary road to
road, where district flood severity does not. Labels remain the constraint.
