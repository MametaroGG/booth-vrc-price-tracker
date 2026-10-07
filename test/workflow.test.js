const assert = require('node:assert/strict');
const { execFileSync, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const test = require('node:test');

const workflow = fs.readFileSync(path.join(__dirname, '../.github/workflows/daily_scrape.yml'), 'utf8');

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

const commitScriptPath = path.join(__dirname, '../scripts/push-data.sh');
const commitScript = fs.readFileSync(commitScriptPath, 'utf8');
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
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'boopa-workflow-'));
    t.after(() => fs.rmSync(root, { recursive: true, force: true }));
    const remote = path.join(root, 'remote.git');
    const seed = path.join(root, 'seed');
    const worker = path.join(root, 'worker');
    git(root, 'init', '--bare', '--initial-branch=main', remote);
    git(root, 'init', '--initial-branch=main', seed);
    git(seed, 'config', 'user.name', 'Workflow Test');
    git(seed, 'config', 'user.email', 'workflow@example.invalid');
    write(seed, 'data/products.json', '{"value":"original"}\n');
    write(seed, 'README.md', 'original\n');
    commit(seed, 'Initial data');
    write(seed, 'history.txt', 'Older history should not be fetched\n');
    commit(seed, 'Older history');
    if (branch !== 'main') git(seed, 'checkout', '-b', branch);
    git(seed, 'remote', 'add', 'origin', pathToFileURL(remote).href);
    git(seed, 'push', 'origin', ...new Set(['main', branch]));
    git(root, 'clone', '--depth=1', '--branch', branch, pathToFileURL(remote).href, worker);
    assert.equal(git(worker, 'rev-parse', '--is-shallow-repository'), 'true');
    assert.equal(git(worker, 'rev-list', '--count', 'HEAD'), '1');
    return { root, remote, seed, worker, branch };
}

function runSave(f, message) {
    return spawnSync('bash', [commitScriptPath, ...(message ? [message] : [])], {
        cwd: f.worker,
        env: { ...gitEnv, GITHUB_REF: `refs/heads/${f.branch}`, DEFAULT_BRANCH: 'main' },
        encoding: 'utf8',
        timeout: 15000,
    });
}

function assertSuccess(result) {
    assert.equal(result.error, undefined);
    assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
}

test('workflow budgets setup and saving, tests first, and exposes scraper failures', () => {
    assert.match(workflow, /    timeout-minutes: 360\n/);
    assert.ok(workflow.indexOf('- name: Record job start') < workflow.indexOf('- name: Checkout'));
    assert.match(step('Record job start'), /SCRAPER_JOB_STARTED_AT=.*GITHUB_ENV/);
    assert.match(step('Record job start'), /GITHUB_REF.*refs\/heads\/\$DEFAULT_BRANCH/);
    assert.match(workflow, /DEFAULT_BRANCH: \$\{\{ github\.event\.repository\.default_branch \}\}/);
    assert.match(workflow, /SCRAPER_RESERVATION_ID: \$\{\{ github\.run_id \}\}-\$\{\{ github\.run_attempt \}\}/);
    assert.match(step('Checkout'), /fetch-depth: 1\n/);
    assert.match(step('Checkout'), /ref: \$\{\{ env\.DEFAULT_BRANCH \}\}/);
    assert.ok(workflow.indexOf('- name: Run tests') < workflow.indexOf('- name: Reserve request budget'));
    assert.ok(workflow.indexOf('- name: Reserve request budget') < workflow.indexOf('- name: Commit reservation'));
    assert.ok(workflow.indexOf('- name: Commit reservation') < workflow.indexOf('- name: Run Scraper'));
    assert.match(step('Run tests'), /run: npm test/);
    assert.match(step('Reserve request budget'), /run: node src\/reserve-budget\.js/);
    assert.match(script('Commit reservation'), /bash scripts\/push-data\.sh "chore: reserve scrape request budget"/);
    assert.doesNotMatch(step('Reserve request budget') + step('Commit reservation'), /continue-on-error|if:/);
    assert.match(step('Run Scraper'), /id: scraper/);
    assert.match(step('Run Scraper'), /timeout-minutes: 305/);
    assert.match(step('Run Scraper'), /continue-on-error: true/);
    assert.match(step('Commit and Push'), /!cancelled\(\).*steps\.scraper\.outcome == 'success'.*steps\.scraper\.outcome == 'failure'/);
    assert.match(step('Commit and Push'), /run: bash scripts\/push-data\.sh/);
    assert.match(step('Report scraper failure'), /always\(\).*steps\.scraper\.outcome == 'failure'/);
    assert.match(script('Report scraper failure'), /exit 1/);
    const timeouts = [...workflow.matchAll(/^        timeout-minutes: (\d+)$/gm)].map((match) => Number(match[1]));
    assert.equal(timeouts.length, 11);
    assert.equal(timeouts.reduce((sum, minutes) => sum + minutes, 0), 359);
    assert.ok(timeouts.reduce((sum, minutes) => sum + minutes, 0) < 360);
    assert.doesNotMatch(commitScript, /(?:--force|git pull|--unshallow)/);
});

