const https = require('node:https');

// Mirrors src/continuation.js (the price pipeline) for the metadata job:
// a strict, fail-closed decision about whether a finished run should hand
// over to a successor, and a single-attempt repository_dispatch to start
// that successor. Cron remains the fallback, so an uncertain dispatch is
// never retried.

const DISPATCH_TIMEOUT_MS = 30000;
const MIN_DEADLINE_RUN_MS = 60000;
const DEADLINE_TOLERANCE_MS = 2000;
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const count = value => Number.isSafeInteger(value) && value >= 0;

function shouldContinueMeta(options = {}) {
    if (!record(options)) return false;
    const { result, metrics, startedAt, stoppedAt, deadline, blockedUntil, capReached } = options;
    if (!record(result) || !record(metrics) || result.failed !== false ||
        typeof capReached !== 'boolean' ||
        ![startedAt, stoppedAt, deadline, blockedUntil].every(Number.isFinite) ||
        startedAt < 0 || stoppedAt < startedAt || deadline <= startedAt ||
        blockedUntil < 0 || blockedUntil > stoppedAt ||
        !count(metrics.chargedHttpAttempts) || metrics.chargedHttpAttempts === 0 ||
        !count(metrics.success) || !count(metrics.unavailable) ||
        metrics.success + metrics.unavailable === 0 ||
        !count(metrics.failures) || !count(metrics.planned) || !count(metrics.processed)) return false;

    // Individual item failures stay in the work list and are retried by a
    // later scheduled run; they make the result 'partial' (failed), which
    // the check above already excludes from chaining.

    const elapsed = stoppedAt - startedAt;
    if (result.status === 'paused' && result.reason === 'deadline') {
        // A long batch delay can also report "deadline" before collection
        // time is exhausted. Only hand over at the real boundary, and only
        // when work was left behind: unprocessed items in this run's plan,
        // or a full plan that implies a backlog behind the cap.
        return elapsed >= MIN_DEADLINE_RUN_MS && stoppedAt >= deadline - DEADLINE_TOLERANCE_MS &&
            (metrics.processed < metrics.planned || capReached);
    }
    if (result.status === 'paused' && result.reason === 'day-boundary') return true;
    if (result.status === 'completed' && result.reason === undefined) {
        // Drained below the cap: nothing for a successor to do today.
        // Cap-bound: a backlog remains and the successor picks it up; the
        // daily request budget still bounds the whole chain, because each
        // successor reserves only what is left of today's allowance.
        return capReached;
    }
    return false;
}

function dispatchEnvironment(env) {
    if (!record(env) || env.GITHUB_ACTIONS !== 'true') {
        throw new Error('Continuation dispatch requires GitHub Actions');
    }
    const branch = env.DEFAULT_BRANCH;
    if (typeof branch !== 'string' || !branch || /[\s\x00-\x1f\x7f]/.test(branch) ||
        env.GITHUB_REF !== `refs/heads/${branch}`) {
        throw new Error('Continuation dispatch requires the default branch');
    }
    const repository = env.GITHUB_REPOSITORY;
    const parts = typeof repository === 'string' ? repository.split('/') : [];
    if (parts.length !== 2 || !/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$/.test(parts[0]) ||
        !/^[A-Za-z0-9_.-]{1,100}$/.test(parts[1]) || ['.', '..'].includes(parts[1])) {
        throw new Error('Continuation dispatch requires a valid GitHub repository');
    }
    if (typeof env.GITHUB_RUN_ID !== 'string' || !/^[1-9]\d{0,19}$/.test(env.GITHUB_RUN_ID)) {
        throw new Error('Continuation dispatch requires a valid run ID');
    }
    if (typeof env.GITHUB_TOKEN !== 'string' || !env.GITHUB_TOKEN || /[\s\x00-\x1f\x7f]/.test(env.GITHUB_TOKEN)) {
        throw new Error('Continuation dispatch requires GITHUB_TOKEN');
    }
    if (env.GITHUB_API_URL !== undefined && env.GITHUB_API_URL !== 'https://api.github.com') {
        throw new Error('Continuation dispatch only supports the public GitHub API');
    }
    return { repository, runId: env.GITHUB_RUN_ID, token: env.GITHUB_TOKEN };
}

async function dispatchMetaContinuation({ env = process.env, request = https.request } = {}) {
    const { repository, runId, token } = dispatchEnvironment(env);
    if (typeof request !== 'function') throw new Error('Invalid continuation request transport');
    const body = JSON.stringify({
        event_type: 'continue-meta',
        client_payload: { predecessor_run_id: runId }
    });
    const url = new URL(`https://api.github.com/repos/${repository}/dispatches`);

    // This POST is deliberately attempted once. A dropped response can mean
    // GitHub already accepted it; cron provides recovery without duplicate POSTs.
    return new Promise((resolve, reject) => {
        let pending;
        let settled = false;
        const finish = error => {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            if (error) reject(error);
            else resolve({ statusCode: 204 });
        };
        const onTimeout = () => {
            if (settled) return;
            finish(new Error('Continuation dispatch timed out; acceptance is unknown and no retry was attempted'));
            pending?.destroy();
        };
        const onNetworkError = () => finish(new Error('Continuation dispatch failed; acceptance is unknown and no retry was attempted'));
        // An absolute deadline also covers DNS, connection, and TLS setup.
        const timer = setTimeout(onTimeout, DISPATCH_TIMEOUT_MS);
        try {
            pending = request(url, {
                method: 'POST',
                timeout: DISPATCH_TIMEOUT_MS,
                headers: {
                    Accept: 'application/vnd.github+json',
                    Authorization: `Bearer ${token}`,
                    'Content-Type': 'application/json',
                    'Content-Length': Buffer.byteLength(body),
                    'User-Agent': 'booth-vrc-price-tracker',
                    'X-GitHub-Api-Version': '2022-11-28'
                }
            }, response => {
                // node:https does not follow redirects. Never log response
                // bodies or raw transport errors, which could expose credentials.
                response.once('error', onNetworkError);
                if (settled) {
                    response.destroy();
                    return;
                }
                if (response.statusCode === 204) {
                    response.resume();
                    finish();
                } else {
                    const status = Number.isInteger(response.statusCode) ? response.statusCode : 'unknown';
                    response.destroy();
                    finish(new Error(`Continuation dispatch was not confirmed (HTTP ${status}); no retry was attempted`));
                }
            });
            pending.once('error', onNetworkError);
            pending.once('timeout', onTimeout);
            pending.end(body);
        } catch {
            finish(new Error('Continuation dispatch failed; acceptance is unknown and no retry was attempted'));
            pending?.destroy();
        }
    });
}

if (require.main === module) {
    dispatchMetaContinuation().then(() => {
        console.log('Metadata continuation requested.');
    }).catch(error => {
        console.error(error.message);
        process.exitCode = 1;
    });
}

module.exports = { shouldContinueMeta, dispatchMetaContinuation };
