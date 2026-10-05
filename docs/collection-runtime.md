# Single-writer collection: coverage, limits and recovery

## Two collection lanes

The collector uses one Actions job, one dynamically refilled pool, and one writer. At most five tasks (including search requests) are active. A slow item no longer holds an entire five-item batch. Every actual HTTP start, including redirects and retries, goes through one 500 ms pacing gate. This initial two-starts-per-second ceiling is conservative; it is not evidence of BOOTH's permitted rate.

- **Filtered discovery** uses the original two VRChat/digital search URLs and their existing sorting, categories and 3,333-page limit. Only this search and pre-existing product files can introduce IDs. Search redirects must preserve the full approved URL's origin, path and query; a redirect that drops filters fails before it is followed. Discovered IDs are written durably before the search cursor advances. Search failures retain that cursor and back off while known-product refresh continues.
- **Known-ID refresh** reads the existing product IDs directly, even if they no longer appear in search. It covers every retained eligible ID, normally oldest successful update first with deterministic ID tie-breaking. Successfully saved items are not re-fetched in the same JST day. Failed/unavailable IDs retain their history, receive a bounded retry date, and move behind untouched old work rather than holding the catalog at one bad item.

A per-run claim set prevents the same ID from being fetched twice when it appears in both lanes or multiple search pages. Discovery also alternates search opportunities with pending new-product details, so a large new-ID backlog does not eliminate future search opportunities.

## Durable catalog migration

`data/crawl_registry/` stores cached, prefix-sharded metadata plus a small shard index. The first run imports numeric IDs from existing `data/<prefix>/<id>.json` files and infers their last success from valid, non-future history dates. Product histories are not rewritten by migration. Later runs list the product filenames but avoid reparsing histories already represented by cached existing-ID records.

Broken individual product JSON remains eligible with unknown last success; its eventual save failure receives backoff. Systemic storage errors stop the collector. Corrupt/missing registry metadata fails closed because rebuilding blindly could forget filtered IDs not saved as products yet.

Legacy `crawl_state.json` page-sized pending IDs are imported into the registry before advancing that page's discovery cursor. New discovery checkpoints retain the original categories/pages, daily completion marker, and search retry state. Once an entire discovery cycle completes, it does not restart again that JST day. New listings appearing afterward normally wait until the next JST day; this trades intraday discovery freshness for fewer repeat searches. A multi-day unfinished search cycle keeps its cursor.

Data is saved before marking a product successful in the registry. An interruption may therefore repeat a read, but cannot advance metadata past product history that was never saved. Metadata writes are atomic and remain single-writer. Never run a historical collector version against this migrated state.

## Time and traffic limits

- Runtime deadline: the earlier of scraper start + 5 hours and job start + 5 hours 30 minutes. Checkout/setup count toward the 6-hour Actions job limit. The next cron time is no longer a deadline. The existing concurrency group serializes runs; the following run checks out the latest saved branch state.
- HTTP timeout/abort: 30 seconds, shortened by the remaining runtime. Network/408/5xx errors get at most three attempts per logical request with exponential backoff. Redirect hops are explicitly counted. Product redirects must retain the requested item ID.
- HTTP 403 and 429 stop new requests globally. 403 pauses at least six hours; 429 respects Retry-After with a 60-second minimum. The absolute stop-until time is persisted and logged. Five consecutive transient failures open the global circuit. The actual item that trips that circuit is attributed and deferred, rather than repeatedly pinning the next run's front.
- The provisional daily ceiling is **48,000 total HTTP attempts per JST day**. Search, detail, retry and redirect traffic all count. This is not a BOOTH-published allowance. There is no separate 10,000-per-job cutoff.
- While both lanes have eligible work, 90% of attributable daily capacity is protected for known-ID refresh and 10% for discovery. Counts persist across runs. Legacy traffic with no trustworthy lane is fully charged before splitting the remaining capacity. A lane's unused share may be loaned only after proving it has no eligible queued or in-flight work; a search failure or quota-deferred item is not proof of completion. An ID denied before its first HTTP start can re-enter once when a loan becomes available, after the pool confirms its old key was released. Already-started attempts are not replayed unboundedly.
- Per-item failure backoff is 1 hour, 6 hours, 24 hours, 48 hours, 96 hours, then at most 7 days. Explicit 404/410 outcomes retry weekly. No ID is permanently dropped. Unknown product markup and individual corrupt histories do not halt all other products.

