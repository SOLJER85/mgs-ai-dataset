#!/usr/bin/env python3
"""Generate public AI and shopping feeds from Shopify Admin data."""

from __future__ import annotations

import csv
import gzip
import json
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests


STORE_FRONT_URL = os.getenv("STORE_FRONT_URL", "https://www.malegroomingsupplies.com").rstrip("/")
SELLER_NAME = os.getenv("SELLER_NAME", "Male Grooming Supplies")
SELLER_DESCRIPTION = os.getenv(
    "SELLER_DESCRIPTION",
    "UK based retailer specialising in premium shaving and grooming products.",
)
DEFAULT_STORE_COUNTRY = os.getenv("STORE_COUNTRY", "GB")
DEFAULT_TARGET_COUNTRIES = [
    country.strip().upper()
    for country in os.getenv("TARGET_COUNTRIES", "").split(",")
    if country.strip()
]
USE_SHOPIFY_SKU_AS_MPN = os.getenv("USE_SHOPIFY_SKU_AS_MPN", "false").strip().lower() == "true"
CURRENCY_SYMBOLS = {"GBP": "\u00a3", "USD": "$", "EUR": "\u20ac"}
RETURN_POLICY = f"{STORE_FRONT_URL}/policies/refund-policy"
PRIVACY_POLICY = f"{STORE_FRONT_URL}/policies/privacy-policy"
TERMS_URL = f"{STORE_FRONT_URL}/policies/terms-of-service"

OPENAI_FIELDS = [
    "is_eligible_search",
    "is_eligible_checkout",
    "item_id",
    "gtin",
    "mpn",
    "title",
    "description",
    "url",
    "brand",
    "condition",
    "product_category",
    "material",
    "dimensions",
    "weight",
    "item_weight_unit",
    "age_group",
    "image_url",
    "additional_image_urls",
    "price",
    "sale_price",
    "availability",
    "availability_date",
    "group_id",
    "listing_has_variations",
    "variant_dict",
    "item_group_title",
    "color",
    "size",
    "gender",
    "offer_id",
    "shipping",
    "is_digital",
    "seller_name",
    "seller_url",
    "seller_privacy_policy",
    "seller_tos",
    "accepts_returns",
    "return_deadline_in_days",
    "accepts_exchanges",
    "return_policy",
    "target_countries",
    "store_country",
    "related_product_id",
    "relationship_type",
]

GOOGLE_FIELDS = [
    "id",
    "title",
    "description",
    "link",
    "image_link",
    "additional_image_link",
    "availability",
    "price",
    "sale_price",
    "brand",
    "gtin",
    "mpn",
    "condition",
    "google_product_category",
    "product_type",
    "item_group_id",
    "identifier_exists",
    "adult",
    "age_group",
    "gender",
    "custom_label_0",
    "custom_label_1",
]

SOCIAL_FIELDS = [
    "id",
    "title",
    "description",
    "availability",
    "condition",
    "price",
    "link",
    "image_link",
    "additional_image_link",
    "brand",
    "google_product_category",
    "product_type",
    "item_group_id",
    "gtin",
    "mpn",
]


class HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        return " ".join(self.parts)


def shopify_graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    store = os.environ["SHOPIFY_STORE_DOMAIN"]
    token = os.environ["SHOPIFY_ADMIN_TOKEN"]
    api_version = os.getenv("API_VERSION", "2026-04")
    url = f"https://{store}/admin/api/{api_version}/graphql.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    response = requests.post(url, headers=headers, json={"query": query, "variables": variables or {}}, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], indent=2))
    return payload["data"]


def gid_tail(value: str | None) -> str:
    return (value or "").rsplit("/", 1)[-1]


def bool_string(value: bool) -> str:
    return "true" if value else "false"


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    parser = HTMLTextExtractor()
    parser.feed(value)
    text = parser.text()
    text = text.replace("\u00ad", "")
    return re.sub(r"\s+", " ", text).strip()


def clean_text(value: str | None, limit: int) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].strip() or text[:limit].strip()


