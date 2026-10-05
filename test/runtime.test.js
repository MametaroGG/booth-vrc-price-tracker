const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const {
    CollectionStop, DAILY_REQUEST_LIMIT, REQUEST_INTERVAL_MS, createRequestClient, getStopTargetTime, jstDate,
    reserveDailyAllowance, retryAfterMs, writeJson
} = require('../src/collection-runtime');

const START = Date.parse('2026-10-04T14:32:00Z'); // 23:32 JST, after the old 23:30 cutoff.
const ok = () => ({ status: 200, data: 'ok' });
function httpError(status, headers = {}) {
    return Object.assign(new Error(`HTTP ${status}`), { response: { status, headers } });
}
function fixture(t, options = {}) {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'boopa-runtime-'));
    t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
    let time = START;
    const waits = [];
    const calls = [];
    const budgetFile = path.join(dir, 'request_budget.json');
    writeJson(budgetFile, { date: jstDate(START), requests: 0, blockedUntil: 0 });
    const makeClient = (overrides = {}) => createRequestClient({
        budgetFile,
        deadline: START + 5 * 3600000,
        intervalMs: 300, // Exercise configurable spacing; the production default is tested separately.
        now: () => time,
        wait: async ms => { waits.push(ms); time += ms; },
        get: async (url, config) => { calls.push({ url, config, time }); return ok(); },
        ...options,
        ...overrides
    });
    return { budgetFile, makeClient, calls, waits, now: () => time, setTime: value => { time = value; } };
}

test('delayed 23:32 JST start receives five hours regardless of the next cron', () => {
    assert.equal(getStopTargetTime(START).toISOString(), '2026-10-04T19:32:00.000Z');
    assert.equal(getStopTargetTime(START, '2026-10-04T14:16:19Z').getTime(), START + 5 * 3600000);
});

test('long setup is included in the six-hour job limit with a 30-minute save reserve', () => {
    assert.equal(getStopTargetTime(START, START - 3600000).getTime(), START + 4.5 * 3600000);
    assert.throws(() => getStopTargetTime(START, 'bad timestamp'), /Invalid/);
    assert.throws(() => getStopTargetTime(START, START + 1), /Invalid/);
});

test('transient failures use bounded exponential backoff and every retry consumes budget', async t => {
    let calls = 0;
    const f = fixture(t);
    const client = f.makeClient({ get: async () => { if (++calls < 3) throw httpError(503); return ok(); } });
    assert.equal((await client.get('https://booth.pm/a')).status, 200);
    assert.deepEqual(f.waits, [1500, 3000]);
    assert.equal(client.getBudget().requests, 3);
    assert.equal(JSON.parse(fs.readFileSync(f.budgetFile)).requests, 3);
});

test('retry exhaustion is a failure after three total attempts', async t => {
    const f = fixture(t);
    const client = f.makeClient({ get: async () => { throw httpError(502); } });
    await assert.rejects(client.get('https://booth.pm/a'), /HTTP 502/);
    assert.equal(client.getBudget().requests, 3);
});

test('daily cap is shared by concurrent requests and persists across client restarts', async t => {
    const f = fixture(t, { dailyLimit: 3 });
    const client = f.makeClient();
    const results = await Promise.allSettled(Array.from({ length: 8 }, () => client.get('https://booth.pm/a')));
    assert.equal(results.filter(result => result.status === 'fulfilled').length, 3);
    assert.equal(f.calls.length, 3);
    assert.deepEqual(f.calls.map(call => call.time - START), [0, 300, 600]);
    const second = f.makeClient();
    await assert.rejects(second.get('https://booth.pm/a'), error => error.reason === 'request-budget');
    assert.equal(f.calls.length, 3);
});

test('retry requests cannot exceed the shared daily budget', async t => {
    const f = fixture(t);
    const client = f.makeClient({ dailyLimit: 2, get: async () => { throw httpError(500); } });
    await assert.rejects(client.get('https://booth.pm/a'), error => error.reason === 'request-budget');
    assert.equal(client.getBudget().requests, 2);
});

test('429 stops the run, honors Retry-After, and blocks queued and restarted requests', async t => {
    const f = fixture(t);
    let calls = 0;
    const get = async () => { calls++; throw httpError(429, { 'retry-after': '900' }); };
    const client = f.makeClient({ get });
    const results = await Promise.allSettled(Array.from({ length: 5 }, () => client.get('https://booth.pm/a')));
    assert.equal(calls, 1);
    assert.equal(results.every(result => result.status === 'rejected'), true);
    assert.ok(client.getBudget().blockedUntil >= START + 900000);
    await assert.rejects(f.makeClient({ get }).get('https://booth.pm/a'), error => error.reason === 'cooldown');
    assert.equal(calls, 1);
    f.setTime(client.getBudget().blockedUntil);
    await f.makeClient().get('https://booth.pm/a');
    assert.equal(f.calls.length, 1);
});

