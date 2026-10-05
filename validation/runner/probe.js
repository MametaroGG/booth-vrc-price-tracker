'use strict';

// Inert by default. Only the operator may select --execute after approval
// and an independently verified exclusive, accounted-for JST-day window.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync, fork } = require('node:child_process');
const { performance } = require('node:perf_hooks');
const { plainText, safeResponse, safeUrl } = require('./diagnostics');

const HOME = fs.realpathSync(__dirname);
const SOURCE_COMMIT = 'abe8b896c2165004b5ccbc618cf97da4a9ab4f26';
const EXPECTED_RUNTIME_COMMIT = '4aedd907f01f10ce5eb36f69401fff4dadf89383';
const PRIOR_CLOUD_REQUESTS = 2;
const PRIOR_LEDGER = Object.freeze({ date: '2026-10-05', requests: 2, blockedUntil: 1791179136081,
    laneUsage: { refresh: 2, discovery: 0 }, laneReleased: { refresh: false, discovery: true } });
const LIMITS = Object.freeze({ maxHttpAttempts: 20, selectedIds: 10, concurrency: 1,
    intervalMs: 1000, timeoutMs: 30000, maxAttemptsPerItem: 2,
    maxRedirectsPerItem: 3, workRuntimeMs: 285000, hardRuntimeMs: 295000,
    dailyLimit: 48000, maxResponseBytes: 4 * 1024 * 1024 });
const jstDate = time => new Date(time + 9 * 3600000).toISOString().slice(0, 10);
const inside = (child, operator) => child === operator || child.startsWith(operator + path.sep);
const sha256 = data => crypto.createHash('sha256').update(data).digest('hex');
const git = (repo, args) => execFileSync('git', ['--no-lazy-fetch', '-C', repo, ...args], {
    encoding: 'utf8', maxBuffer: 32 * 1024 * 1024, timeout: 15000,
    env: { ...process.env, GIT_NO_LAZY_FETCH: '1', GIT_ALLOW_PROTOCOL: '' } });
const errorInfo = error => ({ message: plainText(error?.message || String(error), 300),
    reason: error?.reason || null, code: error?.code || null });

function accounting(scope = 'full-day') {
    if (!['full-day', 'incremental-exception'].includes(scope)) throw new Error('Unknown accounting scope');
    return scope === 'incremental-exception'
        ? { accountingScope: scope, knownScope: 'probe-only', ceiling: LIMITS.maxHttpAttempts,
            fullDayComplianceEstablished: false,
            notice: 'ONE-TIME EXCEPTION: legacy daily usage is unknown; this ledger bounds this probe only, not the full-day aggregate' }
        : { accountingScope: scope, knownScope: 'all-collectors-jst-day', ceiling: LIMITS.dailyLimit,
            fullDayComplianceEstablished: 'conditional-on-operator-proven-full-day-accounting',
            notice: 'Full-day mode requires proven conservative usage for all collectors and continued accounting for all later same-day traffic' };
}

function atomicJson(file, object) {
    const temporary = `${file}.tmp`;
    fs.writeFileSync(temporary, JSON.stringify(object, null, 2) + '\n', { mode: 0o600 });
    fs.renameSync(temporary, file);
}

