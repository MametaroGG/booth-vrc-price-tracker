const assert = require('node:assert/strict');
const { execFileSync, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const test = require('node:test');

// Mirrors test/workflow.test.js (the price pipeline) for the metadata job, so
// both pipelines are held to the same standard: durable reservation first,
// meta-only commits, rebase replay over an advancing upstream, a hard refusal
// to merge stale budget accounting, and bounded push retries.

const workflow = fs.readFileSync(path.join(__dirname, '../.github/workflows/meta_scrape.yml'), 'utf8');
const pushScriptPath = path.join(__dirname, '../scripts/push-meta.sh');
const pushScript = fs.readFileSync(pushScriptPath, 'utf8');

function step(name) {
    const start = workflow.indexOf(`      - name: ${name}\n`);
    assert.notEqual(start, -1, `Missing workflow step: ${name}`);
    const end = workflow.indexOf('\n      - name:', start + 1);
    return workflow.slice(start, end === -1 ? undefined : end);
}

function script(name) {
    const lines = step(name).split('\n');
    const start = lines.indexOf('        run: |');
    assert.notEqual(start, -1, `Missing shell script: ${name}`);
    return lines.slice(start + 1).map((line) => line.replace(/^          /, '')).join('\n');
}

const gitEnv = {
    ...process.env,
    GIT_CONFIG_NOSYSTEM: '1',
    GIT_CONFIG_GLOBAL: os.devNull,
    GIT_TERMINAL_PROMPT: '0',
};

function git(cwd, ...args) {
    return execFileSync('git', args, { cwd, env: gitEnv, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}

function write(cwd, file, value) {
    const destination = path.join(cwd, file);
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.writeFileSync(destination, value);
}

function commit(cwd, message) {
    git(cwd, 'add', '.');
    git(cwd, 'commit', '-m', message);
}

function fixture(t, branch = 'main') {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'boopa-meta-workflow-'));
    // Retry the teardown: a lingering git process can still be writing to the
    // bare remote while it is deleted, which otherwise fails with ENOTEMPTY.
    t.after(() => fs.rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }));
    const remote = path.join(root, 'remote.git');
    const seed = path.join(root, 'seed');
    const worker = path.join(root, 'worker');
    git(root, 'init', '--bare', '--initial-branch=main', remote);
    git(root, 'init', '--initial-branch=main', seed);
    git(seed, 'config', 'user.name', 'Workflow Test');
    git(seed, 'config', 'user.email', 'workflow@example.invalid');
    write(seed, 'meta/791/7918308.json', '{"id":"7918308"}\n');
    write(seed, 'README.md', 'original\n');
    commit(seed, 'Initial metadata');
    write(seed, 'history.txt', 'Older history should not be fetched\n');
    commit(seed, 'Older history');
    if (branch !== 'main') git(seed, 'checkout', '-b', branch);
    git(seed, 'remote', 'add', 'origin', pathToFileURL(remote).href);
    git(seed, 'push', 'origin', ...new Set(['main', branch]));
    git(root, 'clone', '--depth=1', '--branch', branch, pathToFileURL(remote).href, worker);
    assert.equal(git(worker, 'rev-parse', '--is-shallow-repository'), 'true');
    // Retry backoff sleeps must not slow the suite down.
    const stubBin = path.join(root, 'bin');
    fs.mkdirSync(stubBin);
    fs.writeFileSync(path.join(stubBin, 'sleep'), '#!/bin/sh\nexit 0\n');
    fs.chmodSync(path.join(stubBin, 'sleep'), 0o755);
    return { root, remote, seed, worker, branch, stubBin };
}

function runSave(f, message) {
    return spawnSync('bash', [pushScriptPath, ...(message ? [message] : [])], {
        cwd: f.worker,
        env: {
            ...gitEnv,
            PATH: `${f.stubBin}:${process.env.PATH}`,
            GITHUB_REF: `refs/heads/${f.branch}`,
            DEFAULT_BRANCH: 'main',
        },
        encoding: 'utf8',
        timeout: 30000,
    });
}

function assertSuccess(result) {
    assert.equal(result.error, undefined);
    assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
}

