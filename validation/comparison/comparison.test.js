'use strict';
require('./offline-only.cjs');
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { EventEmitter } = require('node:events');
const c = require('./comparison');
const REPO = process.env.BOOPA_REPO || process.env.GITHUB_WORKSPACE || process.cwd();
const runtime = require(path.join(REPO, 'src/collection-runtime.js'));
const scraper = require(path.join(REPO, 'src/scraper.js'));
const { CatalogRegistry } = require(path.join(REPO, 'src/catalog-registry.js'));
const { runTaskPool } = require(path.join(REPO, 'src/task-pool.js'));
const START = Date.parse('2026-10-05T07:00:00Z');
const HTML = '<html><h2>Fixture product</h2><div class="variation-item"><div class="variation-name">standard</div><div class="variation-price">1000円</div><button data-product-variant="fixture1"></button></div></html>';
const SUCCESS = { status: 200, data: HTML, headers: { 'content-type': 'text/html' } };
class VirtualClock {
    constructor(start = START) { this.time = start; this.queue = []; this.scheduled = false; }
    now = () => this.time;
    mono = () => this.time - START;
    wait = ms => new Promise(resolve => {
        this.queue.push({ at: this.time + ms, resolve });
        if (!this.scheduled) { this.scheduled = true; setImmediate(() => this.advance()); }
    });
    advance() {
        if (!this.queue.length) { this.scheduled = false; return; }
        const at = Math.min(...this.queue.map(task => task.at)); this.time = Math.max(this.time, at);
        const ready = this.queue.filter(task => task.at <= this.time); this.queue = this.queue.filter(task => task.at > this.time);
        ready.forEach(task => task.resolve());
        setImmediate(() => this.advance());
    }
}
function fixture(t) {
    const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'boopa-comparison-test-'));
    t.after(() => fs.rmSync(outputDir, { recursive: true, force: true }));
    const budgetFile = path.join(outputDir, 'working-ledger.json');
    fs.writeFileSync(budgetFile, JSON.stringify(c.freshLedger(runtime.jstDate(START))));
    const products = Array.from({ length: 40 }, (_, index) => {
        const id = String(1000000 + index);
        const bytes = Buffer.from(JSON.stringify({ id, name: 'Original name', variations: { standard: [
            { date: '2026-09-01', price: 900, is_sale: false }, { date: '2026-10-01', price: 1100, is_sale: false } ] } }));
        return { id, bytes, path: `data/${id.slice(0, 3)}/${id}.json`, sha256: c.sha256(bytes), git_blob_sha: c.blobSha(bytes) };
    });
    const snapshot = { products, manifestSha256: 'a'.repeat(64), provenance: { sampleCount: 40, populationCount: 195040 } };
    const clock = new VirtualClock(); let count = 0;
    const calls = [];
    return { outputDir, budgetFile, snapshot, clock, calls, run: (transport, options = {}) => c.runComparison({ snapshot, outputDir, budgetFile,
        runtime, scraper, CatalogRegistry, runTaskPool, now: clock.now, mono: clock.mono, wait: clock.wait,
        transport: async (url, config) => { calls.push({ url, time: clock.now(), config }); count++;
            if (transport) return transport(url, config, count, clock);
            await clock.wait(650); return SUCCESS;
        }, ...options }) };
}
const ENV = { GITHUB_ACTIONS: 'true', GITHUB_REPOSITORY: c.REPOSITORY, GITHUB_REF: c.EXPECTED_REF,
    GITHUB_RUN_ATTEMPT: '1', GITHUB_RUN_NUMBER: '1', GITHUB_RUN_ID: '123456789', GITHUB_SHA: 'b'.repeat(40),
    GITHUB_WORKFLOW_REF: `${c.REPOSITORY}/${c.EXPECTED_WORKFLOW}@${c.EXPECTED_REF}` };
function auth(f) { return { budgetFile: f.budgetFile, expectedJstDay: runtime.jstDate(START), exclusiveUntil: new Date(START + c.LIMITS.runtimeMs + 1000).toISOString() }; }

