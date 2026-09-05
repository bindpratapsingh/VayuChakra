---
name: VayuChakra
description: Coupled weather and chemistry forecasting for Delhi NCR, an operational scientific instrument, read by forecasters and reviewed by a jury.
register: product
platform: web
colors:
  brand: "#0f3540"
  brand-active: "#1d5f70"
  brand-wash: "#e7eff1"
  ink: "#0e1719"
  ink-muted: "#47585c"
  surface: "#eff3f4"
  panel: "#ffffff"
  panel-2: "#e2e9ea"
  line: "#cfd9db"
  line-strong: "#b0bfc2"
  s1: "#1f6bb5"
  s2: "#9c4a24"
  s3: "#0e7c8a"
  baseline: "#7d8f93"
  ok: "#0e6b46"
  ok-wash: "#f1f8f4"
  warn: "#8a5320"
  warn-wash: "#fdf7ee"
  bad: "#a32820"
  bad-wash: "#fdf2f1"
  aqi-good: "#009966"
  aqi-satisfactory: "#84cf33"
  aqi-moderate: "#ffde33"
  aqi-poor: "#ff9933"
  aqi-very-poor: "#cc0033"
  aqi-severe: "#7e0023"
  canvas: "#f5f8f8"
  no-data: "#dde5e6"
  skeleton-sweep: "#f2f5f8"
  s2-ink: "#7f3a1a"
  moderate-ink: "#8a6d00"
  ramp-0: "#e7eff1"
  ramp-1: "#c2d8dd"
  ramp-2: "#93bcc5"
  ramp-3: "#5b98a6"
  ramp-4: "#2b7286"
  ramp-5: "#0f3540"
  stab-0: "#1f6bb5"
  stab-1: "#79a5cd"
  stab-2: "#c6d3d7"
  stab-3: "#dcc7b8"
  stab-4: "#c08a63"
  stab-5: "#9c4a24"
typography:
  display:
    fontFamily: "system-ui, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.02em"
    fontFeature: "tabular-nums"
  readout:
    fontFamily: "system-ui, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.02em"
    fontFeature: "tabular-nums"
  title:
    fontFamily: "system-ui, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 650
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  subtitle:
    fontFamily: "system-ui, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 650
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  body:
    fontFamily: "system-ui, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  secondary:
    fontFamily: "system-ui, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.45
    letterSpacing: "normal"
  label:
    fontFamily: "system-ui, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "normal"
  micro:
    fontFamily: "system-ui, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: "normal"
  axis:
    fontFamily: "system-ui, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
    fontSize: "10px"
    fontWeight: 400
    lineHeight: 1
    letterSpacing: "normal"
    fontFeature: "tabular-nums"
rounded:
  xs: "2px"
  sm: "6px"
  md: "10px"
  bar: "4px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "22px"
  xxl: "44px"
components:
  panel:
    backgroundColor: "{colors.panel}"
    borderColor: "{colors.line}"
    rounded: "{rounded.md}"
    padding: "16px"
  rail:
    backgroundColor: "{colors.brand}"
    textColor: "#ffffff"
    width: "224px"
  segmented:
    backgroundColor: "{colors.panel-2}"
    rounded: "{rounded.pill}"
    padding: "3px"
  segmented-selected:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.brand}"
  button:
    backgroundColor: "{colors.panel}"
    borderColor: "{colors.line-strong}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "6px 13px"
  chip:
    backgroundColor: "{colors.panel}"
    borderColor: "{colors.line}"
    textColor: "{colors.ink-muted}"
    rounded: "{rounded.pill}"
    padding: "3px 9px"
  tooltip:
    backgroundColor: "{colors.ink}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
    padding: "8px 10px"
---

# Design System: VayuChakra

## 1. Why this is not AirGrid's system

VayuChakra and AirGrid are siblings from the same team and they share a parent
repository, but they are different products for different readers, and they should not
share a type ramp.

