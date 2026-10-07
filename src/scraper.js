const axios = require('axios');
const cheerio = require('cheerio');
const fs = require('fs');
const path = require('path');

const SEARCH_URLS = [
    'https://booth.pm/ja/browse/3D%E3%83%A2%E3%83%87%E3%83%AB?sort=new&tags%5B%5D=VRChat&type=digital',
    'https://booth.pm/ja/browse/%E3%82%BD%E3%83%95%E3%83%88%E3%82%A6%E3%82%A7%E3%82%A2?sort=new&tags%5B%5D=VRChat&type=digital'
];

const {
    CollectionStop, createRequestClient, getStopTargetTime, jstDate, writeJson
} = require('./collection-runtime');
const { shouldContinueCollection } = require('./continuation');

const DATA_DIR = path.join(__dirname, '..', 'data');
const MAX_PAGES = 3333; // BOOTH's search limit; keep both full categories.

async function scrapeSearchPage(url, client) {
    try {
        console.log(`Scraping Search: ${url}`);
        const response = await client.get(url, { redirectPolicy: 'same-url' });
        if (response.status !== 200) throw new Error(`Search returned HTTP ${response.status}`);
        const $ = cheerio.load(response.data);
        const productIds = [];
        let invalidCard = false;
        $('.item-card').each((i, el) => {
            const id = $(el).attr('data-product-id');
            if (id && /^[1-9]\d*$/.test(id)) productIds.push(id);
            else invalidCard = true;
        });
        if (invalidCard) throw new Error('Search card is missing a valid product ID');
        if (productIds.length > 0) return { kind: 'success', ids: [...new Set(productIds)] };
        // A failed/challenge/unrecognized response is not proof of an empty page.
        const searchShell = $('title').text().includes('BOOTH') &&
            $('a[href*="/browse/"], form[action*="/search"], form[action*="/browse/"]').length > 0;
        const explicitEmpty = /(?:商品が見つかりませんでした|検索結果はありません|検索結果がありません|該当する商品[はが]ありません)/.test($('body').text());
        if (!searchShell || !explicitEmpty) throw new Error('Unrecognized search page markup');
        return { kind: 'empty', ids: [] };
    } catch (error) {
        console.error(`Error scraping search ${url}:`, error.message);
        return { kind: 'failure', error };
    }
}

// A trailing shop sale badge: a final (...) containing a number, a %/円, and a discount
// word (OFF/オフ/SALE/セール) in any order — "(30% OFF)", "(30% SALE)", "(890円 OFF)".
// Requiring all three keeps real names like "(コットン100%)" or "(…100％割引)" intact.
// No /g flag, so .test() is stateless and safe to reuse.
const SALE_BADGE_RE = /\s*[\(（](?=[^)）]*\d)(?=[^)）]*[%％円])(?=[^)）]*(?:OFF|オフ|SALE|セール))[^)）]*[\)）]\s*$/i;

/**
 * Removes a trailing sale badge AND collapses stray whitespace so a variation's price
 * history stays under one stable key, e.g. "✧ Shinano | しなの (30% OFF)" -> "✧ Shinano | しなの".
 */
function normalizeVariationName(name) {
    return name
        .replace(SALE_BADGE_RE, '')
        .replace(/\s{2,}/g, ' ')
        .trim();
}