function getPlan(repo) {
    repo = fs.realpathSync(repo);
    if (inside(HOME, repo) || inside(repo, HOME)) throw new Error('Harness and repository must be separate directories');
    const sourceCommit = git(repo, ['rev-parse', `${SOURCE_COMMIT}^{commit}`]).trim();
    if (sourceCommit !== SOURCE_COMMIT) throw new Error('Unexpected catalog source commit');
    const records = git(repo, ['ls-tree', '-r', SOURCE_COMMIT, '--', 'data'])
        .split('\n').map(line => /^100644 blob ([0-9a-f]{40})\t(data\/[1-9]\d{2}\/[1-9]\d*\.json)$/.exec(line))
        .filter(Boolean).map(match => ({ file: match[2], blobSha: match[1], id: path.basename(match[2], '.json') }))
        .filter(({ file, id }) => file === `data/${id.slice(0, 3)}/${id}.json`);
    if (records.length < LIMITS.selectedIds) throw new Error('Not enough existing catalog IDs');
    const selected = Array.from({ length: LIMITS.selectedIds }, (_, index) =>
        records[Math.floor(index * (records.length - 1) / (LIMITS.selectedIds - 1))]);
    const sourceHashes = Object.fromEntries(['src/collection-runtime.js', 'src/scraper.js', 'package-lock.json']
        .map(file => [file, sha256(fs.readFileSync(path.join(repo, file)))]));
    return { repo, catalogSourceCommit: sourceCommit, runtimeHeadCommit: git(repo, ['rev-parse', 'HEAD']).trim(),
        runtimeSourceSha256: sourceHashes, sourceWorkingTree: git(repo, ['status', '--short']).trim(),
        catalogIdsAtSource: records.length, selected, limits: LIMITS };
}

function loadHistory(plan, selected, historyCache) {
    let bytes;
    if (historyCache) {
        const root = fs.realpathSync(path.resolve(historyCache));
        if (!inside(root, HOME) || inside(root, plan.repo)) throw new Error('History cache must be isolated inside the harness directory');
        const file = path.join(root, selected.file);
        if (fs.existsSync(file)) {
            if (fs.realpathSync(file) !== file || !fs.lstatSync(file).isFile()) throw new Error('History cache cannot contain symlinked/non-file inputs');
            bytes = fs.readFileSync(file);
        }
    }
    bytes ??= Buffer.from(git(plan.repo, ['show', `${SOURCE_COMMIT}:${selected.file}`]), 'utf8');
    const blobSha = crypto.createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex');
    if (blobSha !== selected.blobSha) throw new Error(`History blob hash mismatch for ${selected.file}`);
    return bytes.toString('utf8');
}

function validateExecution({ budgetFile, expectedJstDay, exclusiveUntil, repo, accountingScope = 'full-day' }, now = Date.now()) {
    const scope = accounting(accountingScope);
    if (!budgetFile || !expectedJstDay || !exclusiveUntil) {
        throw new Error('Execution requires an existing --budget-file, --expected-jst-day, and --exclusive-until');
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(expectedJstDay) || expectedJstDay !== jstDate(now)) {
        throw new Error('Expected JST day must exactly match the current JST day; no day reset is permitted');
    }
    const until = Date.parse(exclusiveUntil);
    if (!Number.isFinite(until) || until < now + LIMITS.hardRuntimeMs || jstDate(now + LIMITS.hardRuntimeMs) !== expectedJstDay) {
        throw new Error('Verified exclusive window must cover the full watchdog and remain in the expected JST day');
    }
    const suppliedPath = path.resolve(budgetFile);
    const actualPath = fs.realpathSync(suppliedPath); // Missing ledger is fatal; never bootstrap one here.
    if (suppliedPath !== actualPath || !inside(actualPath, HOME) || inside(actualPath, repo) ||
        !fs.lstatSync(actualPath).isFile() || fs.statSync(actualPath).nlink !== 1) {
        throw new Error('Budget must be a regular, non-symlink, non-hardlinked file inside the isolated harness directory');
    }
    const budget = JSON.parse(fs.readFileSync(actualPath, 'utf8'));
    if (budget.accountingScope !== scope.accountingScope || budget.knownScope !== scope.knownScope) {
        throw new Error(`Ledger scope must explicitly match ${scope.accountingScope} / ${scope.knownScope}; never relabel an unknown aggregate as full-day compliance`);
    }
    if (budget.date !== expectedJstDay || !Number.isSafeInteger(budget.requests) || budget.requests < 0 ||
        budget.requests >= scope.ceiling || !Number.isFinite(budget.blockedUntil) || budget.blockedUntil < 0 ||
        budget.blockedUntil > now || (budget.reservation && !budget.reservation.completed)) {
        throw new Error('Ledger is wrong-day, exhausted, malformed, cooling down, or has an unresolved reservation');
    }
    return { budgetFile: actualPath, budget, allowance: Math.min(LIMITS.maxHttpAttempts, scope.ceiling - budget.requests),
        exclusiveUntil: until, expectedJstDay, ...scope };
}

