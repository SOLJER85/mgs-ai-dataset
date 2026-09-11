import importlib.util
import gzip
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "generate_ai_dataset.py"
SPEC = importlib.util.spec_from_file_location("generate_ai_dataset", MODULE_PATH)
generator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(generator)


def product_fixture(title="Shaving Gel", product_type="Shaving Cream, Gels & Soaps", category=None):
    return {
        "id": "gid://shopify/Product/100",
        "title": title,
        "handle": "shaving-gel",
        "status": "ACTIVE",
        "vendor": "Test Brand",
        "productType": product_type,
        "category": category,
        "onlineStoreUrl": "https://www.malegroomingsupplies.com/products/shaving-gel",
        "description": "A test product.",
        "descriptionHtml": "",
        "seo": {},
        "featuredMedia": {"preview": {"image": {"url": "https://cdn.example/product.jpg"}}},
        "images": {"nodes": [{"url": "https://cdn.example/product.jpg"}]},
        "collections": {"nodes": [{"title": "Shaving Cream, Gels & Soaps"}]},
        "variants": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []},
    }


def variant_fixture(variant_id="200", price="12.50", available=True):
    return {
        "id": f"gid://shopify/ProductVariant/{variant_id}",
        "title": "Default Title",
        "sku": "TEST-SKU",
        "barcode": "09506000134352",
        "price": price,
        "compareAtPrice": None,
        "inventoryQuantity": 5 if available else 0,
        "availableForSale": available,
        "inventoryPolicy": "DENY",
        "selectedOptions": [{"name": "Title", "value": "Default Title"}],
        "image": None,
    }


class GtinTests(unittest.TestCase):
    def test_requires_valid_length_and_check_digit(self):
        self.assertTrue(generator.is_valid_gtin("09506000134352"))
        self.assertFalse(generator.is_valid_gtin("09506000134353"))
        self.assertFalse(generator.is_valid_gtin("123456789"))
        self.assertEqual(generator.gtin_or_blank("0950-6000-1343-52"), "09506000134352")
        self.assertEqual(generator.gtin_or_blank("09506000134353"), "")


class CategoryTests(unittest.TestCase):
    def test_shopify_taxonomy_takes_precedence(self):
        product = product_fixture(category={"fullName": "Health & Beauty > Personal Care > Custom"})
        self.assertEqual(
            generator.product_category(product),
            "Health & Beauty > Personal Care > Custom",
        )

    def test_shaving_gel_and_soap_do_not_fall_into_hair_or_bath(self):
        gel = product_fixture(title="Cooling Shaving Gel")
        soap = product_fixture(title="Traditional Shaving Soap", product_type="Shaving Soap")
        self.assertEqual(
            generator.product_category(gel),
            "Health & Beauty > Personal Care > Shaving & Grooming",
        )
        self.assertEqual(
            generator.product_category(soap),
            "Health & Beauty > Personal Care > Shaving & Grooming",
        )

    def test_uncategorized_taxonomy_uses_reviewed_fallback(self):
        product = product_fixture(
            title="Straight Razor Case",
            product_type="Shaving Accessories & Cases",
            category={"fullName": "Uncategorized"},
        )
        self.assertEqual(
            generator.product_category(product),
            "Health & Beauty > Personal Care > Shaving & Grooming",
        )


