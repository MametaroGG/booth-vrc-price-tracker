const fs = require('node:fs');
const path = require('node:path');

const MAX_EXECUTION_TIME_MS = 5 * 60 * 60 * 1000;
const JOB_TIMEOUT_MS = 6 * 60 * 60 * 1000;
const SAVE_BUFFER_MS = 30 * 60 * 1000;
// Legacy/optional finite ceiling. Production sessions have no daily request cap;
// every attempt is still recorded and server cooldowns remain mandatory.
const DAILY_REQUEST_LIMIT = 48000;
const REQUEST_TIMEOUT_MS = 30000;
const MAX_TIMESTAMP_MS = 8640000000000000; // Maximum timestamp supported by Date.
// Serialize accounting and stop checks without changing the scraper's original
// five-request batches, one-second batch waits, and two-second page waits.
const REQUEST_INTERVAL_MS = 0;
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
    // An overflowing duration still means a long hold. Saturate at the latest
    // representable timestamp so formatting and JSON persistence stay valid.
    const bound = milliseconds => Math.min(MAX_TIMESTAMP_MS - now, Math.max(60000, milliseconds));
    if (value == null || String(value).trim() === '') return bound(60000);
    const text = String(value).trim();
    if (/^\+?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(text)) {
        return bound(Number(text) * 1000);
    }
    const date = Date.parse(text);
    return bound(Number.isFinite(date) ? date - now : 60000);
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
        !Number.isFinite(budget.blockedUntil) || budget.blockedUntil < 0 || budget.blockedUntil > MAX_TIMESTAMP_MS ||
        !Number.isFinite(Date.parse(`${budget.date}T00:00:00Z`)) ||
        new Date(`${budget.date}T00:00:00Z`).toISOString().slice(0, 10) !== budget.date) {
        throw new Error('Invalid request budget; refusing to reset it');
    }
    const reservation = budget.reservation;
    if (reservation !== undefined) {
        const unlimited = reservation?.mode === 'unlimited';
        const validLimit = reservation && (unlimited ? reservation.limit === null && reservation.used <= budget.requests
            : (reservation?.mode === undefined || reservation.mode === 'finite') &&
                Number.isSafeInteger(reservation.limit) && reservation.limit >= 0 && reservation.limit <= DAILY_REQUEST_LIMIT &&
                reservation.used <= reservation.limit && (reservation.completed || budget.requests >= reservation.limit));
        if (!reservation || typeof reservation.id !== 'string' || !reservation.id ||
            typeof reservation.completed !== 'boolean' || !Number.isSafeInteger(reservation.used) ||
            reservation.used < 0 || !validLimit) {
            throw new Error('Invalid request reservation; refusing to reset it');
        }
    }
    return budget;
}

function actualRequests(budget) {
    // requests includes an entire durable reservation until finish(). Its
    // unused precharge is not historical traffic.
    const reservation = budget.reservation;
    return budget.requests - (reservation && !reservation.completed && reservation.limit !== null
        ? reservation.limit - reservation.used : 0);
}

function resetDay(budget, date) {
    return { ...budget, date, requests: 0 };
}

function validateDailyLimit(dailyLimit) {
    if (dailyLimit !== null && (!Number.isSafeInteger(dailyLimit) || dailyLimit < 0 || dailyLimit > DAILY_REQUEST_LIMIT)) {
        throw new Error(`Daily request limit must be null (unlimited) or between 0 and ${DAILY_REQUEST_LIMIT}`);
    }
}