test('Retry-After supports dates and never retries immediately on missing/invalid/zero values', () => {
    assert.equal(retryAfterMs('Mon, 05 Oct 2026 02:00:00 GMT', START), Date.parse('2026-10-05T02:00:00Z') - START);
    for (const value of [null, '', 'invalid', '0', '-1']) assert.equal(retryAfterMs(value, START), 60000);
});

test('403 stops without retry and persists a six-hour cooldown', async t => {
    const f = fixture(t);
    const client = f.makeClient({ get: async () => { throw httpError(403); } });
    await assert.rejects(client.get('https://booth.pm/a'), error => error.reason === 'forbidden');
    assert.equal(client.getBudget().requests, 1);
    assert.equal(client.getBudget().blockedUntil, START + 6 * 3600000);
});

test('transient failure circuit stops later requests', async t => {
    const f = fixture(t);
    const client = f.makeClient({ get: async () => { throw httpError(503); } });
    await assert.rejects(client.get('https://booth.pm/a'), /HTTP 503/);
    await assert.rejects(client.get('https://booth.pm/b'), error => error.reason === 'circuit-breaker');
    await assert.rejects(client.get('https://booth.pm/c'), error => error.reason === 'circuit-breaker');
    assert.equal(client.getBudget().requests, 5);
});

test('404/410 are explicit unavailable results and other permanent errors are not retried', async t => {
    for (const status of [404, 410, 401]) {
        const f = fixture(t);
        const client = f.makeClient({ get: async () => { throw httpError(status); } });
        if (status === 401) await assert.rejects(client.get('https://booth.pm/a'), /401/);
        else assert.equal((await client.get('https://booth.pm/a')).status, status);
        assert.equal(client.getBudget().requests, 1);
    }
});

test('deadline prevents requests and retries, and timeout is bounded by remaining collection time', async t => {
    const f = fixture(t);
    await assert.rejects(f.makeClient({ deadline: START }).get('https://booth.pm/a'), error => error.reason === 'deadline');
    assert.equal(f.calls.length, 0);
    await f.makeClient({ deadline: START + 700 }).get('https://booth.pm/a');
    assert.equal(f.calls[0].config.timeout, 700);
    assert.ok(f.calls[0].config.signal instanceof AbortSignal);
    const client = f.makeClient({ deadline: START + 1000, get: async () => { throw httpError(503); } });
    await assert.rejects(client.get('https://booth.pm/a'), error => error.reason === 'deadline');
    assert.equal(f.waits.length, 0);
});

test('normal requests have a 30-second timeout and automatic redirects disabled', async t => {
    const f = fixture(t);
    await f.makeClient().get('https://booth.pm/a');
    assert.equal(f.calls[0].config.timeout, 30000);
    assert.equal(f.calls[0].config.maxRedirects, 0);
});

test('every allowed redirect is paced and budgeted; non-BOOTH redirects fail', async t => {
    const f = fixture(t);
    const urls = [];
    const client = f.makeClient({ get: async url => {
        urls.push(url);
        return urls.length === 1 ? { status: 302, headers: { location: 'https://shop.booth.pm/items/1' } } : ok();
    } });
    await client.get('https://booth.pm/ja/items/1');
    assert.deepEqual(urls, ['https://booth.pm/ja/items/1', 'https://shop.booth.pm/items/1']);
    assert.equal(client.getBudget().requests, 2);
    const bad = f.makeClient({ get: async () => ({ status: 302, headers: { location: 'https://example.com' } }) });
    await assert.rejects(bad.get('https://booth.pm/a'), error => error.reason === 'redirect');
});

test('JST midnight requires a new reservation and preserves the server cooldown', async t => {
    const f = fixture(t);
    writeJson(f.budgetFile, { date: '2026-10-04', requests: 48000, blockedUntil: START + 2 * 3600000 });
    f.setTime(Date.parse('2026-10-04T15:00:00Z'));
    const client = f.makeClient();
    await assert.rejects(client.get('https://booth.pm/a'), error => error.reason === 'cooldown');
    assert.throws(() => reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'paused', now: f.now() }), /Requests paused/);
    f.setTime(START + 2 * 3600000);
    await assert.rejects(client.get('https://booth.pm/a'), error => error.reason === 'day-boundary');
    reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'new-day', now: f.now() });
    const next = f.makeClient({ reservationId: 'new-day' });
    await next.get('https://booth.pm/a');
    next.finish();
    assert.equal(next.getBudget().date, '2026-10-05');
    assert.equal(next.getBudget().requests, 1);
    assert.equal(jstDate(Date.parse('2026-10-04T14:59:59Z')), '2026-10-04');
});

