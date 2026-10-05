const fs = require('node:fs');
const path = require('node:path');
const { CollectionStop, createRequestClient, getStopTargetTime, jstDate, readJson, writeJson } = require('./collection-runtime');
const { CatalogRegistry } = require('./catalog-registry');
const { runTaskPool } = require('./task-pool');

function loadDiscoveryState(file, { categories = 2, maxPages = 3333 } = {}) {
    const state = readJson(file, { urlIndex: 0, page: 1 });
    if (!state || !Number.isInteger(state.urlIndex) || state.urlIndex < 0 || state.urlIndex >= categories ||
        !Number.isInteger(state.page) || state.page < 1 || state.page > maxPages + 1 ||
        (state.pendingIds !== undefined && (!Array.isArray(state.pendingIds) ||
            !state.pendingIds.every(id => typeof id === 'string' && /^\d+$/.test(id)))) ||
        (state.retryAt !== undefined && (!Number.isFinite(state.retryAt) || state.retryAt < 0)) ||
        (state.failures !== undefined && (!Number.isSafeInteger(state.failures) || state.failures < 0)) ||
        (state.completedDate !== undefined && !/^\d{4}-\d{2}-\d{2}$/.test(state.completedDate))) {
        throw new Error('Invalid crawl checkpoint; refusing to reset it');
    }
    return state;
}

function percentile(values, quantile) {
    if (!values.length) return null;
    const sorted = [...values].sort((a, b) => a - b);
    return sorted[Math.ceil(sorted.length * quantile) - 1];
}

