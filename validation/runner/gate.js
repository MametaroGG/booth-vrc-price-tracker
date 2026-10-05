'use strict';
const fs = require('node:fs');
const assert = require('node:assert/strict');

const REPOSITORY = 'MametaroGG/booth-vrc-price-tracker';
const BRANCH = 'test/bounded-booth-probe-20261005';
const PARENT = '4aedd907f01f10ce5eb36f69401fff4dadf89383';
const WORKFLOW = 'booth_bounded_validation_20261005.yml';
const MARKER = 'bounded-booth-validation-20261005-remaining18';
const ACTIVE_STATES = ['in_progress', 'queued', 'waiting', 'pending', 'requested'];
const jstDate = time => new Date(time + 9 * 3600000).toISOString().slice(0, 10);

function validateContext({ env, event, activation, now }) {
    assert.equal(env.GITHUB_ACTIONS, 'true', 'GitHub Actions is required');
    assert.equal(env.RUNNER_ENVIRONMENT, 'github-hosted', 'Only GitHub-hosted runners are permitted');
    assert.equal(env.GITHUB_REPOSITORY, REPOSITORY);
    assert.equal(env.GITHUB_REF, `refs/heads/${BRANCH}`);
    assert.equal(env.GITHUB_EVENT_NAME, 'push');
    assert.equal(env.GITHUB_RUN_ATTEMPT, '1', 'Reruns cannot spend the one-time allocation');
    assert.equal(env.GITHUB_RUN_NUMBER, '1', 'Only the first run of this unique workflow may spend the allocation');
    assert.match(env.GITHUB_RUN_ID || '', /^[1-9]\d*$/);
    assert.match(env.GITHUB_SHA || '', /^[0-9a-f]{40}$/);
    assert.equal(env.GITHUB_WORKFLOW_REF, `${REPOSITORY}/.github/workflows/${WORKFLOW}@refs/heads/${BRANCH}`);
    assert.equal(event.repository?.full_name, REPOSITORY);
    assert.equal(event.ref, env.GITHUB_REF);
    assert.equal(event.before, PARENT, 'The test must be one atomic push after the tested PR commit');
    assert.equal(event.after, env.GITHUB_SHA);
    assert.equal(event.created, false, 'A branch-creation event cannot run this test');
    assert.equal(event.deleted, false);
    assert.equal(activation.marker, MARKER);
    assert.equal(activation.prCommit, PARENT);
    assert.equal(activation.previouslyUsedRequests, 2);
    assert.equal(activation.remainingRequests, 18);
    assert.equal(activation.totalRequestCeiling, 20);
    assert.equal(activation.accountingScope, 'incremental-exception');
    assert.equal(activation.expectedJstDay, jstDate(now), 'An old allocation cannot reset at midnight');
    const expiry = Date.parse(activation.exclusiveUntil);
    assert.ok(Number.isFinite(expiry) && expiry >= now + 295000, 'The full watchdog must fit inside the approved window');
    assert.equal(jstDate(expiry), activation.expectedJstDay, 'The test window cannot cross a JST day');
    return { runId: env.GITHUB_RUN_ID, sha: env.GITHUB_SHA };
}

async function publicJson(url) {
    const response = await fetch(url, {
        redirect: 'error', signal: AbortSignal.timeout(15000),
        headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'boopa-bounded-validation',
            'X-GitHub-Api-Version': '2022-11-28' }
    });
    if (!response.ok) throw new Error(`GitHub preflight failed with HTTP ${response.status}`);
    const parts = [];
    let size = 0;
    for await (const bytes of response.body) {
        size += bytes.length;
        if (size > 2 * 1024 * 1024) throw new Error('GitHub preflight response exceeded its limit');
        parts.push(bytes);
    }
    return JSON.parse(Buffer.concat(parts).toString('utf8'));
}

function validateRuns(payload) {
    assert.ok(payload && Number.isSafeInteger(payload.total_count) && Array.isArray(payload.workflow_runs));
    assert.equal(payload.total_count, payload.workflow_runs.length, 'Inconsistent or paginated run results are not proof of exclusivity');
    return payload.workflow_runs;
}

async function verifyWindow({ env, event, activation, now = Date.now(), getJson = publicJson }) {
    const context = validateContext({ env, event, activation, now });
    const base = `https://api.github.com/repos/${REPOSITORY}/actions`;
    const workflow = await getJson(`${base}/workflows/daily_scrape.yml`);
    assert.equal(workflow.path, '.github/workflows/daily_scrape.yml');
    assert.equal(workflow.state, 'disabled_manually', 'Daily Scrape must remain disabled throughout the live probe');
    const own = validateRuns(await getJson(`${base}/runs?head_sha=${context.sha}&per_page=100`));
    assert.equal(own.length, 1, 'Ambiguous or duplicate runs at the test commit fail closed');
    assert.equal(String(own[0].id), context.runId);
    assert.equal(own[0].event, 'push');
    assert.equal(own[0].head_sha, context.sha);
    assert.equal(own[0].head_branch, BRANCH);
    const expectedPath = `.github/workflows/${WORKFLOW}`;
    assert.ok([expectedPath, `${expectedPath}@${BRANCH}`, `${expectedPath}@refs/heads/${BRANCH}`].includes(own[0].path),
        'Unexpected workflow path or branch suffix');
    assert.equal(own[0].run_attempt, 1);
    assert.equal(own[0].run_number, 1);
    const states = [];
    for (const status of ACTIVE_STATES) {
        const runs = validateRuns(await getJson(`${base}/runs?status=${status}&per_page=100`));
        assert.ok(runs.every(run => String(run.id) === context.runId), `Another ${status} run prevents a live probe`);
        states.push({ status, otherRuns: 0, ownRunListed: runs.length === 1 });
    }
    return { verifiedAt: new Date(now).toISOString(), repository: REPOSITORY, branch: BRANCH,
        runId: context.runId, commit: context.sha, dailyScrape: 'disabled_manually', states,
        accountingScope: 'incremental-exception', priorRequests: 2, remainingRequests: 18,
        exclusiveUntil: activation.exclusiveUntil };
}

module.exports = { REPOSITORY, BRANCH, PARENT, WORKFLOW, MARKER, ACTIVE_STATES, validateContext, verifyWindow };
if (require.main === module) {
    Promise.resolve().then(async () => {
        const activation = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
        const event = JSON.parse(fs.readFileSync(process.env.GITHUB_EVENT_PATH, 'utf8'));
        console.log(JSON.stringify(await verifyWindow({ env: process.env, event, activation }), null, 2));
    }).catch(error => { console.error(`Live probe blocked: ${error.message}`); process.exitCode = 1; });
}