async function scrapeProductDetails(productId, client) {
    const url = `https://booth.pm/ja/items/${productId}`;
    try {
        const response = await client.get(url, { productId: String(productId) });
        if (response.status === 404 || response.status === 410) {
            return { kind: 'unavailable', id: productId, status: response.status };
        }
        if (response.status !== 200) throw new Error(`Product returned HTTP ${response.status}`);
        const $ = cheerio.load(response.data);

        // New selector: h2 is the title
        const name = $('h2').first().text().trim();
        const variations = [];

        // New selectors: .variation-item, .variation-name, .variation-price
        $('.variation-item').each((i, el) => {
            const rawName = $(el).find('.variation-name').text().trim() || 'default';
            // BOOTH gives every variation a stable internal ID (data-product-variant, aka
            // cart_item_variation_id) that does NOT change when the shop renames the
            // variation. Some shops rewrite the name on every sale (e.g.
            // "✧ Shinano | しなの (30% OFF)"), which would otherwise spawn a brand new key
            // each time. Capturing the ID lets us anchor history to identity, not name.
            const variantId = $(el).find('[data-product-variant]').first().attr('data-product-variant') || null;
            // Strip a trailing discount badge for a clean, stable display label. The
            // presence of that badge (not mere whitespace cleanup) tells us it's on sale.
            const vName = normalizeVariationName(rawName);
            const nameImpliesSale = SALE_BADGE_RE.test(rawName);
            const priceText = $(el).find('.variation-price, .price, .text-20.font-bold').first().text();
            const price = /^\s*無料\s*$/.test(priceText) ? 0 : parseInt(priceText.replace(/[^\d]/g, ''), 10);

            // Check for sale class or indicator
            const isSale = nameImpliesSale ||
                $(el).find('.price, .variation-price').hasClass('is-sale') ||
                $(el).find('.is-sale').length > 0;

            if (!isNaN(price)) {
                variations.push({ name: vName, price, isSale, variantId });
            }
        });

        // Fallback for older or different layouts if any
        if (variations.length === 0) {
            const priceText = $('.item-detail__price .price, .price, .text-20.font-bold').first().text();
            const price = /^\s*無料\s*$/.test(priceText) ? 0 : parseInt(priceText.replace(/[^\d]/g, ''), 10);
            const isSale = $('.price').hasClass('is-sale') || $('.is-sale').length > 0;
            if (!isNaN(price)) {
                variations.push({ name: 'default', price, isSale });
            }
        }

        // Detect sale keywords in title
        const saleKeywords = ['sale', 'セール', '割引', '期間限定', 'off'];
        const hasSaleKeyword = saleKeywords.some(k => name.toLowerCase().includes(k));

        if (!name || variations.length === 0) throw new Error('Unrecognized product page or missing price');
        return { kind: 'success', product: { id: productId, name, variations, hasSaleKeyword } };
    } catch (error) {
        console.error(`Error scraping item ${productId}:`, error.message);
        return { kind: 'failure', error };
    }
}

