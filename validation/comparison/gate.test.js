'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { REPOSITORY, BRANCH, PARENT, WORKFLOW, MARKER, validateContext, verifyWindow } = require('./gate');
const now = Date.parse('2026-10-05T06:00:00Z');
function fixture() {
    const sha = 'a'.repeat(40);
    const env = { GITHUB_ACTIONS: 'true', RUNNER_ENVIRONMENT: 'github-hosted', GITHUB_REPOSITORY: REPOSITORY,
        GITHUB_REF: `refs/heads/${BRANCH}`, GITHUB_EVENT_NAME: 'push', GITHUB_RUN_ATTEMPT: '1',
        GITHUB_RUN_NUMBER: '1', GITHUB_RUN_ID: '12345', GITHUB_SHA: sha,
        GITHUB_WORKFLOW_REF: `${REPOSITORY}/.github/workflows/${WORKFLOW}@refs/heads/${BRANCH}` };
    const event = { repository: { full_name: REPOSITORY }, ref: env.GITHUB_REF, before: PARENT, after: sha, created: false, deleted: false };
    const activation = { marker: MARKER, prCommit: PARENT, priorEvidenceRequests: 12, newRequestCeiling: 400, blockRequestCeiling: 50,
        sampleSize: 40, blockCount: 8, plannedInitialRequests: 320, accountingScope: 'comparison-only', expectedJstDay: '2026-10-05', exclusiveUntil: '2026-10-05T06:30:00Z' };
    const own = { id: 12345, event: 'push', head_sha: sha, head_branch: BRANCH,
        path: `.github/workflows/${WORKFLOW}`, run_number: 1, run_attempt: 1 };
    const getJson = async url => url.includes('/workflows/') ? { path: '.github/workflows/daily_scrape.yml', state: 'disabled_manually' }
        : url.includes('head_sha=') ? { total_count: 1, workflow_runs: [own] }
        : { total_count: 0, workflow_runs: [] };
    return { env, event, activation, now, getJson, own };
}
test('a single first-run push with disabled production and no competing runs is accepted', async () => {
    const result = await verifyWindow(fixture());
    assert.equal(result.newRequestCeiling, 400);
    assert.equal(result.priorEvidenceRequests, 12);
    assert.equal(result.states.length, 5);
});
test('reruns, repeated workflow runs, wrong branch, wrong environment and dispatch events are refused', () => {
    for (const patch of [{ GITHUB_RUN_ATTEMPT: '2' }, { GITHUB_RUN_NUMBER: '2' }, { GITHUB_EVENT_NAME: 'workflow_dispatch' },
        { GITHUB_REF: 'refs/heads/main' }, { RUNNER_ENVIRONMENT: 'self-hosted' }, { GITHUB_REPOSITORY: 'other/repo' }]) {
        const f = fixture(); Object.assign(f.env, patch); assert.throws(() => validateContext(f));
    }
});
test('branch creation, unrelated preceding commit, deletion, and changed allowance are refused', () => {
    for (const patch of [{ before: '0'.repeat(40), created: true }, { before: 'b'.repeat(40) }, { deleted: true }]) {
        const f = fixture(); Object.assign(f.event, patch); assert.throws(() => validateContext(f));
    }
    for (const patch of [{ priorEvidenceRequests: 0 }, { newRequestCeiling: 401 }, { blockRequestCeiling: 51 },
        { accountingScope: 'full-day' }, { marker: 'unrelated' }]) {
        const f = fixture(); Object.assign(f.activation, patch); assert.throws(() => validateContext(f));
    }
});
test('expired, short, cross-day and stale-day windows are refused', () => {
    for (const patch of [{ exclusiveUntil: '2026-10-05T06:00:00Z' }, { exclusiveUntil: '2026-10-05T06:04:54Z' },
        { exclusiveUntil: '2026-10-05T15:00:00Z' }, { expectedJstDay: '2026-10-04' }]) {
        const f = fixture(); Object.assign(f.activation, patch); assert.throws(() => validateContext(f));
    }
});
test('enabled production, ambiguous run counts, duplicate runs and other active runs fail closed', async () => {
    for (const mode of ['enabled', 'inconsistent', 'duplicate', 'other-active', 'second-run']) {
        const f = fixture(), original = f.getJson;
        f.getJson = async url => {
            const value = await original(url);
            if (mode === 'enabled' && url.includes('/workflows/')) value.state = 'active';
            if (mode === 'inconsistent' && url.includes('status=queued')) value.total_count = 1;
            if (mode === 'duplicate' && url.includes('head_sha=')) { value.total_count = 2; value.workflow_runs.push({ ...f.own, id: 12346 }); }
            if (mode === 'other-active' && url.includes('status=in_progress')) { value.total_count = 1; value.workflow_runs.push({ id: 54321 }); }
            if (mode === 'second-run' && url.includes('head_sha=')) value.workflow_runs[0].run_number = 2;
            return value;
        };
        await assert.rejects(verifyWindow(f));
    }
});
test('a GitHub metadata failure does not permit an assumption of exclusivity', async () => {
    const f = fixture(); f.getJson = async () => { throw new Error('metadata unavailable'); };
    await assert.rejects(verifyWindow(f), /metadata unavailable/);
});
test('the exact branch-suffixed API path is accepted but any other ref is refused', async () => {
    const f = fixture(); f.own.path += `@refs/heads/${BRANCH}`;
    await verifyWindow(f);
    f.own.path = `.github/workflows/${WORKFLOW}@${BRANCH}`;
    await verifyWindow(f);
    f.own.path = `.github/workflows/${WORKFLOW}@refs/heads/main`;
    await assert.rejects(verifyWindow(f), /workflow path/);
});
