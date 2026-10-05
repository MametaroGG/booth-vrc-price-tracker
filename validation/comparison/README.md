# Controlled scheduler comparison

This operator harness is inert by default. It compares two schedulers using the same reviewed BOOTH request client, parser, history saver and catalog registry. Publishing and dispatching the workflow are separate operator actions.

## Fixed experiment

- Reviewed source: `4aedd907f01f10ce5eb36f69401fff4dadf89383`
- Catalog archive: `abe8b896c2165004b5ccbc618cf97da4a9ab4f26`
- Repository: `MametaroGG/booth-vrc-price-tracker`
- Branch: `test/booth-scheduler-comparison-20261005`
- Workflow: `booth_scheduler_comparison_20261005.yml`, first run number and first attempt only
- Exactly 40 known IDs, numeric-rank-bin midpoint sample, no discovery or availability filtering
- Four paired repetitions, `AB, BA, BA, AB`; deterministic independently seeded order per pair, identical order within each pair
- A is barrier batches of five, without the legacy extra one-second delay
- B is the actual reviewed `runTaskPool`, continuously refilling up to five slots
- A single request client and a single monotonic actual-HTTP-start gate remain alive across all eight blocks
- Every actual HTTP start is at least 500 ms after the previous start, aggregate concurrency at most five
- At most 50 HTTP dispatches per block and 400 for the new comparison; 320 initial item requests if all blocks complete
- Prior evidence consists of 12 separate requests. It is never subtracted from, or relabeled as, the newly authorized 400-request ceiling. This is comparison-only accounting and makes no full-day or official BOOTH allowance claim

HTTPS BOOTH same-product redirects on the default port are permitted, at most three per item. Every hop uses the same ledger and gate. Automatic transport redirects are disabled. No error is retried: the first 403, 429, timeout, other HTTP error, network error, unexpected redirect, correctness/storage error or safety violation stops the entire experiment. A 404 or 410 is ordinary unavailability and preserves original product history. Calls already in flight drain and may checkpoint successfully; nothing new is dispatched after the protective stop is observed. The maximum cooldown from all late responses is retained.

## Inputs and isolation

`manifest.json` uses `schema_version: 1`, `source.repository`, `source.commit`, `runtime_commit`, and exactly 40 `products`. Each product contains `id`, `path`, `sha256` and `git_blob_sha`. Paths are exactly `data/<first-three-ID-digits>/<ID>.json` relative to the snapshot root. Every input is validated against both supplied hashes and the pinned Git tree before any HTTP. Git lazy fetching is disabled.

The harness creates a 40-product seed under the output directory, bootstraps the reviewed registry once, and hashes the complete result. Each block copies this exact immutable history and registry tree afresh. Fixed IDs are used deliberately; same-day eligibility does not suppress later repetitions. Source histories and production data are never modified.

All generated files, including the one shared working ledger, must be under `RUNNER_TEMP` and outside checkout. The output directory must initially contain only the operator-supplied fresh ledger. Copy `initial-ledger.json` to `working-ledger.json` once. Do not recreate/reset it after a failure or unknown outcome. A permanent `comparison.lock` remains even after completion. Reruns, resume and rebinding to another run are refused.

## Offline validation

Run from an isolated copy of the harness:

```sh
BOOPA_REPO="$GITHUB_WORKSPACE" \
BOOPA_SNAPSHOT="$RUNNER_TEMP/boopa-comparison/snapshot" \
node --require ./offline-only.cjs --test comparison.test.js
```

The preload rejects sockets, HTTP, HTTPS and fetch. Tests use virtual time and injected responses, the reviewed production modules, and the actual archive snapshot. They cover both scheduling modes, all eight reset blocks, safe and unsafe redirects, global/block ceilings, shared pacing, concurrency, stop/drain/cooldown behavior, output correctness, storage failures, telemetry, watchdog and resume refusal. No BOOTH request is part of offline validation.

`node comparison.js` prints an inert plan. Live execution requires all fields:

```sh
node comparison.js --execute \
  --repo "$GITHUB_WORKSPACE" \
  --manifest "$RUNNER_TEMP/boopa-comparison/snapshot/manifest.json" \
  --snapshot-root "$RUNNER_TEMP/boopa-comparison/snapshot" \
  --output-dir "$RUNNER_TEMP/boopa-comparison-results" \
  --budget-file "$RUNNER_TEMP/boopa-comparison-results/working-ledger.json" \
  --expected-jst-day YYYY-MM-DD \
  --exclusive-until ISO_TIMESTAMP
```

The operator must independently verify the exclusive collection window and approved request scope. This program does not toggle any production workflow. It requires the expected repository/ref/workflow and workflow commit, first run number, first attempt, matching JST day, fresh ledger and pinned source contents.

The supervisor hard limit is 20 minutes from script start. When `COMPARISON_JOB_STARTED_AT` is supplied as an ISO timestamp by the first workflow step, dispatch stops no later than job start plus 18 minutes 30 seconds and the supervisor kills no later than job start plus 19 minutes. A 30-second maximum request timeout and reserved drain time leave room for terminal artifacts within a 20-minute job. Expired setup or an insufficient exclusive window fails closed.

## Measurements and interpretation

The parser warms once from local synthetic HTML, without HTTP. Each live block uses a fresh HTTPS agent with Node's default options and at most five sockets; connections are destroyed after block drain. No BOOTH warmup, proxy or fingerprint change, cache-busting request, or credential access is performed.

Each block reports setup-inclusive wall time, scheduler-entry through final data/registry/checkpoint writes, first actual HTTP start through that checkpoint, and HTTP-start span. Final result/summary serialization is reporting overhead outside the recorded checkpoint boundary. Per-request records include start/end timestamps, monotonic timing, latency, status, concurrency and actual gate waiting. Per-item records distinguish client waiting, parsing, history saving and registry writing. CPU usage and sampled RSS, successes/unavailable/failures, unique IDs, all four paired differences and ratios, and ratio/difference spread are included. Safe cache headers are retained when present; remote cache state remains uncontrolled.

The pinned request client durably charges before calling its attempt hook. A stop or deadline may therefore leave a conservative charge without a transport dispatch, including the final block-ceiling guard. `chargedHttp`, `actualHttp` and `prechargedWithoutDispatch` explicitly distinguish these cases. Such charges are never refunded or silently reset. The hard 50/400 HTTP limits apply to all actual dispatches; the client also caps the shared durable ledger at 400.

The registry contains only these 40 records, not the full catalog. This pilot isolates normalized scheduling and is not a strict legacy whole-pipeline A/B, a statistically powered catalog sample, or evidence for full-catalog runtime/distributed-runner performance.

## Artifacts and protective stops

Retain the entire output directory, including `working-ledger.json`, `comparison.lock`, `summary.json`, `requests.jsonl`, the immutable `seed/`, and each `block-XX-A|B/` directory with data, checkpoint and result. `completion.json` is written only after terminal verification. `watchdog.json` records an unknown outcome if the supervisor kills execution. Missing completion, failed storage, watchdog stops or lost artifacts require operator reconciliation; never rerun or automatically resume production. Respect the maximum retained cooldown before any separately authorized restoration.