test('metadata workflow mirrors the price workflow discipline', () => {
    assert.match(workflow, /name: Metadata Scrape/);
    assert.match(workflow, /cron: '35 1,7,13,19 \* \* \*'/);
    assert.match(workflow, /group: meta-scrape-group\s+cancel-in-progress: false/);
    assert.match(workflow, /    timeout-minutes: 360\n/);
    assert.match(workflow, /META_RESERVATION_ID: \$\{\{ github\.run_id \}\}-\$\{\{ github\.run_attempt \}\}/);
    assert.match(step('Record job start'), /META_JOB_STARTED_AT=.*GITHUB_ENV/);
    assert.match(step('Record job start'), /GITHUB_REF.*refs\/heads\/\$DEFAULT_BRANCH/);
    assert.ok(workflow.indexOf('- name: Record job start') < workflow.indexOf('- name: Checkout'));
    assert.ok(workflow.indexOf('- name: Run tests') < workflow.indexOf('- name: Reserve request budget'));
    assert.ok(workflow.indexOf('- name: Reserve request budget') < workflow.indexOf('- name: Commit reservation'));
    assert.ok(workflow.indexOf('- name: Commit reservation') < workflow.indexOf('- name: Run metadata scraper'));
    assert.match(step('Run tests'), /run: npm test/);
    assert.match(step('Reserve request budget'), /run: node src\/reserve-meta-budget\.js/);
    assert.match(script('Commit reservation'), /bash scripts\/push-meta\.sh "chore: reserve metadata request budget"/);
    assert.doesNotMatch(step('Reserve request budget') + step('Commit reservation'), /continue-on-error|if:/);
    assert.match(step('Run metadata scraper'), /id: meta/);
    assert.match(step('Run metadata scraper'), /timeout-minutes: 305/);
    assert.match(step('Run metadata scraper'), /continue-on-error: true/);
    assert.match(step('Commit and Push'), /!cancelled\(\).*steps\.meta\.outcome == 'success'.*steps\.meta\.outcome == 'failure'/);
    assert.match(step('Commit and Push'), /run: bash scripts\/push-meta\.sh/);
    assert.match(step('Report metadata scraper failure'), /always\(\).*steps\.meta\.outcome == 'failure'/);
    assert.match(script('Report metadata scraper failure'), /exit 1/);
    assert.doesNotMatch(pushScript, /(?:--force|git pull|--unshallow)/);
    assert.match(pushScript, /for attempt in 1 2 3 4 5 6/);
});

test('metadata workflow chains continuations like the price workflow', () => {
    assert.match(workflow, /repository_dispatch:\s+types: \[continue-meta\]/);
    assert.ok(workflow.indexOf('- name: Report metadata scraper failure') <
        workflow.indexOf('- name: Continue collection'));
    const continuation = step('Continue collection');
    assert.match(continuation, /success\(\).*steps\.meta\.outcome == 'success'.*steps\.save\.outcome == 'success'.*steps\.meta\.outputs\.continue_collection == 'true'/);
    assert.match(continuation, /run: node src\/meta-continuation\.js/);
    assert.match(continuation, /GITHUB_TOKEN: \$\{\{ github\.token \}\}/);
    assert.match(workflow, /permissions:\s+contents: write/);
    assert.doesNotMatch(workflow, /actions: write|secrets\./);
});

test('unchanged metadata exits successfully without making a commit', (t) => {
    const f = fixture(t);
    const before = git(f.remote, 'rev-parse', 'main');
    const result = runSave(f);
    assertSuccess(result);
    assert.match(result.stdout, /No metadata or checkpoint changes/);
    assert.equal(git(f.remote, 'rev-parse', 'main'), before);
    assert.equal(git(f.worker, 'rev-parse', 'HEAD'), before);
});

test('saves only metadata, excluding unrelated staged files', (t) => {
    const f = fixture(t);
    write(f.worker, 'meta/791/7918308.json', '{"id":"7918308","likes":39}\n');
    write(f.worker, 'meta/meta_state.json', '{"status":"completed"}\n');
    write(f.worker, 'README.md', 'unrelated staged change\n');
    git(f.worker, 'add', 'README.md');
    assertSuccess(runSave(f));
    assert.equal(git(f.remote, 'show', 'main:meta/791/7918308.json'), '{"id":"7918308","likes":39}');
    assert.equal(git(f.remote, 'show', 'main:meta/meta_state.json'), '{"status":"completed"}');
    assert.equal(git(f.remote, 'show', 'main:README.md'), 'original');
});