def gtin_or_blank(value: str | None) -> str:
    digits = re.sub(r"\D+", "", value or "")
    return digits if len(digits) in {8, 12, 13, 14} else ""


def price_string(amount: str | None, currency: str) -> str:
    return f"{amount} {currency}" if amount else ""


def display_price(amount: str | None, currency: str) -> str | None:
    if not amount:
        return None
    return f"{CURRENCY_SYMBOLS.get(currency, currency + ' ')}{amount}"


def variant_title(product_title: str, variant: dict[str, Any]) -> str:
    title = variant.get("title") or ""
    if not title or title == "Default Title":
        return product_title
    return f"{product_title} - {title}"


def variant_options(variant: dict[str, Any]) -> dict[str, str]:
    options: dict[str, str] = {}
    for option in variant.get("selectedOptions") or []:
        name = option.get("name") or ""
        value = option.get("value") or ""
        if not name or not value or (name == "Title" and value == "Default Title"):
            continue
        options[name] = value
    return options


def option_lookup(options: dict[str, str], names: set[str]) -> str:
    for name, value in options.items():
        if name.strip().lower() in names:
            return value
    return ""


def active_market_country_codes() -> list[str]:
    if DEFAULT_TARGET_COUNTRIES:
        countries = DEFAULT_TARGET_COUNTRIES
    else:
        query = """
        query Markets {
          markets(first: 100) {
            nodes {
              status
              regions(first: 250) {
                nodes {
                  ... on MarketRegionCountry { code }
                }
              }
            }
          }
        }
        """
        try:
            data = shopify_graphql(query)
            countries = []
            for market in data.get("markets", {}).get("nodes", []):
                if market.get("status") != "ACTIVE":
                    continue
                for region in market.get("regions", {}).get("nodes", []) or []:
                    code = (region.get("code") or "").upper()
                    if code:
                        countries.append(code)
        except Exception as exc:
            print(f"Warning: could not fetch Shopify Markets, using {DEFAULT_STORE_COUNTRY}: {exc}")
            countries = [DEFAULT_STORE_COUNTRY]

    unique = sorted(set(countries))
    if DEFAULT_STORE_COUNTRY in unique:
        unique.remove(DEFAULT_STORE_COUNTRY)
    return [DEFAULT_STORE_COUNTRY] + unique


def product_category(product: dict[str, Any]) -> str:
    collection_titles = " ".join(collection.get("title") or "" for collection in product["collections"]["nodes"])
    text = " ".join([product.get("productType") or "", product.get("title") or "", collection_titles]).lower()
    if any(word in text for word in ["toothpaste", "mouthwash", "toothbrush", "oral", "dental"]):
        return "Health & Beauty > Personal Care > Oral Care"
    if any(word in text for word in ["hair colour", "hair color", "hair dark", "darkening", "grey hair", "gray hair"]):
        return "Health & Beauty > Personal Care > Hair Care > Hair Color"
    if any(word in text for word in ["fragrance", "eau de parfum", "eau de toilette", "cologne", "perfume"]):
        return "Health & Beauty > Personal Care > Cosmetics > Perfume & Cologne"
    if any(word in text for word in ["beard", "moustache", "mustache"]):
        return "Health & Beauty > Personal Care > Hair Care > Beard & Moustache Care"
    if any(word in text for word in ["pomade", "clay", "wax", "gel", "spray", "tonic", "hair powder", "shampoo", "hair styling"]):
        return "Health & Beauty > Personal Care > Hair Care"
    if any(word in text for word in ["anti ageing", "anti-aging", "anti aging", "wrinkle", "serum", "moisturiser", "moisturizer", "skincare", "skin care", "face", "lip balm"]):
        return "Health & Beauty > Personal Care > Cosmetics > Skin Care"
    if any(word in text for word in ["soap", "bath", "hand wash", "body wash", "deodorant", "talc"]):
        return "Health & Beauty > Personal Care > Bath & Body"
    if any(word in text for word in ["blade", "razor", "shavette", "straight razor"]):
        return "Health & Beauty > Personal Care > Shaving & Grooming > Razors & Razor Blades"
    if any(word in text for word in ["brush", "bowl", "stand", "mug", "strop", "shaving cream", "shaving soap", "post shave", "post-shave", "pre-shave", "pre shave", "alum", "shaving set"]):
        return "Health & Beauty > Personal Care > Shaving & Grooming"
    return "Health & Beauty > Personal Care"