function reserveDailyAllowance({ budgetFile, reservationId, now = Date.now(), dailyLimit = null }) {
    if (!reservationId) throw new Error('SCRAPER_RESERVATION_ID is required');
    validateDailyLimit(dailyLimit);
    // Existing same-day traffic predates this ledger and cannot be measured here.
    // An optional finite mode starts conservatively. Unlimited sessions can start
    // immediately; their count records only traffic observed by this ledger.
    let budget = validateBudget(readJson(budgetFile, { date: jstDate(now), requests: dailyLimit ?? 0, blockedUntil: 0 }));
    if (budget.reservation && !budget.reservation.completed) {
        if (budget.reservation.limit === 0) {
            // No request could have started, so no response/cooldown evidence was
            // lost. A crashed quota-exhausted/bootstrap run must not block forever.
            budget.reservation.completed = true;
        } else {
            throw new Error('Previous request reservation is unresolved (unknown outcome/cooldown). Preserve its accounting and review recovery instructions before collecting again.');
        }
    }
    if (budget.blockedUntil > now) throw new Error(`Requests paused until ${new Date(budget.blockedUntil).toISOString()}`);
    const date = jstDate(now);
    if (date < budget.date) throw new Error('Request budget date is in the future');
    if (date !== budget.date) budget = resetDay(budget, date);
    const limit = dailyLimit === null ? null : Math.max(0, dailyLimit - budget.requests);
    if (limit !== null) budget.requests += limit;
    budget.reservation = { id: reservationId, mode: limit === null ? 'unlimited' : 'finite', limit, used: 0, completed: false };
    // The workflow must push this reservation successfully before collecting.
    // No unbounded allowance is precharged. Losing the final checkpoint cannot
    // forget an unknown response/cooldown, even when the saved used count is zero:
    // the unresolved reservation blocks the next run until explicitly reviewed.
    writeJson(budgetFile, budget);
    return budget.reservation;
}

