'use strict';
require('./offline-only.cjs');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync, execFileSync } = require('node:child_process');
const test = require('node:test');
const { HOME, LIMITS, SOURCE_COMMIT, EXPECTED_RUNTIME_COMMIT, getPlan, loadHistory,
    validateExecution, validateRunnerContext, verifyPinnedRuntime, runProbe, jstDate } = require('./probe');
const { safeResponse, safeUrl, plainText } = require('./diagnostics');
const REPO = fs.realpathSync(process.env.BOOPA_REPO || path.join(HOME, '..', 'boopa'));
const runtime = require(path.join(REPO, 'src/collection-runtime.js'));
const scraper = require(path.join(REPO, 'src/scraper.js'));
const PLAN = getPlan(REPO);
const START = Date.parse('2026-10-05T01:00:00Z');
const HTML = '<h2>Offline test product</h2><div class="variation-item"><span class="variation-name">Default</span><b class="variation-price">500円</b></div>';
const SUCCESS = { status: 200, data: HTML, headers: {} };
const treeBefore = execFileSync('git', ['-C', REPO, 'diff', 'HEAD', '--binary']);

function fixture(t, { start = START, requests = 100, ids = PLAN.selected } = {}) {
    const root = fs.mkdtempSync(path.join(HOME, 'mock-test-'));
    t.after(() => fs.rmSync(root, { recursive: true, force: true }));
    const budgetFile = path.join(root, 'budget.json');
    const budget = { date: jstDate(start), requests, blockedUntil: 0,
        accountingScope: 'full-day', knownScope: 'all-collectors-jst-day' };
    fs.writeFileSync(budgetFile, JSON.stringify(budget));
    const outputDir = path.join(root, 'output');
    fs.mkdirSync(outputDir);
    let clock = start;
    let calls = 0;
    const starts = [];
    const authorization = { budgetFile, budget, expectedJstDay: budget.date,
        accountingScope: 'full-day', knownScope: 'all-collectors-jst-day',
        exclusiveUntil: start + LIMITS.hardRuntimeMs + 10000,
        allowance: Math.min(LIMITS.maxHttpAttempts, LIMITS.dailyLimit - requests) };
    return { root, budgetFile, outputDir, authorization, starts,
        calls: () => calls, now: () => clock, set: time => { clock = time; },
        run: async (get = async () => SUCCESS, overrides = {}) => runProbe({
            plan: { ...PLAN, selected: ids }, authorization, outputDir, runtime, scraper,
            readHistory: selected => JSON.stringify({ id: selected.id, name: 'Offline history',
                variations: { Default: [{ date: '2026-10-04', price: 100, is_sale: false }] } }),
            now: () => clock, mono: () => clock - start,
            wait: async ms => { clock += ms; },
            transport: async (url, config) => {
                calls++;
                starts.push(clock);
                return get(url, config, calls);
            }, ...overrides
        }) };
}

test('default dry run and import have no network, ledger creation, or run-directory side effects', () => {
    const entriesBefore = fs.readdirSync(HOME).sort();
    const env = { ...process.env, BOOPA_REPO: REPO,
        NODE_OPTIONS: `--require=${path.join(HOME, 'offline-only.cjs')}` };
    const dry = spawnSync(process.execPath, [path.join(HOME, 'probe.js')], { env, encoding: 'utf8' });
    assert.equal(dry.status, 0, dry.stderr);
    const result = JSON.parse(dry.stdout);
    assert.equal(result.mode, 'dry-run');
    assert.equal(result.networkRequests, 0);
    assert.equal(result.quotaVerified, false);
    assert.equal(result.selected.length, 10);
    assert.equal(result.catalogSourceCommit, SOURCE_COMMIT);
    const imported = spawnSync(process.execPath, ['-e', `require(${JSON.stringify(path.join(HOME, 'probe.js'))})`], { env, encoding: 'utf8' });
    assert.equal(imported.status, 0, imported.stderr);
    assert.equal(imported.stdout, '');
    assert.deepEqual(fs.readdirSync(HOME).sort(), entriesBefore);
});