def product_type_path(product: dict[str, Any]) -> str:
    product_type = clean_text(product.get("productType"), 120)
    collections = [clean_text(collection.get("title"), 120) for collection in product["collections"]["nodes"]]
    collections = [title for title in collections if title and title.lower() != "new additions"]
    if product_type and collections:
        return f"{product_type} > {collections[0]}"
    return product_type or (collections[0] if collections else "Grooming Products")


def fetch_products() -> tuple[list[dict[str, Any]], str]:
    query = """
    query Products($cursor: String) {
      shop { currencyCode }
      products(first: 100, after: $cursor, sortKey: TITLE) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          title
          handle
          status
          vendor
          productType
          onlineStoreUrl
          totalInventory
          description
          descriptionHtml
          seo { title description }
          featuredMedia { preview { image { url altText width height } } }
          images(first: 10) { nodes { url altText width height } }
          collections(first: 10) { nodes { title handle } }
          variants(first: 100) {
            nodes {
              id
              title
              sku
              barcode
              price
              compareAtPrice
              inventoryQuantity
              availableForSale
              inventoryPolicy
              selectedOptions { name value }
              image { url altText width height }
            }
          }
        }
      }
    }
    """
    products: list[dict[str, Any]] = []
    cursor = None
    currency = "GBP"
    while True:
        data = shopify_graphql(query, {"cursor": cursor})
        currency = data.get("shop", {}).get("currencyCode") or currency
        connection = data["products"]
        products.extend(connection["nodes"])
        if not connection["pageInfo"]["hasNextPage"]:
            break
        cursor = connection["pageInfo"]["endCursor"]
        time.sleep(0.2)
    return products, currency


def variant_availability(variant: dict[str, Any]) -> tuple[str, str]:
    if variant.get("availableForSale"):
        return "in_stock", "in stock"
    if variant.get("inventoryPolicy") == "CONTINUE":
        return "backorder", "available for order"
    inventory_quantity = variant.get("inventoryQuantity")
    if isinstance(inventory_quantity, int) and inventory_quantity <= 0:
        return "out_of_stock", "out of stock"
    return "unknown", "out of stock"


def image_urls(product: dict[str, Any], variant: dict[str, Any]) -> tuple[str, list[str]]:
    product_image = ((product.get("featuredMedia") or {}).get("preview") or {}).get("image") or {}
    main = (variant.get("image") or product_image or {}).get("url") or ""
    additional = []
    for image in product.get("images", {}).get("nodes", []) or []:
        url = image.get("url")
        if url and url != main:
            additional.append(url)
    return main, additional[:9]


