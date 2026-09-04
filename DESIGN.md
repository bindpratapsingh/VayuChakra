---
name: VayuChakra
description: Coupled weather and chemistry forecasting for Delhi NCR, an operational scientific instrument, read by forecasters and reviewed by a jury.
register: product
platform: web
colors:
  brand: "#1c3260"
  brand-active: "#2c4b8a"
  brand-wash: "#eef1f8"
  ink: "#101820"
  ink-muted: "#4a5764"
  surface: "#f4f6f8"
  panel: "#ffffff"
  panel-2: "#eaeef3"
  line: "#d6dde5"
  line-strong: "#b9c4d0"
  s1: "#3b62d4"
  s2: "#c2701c"
  s3: "#0f9b8e"
  baseline: "#8b98a8"
  ok: "#0f7b4a"
  ok-wash: "#f1f8f4"
  warn: "#b06a12"
  warn-wash: "#fdf7ee"
  bad: "#b3261e"
  bad-wash: "#fdf2f1"
  aqi-good: "#009966"
  aqi-satisfactory: "#84cf33"
  aqi-moderate: "#ffde33"
  aqi-poor: "#ff9933"
  aqi-very-poor: "#cc0033"
  aqi-severe: "#7e0023"
  canvas: "#f7f9fb"
  no-data: "#e3e8ee"
  skeleton-sweep: "#f2f5f8"
  s2-ink: "#8a4f10"
  moderate-ink: "#8a6d00"
  ramp-0: "#eef1f8"
  ramp-1: "#c8d3ea"
  ramp-2: "#93a9d6"
  ramp-3: "#5c78bd"
  ramp-4: "#33539c"
  ramp-5: "#1c3260"
  stab-0: "#3b62d4"
  stab-1: "#8ba3de"
  stab-2: "#c6cfda"
  stab-3: "#c9c3b6"
  stab-4: "#dcae7e"
  stab-5: "#c2701c"
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
- **Atmospheric Indigo** (#1c3260) is the single brand voice: rail, primary emphasis.
  Deep enough to read as institutional. Indigo rather than AirGrid's teal because the
  subject is the vertical structure of the atmosphere. 12.54:1 with white.
- **Active Indigo** (#2c4b8a) for focus rings and interactive states.
- **Indigo Wash** (#eef1f8) is the tint behind the loop-closure note.

### Neutrals
- **Ink** (#101820) body text, 16.52:1 on surface.
- **Muted Ink** (#4a5764) secondary text, 6.83:1 on surface and 7.40:1 on panel. Never
  lighter: this is the floor, not a starting point.
- **Surface** (#f4f6f8) page background, a cool off-white.
- **Panel** (#ffffff) the reading layer. **Panel-2** (#eaeef3) control strips.
- **Line** (#d6dde5) hairlines. **Line-strong** (#b9c4d0) borders that must be seen.

### Chart series (validated, fixed order)
`s1 #3b62d4` → `s2 #c2701c` → `s3 #0f9b8e`, plus `baseline #8b98a8` for controls.

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

`#eef1f8 → #c8d3ea → #93a9d6 → #5c78bd → #33539c → #1c3260`

One hue, light to dark, running from Indigo Wash to the brand itself. Used where a
quantity is continuous and has no published band scale: the relative AQI map mode, and
the coarse-tier cells on the domain map. Single-hue by rule, because a rainbow ramp
invents category boundaries the data does not have and reads differently to a
colour-blind viewer at every step.

It is never used for AQI in the default view. AQI has a legislated band scale and
recolouring it would be a fabrication, so the relative mode is opt-in and says in its own
caption that these are not CPCB colours.

### Diverging ramp (static stability)

`#3b62d4 → #8ba3de → #c6cfda → #c9c3b6 → #dcae7e → #c2701c`

Two hues with a near-neutral midpoint, built from the ends of the validated series pair:
`s1` for stable air, `s2` for unstable. Reserved for one quantity, the lapse rate on the
time and height cross-section, because stability is genuinely two-sided around a neutral
value and a sequential ramp would hide the sign change that matters most. The two hues
inherit the series pair's CVD separation, so the stable and unstable ends stay
distinguishable under protanopia.

### Darkened tones for small text

Two tokens exist only because their parents fail contrast at 10px:

- **`s2-ink #8a4f10`** is `s2` darkened to 6.1:1 for the stubble-belt label, which sits at
  10px on the map ground where `s2` itself reaches only about 3.3:1.
- **`moderate-ink #8a6d00`** is the Moderate band darkened for the large AQI readout.
  `#ffde33` as text on white is 1.4:1 and effectively invisible.

Both are text-only. Neither is ever used as a fill, because that would put a second
almost-identical tone next to its parent and imply a distinction that is not there.

### Utility neutrals

`canvas #f7f9fb` is the map ground, one shade lighter than the surface so the domain
reads as a distinct plane. `no-data #e3e8ee` fills a cell with no index and is
deliberately outside the CPCB set, so absence never resembles a band. `skeleton-sweep
#f2f5f8` is the highlight in the loading sweep.

### Status
`ok #0f7b4a` · `warn #b06a12` · `bad #b3261e`, each with a wash for chip backgrounds.
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

## 11. The report is a different surface, and it is typeset

`docs/REPORT.html` deliberately departs from the one rule this document is most
committed to: **the product UI uses `system-ui` and nothing else.** That rule was
written about the dashboard, and it holds there. A dashboard is scanned and operated,
so a display pairing buys nothing and costs a font request on a cold instance.

The report is read, not operated. It is the artefact a judge or a reviewer sits with,
and typography is what carries a document. So it pairs on a real contrast axis:

| role | face | why |
|---|---|---|
| headings | **Newsreader** | an editorial serif with enough weight to give a technical report gravity, italic used only for the one phrase in the title that is the thesis |
| body | **IBM Plex Sans** | humanist, institutional, reads at length; a genuine contrast against the serif rather than a second sans that is nearly the same |
| figures, labels, file paths | **IBM Plex Mono** | tabular by construction, and it marks every path and identifier as a literal thing on disk |

The palette does **not** depart. It is the same atmospheric indigo, the same cool
neutral ground biased toward that indigo rather than toward warmth, and the same
semantic green and ochre for pass and gap. The report should look like it came from
the same place as the product, and it does, because colour is what carries that and
colour is unchanged.

Three tokens exist only in the report and are listed here so they are not mistaken for
drift: `--dot-hollow` and `--dot-stroke` (the persistence marker in the dumbbell chart,
which must read as an outline against the filled model marker in both themes), and
`--connector` (the segment between the pair, which must sit visually behind both dots
without disappearing on the dark ground).
