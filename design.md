---
name: Sdílený případ
description: Professional, simple, low-motion dashboard language for four role views of one shared oncology case (revised proposal, awaiting user evaluation).
colors:
  page: "#F1F4F8"
  surface: "#FFFFFF"
  surface-sunken: "#F5F7FA"
  surface-head: "#E9EEF4"
  line: "#B8C2CE"
  line-soft: "#D7DEE6"
  line-strong: "#747F8D"
  ink: "#1B2430"
  ink-muted: "#4D5A6A"
  accent: "#1F5FBF"
  accent-hover: "#194E9E"
  accent-soft: "#E8F0FC"
  accent-line: "#8FB0E3"
  accent-ink: "#FFFFFF"
  focus: "#1F5FBF"
  danger: "#B42318"
  danger-soft: "#FDECEA"
  danger-line: "#E7A39C"
  warning: "#8A5300"
  warning-soft: "#FFF4E0"
  warning-line: "#DDB46A"
  success: "#1E6B3A"
  success-soft: "#E6F4EA"
  success-line: "#93C6A3"
  neutral: "#4D5A6A"
  neutral-soft: "#EEF1F5"
  neutral-line: "#B8C2CE"
  info: "#1F5FBF"
  info-soft: "#E8F0FC"
  info-line: "#8FB0E3"
typography:
  display:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Noto Sans\", \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "2.25rem"
    fontWeight: 650
    lineHeight: 1.1
  headline:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Noto Sans\", \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 650
    lineHeight: 1.25
  title:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Noto Sans\", \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1.1875rem"
    fontWeight: 650
    lineHeight: 1.25
  body:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Noto Sans\", \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  body-sm:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Noto Sans\", \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
  data:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Noto Sans\", \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Noto Sans\", \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 500
    lineHeight: 1.5
  button:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Noto Sans\", \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: 1.25
  tag:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Noto Sans\", \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 650
    lineHeight: 1.4
  segmented:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Noto Sans\", \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: 1.5
  table-heading:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Noto Sans\", \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 650
    lineHeight: 1.5
rounded:
  sm: "3px"
  md: "4px"
spacing:
  s-1: "0.25rem"
  s-2: "0.5rem"
  s-3: "0.75rem"
  s-4: "1rem"
  s-5: "1.5rem"
  s-6: "2rem"
  s-7: "3rem"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: "0 1rem"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
    textColor: "{colors.accent-ink}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.accent}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: "0 1rem"
  button-secondary-hover:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.accent}"
  button-disabled:
    backgroundColor: "{colors.neutral-soft}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.button}"
  panel:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.md}"
  panel-head:
    backgroundColor: "{colors.surface-sunken}"
    padding: "0.75rem 1rem"
  tag-danger:
    backgroundColor: "{colors.danger-soft}"
    textColor: "{colors.danger}"
    typography: "{typography.tag}"
    rounded: "{rounded.sm}"
    padding: "0.125rem 0.45rem"
  tag-warning:
    backgroundColor: "{colors.warning-soft}"
    textColor: "{colors.warning}"
    typography: "{typography.tag}"
    rounded: "{rounded.sm}"
  tag-success:
    backgroundColor: "{colors.success-soft}"
    textColor: "{colors.success}"
    typography: "{typography.tag}"
    rounded: "{rounded.sm}"
  tag-neutral:
    backgroundColor: "{colors.neutral-soft}"
    textColor: "{colors.neutral}"
    typography: "{typography.tag}"
    rounded: "{rounded.sm}"
  tag-info:
    backgroundColor: "{colors.info-soft}"
    textColor: "{colors.info}"
    typography: "{typography.tag}"
    rounded: "{rounded.sm}"
  segmented-item:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.segmented}"
    padding: "0 0.75rem"
  segmented-item-current:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
  table-head:
    backgroundColor: "{colors.surface-head}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.table-heading}"
    padding: "0.5rem 0.75rem"
  table-row-selected:
    backgroundColor: "{colors.accent-soft}"
  next-step-head:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.accent}"
    padding: "0.5rem 0.75rem"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.md}"
    padding: "0 0.75rem"
---

# Design System: Sdílený případ