def row_context(product: dict[str, Any], variant: dict[str, Any], currency: str) -> dict[str, Any]:
    product_id = gid_tail(product["id"])
    variant_id = gid_tail(variant["id"])
    options = variant_options(variant)
    title = clean_text(variant_title(product["title"], variant), 150)
    description = clean_text(
        product.get("description")
        or html_to_text(product.get("descriptionHtml"))
        or (product.get("seo") or {}).get("description")
        or title,
        5000,
    )
    url = product.get("onlineStoreUrl") or f"{STORE_FRONT_URL}/products/{product['handle']}"
    if len(product["variants"]["nodes"]) > 1:
        url = f"{url}?{urlencode({'variant': variant_id})}"
    main_image, additional_images = image_urls(product, variant)
    catalog_availability, social_availability = variant_availability(variant)
    price = variant.get("price") or ""
    compare_at = variant.get("compareAtPrice")
    regular_price = price_string(price, currency)
    sale_price = ""
    if compare_at:
        try:
            if float(price) < float(compare_at):
                regular_price = price_string(compare_at, currency)
                sale_price = price_string(price, currency)
        except (TypeError, ValueError):
            pass
    brand = clean_text(product.get("vendor") or SELLER_NAME, 70)
    sku = clean_text(variant.get("sku"), 120)
    mpn = clean_text(sku, 70) if USE_SHOPIFY_SKU_AS_MPN else ""
    gtin = gtin_or_blank(variant.get("barcode"))
    category = product_category(product)
    product_type = product_type_path(product)
    return {
        "product_id": product_id,
        "variant_id": variant_id,
        "title": title,
        "description": description,
        "url": url,
        "main_image": main_image,
        "additional_images": additional_images,
        "availability": catalog_availability,
        "social_availability": social_availability,
        "available_for_sale": bool(variant.get("availableForSale")),
        "price": regular_price,
        "sale_price": sale_price,
        "display_price": display_price(price, currency),
        "brand": brand,
        "mpn": mpn,
        "sku": sku,
        "gtin": gtin,
        "category": category,
        "product_type": product_type,
        "options": options,
        "color": clean_text(option_lookup(options, {"color", "colour"}), 40),
        "size": clean_text(option_lookup(options, {"size", "amount", "volume", "pack size"}), 20),
    }


def openai_row(product: dict[str, Any], variant: dict[str, Any], currency: str, target_countries: list[str]) -> dict[str, str]:
    ctx = row_context(product, variant, currency)
    has_variations = len(product["variants"]["nodes"]) > 1
    return {
        "is_eligible_search": "true",
        "is_eligible_checkout": bool_string(ctx["available_for_sale"]),
        "item_id": ctx["variant_id"],
        "gtin": ctx["gtin"],
        "mpn": ctx["mpn"],
        "title": ctx["title"],
        "description": ctx["description"],
        "url": ctx["url"],
        "brand": ctx["brand"],
        "condition": "new",
        "product_category": ctx["category"],
        "material": "",
        "dimensions": "",
        "weight": "",
        "item_weight_unit": "",
        "age_group": "adult",
        "image_url": ctx["main_image"],
        "additional_image_urls": ",".join(ctx["additional_images"]),
        "price": ctx["price"],
        "sale_price": ctx["sale_price"],
        "availability": ctx["availability"],
        "availability_date": "",
        "group_id": ctx["product_id"],
        "listing_has_variations": bool_string(has_variations),
        "variant_dict": json.dumps(ctx["options"], ensure_ascii=False, sort_keys=True) if ctx["options"] else "",
        "item_group_title": clean_text(product["title"], 150),
        "color": ctx["color"],
        "size": ctx["size"],
        "gender": "male",
        "offer_id": clean_text(f"{ctx['sku'] or ctx['variant_id']}-{ctx['price']}", 120),
        "shipping": "",
        "is_digital": "false",
        "seller_name": SELLER_NAME,
        "seller_url": STORE_FRONT_URL,
        "seller_privacy_policy": PRIVACY_POLICY,
        "seller_tos": TERMS_URL,
        "accepts_returns": "true",
        "return_deadline_in_days": "30",
        "accepts_exchanges": "false",
        "return_policy": RETURN_POLICY,
        "target_countries": ",".join(target_countries),
        "store_country": DEFAULT_STORE_COUNTRY,
        "related_product_id": "",
        "relationship_type": "",
    }


def google_row(product: dict[str, Any], variant: dict[str, Any], currency: str) -> dict[str, str]:
    ctx = row_context(product, variant, currency)
    return {
        "id": ctx["variant_id"],
        "title": ctx["title"],
        "description": ctx["description"],
        "link": ctx["url"],
        "image_link": ctx["main_image"],
        "additional_image_link": ",".join(ctx["additional_images"]),
        "availability": ctx["availability"],
        "price": ctx["price"],
        "sale_price": ctx["sale_price"],
        "brand": ctx["brand"],
        "gtin": ctx["gtin"],
        "mpn": ctx["mpn"],
        "condition": "new",
        "google_product_category": ctx["category"],
        "product_type": ctx["product_type"],
        "item_group_id": ctx["product_id"],
        "identifier_exists": "yes" if ctx["gtin"] or (ctx["mpn"] and ctx["brand"]) else "no",
        "adult": "no",
        "age_group": "adult",
        "gender": "male",
        "custom_label_0": ctx["brand"],
        "custom_label_1": ctx["product_type"],
    }


