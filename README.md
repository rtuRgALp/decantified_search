# Decantified Scent Finder

A modern, zero-backend fragrance discovery experience designed to help people find promising samples and continue to [Decantified.com](https://decantified.com).

## Product shape

- Explore a curated catalog by mood: fresh, warm, bold, or smooth.
- Search fragrance names, inspirations, descriptions, and notes.
- Open a focused scent profile and continue to its Decantified product.
- Use “Surprise me” when there is no specific note in mind.
- Attribute outbound visits with UTM campaign parameters.

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

The interface reads `decantified_product_metadata.json`. The existing Python utilities contain the source parsing and matching logic used to build catalog data. Refresh that file, validate the site locally, and commit the updated snapshot. The browser derives display notes and scent moods from the catalog description, avoiding duplicate UI data.

The current snapshot is a curated subset. A useful next iteration is adapting `decantified_scent_wizard.py` to export the complete in-stock catalog into the same metadata shape during an intentional content refresh.

## Architecture

See [ADR-001](docs/adr/001-static-github-pages.md). Core boundaries:

- `index.html`: accessible page structure and content
- `styles.css`: responsive visual system
- `app.js`: catalog normalization, filtering, rendering, and details
- `decantified_product_metadata.json`: replaceable catalog snapshot
- `.github/workflows/pages.yml`: free GitHub Pages deployment
- `decantified_scent_wizard.py`: existing catalog/search domain tooling

## Verify

```bash
python3 -m unittest discover -s tests -v
```

Then preview the site and check search, mood filters, product dialogs, outbound links, keyboard navigation, and narrow-screen layout.
