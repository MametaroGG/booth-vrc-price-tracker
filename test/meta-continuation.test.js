const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const test = require('node:test');

const { shouldContinueMeta, dispatchMetaContinuation } = require('../src/meta-continuation');

const HOUR = 60 * 60 * 1000;
function baseOptions(overrides = {}) {
    return {
        result: { status: 'completed', failed: false },
        metrics: {
            chargedHttpAttempts: 9000, success: 8000, unavailable: 500,
            failures: 0, planned: 10000, processed: 8500
        },
        startedAt: 0,
        stoppedAt: 3 * HOUR,
        deadline: 4.5 * HOUR,
        blockedUntil: 0,
        capReached: true,
        ...overrides
    };
}

test('shouldContinueMeta chains a cap-bound completed run only', () => {
    assert.equal(shouldContinueMeta(baseOptions()), true);
    assert.equal(shouldContinueMeta(baseOptions({ capReached: false })), false);
});

test('shouldContinueMeta hands over at the real deadline with work left', () => {
    const atBoundary = baseOptions({
        result: { status: 'paused', reason: 'deadline', failed: false },
        stoppedAt: 4.5 * HOUR,
        capReached: false
    });
    assert.equal(shouldContinueMeta(atBoundary), true); // processed < planned
    const drained = baseOptions({
        result: { status: 'paused', reason: 'deadline', failed: false },
        stoppedAt: 4.5 * HOUR,
        capReached: false,
        metrics: {
            chargedHttpAttempts: 100, success: 90, unavailable: 10,
            failures: 0, planned: 100, processed: 100
        }
    });
    assert.equal(shouldContinueMeta(drained), false);
    const early = baseOptions({
        result: { status: 'paused', reason: 'deadline', failed: false },
        stoppedAt: 1 * HOUR
    });
    assert.equal(shouldContinueMeta(early), false); // not at the boundary
});

test('shouldContinueMeta continues across a day boundary but never into a hold or budget stop', () => {
    assert.equal(shouldContinueMeta(baseOptions({
        result: { status: 'paused', reason: 'day-boundary', failed: false }, capReached: false
    })), true);
    assert.equal(shouldContinueMeta(baseOptions({
        result: { status: 'paused', reason: 'request-budget', failed: false }
    })), false);
    assert.equal(shouldContinueMeta(baseOptions({
        result: { status: 'paused', reason: 'cooldown', failed: false }, blockedUntil: 0
    })), false);
    assert.equal(shouldContinueMeta(baseOptions({ blockedUntil: 4 * HOUR })), false); // active hold
});

test('shouldContinueMeta refuses failed, empty, or malformed runs', () => {
    assert.equal(shouldContinueMeta(baseOptions({
        result: { status: 'partial', reason: undefined, failed: true }
    })), false);
    assert.equal(shouldContinueMeta(baseOptions({
        metrics: {
            chargedHttpAttempts: 0, success: 0, unavailable: 0,
            failures: 0, planned: 0, processed: 0
        }
    })), false);
    assert.equal(shouldContinueMeta(baseOptions({
        metrics: {
            chargedHttpAttempts: 5, success: 0, unavailable: 0,
            failures: 0, planned: 3, processed: 0
        }
    })), false);
    assert.equal(shouldContinueMeta(null), false);
    assert.equal(shouldContinueMeta({}), false);
    assert.equal(shouldContinueMeta(baseOptions({ capReached: 'yes' })), false);
});

const validEnv = {
    GITHUB_ACTIONS: 'true',
    DEFAULT_BRANCH: 'main',
    GITHUB_REF: 'refs/heads/main',
    GITHUB_REPOSITORY: 'MametaroGG/booth-vrc-price-tracker',
    GITHUB_RUN_ID: '12345',
    GITHUB_TOKEN: 'test-token'
};

function fakeRequest(statusCode, capture) {
    return (url, options, callback) => {
        const pending = new EventEmitter();
        pending.destroy = () => {};
        pending.end = body => {
            capture.push({ url: String(url), options, body });
            const response = new EventEmitter();
            response.statusCode = statusCode;
            response.resume = () => {};
            response.destroy = () => {};
            callback(response);
        };
        return pending;
    };
}

test('dispatchMetaContinuation posts one continue-meta dispatch', async () => {
    const capture = [];
    const result = await dispatchMetaContinuation({ env: validEnv, request: fakeRequest(204, capture) });
    assert.deepEqual(result, { statusCode: 204 });
    assert.equal(capture.length, 1);
    assert.equal(capture[0].url, 'https://api.github.com/repos/MametaroGG/booth-vrc-price-tracker/dispatches');
    const body = JSON.parse(capture[0].body);
    assert.equal(body.event_type, 'continue-meta');
    assert.equal(body.client_payload.predecessor_run_id, '12345');
    assert.equal(capture[0].options.headers.Authorization, 'Bearer test-token');
});

test('dispatchMetaContinuation validates the environment and never retries a refusal', async () => {
    await assert.rejects(
        dispatchMetaContinuation({ env: { ...validEnv, GITHUB_ACTIONS: 'false' }, request: fakeRequest(204, []) }),
        /requires GitHub Actions/);
    await assert.rejects(
        dispatchMetaContinuation({ env: { ...validEnv, GITHUB_REF: 'refs/heads/other' }, request: fakeRequest(204, []) }),
        /default branch/);
    const capture = [];
    await assert.rejects(
        dispatchMetaContinuation({ env: validEnv, request: fakeRequest(403, capture) }),
        /was not confirmed \(HTTP 403\); no retry was attempted/);
    assert.equal(capture.length, 1);
});
