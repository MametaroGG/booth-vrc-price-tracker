const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { main } = require('../src/scraper');
const { CatalogRegistry } = require('../src/catalog-registry');
const { createRequestClient, jstDate, reserveDailyAllowance, writeJson } = require('../src/collection-runtime');

const START = Date.parse('2026-10-05T01:00:00Z');
const EMPTY = '<title>BOOTH</title><a href="/ja/browse/3D">3D</a><p>商品が見つかりませんでした</p>';
const product = id => `<h2>Product ${id}</h2><div class="variation-item"><span class="variation-name">default</span><b class="variation-price">100円</b></div>`;
const cards = ids => ids.map(id => `<div class="item-card" data-product-id="${id}"></div>`).join('');
function fixture(t, count = 0) {
    const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'boopa-collector-'));
    t.after(() => fs.rmSync(dataDir, { recursive: true, force: true }));
    const ids = Array.from({ length: count }, (_, i) => String(1000 + i));
    for (const id of ids) writeJson(path.join(dataDir, id.slice(0, 3), `${id}.json`), {
        id, name: `Old ${id}`, variations: { default: [{ date: '2026-01-01', price: 100 }] }
    });
    const budgetFile = path.join(dataDir, 'request_budget.json');
    writeJson(budgetFile, { date: jstDate(START), requests: 0, blockedUntil: 0 });
    let run = 0;
    const calls = [];
    async function collect({ get, cap = 48000, time = START, ...options } = {}) {
        const reservationId = `fixture-${++run}`;
        reserveDailyAllowance({ budgetFile, reservationId, now: time });
        const wrappedGet = async (url, config) => {
            calls.push(url);
            return get ? get(url, config) : { status: 200, data: url.includes('/items/') ? product(url.split('/').at(-1)) : EMPTY };
        };
        const client = createRequestClient({
            get: wrappedGet, budgetFile, reservationId, now: () => time, deadline: time + 5 * 3600000,
            dailyLimit: cap, intervalMs: 0, laneBudgets: true, wait: async () => {}
        });
        return main({ dataDir, reservationId, now: () => time, client, log: () => {}, logError: () => {}, ...options });
    }
    return { dataDir, ids, budgetFile, calls, collect,
        registry: () => new CatalogRegistry({ dataDir, now: () => START }).bootstrap() };
}

test('known IDs omitted from filtered search still refresh; new IDs enter only through the original filtered URLs', async t => {
    const f = fixture(t, 3);
    let searches = 0;
    const result = await f.collect({ get: async url => {
        if (url.includes('/items/')) return { status: 200, data: product(url.split('/').at(-1)) };
        searches++;
        return { status: 200, data: searches === 1 ? cards(['9999', f.ids[0]]) : EMPTY };
    } });
    const fetched = f.calls.filter(url => url.includes('/items/')).map(url => url.split('/').at(-1)).sort();
    assert.deepEqual(fetched, [...f.ids, '9999'].sort());
    assert.equal(result.metrics.uniqueUpdated, 4);
    assert.equal(result.metrics.discovered, 1);
    assert.equal(result.metrics.duplicatesAvoided, 1);
    for (const url of f.calls.filter(url => !url.includes('/items/'))) {
        const parsed = new URL(url);
        assert.equal(parsed.hostname, 'booth.pm');
        assert.equal(parsed.searchParams.get('sort'), 'new');
        assert.deepEqual(parsed.searchParams.getAll('tags[]'), ['VRChat']);
        assert.equal(parsed.searchParams.get('type'), 'digital');
        assert.ok(parsed.pathname.includes('/browse/'));
    }
    assert.equal(f.registry().has('8888'), false);
});

