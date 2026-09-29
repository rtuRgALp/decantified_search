# ADR-001: Static, dependency-free GitHub Pages application

## Status
Accepted

## Context
The product must be free to operate, easy to share, fast on mobile, and primarily drive qualified visitors to Decantified.com. The existing project contains a catalog snapshot and Python tooling, but a visitor should not need a server or account.

## Decision
Build the experience with semantic HTML, modern CSS, and dependency-free JavaScript. Store the catalog snapshot as checked-in JSON, deploy with GitHub Actions, and link every result to its Decantified product page with campaign parameters. Keep presentation, filtering logic, and catalog data separate.

## Consequences
**Positive:** No hosting bill or server maintenance, fast delivery, simple local preview, transparent outbound links, and minimal supply-chain risk.

**Negative:** Catalog freshness depends on rebuilding and committing the snapshot. There is no server-side personalization or inventory guarantee.

## Alternatives Considered
- React/Next.js: build complexity without a current product need.
- Hosted database/API: introduces cost, secrets, and maintenance.
- Live store requests: vulnerable to cross-origin restrictions and couples page load to a second service.
