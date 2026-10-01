"""Refresh independent, validated public retailer snapshots. Standard library only."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from decantified_scent_wizard import html_to_text, extract_notes, extract_inspired_by

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 2
SAMPLE = re.compile(r"\b(?:samples?|decants?|décants?|decanted|staaltjes?|muestras?|amostras?|campioni|campione|échantillons?|atomizers?|spray vial|travel spray|spray sample)\b", re.I)
NON_FRAGRANCE = re.compile(r"\b(?:gift card|empty (?:bottle|vial)|accessories|discovery set|sample set|bundle|subscription)\b", re.I)
CONCENTRATION = re.compile(r"\b(extrait(?: de parfum)?|eau de parfum|eau de toilette|eau de cologne|EDP|EDT|EDC|parfum)\b", re.I)
BRAND_ALIASES = {"paris corner": "Paris Corner", "riiffs": "RiiFFS", "maison alhambra": "Maison Alhambra"}


def apply_reviewed_identity(product):
    """Exact, retailer-agnostic reviewed identities; never override conflicting concentrations."""
    path = ROOT / 'fragrance-mappings.json'
    mappings = json.loads(path.read_text())['mappings'] if path.exists() else []
    identity_data = product['fragrance']
    for mapping in mappings:
        if normalize(identity_data.get('brand')) != normalize(mapping['brand']) or normalize(identity_data['name']) != normalize(mapping['name']):
            continue
        if identity_data.get('concentration') and identity_data['concentration'] != mapping['concentration']:
            continue
        identity_data.update(brand=mapping['brand'], name=mapping['name'], concentration=mapping['concentration'])
        evidence = f"Reviewed exact identity: {mapping['evidence_url']}"
        if evidence not in identity_data['evidence']:
            identity_data['evidence'].append(evidence)
        product['identity_evidence_url'] = mapping['evidence_url']
        break
    if identity_data.get('brand') and identity_data.get('concentration'):
        key = '|'.join(normalize(identity_data[k]) for k in ('brand', 'name', 'concentration'))
        product['fragrance_id'] = 'fragrance:' + hashlib.sha256(key.encode()).hexdigest()[:24]
    return product


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize(value):
    return re.sub(r"[^\w]+", " ", str(value).casefold(), flags=re.UNICODE).strip()


def safe_url(url, retailer):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or f"https://{parsed.netloc}" not in retailer["approved_origins"]:
        raise ValueError(f"Unapproved retailer URL: {url}")
    return url


def request_json(url, retailer, attempt=0, decode_json=True):
    safe_url(url, retailer)
    # Redirect destinations must be approved before making the redirected request.
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            safe_url(newurl, retailer)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    req = urllib.request.Request(url, headers={"User-Agent": "ScentCompass/3.0 public catalog refresh", "Accept": "application/json"})
    try:
        with urllib.request.build_opener(Redirect).open(req, timeout=30) as response:
            safe_url(response.url, retailer)
            return (json.load(response) if decode_json else response.read(3000000).decode('utf-8', 'replace')), dict(response.headers)
    except urllib.error.HTTPError as exc:
        response_excerpt = exc.read(1000).decode('utf-8', 'replace')
        if 'Verifying your connection' in response_excerpt or 'captcha' in response_excerpt.lower():
            raise ValueError(f"Retailer connection verification blocks public catalog access (HTTP {exc.code}); no challenge bypass attempted") from exc
        if exc.code not in (408, 429, 500, 502, 503, 504) or attempt >= 2:
            raise
        retry_after = exc.headers.get('Retry-After')
        if retry_after and retry_after.isdigit():
            if int(retry_after) > 60:
                raise ValueError('Retailer requested a long retry delay; deferred to next refresh') from exc
            time.sleep(int(retry_after))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        if attempt >= 2:
            raise
    time.sleep(2 ** attempt)
    return request_json(url, retailer, attempt + 1, decode_json)


def verify_shopify_currency(retailer):
    """Product JSON has no currency field: reconfirm storefront currency before assigning amounts."""
    page, _ = request_json(retailer['origin'] + '/', retailer, decode_json=False)
    match = re.search(r'Shopify\.currency\s*=\s*\{\s*"active"\s*:\s*"([A-Z]{3})"', page)
    if not match:
        raise ValueError('Native catalog currency could not be reconfirmed from storefront metadata')
    if match[1] != retailer['currency']:
        raise ValueError(f"Storefront currency changed ({match[1]}); configuration review required")


def fetch_shopify(retailer, get=request_json, collection=None):
    products, seen = [], set()
    for page in range(1, 1001):
        prefix = f"/collections/{collection}" if collection else ""
        data, _ = get(f"{retailer['origin']}{prefix}/products.json?page={page}&limit=250", retailer)
        batch = data.get("products") if isinstance(data, dict) else None
        if not isinstance(batch, list):
            raise ValueError("Invalid Shopify page")
        if not batch:
            return products
        for product in batch:
            key = str(product.get("id", ""))
            if not key or key in seen:
                raise ValueError("Missing/duplicate product ID or repeated pagination")
            seen.add(key)
            products.append(product)
        time.sleep(.15)
    raise ValueError("Pagination limit reached; refusing incomplete catalog")


def fetch_woocommerce(retailer, get=request_json):
    products, seen = [], set()
    total_pages = None
    for page in range(1, 1001):
        data, headers = get(f"{retailer['origin']}/wp-json/wc/store/v1/products?per_page=100&page={page}", retailer)
        if not isinstance(data, list):
            raise ValueError("Invalid WooCommerce page")
        header_map = {k.lower(): v for k, v in headers.items()}
        if "x-wp-totalpages" in header_map:
            declared = int(header_map["x-wp-totalpages"])
            if total_pages is not None and declared != total_pages:
                raise ValueError("Catalog changed during pagination; retry next run")
            total_pages = declared
        for product in data:
            key = str(product.get("id", ""))
            if not key or key in seen:
                raise ValueError("Missing/duplicate WooCommerce product ID")
            seen.add(key)
            products.append(product)
        if not data or (total_pages is not None and page >= total_pages):
            break
        time.sleep(.15)
    else:
        raise ValueError("Pagination limit reached")
    # Batch variation IDs across parents; a public catalog may contain thousands of offers.
    variations = [v for p in products for v in p.get('variations', [])]
    by_id = {}
    for offset in range(0, len(variations), 50):
        ids = [str(v['id']) for v in variations[offset:offset + 50]]
        data, _ = get(f"{retailer['origin']}/wp-json/wc/store/v1/products?type=variation&per_page=100&include={','.join(ids)}", retailer)
        if not isinstance(data, list) or {str(v.get('id')) for v in data} != set(ids):
            raise ValueError('Incomplete variation data')
        by_id.update({str(v['id']): v for v in data})
        time.sleep(.3)
    for product in products:
        detailed = []
        for variation in product.get('variations', []):
            record = by_id[str(variation['id'])]
            record['selection_attributes'] = variation.get('attributes', [])
            detailed.append(record)
        product['detailed_variations'] = detailed
    return products


def volume(label):
    # The first explicit volume is the fragrance amount, not a parenthesized vial capacity.
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*ml\b", label, re.I)
    return float(match[1].replace(",", ".")) if match else None


def minor_price(value, already_minor=False):
    try:
        amount = Decimal(str(value)) * (1 if already_minor else 100)
    except InvalidOperation as exc:
        raise ValueError("Invalid price") from exc
    if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
        raise ValueError("Invalid minor-unit price")
    return int(amount)


def identity(name, brand, retailer):
    evidence = []
    # Remove retailer merchandising badges, not meaningful fragrance flankers.
    name = re.sub(r'^\s*\((?:rare find|rare gem|\d{4} release)\)\s*[–—-]?\s*', '', name, flags=re.I)
    name = re.sub(r"\([^)]*(?:sample|decant)[^)]*\)", "", name, flags=re.I).strip()
    title = re.sub(r"\s*[|–—-]?\s*(?:fragrance sample|sample sizes|sample decant|decant sample|sample/decant|sample|decant)(?:\s*[/|–—-]\s*(?:sample|decant))?\b.*$", "", name, flags=re.I).strip(" |–—-")
    title = re.sub(r"\([^)]*(?:sample|decant)[^)]*\)", "", title, flags=re.I).strip()
    # Product titles often explicitly state a brand more reliably than Shopify vendor.
    by = re.search(r"\s+by\s+([^|]+)$", title, re.I)
    dash = re.search(r"^(.+?)\s+[–—-]\s+([^–—-]+)$", title)
    if by:
        brand, title = by[1].strip(), title[:by.start()].strip()
        evidence.append("brand explicitly stated in listing title")
    elif dash and brand and normalize(dash[1]) == normalize(brand):
        title = dash[2].strip()
        evidence.append("brand field agrees with title prefix")
    elif dash and not CONCENTRATION.fullmatch(dash[2].strip()) and (normalize(dash[2]) == normalize(brand) or retailer.get('title_brand_position') == 'after_separator'):
        brand, title = dash[2].strip(), dash[1].strip()
        evidence.append("brand explicitly stated after title separator")
    elif brand:
        evidence.append("retailer product brand field")
    if brand and (normalize(brand) in {normalize(retailer['name']), normalize(retailer['id']), normalize(retailer['original_domain']), 'my store'} or re.search(r"inspir|sample|decant", brand, re.I)):
        brand = ""
    brand = BRAND_ALIASES.get(normalize(brand), brand)
    conc_match = CONCENTRATION.search(title)
    concentration = None
    if conc_match:
        concentration = {"eau de parfum": "EDP", "edp": "EDP", "eau de toilette": "EDT", "edt": "EDT", "eau de cologne": "EDC", "edc": "EDC", "extrait de parfum": "Extrait", "extrait": "Extrait", "parfum": "Parfum"}[conc_match[0].lower()]
        title = (title[:conc_match.start()] + title[conc_match.end():]).strip(" |–—-")
        evidence.append("concentration explicitly stated in listing title")
    if brand:
        without_brand = re.sub(r"^" + re.escape(brand) + r"\s+[–—-]?\s*", "", title, flags=re.I).strip()
        # An eponymous perfume (e.g. Coach Parfum) still has a name after concentration removal.
        if re.sub(r'\b(?:women|men|woman|man|unisex|for|pour)\b|[()\s]', '', without_brand, flags=re.I):
            title = without_brand
    title = re.sub(r"\s+", " ", title).strip()
    return {"name": title or name, "brand": brand or None, "concentration": concentration, "evidence": evidence}


def normalize_product(raw, retailer, observed):
    woo = retailer["adapter"] == "woocommerce"
    source_id = str(raw.get("id", ""))
    if not source_id:
        raise ValueError("Missing source product ID")
    name = html_to_text(raw.get("name" if woo else "title", ""))
    if not name:
        raise ValueError("Missing product name")
    description = html_to_text(raw.get("description" if woo else "body_html", "") or "")
    tags = raw.get("tags", [])
    if woo:
        tags = [t.get("name", "") for t in tags]
    if isinstance(tags, str):
        tags = tags.split(",")
    context = " ".join([name, description, str(raw.get('product_type', '')), *tags])
    if NON_FRAGRANCE.search(name) or re.search(r"\b(?:full bottles?|retail bottles?|sealed bottles?)\b", name, re.I):
        return None
    if re.fullmatch(r'(?:(?:samples?|decants?)\s*)?\d+(?:[.,]\d+)?\s*ml(?:\s*[/|,]\s*\d+(?:[.,]\d+)?\s*ml)*', name, re.I):
        # Generic configurable samples do not identify a fragrance to search or compare.
        return None
    explicit = bool(SAMPLE.search(context))
    reviewed = raw.get("verified_sample_catalog")
    rule = retailer["decant_rule"].get("reviewed_catalog", {})
    variants = []
    records = (raw.get("detailed_variations") or ([raw] if raw.get("type") == "simple" else [])) if woo else raw.get("variants", [])
    for v in records:
        label = " / ".join(a.get("value", "") for a in v.get("selection_attributes", [])) if woo else str(v.get("title", ""))
        if not label or label == "Default Title":
            label = name
        size = volume(label)
        if size is None and explicit:
            size = volume(name)
        if not size or size > retailer["decant_rule"]["max_ml"] or not (explicit or SAMPLE.search(label) or (reviewed and (not rule.get("sizes_ml") or size in rule["sizes_ml"]))) or re.search(r'\b(?:full bottle|retail bottle|sealed bottle)\b', label, re.I):
            continue
        prices = v.get("prices", {}) if woo else {}
        currency = prices.get("currency_code") if woo else retailer["currency"]
        if not currency or not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("Missing currency")
        if currency != retailer['currency']:
            raise ValueError('Catalog currency differs from verified retailer configuration')
        if woo and prices.get("currency_minor_unit") != 2:
            raise ValueError("Unsupported currency minor-unit scale")
        available = v.get("is_in_stock") if woo else v.get("available")
        backorder = bool(v.get("is_on_backorder") or v.get("backorders_allowed")) if woo else False
        stock = "backorder" if backorder else "in_stock" if available is True else "out_of_stock" if available is False else "unknown"
        vid = str(v.get("id", ""))
        if not vid:
            raise ValueError("Missing variant ID")
        variants.append({"id": f"{retailer['id']}:{vid}", "source_id": vid, "title": label, "size_ml": size, "price_minor": minor_price(prices.get("price") if woo else v.get("price"), woo), "currency": currency, "stock": stock, "observed_at": observed})
    if not variants:
        return None
    if len({v['id'] for v in variants}) != len(variants):
        raise ValueError("Duplicate variant IDs")
    notes = extract_notes(description)
    if woo:
        for attr in raw.get("attributes", []):
            layer = {"top notes": "top", "peak notes": "top", "heart notes": "heart", "middle notes": "heart", "average marks": "heart", "base notes": "base", "basic notes": "base"}.get(attr.get("name", "").lower())
            if layer:
                notes[layer] = ", ".join(t.get("name", "") for t in attr.get("terms", []))
    general = re.search(r"(?im)^\s*(?:fragrance notes|notes)\s*:\s*(.+)$", description)
    brand = str(raw.get("vendor", "")) if not woo else next((", ".join(t.get("name", "") for t in a.get("terms", [])) for a in raw.get("attributes", []) if a.get("name", "").lower() == "brand"), "")
    url = raw.get("permalink") if woo else f"{retailer['origin']}/products/{raw.get('handle', '')}"
    if not woo and not raw.get('handle'):
        raise ValueError('Missing product handle')
    safe_url(url, retailer)
    fragrance = identity(name, brand, retailer)
    if fragrance['brand'] and fragrance['concentration']:
        key = "|".join(normalize(fragrance[k]) for k in ('brand', 'name', 'concentration'))
        fragrance_id = "fragrance:" + hashlib.sha256(key.encode()).hexdigest()[:24]
    else:
        fragrance_id = f"listing:{retailer['id']}:{source_id}"
    return apply_reviewed_identity({"id": f"{retailer['id']}:{source_id}", "source_id": source_id, "retailer_id": retailer['id'], "name": name, "url": url, "fragrance_id": fragrance_id, "fragrance": fragrance, "inspired_by": extract_inspired_by(raw, description), "top": notes.get('top', ''), "heart": notes.get('heart', notes.get('middle', '')), "base": notes.get('base', ''), "unlayered": general[1].strip() if general else "", "note_evidence": {"url": url, "retailer_id": retailer['id']}, "decant_evidence": f"Reviewed sample catalog: {reviewed}" if reviewed else "Explicit sample/decant/vial wording in listing", "variants": sorted(variants, key=lambda v: (v['size_ml'], v['id'])), "observed_at": observed})


def merge_snapshot(retailer, products, previous=None, observed=None, uncertain_ids=None):
    uncertain_ids = set(uncertain_ids or [])
    observed = observed or now_iso()
    old = {p['id']: p for p in (previous or {}).get('products', [])}
    old_active = [p for p in old.values() if p.get('listing_state') != 'no_longer_listed']
    retained_incomplete = sum(p["source_id"] in uncertain_ids for p in old_active)
    if previous and (not products and not retained_incomplete and old_active or len(products) + retained_incomplete < len(old_active) * .5):
        raise ValueError("Catalog count collapse quarantined; retained last valid snapshot")
    baseline = not (previous or {}).get("products")
    merged = []
    for product in products:
        former = old.pop(product['id'], None)
        product = {**product, "listing_state": "listed", "first_seen_at": former.get('first_seen_at', observed) if former else observed, "initial_import": former.get('initial_import', False) if former else baseline}
        merged.append(product)
    for product in old.values():
        if product["source_id"] in uncertain_ids:
            merged.append({**product, "listing_state": "listed", "variants": [{**v, "stock": "unknown"} for v in product["variants"]], "validation_notice": "Present source listing has incomplete metadata; previous selection retained for review."})
        else:
            merged.append({**product, "listing_state": "no_longer_listed", "variants": [{**v, "stock": "no_longer_listed"} for v in product['variants']]})
    return {"schema_version": SCHEMA, "retailer_id": retailer['id'], "generated_at": observed, "products": sorted(merged, key=lambda p: p['id'])}


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    temporary.replace(path)


def refresh_one(retailer, output):
    path = output / f"{retailer['id']}.json"
    previous = json.loads(path.read_text()) if path.exists() else None
    report = {"retailer_id": retailer['id'], "name": retailer['name'], "status": "link_only", "reason": retailer.get('fallback_reason'), "last_success_at": (previous or {}).get('generated_at'), "catalog_path": f"catalogs/{retailer['id']}.json" if previous else None}
    if retailer['adapter'] == 'none':
        return report
    try:
        observed = now_iso()
        if retailer['adapter'] == 'shopify':
            verify_shopify_currency(retailer)
        raw = fetch_shopify(retailer) if retailer['adapter'] == 'shopify' else fetch_woocommerce(retailer)
        reviewed = retailer['decant_rule'].get('reviewed_catalog')
        verified_ids = set()
        if reviewed:
            if reviewed.get('collection'):
                verified_ids = {str(p['id']) for p in fetch_shopify(retailer, collection=reviewed['collection'])}
            else:
                page, _ = request_json(reviewed['evidence_url'], retailer, decode_json=False)
                if not re.search(reviewed['declaration_pattern'], html_to_text(page), re.I):
                    raise ValueError('Reviewed sample catalog declaration changed; evidence review required')
                verified_ids = {str(p['id']) for p in raw}
        products, exclusions, uncertain_ids = [], 0, set()
        for record in raw:
            if not html_to_text(record.get('name' if retailer['adapter'] == 'woocommerce' else 'title', '') or ''):
                uncertain_ids.add(str(record['id']))
                exclusions += 1
                continue
            if str(record['id']) in verified_ids:
                record['verified_sample_catalog'] = reviewed['evidence_url']
            product = normalize_product(record, retailer, observed)
            if product:
                products.append(product)
            else:
                exclusions += 1
        variant_ids = [v['id'] for p in products for v in p['variants']]
        if len(variant_ids) != len(set(variant_ids)):
            raise ValueError('Variant IDs collide across product listings')
        snapshot = merge_snapshot(retailer, products, previous, observed, uncertain_ids)
        atomic_json(path, snapshot)
        report.update(status='searchable' if products else 'empty', reason=None if products else 'No verified sample/decant offers in the public catalog.', last_success_at=observed, catalog_path=f'catalogs/{retailer["id"]}.json', raw_count=len(raw), offer_count=len(products), excluded_count=exclusions, incomplete_record_count=len(uncertain_ids))
    except Exception as exc:
        report.update(status='retained' if previous else 'unavailable', reason=str(exc), offer_count=len([p for p in (previous or {}).get('products', []) if p.get('listing_state') != 'no_longer_listed']))
    print(f"{report['name']}: {report['status']} — {report.get('offer_count', 0)} offers {report.get('reason') or ''}", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retailer', action='append', help='Refresh specified retailer IDs only')
    parser.add_argument('--output', type=Path, default=ROOT / 'catalogs')
    args = parser.parse_args()
    retailers = json.loads((ROOT / 'retailers.json').read_text())['retailers']
    existing = {}
    manifest_path = args.output / 'manifest.json'
    if manifest_path.exists():
        existing = {r['retailer_id']: r for r in json.loads(manifest_path.read_text())['retailers']}
    selected = [r for r in retailers if not args.retailer or r['id'] in args.retailer]
    if args.retailer and set(args.retailer) - {r['id'] for r in selected}:
        parser.error('Unknown retailer ID')
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda r: refresh_one(r, args.output), selected))
    existing.update({r['retailer_id']: r for r in results})
    for retailer in retailers:
        existing.setdefault(retailer['id'], {'retailer_id': retailer['id'], 'name': retailer['name'], 'status': 'link_only', 'reason': retailer.get('fallback_reason') or 'Catalog not refreshed yet.', 'last_success_at': None, 'catalog_path': None})
    report = {'schema_version': SCHEMA, 'generated_at': now_iso(), 'elapsed_seconds': round(time.monotonic() - started, 2), 'retailers': [existing[r['id']] for r in retailers]}
    atomic_json(manifest_path, report)
    atomic_json(args.output / 'refresh-report.json', report)
    summary = '\n'.join(f"- {r['name']}: {r['status']} ({r.get('offer_count', 0)} offers) {r.get('reason') or ''}" for r in report['retailers'])
    import os
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(f"## Catalog refresh\n\nElapsed: {report['elapsed_seconds']} seconds\n\n{summary}\n")


if __name__ == '__main__':
    main()
