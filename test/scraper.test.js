const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { CollectionStop, createRequestClient, jstDate, reserveDailyAllowance, writeJson } = require('../src/collection-runtime');
const { normalizeVariationName, scrapeSearchPage, scrapeProductDetails, saveProductData, loadState, main } = require('../src/scraper');

const START = Date.parse('2026-10-04T14:32:00Z');
const HOUR = 3600000;
const emptyHtml = '<html><title>検索 - BOOTH</title><body><a href="/ja/browse/3D">3D</a><p>商品が見つかりませんでした</p></body></html>';
const productHtml = '<h2>Avatar</h2><div class="variation-item"><span class="variation-name">Avatar (30% OFF)</span><b class="variation-price">1,200円</b><button data-product-variant="v1"></button></div>';
const clientFor = data => ({ get: async () => ({ status: 200, data }), check() {} });
const success = id => ({ kind: 'success', product: { id, name: `Product ${id}`, variations: [{ name: 'default', price: 100, isSale: false }], hasSaleKeyword: false } });
const page = ids => ({ kind: 'success', ids });
const empty = () => ({ kind: 'empty' });
const httpError = (status, headers = {}) => Object.assign(new Error(`HTTP ${status}`), { response: { status, headers } });
function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
}
const tick = () => new Promise(resolve => setImmediate(resolve));
function fixture(t) {
    const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'boopa-minimal-scraper-'));
    t.after(() => fs.rmSync(dataDir, { recursive: true, force: true }));
    const stateFile = path.join(dataDir, 'crawl_state.json');
    const budgetFile = path.join(dataDir, 'request_budget.json');
    return {
        dataDir, stateFile, budgetFile,
        readState: () => JSON.parse(fs.readFileSync(stateFile, 'utf8')),
        run: options => main({ dataDir, now: () => START, client: clientFor(''), wait: async () => {}, log: () => {}, logError: () => {}, ...options })
    };
}

test('search distinguishes products, explicit empty, HTTP errors and malformed HTML', async () => {
    assert.deepEqual(await scrapeSearchPage('fixture', clientFor('<div class="item-card" data-product-id="123"></div>')), page(['123']));
    assert.equal((await scrapeSearchPage('fixture', clientFor(emptyHtml))).kind, 'empty');
    assert.equal((await scrapeSearchPage('fixture', { get: async () => { throw httpError(503); } })).kind, 'failure');
    for (const html of ['', '<h1>Challenge</h1>', '<title>BOOTH</title><a href="/browse/x">3D</a><p>Temporary error</p>',
        '<div class="item-card" data-product-id="123"></div><div class="item-card"></div>',
        '<div class="item-card" data-product-id="0"></div>']) {
        assert.equal((await scrapeSearchPage('fixture', clientFor(html))).kind, 'failure');
    }
    assert.equal((await scrapeSearchPage('fixture', { get: async () => ({ status: 503, data: emptyHtml }) })).kind, 'failure');
});

test('product parsing preserves variant identity, sale normalization and explicit free prices', async () => {
    const result = await scrapeProductDetails('123', clientFor(productHtml));
    assert.equal(result.kind, 'success');
    assert.deepEqual(result.product.variations, [{ name: 'Avatar', price: 1200, isSale: true, variantId: 'v1' }]);
    const free = await scrapeProductDetails('123', clientFor(productHtml.replace('1,200円', '無料')));
    assert.equal(free.product.variations[0].price, 0);
    assert.equal(normalizeVariationName('Cotton (コットン100%)'), 'Cotton (コットン100%)');
    assert.equal(normalizeVariationName(' A  B （30% セール） '), 'A B');
    for (const [text, price] of [['1,200円', 1200], ['無料', 0]]) {
        const html = `<h2>Avatar</h2><div class="variation-item"><span class="variation-name">Named</span><div class="variation-price"><span class="price">${text}</span></div></div>`;
        const parsed = await scrapeProductDetails('123', clientFor(html));
        assert.equal(parsed.product.variations[0].price, price);
        assert.equal(parsed.product.variations[0].name, 'Named');
    }
});