Status: the user accepted this design as the BASE for the real frontend; it is not a final approval of every screen. **Authoritative source is now the React app CSS: `app/src/styles/tokens.css` (all values), `components.css`, `layout.css`; overrides in `theme.css`.** The offline `sample/` remains as the immutable historical reference the app was built from; its tokens match except the typography amendment below. Product context: `product.md`. Extended snippets: `.impeccable/design.json`.

## Overview

A conventional, professional clinical dashboard played straight: white bordered panels on a cool grey page, one restrained blue for action, selection, current step and focus, and status always shown as icon + word. Density is controlled for the coordinator, calmer and more graphical for the patient. Motion is limited to a 150 ms colour change.

The user rejected the first sample as too simple, text-heavy and rounded. This revision is the middle ground they asked for: visible 1px borders, 4px corners, a compact top role switch, labelled icons, and step/journey graphics (calendar tile, vertical journey, step bar, completeness cells).

**Key characteristics:**
- Visible 1px borders define panels and controls; soft dividers separate rows inside them.
- 4px corners (3px on tags and skeletons); circles only for journey nodes and the avatar.
- One accent hue; status colours never appear without an icon and a word.
- System font stack, fixed rem scale, no web fonts.
- No hero metrics, no decorative graphics, no motion spectacle.

## Colors

Cool neutral surfaces with one blue accent and four status families (soft fill / line / strong text).

- **Surfaces:** `page` #F1F4F8 behind everything; `surface` #FFFFFF panels; `surface-sunken` #F5F7FA panel heads and hovers; `surface-head` #E9EEF4 table headers.
- **Lines:** `line` #B8C2CE panel, table and timeline boundaries (structural but not a control boundary); `line-soft` #D7DEE6 decorative row dividers inside panels; `line-strong` #747F8D control boundaries (segmented, inputs, secondary button, calendar tile, mini-steps), ≥ 3:1 against white.
- **Text:** `ink` #1B2430; `ink-muted` #4D5A6A for meta and labels. The generated text-node contrast check on sampled solid ancestor backgrounds reported a minimum 5.31:1 and no failures within that check; it is not exhaustive coverage of placeholders, UI boundaries, interaction/focus states, alpha compositing or assistive-technology conformance.
- **Accent:** `accent` #1F5FBF for primary action, current role, selected row tint (`accent-soft`), current step, links and focus ring; `accent-hover` #194E9E.
- **Status:** danger (missing, not acknowledged), warning (verify / uncertain), success (done, have), neutral, info. Sampled status text was checked against its solid soft fill in the same bounded text-node check; the `*-line` colours are decorative tag borders, not 3:1 requirements.

Rule: colour is never the only signal. Every tag, cell and node carries an icon, a pattern (uncertain cells are hatched) or a word.

## Typography

One family: the system UI stack (no web fonts). Fixed rem steps, ratio about 1.2, no fluid type. Weights 400 / 500 / 650 (650 is requested; how it renders depends on the installed system face — Chrome on the test machine reported computed 650). Numerals are tabular everywhere.

Semantic roles (in `app/src/styles/tokens.css`; customise these first):

| Role variable | Value | Use |
|---|---|---|
| `--type-page-title` | `fs-xl` 24px, 650, lh 1.25 | view title (h1) |
| `--type-panel-title` | `fs-lg` 19px, 650, lh 1.25 | panel/section titles, patient event and helper titles |
| `--type-task` | `fs-lg` 19px, 650, lh 1.25, balanced | the next-task sentence (focal point inside "Další krok") |
| `--type-label` | `fs-sm` 14px, 650 | next-step head label |
| `--type-body` | `fs-md` 16px, lh 1.5 | running text |
| `--type-patient` | `fs-md` 16px, lh 1.5 | everything in the patient view, incl. event explanation (max 68ch), journey status lines and helper note; the patient "Co teď" sentence is 16px 650 |
| `--type-data` | `fs-sm` 14px, lh 1.45 | table cells and their secondary lines (diagnosis, owner), controls, quotes (lh 1.5) |
| `--type-meta` | `fs-xs` 13px | table headers (650), captions, citations, tags, panel meta |