test('live CLI fails closed without ledger, expected day, or verified window', () => {
    const missing = spawnSync(process.execPath, [path.join(HOME, 'probe.js'), '--execute'], {
        env: { ...process.env, NODE_OPTIONS: `--require=${path.join(HOME, 'offline-only.cjs')}` }, encoding: 'utf8' });
    assert.equal(missing.status, 1);
    assert.match(missing.stderr, /requires an existing/);
});

test('missing/corrupt/exhausted/wrong-day/cooldown/reserved ledgers fail closed', t => {
    const f = fixture(t);
    const options = { budgetFile: f.budgetFile, expectedJstDay: jstDate(START), repo: REPO,
        exclusiveUntil: new Date(START + LIMITS.hardRuntimeMs + 1000).toISOString() };
    assert.equal(validateExecution(options, START).allowance, 20);
    assert.throws(() => validateExecution({ ...options, budgetFile: path.join(f.root, 'missing') }, START), /ENOENT/);
    assert.throws(() => validateExecution({ ...options, expectedJstDay: '2026-10-04' }, START), /JST day/);
    fs.writeFileSync(f.budgetFile, '{broken');
    assert.throws(() => validateExecution(options, START), /JSON/);
    for (const patch of [{ requests: -1 }, { requests: 48000 }, { date: '2026-10-04' },
        { blockedUntil: START + 1000 }, { reservation: { completed: false } }, { blockedUntil: null }]) {
        fs.writeFileSync(f.budgetFile, JSON.stringify({ ...f.authorization.budget, ...patch }));
        assert.throws(() => validateExecution(options, START), /Ledger/);
    }
});

test('exclusive-window expiry and upcoming JST rollover reject execution', t => {
    const f = fixture(t);
    const options = { budgetFile: f.budgetFile, expectedJstDay: jstDate(START), repo: REPO,
        exclusiveUntil: new Date(START + LIMITS.hardRuntimeMs - 1).toISOString() };
    assert.throws(() => validateExecution(options, START), /exclusive window/);
    const almostMidnight = Date.parse('2026-10-05T14:59:59Z');
    assert.throws(() => validateExecution({ ...options, exclusiveUntil: new Date(almostMidnight + 400000).toISOString() }, almostMidnight), /JST day/);
});

test('success parses received bytes only and saves isolated historical copies', async t => {
    const f = fixture(t);
    const result = await f.run();
    assert.equal(result.status, 'completed');
    assert.equal(f.calls(), 10);
    assert.equal(result.actualHttpAttempts, 10);
    assert.equal(result.chargedAttempts, 10);
    assert.equal(result.maxActiveHttp, 1);
    assert.ok(f.starts.slice(1).every((time, i) => time - f.starts[i] >= 1000));
    assert.ok(result.items.every(item => item.kind === 'success' && item.savedSha256 && item.parsingElapsedMs >= 0 && item.saveElapsedMs >= 0));
    for (const item of result.items) {
        const saved = JSON.parse(fs.readFileSync(path.join(f.outputDir, 'data', item.id.slice(0, 3), `${item.id}.json`)));
        assert.equal(String(saved.id), item.id);
        assert.ok(JSON.stringify(saved).includes('2026-10-05'));
    }
});

test('20-attempt ceiling counts redirects and transient retries together', async t => {
    const f = fixture(t);
    const counts = new Map();
    const result = await f.run(async url => {
        const id = new URL(url).pathname.split('/').at(-1);
        const count = (counts.get(id) || 0) + 1;
        counts.set(id, count);
        if (count === 1) return { status: 302, headers: { location: `https://test-shop.booth.pm/items/${id}` } };
        if (count === 2) return { status: 503, headers: {} };
        return SUCCESS;
    });
    assert.equal(result.actualHttpAttempts, 20);
    assert.equal(f.calls(), 20);
    assert.equal(result.chargedAttempts, 20);
    assert.equal(result.stop.reason, 'request-budget');
    assert.ok(result.redirects > 0);
    assert.ok(f.starts.slice(1).every((time, i) => time - f.starts[i] >= 1000));
});