test('only explicit 404/410 is unavailable; missing title/price and non-200 HTML fail', async () => {
    for (const html of ['<h2>Temporary error</h2>', '<div class="price">500円</div>']) {
        assert.equal((await scrapeProductDetails('123', clientFor(html))).kind, 'failure');
    }
    for (const status of [404, 410]) assert.equal((await scrapeProductDetails('123', { get: async () => ({ status }) })).kind, 'unavailable');
    assert.equal((await scrapeProductDetails('123', { get: async () => ({ status: 503, data: productHtml }) })).kind, 'failure');
});

test('a delayed start shortly before the next cron still performs actual work', async t => {
    const f = fixture(t);
    const details = [];
    let searches = 0;
    const result = await f.run({ jobStartedAt: START - 10 * 60000,
        search: async () => ++searches === 1 ? page(['123']) : empty(),
        detail: async id => { details.push(id); return success(id); } });
    assert.equal(result.status, 'completed');
    assert.deepEqual(details, ['123']);
    assert.equal(searches, 3);
});

test('search errors preserve the failed page and cannot end a category', async t => {
    for (const outcome of [{ kind: 'failure', error: new Error('HTTP 503') }, page([]), page(['0'])]) {
        const f = fixture(t);
        writeJson(f.stateFile, { urlIndex: 0, page: 27 });
        const urls = [];
        const result = await f.run({ search: async url => { urls.push(url); return outcome; } });
        assert.equal(result.status, 'partial');
        assert.equal(result.failed, true);
        assert.equal(result.reason, 'search-failure');
        assert.equal(f.readState().page, 27);
        assert.equal(f.readState().urlIndex, 0);
        assert.equal(urls.length, 1);
    }
});

test('both original filtered categories and all 3333 pages remain in sequential order', async t => {
    const f = fixture(t);
    writeJson(f.stateFile, { urlIndex: 0, page: 3333 });
    const urls = [];
    const result = await f.run({ search: async url => { urls.push(url); return urls.length === 1 ? page(['123']) : empty(); }, detail: async id => success(id) });
    assert.equal(result.status, 'completed');
    assert.equal(urls.length, 2);
    assert.match(urls[0], /browse\/3D%E3%83%A2%E3%83%87%E3%83%AB\?sort=new&tags%5B%5D=VRChat&type=digital&page=3333$/);
    assert.match(urls[1], /browse\/%E3%82%BD%E3%83%95%E3%83%88%E3%82%A6%E3%82%A7%E3%82%A2\?sort=new&tags%5B%5D=VRChat&type=digital&page=1$/);
    assert.deepEqual(f.readState(), { urlIndex: 0, page: 1, retries: [] });
});

test('legacy page 3334 checkpoints advance categories without requesting page 3334', async t => {
    const f = fixture(t);
    writeJson(f.stateFile, { urlIndex: 0, page: 3334 });
    const urls = [];
    await f.run({ search: async url => { urls.push(url); return empty(); } });
    assert.equal(urls.length, 1);
    assert.match(urls[0], /page=1$/);
});

test('pending IDs are durable before requests; successful history precedes pending removal', async t => {
    const f = fixture(t);
    let searches = 0;
    const saved = [];
    await f.run({ search: async () => ++searches === 1 ? page(['101', '102']) : empty(),
        detail: async id => { assert.ok(f.readState().pendingIds.includes(id)); return success(id); },
        save: async product => { assert.ok(f.readState().pendingIds.includes(product.id)); saved.push(product.id); } });
    assert.deepEqual(saved, ['101', '102']);
    assert.equal(f.readState().pendingIds, undefined);
});