def social_row(product: dict[str, Any], variant: dict[str, Any], currency: str) -> dict[str, str]:
    ctx = row_context(product, variant, currency)
    return {
        "id": ctx["variant_id"],
        "title": ctx["title"],
        "description": ctx["description"],
        "availability": ctx["social_availability"],
        "condition": "new",
        "price": ctx["price"],
        "link": ctx["url"],
        "image_link": ctx["main_image"],
        "additional_image_link": ",".join(ctx["additional_images"]),
        "brand": ctx["brand"],
        "google_product_category": ctx["category"],
        "product_type": ctx["product_type"],
        "item_group_id": ctx["product_id"],
        "gtin": ctx["gtin"],
        "mpn": ctx["mpn"],
    }


def ai_dataset_product(product: dict[str, Any], currency: str) -> dict[str, Any]:
    variants = []
    first_active_variant = None
    for variant in product["variants"]["nodes"]:
        ctx = row_context(product, variant, currency)
        if first_active_variant is None:
            first_active_variant = ctx
        variants.append(
            {
                "id": ctx["variant_id"],
                "sku": ctx["sku"] or None,
                "gtin": ctx["gtin"] or None,
                "mpn": ctx["mpn"] or None,
                "title": ctx["title"],
                "url": ctx["url"],
                "price": ctx["price"],
                "sale_price": ctx["sale_price"] or None,
                "availability": ctx["availability"],
                "image": ctx["main_image"] or None,
                "options": ctx["options"],
            }
        )
    first = first_active_variant or {}
    collections = [collection.get("title") for collection in product["collections"]["nodes"] if collection.get("title")]
    return {
        "name": product["title"],
        "category": product_type_path(product),
        "product_category": product_category(product),
        "description": first.get("description") or "",
        "url": product.get("onlineStoreUrl") or f"{STORE_FRONT_URL}/products/{product['handle']}",
        "price": first.get("display_price"),
        "brand": first.get("brand") or product.get("vendor") or SELLER_NAME,
        "vendor": product.get("vendor") or None,
        "image": first.get("main_image") or None,
        "availability": first.get("availability") or None,
        "condition": "new",
        "return_policy": RETURN_POLICY,
        "shipping": "Calculated at checkout",
        "product_type": product.get("productType") or None,
        "collections": collections,
        "variants": variants,
    }


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]], delimiter: str = ",") -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


def write_gzip_csv(path: Path, fields: list[str], rows: list[dict[str, str]], delimiter: str = ",") -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


def validate_openai_rows(rows: list[dict[str, str]]) -> dict[str, Any]:
    required = [
        "is_eligible_search",
        "is_eligible_checkout",
        "item_id",
        "title",
        "description",
        "url",
        "brand",
        "image_url",
        "price",
        "availability",
        "seller_name",
        "seller_url",
        "return_policy",
        "target_countries",
        "store_country",
    ]
    missing = {field: sum(1 for row in rows if not row.get(field)) for field in required}
    duplicate_item_ids = [item for item, count in Counter(row["item_id"] for row in rows).items() if count > 1]
    return {
        "row_count": len(rows),
        "required_missing": missing,
        "duplicate_item_id_count": len(duplicate_item_ids),
        "invalid_gtin_rows": sum(1 for row in rows if row.get("gtin") and not re.fullmatch(r"\d{8}|\d{12}|\d{13}|\d{14}", row["gtin"])),
        "overlong_title_rows": sum(1 for row in rows if len(row.get("title", "")) > 150),
        "overlong_description_rows": sum(1 for row in rows if len(row.get("description", "")) > 5000),
        "availability_counts": dict(sorted(Counter(row["availability"] for row in rows).items())),
        "checkout_eligibility_counts": dict(sorted(Counter(row["is_eligible_checkout"] for row in rows).items())),
        "rows_with_gtin": sum(1 for row in rows if row.get("gtin")),
        "rows_with_mpn": sum(1 for row in rows if row.get("mpn")),
        "target_country_count": len((rows[0].get("target_countries") or "").split(",")) if rows else 0,
    }


