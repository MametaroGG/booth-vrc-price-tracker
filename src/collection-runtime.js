const fs = require('node:fs');
const path = require('node:path');

const MAX_EXECUTION_TIME_MS = 5 * 60 * 60 * 1000;
const JOB_TIMEOUT_MS = 6 * 60 * 60 * 1000;
const SAVE_BUFFER_MS = 30 * 60 * 1000;
// Provisional daily ceiling, shared by searches, details, redirects
// and retries across all scheduled runs. This is not a BOOTH-published limit.
const DAILY_REQUEST_LIMIT = 48000;
const REQUEST_TIMEOUT_MS = 30000;
// One start gate covers search, detail, retry and redirect attempts. Two starts
// per second is deliberately conservative; concurrency does not bypass pacing.
const REQUEST_INTERVAL_MS = 500;
const LANES = ['refresh', 'discovery'];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function jstDate(time) {
    return new Date(time + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function getStopTargetTime(startTime, jobStartedAt = startTime) {
    const jobStart = typeof jobStartedAt === 'string' ? Date.parse(jobStartedAt) : jobStartedAt;
    if (!Number.isFinite(startTime) || !Number.isFinite(jobStart) || jobStart > startTime) {
        throw new Error('Invalid scraper/job start time');
    }
    // Concurrency already serializes jobs. The next cron time is not a deadline:
    // a delayed checkout must not cause an otherwise healthy run to do no work.
    return new Date(Math.min(startTime + MAX_EXECUTION_TIME_MS, jobStart + JOB_TIMEOUT_MS - SAVE_BUFFER_MS));
}

function readJson(file, fallback) {
    if (!fs.existsSync(file)) return fallback;
    // Fail closed on a corrupt budget/checkpoint rather than silently restarting.
    return JSON.parse(fs.readFileSync(file, 'utf8'));
}

function writeJson(file, value) {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const temporary = `${file}.tmp`;
    fs.writeFileSync(temporary, JSON.stringify(value, null, 2));
    fs.renameSync(temporary, file);
}

class CollectionStop extends Error {
    constructor(reason, message, failed = false) {
        super(message);
        this.name = 'CollectionStop';
        this.reason = reason;
        this.failed = failed;
    }
}

function retryAfterMs(value, now) {
    if (value == null || value === '') return 60000;
    const seconds = Number(value);
    if (Number.isFinite(seconds) && seconds >= 0) return Math.max(60000, seconds * 1000);
    const date = Date.parse(value);
    return Number.isFinite(date) ? Math.max(60000, date - now) : 60000;
}

function urlIdentity(url) {
    const query = [...url.searchParams.entries()].sort(([leftKey, leftValue], [rightKey, rightValue]) =>
        leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : leftValue < rightValue ? -1 : leftValue > rightValue ? 1 : 0);
    // Preserve all query entries, including duplicates. Reordering, percent
    // encoding and fragments cannot change the filtered source's identity.
    return JSON.stringify([url.origin, decodeURIComponent(url.pathname), query]);
}

function validateBudget(budget) {
    if (!budget || !/^\d{4}-\d{2}-\d{2}$/.test(budget.date) ||
        !Number.isSafeInteger(budget.requests) || budget.requests < 0 ||
        !Number.isFinite(budget.blockedUntil) || budget.blockedUntil < 0 ||
        !Number.isFinite(Date.parse(`${budget.date}T00:00:00Z`)) ||
        new Date(`${budget.date}T00:00:00Z`).toISOString().slice(0, 10) !== budget.date) {
        throw new Error('Invalid request budget; refusing to reset it');
    }
    const reservation = budget.reservation;
    if (reservation !== undefined && (!reservation || typeof reservation.id !== 'string' || !reservation.id ||
        typeof reservation.completed !== 'boolean' || !Number.isSafeInteger(reservation.limit) ||
        reservation.limit < 0 || reservation.limit > DAILY_REQUEST_LIMIT || !Number.isSafeInteger(reservation.used) ||
        reservation.used < 0 || reservation.used > reservation.limit ||
        (!reservation.completed && budget.requests < reservation.limit))) {
        throw new Error('Invalid request reservation; refusing to reset it');
    }
    if (budget.laneUsage !== undefined && (!budget.laneUsage ||
        LANES.some(lane => !Number.isSafeInteger(budget.laneUsage[lane]) || budget.laneUsage[lane] < 0) ||
        budget.laneUsage.refresh + budget.laneUsage.discovery > actualRequests(budget))) {
        throw new Error('Invalid lane usage; refusing to reset it');
    }
    if (budget.laneReleased !== undefined && (!budget.laneReleased ||
        LANES.some(lane => typeof budget.laneReleased[lane] !== 'boolean'))) {
        throw new Error('Invalid lane release state; refusing to reset it');
    }
    return budget;
}

function actualRequests(budget) {
    // requests includes an entire durable reservation until finish(). Its
    // unused precharge is not historical traffic and must not shrink lane caps.
    const reservation = budget.reservation;
    return budget.requests - (reservation && !reservation.completed ? reservation.limit - reservation.used : 0);
}

function initializeLanes(budget) {
    budget.laneUsage ??= { refresh: 0, discovery: 0 };
    budget.laneReleased ??= { refresh: false, discovery: false };
    return budget;
}

function resetDay(budget, date) {
    return { ...budget, date, requests: 0, laneUsage: { refresh: 0, discovery: 0 },
        laneReleased: { refresh: false, discovery: false } };
}

function reserveDailyAllowance({ budgetFile, reservationId, now = Date.now() }) {
    if (!reservationId) throw new Error('SCRAPER_RESERVATION_ID is required');
    // Existing same-day traffic predates this ledger and cannot be measured here.
    // Bootstrap with no allowance until the next JST day to avoid a rollout spike.
    let budget = validateBudget(readJson(budgetFile, { date: jstDate(now), requests: DAILY_REQUEST_LIMIT, blockedUntil: 0 }));
    if (budget.reservation && !budget.reservation.completed) {
        if (budget.reservation.limit === 0) {
            // No request could have started, so no response/cooldown evidence was
            // lost. A crashed quota-exhausted/bootstrap run must not block forever.
            budget.reservation.completed = true;
        } else {
            throw new Error('Previous request reservation is unresolved (unknown outcome/cooldown). Keep its full charge and review recovery instructions before collecting again.');
        }
    }
    if (budget.blockedUntil > now) throw new Error(`Requests paused until ${new Date(budget.blockedUntil).toISOString()}`);
    const date = jstDate(now);
    if (date < budget.date) throw new Error('Request budget date is in the future');
    if (date !== budget.date) budget = resetDay(budget, date);
    initializeLanes(budget);
    const limit = Math.max(0, DAILY_REQUEST_LIMIT - budget.requests);
    budget.requests += limit;
    budget.reservation = { id: reservationId, limit, used: 0, completed: false };
    // The workflow must push this reservation successfully before collecting.
    // Losing the final checkpoint cannot replenish quota or forget a cooldown:
    // the unresolved reservation blocks the next run until explicitly reviewed.
    writeJson(budgetFile, budget);
    return budget.reservation;
}

function createRequestClient({
    get, budgetFile, deadline, now = Date.now, wait = sleep,
    dailyLimit = DAILY_REQUEST_LIMIT, intervalMs = REQUEST_INTERVAL_MS,
    timeoutMs = REQUEST_TIMEOUT_MS, maxAttempts = 3, failureThreshold = 5, reservationId,
    laneBudgets = false
}) {
    if (!Number.isSafeInteger(dailyLimit) || dailyLimit < 0 || dailyLimit > DAILY_REQUEST_LIMIT) {
        throw new Error(`Daily request limit must be between 0 and ${DAILY_REQUEST_LIMIT}`);
    }
    if (!Number.isFinite(intervalMs) || intervalMs < 0 || !Number.isSafeInteger(maxAttempts) || maxAttempts < 1 || maxAttempts > 3) {
        throw new Error('Invalid request pacing or retry limit');
    }
    let budget = validateBudget(readJson(budgetFile, { date: jstDate(now()), requests: 0, blockedUntil: 0 }));
    if (reservationId && (budget.reservation?.id !== reservationId || budget.reservation.completed)) {
        throw new Error('Missing active request reservation for this run');
    }
    if (!reservationId && budget.reservation && !budget.reservation.completed) {
        throw new Error('Active request reservation requires its reservation ID');
    }
    initializeLanes(budget);
    let nextStart = 0;
    let gate = Promise.resolve();
    let consecutiveFailures = 0;
    let stopped;
    let finished = false;

    function check() {
        if (finished) throw new CollectionStop('finished', 'Request client is already finished', true);
        if (stopped) throw stopped;
        if (now() >= deadline) throw new CollectionStop('deadline', 'Collection time budget reached');
        if (budget.blockedUntil > now()) {
            throw new CollectionStop('cooldown', `Requests paused until ${new Date(budget.blockedUntil).toISOString()}`, true);
        }
        const date = jstDate(now());
        if (date < budget.date) throw new Error('Request budget date is in the future');
        if (reservationId || laneBudgets) {
            if (date !== budget.date) throw new CollectionStop('day-boundary', 'JST day changed; a new durable reservation is required');
            if (reservationId && budget.reservation.used >= budget.reservation.limit) throw new CollectionStop('request-budget', 'Reserved request allowance reached');
        } else {
            if (date !== budget.date) budget = resetDay(budget, date);
        }
        if (actualRequests(budget) >= dailyLimit) throw new CollectionStop('request-budget', 'JST daily request budget reached');
    }

    function validateLane(lane) {
        if (!LANES.includes(lane)) throw new Error(`Unknown request lane: ${lane}`);
    }

    function remaining(lane) {
        if (lane !== undefined) validateLane(lane);
        if (finished || stopped || now() >= deadline || budget.blockedUntil > now() || jstDate(now()) !== budget.date) return 0;
        const global = Math.max(0, Math.min(dailyLimit - actualRequests(budget),
            reservationId ? budget.reservation.limit - budget.reservation.used : dailyLimit));
        if (!laneBudgets || lane === undefined) return global;
        const other = lane === 'refresh' ? 'discovery' : 'refresh';
        if (budget.laneReleased[other]) return global;
        // Legacy or operator-reconciled traffic with no proven lane remains
        // fully charged. Split only the capacity left after that traffic.
        const unattributed = actualRequests(budget) - budget.laneUsage.refresh - budget.laneUsage.discovery;
        const attributableLimit = Math.max(0, dailyLimit - unattributed);
        const refreshLimit = Math.floor(attributableLimit * 9 / 10);
        const limit = lane === 'refresh' ? refreshLimit : attributableLimit - refreshLimit;
        return Math.max(0, Math.min(global, limit - budget.laneUsage[lane]));
    }

    function checkLane(lane = 'refresh') {
        validateLane(lane);
        check();
        if (laneBudgets && remaining(lane) <= 0) {
            throw new CollectionStop('lane-budget', `Protected ${lane} request allowance reached`);
        }
    }

    function stop(reason, message, failed = true) {
        stopped ??= new CollectionStop(reason, message, failed);
        return stopped;
    }

    function persistBudget() {
        try {
            writeJson(budgetFile, budget);
        } catch (error) {
            throw stop('budget-write', `Cannot persist request budget: ${error.message}`);
        }
    }

    function releaseLane(lane) {
        validateLane(lane);
        if (finished) throw new CollectionStop('finished', 'Request client is already finished', true);
        if (stopped) throw stopped;
        if (jstDate(now()) !== budget.date) throw new CollectionStop('day-boundary', 'JST day changed; a new durable reservation is required');
        // The orchestrator may call this only after proving the lane has no
        // currently eligible queued or in-flight work. Exhaustion is not proof.
        if (!budget.laneReleased[lane]) {
            budget.laneReleased[lane] = true;
            persistBudget();
        }
        return remaining(lane === 'refresh' ? 'discovery' : 'refresh');
    }

    async function delay(ms) {
        check();
        if (now() + ms >= deadline) throw new CollectionStop('deadline', 'Not enough collection time for backoff');
        await wait(ms);
        check();
    }

    async function reserve(start, lane) {
        // Serialize starts, not whole HTTP calls. Queued calls recheck the circuit,
        // deadline and budget before sending, including after another call fails.
        const reservation = gate.then(async () => {
            checkLane(lane);
            if (nextStart > now()) await delay(nextStart - now());
            checkLane(lane);
            if (reservationId) budget.reservation.used++;
            else budget.requests++;
            budget.laneUsage[lane]++;
            persistBudget(); // Count attempts before sending, even on crash.
            // Start HTTP inside the gate so timer/microtask ordering cannot bunch starts.
            return { pending: start() };
        });
        gate = reservation.catch(() => {});
        return reservation;
    }

    function block(reason, milliseconds, message, details = {}) {
        budget.blockedUntil = Math.max(budget.blockedUntil, now() + milliseconds);
        stopped = Object.assign(new CollectionStop(reason,
            `${message}; requests paused until ${new Date(budget.blockedUntil).toISOString()}`, true), details);
        persistBudget();
        return stopped;
    }

    async function request(url, { lane = 'refresh', redirectPolicy = 'booth-host', productId, onAttempt } = {}) {
        validateLane(lane);
        if (!['booth-host', 'same-url'].includes(redirectPolicy)) throw new Error(`Unknown redirect policy: ${redirectPolicy}`);
        if (onAttempt !== undefined && typeof onAttempt !== 'function') throw new Error('onAttempt must be a function');
        if (productId !== undefined && (typeof productId !== 'string' || !/^[1-9]\d*$/.test(productId))) {
            throw new Error('Redirect productId must be a canonical positive numeric ID');
        }
        const originalIdentity = redirectPolicy === 'same-url' ? urlIdentity(new URL(url)) : undefined;
        let currentUrl = url;
        let redirects = 0;
        for (let attempt = 1; attempt <= maxAttempts; attempt++) {
            try {
                const { pending } = await reserve(() => {
                    const chargedDate = budget.date;
                    // The reserved start already persisted its charge. Keep
                    // this observer synchronous so it cannot move HTTP outside
                    // the shared start gate or alter its pacing.
                    try {
                        const observed = onAttempt?.();
                        if (observed && typeof observed.then === 'function') {
                            Promise.resolve(observed).catch(() => {});
                            throw new Error('onAttempt must be synchronous');
                        }
                    } catch (error) {
                        throw stop('attempt-hook', `Request attempt hook failed: ${error?.message || error}`);
                    }
                    // A synchronous disk write/observer can cross midnight or
                    // the deadline after charging but before the actual start.
                    // Keep that conservative charge; never send against another
                    // day's allowance or after an observed global stop.
                    if (stopped) throw stopped;
                    if (finished) throw new CollectionStop('finished', 'Request client is already finished', true);
                    if (now() >= deadline) throw new CollectionStop('deadline', 'Collection time budget reached');
                    if (jstDate(now()) !== chargedDate) throw new CollectionStop('day-boundary', 'JST day changed before HTTP start');
                    if (budget.blockedUntil > now()) throw new CollectionStop('cooldown', 'Requests are paused', true);
                    const timeout = Math.max(1, Math.min(timeoutMs, deadline - now()));
                    nextStart = now() + intervalMs;
                    return get(currentUrl, {
                        timeout,
                        signal: AbortSignal.timeout(timeout),
                        // Handle redirects explicitly so every network hop is budgeted.
                        maxRedirects: 0,
                        validateStatus: status => status >= 200 && status < 400,
                        headers: {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                        }
                    });
                }, lane);
                const response = await pending;
                if ([301, 302, 303, 307, 308].includes(response.status)) {
                    const location = response.headers?.location;
                    let target;
                    let allowed = false;
                    try {
                        target = location && new URL(location, currentUrl);
                        allowed = target && target.protocol === 'https:' && !target.username && !target.password &&
                            (target.hostname === 'booth.pm' || target.hostname.endsWith('.booth.pm')) &&
                            (redirectPolicy !== 'same-url' || urlIdentity(target) === originalIdentity) &&
                            (productId === undefined || new RegExp(`^/(?:ja/|en/)?items/${productId}/?$`).test(decodeURIComponent(target.pathname)));
                    } catch {
                        // Malformed URLs/escapes are unsafe redirects, never
                        // transient network errors to retry against the source.
                    }
                    if (!allowed || ++redirects > 3) {
                        throw new CollectionStop('redirect', 'Unrecognized or excessive BOOTH redirect', true);
                    }
                    currentUrl = target.href;
                    attempt--; // Redirects count toward the daily cap, not retry allowance.
                    continue;
                }
                if (response.status !== 200) throw new CollectionStop('http', `Unexpected HTTP ${response.status}`, true);
                consecutiveFailures = 0;
                return response;
            } catch (error) {
                if (error instanceof CollectionStop) throw error;
                const status = error.response?.status;
                if (status === 403) {
                    throw block('forbidden', Math.max(6 * 60 * 60 * 1000, retryAfterMs(error.response?.headers?.['retry-after'], now())),
                        'HTTP 403: stopping rather than retrying access', { triggeringUrl: url });
                }
                if (status === 429) {
                    throw block('rate-limit', retryAfterMs(error.response?.headers?.['retry-after'], now()),
                        'HTTP 429: stopping and preserving Retry-After cooldown');
                }
                // Missing/removed items are explicit terminal outcomes, not failures.
                if (status === 404 || status === 410) {
                    consecutiveFailures = 0;
                    return { status, data: '' };
                }
                const transient = !status || status === 408 || status >= 500;
                if (!transient) throw error;
                // An already-active failure may arrive while the pool drains.
                // Keep the first global stop and its proven triggering request.
                if (stopped) throw stopped;
                consecutiveFailures++;
                if (consecutiveFailures >= failureThreshold) {
                    throw block('circuit-breaker', 60000, 'Repeated request failures: circuit opened',
                        { triggeringUrl: url });
                }
                if (attempt === maxAttempts) throw error;
                const backoff = Math.max(1500 * 2 ** (attempt - 1),
                    error.response?.headers?.['retry-after'] == null ? 0 :
                        retryAfterMs(error.response.headers['retry-after'], now()));
                await delay(backoff);
            }
        }
    }

    function finish() {
        finished = true;
        if (reservationId && !budget.reservation.completed) {
            budget.requests -= budget.reservation.limit - budget.reservation.used;
            budget.reservation.completed = true;
            persistBudget();
        }
    }

    return { get: request, check, checkLane, remaining, releaseLane, stop, finish, getBudget: () => structuredClone(budget) };
}

module.exports = {
    CollectionStop, DAILY_REQUEST_LIMIT, MAX_EXECUTION_TIME_MS, REQUEST_INTERVAL_MS, SAVE_BUFFER_MS,
    createRequestClient, getStopTargetTime, jstDate, readJson, reserveDailyAllowance, retryAfterMs, writeJson
};