test('one bad item is queued durably while the remaining page and following pages proceed', async t => {
    const f = fixture(t);
    const ids = ['101', '102', '103', '104', '105', '106'];
    const details = [];
    let searches = 0;
    const first = await f.run({ search: async () => {
        searches++;
        if (searches === 1) return page(ids);
        assert.ok(f.readState().retries.some(entry => entry.id === '103'));
        return { kind: 'failure', error: new Error('temporary search failure') };
    }, detail: async id => { details.push(id); return id === '103' ? { kind: 'failure', error: new Error('timeout') } : success(id); } });
    assert.equal(first.status, 'partial');
    assert.deepEqual(details, ids);
    assert.equal(f.readState().page, 2);
    assert.deepEqual(f.readState().retries, [{ id: '103', failures: 1, nextAttemptAt: START + HOUR }]);

    const resumed = [];
    const urls = [];
    const second = await f.run({ now: () => START + HOUR, search: async url => { urls.push(url); return empty(); },
        detail: async id => { resumed.push(id); return success(id); } });
    assert.equal(second.status, 'completed');
    assert.deepEqual(resumed, ['103']);
    assert.match(urls[0], /page=2$/);
    assert.deepEqual(f.readState().retries, []);
});

test('a completed sweep restarts next run even with backed-off failures', async t => {
    const f = fixture(t);
    let pages = 0;
    await f.run({ search: async () => ++pages === 1 ? page(['123']) : empty(), detail: async () => ({ kind: 'failure', error: new Error('bad item') }) });
    assert.equal(f.readState().urlIndex, 0);
    assert.equal(f.readState().page, 1);
    const urls = [];
    const details = [];
    const result = await f.run({ now: () => START + 1, search: async url => { urls.push(url); return urls.length === 1 ? page(['123', '456']) : empty(); },
        detail: async id => { details.push(id); return success(id); } });
    assert.equal(result.status, 'partial');
    assert.match(urls[0], /page=1$/);
    assert.deepEqual(details, ['456']);
    assert.equal(f.readState().retries[0].failures, 1);
});

test('404/410 preserve historical bytes and schedule a later retry without pinning pages', async t => {
    for (const status of [404, 410]) {
        const f = fixture(t);
        writeJson(f.stateFile, { urlIndex: 0, page: 1, pendingIds: ['123'] });
        const file = path.join(f.dataDir, '123', '123.json');
        writeJson(file, { id: '123', variations: { old: [{ date: '2026-01-01', price: 500 }] } });
        const before = fs.readFileSync(file, 'utf8');
        const urls = [];
        await f.run({ search: async url => { urls.push(url); return empty(); }, detail: async () => ({ kind: 'unavailable', status }) });
        assert.equal(fs.readFileSync(file, 'utf8'), before);
        assert.match(urls[0], /page=2$/);
        assert.deepEqual(f.readState().retries, [{ id: '123', failures: 1, nextAttemptAt: START + 24 * HOUR }]);
    }
});

test('deadline and budget stops preserve pending work without inventing item failures', async t => {
    for (const reason of ['deadline', 'request-budget', 'day-boundary']) {
        const f = fixture(t);
        let pages = 0;
        const result = await f.run({ search: async () => ++pages === 1 ? page(['123']) : empty(),
            detail: async () => ({ kind: 'failure', error: new CollectionStop(reason, reason) }) });
        assert.equal(result.status, 'paused');
        assert.deepEqual(f.readState().pendingIds, ['123']);
        assert.deepEqual(f.readState().retries, []);
        assert.equal(f.readState().page, 1);
    }
});

test('resuming pending IDs skips the page search and never repeats already-saved successes', async t => {
    const f = fixture(t);
    writeJson(f.stateFile, { urlIndex: 0, page: 19, pendingIds: ['105', '106'] });
    const ids = [];
    const urls = [];
    await f.run({ detail: async id => { ids.push(id); return success(id); }, search: async url => { urls.push(url); return empty(); } });
    assert.deepEqual(ids, ['105', '106']);
    assert.match(urls[0], /page=20$/);
});

