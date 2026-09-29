# ADR-002: Browser domain parity with the command-line wizard

## Status
Accepted

## Context
The public product must support the command-line tool's critical discovery and cart-building journeys without a server or ongoing hosting cost.

## Decision
Keep matching, similarity scoring, variant selection, exclusions, price rules, and cart URL construction in a pure JavaScript domain module. Generate a complete static catalog snapshot from the existing Python parser. Keep transient searches in memory and the working cart and final-review rules in local browser storage.

## Consequences
**Positive:** The public experience matches the proven CLI rules, remains free on GitHub Pages, supports multi-round discovery and real Shopify carts, and keeps business logic independently testable.

**Negative:** Inventory is only as current as the last committed export. Cart availability must still be confirmed on Decantified before checkout.

## Alternatives Considered
- Reimplement the Python wizard on a hosted API: introduces operational cost and availability concerns.
- Fetch Shopify directly from every browser: couples the interface to cross-origin policy and store uptime.
- Keep only the simple browse UI: omits the workflows that make the CLI valuable.
