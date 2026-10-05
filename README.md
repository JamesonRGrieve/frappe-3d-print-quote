# frappe-3d-print-quote

3D-printing quotes for Frappe v16 / ERPNext. A customer uploads STL or 3MF models on a public page
and gets an instant estimate. The shop gets a **Print Quote Request**, a **Lead** and a priced
**Quotation** (a draft for review, or sent directly).

- **Print Quote Profile**, one per quote service/store:
  - selling company, quotation item, materials offered;
  - pricing model: fill fraction, throughput g/h, machine rate, per-part and setup fees, minimum order, markup;
  - limits: build volume, file size, quantity, files per request;
  - optional slicer refinement.
- **Print Material**: process, density, price per gram, colours.
- **Estimate per part**: volume (from the mesh) × density × fill fraction gives grams; grams ÷ throughput gives hours; price = grams × price/g + hours × machine rate + per-part fee. With a slicer configured (headless PrusaSlicer/OrcaSlicer), the slicer's own grams and print time are used instead.
- **Widget**: a site's own page embeds `<div data-print-quote-profile="…"></div>` + `/assets/print_quote/js/print_quote_widget.js`. Uploads go to `print_quote.api.submit`, which does its own validation and rate limiting, so Frappe's site-wide guest uploads stay off. Models are stored as private files on the request.

License: AGPL-3.0-or-later.
