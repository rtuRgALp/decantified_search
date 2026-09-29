# Decantified Scent Finder

A modern, zero-backend fragrance discovery experience that translates the complete command-line scent wizard into a shareable browser product.

## Product shape

- Search the live-exported, in-stock masculine and unisex catalog by note or note layer.
- Choose any/all matching and a maximum Versace Man Eau Fraiche similarity.
- Run independent search rounds and combine selections in one working scent edit.
- Apply one batch size with smallest-available fallbacks, then adjust individual sizes.
- Apply term or exact-note exclusions and a per-item price ceiling.
- Open one prefilled Decantified cart or download the complete review as CSV.
- Browse freely by mood, name, inspiration, and note, with “Surprise me” discovery.

The site is intentionally static: HTML, CSS, JavaScript, and a checked-in JSON catalog. There are no runtime services, accounts, paid APIs, or framework dependencies.

## Preview locally

```bash
python3 -m http.server 8000
```

Open `http://localhost:8000`. Opening `index.html` directly will not load the JSON catalog because browsers restrict local file requests.

## Deploy with GitHub Pages

1. Push this folder to the repository's `main` branch.
2. Open **Settings → Pages** in GitHub.
3. Set **Build and deployment → Source** to **GitHub Actions**.
4. The included workflow publishes the site on every push to `main`.

GitHub shows the public URL in the workflow summary and Pages settings. Hosting and deployment use GitHub’s free static infrastructure.

## Refresh the catalog

The interface reads `web_catalog.json`. Refresh it from Decantified's public catalog with:

```bash
python3 -m scripts.build_web_catalog --output web_catalog.json
```

The export records its timestamp, the full note bank, eligible products, current in-stock variants, prices, and Shopify variant IDs. Review and commit the generated snapshot to publish it.

## Architecture

See [ADR-001](docs/adr/001-static-github-pages.md). Core boundaries:

- `index.html`: accessible page structure and content
- `styles.css`: responsive visual system
- `finder-core.js`: testable matching, similarity, exclusion, variant, and cart rules
- `app.js`: interaction, persistence, rendering, CSV export, and browser orchestration
- `web_catalog.json`: replaceable full-catalog snapshot
- `scripts/build_web_catalog.py`: reproducible catalog exporter
- `.github/workflows/pages.yml`: free GitHub Pages deployment
- `decantified_scent_wizard.py`: existing catalog/search domain tooling

## Verify

```bash
python3 -m unittest discover -s tests -v
/Users/luisvargas/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --test tests/finder-core.test.mjs
```

Then preview the site and check search, mood filters, product dialogs, outbound links, keyboard navigation, and narrow-screen layout.
