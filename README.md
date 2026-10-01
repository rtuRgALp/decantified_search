# Scent Compass

An independent, retailer-neutral fragrance sample finder. All searchable retailers are selected by default; offers appear alphabetically. No retailer rankings, paid placement, accounts, runtime backend, or paid APIs.

## Experience

- Search decants by name, brand, inspiration, or notes; use any/all note matching and exclusions.
- Compare confidently identified fragrances across retailers; ambiguous names and concentrations remain separate.
- Browse available samples by default, or include sold-out, unverified, backorder, and discontinued listings.
- Choose sizes and retailers explicitly. Keep saved samples through stock and price changes.
- Review separate retailer/currency subtotals, set per-currency budgets, and export CSV.
- Use verified Shopify cart links or individual retailer product links. Always confirm stock, price, and shipping at the retailer.

## Freshness

Actual public Shopify product catalogs and WooCommerce Store API catalogs are fetched outside the browser. The daily refresh runs at 09:17 UTC, with manual dispatch in GitHub Actions. New listings appear after the next successful refresh and Cloudflare deployment. Initial imports are not marked new; later listings show “Newly listed” for 30 days, not an asserted fragrance release date.

Every retailer has its own snapshot and last-check time. Overdue checks are flagged after 36 hours. After 72 hours stock becomes unverified and is excluded from available-now search and prefilled checkout. Errors and incomplete pagination retain prior observations; they never imply sold out. Discontinued selections remain visible in saved samples.

The repository is public and uses standard Ubuntu runners, which GitHub documents as free for public repositories. The workflow refuses to run if the repository becomes private. No paid ingestion service, artifact upload, or cache is required. Scheduled runs can be delayed, and public retailer endpoints can rate-limit or require connection verification.

## Local preview

```sh
python3 -m http.server 8000
```

Open http://localhost:8000. Opening the HTML directly cannot load catalogs.

## Refresh

```sh
python3 -m scripts.refresh_catalogs
python3 -m scripts.refresh_catalogs --retailer decantified
```

Review `catalogs/refresh-report.json`, then commit only validated snapshots. Empty catalogs and drops over 50% are quarantined. Audit a legitimate collapse manually before replacing its previous snapshot. `retailers.json` lists every domain from the original CSV, verified origins, currency evidence, adapter, fallback reason, and checkout verification. The ranking spreadsheet is reference material only; it never drives price, stock, shipping, or ranking behavior.

`fragrance-mappings.json` contains reviewed exact identity mappings and their evidence URLs. Mappings must match brand and exact fragrance name; they cannot override a conflicting concentration. No enrichment creates unsupported note layers.

## Deployment

Pushing `main` publishes through Cloudflare Pages at https://scent-compass.pages.dev. Follow AGENTS.md: verify locally, commit task changes, push normally, wait for deployment, and smoke-test affected journeys. The existing GitHub Pages workflow is a secondary publication destination; Cloudflare is primary. Automated refresh commits are normal pushes and never overwrite newer remote work.

## Architecture and verification

- `scripts/refresh_catalogs.py`: public ingestion, normalization, history, validation, reports.
- `catalog-core.js`: pure grouping, availability, neutral ordering, migration, budgets, reconciliation, safe links, and CSV.
- `finder-core.js`: existing note matching and exclusions.
- `app.js`, `index.html`, `styles.css`: accessible static browser experience.
- `catalogs/`: versioned retailer snapshots and manifest.
- `.github/workflows/catalog-refresh.yml`: daily/manual refresh.

```sh
python3 -m unittest discover -s tests -v
npm test
```

Check search, offer ordering, retailer filters, stock states, saved-cart reload, exports, keyboard access, mobile layout, and retailer handoffs in a browser. See ADR-003 for the multi-retailer decision. Existing Decantified CLI tools and the legacy `web_catalog.json` exporter remain available for their original single-retailer workflow.
