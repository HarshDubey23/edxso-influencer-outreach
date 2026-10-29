---
name: Creator Outreach Engine
description: Results day on a green felt notice board; every channel ranked, stamped, and withheld with its reason.
colors:
  felt: "#1d3a31"
  felt-deep: "#142a23"
  felt-ink: "#e8efe9"
  felt-soft: "#a9c2b6"
  paper: "#f6f7f4"
  paper-rule: "#d9ddd5"
  index-card: "#fffef8"
  ink: "#15181a"
  ink-soft: "#4f5752"
  stamp-red: "#c62f26"
  ballpoint-blue: "#2342a8"
  brass: "#c9a14e"
  desk-grey: "#e9ede9"
  desk-line: "#d3d9d2"
  desk-soft: "#eef1ed"
  felt-tint: "#dde8e2"
  pass-green: "#1f6f3f"
  pass-tint: "#dff0e4"
  caution-umber: "#9a4a10"
  caution-tint: "#f6e7d8"
  stamp-tint: "#f8e1df"
  night-board: "#10211b"
  night-sheet: "#172b24"
  night-line: "#2c4a3f"
  night-stamp: "#ff8f86"
  night-ballpoint: "#9fb4ff"
  night-pass: "#7fd69b"
  night-caution: "#f0a46c"
typography:
  display:
    fontFamily: "Big Shoulders Display, Arial Narrow, sans-serif"
    fontSize: "clamp(52px, 8.4vw, 6rem)"
    fontWeight: 900
    lineHeight: 0.9
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "Big Shoulders Display, Arial Narrow, sans-serif"
    fontSize: "clamp(38px, 5.4vw, 68px)"
    fontWeight: 900
    lineHeight: 0.95
    letterSpacing: "-0.005em"
  title:
    fontFamily: "Big Shoulders Display, Arial Narrow, sans-serif"
    fontSize: "26px"
    fontWeight: 800
    lineHeight: 1
  body:
    fontFamily: "Public Sans, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Public Sans, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "0.08em"
  margin-note:
    fontFamily: "Public Sans, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
  figure:
    fontFamily: "JetBrains Mono, ui-monospace, Consolas, monospace"
    fontSize: "26px"
    fontWeight: 600
    lineHeight: 1
    fontFeature: "tnum"
  figure-small:
    fontFamily: "JetBrains Mono, ui-monospace, Consolas, monospace"
    fontSize: "12.5px"
    fontWeight: 400
    lineHeight: 1.4
    fontFeature: "tnum"
rounded:
  sheet: "2px"
  control: "3px"
  tab: "4px"
  stamp: "6px"
spacing:
  gutter: "clamp(16px, 4vw, 56px)"
  sheet-pad: "clamp(22px, 3vw, 40px)"
  rule-pitch: "28px"
  gap: "22px"
  band: "clamp(72px, 10vw, 132px)"
components:
  button-rail:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
  button-rail-hover:
    backgroundColor: "#ffffff"
  slip-primary:
    backgroundColor: "{colors.stamp-red}"
    textColor: "#ffffff"
    rounded: "{rounded.sheet}"
    padding: "26px 22px 20px"
  slip:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sheet}"
    padding: "26px 22px 20px"
  preset-button:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  preset-button-hover:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
  result-sheet:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sheet}"
    padding: "{spacing.sheet-pad}"
  verdict-stamp:
    textColor: "{colors.stamp-red}"
    typography: "{typography.display}"
    rounded: "{rounded.stamp}"
    padding: "8px 18px 6px"
  rail-tab-selected:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  op-button:
    backgroundColor: "{colors.felt}"
    textColor: "{colors.paper}"
    padding: "8px 14px"
---

# Design System: Creator Outreach Engine

## Overview

**Creative North Star: "The Merit List"**

It is results day. The page is a green felt notice board, and everything readable on it is a typed paper sheet pinned up with brass pins: ranked lists, tallies, case files, letters. Verdicts are pressed on in red rubber-stamp ink. Marks, reasons, and links are written in blue ballpoint. Headings use condensed poster capitals, the prose is plain typewriter-clean sans, and monospace only ever carries a number. The board is dense where a result sheet would be dense. A sheet does not decorate itself. It ranks, strikes out, and gives reasons.

The public landing (Persuade) shows the full world: a fibre-textured felt background, slightly rotated sheets, pins, stamps that press in, a cut-off line that draws once. The working dashboard (Operate) is the same world in restrained form. The felt becomes the top rail, sheets become flat panels on a grey desk or, in dark theme, a night board, stamp red and ballpoint blue keep their meanings, and the poster capitals stay on page headings. The landing explicitly rejects the dark AI-landing look, with its gradient headline, metric tiles, and dashboard screenshot.

**Key Characteristics:**
- Felt board ground, paper sheets as the only reading surface.
- State is shown as a mark (strike-through, stamp, ballpoint reason), never as a colour wash alone.
- Rank is shown as type size: the top of a list is set larger.
- Real figures in tabular monospace; everything else in Public Sans or poster caps.
- Motion happens once: sheets settle, stamps press, the cut-off draws, counts tick up.

## Colors

