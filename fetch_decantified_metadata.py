import csv
import html
import json
import re
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

SOURCE = Path("outputs/eau-fraiche-filtered-20260926/decantified_tobacco_low_eau_fraiche_similarity.csv")
OUTPUT = Path("decantified_product_metadata.json")


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.chunks = []

    def handle_data(self, data):
        self.chunks.append(data)


def clean_description(text):
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def product_description(raw_html):
    parser = TextParser()
    parser.feed(raw_html or "")
    return clean_description(" ".join(parser.chunks))


def classify_gender(product_name, description):
    lower = f"{product_name} {description}".lower()
    unisex_patterns = [r"\bunisex\b", r"\bfor (?:both )?men and women\b", r"\bfor (?:both )?women and men\b"]
    women_patterns = [
        r"\bfor women\b", r"\bwomen'?s fragrance\b", r"\bfragrance for her\b",
        r"\bpour femme\b", r"\bfeminine\b",
    ]
    men_patterns = [
        r"\bfor men\b", r"\bmen'?s fragrance\b", r"\bfragrance for him\b",
        r"\bpour homme\b", r"\bmasculine\b",
    ]
    if any(re.search(pattern, lower) for pattern in unisex_patterns):
        return "unisex", "Explicit unisex wording"
    women = any(re.search(pattern, lower) for pattern in women_patterns)
    men = any(re.search(pattern, lower) for pattern in men_patterns)
    if women and not men:
        return "women", "Explicit women-only wording"
    if men and not women:
        return "men", "Explicit men-only wording"
    if women and men:
        return "unisex", "Both women and men are named"
    return "unspecified", "No explicit gender wording on product page"


with SOURCE.open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle))

metadata = []
for index, row in enumerate(rows, start=1):
    request = urllib.request.Request(
        f"{row['url']}.js",
        headers={"User-Agent": "Mozilla/5.0 (compatible; product-metadata-review/1.0)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            product = json.loads(response.read().decode("utf-8", errors="replace"))
        description = product_description(product.get("description", ""))
        gender, evidence = classify_gender(row["product_name"], description)
        tags = product.get("tags", [])
        vendor = product.get("vendor", "")
        product_type = product.get("type", "")
        status = "ok"
    except Exception as exc:
        description = ""
        gender = "unavailable"
        evidence = f"Page retrieval failed: {type(exc).__name__}"
        tags = []
        vendor = ""
        product_type = ""
        status = "error"
    metadata.append({
        "product_name": row["product_name"],
        "url": row["url"],
        "website_description": description,
        "gender_label": gender,
        "gender_evidence": evidence,
        "website_tags": tags,
        "website_vendor": vendor,
        "website_product_type": product_type,
        "fetch_status": status,
    })
    print(f"{index:02d}/{len(rows)} {status:5s} {gender:11s} {row['product_name']}", flush=True)
    time.sleep(0.15)

OUTPUT.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps({
    "products": len(metadata),
    "women": sum(item["gender_label"] == "women" for item in metadata),
    "men": sum(item["gender_label"] == "men" for item in metadata),
    "unisex": sum(item["gender_label"] == "unisex" for item in metadata),
    "unspecified": sum(item["gender_label"] == "unspecified" for item in metadata),
    "unavailable": sum(item["gender_label"] == "unavailable" for item in metadata),
}, ensure_ascii=False))