test('corrupt/malformed/future budget cannot silently grant fresh allowance', t => {
    const f = fixture(t);
    for (const budget of [{ requests: -1 }, { date: '2026-10-04', requests: -1, blockedUntil: 0 }]) {
        writeJson(f.budgetFile, budget);
        assert.throws(() => f.makeClient(), /Invalid request budget/);
    }
    fs.writeFileSync(f.budgetFile, '{bad json');
    assert.throws(() => f.makeClient(), SyntaxError);
    writeJson(f.budgetFile, { date: '2026-10-06', requests: 1, blockedUntil: 0 });
    assert.throws(() => f.makeClient().check(), /future/);
});

test('durable reservations bound each run and all retries, refunding unused allowance only at finish', async t => {
    const f = fixture(t);
    const reservation = reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'run-1', now: START });
    assert.equal(reservation.limit, 48000);
    const client = f.makeClient({ reservationId: 'run-1' });
    await client.get('https://booth.pm/a');
    assert.equal(client.getBudget().requests, 48000);
    assert.equal(client.getBudget().reservation.used, 1);
    client.finish();
    assert.equal(client.getBudget().requests, 1);
    assert.equal(client.getBudget().reservation.completed, true);
    assert.equal(reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'run-2', now: START }).limit, 47999);
});

test('lost final checkpoint fails closed instead of replenishing quota, including the next day', t => {
    const f = fixture(t);
    reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'lost-run', now: START });
    for (const now of [START, START + 24 * 3600000]) {
        assert.throws(() => reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'next-run', now }), /unresolved/);
    }
    assert.throws(() => f.makeClient({ reservationId: 'different-run' }), /Missing active/);
});

test('last daily reservation is clamped to remaining quota and resumes count correctly', async t => {
    const f = fixture(t);
    writeJson(f.budgetFile, { date: jstDate(START), requests: 47998, blockedUntil: 0 });
    assert.equal(reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'last', now: START }).limit, 2);
    const client = f.makeClient({ reservationId: 'last' });
    await client.get('https://booth.pm/a');
    await client.get('https://booth.pm/b');
    await assert.rejects(client.get('https://booth.pm/c'), error => error.reason === 'request-budget');
    client.finish();
    assert.equal(client.getBudget().requests, 48000);
    assert.equal(reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'empty', now: START }).limit, 0);
});

test('a reserved run stops at JST midnight instead of borrowing unreserved next-day quota', async t => {
    const f = fixture(t);
    reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'midnight', now: START });
    const client = f.makeClient({ reservationId: 'midnight' });
    f.setTime(Date.parse('2026-10-04T15:00:00Z'));
    await assert.rejects(client.get('https://booth.pm/a'), error => error.reason === 'day-boundary');
    client.finish();
    assert.equal(reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'next-day', now: f.now() }).limit, 48000);
});

test('cooldown blocks quota reservations as well as requests', t => {
    const f = fixture(t);
    writeJson(f.budgetFile, { date: jstDate(START), requests: 1, blockedUntil: START + 60000 });
    assert.throws(() => reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'blocked', now: START }), /Requests paused/);
});

test('first deployment cannot add unmeasured traffic to the current JST day', t => {
    const f = fixture(t);
    fs.unlinkSync(f.budgetFile);
    assert.equal(reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'bootstrap', now: START }).limit, 0);
    f.makeClient({ reservationId: 'bootstrap' }).finish();
    assert.equal(reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'new-day', now: START + 24 * 3600000 }).limit, 48000);
});

test('403 respects a Retry-After longer than the default six-hour pause', async t => {
    const f = fixture(t);
    const client = f.makeClient({ get: async () => { throw httpError(403, { 'retry-after': '86400' }); } });
    await assert.rejects(client.get('https://booth.pm/a'), error => error.reason === 'forbidden');
    assert.equal(client.getBudget().blockedUntil, START + 24 * 60 * 60 * 1000);
});

test('terminal responses break consecutive transient failure streaks', async t => {
    const f = fixture(t);
    let calls = 0;
    const client = f.makeClient({ get: async () => { throw httpError(++calls % 2 ? 500 : 404); } });
    for (let i = 0; i < 6; i++) assert.equal((await client.get('https://booth.pm/a')).status, 404);
    assert.equal(client.getBudget().requests, 12);
});

test('finishing a client is terminal and cannot spend refunded quota', async t => {
    const f = fixture(t);
    reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'finish', now: START });
    const client = f.makeClient({ reservationId: 'finish' });
    await client.get('https://booth.pm/a');
    client.finish();
    await assert.rejects(client.get('https://booth.pm/b'), error => error.reason === 'finished');
    client.finish();
    assert.equal(f.calls.length, 1);
    assert.equal(client.getBudget().requests, 1);
});

test('calendar-invalid budget dates fail closed', t => {
    const f = fixture(t);
    for (const date of ['0000-00-00', '2026-02-30', '2026-13-01']) {
        writeJson(f.budgetFile, { date, requests: 48000, blockedUntil: 0 });
        assert.throws(() => f.makeClient(), /Invalid request budget/);
    }
});

