#!/usr/bin/env python3
"""Export the live Decantified catalog for the static GitHub Pages app."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from decantified_scent_wizard import build_note_bank, fetch_products, parse_product


def export_catalog(raw_products: list[dict], output: Path) -> dict:
    products = [parse_product(raw) for raw in raw_products]
    eligible = [
        product for product in products
        if product.gender in {"men", "unisex"} and product.available_variants
    ]
    bank = build_note_bank(products)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "https://decantified.com/products.json",
        "eligibility": "In-stock products explicitly described as masculine or unisex",
        "note_bank": {
            layer: [{"term": term, "count": count} for term, count in entries]
            for layer, entries in bank.items()
        },
        "products": [
            {
                "id": index,
                "name": product.name,
                "url": product.url,
                "inspired_by": product.inspired_by,
                "top": product.top,
                "heart": product.heart,
                "base": product.base,
                "gender": product.gender,
                "gender_evidence": product.gender_evidence,
                "lowest_in_stock_price": product.lowest_in_stock_price,
                "tags": product.tags,
                "variants": [
                    {"id": variant.id, "title": variant.title, "price": variant.price}
                    for variant in product.available_variants
                ],
            }
            for index, product in enumerate(eligible)
        ],
    }
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, help="Use a saved products.json fixture")
    parser.add_argument("--output", type=Path, default=Path("web_catalog.json"))
    args = parser.parse_args()
    if args.catalog:
        data = json.loads(args.catalog.read_text(encoding="utf-8"))
        raw_products = data.get("products", data) if isinstance(data, dict) else data
    else:
        raw_products = fetch_products()
    payload = export_catalog(raw_products, args.output)
    print(
        f"Exported {len(payload['products'])} eligible products and "
        f"{len(payload['note_bank']['all'])} note terms to {args.output}"
    )


if __name__ == "__main__":
    main()