test('an empty durable pending array advances without repeating its finished search page', async t => {
    const f = fixture(t);
    writeJson(f.stateFile, { urlIndex: 0, page: 19, pendingIds: [] });
    const urls = [];
    await f.run({ search: async url => { urls.push(url); return empty(); } });
    assert.match(urls[0], /page=20$/);
});

test('original five-item Promise.all barrier, one-second batch and two-second page waits remain', async t => {
    const f = fixture(t);
    let time = START;
    const work = new Map();
    const started = [];
    const searches = [];
    const waits = [];
    const run = f.run({ now: () => time, wait: async ms => { waits.push(ms); time += ms; },
        search: async url => { searches.push({ url, time }); return searches.length === 1 ? page(['101', '102', '103', '104', '105', '106']) : empty(); },
        detail: id => { started.push({ id, time }); const item = deferred(); work.set(id, item); return item.promise; } });
    await tick();
    assert.deepEqual(started.map(entry => entry.id), ['101', '102', '103', '104', '105']);
    for (const id of ['102', '103', '104', '105']) work.get(id).resolve(success(id));
    await tick();
    assert.equal(started.length, 5, 'a free slot does not refill ahead of the slowest batch member');
    assert.deepEqual(waits, []);
    work.get('101').resolve(success('101'));
    await tick();
    assert.equal(started.at(-1).id, '106');
    assert.equal(started.at(-1).time, START + 1000);
    work.get('106').resolve(success('106'));
    assert.equal((await run).status, 'completed');
    assert.deepEqual(waits, [1000, 1000, 2000]);
    assert.equal(searches[1].time, START + 4000);
});

test('duplicate search IDs are claimed once per run without concurrent writes', async t => {
    const f = fixture(t);
    let searches = 0;
    const details = [];
    const pauses = [];
    const result = await f.run({ wait: async ms => pauses.push(ms),
        search: async () => ++searches <= 2 ? page(['123', '123']) : empty(),
        detail: async id => { details.push(id); return success(id); } });
    assert.equal(result.status, 'completed');
    assert.deepEqual(details, ['123']);
    assert.equal(result.metrics.duplicatesAvoided, 1);
    assert.deepEqual(pauses, [1000, 2000, 1000, 2000]);
});

test('due retry batches alternate with normal pages and retry each failure at most once per run', async t => {
    const f = fixture(t);
    const retries = Array.from({ length: 12 }, (_, i) => ({ id: String(200 + i), failures: 1, nextAttemptAt: START - 1 }));
    writeJson(f.stateFile, { urlIndex: 0, page: 1, retries });
    const events = [];
    let searches = 0;
    const result = await f.run({ search: async () => { events.push('search'); return ++searches <= 2 ? page([String(100 + searches)]) : empty(); },
        detail: async id => { events.push(id); return id === '200' ? { kind: 'failure', error: new Error('still bad') } : success(id); } });
    assert.equal(result.status, 'partial');
    assert.deepEqual(events.slice(0, 7), ['200', '201', '202', '203', '204', 'search', '101']);
    assert.deepEqual(events.slice(7, 14), ['205', '206', '207', '208', '209', 'search', '102']);
    assert.equal(events.filter(id => id === '200').length, 1);
    assert.equal(result.metrics.retries, 12);
    assert.deepEqual(f.readState().retries, [{ id: '200', failures: 2, nextAttemptAt: START + 2 * HOUR }]);
});

test('retry backoff is capped and rediscovery does not bypass it', async t => {
    const f = fixture(t);
    writeJson(f.stateFile, { urlIndex: 0, page: 1, retries: [{ id: '123', failures: 99, nextAttemptAt: START }] });
    let searches = 0;
    let calls = 0;
    await f.run({ search: async () => ++searches === 1 ? page(['123']) : empty(),
        detail: async () => { calls++; return { kind: 'failure', error: new Error('still bad') }; } });
    assert.equal(calls, 1);
    assert.equal(f.readState().retries[0].nextAttemptAt, START + 24 * HOUR);
});