function validateRunnerContext(authorization, environment = process.env) {
    if (environment.GITHUB_ACTIONS !== 'true' || environment.GITHUB_RUN_ATTEMPT !== '1' ||
        !/^[1-9]\d*$/.test(environment.GITHUB_RUN_ID || '') ||
        environment.GITHUB_REPOSITORY !== 'MametaroGG/booth-vrc-price-tracker') {
        throw new Error('Runner live work requires the expected GitHub repository and first run_attempt only; reruns are forbidden');
    }
    if (authorization.accountingScope !== 'incremental-exception' ||
        authorization.budget.requests < PRIOR_CLOUD_REQUESTS ||
        authorization.budget.date !== PRIOR_LEDGER.date ||
        authorization.budget.blockedUntil < PRIOR_LEDGER.blockedUntil ||
        authorization.budget.laneUsage?.refresh < PRIOR_LEDGER.laneUsage.refresh ||
        !Number.isSafeInteger(authorization.budget.laneUsage?.refresh) ||
        !Number.isSafeInteger(authorization.budget.laneUsage?.discovery) || authorization.budget.laneUsage.discovery < 0 ||
        authorization.budget.laneReleased?.refresh !== false || authorization.budget.laneReleased?.discovery !== true) {
        throw new Error('Runner ledger must preserve the authoritative prior date, 2 cloud charges, cooldown, and lane state in the explicit probe-only exception scope');
    }
    if (authorization.budget.runnerRunId && authorization.budget.runnerRunId !== environment.GITHUB_RUN_ID) {
        throw new Error('Ledger is bound to another GitHub run; never reset/rebind it after an unknown outcome');
    }
    return { runId: environment.GITHUB_RUN_ID, runAttempt: 1, priorCloudRequests: PRIOR_CLOUD_REQUESTS,
        maximumAdditionalRequests: authorization.allowance };
}

function verifyPinnedRuntime(repo, readGit = git) {
    if (!/^[0-9a-f]{40}$/.test(EXPECTED_RUNTIME_COMMIT)) throw new Error('Full PR runtime commit pin has not been supplied');
    const pin = readGit(repo, ['rev-parse', `${EXPECTED_RUNTIME_COMMIT}^{commit}`]).trim();
    if (pin !== EXPECTED_RUNTIME_COMMIT) throw new Error('Runtime commit pin mismatch');
    readGit(repo, ['merge-base', '--is-ancestor', EXPECTED_RUNTIME_COMMIT, 'HEAD']);
    for (const file of ['src/collection-runtime.js', 'src/scraper.js', 'package-lock.json']) {
        // Tree metadata is enough to verify the checked-out bytes; do not lazy
        // fetch a second copy of each blob from a partial clone.
        const pinned = readGit(repo, ['rev-parse', `${EXPECTED_RUNTIME_COMMIT}:${file}`]).trim();
        const bytes = fs.readFileSync(path.join(repo, file));
        const actual = crypto.createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex');
        if (pinned !== actual) {
            throw new Error(`Runtime file differs from the reviewed PR commit: ${file}`);
        }
    }
    return pin;
}

