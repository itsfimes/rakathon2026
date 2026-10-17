---
version: 1
slug: "app-src"
primary_target: "app/src/App.tsx"
related_targets: ["app/src/styles/tokens.css", "app/src/components/ui", "app/src/features"]
---

# Surface: app/ — real React frontend (frontend only, no backend)

Inherits the accepted design base (design.md; historical reference sample/). Not a new visual world: same palette, 1px visible borders, 4px corners, icon+word tags, graphical patient calendar/journey, top role switch (one sticky row desktop, 3-column two-row non-sticky grid ≤760px). Operate mode.

Additions over the sample: persistent data-source strip (mock / backend not configured / config error) pinned on every screen; explicit loading/error/empty states; local demo actions labelled "(lokálně v demu)"; finalisation always disabled.

Typography amendment (user request "slightly more focus on typography"): semantic role variables (`--type-*`), panel titles 19px, patient text 16px throughout, table secondary lines and quotes 14px, buttons lh 1.25 with vertical padding, `text-wrap: pretty` for prose. No font-family change, no web fonts.

Unresolved: real backend adapter and endpoints; role/permission matrix; SLA values; user's final visual acceptance.