async function runCollector({
    dataDir, searchUrls, search, detail, save, get,
    now = Date.now, wait, maxPages = 3333, concurrency = 5,
    jobStartedAt = process.env.SCRAPER_JOB_STARTED_AT,
    reservationId = process.env.SCRAPER_RESERVATION_ID,
    client: suppliedClient, registry: suppliedRegistry, requestIntervalMs,
    log = console.log, logError = console.error
}) {
    fs.mkdirSync(dataDir, { recursive: true });
    const startedAt = now();
    const today = jstDate(startedAt);
    const cpuStarted = process.cpuUsage();
    const deadline = getStopTargetTime(startedAt, jobStartedAt ?? startedAt).getTime();
    const stateFile = path.join(dataDir, 'crawl_state.json');
    const latencies = [];
    const stats = {
        startedAt: new Date(startedAt).toISOString(), deadline: new Date(deadline).toISOString(),
        httpAttempts: 0, httpErrors: 0, maxActiveHttp: 0, statusCodes: {}, transportMeasured: !suppliedClient,
        searchPages: 0, searchFailures: 0, candidates: 0, discovered: 0,
        refreshSuccess: 0, discoverySuccess: 0, unavailable: 0, itemFailures: 0,
        duplicatesAvoided: 0, quotaDeferred: 0, saveTimeMs: 0, errors: []
    };
    let activeHttp = 0;
    const measuredGet = async (url, config) => {
        const before = now();
        stats.httpAttempts++;
        activeHttp++;
        stats.maxActiveHttp = Math.max(stats.maxActiveHttp, activeHttp);
        try {
            const response = await get(url, config);
            stats.statusCodes[response.status] = (stats.statusCodes[response.status] || 0) + 1;
            return response;
        } catch (error) {
            stats.httpErrors++;
            const code = error.response?.status || error.code || 'network';
            stats.statusCodes[code] = (stats.statusCodes[code] || 0) + 1;
            throw error;
        } finally {
            activeHttp--;
            latencies.push(Math.max(0, now() - before));
        }
    };
    const client = suppliedClient || createRequestClient({
        get: measuredGet, budgetFile: path.join(dataDir, 'request_budget.json'),
        deadline, now, reservationId, laneBudgets: true,
        ...(wait ? { wait } : {}), ...(requestIntervalMs !== undefined ? { intervalMs: requestIntervalMs } : {})
    });
    const initialLaneUsage = client.getBudget?.().laneUsage || { refresh: 0, discovery: 0 };
    const initialUsed = client.getBudget?.().reservation?.used || 0;
    let state = loadDiscoveryState(stateFile, { categories: searchUrls.length, maxPages });
    const registry = suppliedRegistry || new CatalogRegistry({ dataDir, now });
    const bootstrapStart = now();
    registry.bootstrap();
    stats.bootstrapTimeMs = Math.max(0, now() - bootstrapStart);
    const checkpoint = () => writeJson(stateFile, state);

    // Old page checkpoints contained every failed/unstarted ID from that page.
    // Register them durably before advancing its search cursor. Completed product
    // files are already in the bootstrap; nothing is silently dropped.
    if (state.pendingIds !== undefined) {
        registry.discover(state.pendingIds);
        state = { ...state, page: state.page + 1 };
        delete state.pendingIds;
        checkpoint();
    }

    const refresh = registry.eligible('refresh', startedAt);
    const pendingNew = registry.eligible('discovery', startedAt);
    let refreshIndex = 0;
    let discoveryIndex = 0;
    const claimed = new Set();
    const succeeded = new Set();
    const active = { refresh: 0, discovery: 0 };
    const released = { refresh: false, discovery: false };
    const deferred = { refresh: 0, discovery: 0 };
    const deferredTasks = new Map();
    const deferredRetries = new Set();
    let searchSuspended = false;
    let searchActive = false;
    let discoveryDetailStreak = 4; // Start with a search, then up to four new IDs.
    let turn = 0;
    let haltError;
    let fatal;
    let poolStats;

    function rememberError(error, context) {
        const message = `${context}: ${error.message}`;
        if (stats.errors.length < 10) stats.errors.push(message);
        logError(message);
    }
    function halt(error) {
        if (!haltError || (!(error instanceof CollectionStop) || error.failed)) haltError = error;
        client.stop?.(error.reason || 'collector-error', error.message,
            !(error instanceof CollectionStop) || error.failed);
    }
    function laneClient(lane, task) {
        return { get: (url, options) => client.get(url, { ...options, lane,
            onAttempt: () => { task.attempts++; } }) };
    }
    function remaining(lane) {
        return client.remaining ? client.remaining(lane) : Infinity;
    }
    function normalizeSearchCursor() {
        if (state.page > maxPages) {
            state = { ...state, urlIndex: state.urlIndex + 1, page: 1 };
            if (state.urlIndex >= searchUrls.length) {
                state = { urlIndex: 0, page: 1, completedDate: today, failures: 0, retryAt: 0 };
            }
            checkpoint();
        }
    }
    function searchReady() {
        return !searchActive && !searchSuspended && state.completedDate !== today && (state.retryAt || 0) <= now();
    }
    function nextId(lane, claim) {
        const list = lane === 'refresh' ? refresh : pendingNew;
        let index = lane === 'refresh' ? refreshIndex : discoveryIndex;
        while (index < list.length) {
            const id = list[index];
            if (claimed.has(id) || !registry.isDue(id, now())) {
                if (claimed.has(id)) stats.duplicatesAvoided++;
                index++;
                continue;
            }
            if (lane === 'refresh') refreshIndex = index;
            else discoveryIndex = index;
            if (!claim) return id;
            claimed.add(id);
            if (lane === 'refresh') refreshIndex++;
            else discoveryIndex++;
            return id;
        }
        if (lane === 'refresh') refreshIndex = index;
        else discoveryIndex = index;
        return null;
    }
    function releaseFinishedLanes() {
        if (!released.refresh && !active.refresh && !deferred.refresh && nextId('refresh', false) === null) {
            client.releaseLane?.('refresh');
            released.refresh = true;
        }
        // A search failure/backoff is not proof discovery finished: retain its
        // share for a later run rather than consuming it all on known products.
        if (!released.discovery && !active.discovery && !deferred.discovery && state.completedDate === today &&
            nextId('discovery', false) === null) {
            client.releaseLane?.('discovery');
            released.discovery = true;
        }
    }
    function productTask(lane) {
        const id = nextId(lane, true);
        if (id === null) return null;
        active[lane]++;
        if (lane === 'discovery') discoveryDetailStreak++;
        const task = { key: `product:${id}`, kind: 'product', lane, id, attempts: 0 };
        task.run = () => detail(id, laneClient(lane, task));
        return task;
    }
    function restoreUnstartedDeferrals() {
        // Only the pool's post-release hook can prove an old key is reusable.
        // Requests that never started may re-enter once after a loan creates room.
        for (const [id, task] of deferredTasks) {
            if (!task.poolReleased || task.attempts || deferredRetries.has(id) || remaining(task.lane) <= 0) continue;
            deferredRetries.add(id);
            deferredTasks.delete(id);
            deferred[task.lane]--;
            claimed.delete(id);
            (task.lane === 'refresh' ? refresh : pendingNew).push(id);
        }
    }
    function discoveryTask() {
        const pending = nextId('discovery', false);
        if (searchReady() && (pending === null || discoveryDetailStreak >= 4)) {
            searchActive = true;
            active.discovery++;
            discoveryDetailStreak = 0;
            const url = `${searchUrls[state.urlIndex]}&page=${state.page}`;
            const task = { key: 'filtered-search', kind: 'search', lane: 'discovery', url, attempts: 0 };
            task.run = () => search(url, laneClient('discovery', task));
            return task;
        }
        return pending === null ? null : productTask('discovery');
    }
    function nextTask() {
        if (haltError) return null;
        try {
            client.check();
            normalizeSearchCursor();
            releaseFinishedLanes();
            restoreUnstartedDeferrals();
        } catch (error) {
            halt(error);
            return null;
        }
        // Weighted task opportunities plus protected HTTP budgets ensure a large
        // backlog in one lane cannot consume the other lane's entire day.
        const preferred = turn++ % 10 === 0 ? 'discovery' : 'refresh';
        for (const lane of [preferred, preferred === 'refresh' ? 'discovery' : 'refresh']) {
            if (remaining(lane) <= 0) continue;
            const task = lane === 'refresh' ? productTask(lane) : discoveryTask();
            if (task) return task;
        }
        return null;
    }
    function handleStop(error, task) {
        if (!(error instanceof CollectionStop)) return false;
        // Invalid content/identity on one URL is a deferred item/search failure,
        // not evidence that every catalog request must be stopped.
        if (['redirect', 'http'].includes(error.reason)) return false;
        if (error.reason === 'lane-budget') {
            stats.quotaDeferred++;
            if (task.kind === 'product') {
                deferred[task.lane]++;
                deferredTasks.set(task.id, task);
            } else if (task.attempts > 0) {
                searchSuspended = true;
            }
        }
        else halt(error);
        return true;
    }
    async function onSettled(task, settlement) {
        const result = settlement.status === 'fulfilled' ? settlement.value : { kind: 'failure', error: settlement.reason };
        try {
            if (task.kind === 'search') {
                if (result.kind === 'failure') {
                    if (handleStop(result.error, task)) return;
                    stats.searchFailures++;
                    state.failures = (state.failures || 0) + 1;
                    state.retryAt = now() + Math.min(6 * 3600000, 15 * 60000 * 2 ** Math.min(state.failures - 1, 5));
                    checkpoint();
                    rememberError(result.error, 'Filtered search deferred');
                    return;
                }
                stats.searchPages++;
                state.failures = 0;
                state.retryAt = 0;
                if (result.kind === 'empty') {
                    state = { ...state, urlIndex: state.urlIndex + 1, page: 1 };
                    if (state.urlIndex >= searchUrls.length) {
                        state = { urlIndex: 0, page: 1, completedDate: today, failures: 0, retryAt: 0 };
                    }
                } else if (result.kind === 'success') {
                    stats.candidates += result.ids.length;
                    // Register before cursor advance. Only filtered discovery or
                    // existing stored product files can introduce an ID.
                    const added = registry.discover(result.ids);
                    stats.discovered += added.length;
                    stats.duplicatesAvoided += result.ids.length - added.length;
                    pendingNew.push(...added.filter(id => registry.isDue(id, now())));
                    state.page++;
                } else throw new Error('Unknown filtered search result');
                checkpoint();
                return;
            }
            if (result.kind === 'failure') {
                if (handleStop(result.error, task)) {
                    if (['circuit-breaker', 'forbidden'].includes(result.error.reason) &&
                        result.error.triggeringUrl === `https://booth.pm/ja/items/${task.id}`) {
                        registry.recordFailure(task.id, now());
                        stats.itemFailures++;
                    }
                    return;
                }
                registry.recordFailure(task.id, now());
                stats.itemFailures++;
                rememberError(result.error, `Product ${task.id} deferred`);
            } else if (result.kind === 'unavailable') {
                registry.recordFailure(task.id, now(), { unavailable: true });
                stats.unavailable++;
            } else if (result.kind === 'success') {
                const saveStarted = now();
                try {
                    await save(result.product, { dataDir, today: jstDate(saveStarted) });
                } catch (error) {
                    if (['ENOSPC', 'EIO', 'EROFS', 'EMFILE', 'ENFILE'].includes(error.code)) throw error;
                    registry.recordFailure(task.id, now());
                    stats.itemFailures++;
                    rememberError(error, `Product ${task.id} save deferred`);
                    return;
                } finally {
                    stats.saveTimeMs += Math.max(0, now() - saveStarted);
                }
                // Data first, registry second: an interrupted metadata write may
                // repeat a read, but never advances past missing product history.
                registry.recordSuccess(task.id, saveStarted);
                succeeded.add(task.id);
                stats[task.lane === 'refresh' ? 'refreshSuccess' : 'discoverySuccess']++;
            } else throw new Error('Unknown product result');
        } catch (error) {
            fatal = error;
            halt(error);
            throw error;
        } finally {
            active[task.lane]--;
            if (task.kind === 'search') searchActive = false;
        }
    }

    log(`Starting known-ID refresh + filtered discovery; deadline ${new Date(deadline).toISOString()}`);
    try {
        poolStats = await runTaskPool({ concurrency, nextTask, onSettled,
            onReleased: task => { task.poolReleased = true; }, shouldStop: () => Boolean(haltError) });
    } catch (error) {
        fatal = error;
        halt(error);
    } finally {
        checkpoint();
        client.finish?.();
    }
    const elapsedMs = Math.max(0, now() - startedAt);
    const finalBudget = client.getBudget?.();
    const used = finalBudget?.reservation?.used;
    stats.budgetChargedAttempts = used === undefined ? null : used - initialUsed;
    if (suppliedClient && used !== undefined) stats.httpAttempts = used - initialUsed;
    stats.requestsByLane = Object.fromEntries(['refresh', 'discovery'].map(lane => [lane,
        (finalBudget?.laneUsage?.[lane] || 0) - (initialLaneUsage[lane] || 0)]));
    stats.elapsedMs = elapsedMs;
    stats.cpuTimeMs = Object.values(process.cpuUsage(cpuStarted)).reduce((sum, value) => sum + value, 0) / 1000;
    stats.uniqueUpdated = succeeded.size;
    stats.updatesPerRequest = stats.httpAttempts ? succeeded.size / stats.httpAttempts : null;
    stats.updatesPerSecond = elapsedMs ? succeeded.size / (elapsedMs / 1000) : null;
    stats.requestP50Ms = percentile(latencies, 0.5);
    stats.requestP95Ms = percentile(latencies, 0.95);
    stats.pool = poolStats || null;
    stats.finishedAt = new Date(now()).toISOString();
    stats.discovery = { urlIndex: state.urlIndex, page: state.page, completedDate: state.completedDate || null };
    const failed = Boolean(fatal || (haltError && (!(haltError instanceof CollectionStop) || haltError.failed)) ||
        stats.itemFailures || stats.searchFailures);
    const unfinished = refreshIndex < refresh.length || discoveryIndex < pendingNew.length ||
        state.completedDate !== today || deferred.refresh || deferred.discovery;
    const status = failed ? 'partial' : haltError || unfinished ? 'paused' : 'completed';
    const reason = haltError?.reason || (fatal ? 'storage-or-runtime-error' : unfinished ? 'work-deferred' : undefined);
    writeJson(path.join(dataDir, 'collection_metrics.json'), { status, reason, ...stats });
    log(`Collection metrics: ${JSON.stringify({ status, uniqueUpdated: stats.uniqueUpdated,
        httpAttempts: stats.httpAttempts, updatesPerRequest: stats.updatesPerRequest, elapsedMs })}`);
    return { status, reason, failed, metrics: stats };
}

module.exports = { loadDiscoveryState, runCollector };