test('429 stops launches but drains active successes and late 403 evidence before finishing quota', async t => {
    const f = fixture(t);
    const pending = new Map();
    const ids = ['101', '102', '103', '104', '105', '106'];
    const calls = [];
    const client = createRequestClient({ budgetFile: f.budgetFile, now: () => START, deadline: START + HOUR, intervalMs: 0,
        get: async url => { calls.push(url); const id = url.split('/').at(-1); const item = deferred(); pending.set(id, item); return item.promise; } });
    let finished = false;
    const finish = client.finish;
    client.finish = () => { assert.equal(pending.size, 0); finished = true; finish(); };
    const run = f.run({ client, search: async () => page(ids) });
    await tick();
    assert.equal(calls.length, 5);
    pending.get('101').reject(httpError(429, { 'retry-after': '60' })); pending.delete('101');
    await tick();
    assert.equal(finished, false);
    assert.equal(calls.length, 5);
    pending.get('102').reject(httpError(403, { 'retry-after': '86400' })); pending.delete('102');
    for (const id of ['103', '104', '105']) { pending.get(id).resolve({ status: 200, data: productHtml }); pending.delete(id); }
    const result = await run;
    assert.equal(result.status, 'partial');
    assert.equal(finished, true);
    assert.deepEqual(f.readState().pendingIds, ['101', '102', '106']);
    assert.deepEqual(f.readState().retries, []);
    assert.equal(client.getBudget().requests, 5);
    assert.ok(client.getBudget().blockedUntil >= START + 86400000);
    for (const id of ['103', '104', '105']) assert.ok(fs.existsSync(path.join(f.dataDir, id, `${id}.json`)));
});

test('reserved daily budget checkpoints partial batches and resumes only unfinished IDs next day', async t => {
    const f = fixture(t);
    let time = START;
    const calls = [];
    const ids = ['101', '102', '103', '104', '105', '106'];
    const get = async url => {
        calls.push(url);
        return { status: 200, data: url.includes('/items/') ? productHtml : calls.length === 1
            ? ids.map(id => `<div class="item-card" data-product-id="${id}"></div>`).join('') : emptyHtml };
    };
    const run = reservationId => main({ dataDir: f.dataDir, now: () => time, reservationId,
        wait: async () => {}, log: () => {}, logError: () => {},
        client: createRequestClient({ get, budgetFile: f.budgetFile, reservationId, now: () => time, deadline: time + HOUR, intervalMs: 0 }) });
    writeJson(f.budgetFile, { date: jstDate(time), requests: 47995, blockedUntil: 0 });
    assert.equal(reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'first', now: time }).limit, 5);
    const firstResult = await run('first');
    assert.equal(firstResult.status, 'paused');
    assert.equal(firstResult.metrics.chargedHttpAttempts, 5);
    assert.equal(firstResult.metrics.dailyChargedRequests, 48000);
    assert.deepEqual(f.readState().pendingIds, ['105', '106']);
    assert.equal(f.readState().page, 1);
    const first = JSON.parse(fs.readFileSync(f.budgetFile));
    assert.equal(first.requests, 48000);
    assert.deepEqual(first.reservation, { id: 'first', limit: 5, used: 5, completed: true });
    assert.equal(calls.length, 5);
    time += 24 * HOUR;
    assert.equal(reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'second', now: time }).limit, 48000);
    const secondResult = await run('second');
    assert.equal(secondResult.status, 'completed');
    assert.equal(secondResult.metrics.chargedHttpAttempts, 4);
    assert.equal(secondResult.metrics.dailyChargedRequests, 4);
    assert.deepEqual(calls.slice(5).filter(url => url.includes('/items/')).map(url => url.split('/').at(-1)), ['105', '106']);
    const second = JSON.parse(fs.readFileSync(f.budgetFile));
    assert.equal(second.requests, 4);
    assert.deepEqual(second.reservation, { id: 'second', limit: 48000, used: 4, completed: true });
    assert.match(calls[7], /page=2$/);
});

