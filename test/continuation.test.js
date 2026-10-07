const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const test = require('node:test');
const { shouldContinueCollection, dispatchContinuation } = require('../src/continuation');

const START = Date.parse('2026-10-07T00:00:00Z');
const HOUR = 60 * 60 * 1000;
const healthy = overrides => ({
    result: { status: 'paused', reason: 'deadline', failed: false },
    metrics: { chargedHttpAttempts: 20, itemSuccess: 10, unavailable: 0, itemFailures: 0, searchFailures: 0 },
    startedAt: START,
    stoppedAt: START + 5 * HOUR,
    deadline: START + 5 * HOUR,
    blockedUntil: 0,
    startedMidSweep: false,
    ...overrides
});

test('productive actual deadlines continue, including normal page delay and in-flight draining', () => {
    for (const adjustment of [-2000, 0, 30000]) {
        assert.equal(shouldContinueCollection(healthy({ stoppedAt: START + 5 * HOUR + adjustment })), true);
    }
    assert.equal(shouldContinueCollection(healthy({ stoppedAt: START + 5 * HOUR - 2001 })), false);
});

test('early oversized-backoff deadlines and tiny deadline loops cannot continue', () => {
    assert.equal(shouldContinueCollection(healthy({ stoppedAt: START + 1000 })), false);
    assert.equal(shouldContinueCollection(healthy({ deadline: START + 59000, stoppedAt: START + 59000 })), false);
    assert.equal(shouldContinueCollection(healthy({ deadline: START + 60000, stoppedAt: START + 60000 })), true);
});

test('healthy midnight transitions may continue after real work', () => {
    assert.equal(shouldContinueCollection(healthy({
        result: { status: 'paused', reason: 'day-boundary', failed: false }, stoppedAt: START + 1000
    })), true);
});

test('a completed short final segment continues, but a fresh short sweep cannot recur', () => {
    const completed = healthy({
        result: { status: 'completed', failed: false }, stoppedAt: START + 1000, startedMidSweep: true
    });
    assert.equal(shouldContinueCollection(completed), true);
    assert.equal(shouldContinueCollection({ ...completed, startedMidSweep: false }), false);
    assert.equal(shouldContinueCollection({ ...completed, startedMidSweep: false, stoppedAt: START + HOUR - 1 }), false);
    assert.equal(shouldContinueCollection({ ...completed, startedMidSweep: false, stoppedAt: START + HOUR }), true);
});

test('HTTP attempts and search-only empty pages are insufficient progress', () => {
    const noItems = { ...healthy().metrics, itemSuccess: 0, unavailable: 0, searchPages: 100 };
    assert.equal(shouldContinueCollection(healthy({ metrics: noItems })), false);
    assert.equal(shouldContinueCollection(healthy({ metrics: { ...healthy().metrics, chargedHttpAttempts: 0 } })), false);
    assert.equal(shouldContinueCollection(healthy({ metrics: { ...healthy().metrics, itemSuccess: 0, unavailable: 1 } })), true);
    assert.equal(shouldContinueCollection(healthy({
        result: { status: 'completed', failed: false }, metrics: noItems, startedMidSweep: true
    })), false);
});

test('failures, deferred retries, unknown statuses, and cooldowns stop continuation', () => {
    const results = [
        { status: 'partial', reason: 'retry-pending', failed: false },
        { status: 'failed', reason: 'storage', failed: true },
        { status: 'paused', reason: 'deadline', failed: true },
        { status: 'paused', reason: 'deadline' },
        { status: 'completed', reason: 'retry-pending', failed: false },
        { status: 'unknown', failed: false },
        ...['request-budget', 'cooldown', 'forbidden', 'rate-limit', 'circuit-breaker', 'storage', 'search-failure']
            .map(reason => ({ status: 'paused', reason, failed: false }))
    ];
    for (const result of results) assert.equal(shouldContinueCollection(healthy({ result })), false, JSON.stringify(result));
    assert.equal(shouldContinueCollection(healthy({ blockedUntil: START + 5 * HOUR + 1 })), false);
    assert.equal(shouldContinueCollection(healthy({ blockedUntil: START + 5 * HOUR })), true);
});

