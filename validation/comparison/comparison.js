'use strict';

// Inert unless a first-attempt, explicitly gated GitHub Actions execution is requested.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync, fork } = require('node:child_process');
const { performance } = require('node:perf_hooks');
const { plainText, safeResponse, safeUrl } = require('./diagnostics');

const SOURCE_COMMIT = '4aedd907f01f10ce5eb36f69401fff4dadf89383';
const CATALOG_COMMIT = 'abe8b896c2165004b5ccbc618cf97da4a9ab4f26';
const REPOSITORY = 'MametaroGG/booth-vrc-price-tracker';
const EXPECTED_REF = 'refs/heads/test/booth-scheduler-comparison-20261005';
const EXPECTED_WORKFLOW = '.github/workflows/booth_scheduler_comparison_20261005.yml';
const PRIOR_EVIDENCE_REQUESTS = 12;
const LIMITS = Object.freeze({ products: 40, blocks: 8, pairs: 4, concurrency: 5, intervalMs: 500,
    blockHttp: 50, totalHttp: 400, timeoutMs: 30000, maxAttempts: 1,
    runtimeMs: 20 * 60 * 1000, drainReserveMs: 35000, maxResponseBytes: 4 * 1024 * 1024 });
const PAIR_ARMS = Object.freeze([['A', 'B'], ['B', 'A'], ['B', 'A'], ['A', 'B']]);
const SOURCE_FILES = ['src/collection-runtime.js', 'src/scraper.js', 'src/catalog-registry.js',
    'src/task-pool.js', 'src/collector.js', 'package.json', 'package-lock.json'];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const sha256 = data => crypto.createHash('sha256').update(data).digest('hex');
const blobSha = bytes => crypto.createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex');
const inside = (child, root) => child === root || child.startsWith(root + path.sep);
const jstDate = time => new Date(time + 9 * 3600000).toISOString().slice(0, 10);
const git = (repo, args) => execFileSync('git', ['--no-lazy-fetch', '-C', repo, ...args], {
    encoding: 'utf8', timeout: 15000, maxBuffer: 32 * 1024 * 1024,
    env: { ...process.env, GIT_NO_LAZY_FETCH: '1', GIT_ALLOW_PROTOCOL: '' } });
const errorInfo = error => ({ reason: error?.reason || error?.code || 'error',
    message: plainText(error?.message || String(error), 300), code: error?.code || null });
