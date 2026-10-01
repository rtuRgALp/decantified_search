# ADR-003: Independent retailer offers with daily static snapshots

## Status
Accepted

## Decision
Use standard-library public Shopify and WooCommerce adapters to publish per-retailer versioned JSON snapshots. Daily public-repository GitHub Actions run at 09:17 UTC; manual refreshes are supported. Cloudflare Pages publishes main. Standard Ubuntu runners are free for this public repository; the refresh does not create billable artifacts or caches and refuses to run if the repository becomes private.

Separate fragrance identity, retailer listing, and size variants. Only explicit brand/name/concentration identities group automatically. Keep provenance and ambiguous identities separate. Available variants, prices, budgets, and checkout belong to an individual retailer and currency. Never infer stock from a refresh failure or substitute retailers silently.

Every searchable retailer is selected by default. Fragrances rank by note relevance, then name and identity; offers rank alphabetically unless the user requests an equal-volume, equal-currency price comparison. CSV rankings and historical shipping assertions never control the public experience.

Keep unavailable selections visible. Last observations become overdue after 36 hours and unverified after 72 hours. Publish both sold-out and available samples; initial imports are not new releases. Subsequent offers retain first-seen dates and show “Newly listed” for 30 days.

## Consequences
Static hosting remains inexpensive and independent of retailer uptime. Daily catalog discovery includes new listings and restocks, but stock can change between observations and checkout. Each retailer requires explicit evidence and acceptance checks; unsupported stores remain in the directory. Public endpoints may rate-limit or change. Full catalog failures and count collapses retain prior snapshots.

## Alternatives
Live browser requests depend on CORS and retailer uptime. A hosted stock proxy would add an operational service. Neither is required for the daily-freshness goal.