test('malformed checkpoints fail closed and leave their original bytes unchanged', async t => {
    const f = fixture(t);
    const invalid = [{ urlIndex: 5, page: 1 }, { urlIndex: 0, page: 0 }, { urlIndex: 0, page: 1, pendingIds: ['../secret'] },
        { urlIndex: 0, page: 1, pendingIds: ['0'] }, { urlIndex: 0, page: 1, pendingIds: ['123', '123'] },
        { urlIndex: 0, page: 1, retries: [{ id: '../secret', failures: 1, nextAttemptAt: 0 }] },
        { urlIndex: 0, page: 1, retries: [{ id: '0', failures: 1, nextAttemptAt: 0 }] },
        { urlIndex: 0, page: 1, retries: [{ id: '123', failures: 0, nextAttemptAt: 0 }] },
        { urlIndex: 0, page: 1, retries: [{ id: '123', failures: 1, nextAttemptAt: -1 }] },
        { urlIndex: 2, page: 1, pendingIds: ['123'] }, { urlIndex: 0, page: 3334, pendingIds: [] }];
    for (const value of invalid) {
        writeJson(f.stateFile, value);
        const before = fs.readFileSync(f.stateFile, 'utf8');
        assert.throws(() => loadState(f.stateFile), /Invalid crawl/);
        await assert.rejects(f.run({ search: () => assert.fail('must not request') }), /Invalid crawl/);
        assert.equal(fs.readFileSync(f.stateFile, 'utf8'), before);
    }
    fs.writeFileSync(f.stateFile, '{truncated');
    await assert.rejects(f.run({ search: () => assert.fail('must not request') }), SyntaxError);
    assert.equal(fs.readFileSync(f.stateFile, 'utf8'), '{truncated');
});

test('isolated corrupt history preserves bytes and queues a retry without pinning the page', async t => {
    const f = fixture(t);
    writeJson(f.stateFile, { urlIndex: 0, page: 1, pendingIds: ['123'] });
    const file = path.join(f.dataDir, '123', '123.json');
    fs.mkdirSync(path.dirname(file));
    fs.writeFileSync(file, '{truncated');
    const urls = [];
    const result = await f.run({ search: async url => { urls.push(url); return empty(); }, detail: async id => success(id) });
    assert.equal(result.status, 'partial');
    assert.equal(fs.readFileSync(file, 'utf8'), '{truncated');
    assert.equal(f.readState().pendingIds, undefined);
    assert.deepEqual(f.readState().retries, [{ id: '123', failures: 1, nextAttemptAt: START + HOUR }]);
    assert.match(urls[0], /page=2$/);
});

test('malformed nested history entries are isolated failures, retain bytes, and do not pin the crawl', async t => {
    for (const entry of [null, 'invalid', { date: 123, price: 100 }, { date: '2026-10-03', price: 'invalid' }]) {
        const f = fixture(t);
        writeJson(f.stateFile, { urlIndex: 0, page: 1, pendingIds: ['123', '456'] });
        const file = path.join(f.dataDir, '123', '123.json');
        writeJson(file, { id: '123', variations: { default: [entry] } });
        const before = fs.readFileSync(file, 'utf8');
        const urls = [];
        const result = await f.run({ search: async url => { urls.push(url); return empty(); }, detail: async id => success(id) });
        assert.equal(result.status, 'partial');
        assert.equal(result.metrics.itemSuccess, 1);
        assert.equal(fs.readFileSync(file, 'utf8'), before);
        assert.deepEqual(f.readState().retries, [{ id: '123', failures: 1, nextAttemptAt: START + HOUR }]);
        assert.match(urls[0], /page=2$/);
    }
});