function createRequestClient({
    get, budgetFile, deadline, now = Date.now, wait = sleep,
    dailyLimit = null, intervalMs = REQUEST_INTERVAL_MS,
    timeoutMs = REQUEST_TIMEOUT_MS, maxAttempts = 3, failureThreshold = 5, reservationId
}) {
    validateDailyLimit(dailyLimit);
    if (!Number.isFinite(intervalMs) || intervalMs < 0 || !Number.isSafeInteger(maxAttempts) || maxAttempts < 1 || maxAttempts > 3) {
        throw new Error('Invalid request pacing or retry limit');
    }
    const budget = validateBudget(readJson(budgetFile, { date: jstDate(now()), requests: 0, blockedUntil: 0 }));
    if (reservationId && (budget.reservation?.id !== reservationId || budget.reservation.completed)) {
        throw new Error('Missing active request reservation for this run');
    }
    if (!reservationId && budget.reservation && !budget.reservation.completed) {
        throw new Error('Active request reservation requires its reservation ID');
    }
    let nextStart = 0;
    let gate = Promise.resolve();
    let consecutiveFailures = 0;
    let stopped;
    let finished = false;
    let attemptCount = 0;

    function check() {
        if (finished) throw new CollectionStop('finished', 'Request client is already finished', true);
        if (stopped) throw stopped;
        if (now() >= deadline) throw new CollectionStop('deadline', 'Collection time budget reached');
        if (budget.blockedUntil > now()) {
            throw new CollectionStop('cooldown', `Requests paused until ${new Date(budget.blockedUntil).toISOString()}`, true);
        }
        const date = jstDate(now());
        if (date < budget.date) throw new Error('Request budget date is in the future');
        if (date !== budget.date) throw new CollectionStop('day-boundary', 'JST day changed; a new durable reservation is required');
        if (reservationId && budget.reservation.limit !== null && budget.reservation.used >= budget.reservation.limit) {
            throw new CollectionStop('request-budget', 'Reserved request allowance reached');
        }
        if (dailyLimit !== null && actualRequests(budget) >= dailyLimit) throw new CollectionStop('request-budget', 'JST daily request budget reached');
    }

    function remaining() {
        if (finished || stopped || now() >= deadline || budget.blockedUntil > now() || jstDate(now()) !== budget.date) return 0;
        return Math.max(0, Math.min(dailyLimit === null ? Infinity : dailyLimit - actualRequests(budget),
            reservationId && budget.reservation.limit !== null ? budget.reservation.limit - budget.reservation.used : Infinity));
    }

    function stop(reason, message, failed = true) {
        // A draining request/storage failure takes priority over a normal
        // deadline pause, while the first actual failure keeps its identity.
        if (!stopped || (!stopped.failed && failed)) stopped = new CollectionStop(reason, message, failed);
        return stopped;
    }

    function persistBudget() {
        try {
            writeJson(budgetFile, budget);
        } catch (error) {
            throw stop('budget-write', `Cannot persist request budget: ${error.message}`);
        }
    }

    async function delay(ms) {
        check();
        if (now() + ms >= deadline) throw new CollectionStop('deadline', 'Not enough collection time for backoff');
        await wait(ms);
        check();
    }

    async function reserve(start) {
        // Serialize starts, not whole HTTP calls. Queued calls recheck the circuit,
        // deadline and budget before sending, including after another call fails.
        const reservation = gate.then(async () => {
            check();
            if (nextStart > now()) await delay(nextStart - now());
            check();
            if (actualRequests(budget) >= Number.MAX_SAFE_INTEGER || budget.reservation?.used >= Number.MAX_SAFE_INTEGER) {
                throw stop('request-accounting', 'Request count cannot be recorded safely');
            }
            if (reservationId) budget.reservation.used++;
            if (!reservationId || budget.reservation.limit === null) budget.requests++;
            attemptCount++;
            persistBudget(); // Count attempts before sending, even on crash.
            // Start HTTP inside the gate so timer/microtask ordering cannot bunch starts.
            return { pending: start() };
        });
        gate = reservation.catch(() => {});
        return reservation;
    }

    function block(reason, milliseconds, message, details = {}) {
        budget.blockedUntil = Math.min(MAX_TIMESTAMP_MS, Math.max(budget.blockedUntil, now() + milliseconds));
        if (!stopped || !stopped.failed) {
            stopped = Object.assign(new CollectionStop(reason,
                `${message}; requests paused until ${new Date(budget.blockedUntil).toISOString()}`, true), details);
        }
        persistBudget();
        return stopped;
    }

    function observeFailure(error, url, deadlineLimited = false, signal) {
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
        // A request's timer is shortened to the collection deadline. Its own
        // cancellation is a normal pause, not a failed retry/circuit strike.
        // Its own timeout signal also proves this when timer and wall-clock
        // precision differ slightly. Arbitrary earlier cancellations, real HTTP
        // responses and ordinary transport timeouts retain failure handling.
        const ownDeadlineTimeout = signal?.aborted && signal.reason?.name === 'TimeoutError';
        if (deadlineLimited && (now() >= deadline || ownDeadlineTimeout) && error.response == null &&
            (['ERR_CANCELED', 'ECONNABORTED', 'ETIMEDOUT'].includes(error.code) ||
                ['AbortError', 'TimeoutError'].includes(error.name))) {
            throw stop('deadline', 'Collection time budget reached', false);
        }
        // Missing/removed items are explicit terminal outcomes, not failures.
        if (status === 404 || status === 410) {
            consecutiveFailures = 0;
            return { status, data: '' };
        }
        const transient = !status || status === 408 || status >= 500;
        if (!transient) throw error;
        const serverBackoff = error.response?.headers?.['retry-after'] == null ? 0
            : retryAfterMs(error.response.headers['retry-after'], now());
        // An already-active failure may arrive while the pool drains.
        // Keep the first global stop and its proven triggering request, while
        // preserving any longer server hold returned by a draining request.
        if (stopped) {
            if (serverBackoff) block('retry-backoff', serverBackoff, 'Preserving server Retry-After cooldown');
            throw stopped;
        }
        consecutiveFailures++;
        if (consecutiveFailures >= failureThreshold) {
            throw block('circuit-breaker', Math.max(60000, serverBackoff), 'Repeated request failures: circuit opened',
                { triggeringUrl: url });
        }
        throw error;
    }

    async function request(url, { redirectPolicy = 'booth-host', productId, onAttempt } = {}) {
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
                    const remainingTime = deadline - now();
                    const deadlineLimited = remainingTime <= timeoutMs;
                    const timeout = Math.max(1, Math.min(timeoutMs, remainingTime));
                    const signal = AbortSignal.timeout(timeout);
                    nextStart = now() + intervalMs;
                    let pending;
                    try {
                        pending = get(currentUrl, {
                            timeout,
                            signal,
                            // Handle redirects explicitly so every network hop is budgeted.
                            maxRedirects: 0,
                            validateStatus: status => status >= 200 && status < 400,
                            headers: {
                                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                            }
                        });
                    } catch (error) {
                        return observeFailure(error, url, deadlineLimited, signal);
                    }
                    // Observe the transport outcome before releasing further
                    // queued starts, including when no start interval is set.
                    return Promise.resolve(pending).then(response => {
                        if ([200, 404, 410].includes(response.status)) consecutiveFailures = 0;
                        return response;
                    }, error => observeFailure(error, url, deadlineLimited, signal));
                });
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
                    attempt--; // Redirects are recorded separately from the retry allowance.
                    continue;
                }
                if ([404, 410].includes(response.status)) return response;
                if (response.status !== 200) throw new CollectionStop('http', `Unexpected HTTP ${response.status}`, true);
                return response;
            } catch (error) {
                if (error instanceof CollectionStop) throw error;
                const status = error.response?.status;
                if (status && status !== 408 && status < 500) throw error;
                if (stopped) {
                    // Another response can stop the client between observing
                    // this failure and reaching this catch. Its earlier server
                    // hold still applies even though this request cannot retry.
                    if (error.response?.headers?.['retry-after'] != null) {
                        block('retry-backoff', retryAfterMs(error.response.headers['retry-after'], now()),
                            'Preserving server Retry-After cooldown');
                    }
                    throw stopped;
                }
                if (attempt === maxAttempts) {
                    if (error.response?.headers?.['retry-after'] != null) {
                        throw block('retry-backoff', retryAfterMs(error.response.headers['retry-after'], now()),
                            'Retry limit reached; preserving server Retry-After cooldown', { triggeringUrl: url });
                    }
                    throw error;
                }
                const backoff = Math.max(1500 * 2 ** (attempt - 1),
                    error.response?.headers?.['retry-after'] == null ? 0 :
                        retryAfterMs(error.response.headers['retry-after'], now()));
                // A new run must not bypass an unfinished retry wait. Keep the
                // hold durable when this run cannot wait through its deadline or
                // day boundary; ordinary request pacing still uses delay alone.
                if (now() + backoff >= deadline || jstDate(now() + backoff) !== budget.date) {
                    throw block('retry-backoff', backoff, 'Retry backoff continues beyond this collection run');
                }
                await delay(backoff);
            }
        }
    }

    function finish() {
        finished = true;
        if (reservationId && !budget.reservation.completed) {
            if (budget.reservation.limit !== null) budget.requests -= budget.reservation.limit - budget.reservation.used;
            budget.reservation.completed = true;
            persistBudget();
        }
    }

    return { get: request, check, remaining, stop, finish, getBudget: () => structuredClone(budget),
        getAttemptCount: () => attemptCount, getActualRequests: () => actualRequests(budget) };
}

module.exports = {
    CollectionStop, DAILY_REQUEST_LIMIT, MAX_EXECUTION_TIME_MS, REQUEST_INTERVAL_MS, SAVE_BUFFER_MS,
    createRequestClient, getStopTargetTime, jstDate, readJson, reserveDailyAllowance, retryAfterMs, writeJson
};