async function saveProductData(product, { dataDir = DATA_DIR, today = jstDate(Date.now()) } = {}) {
    const shard = product.id.toString().substring(0, 3);
    const shardDir = path.join(dataDir, shard);
    if (!fs.existsSync(shardDir)) {
        fs.mkdirSync(shardDir, { recursive: true });
    }

    const filePath = path.join(shardDir, `${product.id}.json`);
    let result = {
        id: product.id,
        name: product.name,
        variations: {}
    };

    if (fs.existsSync(filePath)) {
        try {
            const existing = JSON.parse(fs.readFileSync(filePath, 'utf8'));
            if (existing && typeof existing === 'object' && !Array.isArray(existing)) {
                const record = value => value && typeof value === 'object' && !Array.isArray(value);
                if ((existing.variations !== undefined && (!record(existing.variations) ||
                    !Object.values(existing.variations).every(history => Array.isArray(history) && history.every(entry =>
                        record(entry) && typeof entry.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(entry.date) &&
                        Number.isFinite(entry.price) && entry.price >= 0)))) ||
                    (existing.variation_keys !== undefined && (!record(existing.variation_keys) ||
                        !Object.values(existing.variation_keys).every(key => typeof key === 'string' &&
                            record(existing.variations) && Object.hasOwn(existing.variations, key))))) {
                    throw new Error('History has incompatible variation records');
                }
                result = existing;
                // [Self-Healing] Update name if it's missing or empty
                if (product.name && (!result.name || result.name.trim() === "")) {
                    result.name = product.name;
                }
            } else {
                throw new Error('History must be a JSON object');
            }
        } catch (e) {
            const error = new Error(`Cannot read existing history for ${product.id}: ${e.message}`, { cause: e });
            // A single malformed legacy record must not pin the entire crawl.
            // Real I/O failures keep their system code and stop collection.
            error.code = e.code || 'HISTORY_CORRUPT';
            throw error;
        }
    }

    // Shop-provided names and variant IDs may legitimately be "constructor" or
    // "__proto__". Treat every key as data, never as an inherited property.
    result.variations = Object.assign(Object.create(null), result.variations || {});
    // Map of BOOTH's stable variation ID -> the canonical key we store its history under.
    // Anchoring identity to the ID means a shop renaming a variation (sale badges, emoji,
    // reworded names) can never split one variation into multiple keys / chart lines.
    result.variation_keys = Object.assign(Object.create(null), result.variation_keys || {});

    // Update each variation
    product.variations.forEach(v => {
        // Resolve the stable storage key for this variation.
        let key = (v.variantId && result.variation_keys[v.variantId]) || null;
        if (!key) {
            key = v.name;
            // First time we see this ID and there is no clean bucket yet: adopt an existing
            // bucket that normalizes to the same name (older data collected before
            // ID-anchoring, possibly fragmented by sale badges) so history stays continuous.
            if (!result.variations[key]) {
                const match = Object.keys(result.variations)
                    .find(k => normalizeVariationName(k) === v.name);
                if (match) key = match;
            }
            if (v.variantId) {
                result.variation_keys[v.variantId] = key;
            }
        }

        if (!result.variations[key]) {
            result.variations[key] = [];
        }

        const history = result.variations[key];
        const existingEntryIndex = history.findIndex(entry => entry.date === today);

        // Price drop heuristic
        const lastValidEntry = [...history].reverse().find(entry => entry.date !== today);
        let isSaleFinal = v.isSale || product.hasSaleKeyword;
        if (!isSaleFinal && lastValidEntry && v.price < lastValidEntry.price) {
            isSaleFinal = true;
        }

        const newEntry = {
            date: today,
            price: v.price,
            is_sale: isSaleFinal
        };

        if (existingEntryIndex !== -1) {
            history[existingEntryIndex] = newEntry;
        } else {
            history.push(newEntry);
        }
        history.sort((a, b) => a.date.localeCompare(b.date));
    });

    writeJson(filePath, result);
}

const BATCH_SIZE = 5;
const RETRY_BASE_MS = 60 * 60 * 1000;
const RETRY_MAX_MS = 24 * RETRY_BASE_MS;
const validId = id => typeof id === 'string' && /^[1-9]\d*$/.test(id);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function loadState(stateFile = path.join(DATA_DIR, 'crawl_state.json'), { categories = SEARCH_URLS.length, maxPages = MAX_PAGES } = {}) {
    if (!fs.existsSync(stateFile)) return { urlIndex: 0, page: 1, retries: [] };
    const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
    const pending = state?.pendingIds;
    const retries = state?.retries;
    if (!state || Array.isArray(state) || !Number.isSafeInteger(state.urlIndex) || state.urlIndex < 0 || state.urlIndex > categories ||
        !Number.isSafeInteger(state.page) || state.page < 1 || state.page > maxPages + 1 ||
        (pending !== undefined && (!Array.isArray(pending) || !pending.every(validId) || new Set(pending).size !== pending.length)) ||
        (retries !== undefined && (!Array.isArray(retries) || !retries.every(entry => entry && validId(entry.id) &&
            Number.isSafeInteger(entry.failures) && entry.failures > 0 && Number.isSafeInteger(entry.nextAttemptAt) && entry.nextAttemptAt >= 0) ||
            new Set(retries.map(entry => entry.id)).size !== retries.length)) ||
        (state.urlIndex === categories && (state.page !== 1 || pending !== undefined)) ||
        (state.page > maxPages && pending !== undefined)) {
        throw new Error('Invalid crawl checkpoint; refusing to reset it');
    }
    return { urlIndex: state.urlIndex, page: state.page, ...(pending === undefined ? {} : { pendingIds: pending }), retries: retries || [] };
}