test('one job can use more than 10,000 requests within the approved remaining daily allowance', async t => {
    const f = fixture(t);
    const reservation = reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'long-run', now: START });
    assert.equal(reservation.limit, 48000);
    const persisted = JSON.parse(fs.readFileSync(f.budgetFile));
    persisted.reservation.used = 10000;
    writeJson(f.budgetFile, persisted);
    const client = f.makeClient({ reservationId: 'long-run' });
    await client.get('https://booth.pm/a');
    assert.equal(client.getBudget().reservation.used, 10001);
    client.finish();
    assert.equal(client.getBudget().requests, 10001);
    assert.equal(reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'following-run', now: START }).limit, 37999);
});

test('a lost zero-allowance run recovers automatically because it could not send requests', t => {
    const f = fixture(t);
    fs.unlinkSync(f.budgetFile);
    assert.equal(reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'bootstrap-crash', now: START }).limit, 0);
    assert.equal(reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'next-day', now: START + 24 * 3600000 }).limit, 48000);
});

test('operator-reconciled abandoned quota stays charged and never lowers a verified cooldown', t => {
    const f = fixture(t);
    reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'abandoned', now: START });
    const budget = JSON.parse(fs.readFileSync(f.budgetFile));
    // Recovery procedure after confirming the old job ended and reviewing logs:
    // keep requests/limit/used unchanged, close the reservation, preserve cooldown.
    budget.reservation.completed = true;
    budget.blockedUntil = START + 60000;
    writeJson(f.budgetFile, budget);
    assert.throws(() => reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'too-soon', now: START }), /Requests paused/);
    assert.equal(JSON.parse(fs.readFileSync(f.budgetFile)).requests, 48000);
    assert.equal(reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'same-day', now: START + 60000 }).limit, 0);
    assert.equal(reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'fresh-day', now: START + 24 * 3600000 }).limit, 48000);
});

test('default pacing preserves a simultaneous five-request batch while persisting every start', async t => {
    const f = fixture(t);
    const releases = [];
    const persisted = [];
    const client = f.makeClient({ intervalMs: undefined, get: () => {
        persisted.push(JSON.parse(fs.readFileSync(f.budgetFile)).requests);
        return new Promise(resolve => releases.push(() => resolve(ok())));
    } });
    const batch = Array.from({ length: 5 }, () => client.get('https://booth.pm/a'));
    // The start gate must release before an HTTP response completes, so all five
    // requests can be in flight together as in the original scraper.
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(REQUEST_INTERVAL_MS, 0);
    assert.equal(releases.length, 5);
    assert.deepEqual(persisted, [1, 2, 3, 4, 5]);
    assert.deepEqual(f.waits, []);
    releases.forEach(release => release());
    await Promise.all(batch);
});

test('concurrent search and detail requests share the full remaining allowance', async t => {
    const f = fixture(t);
    writeJson(f.budgetFile, { date: jstDate(START), requests: 47990, blockedUntil: 0 });
    reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'near-cap', now: START });
    const client = f.makeClient({ reservationId: 'near-cap', intervalMs: undefined });
    assert.equal(client.remaining(), 10);
    const results = await Promise.allSettled(Array.from({ length: 30 }, (_, index) =>
        client.get(index % 2 ? 'https://booth.pm/ja/items/1' : 'https://booth.pm/ja/search')));
    assert.equal(results.filter(result => result.status === 'fulfilled').length, 10);
    assert.equal(f.calls.length, 10);
    assert.equal(client.remaining(), 0);
    client.finish();
    assert.equal(client.getBudget().requests, DAILY_REQUEST_LIMIT);
    assert.throws(() => f.makeClient({ dailyLimit: 48001 }), /Daily request limit/);
    assert.throws(() => f.makeClient({ maxAttempts: 4 }), /retry limit/);
});

test('remaining quota excludes the durable precharge and spans completed runs', async t => {
    const f = fixture(t);
    reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'first', now: START });
    const first = f.makeClient({ reservationId: 'first' });
    assert.equal(first.getBudget().requests, 48000);
    assert.equal(first.remaining(), 48000);
    await first.get('https://booth.pm/ja/search');
    await first.get('https://booth.pm/ja/items/1');
    assert.equal(first.remaining(), 47998);
    first.finish();
    reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'second', now: f.now() });
    const second = f.makeClient({ reservationId: 'second' });
    assert.equal(second.remaining(), 47998);
    assert.equal(second.getBudget().reservation.limit, 47998);
    assert.throws(() => f.makeClient(), /reservation ID/);
});