Calendar day number stays `fs-2xl` 36px. Buttons: 14px / 500 / lh 1.25 with `--control-pad-y` 0.375rem vertical padding inside the 40px (44px mobile) minimum, so wrapped Czech labels have room. In the queue the next-step text is 500 (primary) over its 400 owner line. Prose, list items, notices and disclosures use `text-wrap: pretty`; headings and the task sentence use `balance`.

Amendment (refinement, not a new direction): compared with the sample, panel titles went 16→19px, table secondary lines and quotes 13→14px, patient event/journey/helper text 13–14→16px, button line height 1.2→1.25 with vertical padding.

## Layout

- **Space:** 4px base; `s-1`…`s-7` = 4, 8, 12, 16, 24, 32, 48px.
- **Shell:** top app bar (product name, "Ukázka · smyšlená data" link to the disclaimer, role switch, date), then `main#obsah` max 96rem, padding `s-5`, sections separated by `s-7`.
- **Desktop (> 760px):** app bar is `position: sticky` and one row (measured 65px at 1440). Skip and deep-link targets (`#obsah`, `.view`, `.view__title`, `.content [id]`) carry `scroll-margin-top: 4.5rem` so headings land below the bar (h1 top measured 89px).
- **Work area:** `.split` two columns (1.6fr / min 22rem) collapsing to one column at ≤ 1100px.
- **Mobile (≤ 760px):** app bar is static (not sticky); the date is hidden; the role switch becomes a full-width 3-column grid, two rows (Koordinátor · Pacient · Lékař / MDT · Vizuální jazyk spanning 2). At the page top all options fit without horizontal clipping or scrolling; the current role has a filled selected state. The header scrolls out of the viewport normally on skip links, history navigation or page scrolling. Scroll margin drops to `s-2`. Measured at page top: app bar 136px and h1 top 148px at 390; 160px and 172px at 320. Buttons and segments have a 44px minimum (`target-touch`). Tables stack into label/value rows.
- **≤ 380px:** role labels drop to `fs-xs` with tighter padding; stacked table cells and the step bar go single column.
- Patient column is capped at 44rem.

## Elevation & Depth

Flat, defined by borders. One shadow token: `shadow-1` = `0 1px 2px rgba(27,36,48,0.08)`, used only on panels. No other shadows, glass or blur. The current step in the step bar is marked by a 3px inset bottom rule plus the soft accent fill and the word, not by elevation.

## Shapes

- `radius` 4px on panels, buttons, inputs, notices, disclosures, segmented, calendar tile; `radius-sm` 3px on tags and skeletons.
- Circles only for timeline nodes (2rem, 2px border; dashed for "later") and the avatar.
- Borders: 1px everywhere except journey nodes (2px) and the timeline connector (2px).
- Icons: authored inline SVG `<symbol>`s, 24-unit viewBox, stroke `currentColor`, `stroke-width 1.75` (2 inside tags, 2.25 inside nodes), round caps and joins, size `1.125rem` (`icon`), `0.9rem` small. Always `aria-hidden` next to a visible word.

## Components

In the React app each primitive is its own component in `app/src/components/ui/` (Panel, Button, Tag, Notice, Disclosure, Facts, StepBar/MiniSteps, NextStep, Checklist, Cells, Timeline, CalendarTile, Table/StackCell, Field/Input/Select, Segmented, Skeleton, Avatar); role compositions live in `app/src/features/`. App behaviour: a pinned data-source strip on every screen (mock: "DEMO · SYNTETICKÁ DATA · bez backendu" + "Obnovit demo"; backend: "Backend · není nakonfigurován"), explicit loading/error/empty states, queue rows selectable by native buttons, local demo actions labelled "(lokálně v demu)", urge/inform/confirm buttons disabled, finalisation always disabled. The app needs JavaScript; the no-JS behaviour below applies only to the historical sample.

Historical sample (`sample/`) behaviour — primitives live in `sample/css/components.css`; role compositions in `views.css`. Behaviour split:

Control sizes are minimums, not fixed heights: buttons, segments and inputs use `min-height: 2.5rem` on desktop and grow with content. At ≤ 760px, buttons and segments use `min-height: 2.75rem`; inputs retain the 2.5rem minimum. The frontmatter omits fixed `height`; responsive `min-height` is represented in the sidecar CSS.

