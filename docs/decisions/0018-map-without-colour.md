# 0018 — The Map Had To Work Without Colour

**Status:** FIXED 29 Sep 2026.

## The defect

The corridor map drew three road states — cut off, degraded, clear — and the
only thing separating them was hue. The colours came from the interface's
`--alert`, `--caution` and `--ok` tokens, which are tuned for *text on
white*. Measured relative luminance:

| state | colour | luminance |
|---|---|---|
| cut off | `#c03a3a` | 0.145 |
| clear | `#2f7d5d` | 0.161 |
| degraded | `#b06a15` | 0.196 |

Contrast ratio between a cut-off road and a clear road: **1.08**. Between any
pair: 1.08 to 1.26. The accepted minimum for distinguishing two graphical
objects is 3:1.

So the map said "impassable" and "fine" in red and green at the same
brightness. Roughly one man in twelve cannot reliably separate those, and in
greyscale, on a projector, or in a printout nobody can. The only other visual
channel in use was line width, and that encoded *bridge or not*:

```js
"line-width": ["case", ["get", "is_bridge"], 4, 2]
```

There was also no legend at all — just a line of body text reading "Red =
worst, green = best", which states the encoding in the very terms a reader
with colour vision deficiency cannot use.

This is the project's own stated requirement failing: a flood map "has to say
three things at a glance". It was saying them in a way some readers could not
hear.

## The fix

**Pull the brightness apart.** The map ramp is now separate from the text
tokens, and documented as to why:

| state | colour | luminance | vs cut off |
|---|---|---|---|
| cut off | `#8a1f1f` | 0.065 | — |
| clear | `#3f9c74` | 0.261 | 2.71 |
| degraded | `#d4901c` | 0.340 | 3.40 |

Dark-to-light now tracks bad-to-good with no hue involved.

**Dash the cut-off roads.** A dash is not a colour. Cut-off roads (below
0.34) are drawn again on a layer above, dashed and slightly wider. This needs
a second layer because `line-dasharray` cannot be driven by a feature's own
properties in MapLibre — only by zoom — so one layer cannot dash some roads
and not others.

**Add a real legend**, which draws each band exactly as the map draws it,
dash included, and quotes the numeric band edges. The colours are no longer
the only statement of what a band means.

## What is still only hue

Degraded against clear is 1.26 — weak. A light basemap leaves little room
above mid-grey before a line stops being visible at all, so the brightness
budget went to the distinction that matters. Mistaking "slow" for "clear"
costs a delay; mistaking "impassable" for "clear" sends a truck into water.
Stated here rather than quietly left as an unexplained gap.

## How it was checked

Not by eye. The luminances above are computed, and the rendered map was
inspected under a full greyscale filter with every colour removed: the
cut-off roads remain unmistakable — dark and dashed — where previously all
three states collapsed to the same mid-grey.