class MarketConfigTests(unittest.TestCase):
    def test_defaults_to_no_unconfirmed_market_claims(self):
        with (
            patch.object(generator, "OPENAI_TARGET_COUNTRIES", []),
            patch.object(generator, "OPENAI_STORE_COUNTRY", ""),
            patch.object(generator, "OPENAI_MARKET_SETUP_CONFIRMED", False),
        ):
            self.assertEqual(generator.openai_market_config(), ([], ""))

    def test_market_values_require_explicit_confirmation(self):
        with (
            patch.object(generator, "OPENAI_TARGET_COUNTRIES", ["US"]),
            patch.object(generator, "OPENAI_STORE_COUNTRY", "GB"),
            patch.object(generator, "OPENAI_MARKET_SETUP_CONFIRMED", False),
        ):
            with self.assertRaisesRegex(ValueError, "OPENAI_MARKET_SETUP_CONFIRMED"):
                generator.openai_market_config()

    def test_rejects_target_country_outside_shared_stable_format(self):
        with (
            patch.object(generator, "OPENAI_TARGET_COUNTRIES", ["GB"]),
            patch.object(generator, "OPENAI_STORE_COUNTRY", "GB"),
            patch.object(generator, "OPENAI_MARKET_SETUP_CONFIRMED", True),
        ):
            with self.assertRaisesRegex(ValueError, "Unsupported OpenAI target countries: GB"):
                generator.openai_market_config()


class FeedRowTests(unittest.TestCase):
    def setUp(self):
        self.product = product_fixture()
        self.variant = variant_fixture()
        self.product["variants"]["nodes"] = [self.variant]

    def test_openai_row_uses_stable_offer_and_conservative_optional_flags(self):
        with patch.object(generator, "OPENAI_CHECKOUT_ENABLED", False):
            row = generator.openai_row(self.product, self.variant, "GBP", [], "")
        self.assertEqual(row["offer_id"], "mgs-200")
        self.assertNotIn(row["price"], row["offer_id"])
        self.assertEqual(row["is_eligible_checkout"], "false")
        self.assertEqual(row["accepts_returns"], "")
        self.assertEqual(row["return_deadline_in_days"], "")
        self.assertEqual(row["accepts_exchanges"], "")
        self.assertEqual(row["target_countries"], "")
        self.assertEqual(row["store_country"], "")
        self.assertEqual(row["is_digital"], "")
        self.assertEqual(row["seller_privacy_policy"], "")
        self.assertEqual(row["seller_tos"], "")

    def test_jsonl_uses_native_types_and_omits_empty_optionals(self):
        with patch.object(generator, "OPENAI_CHECKOUT_ENABLED", False):
            row = generator.openai_row(self.product, self.variant, "GBP", ["US", "CA"], "GB")
        output = generator.openai_jsonl_row(row)
        self.assertIs(output["is_eligible_search"], True)
        self.assertIs(output["is_eligible_checkout"], False)
        self.assertEqual(output["target_countries"], ["US", "CA"])
        self.assertNotIn("accepts_returns", output)
        self.assertNotIn("return_deadline_in_days", output)
        json.dumps(output)

    def test_validator_accepts_a_generated_discovery_row(self):
        with patch.object(generator, "OPENAI_CHECKOUT_ENABLED", False):
            row = generator.openai_row(self.product, self.variant, "GBP", [], "")
            validation = generator.validate_openai_rows([row])
        self.assertEqual(generator.validation_errors(validation), [])

    def test_validator_rejects_duplicate_offer_ids(self):
        with patch.object(generator, "OPENAI_CHECKOUT_ENABLED", False):
            first = generator.openai_row(self.product, self.variant, "GBP", [], "")
        second = dict(first, item_id="201")
        validation = generator.validate_openai_rows([first, second])
        self.assertEqual(validation["duplicate_offer_id_count"], 1)
        self.assertIn("duplicate_offer_id_count: 1", generator.validation_errors(validation))

    def test_validator_rejects_empty_feed(self):
        self.assertIn("row_count: 0", generator.validation_errors(generator.validate_openai_rows([])))

    def test_social_feed_uses_current_sale_price(self):
        self.variant["compareAtPrice"] = "20.00"
        self.assertEqual(generator.social_row(self.product, self.variant, "GBP")["price"], "12.50 GBP")

    def test_validator_rejects_invalid_price_url_and_availability(self):
        row = generator.openai_row(self.product, self.variant, "GBP", [], "")
        for field, value in (("price", "-1 GBP"), ("url", "/relative"), ("availability", "available")):
            with self.subTest(field=field):
                self.assertTrue(generator.validation_errors(generator.validate_openai_rows([dict(row, **{field: value})])))

    def test_validator_rejects_duplicate_variant_selection(self):
        first = generator.openai_row(self.product, self.variant, "GBP", [], "")
        first.update(listing_has_variations="true", variant_dict='{"Size":"Small"}')
        second = dict(first, item_id="201", offer_id="mgs-201")
        errors = generator.validation_errors(generator.validate_openai_rows([first, second]))
        self.assertTrue(any("duplicate variant selections" in error for error in errors))

    def test_validator_rejects_unconfirmed_market_claim(self):
        row = generator.openai_row(self.product, self.variant, "GBP", ["US"], "GB")
        with patch.object(generator, "OPENAI_MARKET_SETUP_CONFIRMED", False):
            errors = generator.validation_errors(generator.validate_openai_rows([row]))
        self.assertTrue(any("unconfirmed market claims" in error for error in errors))

    def test_unavailable_continue_variant_does_not_claim_dated_backorder(self):
        variant = variant_fixture(available=False)
        variant["inventoryPolicy"] = "CONTINUE"
        self.assertEqual(generator.variant_availability(variant), ("unknown", "available for order"))


