# Offer identity transition — 11 September 2026

This release replaces all 1,288 price-bearing `offer_id` values with
`mgs-{Shopify variant ID}`. All 1,288 existing `item_id` values and all parent
`group_id` values remain unchanged. Future price and stock changes will not
change these identifiers.

The mapping is in [offer-id-migration-20260911.csv](offer-id-migration-20260911.csv).
Join by `item_id`, not the old offer ID: the previous snapshot contains a
duplicate old offer ID shared by two distinct items. The mapping describes
the snapshot at commit `65b2cdcb171362425c56bd499233655216a7bc59`; later products
use the same variant-derived rule.

Consumers maintaining offer-keyed state should replace the complete snapshot
or migrate each record using `item_id`, then remove the corresponding old
offer key. Do not append the new offers alongside the old offers. All existing
feed filenames and URLs remain available. The old snapshot remains accessible
through its immutable Git commit for reconciliation.

This public feed has no confirmed OpenAI ingestion or checkout registration.
Publishing this transition does not enable either. Any separately registered
consumer must complete its own import and acknowledge the replacement; no
external consumer's retained state has been modified by this repository.

Other changes remove unconfirmed worldwide market coverage and blanket return
claims, disable OpenAI checkout eligibility, and prefer Shopify product
taxonomy. The current catalogue has 1,000 category corrections. Social CSV
uses the current payable sale price. Shopify products and store settings are
not changed by the generator.

Validation runs before generated files are written. Identical same-day input
produces identical output, and publication aborts if main changes during a
build. Run `python -m unittest discover -s tests -v` to verify the generator.