async function main({
    dataDir = DATA_DIR, searchUrls = SEARCH_URLS, maxPages = MAX_PAGES,
    get = axios.get, search = scrapeSearchPage, detail = scrapeProductDetails, save = saveProductData,
    now = Date.now, wait = sleep, client: suppliedClient, requestIntervalMs,
    jobStartedAt = process.env.SCRAPER_JOB_STARTED_AT, reservationId = process.env.SCRAPER_RESERVATION_ID,
    log = console.log, logError = console.error
} = {}) {
    const startedAt = now();
    const deadline = getStopTargetTime(startedAt, jobStartedAt ?? startedAt).getTime();
    const stateFile = path.join(dataDir, 'crawl_state.json');
    // Load before constructing a client: corrupt state must never start HTTP or
    // be silently replaced with a fresh cursor.
    let state = loadState(stateFile, { categories: searchUrls.length, maxPages });
    const startedMidSweep = state.urlIndex > 0 || state.page > 1 || Boolean(state.pendingIds?.length);
    fs.mkdirSync(dataDir, { recursive: true });
    const client = suppliedClient || createRequestClient({
        get, budgetFile: path.join(dataDir, 'request_budget.json'), deadline, now, wait, reservationId,
        ...(requestIntervalMs === undefined ? {} : { intervalMs: requestIntervalMs })
    });
    const initialBudget = client.getBudget?.();
    const processedIds = new Set();
    const metrics = { searchPages: 0, searchFailures: 0, itemSuccess: 0, itemFailures: 0, unavailable: 0, retries: 0, duplicatesAvoided: 0 };
    let haltError;
    let fatalError;

    function halt(error) {
        // A failed disk write is more serious than a normal time/quota pause.
        if (!haltError || (!(error instanceof CollectionStop) || error.failed)) haltError = error;
        client.stop?.(error.reason || 'storage', error.message, !(error instanceof CollectionStop) || error.failed);
    }
    function checkpoint(next = state) {
        try {
            writeJson(stateFile, next);
            state = next;
        } catch (error) {
            fatalError = error;
            halt(error);
            throw error;
        }
    }
    function check() {
        if (haltError) throw haltError;
        if (now() >= deadline) throw new CollectionStop('deadline', 'Collection time budget reached');
        client.check?.();
    }
    async function pause(ms) {
        check();
        if (now() + ms >= deadline) throw new CollectionStop('deadline', 'Not enough collection time for crawl delay');
        await wait(ms);
        check();
    }
    function nextPage() {
        const page = state.page + 1;
        checkpoint({ urlIndex: state.urlIndex + (page > maxPages ? 1 : 0), page: page > maxPages ? 1 : page, retries: state.retries });
    }
    function retryEntry(id, unavailable) {
        const previous = state.retries.find(entry => entry.id === id);
        const failures = Math.min(Number.MAX_SAFE_INTEGER, (previous?.failures || 0) + 1);
        const delay = unavailable ? RETRY_MAX_MS : Math.min(RETRY_MAX_MS, RETRY_BASE_MS * 2 ** Math.min(failures - 1, 5));
        return { id, failures, nextAttemptAt: now() + delay };
    }

    async function batch(ids, retry = false) {
        check();
        // Each worker resolves with an outcome. Promise.all remains the original
        // five-item barrier, including after a stop or a save failure. No final
        // checkpoint or quota refund can race an already-started request.
        const results = await Promise.all(ids.map(async id => {
            try {
                if (processedIds.has(id)) {
                    metrics.duplicatesAvoided++;
                    return { id, kind: 'skipped' };
                }
                // Its already-durable retry entry makes skipping safe without
                // bypassing backoff when the same product appears in search.
                if (state.retries.some(entry => entry.id === id && entry.nextAttemptAt > now())) return { id, kind: 'skipped' };
                check();
                processedIds.add(id);
                const result = await detail(id, client);
                if (result?.kind === 'success') {
                    try {
                        await save(result.product, { dataDir, today: jstDate(now()) });
                    } catch (error) {
                        if (error.code === 'HISTORY_CORRUPT') {
                            logError(`Item ${id}: ${error.message}`);
                            return { id, kind: 'failure' };
                        }
                        fatalError = error;
                        halt(error);
                        return { id, kind: 'stopped' };
                    }
                    return { id, kind: 'success' };
                }
                if (result?.kind === 'unavailable' && [404, 410].includes(result.status)) return { id, kind: 'unavailable' };
                throw result?.error || new Error('Invalid product outcome');
            } catch (error) {
                if ((error instanceof CollectionStop && !['redirect', 'http'].includes(error.reason)) || haltError) {
                    halt(error);
                    return { id, kind: 'stopped' };
                }
                logError(`Item ${id}: ${error.message}`);
                return { id, kind: 'failure' };
            }
        }));
        const settledIds = new Set();
        const retries = new Map(state.retries.map(entry => [entry.id, entry]));
        for (const result of results) {
            if (result.kind === 'stopped') continue;
            settledIds.add(result.id);
            if (result.kind === 'skipped') continue;
            if (retry) metrics.retries++;
            if (result.kind === 'success') {
                metrics.itemSuccess++;
                retries.delete(result.id);
            } else {
                if (result.kind === 'unavailable') metrics.unavailable++;
                else metrics.itemFailures++;
                retries.set(result.id, retryEntry(result.id, result.kind === 'unavailable'));
            }
        }
        // History writes finished above. A failed item leaves pendingIds only
        // in the same atomic checkpoint that durably adds its retry entry.
        checkpoint({ ...state, retries: [...retries.values()],
            ...(state.pendingIds === undefined ? {} : { pendingIds: state.pendingIds.filter(id => !settledIds.has(id)) }) });
        check();
        await pause(1000);
    }

    async function retryBatch() {
        const ids = state.retries.filter(entry => entry.nextAttemptAt <= now() && !processedIds.has(entry.id))
            .sort((a, b) => a.nextAttemptAt - b.nextAttemptAt).slice(0, BATCH_SIZE).map(entry => entry.id);
        if (!ids.length) return false;
        await batch(ids, true);
        return true;
    }

    let result;
    try {
        // A completed sweep starts over on the next run, as in the original
        // crawler. Only failed IDs survive; there is no catalog/success ledger.
        if (state.urlIndex === searchUrls.length) checkpoint({ urlIndex: 0, page: 1, retries: state.retries });
        else checkpoint();
        await retryBatch();
        while (state.urlIndex < searchUrls.length) {
            check();
            if (state.page > maxPages) {
                checkpoint({ urlIndex: state.urlIndex + 1, page: 1, retries: state.retries });
                continue;
            }
            if (state.pendingIds === undefined) {
                const url = `${searchUrls[state.urlIndex]}&page=${state.page}`;
                let found;
                try { found = await search(url, client); }
                catch (error) { found = { kind: 'failure', error }; }
                metrics.searchPages++;
                if (found?.kind === 'empty') {
                    checkpoint({ urlIndex: state.urlIndex + 1, page: 1, retries: state.retries });
                    await retryBatch();
                    continue;
                }
                if (found?.kind !== 'success' || !Array.isArray(found.ids) || !found.ids.length || !found.ids.every(validId)) {
                    const error = found?.error || new Error('Invalid search outcome');
                    if (error instanceof CollectionStop) throw error;
                    metrics.searchFailures++;
                    throw new CollectionStop('search-failure', `Search page failed; cursor preserved: ${error.message}`, true);
                }
                // Persist every discovered ID before starting its details.
                checkpoint({ ...state, pendingIds: [...new Set(found.ids)] });
            }
            while (state.pendingIds.length) await batch(state.pendingIds.slice(0, BATCH_SIZE));
            nextPage();
            await pause(2000);
            // A bounded retry batch between pages guarantees retry progress
            // without replacing or starving the sequential search crawl.
            await retryBatch();
        }
        while (await retryBatch()) { /* Drain due failures after the normal sweep. */ }
        checkpoint({ urlIndex: 0, page: 1, retries: state.retries });
        result = { status: state.retries.length ? 'partial' : 'completed',
            ...(state.retries.length ? { reason: 'retry-pending' } : {}), failed: metrics.itemFailures > 0 };
    } catch (error) {
        halt(error);
        logError(error.message);
        result = error instanceof CollectionStop
            ? { status: error.failed ? 'partial' : 'paused', reason: error.reason, failed: error.failed }
            : { status: 'failed', reason: 'storage', failed: true };
    } finally {
        // All batch work was drained before reaching this point, including
        // successes which arrived after another request tripped the circuit.
        let checkpointSaved = false;
        try { checkpoint(); checkpointSaved = true; } catch { /* Keep the durable reservation charged until recovery. */ }
        if (checkpointSaved) {
            try { client.finish?.(); }
            catch (error) { fatalError = error; logError(`Cannot finish request budget: ${error.message}`); }
        }
    }
    if (fatalError) result = { status: 'failed', reason: 'storage', failed: true };
    const finalBudget = client.getBudget?.();
    const actualRequests = budget => budget.requests - (budget.reservation && !budget.reservation.completed && budget.reservation.limit !== null
        ? budget.reservation.limit - budget.reservation.used : 0);
    metrics.chargedHttpAttempts = client.getAttemptCount?.() ?? (initialBudget && finalBudget ? finalBudget.reservation && initialBudget.reservation
        ? finalBudget.reservation.used - initialBudget.reservation.used : actualRequests(finalBudget) - actualRequests(initialBudget) : null);
    metrics.dailyChargedRequests = client.getActualRequests?.() ?? (finalBudget ? actualRequests(finalBudget) : null);
    log(`Collection ${result.status}; saved ${metrics.itemSuccess}, queued retries ${state.retries.length}` +
        (metrics.chargedHttpAttempts === null ? '' : `; charged HTTP attempts ${metrics.chargedHttpAttempts}, daily charged total ${metrics.dailyChargedRequests}`));
    const continueCollection = shouldContinueCollection({ result, metrics, startedAt, stoppedAt: now(), deadline,
        blockedUntil: finalBudget?.blockedUntil, startedMidSweep });
    return { ...result, metrics, continueCollection };
}

// Importing the module for offline tests never starts network collection.
if (require.main === module) {
    // Workflow pushes its active request session before starting. Refuse an
    // accidental untracked CLI collection; tests use the injected main() interface.
    const run = process.env.SCRAPER_RESERVATION_ID
        ? main()
        : Promise.reject(new Error('Run through the workflow with a committed request reservation'));
    run.then(result => {
        console.log(`Collection result: ${result.status}${result.reason ? ` (${result.reason})` : ''}`);
        if (process.env.GITHUB_OUTPUT) {
            fs.appendFileSync(process.env.GITHUB_OUTPUT, `continue_collection=${result.continueCollection === true}\n`);
        }
        if (result.failed || result.status === 'failed') process.exitCode = 1;
    }).catch(error => {
        console.error('Scraper failed:', error);
        process.exitCode = 1;
    });
}

module.exports = {
    normalizeVariationName, scrapeSearchPage, scrapeProductDetails, saveProductData,
    loadState, main, getStopTargetTime
};