class VariantPaginationTests(unittest.TestCase):
    def test_fetches_all_remaining_variant_pages(self):
        product = product_fixture()
        product["variants"] = {
            "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
            "nodes": [{"id": "gid://shopify/ProductVariant/1"}],
        }
        response = {
            "product": {
                "variants": {
                    "pageInfo": {"hasNextPage": False, "endCursor": "cursor-2"},
                    "nodes": [{"id": "gid://shopify/ProductVariant/2"}],
                }
            }
        }
        with patch.object(generator, "shopify_graphql", return_value=response) as graphql:
            generator.fetch_remaining_variants(product)
        self.assertEqual([node["id"] for node in product["variants"]["nodes"]], [
            "gid://shopify/ProductVariant/1",
            "gid://shopify/ProductVariant/2",
        ])
        graphql.assert_called_once()


class OutputSafetyTests(unittest.TestCase):
    def test_same_day_replay_is_byte_identical(self):
        product = product_fixture()
        product["variants"]["nodes"] = [variant_fixture()]
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                with patch.object(generator, "fetch_products", return_value=([product], "GBP")), patch.object(generator, "openai_market_config", return_value=([], "")), patch("builtins.print"):
                    generator.main()
                    first = {path.name: path.read_bytes() for path in Path(directory).iterdir()}
                    generator.main()
                    second = {path.name: path.read_bytes() for path in Path(directory).iterdir()}
                self.assertEqual(first, second)
            finally:
                os.chdir(original_cwd)

    def test_gzip_output_is_deterministic(self):
        rows = [{"item_id": "1", "title": "Test"}]
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.csv.gz"
            second = Path(directory) / "second.csv.gz"
            generator.write_gzip_csv(first, ["item_id", "title"], rows)
            generator.write_gzip_csv(second, ["item_id", "title"], rows)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(gzip.open(first, "rt").read(), "item_id,title\n1,Test\n")

    def test_invalid_feed_does_not_overwrite_existing_outputs(self):
        product = product_fixture()
        variant = variant_fixture()
        product["variants"]["nodes"] = [variant]
        product["featuredMedia"] = None
        product["images"] = {"nodes": []}
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "ai-dataset.json"
            output.write_text("sentinel\n")
            try:
                os.chdir(directory)
                with (
                    patch.object(generator, "fetch_products", return_value=([product], "GBP")),
                    patch.object(generator, "openai_market_config", return_value=([], "")),
                ):
                    with self.assertRaisesRegex(RuntimeError, "missing required image_url"):
                        generator.main()
            finally:
                os.chdir(original_cwd)
            self.assertEqual(output.read_text(), "sentinel\n")


if __name__ == "__main__":
    unittest.main()