A dark felt green with warm brass, cool white paper, near-black type, and two inks that each carry one meaning.

### Primary
- **Notice-board Felt** (felt): the board itself, the Operate top rail, the browser theme colour, and the Operate light-theme accent. Felt Deep is the sticky rail and the scrollbar track.
- **Stamp Red** (stamp-red): verdicts and nothing else. Stamps, the cut-off line, strike-throughs, the classifier's top bar and its tally row, the primary action slip, text selection, and the `bad` state in Operate.

### Secondary
- **Ballpoint Blue** (ballpoint-blue): the examiner's hand. Withholding reasons, margin notes, the index-card head rule and figure, arrow icons, link underlines, and the focus ring inside sheets.

### Tertiary
- **Pin Brass** (brass): pins (a radial gradient from #f3dc9a through brass to #6e5420), the focus ring on felt, and the Operate dark-theme accent and chart colour.

### Neutral
- **Typed Sheet** (paper) with **Sheet Rule** (paper-rule): the sheet surface and its hairline rules, the ghost step numerals, and progress tracks. **Index Card** (index-card) is reserved for the warmer ruled card.
- **Type Black** (ink) / **Carbon** (ink-soft): text on paper, and secondary text and struck rows.
- **Felt Ink** / **Felt Moss** (felt-ink, felt-soft): text on felt, and secondary text, band ledes, and the footer.
- **Operate desk** (desk-grey, desk-line, desk-soft, felt-tint): the light-theme ground, borders, table heads, and accent tint. Night tokens (night-board, night-sheet, night-line, plus night-stamp, night-ballpoint, night-pass, night-caution) are the dark-theme replacements for the same roles.
- **Status inks** (pass-green, caution-umber with their tints, plus stamp-tint): Operate pills and checks only.

### Named Rules
**The Two Inks Rule.** Red means a verdict was pressed (qualified, withheld, failed). Blue means an examiner wrote something (a reason, a note, a link). Never swap them, and never use either one as decoration.

**The Mark Not Hue Rule.** A withheld result is struck through in red and given its reason in blue. Colour reinforces the state but never carries it alone.

## Typography

**Display Font:** Big Shoulders Display (with Arial Narrow, sans-serif), weights 600/800/900
**Body Font:** Public Sans (with system-ui, sans-serif)
**Label/Mono Font:** JetBrains Mono (with ui-monospace, Consolas), numbers only

**Character:** Poster capitals pinned above clean civic sans. The condensed caps shout the result, and the sans explains it quietly.

### Hierarchy
- **Display** (900, clamp(52px, 8.4vw, 6rem), 0.9, uppercase, balanced): the one verdict headline per page. Operate page headings use the same face at clamp(36px, 5vw, 62px).
- **Headline** (900, clamp(38px, 5.4vw, 68px), 0.95, uppercase): band headings on felt. Operate section headings are 800 at 34px.
- **Title** (800, 22-28px, 1.0-1.1, uppercase): step names, slip titles, letter subjects, ledger terms, close links. Merit-list ranks and marks also use 800 poster caps, at 1.25-1.35em of their row.
- **Body** (400, 16px, 1.55): prose. Ledes use 15-17px in ink-soft or felt-soft with a 62-66ch maximum. Letters use 15px/1.6 at 64ch.
- **Label** (600, 11-13px, 0.08-0.1em, uppercase): letterheads, merit-list column heads, cut-off captions, the DM label. Operate table heads use 12px at 0.04em.
- **Margin note** (italic 400, 13-14px, ballpoint blue): reasons and examiner notes.
- **Figure** (JetBrains Mono 600, 26-46px, tabular): counts on step sheets, the index-card accuracy, Operate KPIs. Small figures (12.5-13px) are roll numbers, counts, word counts, and addresses.

### Named Rules
**The Rank Is Size Rule.** In a ranked list, rank 1 is set at clamp(20px, 2.2vw, 30px) and each row steps down (24, 20, 17, 15, 14px) until it reaches the 14px base.

**The Mono Is For Numbers Rule.** JetBrains Mono sets figures, roll numbers, addresses, and the classifier input. It never sets headings or prose.

## Layout

The board is centred at a maximum width of 1440px with a fluid gutter. The first viewport is a two-column grid (8fr sheet, 3.4fr slip column with a 260px minimum) that stacks below 1000px, where the slips flow into auto-fit columns of at least 230px. Bands are separated by a large fluid gap (`spacing.band`), and each opens with a felt headline and a felt-soft lede. Card grids are three-column for steps (two below 1000px, one below 620px), and two-column for letters (one below 900px) and the ledger (one below 760px). Sheets carry a 28px horizontal rule pitch, so typed lines sit on the ruling. The merit table drops roll number, niche, and engagement below 640px. The rail hides its section nav below 860px and shortens its call to action below 480px.

Operate uses a 1240px wrap with 20px padding, a 60px sticky felt rail with tabs that wrap to their own row below 760px, auto-fit KPI panels (150px minimum), and a two-column grid that collapses below 860px.

## Elevation & Depth

Depth is physical. Paper sits on felt and casts a soft, long, downward shadow, and pinned sheets are rotated a fraction of a degree (between -0.9 and 1.2 degrees) so they read as hung by hand. There are no glows and no hard offset shadows. Hover lifts a slip by straightening it and dropping its shadow further. In Operate, panels are flat with a faint two-part shadow in light theme and a 1-2px shadow in dark theme.

### Shadow Vocabulary
- **Pinned sheet** (`box-shadow: 0 1px 1px rgba(0,0,0,.25), 0 18px 40px -12px rgba(0,0,0,.55)`): full result sheets.
- **Pinned slip** (`box-shadow: 0 1px 1px rgba(0,0,0,.25), 0 14px 30px -12px rgba(0,0,0,.55)`): slips, steps, letters, index card. Hover: `0 1px 1px rgba(0,0,0,.25), 0 22px 40px -14px rgba(0,0,0,.6)`.
- **Operate panel** (`box-shadow: 0 1px 1px rgba(10,20,15,.08), 0 10px 24px -14px rgba(10,20,15,.35)`; dark `0 1px 2px rgba(0,0,0,.4)`).

### Named Rules
**The Hung By Hand Rule.** Every pinned sheet is rotated slightly and alternates direction with its neighbours. Nothing on the board is rotated more than about 1.2 degrees, except stamps (-9 to 6 degrees).

## Shapes

Paper has near-square corners (2px). Controls are 3px, and rail tabs are 3-4px. The stamp is the only rounded rectangle (6px, 4px double border) and is masked with turbulence noise so its ink lands unevenly. Bars are drawn, not filled: tally bars are 2px ink strokes every 7px, clipped to length. Pins are brass circles with a cast shadow. Dividers are 1px paper-rule hairlines, a 2px ink rule under letterheads, and dashed rules above step marks.

## Components

### Buttons
- **Shape:** near-square (3px).
- **Rail call to action:** a paper chip on felt, ink text weight 700, padding 8px 14px, with an arrow icon. It turns pure white on hover.
- **Preset buttons:** a 1.5px ink outline on paper that inverts to ink fill on hover.
- **Focus:** a 3px brass outline at 3px offset on felt. Inside sheets the outline turns ballpoint blue. On the red slip it turns paper.
- **Operate:** a felt-filled button with a ghost variant (felt text, transparent background), weight 600, and 0.5 opacity when disabled.

### Action Slips (signature)
Pinned paper slips act as the primary actions. The primary slip is stamp red with white text. Titles are poster caps at 28px, and the arrow is ballpoint (white on red). Slips rest rotated and straighten with a 3px lift on hover (0.4s, house ease).

### Result Sheet (signature)
A paper sheet with one or two pins, a letterhead line (uppercase label plus mono metadata over a 2px ink rule), and ruled body content. The ranked list shows rank as size, a red cut-off line that draws once, and struck withheld rows each followed by a ballpoint reason.

### Verdict Stamp (signature)
Red uppercase poster caps inside a 4px double border with noise-masked ink and multiply blend, with an optional mono sub-line. It presses in once (0.55s: from 1.6x scale, blurred, at 0.3 opacity down to rest). The classifier stamp presses again every time its predicted label changes. An uncertain result is stamped in carbon instead of red.

### Index Card
A warm index-card surface with a 6px ballpoint top border, blue ruled lines on the 28px pitch, and a 46px mono ballpoint figure.

### Inputs / Fields
- **Ruled textarea:** borderless, transparent, 17px/28px mono on the sheet's ruling. Focus shows a 3px ballpoint outline at 6px offset.
- **Operate fields:** panel background with a 1px line border.

### Navigation
- **Landing rail:** sticky felt-deep at 88% with an 8px backdrop blur. Felt-soft 14px links turn felt-ink on a faint white wash when hovered.
- **Operate tabs:** felt rail. The selected tab is a paper chip with ink text at weight 600.

### Chips / Pills (Operate)
Pills are tinted status pills: pass-green, stamp-red, caution, and felt accent text on their tints. The pipeline flow is a row of bordered panels, with classifier steps outlined in the accent.

## Do's and Don'ts

### Do:
- **Do** put every block of reading on a paper sheet; felt carries only headings, ledes and the footer.
- **Do** give every withheld or failed item a red strike and a blue italic reason.
- **Do** set figures in JetBrains Mono with tabular numerals, and set rank as type size.
- **Do** run motion once with `cubic-bezier(.16, 1, .3, 1)`. Sheets settle 16px over 0.9s, the cut-off draws over 1.1s after a 0.5s delay, and counts tick up over 1.4s on an exponential ease-out. Under reduced motion, everything is static and visible by default.
- **Do** keep stamp red to verdicts and the single primary action.

### Don't:
- **Don't** build the dark AI-landing: gradient headline, metric-tile hero, dashboard screenshot.
- **Don't** use JetBrains Mono for headings or prose.
- **Don't** use stamp red or ballpoint blue as decorative fills or section backgrounds.
- **Don't** add hard offset shadows, glows, or large radii to paper; sheets are 2px and cast soft drop shadows.
- **Don't** set a small uppercase label above a heading; uppercase labels live only in a sheet's letterhead and in table heads, where they carry that sheet's data.