test('dry run and import are inert with the network disabled', () => {
    const result = spawnSync(process.execPath, ['--require', path.join(__dirname, 'offline-only.cjs'), path.join(__dirname, 'comparison.js')], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr); const plan = JSON.parse(result.stdout);
    assert.equal(plan.networkRequests, 0); assert.equal(plan.priorEvidenceRequests, 12); assert.equal(plan.limits.totalHttp, 400);
    assert.equal(plan.fullDayComplianceEstablished, false);
    const imported = spawnSync(process.execPath, ['--require', path.join(__dirname, 'offline-only.cjs'), '-e', `require(${JSON.stringify(path.join(__dirname, 'comparison.js'))})`], { encoding: 'utf8' });
    assert.equal(imported.status, 0); assert.equal(imported.stdout, '');
});
test('reviewed runtime source pins and forty archive hashes verify offline', () => {
    assert.equal(Object.keys(c.sourceHashes(REPO)).length, 7);
    const root = process.env.BOOPA_SNAPSHOT || path.join(__dirname, 'snapshot');
    const snapshot = c.readSnapshot(path.join(root, 'manifest.json'), root, REPO);
    assert.equal(snapshot.products.length, 40); assert.equal(snapshot.provenance.populationCount, 195040);
});
test('pair order AB BA BA AB and reproducible distinct per-pair permutations', () => {
    const ids = Array.from({ length: 40 }, (_, i) => String(1000000 + i)); const plan = c.blockPlan(ids);
    assert.equal(plan.map(block => block.arm).join(''), 'ABBABAAB');
    for (let i = 0; i < 8; i += 2) {
        assert.deepEqual(plan[i].order, plan[i + 1].order); assert.equal(new Set(plan[i].order).size, 40);
        assert.deepEqual(plan[i].order.slice().sort(), ids.slice().sort());
    }
    assert.equal(new Set(plan.filter((_, index) => index % 2 === 0).map(block => block.order.join(','))).size, 4);
    assert.deepEqual(plan, c.blockPlan(ids));
});
test('runner refuses wrong repo/ref/workflow, subsequent run/attempt, stale day and existing ledger', t => {
    const f = fixture(t); assert.equal(c.validateRunner(auth(f), ENV, START).runId, ENV.GITHUB_RUN_ID);
    for (const patch of [{ GITHUB_RUN_ATTEMPT: '2' }, { GITHUB_RUN_NUMBER: '2' }, { GITHUB_REF: 'refs/heads/main' },
        { GITHUB_REPOSITORY: 'other/repository' }, { GITHUB_WORKFLOW_REF: 'other-workflow' }]) assert.throws(() => c.validateRunner(auth(f), { ...ENV, ...patch }, START), /Expected repository/);
    assert.throws(() => c.validateRunner({ ...auth(f), expectedJstDay: '2026-10-04' }, ENV, START), /JST day/);
    assert.throws(() => c.validateRunner({ ...auth(f), exclusiveUntil: new Date(START + 1000).toISOString() }, ENV, START), /exclusive window/);
    for (const patch of [{ requests: 1 }, { runnerRunId: ENV.GITHUB_RUN_ID }, { priorEvidenceRequests: 0 }, { accountingScope: 'daily' },
        { fullDayComplianceEstablished: true }, { blockedUntil: START + 1 }, { reservation: {} }]) {
        fs.writeFileSync(f.budgetFile, JSON.stringify({ ...c.freshLedger(runtime.jstDate(START)), ...patch }));
        assert.throws(() => c.validateRunner(auth(f), ENV, START), /fresh authorized/);
    }
});
test('outputs require a fresh directory under RUNNER_TEMP outside checkout', t => {
    const f = fixture(t); const options = { repo: REPO, outputDir: f.outputDir, budgetFile: f.budgetFile };
    assert.equal(c.checkPaths(options, { RUNNER_TEMP: os.tmpdir() }).outputDir, f.outputDir);
    fs.writeFileSync(path.join(f.outputDir, 'comparison.lock'), 'unknown');
    assert.throws(() => c.checkPaths(options, { RUNNER_TEMP: os.tmpdir() }), /empty regular/);
});
test('20-minute watchdog and job setup headroom are bounded and fail closed', () => {
    assert.deepEqual(c.runtimeBounds(START, {}, START), { dispatchDeadline: START + 1165000, hardDeadline: START + 1200000 });
    assert.deepEqual(c.runtimeBounds(START + 60000, { COMPARISON_JOB_STARTED_AT: new Date(START).toISOString() }, START + 60000),
        { dispatchDeadline: START + 1110000, hardDeadline: START + 1140000 });
    assert.throws(() => c.runtimeBounds(START + 1120000, { COMPARISON_JOB_STARTED_AT: new Date(START).toISOString() }, START + 1120000), /consumed/);
});
test('supervisor kills once and leaves durable unknown-outcome refusal', t => {
    const f = fixture(t), child = new EventEmitter(); let callback, killed = 0, cleared = 0;
    child.kill = signal => { assert.equal(signal, 'SIGKILL'); killed++; };
    c.supervise(child, f.outputDir, 1200000, { setTimeout: (fn, ms) => { assert.equal(ms, 1200000); callback = fn; return 99; }, clearTimeout: id => { assert.equal(id, 99); cleared++; } });
    callback(); assert.equal(killed, 1); const record = JSON.parse(fs.readFileSync(path.join(f.outputDir, 'watchdog.json')));
    assert.equal(record.resumeAllowed, false); assert.equal(record.outcome, 'unknown');
    child.emit('exit', 0, null); assert.equal(cleared, 1);
});
test('all eight blocks complete forty IDs with identical seed and shared global pacing', async t => {
    const f = fixture(t); const result = await f.run();
    assert.equal(result.status, 'completed', JSON.stringify(result.stop)); assert.equal(f.calls.length, 320);
    assert.equal(result.actualHttp, 320); assert.equal(result.chargedHttp, 320); assert.equal(result.prechargedWithoutDispatch, 0);
    assert.equal(result.registryRecordCount, 40); assert.equal(result.priorEvidenceRequests, 12); assert.equal(result.budgetAfter.requests, 320);
    assert.equal(result.blocks.length, 8); assert.equal(new Set(result.blocks.map(block => block.initialSnapshotSha256)).size, 1);
    assert.ok(result.maxActiveHttp <= 5); assert.ok(result.maxActiveHttp >= 2);
    assert.ok(result.minStartSpacingMs >= 500); assert.ok(f.calls.slice(1).every((call, i) => call.time - f.calls[i].time >= 500));
    assert.ok(result.blocks.every(block => block.uniqueIds === 40 && block.actualHttp === 40 && block.successes === 40 && block.status === 'completed'));
    assert.ok(result.blocks.every(block => block.items.every(item => item.savedSha256 && item.parsingMs >= 0 && item.historySaveMs >= 0 && item.registryWriteMs >= 0)));
    assert.equal(result.pairedWallDifferencesMs.length, 4); assert.ok(result.pairedWallDifferencesMs.every(pair => pair.complete && pair.bOverA > 0));
    assert.ok(result.blocks.every(block => block.wallMs >= block.firstHttpThroughCheckpointMs && block.firstHttpThroughCheckpointMs >= block.httpStartSpanMs));
    assert.ok(result.peakRssBytes > 0); assert.ok(result.cpuUsageMicroseconds.user >= 0);
    assert.equal(result.legacyResume.automatic, false);
    const events = fs.readFileSync(path.join(f.outputDir, 'requests.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
    assert.equal(events.length, 640); assert.ok(events.filter(event => event.phase === 'complete').every(event => event.startedAt && event.endedAt && event.latencyMs >= 0 && event.startSpacingMs >= 500 || event.sequence === 1));
});
test('barrier holds next batch while actual runTaskPool refills a free slot', async () => {
    const ids = Array.from({ length: 10 }, (_, i) => String(i));
    async function run(arm) {
        const clock = new VirtualClock(), starts = new Map();
        const counts = await c.schedule(arm, ids, async id => { starts.set(id, clock.now()); await clock.wait(id === '0' ? 10000 : 100); }, () => false, runTaskPool);
        assert.equal(counts.maxActive, 5); return starts;
    }
    const a = await run('A'), b = await run('B'); assert.equal(a.get('5'), START + 10000); assert.equal(b.get('5'), START + 100);
});
test('one actual-start gate honors 50/block and 400 aggregate, including follow-ups', async () => {
    const clock = new VirtualClock(), events = []; let calls = 0;
    const gate = c.createStartGate({ now: clock.now, mono: clock.mono, wait: clock.wait, deadline: START + 1000000, onEvent: value => events.push(value) });
    const item = { id: '1234567', httpAttempts: 0, pacingWaitMs: 0, httpElapsedMs: 0 };
    for (let block = 1; block <= 8; block++) for (let count = 0; count < 50; count++) await gate.run(block, item,
        `https://booth.pm/ja/items/${item.id}`, { maxRedirects: 0, timeout: 30000 }, async () => { calls++; return SUCCESS; });
    assert.equal(gate.total, 400); assert.equal(calls, 400); assert.equal(gate.blockCount(1), 50);
    await assert.rejects(gate.run(9, item, `https://booth.pm/ja/items/${item.id}`, { maxRedirects: 0 }, async () => { calls++; return SUCCESS; }), /ceiling/);
    assert.equal(calls, 400);
    const second = c.createStartGate({ now: clock.now, mono: clock.mono, wait: clock.wait, deadline: clock.now() + 1000000 });
    for (let count = 0; count < 50; count++) await second.run(1, item, `https://booth.pm/ja/items/${item.id}`, { maxRedirects: 0 }, async () => SUCCESS);
    await assert.rejects(second.run(1, item, `https://booth.pm/ja/items/${item.id}`, { maxRedirects: 0 }, async () => SUCCESS), /ceiling/);
    assert.equal(second.total, 50);
});
test('actual gate rejects concurrency above five and drains existing requests', async () => {
    const clock = new VirtualClock(), pending = [], gate = c.createStartGate({ now: clock.now, mono: clock.mono, wait: clock.wait, deadline: START + 1000000 });
    const item = { id: '1234567', httpAttempts: 0, pacingWaitMs: 0, httpElapsedMs: 0 };
    const calls = Array.from({ length: 6 }, () => gate.run(1, item, `https://booth.pm/ja/items/${item.id}`, { maxRedirects: 0 }, () => new Promise(resolve => pending.push(resolve))));
    calls.forEach(call => call.catch(() => {}));
    while (pending.length < 5 || !gate.stopped) await new Promise(resolve => setImmediate(resolve));
    assert.equal(gate.total, 5); assert.equal(gate.state.maxActive, 5); assert.equal(gate.stopped.reason, 'concurrency');
    pending.forEach(resolve => resolve(SUCCESS)); await Promise.allSettled(calls); assert.equal(gate.active, 0);
});
for (const status of [404, 410]) test(`${status} is unavailable, preserves complete original history and continues`, async t => {
    const f = fixture(t), unavailable = f.snapshot.products[0];
    const result = await f.run(async url => url.includes(unavailable.id) ? { status, data: '', headers: {} } : SUCCESS);
    assert.equal(result.status, 'completed'); assert.equal(result.actualHttp, 320);
    assert.ok(result.blocks.every(block => block.unavailable === 1 && block.successes === 39));
    for (const block of result.blocks) assert.equal(c.sha256(fs.readFileSync(path.join(f.outputDir, `block-${String(block.index).padStart(2, '0')}-${block.arm}`, unavailable.path))), unavailable.sha256);
});
for (const status of [403, 429, 500, 502, 400]) test(`first ${status} stops all new dispatches without retry`, async t => {
    const f = fixture(t);
    const result = await f.run(async () => ({ status, data: 'Failure', headers: { 'retry-after': '7200', 'content-type': 'text/plain' } }));
    assert.equal(result.status, 'stopped'); assert.equal(f.calls.length, 1); assert.equal(result.actualHttp, 1); assert.equal(result.blocks.length, 1);
    assert.ok(result.budgetAfter.blockedUntil >= START + (status === 403 ? 21600000 : 7200000));
    assert.equal(result.legacyResume.status, 'blocked-pending-operator-reconciliation');
});
test('timeout stops once with finite timeout/signal and no retry', async t => {
    const f = fixture(t); const result = await f.run(async (url, config) => {
        assert.equal(config.maxRedirects, 0); assert.ok(config.signal instanceof AbortSignal); assert.ok(config.timeout > 0 && config.timeout <= 30000);
        throw Object.assign(new Error('Simulated timeout'), { code: 'ETIMEDOUT' });
    });
    assert.equal(result.stop.reason, 'timeout'); assert.equal(f.calls.length, 1);
});
test('in-flight requests drain and late 403 preserves the maximum cooldown', async t => {
    const f = fixture(t); const result = await f.run(async (url, config, count, clock) => {
        if (count === 1) { await clock.wait(3000); return { status: 429, headers: { 'retry-after': '3600' } }; }
        if (count === 2) { await clock.wait(3500); return { status: 403, headers: { 'retry-after': '40000' } }; }
        await clock.wait(5000); return SUCCESS;
    });
    assert.equal(result.status, 'stopped'); assert.equal(result.actualHttp, 5); assert.equal(result.maxActiveHttp, 5);
    assert.ok(f.calls.every(call => call.time < Date.parse(result.stop.observedAt)));
    assert.ok(result.budgetAfter.blockedUntil >= START + 4000 + 40000000); assert.equal(result.blocks[0].successes, 3);
});
test('safe same-product redirects retain exact accounting, global pacing and trailing slash', async t => {
    const f = fixture(t); const result = await f.run(async url => url.startsWith('https://booth.pm/') && url.includes(f.snapshot.products[0].id)
        ? { status: 302, headers: { location: `https://fixture-shop.booth.pm/items/${f.snapshot.products[0].id}/` } } : SUCCESS);
    assert.equal(result.status, 'completed', JSON.stringify(result.stop)); assert.equal(result.actualHttp, 328); assert.equal(result.chargedHttp, 328);
    assert.ok(result.blocks.every(block => block.actualHttp === 41)); assert.ok(result.minStartSpacingMs >= 500);
});
for (const location of ['https://evil.example/items/1234567', 'https://booth.pm:8443/ja/items/1234567', 'http://booth.pm/ja/items/1234567', 'https://booth.pm/ja/items/9999999'])
    test(`unsafe redirect stops before following: ${location}`, async t => {
        const f = fixture(t); const result = await f.run(async () => ({ status: 302, headers: { location } }));
        assert.equal(result.stop.reason, 'unexpected-redirect'); assert.equal(result.actualHttp, 1);
    });
test('fourth safe redirect stops before fifth HTTP and never retries', async t => {
    const f = fixture(t); const result = await f.run(async url => ({ status: 302, headers: { location: url } }));
    assert.equal(result.status, 'stopped'); assert.equal(result.stop.reason, 'unexpected-redirect');
    assert.ok(Math.max(...result.blocks[0].items.map(item => item.httpAttempts)) <= 4); assert.ok(result.actualHttp <= 20);
});
test('malformed markup is a correctness stop with no further HTTP', async t => {
    const f = fixture(t); const result = await f.run(async () => ({ status: 200, data: '<h1>No item</h1>', headers: {} }));
    assert.equal(result.status, 'stopped'); assert.equal(result.stop.reason, 'correctness'); assert.equal(result.actualHttp, 1);
});
test('storage failure in history save stops and preserves original snapshot', async t => {
    const f = fixture(t); const result = await f.run(undefined, { scraper: { ...scraper, saveProductData: async () => { throw Object.assign(new Error('Disk is full'), { code: 'ENOSPC' }); } } });
    assert.equal(result.status, 'stopped'); assert.equal(result.stop.reason, 'storage'); assert.ok(result.actualHttp <= 2);
    assert.equal(new Set(result.blocks.map(block => block.initialSnapshotSha256)).size, 1);
});
test('completion telemetry storage failure cannot erase a 403 cooldown', async t => {
    const f = fixture(t); let failed = false;
    const result = await f.run(async () => ({ status: 403, headers: {} }), { eventWrite: event => {
        if (event.phase === 'complete' && !failed) { failed = true; throw Object.assign(new Error('Telemetry disk failure'), { code: 'EIO' }); }
    } });
    assert.equal(result.status, 'stopped'); assert.equal(result.actualHttp, 1); assert.ok(result.budgetAfter.blockedUntil >= START + 21600000);
});
test('deadline crossing during pre-dispatch durable write blocks HTTP but retains charge', async t => {
    const f = fixture(t); const deadline = START + 1000;
    const result = await f.run(undefined, { deadline, eventWrite: event => { if (event.phase === 'pre-dispatch') f.clock.time = deadline; } });
    assert.equal(result.status, 'stopped'); assert.equal(result.actualHttp, 0); assert.equal(result.chargedHttp, 1); assert.equal(result.stop.reason, 'watchdog');
});
test('safe diagnostics never retain sensitive headers or authentication body text', async t => {
    const f = fixture(t); const result = await f.run(async () => ({ status: 502, data: 'Authorization: Bearer secret', headers: {
        'content-type': 'text/plain', server: 'edge', 'set-cookie': 'privatecookie', authorization: 'Bearer private', 'x-private': 'privatevalue' } }));
    assert.equal(result.actualHttp, 1);
    const events = fs.readFileSync(path.join(f.outputDir, 'requests.jsonl'), 'utf8');
    assert.ok(!events.includes('privatecookie') && !events.includes('privatevalue') && !events.includes('Bearer secret'));
    assert.match(events, /potentially sensitive diagnostic text/);
});

test('real pinned client and safe redirects never transmit above the per-block ceiling', async t => {
    const f = fixture(t); const result = await f.run(async url => url.startsWith('https://booth.pm/')
        ? { status: 302, headers: { location: url.replace('https://booth.pm/', 'https://fixture-shop.booth.pm/') } } : SUCCESS);
    assert.equal(result.status, 'stopped'); assert.equal(result.stop.reason, 'http-budget');
    assert.equal(result.actualHttp, 50); assert.equal(f.calls.length, 50); assert.equal(result.blocks.length, 1);
    assert.ok(result.chargedHttp >= 50); assert.equal(result.chargedHttp - result.actualHttp, result.prechargedWithoutDispatch);
    assert.equal(result.blocks[0].chargedHttp, result.chargedHttp);
});
test('scheduler wall includes final history, registry, and checkpoint writes', async t => {
    const f = fixture(t); let releases = 0;
    const result = await f.run(async () => SUCCESS, { scraper: { ...scraper, saveProductData: async (...args) => {
        f.clock.time += 5; return scraper.saveProductData(...args);
    } }, writeJson: (file, value) => { if (file.endsWith('checkpoint.json')) f.clock.time += 17; fs.writeFileSync(file, JSON.stringify(value)); },
    onBlockReady: () => { releases++; }, onBlockDrained: () => {} });
    assert.equal(result.status, 'completed'); assert.equal(releases, 8);
    assert.ok(result.blocks.every(block => block.items.every(item => item.historySaveMs >= 5)));
    assert.ok(result.blocks.every(block => block.schedulerThroughCheckpointMs >= block.httpStartSpanMs + 17));
});
test('clock rollback and broken wait cannot bypass the actual start gate', async () => {
    const clock = new VirtualClock(); let starts = 0;
    const gate = c.createStartGate({ now: clock.now, mono: clock.mono, wait: clock.wait, deadline: START + 10000 });
    const item = { id: '1234567', httpAttempts: 0, pacingWaitMs: 0, httpElapsedMs: 0 };
    await gate.run(1, item, 'https://booth.pm/ja/items/1234567', { maxRedirects: 0 }, async () => { starts++; return SUCCESS; });
    clock.time -= 100;
    await gate.run(2, item, 'https://booth.pm/ja/items/1234567', { maxRedirects: 0 }, async () => { starts++; return SUCCESS; });
    assert.equal(starts, 2); assert.ok(gate.state.starts[1] - gate.state.starts[0] >= 500);
});

test('real forty-product immutable archive completes all 320 offline parse/save/registry operations', async t => {
    const f = fixture(t), root = process.env.BOOPA_SNAPSHOT || path.join(__dirname, 'snapshot');
    const snapshot = c.readSnapshot(path.join(root, 'manifest.json'), root, REPO);
    const result = await f.run(async () => SUCCESS, { snapshot });
    assert.equal(result.status, 'completed', JSON.stringify(result.stop)); assert.equal(result.actualHttp, 320);
    assert.equal(result.registryRecordCount, 40);
    const historyHashes = result.blocks.map(block => Object.fromEntries(Object.entries(block.finalDataHashes).filter(([file]) => !file.startsWith('crawl_registry/'))));
    assert.ok(historyHashes.every(hashes => JSON.stringify(hashes) === JSON.stringify(historyHashes[0])));
    assert.equal(c.readSnapshot(path.join(root, 'manifest.json'), root, REPO).manifestSha256, snapshot.manifestSha256);
});
test('registry persistence failure stops the entire experiment after in-flight drain', async t => {
    const f = fixture(t);
    class FailingRegistry extends CatalogRegistry { recordSuccess() { throw Object.assign(new Error('Registry storage unavailable'), { code: 'EIO' }); } }
    const result = await f.run(async () => SUCCESS, { CatalogRegistry: FailingRegistry });
    assert.equal(result.status, 'stopped'); assert.equal(result.stop.reason, 'storage'); assert.equal(result.actualHttp, 1); assert.equal(result.blocks.length, 1);
});
test('safe cache metadata is retained without private or opaque response headers', () => {
    const { safeResponse } = require('./diagnostics');
    const result = safeResponse({ status: 200, headers: { age: '120', 'cache-control': 'public, max-age=60', 'cf-cache-status': 'HIT',
        'x-cache': 'MISS', 'cf-ray': 'opaque-private-ray', 'set-cookie': 'secret' } });
    assert.deepEqual(result.headers, { 'x-cache': 'MISS', age: '120', 'cache-control': 'public, max-age=60', 'cf-cache-status': 'HIT' });
});
