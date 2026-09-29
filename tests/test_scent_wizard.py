import csv
import tempfile
import unittest
from pathlib import Path

from decantified_scent_wizard import (
    Selection,
    apply_cart_exclusions,
    apply_cart_exact_exclusions,
    apply_cart_price_limit,
    build_note_bank,
    build_cart_url,
    choose_cart,
    choose_exclusion_terms,
    choose_notes,
    eau_fraiche_similarity,
    filter_products,
    parse_product,
    split_note_terms,
    write_csv,
)


def raw_product(
    title="Night Smoke by Example",
    vendor="Inspiration: Tobacco Vanille Tom Ford",
    description=(
        "<p>A bold masculine fragrance.</p>"
        "<p>Top Notes: Bergamot, Black Pepper</p>"
        "<p>Heart (Middle) Notes: Tobacco and Honey</p>"
        "<p>Base Notes: Vanilla, Cedarwood</p>"
    ),
    available=True,
):
    return {
        "title": title,
        "handle": "night-smoke-example",
        "vendor": vendor,
        "body_html": description,
        "tags": ["Sample Product"],
        "variants": [
            {"id": 101, "title": "1ml", "price": "2.50", "available": available},
            {"id": 102, "title": "5ml", "price": "8.50", "available": False},
        ],
    }