test('item redirect and HTTP identity failures are retryable without globally pinning the page', async t => {
    for (const reason of ['redirect', 'http']) {
        const f = fixture(t);
        writeJson(f.stateFile, { urlIndex: 0, page: 1, pendingIds: ['123', '456'] });
        const urls = [];
        const result = await f.run({ search: async url => { urls.push(url); return empty(); },
            detail: async id => id === '123' ? { kind: 'failure', error: new CollectionStop(reason, reason, true) } : success(id) });
        assert.equal(result.status, 'partial');
        assert.equal(result.metrics.itemSuccess, 1);
        assert.deepEqual(f.readState().retries, [{ id: '123', failures: 1, nextAttemptAt: START + HOUR }]);
        assert.match(urls[0], /page=2$/);
    }
});

test('systemic history writes stop new batches, drain started saves, and retain failures pending', async t => {
    const f = fixture(t);
    writeJson(f.stateFile, { urlIndex: 0, page: 1, pendingIds: ['101', '102', '103', '104', '105', '106'] });
    const delayed = deferred();
    const started = [];
    let finished = false;
    const client = { check() {}, stop() {}, finish() { finished = true; } };
    const run = f.run({ client, detail: async id => { started.push(id); return success(id); },
        save: async product => { if (product.id === '101') throw Object.assign(new Error('disk full'), { code: 'ENOSPC' }); if (product.id === '102') await delayed.promise; } });
    await tick();
    assert.equal(finished, false);
    assert.deepEqual(started, ['101', '102', '103', '104', '105']);
    delayed.resolve();
    assert.equal((await run).status, 'failed');
    assert.deepEqual(f.readState().pendingIds, ['101', '106']);
    assert.equal(finished, true);
});

test('failed final checkpoint keeps a durable reservation unresolved instead of refunding quota', async t => {
    const f = fixture(t);
    writeJson(f.stateFile, { urlIndex: 0, page: 1, pendingIds: ['123'] });
    writeJson(f.budgetFile, { date: jstDate(START), requests: 0, blockedUntil: 0 });
    reserveDailyAllowance({ budgetFile: f.budgetFile, reservationId: 'held', now: START });
    const original = fs.renameSync;
    let failCheckpoint = false;
    t.mock.method(fs, 'renameSync', function (from, to) {
        if (failCheckpoint && String(to) === f.stateFile) throw Object.assign(new Error('disk full'), { code: 'ENOSPC' });
        return original.call(this, from, to);
    });
    const client = createRequestClient({ get: async () => ({ status: 200, data: productHtml }), budgetFile: f.budgetFile,
        reservationId: 'held', now: () => START, deadline: START + HOUR, intervalMs: 0 });
    const result = await f.run({ client, save: async () => { failCheckpoint = true; } });
    assert.equal(result.status, 'failed');
    assert.deepEqual(f.readState().pendingIds, ['123']);
    const budget = JSON.parse(fs.readFileSync(f.budgetFile));
    assert.equal(budget.reservation.completed, false);
    assert.equal(budget.requests, 48000);
    assert.equal(budget.reservation.used, 1);
});

test('same-day history updates are idempotent and retain stable variation keys and earlier prices', async t => {
    const f = fixture(t);
    const file = path.join(f.dataDir, '123', '123.json');
    writeJson(file, { id: '123', name: 'Existing', variation_keys: { v1: 'old name' }, variations: { 'old name': [{ date: '2026-10-03', price: 1500 }] } });
    const product = (await scrapeProductDetails('123', clientFor(productHtml))).product;
    await saveProductData(product, { dataDir: f.dataDir, today: '2026-10-04' });
    await saveProductData(product, { dataDir: f.dataDir, today: '2026-10-04' });
    const saved = JSON.parse(fs.readFileSync(file));
    assert.deepEqual(Object.keys(saved.variations), ['old name']);
    assert.deepEqual(saved.variations['old name'], [{ date: '2026-10-03', price: 1500 }, { date: '2026-10-04', price: 1200, is_sale: true }]);
    assert.equal(saved.name, 'Existing');
});

