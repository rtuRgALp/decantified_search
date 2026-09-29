#!/usr/bin/env python3
"""Interactive, live-stock fragrance finder for Decantified."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable


BASE_URL = "https://decantified.com"
PRODUCTS_URL = f"{BASE_URL}/products.json"
USER_AGENT = "Mozilla/5.0 (compatible; decantified-scent-wizard/2.0)"
DEFAULT_MAX_EAU_FRAICHE_SCORE = 25
DEFAULT_OUTPUT_DIR = Path("outputs")
SEARCH_FIELDS = ("name", "inspired_by", "top", "heart", "base")
NOTE_LAYERS = ("top", "heart", "base")

# Versace Man Eau Fraiche's characteristic note pyramid. Aliases are kept in
# groups so "star fruit" and "carambola" count as the same reference note.
EAU_FRAICHE_REFERENCE = {
    "top": {
        "lemon": ("lemon",),
        "bergamot": ("bergamot",),
        "carambola": ("carambola", "star fruit"),
        "cardamom": ("cardamom",),
        "brazilian rosewood": ("brazilian rosewood", "rosewood"),
    },
    "heart": {
        "cedar": ("cedar", "cedarwood"),
        "tarragon": ("tarragon",),
        "sage": ("sage",),
        "pepper": ("pepper", "black pepper", "white pepper", "pink pepper"),
    },
    "base": {
        "musk": ("musk", "white musk"),
        "amber": ("amber",),
        "sycamore": ("sycamore", "sycamore wood"),
        "saffron": ("saffron",),
    },
}


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "div", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        joined = html.unescape("".join(self.parts))
        joined = re.sub(r"[ \t\r\f\v]+", " ", joined)
        joined = re.sub(r"\n\s+", "\n", joined)
        joined = re.sub(r"\n{2,}", "\n", joined)
        return joined.strip()


@dataclass(frozen=True)
class Selection:
    layer: str
    term: str


@dataclass(frozen=True)
class Variant:
    id: str
    title: str
    price: str


@dataclass
class Product:
    name: str
    url: str
    inspired_by: str
    top: str
    heart: str
    base: str
    gender: str
    gender_evidence: str
    in_stock_sizes: str
    lowest_in_stock_price: str
    tags: str
    available_variants: list[Variant] = field(repr=False)
    searchable: dict[str, str] = field(repr=False)


def fetch_json(url: str, retries: int = 3, delay: float = 0.5) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(delay * attempt)
    raise RuntimeError(f"Could not fetch {url}: {last_error}")


def fetch_products(limit: int = 250, sleep: float = 0.15) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    page = 1
    while True:
        query = urllib.parse.urlencode({"limit": limit, "page": page})
        batch = fetch_json(f"{PRODUCTS_URL}?{query}").get("products", [])
        if not batch:
            break
        products.extend(batch)
        page += 1
        time.sleep(sleep)
    return products


def html_to_text(body_html: str) -> str:
    parser = TextExtractor()
    parser.feed(body_html or "")
    return parser.text()


def clean_value(value: str) -> str:
    value = re.sub(r"\s+", " ", value)
    value = re.sub(
        r"\s+(?:Scent Profile|Inspired & Occasion|Inspiration & Occasion|"
        r"Try Before You Commit|How it unfolds|Scent Journey|Why You.ll Like It|"
        r"A scent character comparison only)\b.*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return value.strip(" :-\n\t")


def extract_notes(text: str) -> dict[str, str]:
    """Extract explicitly labelled note lines from varied product copy."""
    values: dict[str, str] = {}
    pattern = re.compile(
        r"(?im)^\s*(Top|Heart|Middle)(?:\s*\(Middle\))?\s*(?:Notes?)?\s*:\s*(.+?)\s*$"
        r"|^\s*(Base)\s*(?:Notes?)?\s*:\s*(.+?)\s*$"
    )
    for match in pattern.finditer(text):
        label = (match.group(1) or match.group(3)).lower()
        value = clean_value(match.group(2) or match.group(4))
        if value:
            values[label] = value
    return values


def extract_inspired_by(raw: dict[str, Any], text: str) -> str:
    vendor = str(raw.get("vendor", "")).strip()
    vendor_match = re.match(r"(?i)^(?:inspired\s+by|inspiration)\s*:?\s*(.+)$", vendor)
    if vendor_match:
        return clean_value(vendor_match.group(1))
    text_match = re.search(
        r"(?im)^\s*(?:inspired\s+by|inspiration)\s*:\s*(.+?)\s*$", text
    )
    return clean_value(text_match.group(1)) if text_match else ""


def normalize_term(value: str) -> str:
    value = html.unescape(value).lower().replace("&", " and ")
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[^a-z0-9' -]+", " ", value)
    return re.sub(r"\s+", " ", value).strip(" .:-")


def split_note_terms(value: str) -> list[str]:
    """Split a website note line into selectable, normalized note terms."""
    pieces = re.split(r"\s*(?:,|;|/|\||\u2022|\band\b)\s*", value, flags=re.IGNORECASE)
    terms: list[str] = []
    for piece in pieces:
        term = normalize_term(piece)
        term = re.sub(r"^(?:notes? of|a hint of|touch of)\s+", "", term)
        if term and term not in {"notes", "note"} and term not in terms:
            terms.append(term)
    return terms


def classify_gender(name: str, text: str, tags: Iterable[str]) -> tuple[str, str]:
    haystack = normalize_term(" ".join([name, text, *map(str, tags)]))
    explicit_both_patterns = (
        r"\bfor (?:both )?men and women\b",
        r"\bfor (?:both )?women and men\b",
    )
    unisex_patterns = (r"\bunisex\b", *explicit_both_patterns)
    women_patterns = (
        r"\bfor women\b", r"\bwomen'?s fragrance\b", r"\bfragrance for her\b",
        r"\bpour femme\b", r"\bfeminine\b",
    )
    men_patterns = (
        r"\bfor men\b", r"\bmen'?s fragrance\b", r"\bfragrance for him\b",
        r"\bpour homme\b", r"\bmasculine\b", r"\bman by\b",
    )
    # Remove explicit "for women and men" constructions before looking for
    # women-only wording, while retaining any separate feminine claim.
    women_haystack = haystack
    for pattern in explicit_both_patterns:
        women_haystack = re.sub(pattern, " unisex ", women_haystack)
    women = any(re.search(pattern, women_haystack) for pattern in women_patterns)
    men = any(re.search(pattern, haystack) for pattern in men_patterns)
    unisex = any(re.search(pattern, haystack) for pattern in unisex_patterns)
    # Strict masculine/unisex filtering: feminine evidence is a veto even if
    # marketing copy also uses softer wording such as "unisex-feeling".
    if women:
        return "women", "Feminine wording overrides conflicting unisex or masculine language"
    if unisex:
        return "unisex", "Explicit unisex wording with no feminine language"
    if men:
        return "men", "Explicit masculine wording on the product listing"
    return "unspecified", "No explicit masculine or unisex evidence"


def parse_product(raw: dict[str, Any]) -> Product:
    text = html_to_text(str(raw.get("body_html", "")))
    notes = extract_notes(text)
    inspired_by = extract_inspired_by(raw, text)
    name = str(raw.get("title", "")).strip()
    tags = [str(tag) for tag in raw.get("tags", [])]
    gender, evidence = classify_gender(name, text, tags)
    available = [variant for variant in raw.get("variants", []) if variant.get("available")]
    available_variants = [
        Variant(
            id=str(variant.get("id", "")).strip(),
            title=str(variant.get("title", "")).strip(),
            price=str(variant.get("price", "")).strip(),
        )
        for variant in available
        if variant.get("id") and variant.get("title")
    ]
    sizes = "; ".join(
        f"{str(variant.get('title', '')).strip()} (${str(variant.get('price', '')).strip()})"
        for variant in available if variant.get("title")
    )
    prices = []
    for variant in available:
        try:
            prices.append(float(variant.get("price", "")))
        except (TypeError, ValueError):
            pass
    searchable = {
        "name": name,
        "inspired_by": inspired_by,
        "top": notes.get("top", ""),
        "heart": notes.get("heart", notes.get("middle", "")),
        "base": notes.get("base", ""),
    }
    return Product(
        name=name,
        url=f"{BASE_URL}/products/{raw.get('handle', '')}",
        inspired_by=inspired_by,
        top=searchable["top"], heart=searchable["heart"], base=searchable["base"],
        gender=gender, gender_evidence=evidence, in_stock_sizes=sizes,
        lowest_in_stock_price=f"{min(prices):.2f}" if prices else "",
        tags="; ".join(tags), available_variants=available_variants, searchable=searchable,
    )


def build_note_bank(products: Iterable[Product]) -> dict[str, list[tuple[str, int]]]:
    counts = {layer: Counter() for layer in NOTE_LAYERS}
    all_layer_counts: Counter[str] = Counter()
    for product in products:
        product_terms: set[str] = set()
        for layer in NOTE_LAYERS:
            layer_terms = set(split_note_terms(getattr(product, layer)))
            counts[layer].update(layer_terms)
            product_terms.update(layer_terms)
        all_layer_counts.update(product_terms)
    bank = {
        layer: sorted(count.items(), key=lambda item: (-item[1], item[0]))
        for layer, count in counts.items()
    }
    bank["all"] = sorted(all_layer_counts.items(), key=lambda item: (-item[1], item[0]))
    return bank


def contains_term(text: str, term: str) -> bool:
    normalized_text = normalize_term(text)
    normalized_term = normalize_term(term)
    return bool(normalized_term) and re.search(
        rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])", normalized_text
    ) is not None


def selection_matches(product: Product, selection: Selection) -> list[str]:
    # Like the tobacco search, names and inspiration references are always
    # checked. The selected note layer is additionally checked in-place.
    fields = SEARCH_FIELDS if selection.layer == "all" else ("name", "inspired_by", selection.layer)
    return [field for field in fields if contains_term(product.searchable[field], selection.term)]


def eau_fraiche_similarity(product: Product) -> tuple[int, list[str]]:
    identity = f"{product.name} {product.inspired_by}"
    if re.search(r"\b(?:versace\s+)?man\s+eau\s+fraiche\b", identity, re.IGNORECASE):
        return 100, ["direct Versace Man Eau Fraiche reference"]

    matched: list[str] = []
    total = sum(len(notes) for notes in EAU_FRAICHE_REFERENCE.values())
    for layer, reference_notes in EAU_FRAICHE_REFERENCE.items():
        field_value = getattr(product, layer)
        for canonical, aliases in reference_notes.items():
            if any(contains_term(field_value, alias) for alias in aliases):
                matched.append(f"{layer}: {canonical}")
    return round(100 * len(matched) / total), matched


def filter_products(
    products: Iterable[Product], selections: list[Selection], match_mode: str,
    max_eau_fraiche_score: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for product in products:
        if not product.in_stock_sizes or product.gender not in {"men", "unisex"}:
            continue
        match_map = {
            f"{selection.layer}:{selection.term}": selection_matches(product, selection)
            for selection in selections
        }
        matched_count = sum(bool(fields) for fields in match_map.values())
        qualifies = matched_count == len(selections) if match_mode == "all" else matched_count > 0
        if not qualifies:
            continue
        similarity, similarity_traits = eau_fraiche_similarity(product)
        if similarity > max_eau_fraiche_score:
            continue
        details = "; ".join(
            f"{key} -> {', '.join(fields)}" for key, fields in match_map.items() if fields
        )
        results.append({
            "product_name": product.name, "url": product.url,
            "in_stock_sizes": product.in_stock_sizes,
            "lowest_in_stock_price": product.lowest_in_stock_price,
            "gender": product.gender, "gender_evidence": product.gender_evidence,
            "inspired_by": product.inspired_by, "top": product.top,
            "heart": product.heart, "base": product.base,
            "matched_selections": f"{matched_count}/{len(selections)}",
            "matched_fields": details,
            "eau_fraiche_similarity": similarity,
            "eau_fraiche_shared_traits": "; ".join(similarity_traits),
            "tags": product.tags,
        })
    results.sort(key=lambda row: (
        -int(str(row["matched_selections"]).split("/")[0]),
        int(row["eau_fraiche_similarity"]), row["product_name"].lower(),
    ))
    return results


def prompt_choice(prompt: str, valid: set[str], default: str, input_fn: Callable[[str], str]) -> str:
    while True:
        answer = input_fn(prompt).strip().lower() or default
        if answer in valid:
            return answer
        print(f"Please enter one of: {', '.join(sorted(valid))}.")


def choose_notes(
    bank: dict[str, list[tuple[str, int]]], input_fn: Callable[[str], str] = input,
) -> list[Selection]:
    print("\nChoose notes from Decantified's current catalog.")
    scope = prompt_choice(
        "Search across all note layers or choose layer-specific notes? [all]: ",
        {"all", "layers"}, "all", input_fn,
    )
    layers = ("all",) if scope == "all" else NOTE_LAYERS
    if scope == "all":
        print("Terms selected here can match top, heart, base, name, or inspiration.")
    else:
        print("For each layer, enter words to search its note bank; press Enter to skip.")
    selections: list[Selection] = []
    for layer in layers:
        entries = bank[layer]
        label = "All-layer" if layer == "all" else layer.title()
        print(f"\n{label} bank: {len(entries)} terms from the full catalog")
        preview = ", ".join(term for term, _count in entries[:20])
        print(f"Most common: {preview}")
        while True:
            query = input_fn(f"Search {label.lower()} notes (or Enter when finished): ").strip().lower()
            if not query:
                break
            matches = [(term, count) for term, count in entries if query in term][:30]
            if not matches:
                print("No bank terms matched that search.")
                continue
            for index, (term, count) in enumerate(matches, start=1):
                print(f"  {index:>2}. {term} ({count} product{'s' if count != 1 else ''})")
            raw = input_fn(
                "Add specific numbers, enter 'skip', or press Enter for all matches [all]: "
            ).strip().lower()
            if raw in {"skip", "none"}:
                continue
            try:
                indexes = (
                    list(range(1, len(matches) + 1))
                    if raw in {"", "all"}
                    else [int(value.strip()) for value in raw.split(",")]
                )
                if any(index < 1 or index > len(matches) for index in indexes):
                    raise ValueError
            except ValueError:
                print("Use shown numbers, press Enter for all matches, or enter 'skip'.")
                continue
            for index in indexes:
                selection = Selection(layer, matches[index - 1][0])
                if selection not in selections:
                    selections.append(selection)
                    print(f"Added {label.lower()}: {selection.term}")
    return selections


def write_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for field_name in row:
            if field_name not in fieldnames:
                fieldnames.append(field_name)
    if not fieldnames:
        fieldnames = [
        "product_name", "url", "in_stock_sizes", "lowest_in_stock_price", "gender",
        "gender_evidence", "inspired_by", "top", "heart", "base",
        "matched_selections", "matched_fields", "eau_fraiche_similarity",
        "eau_fraiche_shared_traits", "tags", "cart_selection", "cart_url",
        ]
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def display_results(rows: list[dict[str, Any]]) -> None:
    print(f"\nFound {len(rows)} qualifying scent{'s' if len(rows) != 1 else ''}.")
    for index, row in enumerate(rows, start=1):
        print(f"\n{index}. {row['product_name']} — ${row['lowest_in_stock_price']}+")
        print(f"   Gender: {row['gender']} | Eau Fraiche similarity: {row['eau_fraiche_similarity']}%")
        print(f"   Matched: {row['matched_fields']}")
        print(f"   Inspired by: {row['inspired_by'] or 'Not listed'}")
        print(f"   In stock: {row['in_stock_sizes']}")
        print(f"   {row['url']}")


def variant_sort_key(variant: Variant) -> tuple[int, float, float]:
    """Put the smallest milliliter sample first, with price as a fallback."""
    size_match = re.search(r"(\d+(?:\.\d+)?)\s*ml\b", variant.title, re.IGNORECASE)
    try:
        price = float(variant.price)
    except ValueError:
        price = float("inf")
    if size_match:
        return 0, float(size_match.group(1)), price
    return 1, price, price


def choose_cart(
    rows: list[dict[str, Any]], products_by_url: dict[str, Product],
    input_fn: Callable[[str], str] = input,
    cart_items: dict[str, Variant] | None = None,
) -> str | None:
    if cart_items is None:
        cart_items = {}
    if not rows:
        return None
    print("\nBuild a Decantified cart from these results.")
    while True:
        raw = input_fn(
            "Enter result numbers separated by commas, 'skip', or press Enter for all [all]: "
        ).strip().lower()
        if raw in {"skip", "none"}:
            return None
        if raw in {"", "all"}:
            indexes = list(range(1, len(rows) + 1))
            break
        try:
            indexes = [int(value.strip()) for value in raw.split(",")]
            if not indexes or len(set(indexes)) != len(indexes):
                raise ValueError
            if any(index < 1 or index > len(rows) for index in indexes):
                raise ValueError
            break
        except ValueError:
            print("Use unique result numbers, press Enter for all, or enter 'skip'.")

    selected_products = [
        products_by_url[str(rows[index - 1]["url"])] for index in indexes
    ]
    title_examples: dict[str, Variant] = {}
    for product in selected_products:
        for variant in product.available_variants:
            title_examples.setdefault(variant.title.casefold(), variant)
    size_options = sorted(title_examples.values(), key=variant_sort_key)
    if not size_options:
        print("None of the selected products had a purchasable variant ID.")
        return None
    print("\nChoose one size for all selected scents:")
    for size_index, variant in enumerate(size_options, start=1):
        default = " [default]" if size_index == 1 else ""
        print(f"  {size_index}. {variant.title}{default}")
    while True:
        choice = input_fn("Choose batch size [1]: ").strip()
        try:
            size_index = int(choice) if choice else 1
            if size_index < 1 or size_index > len(size_options):
                raise ValueError
            break
        except ValueError:
            print("Choose one of the batch-size numbers shown above.")
    selected_title = size_options[size_index - 1].title.casefold()

    for index, product in zip(indexes, selected_products):
        row = rows[index - 1]
        variants = sorted(product.available_variants, key=variant_sort_key)
        if not variants:
            print(f"Skipping {product.name}: no purchasable variant ID was available.")
            continue
        variant = next(
            (item for item in variants if item.title.casefold() == selected_title),
            variants[0],
        )
        fallback = " (smallest available fallback)" if variant.title.casefold() != selected_title else ""
        print(f"  {product.name}: {variant.title} (${variant.price}){fallback}")
        cart_items[product.url] = variant
        row["cart_selection"] = f"{variant.title} (${variant.price})"

    if not cart_items:
        return None
    cart_url = build_cart_url(cart_items)
    for index in indexes:
        row = rows[index - 1]
        if row.get("cart_selection"):
            row["cart_url"] = cart_url
    print("\nYour prefilled Decantified cart:")
    print(cart_url)
    print("Review the cart and availability on Decantified before checking out.")
    return cart_url


def build_cart_url(cart_items: dict[str, Variant]) -> str:
    variants = ",".join(f"{variant.id}:1" for variant in cart_items.values())
    return f"{BASE_URL}/cart/{variants}?storefront=true"


def prompt_another_search(input_fn: Callable[[str], str] = input) -> bool:
    while True:
        answer = input_fn("\nRun another narrow note search for this cart? [y/N]: ").strip().lower()
        if answer in {"", "n", "no"}:
            return False
        if answer in {"y", "yes"}:
            return True
        print("Enter y for another search or n to finish the cart.")


def choose_exclusion_terms(
    bank: dict[str, list[tuple[str, int]]], input_fn: Callable[[str], str] = input,
) -> list[str]:
    answer = prompt_choice(
        "\nDo you want to add exclusion terms? [Y/n]: ",
        {"y", "yes", "n", "no"}, "yes", input_fn,
    )
    if answer in {"n", "no"}:
        return []

    entries = bank["all"]
    exclusions: list[str] = []
    print("Exclusions are checked in product names, inspirations, top, heart, and base notes.")
    while True:
        query = input_fn("Search exclusion terms (or Enter when finished): ").strip().lower()
        if not query:
            break
        matches = [(term, count) for term, count in entries if query in term][:30]
        if not matches:
            print("No website note terms matched that search.")
            continue
        for index, (term, count) in enumerate(matches, start=1):
            print(f"  {index:>2}. {term} ({count} product{'s' if count != 1 else ''})")
        raw = input_fn(
            "Add specific numbers, enter 'skip', or press Enter for all matches [all]: "
        ).strip().lower()
        if raw in {"skip", "none"}:
            continue
        try:
            indexes = (
                list(range(1, len(matches) + 1))
                if raw in {"", "all"}
                else [int(value.strip()) for value in raw.split(",")]
            )
            if not indexes or any(index < 1 or index > len(matches) for index in indexes):
                raise ValueError
        except ValueError:
            print("Use shown numbers, press Enter for all matches, or enter 'skip'.")
            continue
        for index in indexes:
            term = matches[index - 1][0]
            if term not in exclusions:
                exclusions.append(term)
                print(f"Excluded term: {term}")
    return exclusions


def apply_cart_exclusions(
    cart_items: dict[str, Variant], products_by_url: dict[str, Product],
    exclusion_terms: Iterable[str],
) -> dict[str, dict[str, list[str]]]:
    removed: dict[str, dict[str, list[str]]] = {}
    terms = list(exclusion_terms)
    for product_url in list(cart_items):
        product = products_by_url[product_url]
        matches = {
            term: selection_matches(product, Selection("all", term))
            for term in terms
        }
        matches = {term: fields for term, fields in matches.items() if fields}
        if matches:
            removed[product_url] = matches
            del cart_items[product_url]
    return removed


def apply_cart_exact_exclusions(
    cart_items: dict[str, Variant], products_by_url: dict[str, Product],
    exact_terms: Iterable[str],
) -> dict[str, dict[str, list[str]]]:
    removed: dict[str, dict[str, list[str]]] = {}
    normalized_terms = [normalize_term(term) for term in exact_terms]
    for product_url in list(cart_items):
        product = products_by_url[product_url]
        matches: dict[str, list[str]] = {}
        for term in normalized_terms:
            fields = [
                layer for layer in NOTE_LAYERS
                if term in split_note_terms(getattr(product, layer))
            ]
            if normalize_term(product.name) == term:
                fields.append("name")
            if normalize_term(product.inspired_by) == term:
                fields.append("inspired_by")
            if fields:
                matches[term] = fields
        if matches:
            removed[product_url] = matches
            del cart_items[product_url]
    return removed


def prompt_cart_price_limit(input_fn: Callable[[str], str] = input) -> float | None:
    while True:
        raw = input_fn(
            "\nMaximum price for each selected cart item, or Enter for no limit: $"
        ).strip()
        if not raw:
            return None
        try:
            value = float(raw.removeprefix("$").strip())
            if value < 0:
                raise ValueError
            return value
        except ValueError:
            print("Enter a non-negative amount such as 2.50, or press Enter for no limit.")


def apply_cart_price_limit(
    cart_items: dict[str, Variant], max_price: float | None,
) -> dict[str, Variant]:
    removed: dict[str, Variant] = {}
    if max_price is None:
        return removed
    for product_url in list(cart_items):
        variant = cart_items[product_url]
        try:
            price = float(variant.price)
        except ValueError:
            # Unknown prices cannot be proven to satisfy an explicit ceiling.
            removed[product_url] = variant
            del cart_items[product_url]
            continue
        if price > max_price:
            removed[product_url] = variant
            del cart_items[product_url]
    return removed


def default_output_path() -> Path:
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return DEFAULT_OUTPUT_DIR / f"decantified-scent-results-{stamp}.csv"


def non_negative_price(value: str) -> float:
    try:
        price = float(value.removeprefix("$").strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("price must be a number such as 2.50") from exc
    if price < 0:
        raise argparse.ArgumentTypeError("price cannot be negative")
    return price


def run_quick_search(
    products: list[Product], bank: dict[str, list[tuple[str, int]]],
    args: argparse.Namespace,
) -> Path:
    products_by_url = {product.url: product for product in products}
    cart_items: dict[str, Variant] = {}
    all_rows: list[dict[str, Any]] = []
    max_score = args.max_eau_fraiche_score
    max_score = DEFAULT_MAX_EAU_FRAICHE_SCORE if max_score is None else max(0, min(100, max_score))

    for round_number, queries in enumerate(args.quick_search, start=1):
        terms: list[str] = []
        for query in queries:
            normalized_query = normalize_term(query)
            for term, _count in bank["all"]:
                if normalized_query in term and term not in terms:
                    terms.append(term)
        if not terms:
            print(f"Quick search {round_number}: no bank terms matched {', '.join(queries)}.")
            continue
        selections = [Selection("all", term) for term in terms]
        rows = filter_products(products, selections, "any", max_score)
        selected_text = ", ".join(terms)
        for row in rows:
            row["search_round"] = round_number
            row["search_terms"] = selected_text
            row["search_match_mode"] = "any"
        print(f"\nQuick search {round_number} ({', '.join(queries)}): {len(rows)} scents")
        for row in rows:
            product = products_by_url[str(row["url"])]
            variants = sorted(product.available_variants, key=variant_sort_key)
            if variants:
                cart_items[product.url] = variants[0]
        all_rows.extend(rows)

    expanded_exclusions: list[str] = []
    for query in args.exclude_all or []:
        normalized_query = normalize_term(query)
        for term, _count in bank["all"]:
            if normalized_query in term and term not in expanded_exclusions:
                expanded_exclusions.append(term)
    exact_exclusions = [normalize_term(term) for term in (args.exclude_exact or [])]
    exact_removed = apply_cart_exact_exclusions(cart_items, products_by_url, exact_exclusions)
    removed = apply_cart_exclusions(cart_items, products_by_url, expanded_exclusions)
    removed.update(exact_removed)
    price_removed = apply_cart_price_limit(cart_items, args.max_cart_price)
    final_cart_url = build_cart_url(cart_items) if cart_items else ""

    for row in all_rows:
        product_url = str(row["url"])
        term_matches = removed.get(product_url)
        if term_matches:
            row["excluded_from_cart"] = "yes"
            row["exclusion_matches"] = "; ".join(
                f"{term} -> {', '.join(fields)}" for term, fields in term_matches.items()
            )
        price_variant = price_removed.get(product_url)
        if price_variant:
            row["excluded_from_cart"] = "yes"
            row["price_exclusion"] = (
                f"{price_variant.title} (${price_variant.price}) exceeds ${args.max_cart_price:.2f}"
            )
        variant = cart_items.get(product_url)
        if variant:
            row["cart_selection"] = f"{variant.title} (${variant.price})"
            row["cart_url"] = final_cart_url

    print(f"\nQuick-search cart: {len(cart_items)} scents")
    if final_cart_url:
        print(final_cart_url)
    print(f"Excluded by terms: {len(removed)}; excluded by price: {len(price_removed)}")
    output_path = Path(args.output) if args.output else default_output_path()
    write_csv(all_rows, output_path)
    print(f"Saved {output_path.resolve()}")
    return output_path


def run_wizard(
    raw_products: list[dict[str, Any]], args: argparse.Namespace,
    input_fn: Callable[[str], str] = input,
) -> Path | None:
    products = [parse_product(raw) for raw in raw_products]
    bank = build_note_bank(products)
    print(
        f"Scanned {len(products)} products and built a bank of "
        + ", ".join(f"{len(bank[layer])} {layer}" for layer in NOTE_LAYERS)
        + " note terms."
    )
    if getattr(args, "quick_search", None):
        return run_quick_search(products, bank, args)
    products_by_url = {product.url: product for product in products}
    cart_items: dict[str, Variant] = {}
    all_rows: list[dict[str, Any]] = []
    round_number = 1
    max_score = args.max_eau_fraiche_score
    if max_score is None:
        raw_score = input_fn(
            f"Maximum Versace Man Eau Fraiche similarity for every search, 0-100 "
            f"[{DEFAULT_MAX_EAU_FRAICHE_SCORE}]: "
        ).strip()
        try:
            max_score = int(raw_score) if raw_score else DEFAULT_MAX_EAU_FRAICHE_SCORE
        except ValueError:
            print(f"Invalid score; using {DEFAULT_MAX_EAU_FRAICHE_SCORE}.")
            max_score = DEFAULT_MAX_EAU_FRAICHE_SCORE
    max_score = max(0, min(100, max_score))
    while True:
        print(f"\n{'=' * 18} Search {round_number} {'=' * 18}")
        selections = choose_notes(bank, input_fn)
        if not selections:
            if not all_rows:
                print("No notes selected; nothing was searched.")
                return None
            print("No notes selected; finishing the combined cart.")
            break

        selected_text = ", ".join(f"{item.layer}: {item.term}" for item in selections)
        print("\nSelected: " + selected_text)
        match_mode = args.match or prompt_choice(
            "Within this search, require all selected notes or any selected note? [any]: ",
            {"all", "any"}, "any", input_fn,
        )
        match_mode = "any" if match_mode == "any" else "all"
        rows = filter_products(products, selections, match_mode, max_score)
        for row in rows:
            row["search_round"] = round_number
            row["search_terms"] = selected_text
            row["search_match_mode"] = match_mode
        display_results(rows)
        choose_cart(rows, products_by_url, input_fn, cart_items)
        all_rows.extend(rows)
        if not prompt_another_search(input_fn):
            break
        round_number += 1

    exclusion_terms = choose_exclusion_terms(bank, input_fn) if cart_items else []
    removed = apply_cart_exclusions(cart_items, products_by_url, exclusion_terms)
    if removed:
        print(f"\nRemoved {len(removed)} scent{'s' if len(removed) != 1 else ''} from the cart:")
        for product_url, term_matches in removed.items():
            product = products_by_url[product_url]
            details = "; ".join(
                f"{term} in {', '.join(fields)}" for term, fields in term_matches.items()
            )
            print(f"- {product.name}: {details}")

    configured_price_limit = getattr(args, "max_cart_price", None)
    max_cart_price = configured_price_limit
    if cart_items and max_cart_price is None:
        max_cart_price = prompt_cart_price_limit(input_fn)
    price_removed = apply_cart_price_limit(cart_items, max_cart_price)
    if price_removed:
        print(
            f"\nRemoved {len(price_removed)} scent"
            f"{'s' if len(price_removed) != 1 else ''} above the "
            f"${max_cart_price:.2f} per-item limit:"
        )
        for product_url, variant in price_removed.items():
            print(f"- {products_by_url[product_url].name}: {variant.title} (${variant.price})")

    final_cart_url = build_cart_url(cart_items) if cart_items else ""
    for row in all_rows:
        row.pop("cart_selection", None)
        row.pop("cart_url", None)
        term_matches = removed.get(str(row["url"]))
        if term_matches:
            row["excluded_from_cart"] = "yes"
            row["exclusion_matches"] = "; ".join(
                f"{term} -> {', '.join(fields)}" for term, fields in term_matches.items()
            )
        price_variant = price_removed.get(str(row["url"]))
        if price_variant:
            row["excluded_from_cart"] = "yes"
            row["price_exclusion"] = (
                f"{price_variant.title} (${price_variant.price}) exceeds "
                f"${max_cart_price:.2f}"
            )
    if final_cart_url:
        print(f"\nCombined cart: {len(cart_items)} scent{'s' if len(cart_items) != 1 else ''}")
        print(final_cart_url)
        for row in all_rows:
            variant = cart_items.get(str(row["url"]))
            if variant:
                row["cart_selection"] = f"{variant.title} (${variant.price})"
                row["cart_url"] = final_cart_url
    elif removed or price_removed:
        print("\nThe final filters removed every selected scent, so no cart link was created.")

    output_path = Path(args.output) if args.output else default_output_path()
    write_csv(all_rows, output_path)
    print(f"\nSaved {output_path.resolve()}")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Interactively find live, in-stock masculine or unisex Decantified scents."
    )
    parser.add_argument("-o", "--output", help="CSV output path (default: timestamped file in outputs).")
    parser.add_argument("--match", choices=("all", "any"), help="Skip the match-mode prompt.")
    parser.add_argument(
        "--max-eau-fraiche-score", type=int, metavar="0-100",
        help=f"Maximum similarity score (default prompt: {DEFAULT_MAX_EAU_FRAICHE_SCORE}).",
    )
    parser.add_argument(
        "--max-cart-price", type=non_negative_price, metavar="AMOUNT",
        help="Maximum price for each selected cart variant, such as 2.50.",
    )
    parser.add_argument(
        "--quick-search", action="append", nargs="+", metavar="TERM",
        help="Run one non-interactive all-layer search group; repeat for narrow groups.",
    )
    parser.add_argument(
        "--exclude-all", nargs="+", metavar="TERM",
        help="In quick mode, exclude all bank terms containing each value.",
    )
    parser.add_argument(
        "--exclude-exact", nargs="+", metavar="TERM",
        help="In quick mode, exclude only exact note terms.",
    )
    parser.add_argument(
        "--catalog", type=Path,
        help="Read a saved products.json fixture instead of the live site (for testing).",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.catalog:
        data = json.loads(args.catalog.read_text(encoding="utf-8"))
        raw_products = data.get("products", data) if isinstance(data, dict) else data
    else:
        print("Fetching Decantified's complete live catalog and current stock...")
        try:
            raw_products = fetch_products()
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
    run_wizard(raw_products, args)


if __name__ == "__main__":
    main()