for (const status of [403, 429]) test(`HTTP ${status} stops all subsequent IDs and retains cooldown`, async t => {
    const f = fixture(t);
    const result = await f.run(async () => ({ status, headers: { 'retry-after': '120' } }));
    assert.equal(f.calls(), 1);
    assert.equal(result.actualHttpAttempts, 1);
    assert.equal(result.stop.reason, status === 403 ? 'forbidden' : 'rate-limit');
    assert.ok(result.budgetAfter.blockedUntil >= START + (status === 403 ? 21600000 : 120000));
});

test('timeout is bounded and stops after two failed attempts', async t => {
    const f = fixture(t);
    const result = await f.run(async (url, config) => {
        assert.equal(config.maxRedirects, 0);
        assert.ok(config.timeout > 0 && config.timeout <= 30000);
        assert.ok(config.signal instanceof AbortSignal);
        f.set(f.now() + config.timeout);
        const error = new Error('offline simulated timeout');
        error.code = 'ETIMEDOUT';
        throw error;
    });
    assert.equal(f.calls(), 2);
    assert.equal(result.stop.reason, 'circuit-breaker');
    assert.ok(result.elapsedMs < LIMITS.workRuntimeMs);
});

test('JST rollover after durable charge but before transport starts sends no HTTP', async t => {
    const f = fixture(t, { start: Date.parse('2026-10-05T14:59:59.900Z') });
    const original = runtime.createRequestClient;
    const crossingRuntime = { ...runtime, createRequestClient: options => original({ ...options,
        get: (url, config) => { f.set(Date.parse('2026-10-05T15:00:00Z')); return options.get(url, config); } }) };
    const result = await f.run(undefined, { runtime: crossingRuntime });
    assert.equal(f.calls(), 0);
    assert.equal(result.actualHttpAttempts, 0);
    assert.equal(result.chargedAttempts, 1); // Deliberately not refunded.
    assert.equal(result.stop.reason, 'day-boundary');
});

test('exclusive window expiring after charge blocks actual transport', async t => {
    const f = fixture(t);
    const original = runtime.createRequestClient;
    const expiredRuntime = { ...runtime, createRequestClient: options => original({ ...options,
        get: (url, config) => { f.set(f.authorization.exclusiveUntil); return options.get(url, config); } }) };
    const result = await f.run(undefined, { runtime: expiredRuntime });
    assert.equal(f.calls(), 0);
    assert.equal(result.chargedAttempts, 1);
    assert.equal(result.stop.reason, 'deadline');
});

