---
name: VayuChakra
description: Coupled weather–chemistry forecasting for Delhi NCR — an operational scientific instrument, read by forecasters and reviewed by a jury.
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
typography:
  display:
    fontFamily: "system-ui, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.1
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
    width: "216px"
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
- **Atmospheric Indigo** (#1c3260) — the single brand voice: rail, primary emphasis.
  Deep enough to read as institutional. Indigo rather than AirGrid's teal because the
  subject is the vertical structure of the atmosphere. 12.54:1 with white.
- **Active Indigo** (#2c4b8a) — focus rings and interactive states.
- **Indigo Wash** (#eef1f8) — the tint behind the loop-closure note.

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

### Status
`ok #0f7b4a` · `warn #b06a12` · `bad #b3261e`, each with a wash for chip backgrounds.
Reserved for state. Never reused as a fourth series colour, and always shipped with a
label rather than a bare dot.

## 4. Typography

One family: the system sans. A product UI does not need a display pairing.

Fixed rem scale, not fluid, at roughly a 1.125 ratio:
`0.6875 → 0.75 → 0.8125 → 0.875 → 0.9375 → 1.0625 → 1.5rem`,
plus a fixed `10px` for chart axis ticks, which sit outside the text ramp because they
must stay legible at a fixed size regardless of the surrounding scale.

The scale is deliberately tighter and has more steps than AirGrid's. A dense instrument
has more distinct text roles than a chat interface, and exaggerated contrast between
them would read as noise.

`font-variant-numeric: tabular-nums` on every number a reader might compare.

## 5. Layout and density

Rail plus content. The rail is a fixed 216px, collapsing to a horizontal bar under
860px. Content is a 22px gutter with panels on a 14px grid.

Panels are used where a genuine grouping exists. **Cards are not the default answer and
are never nested.** The coupling view's five steps are columns divided by hairlines
rather than five cards, because they are one continuous process and not five things.

## 6. Motion

150–250ms, ease-out, on state only: view changes, toggles, tooltip fades, the skeleton
sweep. No orchestrated page-load sequence — the reader arrives to work, not to watch.
Every animation has a `prefers-reduced-motion` alternative, and the skeleton sweep stops
entirely under it.

## 7. Charts

- **Never a dual axis.** Inversion strength (K), mixing depth (m) and ventilation
  coefficient (m²·s⁻¹) are three panels sharing an x-axis, not three lines on two
  y-scales. Two scales let the author choose the story by choosing the scaling.
- 2px lines, recessive grid, crosshair and tooltip on every plot.
- A legend for two or more series, plus a direct label at the last point.
- Loading is a skeleton, never a spinner in the middle of content.
- Empty states say **why** a thing is empty. "No active fires in the stubble belt"
  reads as a broken feed unless it also says that outside October and November this is
  the correct reading.