test('incompatible existing history shapes are never overwritten', async t => {
    const f = fixture(t);
    const file = path.join(f.dataDir, '123', '123.json');
    for (const history of [null, [], { variations: [] }, { variations: { default: {} } }, { variations: {}, variation_keys: [] }]) {
        writeJson(file, history);
        const before = fs.readFileSync(file, 'utf8');
        await assert.rejects(saveProductData(success('123').product, { dataDir: f.dataDir, today: '2026-10-04' }), /Cannot read existing history/);
        assert.equal(fs.readFileSync(file, 'utf8'), before);
    }
});

test('history-read failures retain storage error codes and causes', async t => {
    const f = fixture(t);
    const file = path.join(f.dataDir, '123', '123.json');
    writeJson(file, { id: '123', variations: {} });
    const original = fs.readFileSync;
    const failure = Object.assign(new Error('disk read failed'), { code: 'EIO' });
    t.mock.method(fs, 'readFileSync', function (target, ...args) {
        if (String(target) === file) throw failure;
        return original.call(this, target, ...args);
    });
    await assert.rejects(saveProductData(success('123').product, { dataDir: f.dataDir }), error => error.code === 'EIO' && error.cause === failure);
});

test('CLI refuses unreserved collection before network activity', () => {
    const env = { ...process.env };
    delete env.SCRAPER_RESERVATION_ID;
    const result = spawnSync(process.execPath, ['src/scraper.js'], { cwd: path.join(__dirname, '..'), env, encoding: 'utf8' });
    assert.equal(result.status, 1);
    assert.match(result.stderr, /committed request reservation/);
});

test('dangling inherited-name variation mapping is isolated and cannot pin later products', async t => {
    const f = fixture(t);
    writeJson(f.stateFile, { urlIndex: 0, page: 1, pendingIds: ['123', '124'] });
    const file = path.join(f.dataDir, '123', '123.json');
    writeJson(file, { id: '123', variations: {}, variation_keys: { v1: 'constructor' } });
    const before = fs.readFileSync(file);
    const result = await f.run({ search: async () => empty(), detail: async id => ({ kind: 'success', product: {
        ...success(id).product, variations: [{ name: 'Safe', variantId: 'v1', price: 100, isSale: false }]
    } }) });
    assert.equal(result.status, 'partial');
    assert.deepEqual(fs.readFileSync(file), before);
    assert.ok(fs.existsSync(path.join(f.dataDir, '124', '124.json')));
    assert.deepEqual(f.readState().retries.map(entry => entry.id), ['123']);
    assert.equal(f.readState().page, 1);
    assert.equal(f.readState().urlIndex, 0);
});

test('prototype-like variation names and IDs are ordinary keys and replay idempotently', async t => {
    const f = fixture(t);
    const product = { id: '123', name: 'Special names', hasSaleKeyword: false, variations: [
        { name: '__proto__', variantId: '__proto__', price: 100, isSale: false },
        { name: 'constructor', variantId: 'constructor', price: 200, isSale: false },
        { name: 'toString', variantId: 'toString', price: 300, isSale: false }
    ] };
    await saveProductData(product, { dataDir: f.dataDir, today: '2026-10-04' });
    const file = path.join(f.dataDir, '123', '123.json');
    const bytes = fs.readFileSync(file);
    const saved = JSON.parse(bytes);
    for (const variation of product.variations) {
        assert.equal(Object.hasOwn(saved.variations, variation.name), true);
        assert.equal(Object.hasOwn(saved.variation_keys, variation.variantId), true);
        assert.equal(saved.variation_keys[variation.variantId], variation.name);
        assert.deepEqual(saved.variations[variation.name], [{ date: '2026-10-04', price: variation.price, is_sale: false }]);
    }
    await saveProductData(product, { dataDir: f.dataDir, today: '2026-10-04' });
    assert.deepEqual(fs.readFileSync(file), bytes);
    assert.equal(Object.hasOwn(Object.prototype, 'price'), false);
});