test('partial quota runs eventually cover every known ID without same-day duplicate detail requests', async t => {
    const f = fixture(t, 30);
    const first = await f.collect({ cap: 20 });
    assert.equal(first.metrics.httpAttempts, 20);
    assert.equal(first.metrics.uniqueUpdated, 18); // Two explicit-empty discovery pages.
    const second = await f.collect({ cap: 40 });
    assert.equal(second.metrics.uniqueUpdated, 12);
    const fetched = f.calls.filter(url => url.includes('/items/')).map(url => url.split('/').at(-1));
    assert.equal(fetched.length, 30);
    assert.equal(new Set(fetched).size, 30);
    assert.deepEqual([...new Set(fetched)].sort(), f.ids);
    assert.equal(JSON.parse(fs.readFileSync(f.budgetFile)).requests, 32);
});

test('both active lanes retain their protected share under a large known-ID backlog', async t => {
    const f = fixture(t, 40);
    const result = await f.collect({ cap: 20, get: async url => ({ status: 200,
        data: url.includes('/items/') ? product(url.split('/').at(-1)) : cards(f.ids.slice(0, 2)) }) });
    assert.equal(result.metrics.httpAttempts, 20);
    assert.deepEqual(result.metrics.requestsByLane, { refresh: 18, discovery: 2 });
    assert.equal(result.metrics.uniqueUpdated, 18);
    assert.equal(result.status, 'paused');
});

test('search markup failure cannot starve known-ID refresh or erase the search cursor', async t => {
    const f = fixture(t, 10);
    const result = await f.collect({ get: async url => ({ status: 200,
        data: url.includes('/items/') ? product(url.split('/').at(-1)) : '<h1>Unexpected page</h1>' }) });
    assert.equal(result.status, 'partial');
    assert.equal(result.metrics.uniqueUpdated, 10);
    const state = JSON.parse(fs.readFileSync(path.join(f.dataDir, 'crawl_state.json')));
    assert.equal(state.page, 1);
    assert.equal(state.urlIndex, 0);
    assert.ok(state.retryAt > START);
});

test('legacy pending page migrates before cursor advance and every pending ID survives restart', async t => {
    const f = fixture(t, 1);
    writeJson(path.join(f.dataDir, 'crawl_state.json'), { urlIndex: 0, page: 7, pendingIds: ['7777', '8888'] });
    const result = await f.collect();
    assert.equal(result.metrics.uniqueUpdated, 3);
    assert.equal(f.registry().has('7777'), true);
    assert.equal(f.registry().has('8888'), true);
    const firstSearch = f.calls.find(url => !url.includes('/items/'));
    assert.match(firstSearch, /page=8$/);
    assert.equal(JSON.parse(fs.readFileSync(path.join(f.dataDir, 'crawl_state.json'))).pendingIds, undefined);
});

test('a malformed product is deferred while the rest of the known catalog is covered', async t => {
    const f = fixture(t, 12);
    const result = await f.collect({ get: async url => ({ status: 200,
        data: url.endsWith(`/items/${f.ids[0]}`) ? '<h2>Price unavailable</h2>' :
            url.includes('/items/') ? product(url.split('/').at(-1)) : EMPTY }) });
    assert.equal(result.metrics.uniqueUpdated, 11);
    assert.equal(result.metrics.itemFailures, 1);
    assert.equal(result.status, 'partial');
    const failed = f.registry().get(f.ids[0]);
    assert.equal(failed.failures, 1);
    assert.ok(failed.nextAttemptAt > START);
    const again = await f.collect();
    assert.equal(again.metrics.uniqueUpdated, 0);
    assert.equal(f.calls.filter(url => url.endsWith(`/items/${f.ids[0]}`)).length, 1);
});

test('refill never runs more than five HTTP requests or fetches a discovered existing ID twice', async t => {
    const f = fixture(t, 20);
    let active = 0;
    let maximum = 0;
    let searches = 0;
    const seen = new Map();
    const result = await f.collect({ get: async url => {
        active++;
        maximum = Math.max(maximum, active);
        if (url.includes('/items/')) seen.set(url, (seen.get(url) || 0) + 1);
        await new Promise(resolve => setImmediate(resolve));
        active--;
        return { status: 200, data: url.includes('/items/') ? product(url.split('/').at(-1)) :
            ++searches === 1 ? cards(f.ids) : EMPTY };
    } });
    assert.ok(maximum <= 5);
    assert.equal(result.metrics.uniqueUpdated, 20);
    assert.equal([...seen.values()].every(count => count === 1), true);
    assert.equal(active, 0);
});

