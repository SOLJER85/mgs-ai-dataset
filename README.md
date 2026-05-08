# MGS AI Dataset

Public product data for Male Grooming Supplies, generated from live Shopify data.

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