test('continuation requires a successful scraper, final save and explicit safe output without added permissions', () => {
    assert.match(workflow, /repository_dispatch:\s+types: \[continue-scrape\]/);
    assert.match(workflow, /group: scrape-group\s+cancel-in-progress: false/);
    assert.match(step('Commit and Push'), /id: save/);
    const continuation = step('Continue collection');
    assert.ok(workflow.indexOf('- name: Commit and Push') < workflow.indexOf('- name: Continue collection'));
    assert.match(continuation, /success\(\).*steps\.scraper\.outcome == 'success'.*steps\.save\.outcome == 'success'.*steps\.scraper\.outputs\.continue_collection == 'true'/);
    assert.match(continuation, /run: node src\/continuation\.js/);
    assert.match(continuation, /GITHUB_TOKEN: \$\{\{ github\.token \}\}/);
    assert.match(workflow, /permissions:\s+contents: write/);
    assert.doesNotMatch(workflow, /actions: write|secrets\./);
});

test('recording job start permits only the default branch', (t) => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'boopa-workflow-start-'));
    t.after(() => fs.rmSync(root, { recursive: true, force: true }));
    const envFile = path.join(root, 'env');
    for (const [ref, status] of [['refs/tags/v1', 1], ['refs/heads/test/scraper', 1], ['refs/heads/main', 0]]) {
        fs.writeFileSync(envFile, '');
        const result = spawnSync('bash', ['-e', '-c', script('Record job start')], {
            env: { ...process.env, GITHUB_ENV: envFile, GITHUB_REF: ref, DEFAULT_BRANCH: 'main' },
            encoding: 'utf8',
        });
        assert.equal(result.status, status);
        assert.match(fs.readFileSync(envFile, 'utf8'), /^SCRAPER_JOB_STARTED_AT=\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n$/);
    }
});

test('unchanged data exits successfully without making a commit', (t) => {
    const f = fixture(t);
    const before = git(f.remote, 'rev-parse', 'main');
    const result = runSave(f);
    assertSuccess(result);
    assert.match(result.stdout, /No product data or checkpoint changes/);
    assert.equal(git(f.remote, 'rev-parse', 'main'), before);
    assert.equal(git(f.worker, 'rev-parse', 'HEAD'), before);
});

test('saves only data and checkpoints, excluding unrelated staged files', (t) => {
    const f = fixture(t);
    write(f.worker, 'data/products.json', '{"value":"collected"}\n');
    write(f.worker, 'data/crawl_state.json', '{"page":2}\n');
    write(f.worker, 'README.md', 'unrelated staged change\n');
    git(f.worker, 'add', 'README.md');
    assertSuccess(runSave(f));
    assert.equal(git(f.remote, 'show', `${f.branch}:data/products.json`), '{"value":"collected"}');
    assert.equal(git(f.remote, 'show', `${f.branch}:data/crawl_state.json`), '{"page":2}');
    assert.equal(git(f.remote, 'show', `${f.branch}:README.md`), 'original');
    assert.equal(git(f.worker, 'rev-parse', '--is-shallow-repository'), 'true');
});