- **Dynamic in the sample (classic script `app.js`, no modules, no network, no storage):** role view switching via links (`#koordinator` … `#specimen`, `?role=`), `aria-current="page"` on the active role, focus to the view h1 on hash change, back/forward support; opening the "O ukázce" disclosure when targeted; the specimen's state preview radios (empty / loading / error / done). Native `<details>` disclosures work without JS.
- **Inert clinical controls:** every clinical button (Urgovat, Potvrdit výpis, Finalizovat…), inputs and selects are appearance only and labelled as examples; nothing is sent, stored or approved.
- **Without JavaScript:** all four role views and the specimen are shown one below another; the state switch stays hidden and all four state panes show.

Components: app bar + role switch (segmented links), panel, button (primary / secondary / disabled), tag (danger / warning / success / neutral / info, icon + word), table (stacks on mobile, selected row tint + "Otevřeno vpravo" mark), facts list (icon / label / value), step bar (T1–T3), mini-steps, next-step panel (shared signature: what / who / by when / acknowledgement), checklist, completeness cells (ok / hatched unsure / missing), timeline/journey (done / now / later nodes), calendar tile, notice (info / warning / danger / success), disclosure, input/select, segmented radio, static skeleton.

Focus: `2px solid accent`, offset 2px; inside segmented controls offset −4px and white on the filled current item. Forced colours: current segment uses `Highlight` / `HighlightText`, focus becomes 3px `CanvasText`, current step/mini-step get a `Highlight` outline.

Motion: only `background-color` / `border-color` transitions on buttons, `150ms ease-out` (`t-fast`); `prefers-reduced-motion: reduce` sets it to 0ms. Skeleton is static, no shimmer.

## Do's and Don'ts

**Do**
- Pair every status colour with an icon and a word.
- Use `line-strong` for anything you can operate; `line` for panel structure; `line-soft` for decorative row dividers.
- Show next step, owner, deadline and acknowledgement together (next-step panel).
- Give the patient dates and journeys graphically (calendar tile, labelled journey), in plain words.
- Keep the role switch in one sticky row on desktop; on phones use the two-row grid so all options fit at page top without horizontal clipping, with a filled current-role state (the static header scrolls away normally).

**Don't**
- Don't go back to the rejected look: pill shapes, borderless cards, walls of text.
- Don't add hero metrics, scores, decorative illustration, web fonts or motion beyond colour feedback.
- Don't make a clinical control look functional in the sample, or claim sending, approval or AI processing.
- Don't treat the role switch as login or permissions; the future role/capability matrix is a proposal in `product.md`, not implemented.
- Don't fork primitives per role; compose them. Framework choice is open (see `product.md`, modularity principles).

## Assistant surface (app only)

- **Shape:** conversation-first right side sheet, 30rem on desktop, full screen at 760px and below. It always opens with native `showModal()`. Elevation is a soft left shadow plus a light backdrop; there is no border box around the sections.
- **Header (one place for honesty):** title, an outlined "Skriptovaná ukázka · není AI" / "Asistent není připojen" badge, and one muted line with a dot carrying the real data mode. Quiet text actions: Vymazat, Zavřít. The data-source banner is never repeated inside.
- **Body:** a one-line scope note, then the conversation. User turns are right-aligned accent-soft bubbles; replies are plain text with a small provenance line and fixed source labels. The empty state has one mark, a question and one sentence.
- **Dock (sunken surface):**
  - **Suggestions:** appear in the empty conversation state. "Vložit" fills and focuses the composer without sending.
  - **Context row:** explicit checkbox with "Připojeno: n údajů" state and "Zobrazit údaje" opening a separate inspection view inside the same dialog. Inspection is not consent; its Back control restores focus to the trigger. Valid submission returns to conversation without moving focus from Send.
  - **Composer:** one bordered input with counter, quiet Zastavit and the primary send. The retention note is in the visible scope text. Unavailable mode shows an explanation instead of interactive chat controls.
- **Avoid:** stacked boxed sections, more than one mode banner, gradients, sparkles, and "AI" marketing.
