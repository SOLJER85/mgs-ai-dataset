# MGS AI Dataset

Public product data for Male Grooming Supplies, generated from live Shopify data.

## Agent Discovery

For real-time shopping, agents should use the live Shopify storefront first:

- Storefront: https://www.malegroomingsupplies.com
- Agent instructions: https://www.malegroomingsupplies.com/agents.md
- UCP discovery: https://www.malegroomingsupplies.com/.well-known/ucp

The files in this repository are public structured feeds for catalogue discovery,
offline analysis, eligibility checks, GTIN/image/category review, and fallback
product data. Shopify UCP, product pages and checkout remain the final authority
for live price, stock, shipping, tax, hazardous goods restrictions and payment.
Publishing a feed in GitHub does not register it with OpenAI or enable checkout.

The [11 September 2026 offer-ID transition](docs/offer-id-transition-20260911.md)
preserves item IDs and supplies a complete old-to-new offer mapping for consumers.

## Files

- `ai-dataset.json` keeps the original public dataset URL stable and adds richer product, variant, availability, GTIN, return-policy, market-country, and category data.
- `openai-products-feed.csv.gz` is a compressed CSV aligned to OpenAI/Agentic Commerce product-feed fields.
- `openai-products-feed.jsonl.gz` contains the same OpenAI feed rows as JSONL.
- `shopping-feed-google-compatible.tsv` is a Google/Microsoft-friendly product feed with standard shopping attributes.
- `social-catalog-feed.csv` is a social catalog feed for systems that expect `id`, `title`, `description`, `availability`, `condition`, `price`, `link`, `image_link`, and `brand`.
- `ai-dataset-summary.json` records validation counts, skipped products, category counts, and feed freshness.

## Public URLs

- https://raw.githubusercontent.com/SOLJER85/mgs-ai-dataset/main/ai-dataset.json
- https://raw.githubusercontent.com/SOLJER85/mgs-ai-dataset/main/openai-products-feed.csv.gz
- https://raw.githubusercontent.com/SOLJER85/mgs-ai-dataset/main/openai-products-feed.jsonl.gz
- https://raw.githubusercontent.com/SOLJER85/mgs-ai-dataset/main/shopping-feed-google-compatible.tsv
- https://raw.githubusercontent.com/SOLJER85/mgs-ai-dataset/main/social-catalog-feed.csv

The GitHub Action refreshes the files every day from active Shopify products that have an Online Store URL. It does not edit Shopify product data.

OpenAI checkout eligibility is disabled by default. Market fields are empty by
default because they require confirmed OpenAI onboarding. Only set
`OPENAI_CHECKOUT_ENABLED=true`, or the `OPENAI_MARKET_SETUP_CONFIRMED=true`,
`OPENAI_TARGET_COUNTRIES`, and `OPENAI_STORE_COUNTRY` combination, after OpenAI
has enabled that exact integration and market scope. The shared Stable format
currently supports `US`, `CA`, and `MX` as configured target-country values.