test('durably queued item errors and benign search-stop counts do not stop healthy handovers', () => {
    for (const key of ['itemFailures', 'searchFailures']) {
        const metrics = { ...healthy().metrics, [key]: 1 };
        assert.equal(shouldContinueCollection(healthy({ metrics })), true);
        assert.equal(shouldContinueCollection(healthy({
            metrics, result: { status: 'paused', reason: 'day-boundary', failed: false }
        })), true);
        assert.equal(shouldContinueCollection(healthy({
            metrics, result: { status: 'partial', reason: 'search-failure', failed: true }
        })), false);
    }
});

test('missing, malformed, negative, and out-of-order policy inputs fail closed', () => {
    for (const value of [undefined, null, [], 'invalid']) assert.equal(shouldContinueCollection(value), false);
    for (const field of ['startedAt', 'stoppedAt', 'deadline', 'blockedUntil']) {
        for (const value of [undefined, NaN, Infinity, '0', -1]) {
            assert.equal(shouldContinueCollection(healthy({ [field]: value })), false, `${field}: ${value}`);
        }
    }
    for (const value of [undefined, 0, 'false']) {
        assert.equal(shouldContinueCollection(healthy({ startedMidSweep: value })), false);
    }
    assert.equal(shouldContinueCollection(healthy({ stoppedAt: START - 1 })), false);
    assert.equal(shouldContinueCollection(healthy({ deadline: START })), false);
    for (const key of ['chargedHttpAttempts', 'itemSuccess', 'unavailable', 'itemFailures', 'searchFailures']) {
        for (const value of [undefined, NaN, '1', -1, 0.5]) {
            assert.equal(shouldContinueCollection(healthy({ metrics: { ...healthy().metrics, [key]: value } })), false);
        }
    }
    for (const value of [null, [], 'success']) {
        assert.equal(shouldContinueCollection(healthy({ result: value })), false);
        assert.equal(shouldContinueCollection(healthy({ metrics: value })), false);
    }
});

const environment = overrides => ({
    GITHUB_ACTIONS: 'true',
    DEFAULT_BRANCH: 'main',
    GITHUB_REF: 'refs/heads/main',
    GITHUB_REPOSITORY: 'MametaroGG/booth-vrc-price-tracker',
    GITHUB_RUN_ID: '12345678901',
    GITHUB_TOKEN: 'test-token-never-log',
    GITHUB_API_URL: 'https://api.github.com',
    ...overrides
});

function transport({ statusCode = 204, error, throwAt, silence = false, timeoutEvent = false } = {}) {
    const calls = [];
    const request = (url, options, callback) => {
        const pending = new EventEmitter();
        const call = { url, options, pending, destroyed: false, responseDestroyed: false, resumed: false };
        calls.push(call);
        if (throwAt === 'request') throw new Error('test-token-never-log');
        pending.destroy = () => { call.destroyed = true; };
        pending.end = body => {
            call.body = body;
            if (throwAt === 'end') throw new Error('test-token-never-log');
            if (silence) return;
            queueMicrotask(() => {
                if (timeoutEvent) return pending.emit('timeout');
                if (error) return pending.emit('error', error);
                const response = Object.assign(new EventEmitter(), {
                    statusCode,
                    resume: () => { call.resumed = true; },
                    destroy: () => { call.responseDestroyed = true; }
                });
                call.response = response;
                callback(response);
            });
        };
        return pending;
    };
    return { calls, request };
}