test('systemic product-save failure halts new HTTP work instead of backing off the entire catalog', async t => {
    const f = fixture(t, 12);
    const registry = f.registry(); // Bootstrap before simulating a storage outage.
    let saves = 0;
    const result = await f.collect({ concurrency: 1, registry, save: async () => {
        saves++;
        throw Object.assign(new Error('Storage failed'), { code: 'EIO' });
    } });
    assert.equal(result.status, 'partial');
    assert.equal(saves, 1);
    assert.equal(f.calls.filter(url => url.includes('/items/')).length, 1);
    assert.equal(result.metrics.itemFailures, 0);
    assert.equal(registry.get(f.ids[0]).failures, 0);
});

test('filtered discovery rejects redirects that remove a tag/category/type before following or registering IDs', async t => {
    const f = fixture(t, 8);
    const result = await f.collect({ get: async url => {
        if (url.includes('/items/')) return { status: 200, data: product(url.split('/').at(-1)) };
        if (url.includes('/browse/')) return { status: 302, headers: { location: 'https://booth.pm/ja/search?sort=new' } };
        return { status: 200, data: cards(['9999']) };
    } });
    assert.equal(f.calls.some(url => url.includes('/ja/search?')), false);
    assert.equal(f.registry().has('9999'), false);
    assert.equal(result.metrics.discovered, 0);
    assert.equal(result.metrics.uniqueUpdated, 8);
    assert.equal(result.metrics.searchFailures, 1);
});

test('the item that trips a circuit backs off while untouched IDs remain eligible for the next run', async t => {
    const f = fixture(t, 20);
    const { CollectionStop } = require('../src/collection-runtime');
    const broken = f.ids[0];
    const first = await f.collect({ detail: async id => {
        if (id === broken) {
            const error = new CollectionStop('circuit-breaker', 'Repeated failures', true);
            error.triggeringUrl = `https://booth.pm/ja/items/${id}`;
            return { kind: 'failure', error };
        }
        return { kind: 'success', product: { id, name: `Product ${id}`, variations: [{ name: 'default', price: 100 }], hasSaleKeyword: false } };
    } });
    assert.equal(first.status, 'partial');
    assert.equal(f.registry().get(broken).failures, 1);
    assert.equal(f.registry().isDue(broken), false);
    const second = await f.collect();
    assert.ok(second.metrics.uniqueUpdated > 0);
    for (const id of f.ids.slice(1)) assert.equal(f.registry().get(id).lastSuccess, START);
    assert.equal(f.calls.filter(url => url.endsWith(`/items/${broken}`)).length, 0);
});

test('zero-attempt lane deferrals refill in the same run when an unused share becomes available', async t => {
    const f = fixture(t, 1);
    const registry = f.registry();
    registry.discover(['901', '902', '903']);
    writeJson(path.join(f.dataDir, 'crawl_state.json'), { urlIndex: 0, page: 1, completedDate: jstDate(START) });
    writeJson(f.budgetFile, { date: jstDate(START), requests: 4798, blockedUntil: 0,
        laneUsage: { refresh: 0, discovery: 4798 }, laneReleased: { refresh: false, discovery: false } });
    let resolveKnown;
    const running = f.collect({ get: url => {
        if (url.endsWith(`/items/${f.ids[0]}`)) return new Promise(resolve => { resolveKnown = resolve; });
        return Promise.resolve({ status: 200, data: product(url.split('/').at(-1)) });
    } });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(f.calls.length, 3); // Two discovery starts; the third is quota-deferred.
    assert.equal(typeof resolveKnown, 'function');
    resolveKnown({ status: 200, data: product(f.ids[0]) });
    const result = await running;
    assert.equal(result.status, 'completed');
    assert.equal(result.metrics.uniqueUpdated, 4);
    assert.equal(result.metrics.httpAttempts, 4);
    assert.equal(new Set(f.calls).size, 4);
    assert.equal(f.registry().get('903').lastSuccess, START);
});

