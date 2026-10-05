# GitHub runner probe preparation

This is an offline-prepared adaptation, not a published workflow. No BOOTH request, push, workflow change, or dispatch was performed while preparing it.

## Scope and remaining allowance

- Approved incremental test maximum: 20 HTTP attempts total across cloud and runner, including redirects and retries
- Cloud already consumed 2 attempts. This runner may consume **at most 18 additional attempts**, fewer if the transferred counter has advanced
- The authoritative existing ledger is copied exactly into `prior-ledger.json`: `requests: 2`, `blockedUntil: 1791179136081`, `laneUsage: {refresh: 2, discovery: 0}`, `laneReleased: {refresh: false, discovery: true}`, and original date/scope labels
- That reference is not a fresh allowance and must never reset a retry. Transfer the current ledger exactly once when the operator authorizes the first runner attempt. Keep later counts, cooldowns, and binding intact
- `GITHUB_RUN_ATTEMPT` must be exactly `1`; a rerun refuses live work. The actual working ledger is bound to its first `GITHUB_RUN_ID`, and another run cannot reuse/rebind it silently
- A second workflow dispatch is not authorized by this package. After an interrupted or unknown outcome, preserve the counter and reconcile the outcome before any further action. Never create a replacement ledger from the reference
- The old collector's complete daily usage remains unknown. Every exception report explicitly says it does **not** establish full-day 48,000-request compliance

## Runtime and source pins

The product catalog remains pinned to `abe8b896c2165004b5ccbc618cf97da4a9ab4f26`. The ten IDs remain 1000657, 3403378, 4472127, 5298885, 6156901, 6750014, 7354487, 7883654, 8439329, and 999974.

The runtime is pinned to PR commit `4aedd907f01f10ce5eb36f69401fff4dadf89383`. Live preflight verifies that commit is an ancestor of HEAD and verifies `src/collection-runtime.js`, `src/scraper.js`, and `package-lock.json` against their exact Git blob IDs in the PR tree. A separate test-only child commit is allowed; changing the runtime files is not. No exact-HEAD equality is required.

All ten existing historical JSON files are packaged under `history-cache/data/PREFIX/ID.json`. Every history's Git blob SHA is checked before any HTTP client is created or charge taken. The cache avoids needing production `data/` in the checkout. Git always uses `--no-lazy-fetch`, `GIT_NO_LAZY_FETCH=1`, and `GIT_ALLOW_PROTOCOL=''`.

## Integration contract for the operator

Publication and dispatch remain the operator's responsibility, subject to the separately approved scope. No workflow YAML is installed by this package.

1. A possible test-only commit can put this folder under `/validation/runner/` in the separate approved test branch. Do not change the PR runtime or production workflow. Include the ten cache files and the preserved reference ledger
2. Checkout depth three retaining test commit, PR commit, and ABE catalog commit, with non-cone sparse paths `/src/`, `/test/`, `/validation/`, `/package.json`, and `/package-lock.json`. Do not checkout secrets or production data. Use the repository's locked dependencies
3. Enforce `github.run_attempt == 1` before any live preparation. Copy `validation/runner/` into a fresh `$RUNNER_TEMP/boopa-probe` directory, outside `GITHUB_WORKSPACE`; the code intentionally rejects an in-checkout harness. Do not overwrite an existing live folder/ledger
4. Run offline tests and a dry run. The operator verifies publication authority, old-workflow pause, no active competing runs, cooldown, current JST day, and an exclusive window covering the full 295-second watchdog
5. Transfer the **current authoritative ledger** into the isolated runner folder once, preserving every existing field. The initial baseline is provided for review only; it is not permission to initialize another attempt after uncertainty
6. The operator may then execute the command below once. `--exclusive-until` and `--expected-jst-day` must be supplied from the operator-verified window; the program never chooses or resets them
7. Preserve the working ledger, summary, requests log, and any stale `.probe.lock` on every outcome. Use an always-run artifact step if the authorized workflow is later created. Never upload environment dumps, request headers, node_modules, or unrelated repository files
8. Operator reviews the terminal result before any legacy resumption. A 403/429, retained Retry-After, timeout/circuit stop, or interrupted/uncertain outcome prohibits blind resumption. A five-minute timer does not clear a cooldown or an unknown server response