test('explicit stop blocks queued starts without inventing a cooldown and allows active responses to drain', async t => {
    const f = fixture(t);
    let starts = 0;
    let complete;
    let announce;
    const started = new Promise(resolve => { announce = resolve; });
    const client = f.makeClient({ wait: async () => {
        client.stop('metadata-write', 'Failed to save products');
    }, get: () => {
        starts++;
        announce();
        return new Promise(resolve => { complete = resolve; });
    } });
    const first = client.get('https://booth.pm/a');
    await started;
    const queued = client.get('https://booth.pm/b');
    await assert.rejects(queued, error => error.reason === 'metadata-write' && error.failed === true);
    complete(ok());
    assert.equal((await first).status, 200);
    assert.equal(starts, 1);
    assert.equal(client.getBudget().blockedUntil, 0);
    assert.equal(client.remaining(), 0);
    await assert.rejects(client.get('https://booth.pm/c'), error => error.reason === 'metadata-write');
});

test('429 cooldown stops queued starts at the default zero interval', async t => {
    const f = fixture(t);
    let starts = 0;
    const client = f.makeClient({ intervalMs: undefined, get: async () => {
        starts++;
        throw httpError(429, { 'retry-after': '120' });
    } });
    const results = await Promise.allSettled(Array.from({ length: 10 }, () => client.get('https://booth.pm/a')));
    assert.equal(starts, 1);
    assert.ok(results.every(result => result.status === 'rejected' && result.reason.reason === 'rate-limit'));
    assert.equal(client.getBudget().requests, 1);
    assert.ok(client.getBudget().blockedUntil >= START + 120000);
});

test('budget persistence failure stops queued calls before sending unrecorded HTTP', async t => {
    const f = fixture(t);
    reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'disk-failure', now: START });
    const client = f.makeClient({ reservationId: 'disk-failure' });
    fs.mkdirSync(`${f.budgetFile}.tmp`);
    const results = await Promise.allSettled(Array.from({ length: 4 }, () => client.get('https://booth.pm/a')));
    assert.ok(results.every(result => result.status === 'rejected' && result.reason.reason === 'budget-write'));
    assert.equal(f.calls.length, 0);
    const persisted = JSON.parse(fs.readFileSync(f.budgetFile));
    assert.equal(persisted.requests, 48000);
    assert.equal(persisted.reservation.completed, false);
    assert.equal(persisted.blockedUntil, 0);
});

test('queued requests retain the actual circuit-triggering URL rather than their own URL', async t => {
    const f = fixture(t);
    const starts = [];
    const client = f.makeClient({ failureThreshold: 1, get: async url => {
        starts.push(url);
        throw httpError(500);
    } });
    const urls = ['https://booth.pm/ja/items/1', 'https://booth.pm/ja/items/2', 'https://booth.pm/search'];
    const results = await Promise.allSettled(urls.map(url => client.get(url)));
    assert.deepEqual(starts, [urls[0]]);
    const error = results[0].reason;
    assert.equal(error.reason, 'circuit-breaker');
    assert.equal(error.triggeringUrl, urls[0]);
    assert.ok(results.every(result => result.status === 'rejected' && result.reason === error));
    assert.equal(client.getBudget().requests, 1);
});

test('circuit attribution uses the original URL even when a redirected hop fails', async t => {
    const f = fixture(t);
    const original = 'https://booth.pm/ja/items/123';
    let starts = 0;
    const client = f.makeClient({ failureThreshold: 1, get: async () => {
        if (++starts === 1) return { status: 302, headers: { location: 'https://shop.booth.pm/items/123' } };
        throw httpError(503);
    } });
    await assert.rejects(client.get(original), error => error.reason === 'circuit-breaker' && error.triggeringUrl === original);
    await assert.rejects(client.get('https://booth.pm/ja/items/456'), error => error.triggeringUrl === original);
    assert.equal(starts, 2);
});

test('a later active transient failure does not replace the first circuit origin', async t => {
    const f = fixture(t);
    const rejects = new Map();
    let announce;
    const bothStarted = new Promise(resolve => { announce = resolve; });
    const client = f.makeClient({ failureThreshold: 1, intervalMs: 0, get: url => new Promise((resolve, reject) => {
        rejects.set(url, reject);
        if (rejects.size === 2) announce();
    }) });
    const original = 'https://booth.pm/ja/items/1';
    const later = 'https://booth.pm/ja/items/2';
    const first = client.get(original).catch(error => error);
    const second = client.get(later).catch(error => error);
    await bothStarted;
    rejects.get(original)(httpError(500));
    const stop = await first;
    rejects.get(later)(httpError(500));
    assert.equal(await second, stop);
    assert.equal(stop.triggeringUrl, original);
    await assert.rejects(client.get('https://booth.pm/ja/items/3'), error => error === stop);
    assert.equal(client.getBudget().requests, 2);
});