The known catalog contains roughly 195,000 IDs at the reviewed revision, so even one request per ID takes more than four daily 48,000-request allowances before discovery/retries. This design does not promise a daily sweep or a fixed speedup. Backoff, site changes, unavailable items and runtime limits can lengthen the cycle.

## Durable request allowance and rollout

Only the default branch may collect. Before HTTP work, the workflow reserves the remaining daily allowance in `data/request_budget.json` and must push that reservation. Every attempt increments its usage before transmission. A normal final checkpoint completes the reservation and refunds verified unused capacity. Shallow-safe pushes never force-push or text-merge conflicting quota changes.

If the final save is lost, the whole remote reservation remains charged. A zero-allowance reservation recovers automatically because it could not have sent requests. Nonzero unresolved reservations pause for verification of the previous run and any unknown server cooldown. A job crossing JST midnight stops before sending unreserved next-day requests; the next scheduled run obtains that day's allowance.

For the least disruptive rollout, finish the old collector before a clean JST-day boundary and start this version afterward. Preserve all product data and the crawl cursor. An operator may seed the budget with the last verified JST date when the old collector could send requests, `requests: 48000`, and the latest known absolute `blockedUntil` (zero only when no cooldown is outstanding), with no reservation. Once the current date is later, normal capacity becomes available without another full-day wait. Confirm the old collector ended and did not cross the boundary first.

Mid-day rollout requires a conservatively verified upper bound for all earlier HTTP traffic, not just saved-product counts. If no ledger/accounting exists, the default consumes the current day's allowance and starts on the next JST day. Never delete/reset an existing ledger to bypass quota or cooldown.

## Failure recovery

1. Check whether the final data/metadata push succeeded. Ordinary item/search failures with a successful checkpoint automatically resume when their retry dates and quota allow; other eligible IDs continue meanwhile.
2. For an unresolved nonzero reservation, confirm the previous Actions run is terminal. Review its complete logs/checkpoint to establish the cooldown outcome.
3. Once verified, keep `date`, `requests`, `reservation.limit`, `reservation.used`, and lane usage unchanged. Set `reservation.completed` to `true`, and retain the maximum of the existing and every verified `blockedUntil`. Review and commit this narrow repair. The abandoned allowance stays fully charged for its original day; after the cooldown, a later JST day receives its own allowance.
4. If the cooldown outcome cannot be established, retain the pause. A guessed finite wait cannot guarantee compliance with an unknown Retry-After. No extra Actions permissions or cross-run artifact architecture are introduced here.
5. Never restore an advanced search cursor/registry success marker without its associated product results. Keep the remote state when results were lost; repeated reads then consume the next approved allowance. For invalid metadata or systemic disk errors, repair the storage/state problem before restarting.

## Measurements and offline checks

Each run writes `data/collection_metrics.json`: HTTP attempts and lane counts, status/error counts, unique saved products, updates per request/second, HTTP p50/p95, maximum active HTTP calls, bootstrap/save/CPU time, and pool counts. Timing reflects the supplied clock and transport. Supplied mock clients may not expose HTTP timing, so `transportMeasured` states whether that instrumentation was active. Counts describe this run, not a claim of complete catalog coverage.

Run `npm ci`, `npm test`, and `node scripts/test_timeout.js`. Tests use mocked HTTP, temporary catalogs and disposable local Git remotes. They cover migration, old checkpoints, refill/no-overlap, lane fairness/loans, filtered-source boundaries, failures/deletion/backoff, budget/retry/redirect accounting, midnight, storage failures, shallow Git races and conflict safety. Controlled benchmark numbers must be labeled as synthetic; real BOOTH latency, throttling and end-to-end throughput remain unverified until an authorized production observation.

## Known write-amplification limit

The registry currently saves a complete prefix shard atomically after each successful/failed product outcome. In the synthetic 195,040-product benchmark (about 1,000 records per shard), 1,000 success updates passed about 198 MB cumulatively to filesystem writes and took 1.34 seconds on the test machine. At 48,000 outcomes, a linear volume extrapolation is about 9.5 GB of logical writes; this is neither the Git upload size nor a measurement of physical disk writes. Actual shard distributions, buffering, storage and runner performance differ. The corresponding time extrapolation is roughly 64 seconds/day, not a verified production result.

Immediate atomic checkpoints are retained for the tested recovery behavior. Reducing writes safely would require a durable append journal with replay/compaction, not simply postponing all saves until shutdown. That is a possible next optimization if authorized production metrics identify registry I/O as a bottleneck. The initial synthetic migration took 2.37 seconds; a restart took 0.48 seconds and read no product histories again. These local measurements do not predict BOOTH network performance.