for (const kind of ['midnight', 'deadline']) test(`${kind} during final pre-request log write blocks transport and preserves charge`, async t => {
    const f = fixture(t);
    const result = await f.run(undefined, { writeReport: (file, report) => {
        fs.writeFileSync(file, JSON.stringify(report));
        if (report.preloggedAttempts === 1 && report.actualHttpAttempts === 0) {
            f.set(kind === 'midnight' ? Date.parse('2026-10-05T15:00:00Z') : START + LIMITS.workRuntimeMs);
        }
    } });
    assert.equal(f.calls(), 0);
    assert.equal(result.actualHttpAttempts, 0);
    assert.equal(result.preloggedAttempts, 1);
    assert.equal(result.chargedAttempts, 1);
    assert.equal(result.stop.reason, 'deadline'); // Midnight is also beyond this run's time limit.
    const events = fs.readFileSync(path.join(f.outputDir, 'requests.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
    assert.equal(events.at(-1).transportInvoked, false);
});

test('nondefault HTTPS port is rejected before redirected transport', async t => {
    const f = fixture(t);
    const result = await f.run(async url => ({ status: 302, headers: { location: url.replace('booth.pm/', 'booth.pm:8443/') } }));
    assert.equal(f.calls(), 1);
    assert.equal(result.stop.reason, 'target');
});

test('wrong-product redirect never reaches transport and no new IDs are accepted', async t => {
    const f = fixture(t);
    const result = await f.run(async () => ({ status: 302, headers: { location: 'https://booth.pm/ja/items/999999999999' } }));
    assert.equal(f.calls(), 1);
    assert.equal(result.stop.reason, 'redirect');
});

test('daily remainder smaller than 20 is honored', async t => {
    const f = fixture(t, { requests: 47998 });
    const result = await f.run();
    assert.equal(f.calls(), 2);
    assert.equal(result.budgetAfter.requests, 48000);
    assert.equal(result.stop.reason, 'request-budget');
});

test('incremental exception requires explicit matching scope and probe-only labels', t => {
    const f = fixture(t);
    const options = { budgetFile: f.budgetFile, expectedJstDay: jstDate(START), repo: REPO,
        exclusiveUntil: new Date(START + LIMITS.hardRuntimeMs + 1000).toISOString(),
        accountingScope: 'incremental-exception' };
    assert.throws(() => validateExecution(options, START), /scope/);
    for (const labels of [{}, { accountingScope: 'incremental-exception' },
        { knownScope: 'probe-only' }, { accountingScope: 'incremental-exception', knownScope: 'all-collectors-jst-day' }]) {
        fs.writeFileSync(f.budgetFile, JSON.stringify({ date: jstDate(START), requests: 0, blockedUntil: 0, ...labels }));
        assert.throws(() => validateExecution(options, START), /scope/);
    }
    fs.writeFileSync(f.budgetFile, JSON.stringify({ date: jstDate(START), requests: 0, blockedUntil: 0,
        accountingScope: 'incremental-exception', knownScope: 'probe-only' }));
    assert.throws(() => validateExecution({ ...options, accountingScope: undefined }, START), /scope/);
    const verified = validateExecution(options, START);
    assert.equal(verified.allowance, 20);
    assert.equal(verified.fullDayComplianceEstablished, false);
});

test('exception cap counts only remaining probe charges and never claims daily compliance', async t => {
    const f = fixture(t, { requests: 18 });
    const budget = { date: jstDate(START), requests: 18, blockedUntil: 0,
        accountingScope: 'incremental-exception', knownScope: 'probe-only' };
    fs.writeFileSync(f.budgetFile, JSON.stringify(budget));
    const authorization = validateExecution({ budgetFile: f.budgetFile,
        expectedJstDay: jstDate(START), repo: REPO, accountingScope: 'incremental-exception',
        exclusiveUntil: new Date(START + LIMITS.hardRuntimeMs + 1000).toISOString() }, START);
    const result = await f.run(undefined, { authorization });
    assert.equal(f.calls(), 2);
    assert.equal(result.budgetAfter.requests, 20);
    assert.equal(result.accounting.fullDayComplianceEstablished, false);
    assert.equal(result.accounting.knownScope, 'probe-only');
    assert.equal(result.stop.reason, 'request-budget');
    assert.equal(result.legacyResume.automatic, false);
    assert.match(result.legacyResume.status, /blocked/);
});

test('exception dry run prominently discloses unknown legacy aggregate', () => {
    const result = spawnSync(process.execPath, [path.join(HOME, 'probe.js'), '--accounting-scope', 'incremental-exception'], {
        env: { ...process.env, NODE_OPTIONS: `--require=${path.join(HOME, 'offline-only.cjs')}` }, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    const plan = JSON.parse(result.stdout);
    assert.equal(plan.mode, 'dry-run');
    assert.equal(plan.accounting.fullDayComplianceEstablished, false);
    assert.match(plan.accounting.notice, /legacy daily usage is unknown/);
    assert.equal(plan.networkRequests, 0);
});

test('429 Retry-After beyond the nominal window blocks legacy resumption', async t => {
    const f = fixture(t);
    const result = await f.run(async () => ({ status: 429, headers: { 'retry-after': '7200' } }));
    assert.equal(result.budgetAfter.blockedUntil, START + 7200000);
    assert.ok(result.budgetAfter.blockedUntil > f.authorization.exclusiveUntil);
    assert.equal(result.legacyResume.status, 'blocked-pending-operator-reconciliation');
    assert.equal(result.legacyResume.automatic, false);
});

test('all history snapshots are required before any HTTP or ledger charge', async t => {
    const f = fixture(t);
    const result = await f.run(undefined, { readHistory: selected => {
        if (selected === PLAN.selected.at(-1)) throw new Error('Missing archived history');
        return JSON.stringify({ id: selected.id, variations: {} });
    } });
    assert.equal(f.calls(), 0);
    assert.equal(result.actualHttpAttempts, 0);
    assert.equal(result.chargedAttempts, 0);
    assert.match(result.stop.message, /Missing archived history/);
});

test('isolated history cache is verified against the source Git blob hash', t => {
    const f = fixture(t);
    const selected = PLAN.selected.at(-1);
    const cache = path.join(f.root, 'cache');
    const file = path.join(cache, selected.file);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const supplied = fs.readFileSync(path.join(HOME, 'history-cache', selected.file));
    fs.writeFileSync(file, supplied);
    assert.equal(loadHistory(PLAN, selected, cache), supplied.toString('utf8'));
    fs.appendFileSync(file, '\n');
    assert.throws(() => loadHistory(PLAN, selected, cache), /hash mismatch/);
});

const RUNNER_ENV = { GITHUB_ACTIONS: 'true', GITHUB_RUN_ATTEMPT: '1', GITHUB_RUN_ID: '123456789',
    GITHUB_REPOSITORY: 'MametaroGG/booth-vrc-price-tracker' };
const PRIOR = JSON.parse(fs.readFileSync(path.join(HOME, 'prior-ledger.json')));
function runnerAuthorization(overrides = {}) {
    return { accountingScope: 'incremental-exception', allowance: 18,
        budget: { ...structuredClone(PRIOR), ...overrides } };
}

test('runner requires first attempt, expected repository, and original ledger state', () => {
    assert.equal(validateRunnerContext(runnerAuthorization(), RUNNER_ENV).maximumAdditionalRequests, 18);
    for (const environment of [{}, { ...RUNNER_ENV, GITHUB_RUN_ATTEMPT: '2' },
        { ...RUNNER_ENV, GITHUB_RUN_ATTEMPT: '01' }, { ...RUNNER_ENV, GITHUB_REPOSITORY: 'other/repo' }]) {
        assert.throws(() => validateRunnerContext(runnerAuthorization(), environment), /first run_attempt/);
    }
    for (const patch of [{ requests: 0 }, { requests: 1 }, { blockedUntil: 0 },
        { date: '2026-10-06' }, { laneUsage: { refresh: 0, discovery: 0 } },
        { laneReleased: { refresh: false, discovery: false } }, { laneUsage: undefined }]) {
        assert.throws(() => validateRunnerContext(runnerAuthorization(patch), RUNNER_ENV), /authoritative/);
    }
    assert.throws(() => validateRunnerContext(runnerAuthorization({ runnerRunId: '9999' }), RUNNER_ENV), /another GitHub run/);
});

test('runner starting at prior 2 charges allows at most 18 additional including redirects/retries', async t => {
    const start = PRIOR.blockedUntil + 1000;
    const f = fixture(t, { start, requests: 2 });
    fs.writeFileSync(f.budgetFile, JSON.stringify(PRIOR));
    const authorization = validateExecution({ budgetFile: f.budgetFile,
        expectedJstDay: PRIOR.date, repo: REPO, accountingScope: 'incremental-exception',
        exclusiveUntil: new Date(start + LIMITS.hardRuntimeMs + 1000).toISOString() }, start);
    validateRunnerContext(authorization, RUNNER_ENV);
    const counts = new Map();
    const result = await f.run(async url => {
        const id = new URL(url).pathname.split('/').at(-1);
        const count = (counts.get(id) || 0) + 1;
        counts.set(id, count);
        if (count === 1) return { status: 302, headers: { location: `https://shop.booth.pm/items/${id}` } };
        if (count === 2) return { status: 503, headers: { 'content-type': 'text/plain' }, data: 'Temporary service error' };
        return SUCCESS;
    }, { authorization });
    assert.equal(f.calls(), 18);
    assert.equal(result.actualHttpAttempts, 18);
    assert.equal(result.chargedAttempts, 18);
    assert.equal(result.budgetAfter.requests, 20);
    assert.equal(result.budgetAfter.blockedUntil, PRIOR.blockedUntil);
    assert.deepEqual(result.budgetAfter.laneReleased, PRIOR.laneReleased);
    assert.equal(result.accounting.fullDayComplianceEstablished, false);
});

test('pinned PR source contents are checked while a test-only descendant HEAD is permitted', () => {
    const readGit = (repo, args) => {
        if (args[0] === 'merge-base') {
            assert.deepEqual(args, ['merge-base', '--is-ancestor', EXPECTED_RUNTIME_COMMIT, 'HEAD']);
            return ''; // Model the test-branch child of the pinned PR.
        }
        return execFileSync('git', ['--no-lazy-fetch', '-C', repo, ...args], {
            encoding: 'utf8', env: { ...process.env, GIT_NO_LAZY_FETCH: '1', GIT_ALLOW_PROTOCOL: '' } });
    };
    assert.equal(verifyPinnedRuntime(REPO, readGit), EXPECTED_RUNTIME_COMMIT);
    assert.throws(() => verifyPinnedRuntime(REPO, (repo, args) => args[0] === 'rev-parse' && args[1].includes(':') ? 'changed source' : readGit(repo, args)), /differs from/);
});

test('502 diagnostics retain only bounded safe response metadata', async t => {
    const f = fixture(t);
    const body = '<html><style>secret-style</style><h1>502 Bad Gateway</h1><p>Intermediary could not reach upstream</p></html>';
    const result = await f.run(async () => ({ status: 502, data: body, headers: {
        'content-type': 'text/html; charset=utf-8', server: 'edge-gateway', via: '1.1 gateway', 'x-cache': 'MISS',
        'retry-after': '1', 'set-cookie': 'DO-NOT-RETAIN', authorization: 'Bearer DO-NOT-RETAIN', 'x-private': 'DO-NOT-RETAIN' } }));
    assert.equal(result.actualHttpAttempts, 2);
    const events = fs.readFileSync(path.join(f.outputDir, 'requests.jsonl'), 'utf8');
    assert.ok(!events.includes('DO-NOT-RETAIN'));
    const completed = events.trim().split('\n').map(JSON.parse).find(item => item.phase === 'complete');
    assert.deepEqual(completed.responseMetadata.headers, { 'content-type': 'text/html; charset=utf-8',
        server: 'edge-gateway', via: '1.1 gateway', 'x-cache': 'MISS', 'retry-after': '1' });
    assert.equal(completed.responseMetadata.errorBodyPrefix, '502 Bad Gateway Intermediary could not reach upstream');
    assert.equal(completed.responseMetadata.status, 502);
});

test('diagnostics omit credentials, cookies, tokens, unsafe body types, and URL queries', () => {
    for (const body of ['Authorization: Bearer secret', 'token=short-secret', 'Cookie: sid=secret', 'password: password123']) {
        assert.match(safeResponse({ status: 502, headers: { 'content-type': 'text/plain' }, data: body }).errorBodyPrefix, /omitted/);
    }
    assert.ok(!plainText('Diagnostic abcdefghijklmnopqrstuvwxyz123456789').includes('abcdefghijklmnopqrstuvwxyz'));
    assert.equal(plainText('A'.repeat(1000)).length <= 512, true);
    assert.equal(safeUrl('https://username:password@booth.pm/ja/items/1000657?token=secret#secret'), 'https://booth.pm/ja/items/1000657');
    assert.match(safeResponse({ status: 502, headers: { 'content-type': 'application/json' }, data: '{"token":"secret"}' }).errorBodyPrefix, /omitted/);
    assert.equal(safeResponse({ status: 200, headers: { 'content-type': 'text/plain' }, data: 'token=secret' }).errorBodyPrefix, null);
});

test('repository tracked contents remain unchanged after all offline checks', () => {
    assert.deepEqual(execFileSync('git', ['-C', REPO, 'diff', 'HEAD', '--binary']), treeBefore);
});
