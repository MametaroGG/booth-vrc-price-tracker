# Search crawler: continuous runs, checkpoints and recovery

## Scope and runtime

The original two filtered VRChat/digital searches, category/page order, 3,333-page limit, five-item Promise.all batches, one-second batch wait, and two-second page wait remain. There is no extra HTTP start interval, known-ID registry, priority lane, or refill pool. Products absent from filtered search results may still be missed.

Each run collects for at most five hours and also stops by job start + five hours thirty minutes. The six-hour job timeout and thirty-minute save margin remain. The shared scrape-group with cancel-in-progress:false serializes jobs; every job checks out the latest default branch at depth one.

Removing the daily ceiling allows more running time. It does not make individual requests faster, guarantee a daily full sweep, or establish BOOTH's permitted request volume.

## Automatic continuation

After a productive run reaches its actual time boundary, the workflow saves and pushes the final data, cursor and request state, then makes one repository_dispatch request for the next run. Scraper outcome, final push and an explicit continuation output must all be successful. A failed step masked by continue-on-error cannot trigger continuation.

A normal JST-midnight checkpoint can continue too. A healthy full-sweep completion may repeat when it started partway through the sweep, or when a complete sweep from page one took at least an hour. This lets a short final segment hand over while preventing repeated tiny full sweeps. Empty work, unknown results, global failures, active cooldowns and failed saves do not chain. Isolated item failures already stored in the retry queue do not prevent a normal deadline handover.

The original six-hour cron remains a fallback. A dispatch is attempted once, with a thirty-second timeout and no retry after an uncertain result. Pending cron and continuation runs can replace one another under the existing concurrency rule; the active run is not interrupted and the successor reads the newest saved state.

This uses the existing contents:write GITHUB_TOKEN permission. No PAT, new secret or actions:write is needed. The repository_dispatch listener must be on the default branch. Runner queues, checkout, saving, service delays and required server cooldowns still create gaps; literal uninterrupted 24-hour operation is not guaranteed.

## Saved progress and history

Histories are written atomically. Existing corrupt or incompatible histories are retained and reported, not overwritten. A page's pending IDs are persisted before details start and removed only after their history is saved. Failure-only retry entries come from the filtered searches.

A search error or unrecognized markup preserves its cursor and fails the run. Recognized empty results advance the category. Individual detail failures are deferred with bounded backoff while other items continue. Already-started requests drain before the final checkpoint.

BOOTH also renders a normal search page beyond its last page without an empty-results message. This case advances only when the page title matches the requested page, the search heading and positive result count are present, the unique result-card list is empty, and a final-page control plus its numbered link identify an earlier page with the same origin, category and complete non-page filters. Missing, malformed, conflicting or unrelated pagination remains a failure. A `rel=next` link can still exist beyond the last page and does not override the final-page evidence. The reduced real-DOM fixture under `test/fixtures` documents this case.

The workflow attempts to save partial results after ordinary scraper failures and then exposes the failure. Shallow-safe push replay refuses conflicting request-state changes, without force-pushing or overwriting unrelated updates.

## Observations, sessions and server limits

There is no production daily request ceiling. The former 48,000/JST-day limit was an operator-selected provisional ceiling, not a BOOTH-published allowance. An optional finite injected runtime mode remains for compatibility tests; production uses unlimited mode.

The existing data/request_budget.json records daily observed attempts, server cooldowns and an active run marker. Before BOOTH access, the workflow pushes a session with mode:unlimited, limit:null, used:0 and completed:false. Each search, detail, retry and redirect increments session used and daily requests before transmission. It does not precharge an infinite allowance. The final checkpoint completes the session.

JST midnight ends the current session at a safe checkpoint. A successor preserves its cursor and cooldown, then starts a new session with a new daily observation counter. A missing ledger can start immediately at zero observed requests; this does not claim that no earlier untracked traffic occurred. Counts are conservative accounting, not packet traces. A lost final save can leave remote observations incomplete.

Each HTTP attempt has at most a 30-second timeout, shortened by time remaining. Network/408/5xx errors get at most three attempts with backoff. Redirects are bounded and restricted to the same product or exact filtered-search identity. HTTP 403 stops new requests for at least six hours; HTTP 429 respects Retry-After with a 60-second minimum. Five consecutive transient failures open the shared circuit.

Retry waits extending beyond the runtime or JST boundary persist a cooldown and stop continuation. Terminal transient errors, circuit stops and draining concurrent failures retain any longer Retry-After. Removing the daily ceiling does not remove these protections.

## Rollout and recovery

Let an existing collector finish and verify its final save before deployment. Preserve histories, cursor, observation counts, migration metadata and blockedUntil. A completed old finite reservation migrates directly, including a daily count already at 48,000. No next-day wait or ledger reset is required.

An unresolved old nonzero reservation or any unresolved unlimited session blocks collection, even if its remote used count is zero: request outcomes and server cooldowns may have been lost. Confirm that the prior run is terminal and inspect its saved state/logs before marking it completed and retaining the maximum verified cooldown. If the cooldown is unknown, the hold remains; an arbitrary wait cannot prove an unknown Retry-After expired. Only a legacy zero-allowance finite reservation can recover automatically.

Corrupt checkpoints and systemic storage errors fail closed. Repair from verified state, without advancing a cursor beyond saved results. A continuous chain may therefore need operator recovery after a genuine failure.

## Validation

Offline tests cover the original filters/pacing, five-hour boundary, request observations above 48,000, completed legacy migration, unresolved holds, rollover, cursor restart, history preservation, bounded retries, server cooldowns, shallow push conflicts and one-attempt dispatch behavior. Run npm test and node scripts/test_timeout.js with mocked networking. Include production-like SCRAPER_JOB_STARTED_AT and SCRAPER_RESERVATION_ID to verify test-fixture isolation.

After deployment, verify a saved normal run, one accepted dispatch and its successor resuming the newest cursor. Offline tests cannot prove GitHub event delivery. Prior capped production runs proved their saving/restart behavior, not this new continuation mechanism.

## GitHub references

- [GITHUB_TOKEN dispatch exception](https://docs.github.com/en/actions/concepts/security/github_token)
- [Repository dispatch permission](https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event)
- [Event and default-branch requirements](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#repository_dispatch)
- [Concurrency behavior](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)
- [Hosted-job execution limit](https://docs.github.com/en/actions/reference/limits)
- [Public-runner billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

Standard ubuntu-latest usage in this public repository is currently free. No paid runner or plan change is introduced.
