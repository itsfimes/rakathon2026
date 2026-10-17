# Sdílený případ — ukázka vizuálního jazyka

Static, offline specimen of the dashboard language for four role views (Koordinátor, Pacient, Lékař, MDT) plus a token/component/state sheet. Not the application.

## Open

Open `index.html` directly in a browser (`file://`). No server, network, fonts, packages or build step.

- Role links in the top bar switch the view (on desktop a one-row switch in a sticky bar; on phones a non-sticky 3-column grid so all four role views, the specimen and the current choice are always visible) (`#koordinator`, `#pacient`, `#lekar`, `#mdt`, `#specimen`).
- `index.html?role=pacient` opens a view directly (for screenshots).
- Without JavaScript all views are shown one below another. Full disclaimer: "O ukázce" at the bottom (`#o-ukazce`).

## Layers

- `css/tokens.css` — colours, type scale, spacing, radius, motion.
- `css/components.css` — primitives (panel, button, badge, table, next-step box, notice, disclosure, form controls).
- `css/views.css` — shell layout and the four role compositions.
- `app.js` — view switching and the state specimen only.

## Honesty limits

All people and data are fictitious. Buttons are examples: nothing is sent, approved, accepted, stored or processed by AI. Switching role is not login or data protection. Thresholds are illustrative, not norms.