test('same-url redirects preserve filtered search identity while allowing query order and encoding changes', async t => {
    const f = fixture(t);
    const urls = [];
    const original = 'https://booth.pm/ja/search?sort=new&tags%5B%5D=VRChat&type=digital&tag=blue+sky&tag=avatar';
    const target = 'https://booth.pm/%6Aa/search?tag=avatar&type=digital&tags%5B%5D=VRChat&tag=blue%20sky&sort=new#results';
    const client = f.makeClient({ get: async url => {
        urls.push(url);
        return urls.length === 1 ? { status: 302, headers: { location: target } } : ok();
    } });
    await client.get(original, { redirectPolicy: 'same-url' });
    assert.deepEqual(urls, [original, target]);
    assert.equal(client.getBudget().requests, 2);
});

test('same-url policy rejects filter loss or source changes before following a redirect', async t => {
    const original = 'https://booth.pm/ja/search?sort=new&tags%5B%5D=VRChat&type=digital&page=1';
    for (const target of [
        'https://booth.pm/ja/search?sort=new',
        'https://booth.pm/ja/search?sort=popular&tags%5B%5D=VRChat&type=digital&page=1',
        'https://booth.pm/ja/search?sort=new&tags%5B%5D=VRChat&type=physical&page=1',
        'https://booth.pm/ja/search?sort=new&tags%5B%5D=VRChat&type=digital&page=2',
        'https://booth.pm/ja/search?sort=new&tags%5B%5D=VRChat&tags%5B%5D=extra&type=digital&page=1',
        'https://booth.pm/en/search?sort=new&tags%5B%5D=VRChat&type=digital&page=1',
        'https://shop.booth.pm/ja/search?sort=new&tags%5B%5D=VRChat&type=digital&page=1',
        'https://booth.pm/%ZZ/search?sort=new&tags%5B%5D=VRChat&type=digital&page=1'
    ]) {
        const f = fixture(t);
        let starts = 0;
        const client = f.makeClient({ get: async () => {
            starts++;
            return { status: 302, headers: { location: target } };
        } });
        await assert.rejects(client.get(original, { redirectPolicy: 'same-url' }),
            error => error instanceof CollectionStop && error.reason === 'redirect' && error.failed === true);
        assert.equal(starts, 1, target);
        assert.equal(client.getBudget().requests, 1);
    }
});

test('same-url redirects preserve duplicate query entries instead of comparing only the first value', async t => {
    const f = fixture(t);
    let starts = 0;
    const client = f.makeClient({ get: async () => {
        starts++;
        return { status: 302, headers: { location: 'https://booth.pm/ja/search?tags%5B%5D=VRChat' } };
    } });
    await assert.rejects(client.get('https://booth.pm/ja/search?tags%5B%5D=VRChat&tags%5B%5D=avatar',
        { redirectPolicy: 'same-url' }), error => error.reason === 'redirect');
    assert.equal(starts, 1);
});

test('product identity permits BOOTH shop/localized item redirects for the same numeric ID', async t => {
    for (const target of ['https://shop.booth.pm/items/123', 'https://booth.pm/en/items/123/', 'https://shop.booth.pm/ja/items/123']) {
        const f = fixture(t);
        let starts = 0;
        const client = f.makeClient({ get: async () => ++starts === 1 ? { status: 302, headers: { location: target } } : ok() });
        assert.equal((await client.get('https://booth.pm/ja/items/123', { productId: '123' })).status, 200);
        assert.equal(starts, 2);
    }
});

test('product identity rejects another item, a search page, or a foreign host before following', async t => {
    for (const target of ['https://shop.booth.pm/items/456', 'https://booth.pm/ja/search',
        'https://example.com/items/123', 'https://shop.booth.pm/items/123/reviews', 'https://shop.booth.pm/fr/items/123']) {
        const f = fixture(t);
        let starts = 0;
        const client = f.makeClient({ get: async () => {
            starts++;
            return { status: 302, headers: { location: target } };
        } });
        await assert.rejects(client.get('https://booth.pm/ja/items/123', { productId: '123' }),
            error => error.reason === 'redirect' && error.failed === true);
        assert.equal(starts, 1, target);
    }
});

test('unknown redirect policies and malformed product identities fail before any HTTP attempt', async t => {
    const f = fixture(t);
    const client = f.makeClient();
    await assert.rejects(client.get('https://booth.pm/ja/search', { redirectPolicy: 'allow-anywhere' }), /Unknown redirect policy/);
    for (const productId of [123, '0123', '0', '123|456', '', null]) {
        await assert.rejects(client.get('https://booth.pm/ja/items/123', { productId }), /canonical positive numeric ID/);
    }
    assert.equal(f.calls.length, 0);
    assert.equal(client.getBudget().requests, 0);
});

test('attempt hook observes each persisted retry and redirect immediately before HTTP starts', async t => {
    const f = fixture(t);
    let starts = 0;
    const seen = [];
    const client = f.makeClient({ get: async () => {
        starts++;
        if (starts === 1) return { status: 302, headers: { location: 'https://shop.booth.pm/items/123' } };
        if (starts === 2) throw httpError(503);
        return ok();
    } });
    await client.get('https://booth.pm/ja/items/123', { productId: '123', onAttempt: () => {
        const persisted = JSON.parse(fs.readFileSync(f.budgetFile));
        seen.push({ attempts: persisted.requests, httpAlreadyStarted: starts });
    } });
    assert.deepEqual(seen, [
        { attempts: 1, httpAlreadyStarted: 0 },
        { attempts: 2, httpAlreadyStarted: 1 },
        { attempts: 3, httpAlreadyStarted: 2 }
    ]);
    assert.equal(starts, 3);
});