def main() -> None:
    products, currency = fetch_products()
    target_countries = active_market_country_codes()
    included_products = []
    skipped_products = []
    openai_rows: list[dict[str, str]] = []
    google_rows: list[dict[str, str]] = []
    social_rows: list[dict[str, str]] = []
    category_counts: dict[str, int] = defaultdict(int)

    for product in products:
        if product.get("status") != "ACTIVE" or not product.get("onlineStoreUrl"):
            skipped_products.append(
                {
                    "id": product.get("id") or "",
                    "title": product.get("title") or "",
                    "status": product.get("status") or "",
                    "reason": "not_active_or_no_online_store_url",
                }
            )
            continue
        if not product["variants"]["nodes"]:
            skipped_products.append(
                {
                    "id": product.get("id") or "",
                    "title": product.get("title") or "",
                    "status": product.get("status") or "",
                    "reason": "no_variants",
                }
            )
            continue

        included_products.append(ai_dataset_product(product, currency))
        for variant in product["variants"]["nodes"]:
            openai = openai_row(product, variant, currency, target_countries)
            openai_rows.append(openai)
            google_rows.append(google_row(product, variant, currency))
            social_rows.append(social_row(product, variant, currency))
            category_counts[openai["product_category"]] += 1

    generated_at = datetime.now(timezone.utc)
    payload = [
        {
            "site": STORE_FRONT_URL,
            "brand": SELLER_NAME,
            "last_updated": generated_at.date().isoformat(),
            "generated_at": generated_at.isoformat(timespec="seconds"),
            "schema_version": "2.0",
            "description": SELLER_DESCRIPTION,
            "store_country": DEFAULT_STORE_COUNTRY,
            "target_countries": target_countries,
            "product_count": len(included_products),
            "variant_count": len(openai_rows),
            "products": included_products,
        }
    ]

    Path("ai-dataset.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_csv(Path("openai-products-feed.csv"), OPENAI_FIELDS, openai_rows)
    write_gzip_csv(Path("openai-products-feed.csv.gz"), OPENAI_FIELDS, openai_rows)

    with gzip.open("openai-products-feed.jsonl.gz", "wt", encoding="utf-8") as handle:
        for row in openai_rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    write_csv(Path("shopping-feed-google-compatible.tsv"), GOOGLE_FIELDS, google_rows, delimiter="\t")
    write_gzip_csv(Path("shopping-feed-google-compatible.tsv.gz"), GOOGLE_FIELDS, google_rows, delimiter="\t")
    write_csv(Path("social-catalog-feed.csv"), SOCIAL_FIELDS, social_rows)
    write_gzip_csv(Path("social-catalog-feed.csv.gz"), SOCIAL_FIELDS, social_rows)

    summary = {
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "api_version": os.getenv("API_VERSION", "2026-04"),
        "currency": currency,
        "source_products": len(products),
        "included_products": len(included_products),
        "skipped_products": len(skipped_products),
        "openai_feed": "openai-products-feed.csv.gz",
        "openai_jsonl_feed": "openai-products-feed.jsonl.gz",
        "google_compatible_feed": "shopping-feed-google-compatible.tsv",
        "social_catalog_feed": "social-catalog-feed.csv",
        "validation": validate_openai_rows(openai_rows),
        "category_counts": dict(sorted(category_counts.items())),
        "skipped_sample": skipped_products[:20],
    }
    Path("ai-dataset-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