test('the push script refuses non-default branches even outside the workflow', (t) => {
    const f = fixture(t, 'test/meta');
    const main = git(f.remote, 'rev-parse', 'main');
    const branch = git(f.remote, 'rev-parse', f.branch);
    write(f.worker, 'meta/request_budget.json', '{"reserved":12000}\n');
    const result = runSave(f);
    assert.equal(result.status, 1);
    assert.match(result.stdout, /must use the repository's default branch/);
    assert.equal(git(f.remote, 'rev-parse', 'main'), main);
    assert.equal(git(f.remote, 'rev-parse', f.branch), branch);
});

test('a reservation is durable before subsequent collection results are saved', (t) => {
    const f = fixture(t);
    write(f.worker, 'meta/request_budget.json', '{"reserved":12000}\n');
    assertSuccess(runSave(f, 'chore: reserve metadata request budget'));
    const reservation = git(f.remote, 'rev-parse', 'main');
    assert.equal(git(f.remote, 'show', 'main:meta/request_budget.json'), '{"reserved":12000}');
    assert.equal(git(f.remote, 'log', '-1', '--format=%s', 'main'), 'chore: reserve metadata request budget');
    write(f.worker, 'meta/791/7918308.json', '{"id":"7918308","likes":39}\n');
    write(f.worker, 'meta/request_budget.json', '{"reserved":12000,"attempts":5}\n');
    assertSuccess(runSave(f));
    assert.equal(git(f.remote, 'rev-parse', 'main^'), reservation);
    assert.equal(git(f.remote, 'show', 'main:meta/791/7918308.json'), '{"id":"7918308","likes":39}');
});

test('replays the single meta commit after upstream advances beyond shallow history', (t) => {
    const f = fixture(t);
    write(f.worker, 'meta/791/7918308.json', '{"id":"7918308","likes":39}\n');
    for (let index = 0; index < 3; index++) {
        write(f.seed, 'README.md', `upstream ${index}\n`);
        commit(f.seed, `Upstream update ${index}`);
    }
    git(f.seed, 'push', 'origin', 'main');
    const upstream = git(f.remote, 'rev-parse', 'main');
    assertSuccess(runSave(f));
    assert.equal(git(f.remote, 'rev-parse', 'main^'), upstream);
    assert.equal(git(f.remote, 'show', 'main:meta/791/7918308.json'), '{"id":"7918308","likes":39}');
    assert.equal(git(f.remote, 'show', 'main:README.md'), 'upstream 2');
});

test('upstream budget-ledger changes cannot be merged with stale accounting', (t) => {
    const f = fixture(t);
    write(f.seed, 'meta/request_budget.json', '{"reserved":9999,"upstream":true}\n');
    commit(f.seed, 'Upstream ledger');
    git(f.seed, 'push', 'origin', 'main');
    const upstream = git(f.remote, 'rev-parse', 'main');
    write(f.worker, 'meta/request_budget.json', '{"reserved":12000}\n');
    write(f.worker, 'meta/791/7918308.json', '{"id":"7918308","likes":39}\n');
    const result = runSave(f);
    assert.equal(result.status, 1);
    assert.match(result.stdout, /refusing to merge stale reservation accounting/);
    assert.equal(git(f.remote, 'rev-parse', 'main'), upstream);
    assert.equal(git(f.remote, 'show', 'main:meta/request_budget.json'), '{"reserved":9999,"upstream":true}');
});

test('persistent push rejection fails after six attempts and keeps the reservation durable', (t) => {
    const f = fixture(t);
    write(f.worker, 'meta/request_budget.json', '{"reserved":12000}\n');
    assertSuccess(runSave(f, 'chore: reserve metadata request budget'));
    const reservation = git(f.remote, 'rev-parse', 'main');
    write(f.worker, 'meta/791/7918308.json', '{"id":"7918308","likes":39}\n');
    const hook = path.join(f.remote, 'hooks/pre-receive');
    fs.writeFileSync(hook, '#!/bin/sh\nexit 1\n');
    fs.chmodSync(hook, 0o755);
    const result = runSave(f);
    assert.equal(result.status, 1);
    assert.match(result.stdout, /after six attempts/);
    assert.equal(git(f.remote, 'rev-parse', 'main'), reservation);
    assert.equal(git(f.remote, 'show', 'main:meta/791/7918308.json'), '{"id":"7918308"}');
});