test('shared budget denials never invoke a queued attempt hook', async t => {
    const f = fixture(t);
    let attempts = 0;
    const client = f.makeClient({ dailyLimit: 3, intervalMs: undefined });
    const onAttempt = () => { attempts++; };
    const results = await Promise.allSettled(Array.from({ length: 10 }, () =>
        client.get('https://booth.pm/search', { onAttempt })));
    assert.equal(results.filter(result => result.status === 'fulfilled').length, 3);
    assert.equal(attempts, 3);
    assert.equal(f.calls.length, 3);
    await assert.rejects(client.get('https://booth.pm/ja/items/123', { onAttempt }),
        error => error.reason === 'request-budget');
    assert.equal(attempts, 3);
});

test('attempt hook failure halts all queued starts instead of being retried as a network error', async t => {
    const f = fixture(t);
    let observed = 0;
    const client = f.makeClient();
    const onAttempt = () => { observed++; throw new Error('Task accounting failed'); };
    const results = await Promise.allSettled(Array.from({ length: 3 }, () =>
        client.get('https://booth.pm/ja/items/123', { onAttempt })));
    assert.ok(results.every(result => result.status === 'rejected' && result.reason.reason === 'attempt-hook'));
    assert.equal(observed, 1);
    assert.equal(f.calls.length, 0);
    assert.equal(client.getBudget().requests, 1, 'the durable precharge remains conservatively charged');
    assert.equal(client.getBudget().blockedUntil, 0);
});

test('invalid and asynchronous attempt hooks cannot cause an HTTP start', async t => {
    const f = fixture(t);
    const client = f.makeClient();
    await assert.rejects(client.get('https://booth.pm/ja/items/123', { onAttempt: 'invalid' }), /onAttempt must be a function/);
    assert.equal(client.getBudget().requests, 0);
    await assert.rejects(client.get('https://booth.pm/ja/items/123', { onAttempt: async () => { throw new Error('async hook'); } }),
        error => error.reason === 'attempt-hook');
    assert.equal(f.calls.length, 0);
});

test('403 stops queued hooks at the default zero interval and retains the failing URL', async t => {
    const f = fixture(t);
    let observed = 0;
    let starts = 0;
    const client = f.makeClient({ intervalMs: undefined, get: async () => {
        starts++;
        throw httpError(403, { 'retry-after': '86400' });
    } });
    const urls = ['https://booth.pm/ja/items/123', 'https://booth.pm/ja/items/456'];
    const results = await Promise.allSettled(urls.map(url => client.get(url, { onAttempt: () => { observed++; } })));
    const error = results[0].reason;
    assert.equal(error.reason, 'forbidden');
    assert.equal(error.triggeringUrl, urls[0]);
    assert.ok(results.every(result => result.status === 'rejected' && result.reason === error));
    assert.equal(observed, 1);
    assert.equal(starts, 1);
    assert.ok(client.getBudget().blockedUntil >= START + 86400000);
});

test('a slow synchronous attempt hook cannot bunch subsequent HTTP starts', async t => {
    const f = fixture(t);
    let observed = 0;
    const client = f.makeClient({ intervalMs: 500 });
    const onAttempt = () => { if (++observed === 1) f.setTime(f.now() + 1000); };
    await Promise.all(Array.from({ length: 3 }, () => client.get('https://booth.pm/ja/items/123', { onAttempt })));
    assert.deepEqual(f.calls.map(call => call.time - START), [1000, 1500, 2000]);
});

test('an observer crossing midnight cannot send an old-day charged request on the new day', async t => {
    const f = fixture(t);
    f.setTime(Date.parse('2026-10-04T14:59:59.999Z'));
    const client = f.makeClient({ intervalMs: 0 });
    await assert.rejects(client.get('https://booth.pm/a', {
        onAttempt: () => f.setTime(Date.parse('2026-10-04T15:00:00.001Z'))
    }), error => error.reason === 'day-boundary');
    assert.equal(f.calls.length, 0);
    assert.equal(client.getBudget().requests, 1); // Conservative old-day charge is not refunded.
});

test('an observer crossing the deadline cannot start HTTP after it', async t => {
    const f = fixture(t);
    const client = f.makeClient({ deadline: START + 1 });
    await assert.rejects(client.get('https://booth.pm/a', { onAttempt: () => f.setTime(START + 2) }),
        error => error.reason === 'deadline');
    assert.equal(f.calls.length, 0);
});