AirGrid speaks to Delhi residents on a phone: a public-health bulletin with the warmth
of a helpful neighbour. VayuChakra speaks to a forecaster at NCMRWF and to a scientific
jury. It is an instrument, not an advisory. It is denser, quieter, and more numeric, and
its job is to let a reviewer judge whether the physics underneath it is sound.

**The one thing inherited without change is the CPCB AQI band scale.** That is a public
standard, not a brand asset, and it is reproduced exactly in both products.

## 2. Creative north star: "The instrument panel"

The scene the design is built for: a reviewer at a desk indoors under office light,
mid-morning, reading a 72-hour outlook and deciding whether to trust it; or the same
screen projected in a lit jury room. That scene forces the choices. Light surface,
because the room is lit and the screen may be projected or printed. High density,
because the reader is comparing numbers rather than browsing. Tabular figures
everywhere, because columns of numbers that do not align are harder to compare and
quietly erode confidence.

Authority comes from restraint and from showing the working. The interface recedes; the
number, the band and the confidence stand forward.

## 3. Colours

**Strategy: restrained.** A cool neutral field, one institutional voice, and saturated
colour reserved for two jobs only: severity, and series identity.

### Chrome
- **Atmospheric Petrol** (#0f3540) is the single brand voice: rail, primary emphasis.
  Deep enough to read as institutional. Indigo rather than AirGrid's teal because the
  subject is the vertical structure of the atmosphere. 12.54:1 with white.
- **Active Petrol** (#1d5f70) for focus rings and interactive states.
- **Petrol Wash** (#e7eff1) is the tint behind the loop-closure note.

### Neutrals
- **Ink** (#0e1719) body text, 16.52:1 on surface.
- **Muted Ink** (#47585c) secondary text, 6.83:1 on surface and 7.40:1 on panel. Never
  lighter: this is the floor, not a starting point.
- **Surface** (#eff3f4) page background, a cool off-white.
- **Panel** (#ffffff) the reading layer. **Panel-2** (#e2e9ea) control strips.
- **Line** (#cfd9db) hairlines. **Line-strong** (#b0bfc2) borders that must be seen.

### Chart series (validated, fixed order)
`s1 #1f6bb5` → `s2 #9c4a24` → `s3 #0e7c8a`, plus `baseline #7d8f93` for controls.

Assigned in this order and never cycled. Validated with the palette checker: lightness
band, chroma floor, CVD separation (worst adjacent ΔE 14.0 protan), normal-vision floor
(ΔE 21.7) and contrast against the surface all pass.

The uncoupled baseline is drawn in `baseline` **and dashed**, so the control reads as a
control by two channels rather than by colour alone.

### CPCB AQI bands (public standard, exact)
Good #009966 · Satisfactory #84cf33 · Moderate #ffde33 · Poor #ff9933 ·
Very Poor #cc0033 · Severe #7e0023

Validated as a categorical set: CVD separation passes at ΔE 8.2 (protan), but
Satisfactory, Moderate and Poor all fall **below 3:1 against a light surface**. That
result is not dismissable, and it sets two hard rules:

1. **Every band-coloured element carries its band name and number as visible text.**
   Colour is never the only channel.
2. **Every map cell carries a hairline border**, so a pale yellow cell is still a cell.

Text on bands: dark ink on Good, Satisfactory, Moderate and Poor; white on Very Poor and
Severe. White on Good is only 3.65:1, which is large-text-only, so ink is used there too.

### Sequential ramp (continuous magnitude)

`#e7eff1 → #c2d8dd → #93bcc5 → #5b98a6 → #2b7286 → #0f3540`

One hue, light to dark, running from Indigo Wash to the brand itself. Used where a
quantity is continuous and has no published band scale: the relative AQI map mode, and
the coarse-tier cells on the domain map. Single-hue by rule, because a rainbow ramp
invents category boundaries the data does not have and reads differently to a
colour-blind viewer at every step.

It is never used for AQI in the default view. AQI has a legislated band scale and
recolouring it would be a fabrication, so the relative mode is opt-in and says in its own
caption that these are not CPCB colours.

### Diverging ramp (static stability)

`#1f6bb5 → #79a5cd → #c6d3d7 → #dcc7b8 → #c08a63 → #9c4a24`

Two hues with a near-neutral midpoint, built from the ends of the validated series pair:
`s1` for stable air, `s2` for unstable. Reserved for one quantity, the lapse rate on the
time and height cross-section, because stability is genuinely two-sided around a neutral
value and a sequential ramp would hide the sign change that matters most. The two hues
inherit the series pair's CVD separation, so the stable and unstable ends stay
distinguishable under protanopia.

### Darkened tones for small text

Two tokens exist only because their parents fail contrast at 10px:

- **`s2-ink #7f3a1a`** is `s2` darkened to 6.1:1 for the stubble-belt label, which sits at
  10px on the map ground where `s2` itself reaches only about 3.3:1.
- **`moderate-ink #8a6d00`** is the Moderate band darkened for the large AQI readout.
  `#ffde33` as text on white is 1.4:1 and effectively invisible.

Both are text-only. Neither is ever used as a fill, because that would put a second
almost-identical tone next to its parent and imply a distinction that is not there.

### Utility neutrals

`canvas #f5f8f8` is the map ground, one shade lighter than the surface so the domain
reads as a distinct plane. `no-data #dde5e6` fills a cell with no index and is
deliberately outside the CPCB set, so absence never resembles a band. `skeleton-sweep
#f2f5f8` is the highlight in the loading sweep.

### Status
`ok #0e6b46` · `warn #8a5320` · `bad #a32820`, each with a wash for chip backgrounds.
Reserved for state. Never reused as a fourth series colour, and always shipped with a
label rather than a bare dot.

## 4. Typography

One family: the system sans. A product UI does not need a display pairing.

Fixed rem scale, not fluid, at roughly a 1.125 ratio:
`0.6875 → 0.75 → 0.8125 → 0.875 → 0.9375 → 1.0625 → 1.25 → 1.5rem`,
plus a fixed `10px` for chart axis ticks, which sit outside the text ramp because they
must stay legible at a fixed size regardless of the surrounding scale.

The `1.25rem` **readout** step closes a real gap. Without it the jump from `1.0625` to
`1.5` is a ratio of 1.41, far outside the rest of the scale, and the six coupling-loop
values had nowhere to sit: at `1.5rem` they compete with the city AQI, which is the one
number on the product that should be largest, and at `1.0625rem` they stop reading as
figures and start reading as headings.

The scale is deliberately tighter and has more steps than AirGrid's. A dense instrument
has more distinct text roles than a chat interface, and exaggerated contrast between
them would read as noise.

`font-variant-numeric: tabular-nums` on every number a reader might compare.

## 5. Layout and density

Rail plus content. The rail is a fixed 224px, collapsing to a horizontal bar under
900px. Content is a 22px gutter with panels on a 14px grid.

It widened from 216px when each nav item gained a second line. The six views are named
for physics rather than for pages, so `Vertical` and `Domain` need a sub-label saying
what they contain; 216px wrapped those onto three lines and 224px does not. The
sub-labels are dropped entirely in the collapsed bar, where there is no room for them.

Panels are used where a genuine grouping exists. **Cards are not the default answer and
are never nested.** The coupling view's five steps are columns divided by hairlines
rather than five cards, because they are one continuous process and not five things.

## 6. Motion

150–250ms, ease-out, on state only: view changes, toggles, tooltip fades, the skeleton
sweep. No orchestrated page-load sequence, because the reader arrives to work, not to watch.
Every animation has a `prefers-reduced-motion` alternative, and the skeleton sweep stops
entirely under it.

## 7. The reading comes before the apparatus

Every view opens with **one sentence stating what the instrument says right now**,
derived from the data on screen, above the standing explanation of how it knows. It is
typographic only: larger, darker, a hairline under it, numbers in brand weight. No box,
no tinted panel, nothing that would read as a callout component.

This exists because the surface previously opened with an explanation of the physics and
left the reader to assemble the finding from the charts. That is the right order for a
forecaster who already knows what an inversion is and the wrong order for everyone else,
and the second group is larger.

The sentence is never fixed copy. If the data cannot support it, it says so: "No
inversion forms anywhere in this window" is as valid a lead as a lid at 246 m, and both
are more useful than a paragraph that reads the same on every run.

Navigation follows the same rule. The primary label is what the view answers ("The lid
over the city"), the physics term is the sub-label ("Inversion and mixing depth"). The
vocabulary is kept for the reader who has it, not required of the reader who does not.

## 8. The cycle

The product is named वायु चक्र, the air cycle, and the closure of that loop is its whole
claim. It was drawn as six columns in a row with a footnote saying step 5 feeds step 1,
which asked the reader to take the closure on trust.

It is now a ring: six nodes, each carrying the live value for that link, arcs with
arrowheads, and the last arc closing onto the first. A marker travels the ring once per
solver iteration and then stops, because the solver converges and an animation that ran
for ever would say something false about it. The hub carries the iteration count and the
number of cells that fell back.

Below 1000px there is no room for six labels outside a circumference, so the columns
return: same values, same order, a shape that survives a narrow screen.

## 9. Maps are maps

The domain and the forecast grid render on a real basemap (Leaflet, Esri World Light
Gray Canvas, keyless). Before this they were grids of abstract rectangles, and no reader
could tell that Karnal is 120 km north or that the fires sit in Punjab.

The basemap is near-achromatic on purpose. The only thing on these maps that must be
read by colour is the CPCB scale, so the ground underneath cannot compete with it.

CARTO's raster basemaps were tried first and stamp "API KEY REQUIRED" across every tile.
The HTTP 200 and a plausible byte count hid it: a tile source has to be checked by what
it looks like, not by whether it downloaded.

If the CDN is blocked, `window.L` is undefined and the original SVG renderers draw
instead. Degrading to the previous design is an acceptable failure; an empty panel is
not.

## 10. Charts

- **Never a dual axis.** Inversion strength (K), mixing depth (m) and ventilation
  coefficient (m²·s⁻¹) are three panels sharing an x-axis, not three lines on two
  y-scales. Two scales let the author choose the story by choosing the scaling.
- 2px lines, recessive grid, crosshair and tooltip on every plot.
- A legend for two or more series, plus a direct label at the last point.
- Loading is a skeleton, never a spinner in the middle of content.
- Tables a reviewer interrogates are sortable, with `aria-sort` and keyboard support.
  The caret sits at low opacity when unsorted, so the affordance is visible before the
  hover rather than being a feature nobody finds. Twelve rows are fine to read top to
  bottom, but the question a reviewer arrives with is "which is worst", and that is a
  sort, not a scan.
- Numeric columns take `width: 1px` and never `width: 1%`. Inside a max-content sizing
  context a browser resolves the percentage literally, making the table 100 times the
  cell: a 104px column produced a 10,647px table and pushed the whole page sideways.
- Wide tables scroll inside their own container. The page body never scrolls
  horizontally, at any width down to 390px.
- Empty states say **why** a thing is empty. "No active fires in the stubble belt"
  reads as a broken feed unless it also says that outside October and November this is
  the correct reading.

## 11. The report is a print document, and it has its own type system

`docs/report/report.html` is not a web page. It exists only to be rendered to
`docs/VayuChakra-Report.pdf` by `docs/report/build.py`, and it departs from this
document in three ways, each deliberate.

**Typography.** The product UI uses `system-ui` and nothing else, and that rule holds
on the dashboard: a dashboard is scanned and operated, so a display pairing buys
nothing and costs a font request on a cold instance. A report is read, on paper as
often as on screen, and typography is what carries a document. The faces were
specified by the user:

| role | face | why |
|---|---|---|
| body prose | **Times New Roman** | the serif a technical report is expected to be set in, and it holds up at 10.8 pt on paper where a screen sans does not |
| headings, tables, figures, labels | **Calibri** | a real contrast axis against the serif, and it keeps every table and diagram label legible at 8.6 pt |
| file paths and identifiers | **Consolas** | marks a literal thing on disk as literal; the one face not in the user's brief, and used nowhere but inside `.mono` |

**Units.** The stylesheet is in points and millimetres, not pixels, because the output
is A4. The `rounded` scale in this document is a pixel scale for the web UI and does
not apply; the report uses a single 2 pt radius on status pills and 3 pt on diagram
nodes, which is the print equivalent of `rounded.xs`.

**Section numbering.** Numbered section markers are normally an AI-editorial tell and
are called out as such. Here they are load-bearing: the document cross-references
itself throughout (`see §11.2`, `Table 4.1`, `§12.1 closes C6`), and the eleven
problem-statement clauses are numbered C1 to C11 so the compliance matrix, the gap
list and the roadmap can all point at the same clause. Strip the numbers and every
cross-reference in the report breaks. That is the test: numbering that carries
information the reader needs, rather than numbering as decoration.

**What does not change** is the palette. Same atmospheric indigo, same ochre for the
second series and for gaps, same green for a passing check, same cool neutral ground
biased toward the indigo rather than toward warmth. The report should look like it
came from the same place as the product, and colour is what carries that.


## 12. The warm arc belongs to the data, and chrome may not enter it

The CPCB National AQI ramp is a public standard and is reproduced exactly: green,
yellow-green, yellow, orange, red, maroon. It is the one encoding on this site that a
reader must never have to second-guess, because it is the encoding a GRAP decision is
made on.

The palette that shipped first broke that. The second chart series was `#c2701c`, a
saturated orange sitting **dE 20.3** from `#ff9933`, the AQI *Poor* band. Measured, not
felt: at that distance a rust-orange line on a chart beside an orange-filled map cell is
a question the reader has to stop and resolve, and the answer, "one is a model output and
the other is a severity class", is not something colour was telling them.

So the rule is now explicit, and it is checkable:

> **Warm hues encode severity, and nothing else.** Every band fill in the CPCB ramp is
> warm. No brand colour, no chart series, no chip and no chrome may sit within dE 30 of
> any band in that ramp.

What replaces it comes from the subject rather than from taste. Aerosol preferentially
removes short wavelengths, which is why the sun reddens through haze, why the Angstrom
exponent is in `photolysis.py` at all, and why the ultraviolet pathway is the one that
governs ozone. So the warm light that survives the haze is what the AQI ramp encodes,
and the short-wavelength light the aerosol takes away is what the instrument is drawn
in:

| token | value | what it is |
|---|---|---|
| `brand` | `#0f3540` | deep petrol, the atmospheric column seen edge-on. 13.10:1 with white |
| `s1` | `#1f6bb5` | azure, the clear air and the primary model line |
| `s2` | `#9c4a24` | rust, dust and stubble. Earth, not alarm: dark and desaturated where the AQI oranges are light and saturated |
| `s3` | `#0e7c8a` | teal, the same family as the brand at chart lightness |

The one warm member is kept deliberately. An all-cool series set was tried and measured:
azure, violet and cyan collapse to **dE 7 to 14** under deuteranopia, against 34 for this
set, because dichromats retain the blue-yellow axis and lose red-green. Warm against cool
is what makes a series legible without colour vision, so the warm member stays and is
moved away from the ramp instead of removed.

**Measured, all of it:**

| check | before | now | floor |
|---|---|---|---|
| nearest series to any AQI band | dE 20.3 | **dE 30.0** | 30 |
| series separation, normal vision | dE 86.2 | dE 41.4 | 25 |
| series separation, protanopia | dE 48.0 | dE 35.4 | 25 |
| series separation, deuteranopia | dE 67.3 | dE 34.2 | 25 |
| every series on white panel | | 4.92:1 min | 4.5:1 |
| white on brand | 12.54:1 | 13.10:1 | 4.5:1 |

Normal-vision separation falls because the old palette bought it by straying into the
ramp. The number that matters is the floor, and every series clears it in all three
vision models while no longer competing with the standard.
