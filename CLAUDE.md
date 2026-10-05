# frappe-3d-print-quote — Agent Operating Guide

AGPL-3.0-or-later Frappe v16 app (package `print_quote`): STL/3MF upload → instant estimate → Print
Quote Request + Lead + Quotation. Built for Zephyrex Fabrication (card 263) but generic: one
`Print Quote Profile` per store/company.

## Layout

- `geometry.py` (pure): binary/ASCII STL and 3MF parsing.
  - Volume is the signed-tetrahedron sum (abs, so winding doesn't matter); also the bounding box.
  - STL is read as mm; 3MF unit is honoured.
  - Limits: ≤2M triangles, 3MF zip-bomb cap. Open or flat meshes are refused.
  - `Mesh.fits()` checks any axis-aligned orientation against the build volume.
- `pricing.py` (pure): `estimate_part`, `request_total`, `marked_up`. Markup applies to parts only; the setup fee and the minimum-order shortfall are separate Quotation lines, so the Quotation net total always equals the estimate shown.
- `slicer.py`: optional headless slicer (120 s timeout), parsing `; filament used [g]` and `; estimated printing time`. Any failure falls back to the geometry estimate.
- `quote.py`: validation against profile limits → analysis → estimate → Print Quote Request (files stored private) → Lead (reused per open email) → Quotation (draft when `review_before_send`).
- `api.py`: guest `get_profile` / `submit` (multipart, `rate_limit` 10/h per IP).
- `public/js/print_quote_widget.js`: an accessible upload form.

## Public-site integration

Under frappe-public-site-router, a site's quote page is its own Web Page (e.g. `zxfab/quote`) that embeds the widget. `/api/*` and `/assets/*` aren't website routes, so the router lockdown needs no exception.

## Testing

`bench --site <site> run-tests --app print_quote`. Geometry on known solids (STL ASCII/binary, 3MF units), pricing, slicer parser, and the end-to-end request → Lead → Quotation flow on the real test DB.