function atomicJson(file, value) {
    fs.writeFileSync(file + '.tmp', JSON.stringify(value, null, 2) + '\n', { mode: 0o600 });
    fs.renameSync(file + '.tmp', file);
}
class ExperimentStop extends Error {
    constructor(reason, message) { super(message); this.name = 'ExperimentStop'; this.reason = reason; }
}
function safeTarget(value, id, base) {
    try {
        const url = new URL(value, base);
        return url.protocol === 'https:' && !url.port && !url.username && !url.password &&
            (url.hostname === 'booth.pm' || url.hostname.endsWith('.booth.pm')) &&
            new RegExp(`^/(?:ja/|en/)?items/${id}/?$`).test(decodeURIComponent(url.pathname));
    } catch { return false; }
}
function runtimeBounds(startedAt, env = process.env, now = Date.now()) {
    let hardDeadline = startedAt + LIMITS.runtimeMs;
    let dispatchDeadline = hardDeadline - LIMITS.drainReserveMs;
    if (env.COMPARISON_JOB_STARTED_AT) {
        const jobStart = Date.parse(env.COMPARISON_JOB_STARTED_AT);
        if (!Number.isFinite(jobStart) || jobStart > startedAt) throw new Error('Invalid comparison job start');
        dispatchDeadline = Math.min(dispatchDeadline, jobStart + 18.5 * 60000);
        hardDeadline = Math.min(hardDeadline, jobStart + 19 * 60000);
    }
    if (dispatchDeadline <= now || hardDeadline - dispatchDeadline < LIMITS.timeoutMs) throw new Error('Comparison setup consumed the usable runtime window');
    return { dispatchDeadline, hardDeadline };
}
function sourceHashes(repo) {
    if (git(repo, ['rev-parse', `${SOURCE_COMMIT}^{commit}`]).trim() !== SOURCE_COMMIT) throw new Error('Reviewed source commit is unavailable');
    git(repo, ['merge-base', '--is-ancestor', SOURCE_COMMIT, 'HEAD']);
    return Object.fromEntries(SOURCE_FILES.map(file => {
        const bytes = fs.readFileSync(path.join(repo, file));
        if (blobSha(bytes) !== git(repo, ['rev-parse', `${SOURCE_COMMIT}:${file}`]).trim()) throw new Error(`Pinned source mismatch: ${file}`);
        return [file, sha256(bytes)];
    }));
}
function readSnapshot(manifestFile, root, repo) {
    root = fs.realpathSync(root);
    const manifestBytes = fs.readFileSync(manifestFile);
    const manifest = JSON.parse(manifestBytes);
    if (manifest.schema_version !== 1 || manifest.source?.repository !== REPOSITORY ||
        manifest.source?.commit !== CATALOG_COMMIT || manifest.runtime_commit !== SOURCE_COMMIT ||
        !Array.isArray(manifest.products) || manifest.products.length !== LIMITS.products) throw new Error('Snapshot manifest provenance or product count mismatch');
    const ids = new Set();
    const products = manifest.products.map(product => {
        const { id, path: relative, sha256: hash, git_blob_sha: blob } = product;
        if (typeof id !== 'string' || !/^[1-9]\d*$/.test(id) || ids.has(id) ||
            relative !== `data/${id.slice(0, 3)}/${id}.json` || !/^[a-f0-9]{64}$/.test(hash) || !/^[a-f0-9]{40}$/.test(blob)) throw new Error('Invalid or duplicate snapshot product');
        ids.add(id);
        const file = path.resolve(root, relative);
        if (!inside(file, root) || fs.realpathSync(file) !== file || !fs.lstatSync(file).isFile()) throw new Error('Snapshot file must be a regular non-symlink input');
        const bytes = fs.readFileSync(file);
        if (sha256(bytes) !== hash || blobSha(bytes) !== blob ||
            git(repo, ['rev-parse', `${CATALOG_COMMIT}:${relative}`]).trim() !== blob) throw new Error(`Snapshot hash mismatch: ${relative}`);
        const parsed = JSON.parse(bytes);
        if (String(parsed.id) !== id || !parsed.variations || typeof parsed.variations !== 'object' || Array.isArray(parsed.variations) ||
            !Object.values(parsed.variations).every(Array.isArray)) throw new Error(`Invalid history schema: ${relative}`);
        return { id, path: relative, sha256: hash, git_blob_sha: blob, bytes };
    });
    return { manifestSha256: sha256(manifestBytes), products,
        provenance: { catalogCommit: CATALOG_COMMIT, sourceCommit: SOURCE_COMMIT,
            populationCount: manifest.sampling?.population_count ?? null, sampleCount: products.length } };
}
function permutation(ids, pair) {
    // Each pair has a reproducible independently seeded shuffle; both arms reuse it.
    const result = ids.slice();
    let seed = crypto.createHash('sha256').update(`boopa-comparison-v1-pair-${pair}`).digest().readUInt32LE(0);
    for (let i = result.length - 1; i > 0; i--) {
        seed ^= seed << 13; seed ^= seed >>> 17; seed ^= seed << 5;
        const j = (seed >>> 0) % (i + 1);
        [result[i], result[j]] = [result[j], result[i]];
    }
    return result;
}
function blockPlan(ids) {
    return PAIR_ARMS.flatMap((arms, pair) => {
        const order = permutation(ids, pair + 1);
        return arms.map((arm, position) => ({ index: pair * 2 + position + 1, pair: pair + 1, arm, order: order.slice(),
            seed: `boopa-comparison-v1-pair-${pair + 1}` }));
    });
}
function freshLedger(date) {
    return { date, requests: 0, blockedUntil: 0,
        accountingScope: 'comparison-only', fullDayComplianceEstablished: false,
        priorEvidenceRequests: PRIOR_EVIDENCE_REQUESTS, comparisonCeiling: LIMITS.totalHttp,
        notice: 'Prior evidence is separate from this newly authorized comparison. No official daily allowance is asserted.',
        laneUsage: { refresh: 0, discovery: 0 }, laneReleased: { refresh: false, discovery: true } };
}
function validateRunner(options, env = process.env, now = Date.now()) {
    if (env.GITHUB_ACTIONS !== 'true' || env.GITHUB_REPOSITORY !== REPOSITORY || env.GITHUB_REF !== EXPECTED_REF ||
        env.GITHUB_RUN_ATTEMPT !== '1' || env.GITHUB_RUN_NUMBER !== '1' || !/^[1-9]\d*$/.test(env.GITHUB_RUN_ID || '') ||
        env.GITHUB_WORKFLOW_REF !== `${REPOSITORY}/${EXPECTED_WORKFLOW}@${EXPECTED_REF}` ||
        !/^[a-f0-9]{40}$/.test(env.GITHUB_SHA || '')) throw new Error('Expected repository, branch, workflow, first run number and first attempt are required; reruns are forbidden');
    if (options.expectedJstDay !== jstDate(now)) throw new Error('Expected JST day must match; no day reset is permitted');
    const exclusiveUntil = Date.parse(options.exclusiveUntil);
    if (!Number.isFinite(exclusiveUntil) || exclusiveUntil < now + LIMITS.runtimeMs ||
        jstDate(now + LIMITS.runtimeMs) !== options.expectedJstDay) throw new Error('Verified exclusive window must cover the 20-minute watchdog in one JST day');
    const ledger = JSON.parse(fs.readFileSync(options.budgetFile));
    const expected = freshLedger(options.expectedJstDay);
    if (ledger.accountingScope !== expected.accountingScope || ledger.fullDayComplianceEstablished !== false ||
        ledger.priorEvidenceRequests !== PRIOR_EVIDENCE_REQUESTS || ledger.comparisonCeiling !== LIMITS.totalHttp ||
        ledger.requests !== 0 || ledger.date !== options.expectedJstDay || !Number.isFinite(ledger.blockedUntil) || ledger.blockedUntil > now || ledger.blockedUntil < 0 ||
        ledger.runnerRunId || ledger.reservation || ledger.laneUsage?.refresh !== 0 || ledger.laneUsage?.discovery !== 0 ||
        ledger.laneReleased?.discovery !== true || ledger.laneReleased?.refresh !== false) throw new Error('A fresh authorized comparison-only ledger starting at zero is required; never resume/reset/rebind an existing run');
    return { exclusiveUntil, runId: env.GITHUB_RUN_ID, runAttempt: 1, runNumber: 1, workflowCommit: env.GITHUB_SHA };
}
function checkPaths(options, env = process.env) {
    const repo = fs.realpathSync(options.repo);
    const temp = fs.realpathSync(env.RUNNER_TEMP);
    const output = path.resolve(options.outputDir);
    const ledger = path.resolve(options.budgetFile);
    if (inside(temp, repo) || inside(output, repo) || inside(repo, output) ||
        !inside(output, temp) || output === temp || path.dirname(ledger) !== output ||
        fs.realpathSync(output) !== output || fs.realpathSync(ledger) !== ledger ||
        !fs.lstatSync(ledger).isFile() || fs.statSync(ledger).nlink !== 1 ||
        fs.readdirSync(output).some(file => file !== path.basename(ledger))) throw new Error('All execution outputs and the fresh ledger must use an empty regular directory under RUNNER_TEMP outside checkout');
    return { repo, outputDir: output, budgetFile: ledger };
}

