# Search crawler: runtime limits, checkpoints and recovery

## Scope

The crawler keeps the original two filtered VRChat/digital search URLs, category/page order, 3,333-page limit, five-item `Promise.all` batches, one-second wait after a batch, and two-second wait between search pages. HTTP starts have no additional fixed interval. One Actions concurrency group serializes runs and one writer saves results. There is no known-ID catalog migration, oldest-first refresh, discovery/refresh quota split, or refill pool.

Search remains the source of collection candidates. Products absent from those filtered results may not be revisited. The changes improve delayed-start handling, failure/resume behavior, and saving; no throughput gain or full-known-catalog coverage is claimed.

## Runtime and saving

The collection deadline is the earlier of script start + five hours and job start + five hours thirty minutes. A delayed checkout cannot produce a deadline already in the past simply because the next cron is close. The six-hour job timeout and thirty-minute saving margin remain. The existing `scrape-group` concurrency serializes jobs; each job checks out the latest default-branch state with depth one.

Completed histories are written atomically. Existing corrupt or incompatible history is retained and reported, rather than overwritten. The page cursor and unfinished IDs are checkpointed; completed details are removed only after their history is saved. A failure-only retry queue contains IDs obtained from the filtered search. It is not a registry of all products.

Search failure or unrecognized markup retains its cursor and fails the run; it is not treated as an empty result or the end of a category. Recognized empty results advance to the next category. Individual detail failures are retained for a later bounded retry while the crawl continues. Retry batches use the same concurrency and waits. Completed page/category traversal can restart normally on a later run even if some items remain in backoff.

A stop for quota, deadline, day boundary, 403/429 or storage failure leaves unfinished work resumable. Already-started work drains before the final checkpoint. The workflow attempts to save partial results after an ordinary scraper failure, then reports that failure. A conflicting Git update is never overwritten or force-pushed. Shallow-safe replay fetches only the new branch tip and refuses conflicting request-budget state.

## Shared request budget

The provisional limit is **48,000 total HTTP attempts per JST day**, across all scheduled runs. It includes search, detail, retries and redirects. This is an operator-selected ceiling, not a BOOTH-published allowance. Keeping this prior constraint requires `data/request_budget.json` even in the smaller repair. There is no separate per-job cutoff or per-lane allocation.

Before HTTP work, the workflow reserves the remaining daily allowance and must push that reservation successfully. Usage is incremented before every HTTP transmission. A normal final checkpoint completes the reservation and refunds only verified unused capacity. Crossing JST midnight stops the run before using an unreserved next-day allowance.

The final log reports this run’s charged HTTP attempts and the day’s charged total. A charge persisted immediately before an interrupted dispatch remains conservative; it is not proof that BOOTH received that request.

Each HTTP attempt times out after at most thirty seconds, shortened by the runtime remaining. Network/408/5xx errors receive at most three attempts with backoff. Redirect hops are counted and restricted to the same requested product identity or exact filtered-search identity. HTTP 403/429 stop new requests globally: 403 pauses at least six hours, and 429 respects Retry-After with a sixty-second minimum. Five consecutive transient failures open the shared circuit. Retries remain inside the same daily ceiling and five-item batches.

## Rollout and recovery

For a clean rollout, let the old collector finish before a verified JST-day boundary and start the new version afterward. Preserve product histories and the existing crawl cursor. A verified last old-collector date may be seeded with `requests: 48000`, the latest known `blockedUntil`, and no reservation. When the current JST date is later, the new allowance is available. Confirm that no old run crossed the boundary first.

For a midday rollout, an upper bound for all earlier HTTP traffic is required. Saved-product counts alone omit searches, retries and redirects. If earlier traffic is unknown, the default marks that day fully used and starts collecting on the next JST day. Never delete an existing ledger to replenish quota.

If a run loses its final save, a nonzero remote reservation remains fully charged and collection pauses. Confirm the previous run is terminal and inspect its saved results/logs for cooldown information. Once the outcome is verified, keep the recorded requests and reservation charge, mark the abandoned reservation completed, and retain the maximum verified cooldown. The charge is not refunded. If the cooldown cannot be established, the hold remains; an arbitrary wait cannot prove an unknown Retry-After has expired. A zero-allowance reservation recovers automatically because no request could have been sent.

Corrupt checkpoints or systemic storage errors fail closed. Repair them from verified history/checkpoints; do not advance a cursor without its saved results. No additional Actions permissions or cross-run artifact recovery service is introduced.

## Validation

`npm test` and `node scripts/test_timeout.js` run without BOOTH access. Tests cover delayed starts, exact filtered URLs, batch/page waits, typed search outcomes, pending-page resume, failed-item retries, unavailable products, atomic history preservation, request accounting, redirects, timeout/backoff, 403/429, JST boundaries, lost reservations and shallow Git push races/conflicts.

The prior refill benchmark measured a different design. Its roughly three-percent result does not predict the performance of this minimal repair. Real HTTP compatibility was checked separately on a small fixed sample; a full production cycle of this narrowed version has not been run.