test('the fifth transient failure blocks queued starts at the default zero interval', async t => {
    const f = fixture(t);
    let starts = 0;
    const client = f.makeClient({ intervalMs: undefined, maxAttempts: 1, get: async () => {
        starts++;
        throw httpError(503);
    } });
    const results = await Promise.allSettled(Array.from({ length: 10 }, () => client.get('https://booth.pm/a')));
    assert.equal(starts, 5);
    assert.equal(client.getBudget().requests, 5);
    assert.ok(results.slice(4).every(result => result.status === 'rejected' && result.reason.reason === 'circuit-breaker'));
});

test('a synchronous transport rejection also stops queued requests before the next start', async t => {
    const f = fixture(t);
    let starts = 0;
    const client = f.makeClient({ intervalMs: undefined, get: () => {
        starts++;
        throw httpError(403);
    } });
    const results = await Promise.allSettled(Array.from({ length: 5 }, () => client.get('https://booth.pm/a')));
    assert.equal(starts, 1);
    assert.ok(results.every(result => result.status === 'rejected' && result.reason.reason === 'forbidden'));
});

test('an active later rate-limit response preserves the first stop and extends its durable cooldown', async t => {
    const f = fixture(t);
    const rejects = [];
    const client = f.makeClient({ intervalMs: undefined, get: () => new Promise((resolve, reject) => rejects.push(reject)) });
    const first = client.get('https://booth.pm/a').catch(error => error);
    const second = client.get('https://booth.pm/b').catch(error => error);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(rejects.length, 2);
    rejects[0](httpError(429, { 'retry-after': '120' }));
    const stopped = await first;
    rejects[1](httpError(429, { 'retry-after': '900' }));
    assert.equal(await second, stopped);
    assert.equal(client.getBudget().blockedUntil, START + 900000);
    assert.equal(JSON.parse(fs.readFileSync(f.budgetFile)).blockedUntil, START + 900000);
    await assert.rejects(client.get('https://booth.pm/c'), error => error === stopped);
    assert.equal(client.getBudget().requests, 2);
});


test('overflowing Retry-After durations saturate at a valid far-future timestamp', () => {
    const maximumTimestamp = 8640000000000000;
    for (const header of ['1e308', '1e999', '9'.repeat(400), '100000000000000', 1e308]) {
        const delay = retryAfterMs(header, START);
        assert.ok(Number.isFinite(delay));
        assert.equal(START + delay, maximumTimestamp);
        assert.doesNotThrow(() => new Date(START + delay).toISOString());
    }
    for (const header of ['not-a-duration', '1e+', '1 second']) {
        assert.equal(retryAfterMs(header, START), 60000);
    }
});

test('huge Retry-After on 429 and 403 remains a valid durable hold after finish and restart', async t => {
    for (const status of [429, 403]) {
        for (const header of ['1e308', '1e999', '9'.repeat(400), '100000000000000']) {
            const f = fixture(t);
            let starts = 0;
            reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'huge-cooldown', now: START });
            const client = f.makeClient({ reservationId: 'huge-cooldown', intervalMs: undefined, get: async () => {
                starts++;
                throw httpError(status, { 'retry-after': header });
            } });
            const results = await Promise.allSettled(Array.from({ length: 5 }, () => client.get('https://booth.pm/a')));
            const reason = status === 403 ? 'forbidden' : 'rate-limit';
            assert.ok(results.every(result => result.status === 'rejected' && result.reason.reason === reason));
            assert.equal(starts, 1);
            assert.equal(client.getBudget().blockedUntil, 8640000000000000);
            client.finish();
            const persisted = JSON.parse(fs.readFileSync(f.budgetFile));
            assert.equal(persisted.reservation.completed, true);
            assert.equal(persisted.requests, 1);
            assert.equal(persisted.blockedUntil, 8640000000000000);
            assert.doesNotThrow(() => new Date(persisted.blockedUntil).toISOString());
            const restarted = f.makeClient();
            await assert.rejects(restarted.get('https://booth.pm/b'), error => error.reason === 'cooldown');
            assert.equal(restarted.remaining(), 0);
            assert.throws(() => reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'next-run', now: START }), /Requests paused/);
            assert.equal(f.calls.length, 0);
            assert.equal(starts, 1);
        }
    }
});

test('out-of-range persisted cooldowns fail validation without changing the ledger', t => {
    const f = fixture(t);
    for (const blockedUntil of [8640000000000001, 1e308]) {
        writeJson(f.budgetFile, { date: jstDate(START), requests: 1, blockedUntil });
        const original = fs.readFileSync(f.budgetFile, 'utf8');
        assert.throws(() => f.makeClient(), /Invalid request budget/);
        assert.throws(() => reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'invalid-cooldown', now: START }), /Invalid request budget/);
        assert.equal(fs.readFileSync(f.budgetFile, 'utf8'), original);
        assert.equal(f.calls.length, 0);
    }
});