// transport is injected. Tests always use fake functions; only executeWorker
// below may provide axios.get, after all explicit live-mode checks pass.
async function runProbe({ plan, authorization, outputDir, transport, now = Date.now,
    mono = () => performance.now(), wait, runtime, scraper, writeReport = atomicJson,
    transportMode = 'injected-offline', readHistory = selected => loadHistory(plan, selected) }) {
    const start = now();
    const deadline = Math.min(start + LIMITS.workRuntimeMs, authorization.exclusiveUntil);
    const startedMono = mono();
    const dataDir = path.join(outputDir, 'data');
    fs.mkdirSync(dataDir);
    const summaryFile = path.join(outputDir, 'summary.json');
    const eventsFile = path.join(outputDir, 'requests.jsonl');
    const report = { mode: transportMode, ...plan, accounting: accounting(authorization.accountingScope),
        startedAt: new Date(start).toISOString(), deadline: new Date(deadline).toISOString(),
        expectedJstDay: authorization.expectedJstDay,
        budgetBefore: structuredClone(authorization.budget), effectiveAllowance: authorization.allowance,
        status: 'running', stop: null, preloggedAttempts: 0, actualHttpAttempts: 0, chargedAttempts: 0,
        redirects: 0, maxActiveHttp: 0, items: [], errors: [] };
    const flush = () => writeReport(summaryFile, report);
    const event = value => fs.appendFileSync(eventsFile, JSON.stringify(value) + '\n', { mode: 0o600 });
    let active = 0;
    let lastStart = -Infinity;
    let currentItem;
    let client;
    const allowedIds = new Set(plan.selected.map(item => item.id));
    function guard() {
        if (now() >= deadline) throw new runtime.CollectionStop('deadline', 'Probe time limit reached');
        if (jstDate(now()) !== authorization.expectedJstDay) throw new runtime.CollectionStop('day-boundary', 'Expected JST day changed');
    }
    const measuredGet = async (url, config) => {
        guard();
        const target = new URL(url);
        const match = /^\/(?:ja\/|en\/)?items\/([1-9]\d*)\/?$/.exec(decodeURIComponent(target.pathname));
        if (target.protocol !== 'https:' || target.port !== '' || target.username || target.password ||
            !(target.hostname === 'booth.pm' || target.hostname.endsWith('.booth.pm')) ||
            !match || !allowedIds.has(match[1]) || match[1] !== currentItem.id) {
            throw new runtime.CollectionStop('target', 'Refused a request outside the selected existing product IDs', true);
        }
        if (report.actualHttpAttempts >= authorization.allowance) throw new runtime.CollectionStop('probe-cap', 'Probe HTTP attempt ceiling reached');
        if (active !== 0 || config.maxRedirects !== 0) {
            throw new runtime.CollectionStop('safety', 'Concurrency or redirect invariant failed', true);
        }
        // The runtime gate precedes local logging. This extra conservative gate
        // ensures those writes never shorten the real transport-start interval.
        const pause = LIMITS.intervalMs - (mono() - lastStart);
        if (pause > 0) await (wait || (ms => new Promise(resolve => setTimeout(resolve, ms))))(pause);
        guard();
        report.preloggedAttempts++;
        const attempt = { sequence: report.preloggedAttempts, id: currentItem.id, url: safeUrl(url),
            preloggedAt: new Date(now()).toISOString(), startedAt: null, transportInvoked: false,
            status: null, httpElapsedMs: null, timeoutMs: config.timeout, error: null };
        // Persist the conservative start record before transport; a process crash
        // cannot make a possibly transmitted request vanish from the local log.
        event({ ...attempt, phase: 'pre-dispatch' });
        flush();
        let before;
        try {
            // Logging itself can cross midnight/the deadline. Keep the durable
            // charge but never transmit when that final write used the window.
            guard();
            attempt.startedAt = new Date(now()).toISOString();
            before = mono();
            lastStart = before;
            active++;
            report.maxActiveHttp = Math.max(report.maxActiveHttp, active);
            guard(); // Last check immediately before the transport invocation.
            report.actualHttpAttempts++;
            currentItem.httpAttempts++;
            attempt.transportInvoked = true;
            const response = await transport(url, { ...config, maxContentLength: LIMITS.maxResponseBytes });
            attempt.status = response.status;
            attempt.responseMetadata = safeResponse(response);
            if ([301, 302, 303, 307, 308].includes(response.status)) {
                report.redirects++;
                currentItem.redirectCount++;
                attempt.location = response.headers?.location ? safeUrl(response.headers.location, url) : null;
            }
            // A fake transport must emulate axios's rejection semantics too.
            if (response.status >= 400) {
                const error = new Error(`HTTP ${response.status}`);
                error.response = response;
                throw error;
            }
            return response;
        } catch (error) {
            attempt.status = error.response?.status || attempt.status;
            attempt.responseMetadata = safeResponse(error.response) || attempt.responseMetadata || null;
            attempt.error = errorInfo(error);
            throw error;
        } finally {
            if (before !== undefined) active--;
            if (attempt.transportInvoked) {
                attempt.httpElapsedMs = Math.max(0, mono() - before);
                currentItem.httpElapsedMs += attempt.httpElapsedMs;
            }
            event({ ...attempt, phase: 'complete' });
            flush();
        }
    };

    try {
        // Materialize every required historical blob before any HTTP. Partial
        // clone misses fail locally; Git lazy fetching is explicitly disabled.
        const histories = new Map();
        for (const selected of plan.selected) {
            guard();
            const copyStart = mono();
            const historical = readHistory(selected);
            const previous = JSON.parse(historical);
            if (String(previous.id) !== selected.id) throw new Error('Catalog history identity mismatch');
            const file = path.join(dataDir, selected.id.slice(0, 3), `${selected.id}.json`);
            fs.mkdirSync(path.dirname(file), { recursive: true });
            fs.writeFileSync(file, historical);
            histories.set(selected.id, { historical, elapsedMs: Math.max(0, mono() - copyStart) });
        }
        // A run-local ceiling is also enforced inside the production request
        // client, so redirected/retried requests cannot use the whole day quota.
        client = runtime.createRequestClient({ get: measuredGet, budgetFile: authorization.budgetFile,
            deadline, now, ...(wait ? { wait } : {}), laneBudgets: true,
            dailyLimit: authorization.budget.requests + authorization.allowance,
            intervalMs: LIMITS.intervalMs, timeoutMs: LIMITS.timeoutMs,
            maxAttempts: LIMITS.maxAttemptsPerItem, failureThreshold: 2 });
        // No discovery lane exists in this ten-ID probe. Freeing its share avoids
        // an irrelevant 90/10 reduction while retaining day-boundary protection.
        client.releaseLane('discovery');
        flush();
        for (const selected of plan.selected) {
            guard();
            client.check();
            const file = path.join(dataDir, selected.id.slice(0, 3), `${selected.id}.json`);
            const { historical, elapsedMs } = histories.get(selected.id);
            currentItem = { id: selected.id, sourcePath: selected.file, historicalSha256: sha256(historical),
                historyCopyElapsedMs: elapsedMs, httpAttempts: 0,
                redirectCount: 0, httpElapsedMs: 0, requestTotalElapsedMs: 0,
                parsingElapsedMs: 0, saveElapsedMs: 0, kind: 'pending', error: null };
            report.items.push(currentItem);
            let response;
            const requestStart = mono();
            try {
                response = await client.get(`https://booth.pm/ja/items/${selected.id}`, { productId: selected.id });
            } finally {
                currentItem.requestTotalElapsedMs = Math.max(0, mono() - requestStart);
            }
            currentItem.finalStatus = response.status;
            guard();
            const parseStart = mono();
            // This client replays the already-received response. Parsing performs
            // no second HTTP request and is measured separately from transport.
            const parsed = await scraper.scrapeProductDetails(selected.id, { get: async () => response });
            currentItem.parsingElapsedMs = Math.max(0, mono() - parseStart);
            currentItem.kind = parsed.kind;
            if (parsed.kind === 'failure') {
                currentItem.error = errorInfo(parsed.error);
                throw new runtime.CollectionStop('parse-failure', parsed.error.message, true);
            }
            if (parsed.kind === 'success') {
                guard();
                const saveStart = mono();
                await scraper.saveProductData(parsed.product, { dataDir, today: authorization.expectedJstDay });
                currentItem.saveElapsedMs = Math.max(0, mono() - saveStart);
                currentItem.savedSha256 = sha256(fs.readFileSync(file));
            }
            flush();
        }
        report.status = 'completed';
    } catch (error) {
        report.status = 'stopped';
        report.stop = errorInfo(error);
        report.errors.push(errorInfo(error));
        if (currentItem?.kind === 'pending') {
            currentItem.kind = 'failure';
            currentItem.error = errorInfo(error);
        }
    } finally {
        // finish() does not issue HTTP. Any persisted cooldown is retained.
        client?.finish();
        report.budgetAfter = client?.getBudget() || JSON.parse(fs.readFileSync(authorization.budgetFile, 'utf8'));
        report.chargedAttempts = report.budgetAfter.requests - authorization.budget.requests;
        report.elapsedMs = Math.max(0, mono() - startedMono);
        report.completedAt = new Date(now()).toISOString();
        report.outputDir = outputDir;
        const cooldownActive = report.budgetAfter.blockedUntil > now();
        report.legacyResume = {
            automatic: false,
            status: cooldownActive || report.status !== 'completed' ? 'blocked-pending-operator-reconciliation' : 'requires-operator-review-and-prior-authority',
            blockedUntil: report.budgetAfter.blockedUntil,
            notice: 'Never resume blindly after 403/429, retained Retry-After, timeout/circuit stop, or an interrupted/unknown outcome. The nominal exclusive-window expiry does not clear a cooldown. This report does not authorize workflow changes.'
        };
        flush();
    }
    return report;
}