class WizardTests(unittest.TestCase):
    def test_parses_notes_inspiration_stock_and_gender(self):
        product = parse_product(raw_product())
        self.assertEqual(product.inspired_by, "Tobacco Vanille Tom Ford")
        self.assertEqual(product.top, "Bergamot, Black Pepper")
        self.assertEqual(product.heart, "Tobacco and Honey")
        self.assertEqual(product.base, "Vanilla, Cedarwood")
        self.assertEqual(product.gender, "men")
        self.assertEqual(product.in_stock_sizes, "1ml ($2.50)")
        self.assertEqual(product.lowest_in_stock_price, "2.50")

    def test_note_bank_uses_all_products_and_normalizes_terms(self):
        first = parse_product(raw_product())
        second = parse_product(raw_product(
            title="Masculine Woods",
            description=(
                "<p>A masculine fragrance.</p>"
                "<p>Top: bergamot and Lemon</p>"
                "<p>Middle: Iris</p><p>Base: Cedar</p>"
            ),
        ))
        bank = build_note_bank([first, second])
        self.assertIn(("bergamot", 2), bank["top"])
        self.assertIn(("lemon", 1), bank["top"])
        self.assertIn(("tobacco", 1), bank["heart"])
        self.assertIn(("bergamot", 2), bank["all"])
        self.assertIn(("tobacco", 1), bank["all"])

    def test_split_note_terms(self):
        self.assertEqual(
            split_note_terms("Saffron, Nutmeg and Orange."),
            ["saffron", "nutmeg", "orange"],
        )

    def test_match_all_checks_name_inspiration_and_selected_layer(self):
        product = parse_product(raw_product())
        rows = filter_products(
            [product],
            [Selection("heart", "tobacco"), Selection("base", "vanilla")],
            "all",
            100,
        )
        self.assertEqual(len(rows), 1)
        self.assertIn("heart:tobacco -> inspired_by, heart", rows[0]["matched_fields"])
        self.assertIn("base:vanilla -> base", rows[0]["matched_fields"])

    def test_all_layer_selection_checks_every_note_layer(self):
        product = parse_product(raw_product())
        for term, expected_field in (
            ("bergamot", "top"), ("tobacco", "heart"), ("vanilla", "base")
        ):
            rows = filter_products(
                [product], [Selection("all", term)], "any", 100
            )
            self.assertEqual(len(rows), 1)
            self.assertIn(expected_field, rows[0]["matched_fields"])

    def test_strict_gender_and_stock_filter(self):
        eligible = parse_product(raw_product())
        feminine = parse_product(raw_product(
            title="For Her",
            description="<p>A feminine fragrance.</p><p>Top: Tobacco</p><p>Base: Musk</p>",
        ))
        unknown = parse_product(raw_product(
            title="Unknown",
            description="<p>Top: Tobacco</p><p>Base: Musk</p>",
        ))
        sold_out = parse_product(raw_product(available=False))
        rows = filter_products(
            [eligible, feminine, unknown, sold_out], [Selection("heart", "tobacco")], "any", 100
        )
        self.assertEqual([row["product_name"] for row in rows], [eligible.name])

    def test_feminine_language_vetoes_unisex_feeling_claim(self):
        conflicted = parse_product(raw_product(
            title="Conflicted Scent",
            description=(
                "<p>A feminine yet unisex-feeling fragrance.</p>"
                "<p>Top: Tobacco</p><p>Heart: Honey</p><p>Base: Vanilla</p>"
            ),
        ))
        self.assertEqual(conflicted.gender, "women")
        self.assertIn("overrides", conflicted.gender_evidence)
        rows = filter_products(
            [conflicted], [Selection("top", "tobacco")], "any", 100
        )
        self.assertEqual(rows, [])

    def test_unisex_without_feminine_language_remains_eligible(self):
        product = parse_product(raw_product(
            description=(
                "<p>A refined unisex fragrance for both men and women.</p>"
                "<p>Top: Tobacco</p><p>Heart: Honey</p><p>Base: Vanilla</p>"
            ),
        ))
        self.assertEqual(product.gender, "unisex")
        self.assertEqual(
            len(filter_products([product], [Selection("top", "tobacco")], "any", 100)),
            1,
        )

        reversed_wording = parse_product(raw_product(
            description=(
                "<p>A fragrance for women and men.</p>"
                "<p>Top: Tobacco</p><p>Heart: Honey</p><p>Base: Vanilla</p>"
            ),
        ))
        self.assertEqual(reversed_wording.gender, "unisex")
        self.assertEqual(
            len(filter_products(
                [reversed_wording], [Selection("top", "tobacco")], "any", 100
            )),
            1,
        )

    def test_eau_fraiche_threshold_removes_close_profile(self):
        close = parse_product(raw_product(
            title="Fresh Man by Example",
            vendor="Original Composition",
            description=(
                "<p>A masculine fragrance.</p>"
                "<p>Top: Lemon, Bergamot, Star Fruit, Cardamom</p>"
                "<p>Heart: Cedarwood, Tarragon, Sage, Pepper</p>"
                "<p>Base: Musk, Amber, Sycamore Wood</p>"
            ),
        ))
        score, traits = eau_fraiche_similarity(close)
        self.assertGreater(score, 25)
        self.assertIn("top: carambola", traits)
        rows = filter_products([close], [Selection("top", "lemon")], "all", 25)
        self.assertEqual(rows, [])

    def test_direct_eau_fraiche_reference_is_100_percent(self):
        product = parse_product(raw_product(vendor="Inspired by: Versace Man Eau Fraiche"))
        self.assertEqual(eau_fraiche_similarity(product)[0], 100)

    def test_empty_result_still_writes_csv_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.csv"
            write_csv([], path)
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[0][0], "product_name")
            self.assertEqual(len(rows), 1)

    def test_cart_defaults_to_smallest_sample_and_supports_size_choice(self):
        raw = raw_product()
        raw["variants"] = [
            {"id": 103, "title": "Full Bottle (100ml)", "price": "90.00", "available": True},
            {"id": 102, "title": "5ml", "price": "8.50", "available": True},
            {"id": 101, "title": "1ml", "price": "2.50", "available": True},
        ]
        product = parse_product(raw)
        rows = filter_products(
            [product], [Selection("heart", "tobacco")], "all", 100
        )
        answers = iter(["1", ""])
        cart_url = choose_cart(rows, {product.url: product}, lambda _prompt: next(answers))
        self.assertEqual(
            cart_url, "https://decantified.com/cart/101:1?storefront=true"
        )
        self.assertEqual(rows[0]["cart_selection"], "1ml ($2.50)")
        self.assertEqual(rows[0]["cart_url"], cart_url)

        rows = filter_products(
            [product], [Selection("heart", "tobacco")], "all", 100
        )
        answers = iter(["all", "2"])
        cart_url = choose_cart(rows, {product.url: product}, lambda _prompt: next(answers))
        self.assertEqual(
            cart_url, "https://decantified.com/cart/102:1?storefront=true"
        )

    def test_cart_can_be_skipped(self):
        product = parse_product(raw_product())
        rows = filter_products(
            [product], [Selection("heart", "tobacco")], "all", 100
        )
        self.assertIsNone(choose_cart(rows, {product.url: product}, lambda _prompt: "skip"))

    def test_cart_defaults_to_all_results(self):
        product = parse_product(raw_product())
        rows = filter_products(
            [product], [Selection("heart", "tobacco")], "all", 100
        )
        answers = iter(["", ""])
        cart_url = choose_cart(
            rows, {product.url: product}, lambda _prompt: next(answers)
        )
        self.assertEqual(cart_url, "https://decantified.com/cart/101:1?storefront=true")

    def test_one_batch_size_applies_with_smallest_fallback(self):
        first_raw = raw_product(title="Has Five ML")
        first_raw["handle"] = "has-five-ml"
        first_raw["variants"] = [
            {"id": 101, "title": "1ml", "price": "2.50", "available": True},
            {"id": 105, "title": "5ml", "price": "8.50", "available": True},
        ]
        second_raw = raw_product(title="Only One ML")
        second_raw["handle"] = "only-one-ml"
        second_raw["variants"] = [
            {"id": 201, "title": "1ml", "price": "2.75", "available": True},
        ]
        products = [parse_product(first_raw), parse_product(second_raw)]
        rows = filter_products(
            products, [Selection("heart", "tobacco")], "all", 100
        )
        answers = iter(["", "2"])
        cart_url = choose_cart(
            rows, {product.url: product for product in products},
            lambda _prompt: next(answers),
        )
        self.assertEqual(
            cart_url, "https://decantified.com/cart/105:1,201:1?storefront=true"
        )
        self.assertEqual(rows[0]["cart_selection"], "5ml ($8.50)")
        self.assertEqual(rows[1]["cart_selection"], "1ml ($2.75)")

    def test_multiple_item_cart_and_partially_selected_csv(self):
        first_raw = raw_product(title="Alpha Smoke")
        first_raw["handle"] = "alpha-smoke"
        second_raw = raw_product(title="Beta Smoke")
        second_raw["handle"] = "beta-smoke"
        second_raw["variants"][0]["id"] = 201
        first = parse_product(first_raw)
        second = parse_product(second_raw)
        rows = filter_products(
            [first, second], [Selection("heart", "tobacco")], "all", 100
        )
        answers = iter(["all", "", ""])
        cart_url = choose_cart(
            rows, {first.url: first, second.url: second}, lambda _prompt: next(answers)
        )
        self.assertEqual(
            cart_url, "https://decantified.com/cart/101:1,201:1?storefront=true"
        )

        fresh_rows = filter_products(
            [first, second], [Selection("heart", "tobacco")], "all", 100
        )
        answers = iter(["2", ""])
        choose_cart(
            fresh_rows, {first.url: first, second.url: second}, lambda _prompt: next(answers)
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "partial-cart.csv"
            write_csv(fresh_rows, path)
            with path.open(newline="", encoding="utf-8") as handle:
                saved = list(csv.DictReader(handle))
        self.assertEqual(saved[0]["cart_url"], "")
        self.assertTrue(saved[1]["cart_url"].endswith("/201:1?storefront=true"))

    def test_separate_searches_accumulate_in_one_cart(self):
        water_raw = raw_product(title="Water Search Pick")
        water_raw["handle"] = "water-search-pick"
        almond_raw = raw_product(title="Almond Search Pick")
        almond_raw["handle"] = "almond-search-pick"
        almond_raw["variants"][0]["id"] = 201
        oud_raw = raw_product(title="Oud Search Pick")
        oud_raw["handle"] = "oud-search-pick"
        oud_raw["variants"][0]["id"] = 301
        products = [parse_product(item) for item in (water_raw, almond_raw, oud_raw)]
        products_by_url = {product.url: product for product in products}
        cart_items = {}

        expected_ids = [101, 201, 301]
        for product, expected_id in zip(products, expected_ids):
            rows = filter_products(
                [product], [Selection("heart", "tobacco")], "any", 100
            )
            answers = iter(["1", ""])
            choose_cart(
                rows, products_by_url, lambda _prompt: next(answers), cart_items
            )
            self.assertIn(f"{expected_id}:1", build_cart_url(cart_items))

        self.assertEqual(
            build_cart_url(cart_items),
            "https://decantified.com/cart/101:1,201:1,301:1?storefront=true",
        )

    def test_cart_exclusion_checks_name_inspiration_and_all_note_layers(self):
        tobacco = parse_product(raw_product())
        clean_raw = raw_product(
            title="Clean Almond",
            vendor="Original Composition",
            description=(
                "<p>A unisex fragrance.</p><p>Top: Pear</p>"
                "<p>Heart: Almond</p><p>Base: Vanilla</p>"
            ),
        )
        clean_raw["handle"] = "clean-almond"
        clean_raw["variants"][0]["id"] = 201
        clean = parse_product(clean_raw)
        cart_items = {
            tobacco.url: tobacco.available_variants[0],
            clean.url: clean.available_variants[0],
        }
        removed = apply_cart_exclusions(
            cart_items, {tobacco.url: tobacco, clean.url: clean}, ["tobacco"]
        )
        self.assertIn(tobacco.url, removed)
        self.assertIn("inspired_by", removed[tobacco.url]["tobacco"])
        self.assertIn("heart", removed[tobacco.url]["tobacco"])
        self.assertNotIn(tobacco.url, cart_items)
        self.assertIn(clean.url, cart_items)
        self.assertEqual(
            build_cart_url(cart_items),
            "https://decantified.com/cart/201:1?storefront=true",
        )

    def test_exact_exclusion_does_not_remove_longer_note_term(self):
        rose_raw = raw_product(
            title="Exact Rose",
            description=(
                "<p>A masculine fragrance.</p><p>Top: Pear</p>"
                "<p>Heart: Rose</p><p>Base: Musk</p>"
            ),
        )
        rose_raw["handle"] = "exact-rose"
        rose_water_raw = raw_product(
            title="Rose Water Note",
            description=(
                "<p>A masculine fragrance.</p><p>Top: Pear</p>"
                "<p>Heart: Rose Water</p><p>Base: Musk</p>"
            ),
        )
        rose_water_raw["handle"] = "rose-water-note"
        rose_water_raw["variants"][0]["id"] = 201
        rose = parse_product(rose_raw)
        rose_water = parse_product(rose_water_raw)
        products = {rose.url: rose, rose_water.url: rose_water}
        cart_items = {
            rose.url: rose.available_variants[0],
            rose_water.url: rose_water.available_variants[0],
        }
        removed = apply_cart_exact_exclusions(cart_items, products, ["rose"])
        self.assertIn(rose.url, removed)
        self.assertNotIn(rose_water.url, removed)
        self.assertIn(rose_water.url, cart_items)

    def test_exclusion_search_defaults_to_all_matching_terms(self):
        bank = {
            "all": [
                ("oud", 10),
                ("oud wood", 4),
                ("white oud", 3),
                ("vanilla", 20),
            ]
        }
        answers = iter(["", "oud", "", ""])
        exclusions = choose_exclusion_terms(bank, lambda _prompt: next(answers))
        self.assertEqual(exclusions, ["oud", "oud wood", "white oud"])

    def test_inclusion_search_defaults_to_all_matching_terms(self):
        bank = {
            "all": [
                ("water", 10),
                ("watery notes", 4),
                ("water lily", 3),
                ("vanilla", 20),
            ]
        }
        answers = iter(["", "water", "", ""])
        selections = choose_notes(bank, lambda _prompt: next(answers))
        self.assertEqual(
            selections,
            [
                Selection("all", "water"),
                Selection("all", "watery notes"),
                Selection("all", "water lily"),
            ],
        )

    def test_cart_price_limit_keeps_equal_and_removes_greater(self):
        at_limit = parse_product(raw_product(title="At Limit"))
        over_raw = raw_product(title="Over Limit")
        over_raw["handle"] = "over-limit"
        over_raw["variants"][0]["id"] = 201
        over_raw["variants"][0]["price"] = "2.51"
        over_limit = parse_product(over_raw)
        cart_items = {
            at_limit.url: at_limit.available_variants[0],
            over_limit.url: over_limit.available_variants[0],
        }
        removed = apply_cart_price_limit(cart_items, 2.50)
        self.assertIn(at_limit.url, cart_items)
        self.assertNotIn(over_limit.url, cart_items)
        self.assertEqual(removed[over_limit.url].price, "2.51")
        self.assertEqual(
            build_cart_url(cart_items),
            "https://decantified.com/cart/101:1?storefront=true",
        )


if __name__ == "__main__":
    unittest.main()