test('history and registry use the same captured success date when saving crosses JST midnight', async t => {
    const { saveProductData } = require('../src/scraper');
    const f = fixture(t, 1);
    let time = Date.parse('2026-10-05T14:59:59.999Z');
    writeJson(path.join(f.dataDir, 'crawl_state.json'), { urlIndex: 0, page: 1, completedDate: '2026-10-05' });
    const result = await main({ dataDir: f.dataDir, now: () => time,
        client: { check() {}, get: async url => ({ status: 200, data: product(url.split('/').at(-1)) }) },
        save: async (value, options) => { await saveProductData(value, options); time += 2; },
        log: () => {}, logError: () => {} });
    assert.equal(result.metrics.uniqueUpdated, 1);
    const registry = new CatalogRegistry({ dataDir: f.dataDir, now: () => time }).bootstrap();
    const history = JSON.parse(fs.readFileSync(path.join(f.dataDir, f.ids[0].slice(0, 3), `${f.ids[0]}.json`)));
    assert.equal(history.variations.default.at(-1).date, '2026-10-05');
    assert.equal(jstDate(registry.get(f.ids[0]).lastSuccess), '2026-10-05');
    assert.deepEqual(registry.eligible('refresh'), f.ids);
});

test('a forbidden item moves behind untouched work after the required host cooldown', async t => {
    const f = fixture(t, 12);
    const blockedId = f.ids[0];
    const get = async url => {
        if (url.endsWith(`/items/${blockedId}`)) throw Object.assign(new Error('HTTP 403'), { response: { status: 403, headers: {} } });
        return { status: 200, data: url.includes('/items/') ? product(url.split('/').at(-1)) : EMPTY };
    };
    const first = await f.collect({ get });
    assert.equal(first.status, 'partial');
    assert.equal(f.registry().get(blockedId).failures, 1);
    const later = START + 6 * 3600000 + 1;
    await f.collect({ get, time: later });
    const registry = new CatalogRegistry({ dataDir: f.dataDir, now: () => later }).bootstrap();
    for (const id of f.ids.slice(1)) assert.equal(jstDate(registry.get(id).lastSuccess), jstDate(START));
    assert.equal(registry.get(blockedId).failures, 2);
    assert.ok(JSON.parse(fs.readFileSync(f.budgetFile)).blockedUntil >= later + 6 * 3600000);
});

test('deferred refill waits for actual pool-key release under adversarial microtask ordering', async t => {
    const f = fixture(t, 1);
    f.registry().discover(['901', '902', '903', '904']);
    writeJson(path.join(f.dataDir, 'crawl_state.json'), { urlIndex: 0, page: 1, completedDate: jstDate(START) });
    writeJson(f.budgetFile, { date: jstDate(START), requests: 4798, blockedUntil: 0,
        laneUsage: { refresh: 0, discovery: 4798 }, laneReleased: { refresh: false, discovery: false } });
    const result = await f.collect({ get: async url => {
        const turns = url.endsWith(`/items/${f.ids[0]}`) ? 6 : 8;
        for (let i = 0; i < turns; i++) await Promise.resolve();
        return { status: 200, data: product(url.split('/').at(-1)) };
    } });
    assert.equal(result.status, 'completed');
    assert.equal(result.metrics.uniqueUpdated, 5);
    assert.equal(result.metrics.httpAttempts, 5);
    assert.equal(new Set(f.calls).size, 5);
    assert.equal(result.metrics.errors.some(message => message.includes('Duplicate active')), false);
});