## Commands

Offline preview, from either this isolated preparation directory or the copied runner directory:

```sh
BOOPA_REPO=/path/to/checkout node /path/outside/checkout/probe.js \
  --accounting-scope incremental-exception
BOOPA_REPO=/path/to/checkout node --test /path/outside/checkout/probe.test.js
```

Operator-only live invocation template, not executed during preparation:

```sh
BOOPA_REPO="$GITHUB_WORKSPACE" \
node "$RUNNER_TEMP/boopa-probe/probe.js" \
  --execute --accounting-scope incremental-exception \
  --budget-file "$RUNNER_TEMP/boopa-probe/working-ledger.json" \
  --expected-jst-day OPERATOR_VERIFIED_JST_DAY \
  --exclusive-until OPERATOR_VERIFIED_UTC_ISO_TIMESTAMP \
  --history-cache "$RUNNER_TEMP/boopa-probe/history-cache"
```

The exact expected repository is `MametaroGG/booth-vrc-price-tracker`. The working ledger must carry the exception labels `accountingScope: "incremental-exception"` and `knownScope: "probe-only"`. Missing/wrong scope, fewer than two previous charges, an earlier cooldown, changed prior lane flags, a different date, exhausted allowance, wrong repository, a previous run binding, or `run_attempt > 1` refuses live work.

## Fixed request controls

One request at a time; at least 1,000 ms between actual starts; at most 30 seconds per HTTP timeout; two transient attempts per item; three redirect hops per item; global stop after two consecutive transient failures; immediate global stop on 403/429; only HTTPS BOOTH hosts and the same approved product ID; no nondefault port or URL credentials; maximum four MiB response content. No proxy, authentication, cookie, user-agent, fingerprint, or access-control changes are added by this adaptation.

The work deadline is 285 seconds and the separate supervisor kills the worker at 295 seconds. Deadline/JST guards run again after the final pre-dispatch disk write. Charged-but-not-dispatched attempts remain charged. Interrupted runs leave a lock and conservative accounting.

## Diagnostic output

Each completed request record retains HTTP status and only these response headers, when present: `content-type`, `server`, `via`, `x-cache`, `retry-after`. Values are plain text and bounded to 200 characters. No request or environment headers are logged.

For an HTTP error with a text/plain or text/html response, the log retains at most 512 characters of sanitized plain-text body prefix. Scripts, styles, tags, control characters, emails, long opaque values, and URL credentials/query/fragment values are removed; text suggesting credentials, cookies, sessions, API keys, or tokens is omitted entirely. Other/unknown body types are omitted. Successful response bodies are never logged. Redirect URLs and request URLs in diagnostic events omit credentials, queries, and fragments. Full bodies are bounded by the four-MiB transport limit and are not retained as diagnostic files.

These diagnostics may help distinguish an upstream/intermediary 502; they do not by themselves prove which system generated it. Parsing is performed against received bytes without a second HTTP request, and saving touches only isolated copies.

## Offline evidence

The offline suite contains 28 passing tests, including combined redirect/retry ceilings; 2 prior plus 18 runner attempts; wrong/missing scope; first-run-attempt and run binding; retained cooldown/lane state; PR source hashes with descendant HEAD semantics; all-history preflight and cache hashes; expiry and midnight after the final log write; 403/429; timeout/circuit stop; safe 502 metadata and credential omission; no import/default execution; and no tracked repository changes. Preparation logs and local-machine paths are deliberately excluded from this portable package.

The mocked pin-ancestry test models a test-branch child without modifying the existing checkout. Actual runner ancestry is checked again before any live HTTP. Mock timing and error bodies are synthetic and are not runner results.
