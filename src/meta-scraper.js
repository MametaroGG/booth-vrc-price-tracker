const axios = require('axios');
const fs = require('fs');
const path = require('path');

const {
    CollectionStop, createRequestClient, getStopTargetTime, jstDate, writeJson
} = require('./collection-runtime');
const { shouldContinueMeta } = require('./meta-continuation');

// Item metadata (name, shop, thumbnail, tags, category, wish-list count) is
// collected by a SEPARATE job from the price scraper on purpose: the daily
// price cycle keeps its efficiency, and this job runs its own full-catalog
// sweep under meta/ with its own request ledger. The two jobs write to
// disjoint directories (data/ vs meta/) so their pushes never conflict.
//
// Source of truth per item: BOOTH's own item JSON, https://booth.pm/ja/items/<id>.json
// It carries everything the HTML page renders client-side (tags, category
// breadcrumbs, and the wish-list count shown as the heart number), so one
// request per item is enough and no HTML parsing is needed.

const DATA_DIR = path.join(__dirname, '..', 'data');
const META_DIR = path.join(__dirname, '..', 'meta');
const DEFAULT_RUN_CAP = 250000; // items per run; sized to cover the whole catalog — the run envelope and the JST day boundary pace the sweep, like the price job
const REFRESH_DAYS = 1; // every item is re-fetched daily, mirroring the price sweep
const ACTIVE_WINDOW_DAYS = 14; // items with price activity inside this window are "hot"
const UNAVAILABLE_RETRY_DAYS = 30; // deleted items are re-checked monthly, not daily
const LIKES_HISTORY_CAP = 120; // snapshots kept per item
const BATCH_SIZE = 5;
// Same envelope as the price scraper: one run may collect for up to five
// hours (the runtime's MAX_EXECUTION_TIME_MS), inside a 305-minute step.
// Stopping ourselves at 270 minutes still leaves room for client.finish()
// — which completes the durable request reservation — and for the save
// step to push what was collected. A hard kill by the step timeout would
// strand an unresolved reservation in the ledger and block every later
// run, so the run must always end gracefully.
const DEFAULT_MAX_RUN_MS = 270 * 60 * 1000;

const validId = id => typeof id === 'string' && /^[1-9]\d*$/.test(id);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const shardOf = id => id.substring(0, 3);