// All actual HTTP starts, including any future follow-up attempt, enter this one gate.
// The production request client independently charges and paces every request first.
function createStartGate({ now = Date.now, mono = () => performance.now(), wait = sleep,
    deadline, expectedJstDay, onEvent = () => {}, onStop = () => {}, limits = LIMITS }) {
    let gate = Promise.resolve(), stopped = null, lastStart = -Infinity, active = 0, total = 0;
    const blocks = new Map();
    const state = { maxActive: 0, starts: [], stoppedAt: null, cooldownUntil: 0 };
    function stop(reason, message) {
        if (!stopped) { stopped = new ExperimentStop(reason, message); state.stoppedAt = now(); onStop(stopped); }
        return stopped;
    }
    function check() {
        if (stopped) throw stopped;
        if (now() >= deadline) throw stop('watchdog', 'Overall dispatch deadline reached');
        if (expectedJstDay && jstDate(now()) !== expectedJstDay) throw stop('day-boundary', 'JST day changed');
    }
    async function run(block, item, url, config, transport) {
        const queuedMono = mono();
        const reservation = gate.then(async () => {
            check();
            while (mono() - lastStart < limits.intervalMs) { await wait(limits.intervalMs - (mono() - lastStart)); check(); }
            const blockCount = blocks.get(block) || 0;
            if (total >= limits.totalHttp || blockCount >= limits.blockHttp) throw stop('http-budget', 'HTTP dispatch ceiling reached');
            if (active >= limits.concurrency || config.maxRedirects !== 0) throw stop('concurrency', 'HTTP concurrency or redirect invariant failed');
            if (!safeTarget(url, item.id)) throw stop('target', 'Only an approved same-product BOOTH URL is allowed');
            const attempt = { sequence: total + 1, block, id: item.id, url: safeUrl(url), phase: 'pre-dispatch',
                preloggedAt: new Date(now()).toISOString(), transportInvoked: false, status: null, startedAt: null,
                startedMonoMs: null, endedAt: null, endedMonoMs: null, latencyMs: null,
                pacingWaitMs: Math.max(0, mono() - queuedMono), timeoutMs: config.timeout, error: null };
            try { onEvent(attempt); } catch (error) { throw stop('storage', error.message); }
            check(); // A slow durable write may cross the deadline or JST boundary.
            const startMono = mono();
            if (startMono - lastStart < limits.intervalMs) throw stop('pacing', 'Actual HTTP start spacing invariant failed');
            if (active >= limits.concurrency) throw stop('concurrency', 'Actual HTTP concurrency invariant failed');
            attempt.startedAt = new Date(now()).toISOString(); attempt.startedMonoMs = startMono;
            attempt.startSpacingMs = Number.isFinite(lastStart) ? startMono - lastStart : null;
            attempt.transportInvoked = true; attempt.activeAtStart = ++active;
            total++; blocks.set(block, blockCount + 1); lastStart = startMono;
            state.maxActive = Math.max(state.maxActive, active); state.starts.push(startMono);
            item.httpAttempts++; item.pacingWaitMs += attempt.pacingWaitMs;
            // No await, disk write, or callback between this marker and transport.
            let pending;
            try { pending = Promise.resolve(transport(url, { ...config, maxRedirects: 0, maxContentLength: limits.maxResponseBytes })); }
            catch (error) { pending = Promise.reject(error); }
            pending = pending.then(response => {
                attempt.status = response.status; attempt.responseMetadata = safeResponse(response);
                if (response.status >= 300 && response.status < 400) {
                    const location = response.headers?.location;
                    item.redirects = (item.redirects || 0) + 1;
                    if (![301, 302, 303, 307, 308].includes(response.status) || !location ||
                        !safeTarget(location, item.id, url) || item.redirects > 3) {
                        stop('unexpected-redirect', 'Unsafe, unrecognized or excessive redirect stops the comparison');
                        throw Object.assign(new ExperimentStop('unexpected-redirect', 'Unsafe, unrecognized or excessive redirect'), { response });
                    }
                    attempt.location = safeUrl(location, url);
                    return response;
                }
                if (response.status !== 200 && ![404, 410].includes(response.status)) {
                    const reason = response.status === 403 ? 'forbidden' : response.status === 429 ? 'rate-limit' : 'http-error';
                    stop(reason, `HTTP ${response.status} stops the comparison`);
                    throw Object.assign(new Error(`HTTP ${response.status}`), { response });
                }
                if ([404, 410].includes(response.status)) throw Object.assign(new Error(`HTTP ${response.status}`), { response });
                return response;
            }).catch(error => {
                attempt.status = error.response?.status || attempt.status;
                attempt.responseMetadata = safeResponse(error.response) || attempt.responseMetadata || null;
                attempt.error = errorInfo(error);
                if (![404, 410].includes(attempt.status)) {
                    stop(attempt.status === 403 ? 'forbidden' : attempt.status === 429 ? 'rate-limit' :
                        ['ETIMEDOUT', 'ECONNABORTED', 'ERR_CANCELED'].includes(error.code) ? 'timeout' : error.reason || 'network-error', error.message);
                    const value = error.response?.headers?.['retry-after'];
                    const minimum = attempt.status === 403 ? 6 * 3600000 : 60000;
                    if ([403, 429].includes(attempt.status) || value != null) {
                        const seconds = Number(value), time = value != null && Number.isFinite(seconds) && seconds >= 0 ? now() + seconds * 1000 : Date.parse(value);
                        state.cooldownUntil = Math.max(state.cooldownUntil, now() + minimum, Number.isFinite(time) ? time : 0);
                    }
                }
                throw error;
            }).finally(() => {
                active--; attempt.endedAt = new Date(now()).toISOString(); attempt.endedMonoMs = mono();
                attempt.latencyMs = Math.max(0, attempt.endedMonoMs - startMono);
                item.httpElapsedMs += attempt.latencyMs;
                try { onEvent({ ...attempt, phase: 'complete' }); }
                catch (error) { throw stop('storage', error.message); }
            });
            // Resolve the serialized gate immediately after actual dispatch, not completion.
            return { pending };
        });
        gate = reservation.catch(() => {});
        const { pending } = await reservation;
        return pending;
    }
    return { run, stop, check, state, get stopped() { return stopped; }, get total() { return total; },
        get active() { return active; }, blockCount: block => blocks.get(block) || 0 };
}
async function schedule(arm, ids, work, shouldStop, runTaskPool, hooks = {}) {
    if (arm === 'B') {
        let position = 0;
        return runTaskPool({ concurrency: LIMITS.concurrency, shouldStop,
            nextTask: () => position === ids.length ? null : (() => { const id = ids[position++]; return { key: id, run: () => work(id) }; })(),
            onSettled: hooks.onSettled || (() => {}) });
    }
    if (arm !== 'A') throw new Error('Unknown scheduler arm');
    const counts = { started: 0, completed: 0, maxActive: 0 };
    for (let offset = 0; offset < ids.length && !shouldStop(); offset += LIMITS.concurrency) {
        const batch = ids.slice(offset, offset + LIMITS.concurrency);
        counts.started += batch.length; counts.maxActive = Math.max(counts.maxActive, batch.length);
        await Promise.allSettled(batch.map(async id => { try { return await work(id); } finally { counts.completed++; } }));
    }
    return counts;
}
function treeFiles(root, prefix = '') {
    return fs.readdirSync(path.join(root, prefix), { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))
        .flatMap(entry => entry.isDirectory() ? treeFiles(root, path.join(prefix, entry.name)) : [path.join(prefix, entry.name)]);
}
function treeHashes(root) { return Object.fromEntries(treeFiles(root).map(file => [file, sha256(fs.readFileSync(path.join(root, file)))])); }
function makeSeed(snapshot, outputDir, CatalogRegistry, now) {
    const seed = path.join(outputDir, 'seed'); fs.mkdirSync(seed);
    for (const product of snapshot.products) {
        const target = path.join(seed, product.path.slice(5));
        fs.mkdirSync(path.dirname(target), { recursive: true }); fs.writeFileSync(target, product.bytes);
    }
    const registry = new CatalogRegistry({ dataDir: seed, now }).bootstrap();
    const count = [...registry.shards.values()].reduce((sum, shard) => sum + Object.keys(shard.entries).length, 0);
    if (count !== LIMITS.products || snapshot.products.some(product => !registry.has(product.id))) throw new Error('Seed registry identity/count mismatch');
    return { root: seed, hashes: treeHashes(seed), registryRecords: count };
}
function historyPreserved(before, after, today) {
    if (String(before.id) !== String(after.id)) return false;
    for (const [name, entries] of Object.entries(before.variations)) {
        if (!Array.isArray(after.variations?.[name])) return false;
        for (const entry of entries.filter(entry => entry.date !== today)) {
            if (!after.variations[name].some(candidate => JSON.stringify(candidate) === JSON.stringify(entry))) return false;
        }
    }
    return true;
}
function metrics(values) {
    if (!values.length) return { count: 0, min: null, median: null, p90: null, max: null, spread: null };
    const sorted = values.slice().sort((a, b) => a - b);
    return { count: values.length, min: sorted[0], spread: sorted.at(-1) - sorted[0], median: sorted.length % 2 ? sorted[(sorted.length - 1) / 2] : (sorted[sorted.length / 2 - 1] + sorted[sorted.length / 2]) / 2,
        p90: sorted[Math.ceil(sorted.length * .9) - 1], max: sorted.at(-1) };
}
async function runComparison({ snapshot, outputDir, budgetFile, runtime, scraper, CatalogRegistry, runTaskPool,
    transport, now = Date.now, mono = () => performance.now(), wait = sleep,
    deadline = now() + LIMITS.runtimeMs - LIMITS.drainReserveMs,
    writeJson = atomicJson, eventWrite, onBlockReady = () => {}, onBlockDrained = () => {} }) {
    const initialBudget = JSON.parse(fs.readFileSync(budgetFile));
    if (initialBudget.requests !== 0 || initialBudget.priorEvidenceRequests !== PRIOR_EVIDENCE_REQUESTS ||
        initialBudget.accountingScope !== 'comparison-only') throw new Error('Comparison ledger is not fresh; resuming is forbidden');
    const startedMono = mono(), started = now(), cpuStart = process.cpuUsage();
    const report = { schemaVersion: 1, status: 'running', startedAt: new Date(started).toISOString(),
        sourceCommit: SOURCE_COMMIT, catalogCommit: CATALOG_COMMIT, limits: LIMITS,
        accountingScope: 'comparison-only', fullDayComplianceEstablished: false, priorEvidenceRequests: PRIOR_EVIDENCE_REQUESTS,
        manifestSha256: snapshot.manifestSha256, sample: snapshot.provenance,
        scopeNote: '40 fixed IDs and a 40-record registry. No discovery. This does not model the full-catalog registry shard-write cost.',
        blocks: [], stop: null, actualHttp: 0, chargedHttp: 0, prechargedWithoutDispatch: 0,
        legacyResume: { automatic: false, status: 'operator-review-required' }, pairedWallDifferencesMs: [] };
    const eventFile = path.join(outputDir, 'requests.jsonl');
    const events = [];
    const event = value => { (eventWrite || (value => fs.appendFileSync(eventFile, JSON.stringify(value) + '\n', { mode: 0o600 })))(value); events.push(value); };
    const flush = () => writeJson(path.join(outputDir, 'summary.json'), report);
    const gate = createStartGate({ now, mono, wait, deadline, expectedJstDay: initialBudget.date, onEvent: event,
        onStop: error => { report.stop ||= { ...errorInfo(error), observedAt: new Date(now()).toISOString() }; } });
    let currentBlock, client, seed, peakRss = process.memoryUsage().rss;
    const sampleResources = () => { peakRss = Math.max(peakRss, process.memoryUsage().rss); };
    const resourceTimer = setInterval(sampleResources, 100); resourceTimer.unref?.();
    const charged = new Map();
    const products = new Map(snapshot.products.map(product => [product.id, product]));
    try {
        gate.check();
        const warmupStarted = mono();
        const warmup = await scraper.scrapeProductDetails(snapshot.products[0].id, { get: async () => ({ status: 200,
            data: '<html><h2>Local parser warmup</h2><div class="variation-item"><span class="variation-name">standard</span><span class="variation-price">1000円</span></div></html>' }) });
        if (warmup.kind !== 'success') throw gate.stop('correctness', 'Offline parser warmup failed');
        report.parserWarmup = { mode: 'local-synthetic-html', networkRequests: 0, elapsedMs: mono() - warmupStarted };
        seed = makeSeed(snapshot, outputDir, CatalogRegistry, now);
        report.seedHashes = seed.hashes; report.registryRecordCount = seed.registryRecords;
        client = runtime.createRequestClient({ budgetFile, deadline, now, wait, dailyLimit: LIMITS.totalHttp,
            intervalMs: LIMITS.intervalMs, timeoutMs: LIMITS.timeoutMs, maxAttempts: LIMITS.maxAttempts, failureThreshold: 1, laneBudgets: true,
            get: (url, config) => {
                const match = /^\/(?:ja\/|en\/)?items\/([1-9]\d*)\/?$/.exec(decodeURIComponent(new URL(url).pathname));
                const id = match?.[1], item = currentBlock?.itemMap.get(id);
                if (!item) throw gate.stop('target', 'HTTP request is not a current fixed-workload item');
                return gate.run(currentBlock.index, item, url, config, transport);
            } });
        client.releaseLane('discovery');
        flush();
        for (const block of blockPlan(snapshot.products.map(product => product.id))) {
            gate.check();
            const blockStarted = mono(), blockCpu = process.cpuUsage();
            currentBlock = { ...block, startedAt: new Date(now()).toISOString(), status: 'running', items: [], itemMap: new Map(),
                wallMs: null, setupMs: null, chargedHttp: 0, actualHttp: 0, uniqueIds: 0,
                successes: 0, unavailable: 0, failures: 0, skippedAfterStop: 0, registryWriteMs: 0, peakRssBytes: process.memoryUsage().rss };
            const directory = path.join(outputDir, `block-${String(block.index).padStart(2, '0')}-${block.arm}`);
            fs.mkdirSync(directory); const dataDir = path.join(directory, 'data'); fs.cpSync(seed.root, dataDir, { recursive: true });
            const initialHashes = treeHashes(dataDir);
            if (JSON.stringify(initialHashes) !== JSON.stringify(seed.hashes)) throw gate.stop('correctness', 'Block did not start from the identical immutable snapshot');
            currentBlock.initialSnapshotSha256 = sha256(JSON.stringify(initialHashes));
            const registry = new CatalogRegistry({ dataDir, now }).bootstrap();
            currentBlock.setupMs = Math.max(0, mono() - blockStarted);
            currentBlock.schedulerEnteredMonoMs = mono();
            report.blocks.push(currentBlock);
            await onBlockReady({ block: currentBlock, dataDir, registry, seed });
            const work = async id => {
                const taskStarted = mono();
                const item = { id, kind: 'pending', httpAttempts: 0, httpElapsedMs: 0, pacingWaitMs: 0,
                    clientWaitMs: 0, parsingMs: 0, historySaveMs: 0, registryWriteMs: 0,
                    startedAt: new Date(now()).toISOString(), endedAt: null, taskWallMs: null };
                currentBlock.items.push(item); currentBlock.itemMap.set(id, item);
                const file = path.join(dataDir, id.slice(0, 3), `${id}.json`);
                try {
                    gate.check();
                    const before = mono();
                    let response;
                    try { response = await client.get(`https://booth.pm/ja/items/${id}`, { productId: id, onAttempt: () => {
                        gate.check();
                        const count = (charged.get(block.index) || 0) + 1;
                        charged.set(block.index, count);
                        if (count > LIMITS.blockHttp) throw gate.stop('http-budget', 'Block dispatch ceiling reached; retain the final conservative precharge without transmitting');
                        const budget = client.getBudget();
                        if (budget.requests !== [...charged.values()].reduce((sum, count) => sum + count, 0) || budget.requests > LIMITS.totalHttp) throw gate.stop('accounting', 'Shared client charge accounting mismatch');
                    } }); }
                    finally { item.clientWaitMs = Math.max(0, mono() - before - item.httpElapsedMs); }
                    // Responses already in flight may finish and checkpoint after a protective stop.
                    const parseStart = mono();
                    const parsed = await scraper.scrapeProductDetails(id, { get: async () => response });
                    item.parsingMs = Math.max(0, mono() - parseStart); item.finalStatus = response.status;
                    if (parsed.kind === 'failure' || !['success', 'unavailable'].includes(parsed.kind)) throw gate.stop('correctness', parsed.error?.message || 'Unknown parser outcome');
                    if (parsed.kind === 'success') {
                        if (String(parsed.product.id) !== id) throw gate.stop('correctness', 'Parsed identity mismatch');
                        const saveStart = mono();
                        await scraper.saveProductData(parsed.product, { dataDir, today: initialBudget.date });
                        item.historySaveMs = Math.max(0, mono() - saveStart);
                        const resultBytes = fs.readFileSync(file), saved = JSON.parse(resultBytes);
                        if (!historyPreserved(JSON.parse(products.get(id).bytes), saved, initialBudget.date)) throw gate.stop('correctness', 'Historical data changed unexpectedly');
                        item.savedSha256 = sha256(resultBytes);
                    } else if (sha256(fs.readFileSync(file)) !== products.get(id).sha256) throw gate.stop('correctness', 'Unavailable item history changed');
                    const registryStart = mono();
                    if (parsed.kind === 'success') registry.recordSuccess(id, now());
                    else registry.recordFailure(id, now(), { unavailable: true });
                    item.registryWriteMs = Math.max(0, mono() - registryStart);
                    item.kind = parsed.kind; currentBlock[parsed.kind === 'success' ? 'successes' : 'unavailable']++;
                } catch (error) {
                    item.error = errorInfo(error);
                    if (item.httpAttempts === 0 && gate.stopped) { item.kind = 'skipped-after-stop'; currentBlock.skippedAfterStop++; }
                    else { item.kind = 'failure'; currentBlock.failures++; }
                    gate.stop(error.reason || (['EIO', 'ENOSPC', 'EROFS', 'EMFILE', 'ENFILE'].includes(error.code) ? 'storage' : 'error'), error.message);
                } finally {
                    item.endedAt = new Date(now()).toISOString(); item.taskWallMs = Math.max(0, mono() - taskStarted);
                    sampleResources(); currentBlock.peakRssBytes = Math.max(currentBlock.peakRssBytes, process.memoryUsage().rss);
                }
            };
            currentBlock.scheduler = await schedule(block.arm, block.order, work, () => {
                if (gate.stopped) return true;
                try { gate.check(); client.check(); return false; }
                catch (error) { gate.stop(error.reason || 'error', error.message); return true; }
            }, runTaskPool);
            await onBlockDrained({ block: currentBlock });
            currentBlock.chargedHttp = charged.get(block.index) || 0;
            currentBlock.actualHttp = gate.blockCount(block.index);
            currentBlock.uniqueIds = new Set(currentBlock.items.filter(item => item.httpAttempts > 0).map(item => item.id)).size;
            currentBlock.registryWriteMs = currentBlock.items.reduce((sum, item) => sum + item.registryWriteMs, 0);
            currentBlock.finalDataHashes = treeHashes(dataDir);
            currentBlock.httpLatencyMs = metrics(events.filter(event => event.block === block.index && event.phase === 'complete').map(event => event.latencyMs));
            currentBlock.cpuUsageMicroseconds = process.cpuUsage(blockCpu);
            if (!gate.stopped && (currentBlock.items.length !== LIMITS.products || currentBlock.uniqueIds !== LIMITS.products ||
                currentBlock.successes + currentBlock.unavailable !== LIMITS.products || currentBlock.actualHttp !== currentBlock.chargedHttp)) gate.stop('correctness', 'Block completeness/accounting invariant failed');
            currentBlock.status = gate.stopped ? 'incomplete' : 'completed';
            delete currentBlock.itemMap;
            writeJson(path.join(directory, 'checkpoint.json'), currentBlock);
            const finalCheckpointMono = mono();
            currentBlock.schedulerThroughCheckpointMs = Math.max(0, finalCheckpointMono - currentBlock.schedulerEnteredMonoMs);
            currentBlock.wallMs = Math.max(0, finalCheckpointMono - blockStarted); // Includes all data/registry writes and checkpoint.
            const blockStarts = events.filter(event => event.block === block.index && event.phase === 'complete').map(event => event.startedMonoMs);
            currentBlock.firstHttpThroughCheckpointMs = blockStarts.length ? finalCheckpointMono - Math.min(...blockStarts) : null;
            currentBlock.httpStartSpanMs = blockStarts.length ? Math.max(...blockStarts) - Math.min(...blockStarts) : null;
            currentBlock.cpuUsageMicroseconds = process.cpuUsage(blockCpu);
            currentBlock.endedAt = new Date(now()).toISOString();
            writeJson(path.join(directory, 'result.json'), currentBlock); flush();
            if (gate.stopped) break;
        }
    } catch (error) { gate.stop(error.reason || (['EIO', 'ENOSPC', 'EROFS'].includes(error.code) ? 'storage' : 'error'), error.message); }
    finally {
        clearInterval(resourceTimer);
        await onBlockDrained({ block: currentBlock });
        if (client) {
            try { client.finish(); } catch (error) { gate.stop('storage', error.message); }
        }
        let budget;
        try {
            budget = JSON.parse(fs.readFileSync(budgetFile));
            // Retain stricter Retry-After observed by the transport even when the pinned
            // client's first-error circuit selects another cooldown while calls drain.
            if (gate.state.cooldownUntil > budget.blockedUntil) { budget.blockedUntil = gate.state.cooldownUntil; writeJson(budgetFile, budget); }
            report.budgetAfter = budget; report.chargedHttp = budget.requests;
        } catch (error) { gate.stop('storage', error.message); }
        report.actualHttp = gate.total; report.prechargedWithoutDispatch = Math.max(0, report.chargedHttp - gate.total);
        report.maxActiveHttp = gate.state.maxActive; report.httpLatencyMs = metrics(events.filter(event => event.phase === 'complete').map(event => event.latencyMs));
        report.pacingWaitMs = events.filter(event => event.phase === 'complete').reduce((sum, event) => sum + event.pacingWaitMs, 0);
        report.minStartSpacingMs = gate.state.starts.length > 1 ? Math.min(...gate.state.starts.slice(1).map((start, i) => start - gate.state.starts[i])) : null;
        report.cpuUsageMicroseconds = process.cpuUsage(cpuStart); report.peakRssBytes = Math.max(peakRss, process.memoryUsage().rss);
        report.elapsedMs = Math.max(0, mono() - startedMono); report.endedAt = new Date(now()).toISOString();
        if (seed && JSON.stringify(treeHashes(seed.root)) !== JSON.stringify(seed.hashes)) gate.stop('correctness', 'Immutable seed was modified');
        if (report.actualHttp > LIMITS.totalHttp || report.actualHttp > report.chargedHttp || report.maxActiveHttp > LIMITS.concurrency ||
            (report.minStartSpacingMs !== null && report.minStartSpacingMs < LIMITS.intervalMs) || gate.active !== 0) gate.stop('accounting', 'Final safety reconciliation failed');
        report.status = gate.stopped ? 'stopped' : report.blocks.length === LIMITS.blocks ? 'completed' : 'incomplete';
        report.stop = gate.stopped ? { ...errorInfo(gate.stopped), observedAt: new Date(gate.state.stoppedAt).toISOString() } : null;
        report.legacyResume.status = report.stop ? 'blocked-pending-operator-reconciliation' : 'operator-review-required';
        for (let pair = 1; pair <= LIMITS.pairs; pair++) {
            const blocks = report.blocks.filter(block => block.pair === pair), a = blocks.find(block => block.arm === 'A'), b = blocks.find(block => block.arm === 'B');
            report.pairedWallDifferencesMs.push({ pair, complete: blocks.length === 2 && blocks.every(block => block.status === 'completed'),
                aMs: a?.wallMs ?? null, bMs: b?.wallMs ?? null, bMinusAMs: a?.status === 'completed' && b?.status === 'completed' ? b.wallMs - a.wallMs : null,
                bOverA: a?.status === 'completed' && b?.status === 'completed' && a.wallMs > 0 ? b.wallMs / a.wallMs : null,
                schedulerAMs: a?.schedulerThroughCheckpointMs ?? null, schedulerBMs: b?.schedulerThroughCheckpointMs ?? null,
                schedulerBOverA: a?.status === 'completed' && b?.status === 'completed' && a.schedulerThroughCheckpointMs > 0 ? b.schedulerThroughCheckpointMs / a.schedulerThroughCheckpointMs : null,
                firstHttpBOverA: a?.status === 'completed' && b?.status === 'completed' && a.firstHttpThroughCheckpointMs > 0 ? b.firstHttpThroughCheckpointMs / a.firstHttpThroughCheckpointMs : null });
        }
        report.pairedRatioSummary = metrics(report.pairedWallDifferencesMs.filter(pair => pair.complete).map(pair => pair.bOverA));
        report.pairedDifferenceSummaryMs = metrics(report.pairedWallDifferencesMs.filter(pair => pair.complete).map(pair => pair.bMinusAMs));
        flush();
    }
    return report;
}

