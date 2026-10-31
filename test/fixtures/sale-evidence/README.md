# Bounded sale-classification regression snapshots

Read-only snapshots acquired 2026-10-31 UTC. Tests do not fetch the network.

- coffee-history.json: public tracker data/263/2631238.json (Coffee Tables), 160 observations, all 500 JPY. Historical flags intentionally include the known embedded-OFF false positives. Never treat those fixture flags as ground truth; test verifies old evidence is not rewritten.
- neil-history.json: public tracker data/178/1780665.json, nine historical variation buckets including two discontinued names. Raw flags retained unchanged; official current scope is tested separately.
- neil-official.json: current seven variation IDs and prices observed from https://booth.pm/ja/items/1780665 on 2026-10-31T00:58:28Z. Official description specifies 5000 to 2500 JPY from Oct10 through Nov10; 6000 donation variations and 0 JPY terms are not that price promotion.

Source repository: https://github.com/MametaroGG/booth-vrc-price-tracker

These files are test fixtures, not collection output or migration input. The classifier's false value means no supported evidence, not a universal claim that the seller is not running a promotion. Tests explicitly document remaining old-high/stale-title and future-date legacy-drop limitations.