function parseArgs(args) {
    const result = { execute: false, accountingScope: 'full-day' };
    const options = { '--budget-file': 'budgetFile', '--expected-jst-day': 'expectedJstDay',
        '--exclusive-until': 'exclusiveUntil', '--accounting-scope': 'accountingScope', '--history-cache': 'historyCache' };
    for (let i = 0; i < args.length; i++) {
        if (args[i] === '--execute') result.execute = true;
        else if (options[args[i]] && args[i + 1] && !args[i + 1].startsWith('--')) result[options[args[i]]] = args[++i];
        else throw new Error(`Unknown or incomplete argument: ${args[i]}`);
    }
    accounting(result.accountingScope);
    return result;
}

async function executeWorker(options) {
    const repo = fs.realpathSync(process.env.BOOPA_REPO || path.join(HOME, '..', 'boopa'));
    const authorization = validateExecution({ ...options, repo });
    const runner = validateRunnerContext(authorization);
    const pinnedRuntimeCommit = verifyPinnedRuntime(repo);
    const lockFile = `${authorization.budgetFile}.probe.lock`;
    const lock = fs.openSync(lockFile, 'wx', 0o600);
    fs.writeFileSync(lock, JSON.stringify({ pid: process.pid, at: new Date().toISOString() }));
    fs.closeSync(lock);
    let outputDir;
    try {
        const plan = getPlan(repo);
        plan.runner = runner;
        plan.pinnedRuntimeCommit = pinnedRuntimeCommit;
        // Bind the original transferred ledger to this first attempt. Never
        // manufacture a new counter from the two-request template on a retry.
        authorization.budget.runnerRunId = runner.runId;
        atomicJson(authorization.budgetFile, authorization.budget);
        fs.mkdirSync(path.join(HOME, 'runs'), { recursive: true });
        outputDir = fs.mkdtempSync(path.join(HOME, 'runs', 'probe-'));
        process.send?.({ outputDir });
        const runtime = require(path.join(repo, 'src/collection-runtime.js'));
        const scraper = require(path.join(repo, 'src/scraper.js'));
        const axios = require(require.resolve('axios', { paths: [repo] }));
        const result = await runProbe({ plan, authorization, outputDir, transport: axios.get, runtime, scraper,
            transportMode: 'live', readHistory: selected => loadHistory(plan, selected, options.historyCache) });
        console.log(JSON.stringify({ status: result.status, stop: result.stop, attempts: result.actualHttpAttempts,
            charged: result.chargedAttempts, accounting: result.accounting, legacyResume: result.legacyResume, outputDir }, null, 2));
        if (result.status !== 'completed') process.exitCode = 2;
    } finally {
        // A watchdog/SIGKILL leaves this lock deliberately. Do not remove a stale
        // lock or refund a charged attempt until its outcome is reconciled.
        fs.unlinkSync(lockFile);
    }
}