test('dispatcher makes one exact public GitHub POST and accepts only HTTP 204', async () => {
    const f = transport();
    assert.deepEqual(await dispatchContinuation({ env: environment(), request: f.request }), { statusCode: 204 });
    assert.equal(f.calls.length, 1);
    const call = f.calls[0];
    assert.equal(call.url.href, 'https://api.github.com/repos/MametaroGG/booth-vrc-price-tracker/dispatches');
    assert.equal(call.options.method, 'POST');
    assert.equal(call.options.timeout, 30000);
    assert.equal(call.options.headers.Authorization, 'Bearer test-token-never-log');
    assert.equal(call.options.headers['Content-Length'], Buffer.byteLength(call.body));
    assert.deepEqual(JSON.parse(call.body), {
        event_type: 'continue-scrape', client_payload: { predecessor_run_id: '12345678901' }
    });
    assert.equal(call.resumed, true);
    // HTTP 204 already confirms acceptance; a late close error must not create
    // an unhandled exception or cause another POST.
    call.response.emit('error', new Error('late response error'));
    assert.equal(f.calls.length, 1);
});

test('dispatcher rejects invalid environment before any request, without exposing values', async () => {
    const invalid = [
        { GITHUB_ACTIONS: undefined }, { GITHUB_ACTIONS: 'false' },
        { DEFAULT_BRANCH: '' }, { DEFAULT_BRANCH: 'main\n' }, { GITHUB_REF: 'refs/heads/feature' },
        { GITHUB_REPOSITORY: 'owner/../other' }, { GITHUB_REPOSITORY: 'owner/..' },
        { GITHUB_REPOSITORY: 'owner/repo?token=test-token-never-log' }, { GITHUB_REPOSITORY: 'owner/repo/extra' },
        { GITHUB_RUN_ID: '0' }, { GITHUB_RUN_ID: '01' }, { GITHUB_RUN_ID: '12e3' }, { GITHUB_RUN_ID: 123 },
        { GITHUB_TOKEN: '' }, { GITHUB_TOKEN: 'test-token-never-log\r\nInjected: true' },
        { GITHUB_API_URL: 'https://elsewhere.invalid' }, { GITHUB_API_URL: 'https://api.github.com@elsewhere.invalid' }
    ];
    for (const values of invalid) {
        const f = transport();
        await assert.rejects(dispatchContinuation({ env: environment(values), request: f.request }), error => {
            assert.doesNotMatch(error.message, /test-token-never-log/);
            return true;
        });
        assert.equal(f.calls.length, 0);
    }
});

test('dispatcher does not follow redirects or retry refusals, rate limits, or server errors', async () => {
    for (const statusCode of [200, 201, 301, 302, 307, 403, 429, 500, 502, 503, undefined]) {
        const f = transport({ statusCode: statusCode ?? null });
        await assert.rejects(dispatchContinuation({ env: environment(), request: f.request }), /not confirmed.*no retry/);
        assert.equal(f.calls.length, 1);
        assert.equal(f.calls[0].responseDestroyed, true);
    }
});

test('dispatcher does not retry ambiguous network failures or expose transport errors', async () => {
    for (const options of [
        { error: new Error('test-token-never-log') }, { throwAt: 'request' }, { throwAt: 'end' }
    ]) {
        const f = transport(options);
        await assert.rejects(dispatchContinuation({ env: environment(), request: f.request }), error => {
            assert.match(error.message, /acceptance is unknown.*no retry/);
            assert.doesNotMatch(error.message, /test-token-never-log/);
            return true;
        });
        assert.equal(f.calls.length, 1);
    }
});

test('dispatcher terminates a socket timeout without retrying', async () => {
    const f = transport({ timeoutEvent: true });
    await assert.rejects(dispatchContinuation({ env: environment(), request: f.request }), /timed out.*no retry/);
    assert.equal(f.calls.length, 1);
    assert.equal(f.calls[0].destroyed, true);
});

test('dispatcher enforces an absolute 30-second timeout even before a socket exists', async t => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    const f = transport({ silence: true });
    const pending = dispatchContinuation({ env: environment(), request: f.request });
    const rejection = assert.rejects(pending, /timed out.*no retry/);
    t.mock.timers.tick(29999);
    assert.equal(f.calls[0].destroyed, false);
    t.mock.timers.tick(1);
    await rejection;
    assert.equal(f.calls[0].destroyed, true);
    assert.equal(f.calls.length, 1);
});