function parseArgs(argv) {
    const options = {};
    const flags = { '--repo': 'repo', '--manifest': 'manifest', '--snapshot-root': 'snapshotRoot', '--output-dir': 'outputDir',
        '--budget-file': 'budgetFile', '--expected-jst-day': 'expectedJstDay', '--exclusive-until': 'exclusiveUntil' };
    for (let i = 0; i < argv.length; i++) {
        if (argv[i] === '--execute') options.execute = true;
        else if (flags[argv[i]] && argv[i + 1] && !argv[i + 1].startsWith('--')) options[flags[argv[i]]] = argv[++i];
        else throw new Error(`Unknown or incomplete argument: ${argv[i]}`);
    }
    return options;
}
function supervise(child, outputDir, timeoutMs = LIMITS.runtimeMs, timers = { setTimeout, clearTimeout }) {
    const watchdog = timers.setTimeout(() => {
        try { atomicJson(path.join(outputDir, 'watchdog.json'), { status: 'watchdog-stop', outcome: 'unknown',
            resumeAllowed: false, message: 'Preserve the complete ledger, run lock and events; do not rerun or reset after an unknown outcome' }); }
        finally { child.kill('SIGKILL'); }
    }, timeoutMs);
    child.on('exit', (code, signal) => { timers.clearTimeout(watchdog); process.exitCode = signal ? 2 : code; });
    return watchdog;
}
async function executeWorker(options) {
    const locations = checkPaths(options);
    const authorization = validateRunner(options);
    if (git(locations.repo, ['rev-parse', 'HEAD']).trim() !== authorization.workflowCommit) throw new Error('Checkout HEAD must equal this workflow commit');
    const hashes = sourceHashes(locations.repo);
    const snapshot = readSnapshot(options.manifest, options.snapshotRoot, locations.repo);
    const lock = path.join(locations.outputDir, 'comparison.lock');
    fs.writeFileSync(lock, JSON.stringify({ runId: authorization.runId, sourceCommit: SOURCE_COMMIT, createdAt: new Date().toISOString(), resumeAllowed: false }), { flag: 'wx', mode: 0o600 });
    const budget = JSON.parse(fs.readFileSync(locations.budgetFile)); budget.runnerRunId = authorization.runId;
    atomicJson(locations.budgetFile, budget);
    const runtime = require(path.join(locations.repo, 'src/collection-runtime.js'));
    const scraper = require(path.join(locations.repo, 'src/scraper.js'));
    const { CatalogRegistry } = require(path.join(locations.repo, 'src/catalog-registry.js'));
    const { runTaskPool } = require(path.join(locations.repo, 'src/task-pool.js'));
    const axios = require(require.resolve('axios', { paths: [locations.repo] }));
    const startedAt = Number(process.env.BOOPA_COMPARISON_STARTED_AT);
    const bounds = runtimeBounds(startedAt, process.env);
    if (!Number.isFinite(startedAt) || Date.now() - startedAt >= LIMITS.runtimeMs - LIMITS.drainReserveMs) throw new Error('Watchdog start is unavailable or expired');
    let blockAgent;
    const https = require('node:https');
    const report = await runComparison({ snapshot, ...locations, runtime, scraper, CatalogRegistry, runTaskPool,
        transport: (url, config) => { if (!blockAgent) throw new Error('Missing block-local HTTPS agent'); return axios.get(url, { ...config, httpsAgent: blockAgent }); },
        onBlockReady: () => { if (blockAgent) throw new Error('Previous block connections were not drained');
            blockAgent = new https.Agent({ ...https.globalAgent.options, maxSockets: LIMITS.concurrency }); },
        onBlockDrained: () => { blockAgent?.destroy(); blockAgent = null; },
        deadline: Math.min(bounds.dispatchDeadline, authorization.exclusiveUntil - LIMITS.drainReserveMs) });
    report.runner = authorization; report.sourceSha256 = hashes;
    report.connectionInitialization = 'Fresh Node-default-options HTTPS agent for each block, maxSockets=5, destroyed after drain. No network warmup.';
    if (JSON.stringify(sourceHashes(locations.repo)) !== JSON.stringify(hashes) ||
        readSnapshot(options.manifest, options.snapshotRoot, locations.repo).manifestSha256 !== snapshot.manifestSha256) throw new Error('Source or snapshot changed during the comparison');
    atomicJson(path.join(locations.outputDir, 'summary.json'), report);
    atomicJson(path.join(locations.outputDir, 'completion.json'), { runId: authorization.runId, status: report.status, rerunAllowed: false });
    console.log(JSON.stringify({ status: report.status, stop: report.stop, actualHttp: report.actualHttp, chargedHttp: report.chargedHttp,
        priorEvidenceRequests: PRIOR_EVIDENCE_REQUESTS, pairedWallDifferencesMs: report.pairedWallDifferencesMs }));
    process.exitCode = report.status === 'completed' ? 0 : 2;
    // The lock is deliberately permanent, even on success: never restart this experiment.
}
async function main(options = parseArgs(process.argv.slice(2))) {
    if (!options.execute) {
        console.log(JSON.stringify({ mode: 'dry-run', networkRequests: 0, limits: LIMITS, sourceCommit: SOURCE_COMMIT,
            catalogCommit: CATALOG_COMMIT, repository: REPOSITORY, expectedRef: EXPECTED_REF, expectedWorkflow: EXPECTED_WORKFLOW,
            accountingScope: 'comparison-only', priorEvidenceRequests: PRIOR_EVIDENCE_REQUESTS, fullDayComplianceEstablished: false,
            pairArms: PAIR_ARMS, required: ['Explicit approval for this new 400-request comparison', 'An independently checked exclusive collection window',
                'Exactly 40 SHA256 and Git-blob verified histories', 'Fresh zero-count ledger and all outputs under RUNNER_TEMP outside checkout',
                'Expected branch/workflow first run number and first attempt only'] }, null, 2)); return;
    }
    checkPaths(options); validateRunner(options); sourceHashes(options.repo);
    const startedAt = Date.now();
    const bounds = runtimeBounds(startedAt);
    const child = fork(__filename, process.argv.slice(2), { env: { ...process.env, BOOPA_COMPARISON_WORKER: '1', BOOPA_COMPARISON_STARTED_AT: String(startedAt) },
        stdio: ['ignore', 'inherit', 'inherit', 'ipc'] });
    supervise(child, options.outputDir, bounds.hardDeadline - Date.now());
}
module.exports = { SOURCE_COMMIT, CATALOG_COMMIT, REPOSITORY, EXPECTED_REF, EXPECTED_WORKFLOW, PRIOR_EVIDENCE_REQUESTS,
    LIMITS, PAIR_ARMS, sourceHashes, readSnapshot, permutation, blockPlan, freshLedger, validateRunner, checkPaths,
    createStartGate, safeTarget, runtimeBounds, schedule, makeSeed, treeHashes, historyPreserved, metrics, runComparison, parseArgs, supervise, sha256, blobSha };
if (require.main === module) Promise.resolve().then(() => {
    const options = parseArgs(process.argv.slice(2));
    if (process.env.BOOPA_COMPARISON_WORKER === '1') {
        if (!options.execute || typeof process.send !== 'function') throw new Error('Worker requires supervised execution');
        return executeWorker(options);
    }
    return main(options);
}).catch(error => { console.error(plainText(error.message)); process.exitCode = 1; });