async function main() {
    const options = parseArgs(process.argv.slice(2));
    const repo = fs.realpathSync(process.env.BOOPA_REPO || path.join(HOME, '..', 'boopa'));
    if (!options.execute) {
        console.log(JSON.stringify({ mode: 'dry-run', networkRequests: 0, quotaVerified: false,
            pinnedRuntimeCommit: EXPECTED_RUNTIME_COMMIT, priorCloudRequests: PRIOR_CLOUD_REQUESTS,
            maximumAdditionalRunnerRequests: LIMITS.maxHttpAttempts - PRIOR_CLOUD_REQUESTS,
            ...getPlan(repo), accounting: accounting(options.accountingScope), currentJstDay: jstDate(Date.now()),
            requiredBeforeExecution: ['Explicit operator authorization outside this program',
                options.accountingScope === 'incremental-exception'
                    ? 'Specific one-time approval for up to 20 additional requests despite unknown full-day legacy traffic, plus labeled probe-only ledger and reviewed cooldown'
                    : 'Existing labeled full-day ledger with proven conservative full-day HTTP usage and reviewed cooldown',
                'No active/scheduled competing collector for the entire verified window',
                '--execute --budget-file FILE --expected-jst-day YYYY-MM-DD --exclusive-until ISO_TIMESTAMP'] }, null, 2));
        return;
    }
    const authorization = validateExecution({ ...options, repo });
    validateRunnerContext(authorization); // Operator fails closed before any fork.
    verifyPinnedRuntime(repo);
    const child = fork(__filename, process.argv.slice(2), { env: { ...process.env, BOOPA_PROBE_WORKER: '1' },
        stdio: ['ignore', 'inherit', 'inherit', 'ipc'] });
    let outputDir;
    child.on('message', message => { outputDir = message.outputDir; });
    const watchdog = setTimeout(() => {
        child.kill('SIGKILL');
        console.error(JSON.stringify({ status: 'watchdog-stop', outputDir,
            legacyResume: 'blocked-pending-operator-reconciliation',
            message: 'Hard time bound reached; preserve ledger, lock, and logs. No blind legacy resume: outcome/cooldown may be unknown' }));
    }, LIMITS.hardRuntimeMs);
    child.on('exit', (code, signal) => {
        clearTimeout(watchdog);
        process.exitCode = signal ? 2 : code;
    });
}

module.exports = { SOURCE_COMMIT, EXPECTED_RUNTIME_COMMIT, PRIOR_CLOUD_REQUESTS, LIMITS, HOME,
    getPlan, loadHistory, validateExecution, validateRunnerContext, verifyPinnedRuntime, runProbe, parseArgs, jstDate };
if (require.main === module) {
    const run = process.env.BOOPA_PROBE_WORKER === '1'
        ? (() => { const options = parseArgs(process.argv.slice(2));
            if (!options.execute || typeof process.send !== 'function') throw new Error('Worker requires supervised --execute');
            return executeWorker(options); })
        : main;
    Promise.resolve().then(run).catch(error => { console.error(error.message); process.exitCode = 1; });
}