test('the push script refuses non-default branches even outside the workflow', (t) => {
    const f = fixture(t, 'test/scraper');
    const main = git(f.remote, 'rev-parse', 'main');
    const branch = git(f.remote, 'rev-parse', f.branch);
    write(f.worker, 'data/request_budget.json', '{"reserved":10000}\n');
    const result = runSave(f);
    assert.equal(result.status, 1);
    assert.match(result.stdout, /must use the repository's default branch/);
    assert.equal(git(f.remote, 'rev-parse', 'main'), main);
    assert.equal(git(f.remote, 'rev-parse', f.branch), branch);
});

test('a reservation is durable before subsequent collection results are saved', (t) => {
    const f = fixture(t);
    write(f.worker, 'data/request_budget.json', '{"reserved":10000}\n');
    assertSuccess(runSave(f, 'chore: reserve scrape request budget'));
    const reservation = git(f.remote, 'rev-parse', 'main');
    assert.equal(git(f.remote, 'show', 'main:data/request_budget.json'), '{"reserved":10000}');
    assert.equal(git(f.remote, 'log', '-1', '--format=%s', 'main'), 'chore: reserve scrape request budget');
    write(f.worker, 'data/products.json', '{"value":"collected"}\n');
    write(f.worker, 'data/request_budget.json', '{"reserved":10000,"attempts":5}\n');
    assertSuccess(runSave(f));
    assert.equal(git(f.remote, 'rev-parse', 'main^'), reservation);
    assert.equal(git(f.remote, 'show', 'main:data/products.json'), '{"value":"collected"}');
});

test('a failed final push leaves the earlier request reservation durable', (t) => {
    const f = fixture(t);
    write(f.worker, 'data/request_budget.json', '{"reserved":10000}\n');
    assertSuccess(runSave(f, 'chore: reserve scrape request budget'));
    const reservation = git(f.remote, 'rev-parse', 'main');
    write(f.worker, 'data/products.json', '{"value":"collected"}\n');
    write(f.worker, 'data/request_budget.json', '{"reserved":10000,"attempts":5,"closed":true}\n');
    const hook = path.join(f.remote, 'hooks/pre-receive');
    fs.writeFileSync(hook, '#!/bin/sh\nexit 1\n');
    fs.chmodSync(hook, 0o755);
    const result = runSave(f);
    assert.equal(result.status, 1);
    assert.equal(git(f.remote, 'rev-parse', 'main'), reservation);
    assert.equal(git(f.remote, 'show', 'main:data/request_budget.json'), '{"reserved":10000}');
    assert.equal(git(f.remote, 'show', 'main:data/products.json'), '{"value":"original"}');
});

test('replays the single data commit after upstream advances beyond shallow history', (t) => {
    const f = fixture(t);
    write(f.worker, 'data/products.json', '{"value":"collected"}\n');
    for (let index = 0; index < 3; index++) {
        write(f.seed, 'README.md', `upstream ${index}\n`);
        commit(f.seed, `Upstream update ${index}`);
    }
    git(f.seed, 'push', 'origin', 'main');
    const upstream = git(f.remote, 'rev-parse', 'main');
    assertSuccess(runSave(f));
    assert.equal(git(f.remote, 'rev-parse', 'main^'), upstream);
    assert.equal(git(f.remote, 'show', 'main:data/products.json'), '{"value":"collected"}');
    assert.equal(git(f.remote, 'show', 'main:README.md'), 'upstream 2');
    assert.equal(git(f.worker, 'rev-parse', '--is-shallow-repository'), 'true');
    assert.equal(git(f.worker, 'rev-list', '--count', 'HEAD'), '2');
});

test('a detached checkout can save to the explicit branch', (t) => {
    const f = fixture(t);
    git(f.worker, 'checkout', '--detach', 'HEAD');
    write(f.worker, 'data/request_budget.json', '{"attempts":10}\n');
    assertSuccess(runSave(f));
    assert.equal(git(f.remote, 'show', 'main:data/request_budget.json'), '{"attempts":10}');
});

test('data already saved upstream does not create a duplicate or fail', (t) => {
    const f = fixture(t);
    const value = '{"value":"same checkpoint"}\n';
    write(f.worker, 'data/products.json', value);
    write(f.seed, 'data/products.json', value);
    commit(f.seed, 'Already saved checkpoint');
    git(f.seed, 'push', 'origin', 'main');
    const upstream = git(f.remote, 'rev-parse', 'main');
    assertSuccess(runSave(f));
    assert.equal(git(f.remote, 'rev-parse', 'main'), upstream);
    assert.equal(git(f.worker, 'rev-parse', 'HEAD'), upstream);
});

test('an identical reservation already saved upstream is safe to retry', (t) => {
    const f = fixture(t);
    const value = '{"reservation":"same-run","reserved":10000}\n';
    write(f.worker, 'data/request_budget.json', value);
    write(f.seed, 'data/request_budget.json', value);
    commit(f.seed, 'Already saved reservation');
    git(f.seed, 'push', 'origin', 'main');
    const upstream = git(f.remote, 'rev-parse', 'main');
    assertSuccess(runSave(f));
    assert.equal(git(f.remote, 'rev-parse', 'main'), upstream);
});

test('upstream quota changes cannot be auto-merged with stale accounting', (t) => {
    const f = fixture(t);
    write(f.worker, 'data/request_budget.json', '{"reservation":"local","reserved":10000}\n');
    write(f.seed, 'data/request_budget.json', '{"reservation":"remote","reserved":20000}\n');
    commit(f.seed, 'Newer request reservation');
    git(f.seed, 'push', 'origin', 'main');
    const upstream = git(f.remote, 'rev-parse', 'main');
    const result = runSave(f);
    assert.equal(result.status, 1);
    assert.match(result.stdout, /refusing to merge stale reservation accounting/);
    assert.equal(git(f.remote, 'rev-parse', 'main'), upstream);
    assert.equal(git(f.remote, 'show', 'main:data/request_budget.json'), '{"reservation":"remote","reserved":20000}');
    assert.equal(git(f.worker, 'show', 'HEAD:data/request_budget.json'), '{"reservation":"local","reserved":10000}');
});

test('an upstream change between fetch and push is retried without force', (t) => {
    const f = fixture(t);
    write(f.worker, 'data/products.json', '{"value":"collected"}\n');
    const quote = (value) => `'${value.replaceAll("'", "'\\''")}'`;
    const marker = path.join(f.root, 'raced');
    const hook = path.join(f.worker, '.git/hooks/pre-push');
    fs.writeFileSync(hook, `#!/bin/sh\nset -eu\nif [ -e ${quote(marker)} ]; then exit 0; fi\ntouch ${quote(marker)}\nunset $(git rev-parse --local-env-vars)\nprintf 'raced update\\n' > ${quote(path.join(f.seed, 'README.md'))}\ngit -C ${quote(f.seed)} add README.md\ngit -C ${quote(f.seed)} commit -m 'Concurrent push'\ngit -C ${quote(f.seed)} push origin main\n`);
    fs.chmodSync(hook, 0o755);
    const result = runSave(f);
    assertSuccess(result);
    assert.match(result.stdout, /Push attempt 1 failed/);
    assert.equal(git(f.remote, 'show', 'main:README.md'), 'raced update');
    assert.equal(git(f.remote, 'show', 'main:data/products.json'), '{"value":"collected"}');
    assert.equal(git(f.remote, 'rev-parse', 'main^'), git(f.seed, 'rev-parse', 'HEAD'));
});

test('conflicting remote data fails and preserves the remote and local checkpoint', (t) => {
    const f = fixture(t);
    write(f.worker, 'data/products.json', '{"value":"local checkpoint"}\n');
    write(f.seed, 'data/products.json', '{"value":"newer remote data"}\n');
    commit(f.seed, 'Update remote product');
    git(f.seed, 'push', 'origin', 'main');
    const upstream = git(f.remote, 'rev-parse', 'main');
    const result = runSave(f);
    assert.equal(result.status, 1, `${result.stdout}\n${result.stderr}`);
    assert.match(result.stdout, /refusing to overwrite/);
    assert.equal(git(f.remote, 'rev-parse', 'main'), upstream);
    assert.equal(git(f.remote, 'show', 'main:data/products.json'), '{"value":"newer remote data"}');
    assert.equal(git(f.worker, 'show', 'HEAD:data/products.json'), '{"value":"local checkpoint"}');
    assert.equal(git(f.worker, 'status', '--porcelain'), '');
});

test('a real commit failure is not mistaken for unchanged data', (t) => {
    const f = fixture(t);
    const before = git(f.remote, 'rev-parse', 'main');
    write(f.worker, 'data/products.json', '{"value":"collected"}\n');
    const hook = path.join(f.worker, '.git/hooks/pre-commit');
    fs.writeFileSync(hook, '#!/bin/sh\nexit 1\n');
    fs.chmodSync(hook, 0o755);
    const result = runSave(f);
    assert.notEqual(result.status, 0);
    assert.doesNotMatch(result.stdout, /No product data or checkpoint changes/);
    assert.equal(git(f.remote, 'rev-parse', 'main'), before);
    assert.equal(git(f.worker, 'rev-parse', 'HEAD'), before);
});

test('persistent push rejection fails after three attempts', (t) => {
    const f = fixture(t);
    const before = git(f.remote, 'rev-parse', 'main');
    write(f.worker, 'data/products.json', '{"value":"collected"}\n');
    const hook = path.join(f.remote, 'hooks/pre-receive');
    fs.writeFileSync(hook, '#!/bin/sh\nexit 1\n');
    fs.chmodSync(hook, 0o755);
    const result = runSave(f);
    assert.equal(result.status, 1, `${result.stdout}\n${result.stderr}`);
    assert.equal((result.stdout.match(/Push attempt \d failed/g) || []).length, 3);
    assert.match(result.stdout, /Could not push product data and checkpoints/);
    assert.equal(git(f.remote, 'rev-parse', 'main'), before);
});