function daysBefore(dateStr, days) {
    const time = Date.parse(`${dateStr}T00:00:00Z`);
    if (!Number.isFinite(time)) throw new Error(`Invalid JST date: ${dateStr}`);
    return new Date(time - days * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

// pximg originals look like https://booth.pximg.net/<uuid>/i/<id>/<file>;
// the 620px display variant inserts c/620x620/ after the host. Anything that
// does not match that exact shape keeps the original URL.
function resizedImage(url) {
    if (typeof url !== 'string') return '';
    const match = url.match(/^https:\/\/booth\.pximg\.net\/([0-9a-f-]{36}\/i\/\d+\/.+)$/);
    return match ? `https://booth.pximg.net/c/620x620/${match[1]}` : url;
}

function parseItemJson(productId, data) {
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
        throw new Error('Unrecognized item JSON');
    }
    if (String(data.id) !== String(productId)) {
        throw new Error(`Item JSON id mismatch: expected ${productId}, got ${data.id}`);
    }
    const name = typeof data.name === 'string' ? data.name.trim() : '';
    if (!name) throw new Error('Item JSON is missing a name');
    const shop = data.shop && typeof data.shop === 'object' ? {
        name: typeof data.shop.name === 'string' ? data.shop.name : '',
        subdomain: typeof data.shop.subdomain === 'string' ? data.shop.subdomain : '',
        url: typeof data.shop.url === 'string' ? data.shop.url : ''
    } : null;
    const firstImage = Array.isArray(data.images) && data.images[0] && typeof data.images[0] === 'object'
        ? data.images[0] : null;
    const image = firstImage && typeof firstImage.original === 'string' ? firstImage.original : '';
    const tags = Array.isArray(data.tags)
        ? data.tags.map(tag => tag && typeof tag.name === 'string' ? tag.name : '').filter(Boolean)
        : [];
    const category = data.category && typeof data.category === 'object' ? {
        id: Number.isSafeInteger(data.category.id) ? data.category.id : null,
        name: typeof data.category.name === 'string' ? data.category.name : '',
        parent: data.category.parent && typeof data.category.parent.name === 'string'
            ? data.category.parent.name : ''
    } : null;
    const likes = Number.isSafeInteger(data.wish_lists_count) && data.wish_lists_count >= 0
        ? data.wish_lists_count : null;
    // Declared relations: creators name the parent works (base avatars,
    // required assets) in the description, as BOOTH item URLs. Collect the
    // referenced item ids in first-appearance order, excluding self-links.
    // A bare link is not enough to prove parentage, though: descriptions
    // also cross-sell related works and cite shaders/tools. When the prose
    // gives an explicit context (a supported-avatar section, an inline
    // "made for avatar X" line, a related-works section, a shader/tool
    // note), record the confidently-parent ids separately as base_refs.
    const refs = [];
    let baseRefs = null;
    if (typeof data.description === 'string') {
        const seen = new Set();
        const baseSeen = new Set();
        const pattern = /(?:[a-z0-9-]+\.)?booth\.pm\/(?:[a-z]{2}(?:-[a-z]{2})?\/)?items\/(\d+)/gi;
        const basePattern = /(対応(?:アバター|モデル|3Dモデル|素体|キャラクター|作品)|対象アバター|想定アバター|動作確認|共通素体|ベースアバター|専用(?:アバター|モデル|素体)|こちらへ|베이스\s*(?:모델|아바타)|대응\s*(?:아바타|모델)|호환\s*(?:아바타|모델)|전용\s*(?:아바타|모델|소체)|대상\s*아바타|적용\s*아바타|对应(?:头像|模型|素体)|對應(?:頭像|模型|素體)|专用(?:头像|模型|素体)|專用(?:頭像|模型|素體)|基础模型|基礎模型|base\s*model|supported\s*(?:avatars?|models?)|compatible\s*(?:avatars?|models?|with)|made\s+for|designed\s+for|find\s+.{0,40}\s+here)/i;
        const relatedPattern = /(関連(?:作品|商品)|おすすめ|オススメ|コーデ|新バージョン|リメイク版|別バージョン|他の商品|セット(?:内容|商品)|관련\s*(?:상품|작품)|추천\s*(?:상품|코디)|관련상품|推荐(?:商品|搭配)|推薦(?:商品|搭配)|相关(?:产品|作品)|相關(?:產品|作品)|related\s*(?:items?|products?|works?)|you\s+may\s+also\s+like|recommended)/i;
        const dependencyPattern = /(使用\s*(?:Shader|シェーダー|ツール)|Shader|シェーダー|lilToon|導入(?:方法|手順)|着せ替え|Auto Dresser|メッシュデリーター|下着を消す|アセットを導入|쉐이더|셰이더|사용\s*(?:툴|도구)|설치\s*(?:방법|법)|着色器|使用的(?:工具|着色器)|安裝(?:方法|說明)|安装(?:方法|说明)|shader|requirements?|how\s+to\s+(?:install|use)|installation)/i;
        const contextOf = text => {
            if (dependencyPattern.test(text)) return 'dependency';
            if (relatedPattern.test(text)) return 'related';
            if (basePattern.test(text)) return 'base';
            return null;
        };
        let section = 'plain';
        let judged = false;
        for (const line of data.description.split(/\r?\n/)) {
            const ids = [...line.matchAll(pattern)].map(match => match[1]);
            const text = line.replace(/https?:\/\/\S+/g, '').trim();
            const lineContext = contextOf(text) || contextOf(line);
            if (lineContext) {
                section = lineContext;
                judged = true;
            } else if (!ids.length && text) {
                // A new, unlabelled section or a long prose paragraph ends
                // the previous labelled list. Short entry titles inside a
                // labelled list do not.
                const separator = /^[=━─┅⊹*・\s]+$/.test(text);
                const genericHeading = text.length <= 60 && (/^[■◆●▶▷]/.test(text) || /[：:]$/.test(text));
                if (separator || genericHeading || text.length > 100) section = 'plain';
            }
            const context = lineContext || section;
            for (const id of ids) {
                if (id === String(productId)) continue;
                if (!seen.has(id)) {
                    seen.add(id);
                    refs.push(id);
                }
                if (context === 'base' && !baseSeen.has(id)) {
                    baseSeen.add(id);
                    (baseRefs ??= []).push(id);
                }
                if (refs.length >= 100) break;
            }
            if (refs.length >= 100) break;
        }
        // Only publish the stricter list when the description actually
        // identified at least one parent in context. Otherwise the field
        // stays absent and consumers fall back to refs, rather than a
        // false claim that the item has no parents.
        if (!baseRefs || !baseRefs.length) baseRefs = null;
        void judged;
    }
    return {
        id: String(productId),
        name,
        shop,
        image,
        image_resized: resizedImage(image),
        tags,
        category,
        likes,
        refs,
        ...(baseRefs ? { base_refs: baseRefs } : {}),
        adult: data.is_adult === true,
        sold_out: data.is_sold_out === true,
        end_of_sale: data.is_end_of_sale === true,
        published_at: typeof data.published_at === 'string' ? data.published_at : null
    };
}

function buildRecord(parsed, { today, previous = null } = {}) {
    const history = Array.isArray(previous?.likes_history)
        ? previous.likes_history.filter(entry => entry && typeof entry.date === 'string' &&
            /^\d{4}-\d{2}-\d{2}$/.test(entry.date) && Number.isSafeInteger(entry.count) && entry.count >= 0)
        : [];
    if (parsed.likes !== null) {
        const entry = { date: today, count: parsed.likes };
        const index = history.findIndex(e => e.date === today);
        if (index >= 0) history[index] = entry;
        else history.push(entry);
        history.sort((a, b) => a.date.localeCompare(b.date));
    }
    return { ...parsed, likes_history: history.slice(-LIKES_HISTORY_CAP), fetched_at: today };
}

async function fetchItemMeta(productId, client) {
    const url = `https://booth.pm/ja/items/${productId}.json`;
    try {
        const response = await client.get(url, { productId: String(productId) });
        if (response.status === 404 || response.status === 410) {
            return { kind: 'unavailable', id: productId, status: response.status };
        }
        if (response.status !== 200) throw new Error(`Item JSON returned HTTP ${response.status}`);
        const data = typeof response.data === 'string' ? JSON.parse(response.data) : response.data;
        return { kind: 'success', meta: parseItemJson(productId, data) };
    } catch (error) {
        // The request client already turns 404/410 into responses, but an
        // injected transport (tests, future clients) may reject instead.
        const status = error?.response?.status;
        if (status === 404 || status === 410) return { kind: 'unavailable', id: productId, status };
        return { kind: 'failure', error };
    }
}

function metaFilePath(metaDir, id) {
    return path.join(metaDir, shardOf(id), `${id}.json`);
}

function readPreviousMeta(metaDir, id) {
    try {
        const parsed = JSON.parse(fs.readFileSync(metaFilePath(metaDir, id), 'utf8'));
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null;
    } catch {
        // Metadata is fully regenerable from BOOTH, so an unreadable file is
        // treated as missing and simply collected again (unlike price history).
        return null;
    }
}

function listProductIds(dataDir) {
    if (!fs.existsSync(dataDir)) return [];
    const ids = [];
    for (const shard of fs.readdirSync(dataDir)) {
        if (!/^\d{3}$/.test(shard)) continue;
        const dir = path.join(dataDir, shard);
        if (!fs.statSync(dir).isDirectory()) continue;
        for (const file of fs.readdirSync(dir)) {
            const match = file.match(/^([1-9]\d*)\.json$/);
            if (match) ids.push(match[1]);
        }
    }
    return ids;
}

// "Hot" items are the ones that can plausibly surface on the site's
// featured/trending surfaces, so they get a fresh likes snapshot every day
// (likes_history is date-keyed, exactly like price history: one point per
// day is the matching resolution). Activity is read from the price data
// itself: on sale at the latest observation, a price change inside the
// window, or first tracked inside the window. Histories in data/ are stored
// date-sorted, so first/last entries are the bounds.
function readActivity(dataDir, id, cutoff) {
    try {
        const parsed = JSON.parse(fs.readFileSync(path.join(dataDir, shardOf(id), `${id}.json`), 'utf8'));
        const histories = parsed && parsed.variations && typeof parsed.variations === 'object'
            ? Object.values(parsed.variations) : [];
        for (const history of histories) {
            if (!Array.isArray(history) || !history.length) continue;
            const first = history[0];
            const last = history[history.length - 1];
            if (typeof first?.date === 'string' && first.date >= cutoff) return true; // newly tracked
            if (last?.is_sale === true && typeof last.date === 'string' && last.date >= cutoff) return true;
            for (let i = 1; i < history.length; i++) {
                const entry = history[i];
                if (typeof entry?.date === 'string' && entry.date >= cutoff &&
                    entry.price !== history[i - 1].price) return true;
            }
        }
        return false;
    } catch {
        return false;
    }
}

function buildWorkList({ dataDir, metaDir, today, runCap = DEFAULT_RUN_CAP,
    refreshDays = REFRESH_DAYS, unavailableRetryDays = UNAVAILABLE_RETRY_DAYS,
    activeWindowDays = ACTIVE_WINDOW_DAYS } = {}) {
    const refreshCutoff = daysBefore(today, refreshDays);
    const unavailableCutoff = daysBefore(today, unavailableRetryDays);
    const activeCutoff = daysBefore(today, activeWindowDays);
    const missing = [];
    const hot = [];
    const stale = [];
    for (const id of listProductIds(dataDir)) {
        const previous = readPreviousMeta(metaDir, id);
        if (!previous) {
            missing.push({ id, previous: null });
            continue;
        }
        const fetchedAt = typeof previous.fetched_at === 'string' ? previous.fetched_at : '';
        if (previous.unavailable === true) {
            if (!fetchedAt || fetchedAt <= unavailableCutoff) stale.push({ id, previous, fetchedAt });
            continue;
        }
        if (fetchedAt >= today) continue; // already collected today
        if (readActivity(dataDir, id, activeCutoff)) {
            hot.push({ id, previous, fetchedAt });
        } else if (!fetchedAt || fetchedAt <= refreshCutoff) {
            stale.push({ id, previous, fetchedAt });
        }
    }
    // New items first (higher IDs are newer discoveries), then hot items
    // (stalest snapshot first) for the daily likes delta, then the quiet
    // refresh cycle so it still reaches everything evenly.
    // Records collected before refs extraction shipped have no refs key at
    // all; refresh those first so declared relations backfill fastest.
    const lacksRefs = e => (e.previous && (!('refs' in e.previous) ||
        (Array.isArray(e.previous.refs) && e.previous.refs.length && !('base_refs' in e.previous))) ? 0 : 1);
    missing.sort((a, b) => Number(b.id) - Number(a.id));
    hot.sort((a, b) => lacksRefs(a) - lacksRefs(b) || a.fetchedAt.localeCompare(b.fetchedAt) || Number(b.id) - Number(a.id));
    stale.sort((a, b) => lacksRefs(a) - lacksRefs(b) || a.fetchedAt.localeCompare(b.fetchedAt) || Number(a.id) - Number(b.id));
    return [...missing, ...hot, ...stale].slice(0, runCap);
}

function saveMeta(parsed, { metaDir, today, previous = null }) {
    const record = buildRecord(parsed, { today, previous });
    writeJson(metaFilePath(metaDir, parsed.id), record);
    return record;
}

function saveUnavailable(id, status, { metaDir, today }) {
    writeJson(metaFilePath(metaDir, id), { id: String(id), unavailable: true, status, fetched_at: today });
}

async function main({
    dataDir = DATA_DIR, metaDir = META_DIR, runCap = DEFAULT_RUN_CAP,
    maxRunMs = DEFAULT_MAX_RUN_MS,
    get = axios.get, fetchMeta = fetchItemMeta, now = Date.now, wait = sleep,
    client: suppliedClient, jobStartedAt = process.env.META_JOB_STARTED_AT,
    reservationId = process.env.META_RESERVATION_ID,
    log = console.log, logError = console.error
} = {}) {
    const startedAt = now();
    const deadline = Math.min(
        getStopTargetTime(startedAt, jobStartedAt ?? startedAt).getTime(),
        startedAt + maxRunMs);
    const today = jstDate(startedAt);
    const work = buildWorkList({ dataDir, metaDir, today, runCap });
    fs.mkdirSync(metaDir, { recursive: true });
    const client = suppliedClient || createRequestClient({
        get, budgetFile: path.join(metaDir, 'request_budget.json'), deadline, now, wait, reservationId
    });
    const metrics = { planned: work.length, success: 0, unavailable: 0, failures: 0 };
    let haltError;

    function check() {
        if (haltError) throw haltError;
        if (now() >= deadline) throw new CollectionStop('deadline', 'Collection time budget reached');
        client.check?.();
    }
    async function pause(ms) {
        check();
        if (now() + ms >= deadline) throw new CollectionStop('deadline', 'Not enough collection time for metadata delay');
        await wait(ms);
        check();
    }

    let result;
    let finalBudget;
    try {
        for (let index = 0; index < work.length; index += BATCH_SIZE) {
            check();
            const batch = work.slice(index, index + BATCH_SIZE);
            const outcomes = await Promise.all(batch.map(async entry => {
                try {
                    check();
                    const outcome = await fetchMeta(entry.id, client);
                    if (outcome?.kind === 'success') {
                        saveMeta(outcome.meta, { metaDir, today, previous: entry.previous });
                        return 'success';
                    }
                    if (outcome?.kind === 'unavailable') {
                        saveUnavailable(entry.id, outcome.status, { metaDir, today });
                        return 'unavailable';
                    }
                    throw outcome?.error || new Error('Invalid metadata outcome');
                } catch (error) {
                    if (error instanceof CollectionStop || haltError) {
                        if (!haltError) haltError = error;
                        return 'stopped';
                    }
                    logError(`Item ${entry.id}: ${error.message}`);
                    return 'failure';
                }
            }));
            for (const outcome of outcomes) {
                if (outcome === 'success') metrics.success++;
                else if (outcome === 'unavailable') metrics.unavailable++;
                else if (outcome === 'failure') metrics.failures++;
            }
            if (haltError) throw haltError;
            if (index + BATCH_SIZE < work.length) await pause(1000);
        }
        result = { status: metrics.failures ? 'partial' : 'completed', failed: metrics.failures > 0 };
    } catch (error) {
        haltError = haltError || error;
        logError(error.message);
        result = error instanceof CollectionStop
            ? { status: error.failed ? 'partial' : 'paused', reason: error.reason, failed: error.failed }
            : { status: 'failed', reason: 'storage', failed: true };
    } finally {
        try {
            writeJson(path.join(metaDir, 'meta_state.json'), {
                last_run_at: new Date(now()).toISOString(),
                last_run_date: today,
                status: result?.status ?? 'unknown',
                planned: metrics.planned,
                success: metrics.success,
                unavailable: metrics.unavailable,
                failures: metrics.failures,
                charged_http_attempts: client.getAttemptCount?.() ?? null
            });
        } catch (error) {
            logError(`Cannot save metadata run state: ${error.message}`);
        }
        try { finalBudget = client.getBudget?.(); } catch { /* Continuation defaults to off. */ }
        try { client.finish?.(); }
        catch (error) { logError(`Cannot finish request budget: ${error.message}`); }
    }
    metrics.processed = metrics.success + metrics.unavailable + metrics.failures;
    metrics.chargedHttpAttempts = client.getAttemptCount?.() ?? 0;
    const continueCollection = shouldContinueMeta({
        result, metrics, startedAt, stoppedAt: now(), deadline,
        blockedUntil: finalBudget?.blockedUntil ?? 0,
        capReached: work.length >= runCap
    });
    log(`Metadata collection ${result.status}; planned ${metrics.planned}, saved ${metrics.success}, ` +
        `unavailable ${metrics.unavailable}, failures ${metrics.failures}` +
        (continueCollection ? '; continuation requested' : ''));
    return { ...result, metrics, continueCollection };
}

// Importing the module for offline tests never starts network collection.
if (require.main === module) {
    // The workflow pushes its active request session before starting. Refuse
    // an accidental untracked CLI collection; tests use the injected main().
    const run = process.env.META_RESERVATION_ID
        ? main()
        : Promise.reject(new Error('Run through the workflow with a committed request reservation'));
    run.then(result => {
        console.log(`Metadata collection result: ${result.status}${result.reason ? ` (${result.reason})` : ''}`);
        if (process.env.GITHUB_OUTPUT) {
            fs.appendFileSync(process.env.GITHUB_OUTPUT, `continue_collection=${result.continueCollection === true}\n`);
        }
        if (result.failed || result.status === 'failed') process.exitCode = 1;
    }).catch(error => {
        console.error('Metadata scraper failed:', error);
        process.exitCode = 1;
    });
}

module.exports = {
    DEFAULT_RUN_CAP, DEFAULT_MAX_RUN_MS, REFRESH_DAYS, ACTIVE_WINDOW_DAYS, UNAVAILABLE_RETRY_DAYS,
    resizedImage, parseItemJson, buildRecord, fetchItemMeta, readActivity,
    buildWorkList, saveMeta, saveUnavailable, main
};
