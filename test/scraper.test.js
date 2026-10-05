const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { CatalogRegistry } = require('../src/catalog-registry');
const { CollectionStop, writeJson } = require('../src/collection-runtime');
const {
    normalizeVariationName, scrapeSearchPage, scrapeProductDetails, saveProductData, loadState, main
} = require('../src/scraper');

const START = Date.parse('2026-10-04T14:32:00Z');
const emptyHtml = '<html><title>検索 - BOOTH</title><body><a href="/ja/browse/3D">3D</a><p>商品が見つかりませんでした</p></body></html>';
const productHtml = '<h2>Avatar</h2><div class="variation-item"><span class="variation-name">Avatar (30% OFF)</span><b class="variation-price">1,200円</b><button data-product-variant="v1"></button></div>';
const clientFor = data => ({ get: async () => ({ status: 200, data }), check() {} });
const success = id => ({ kind: 'success', product: { id, name: `Product ${id}`, variations: [{ name: 'default', price: 100, isSale: false }], hasSaleKeyword: false } });
function fixture(t) {
    const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'boopa-scraper-'));
    t.after(() => fs.rmSync(dataDir, { recursive: true, force: true }));
    const stateFile = path.join(dataDir, 'crawl_state.json');
    return {
        dataDir, stateFile, readState: () => JSON.parse(fs.readFileSync(stateFile)),
        run: options => main({ dataDir, now: () => START, client: clientFor(''), wait: async () => {}, log: () => {}, logError: () => {}, ...options })
    };
}

test('search distinguishes success, explicit empty, HTTP failure and malformed/error HTML', async () => {
    assert.deepEqual(await scrapeSearchPage('fixture', clientFor('<div class="item-card" data-product-id="123"></div>')), { kind: 'success', ids: ['123'] });
    assert.equal((await scrapeSearchPage('fixture', clientFor(emptyHtml))).kind, 'empty');
    const rejected = { get: async () => { throw new Error('HTTP 503'); } };
    assert.equal((await scrapeSearchPage('fixture', rejected)).kind, 'failure');
    for (const html of ['', '<h1>Challenge</h1>', '<title>BOOTH</title><a href="/browse/x">3D</a><p>Temporary error</p>',
        '<div class="item-card" data-product-id="123"></div><div class="item-card"></div>']) {
        assert.equal((await scrapeSearchPage('fixture', clientFor(html))).kind, 'failure');
    }
});

test('product parsing retains variant identity, sale normalization and explicit free prices', async () => {
    const result = await scrapeProductDetails('123', clientFor(productHtml));
    assert.equal(result.kind, 'success');
    assert.deepEqual(result.product.variations, [{ name: 'Avatar', price: 1200, isSale: true, variantId: 'v1' }]);
    const free = await scrapeProductDetails('123', clientFor(productHtml.replace('1,200円', '無料')));
    assert.equal(free.product.variations[0].price, 0);
    assert.equal(normalizeVariationName('Cotton (コットン100%)'), 'Cotton (コットン100%)');
    assert.equal(normalizeVariationName(' A  B （30% セール） '), 'A B');
});

test('missing product price/title is a failure; only explicit 404/410 is unavailable', async () => {
    for (const html of ['<h2>Temporary error</h2>', '<div class="price">500円</div>']) {
        assert.equal((await scrapeProductDetails('123', clientFor(html))).kind, 'failure');
    }
    for (const status of [404, 410]) {
        assert.equal((await scrapeProductDetails('123', { get: async () => ({ status }) })).kind, 'unavailable');
    }
});

test('search failure preserves its cursor/backoff while known-ID refresh continues', async t => {
    const f = fixture(t);
    writeJson(f.stateFile, { urlIndex: 0, page: 27 });
    writeJson(path.join(f.dataDir, '123', '123.json'), { id: '123', variations: { default: [{ date: '2026-01-01', price: 100 }] } });
    const urls = [];
    const refreshed = [];
    const result = await f.run({
        search: async url => { urls.push(url); return { kind: 'failure', error: new Error('503') }; },
        detail: async id => { refreshed.push(id); return success(id); }
    });
    assert.equal(result.status, 'partial');
    assert.equal(result.failed, true);
    assert.equal(f.readState().page, 27);
    assert.equal(f.readState().urlIndex, 0);
    assert.ok(f.readState().retryAt > START);
    assert.deepEqual(refreshed, ['123']);
    assert.equal(urls.length, 1);
});

test('one failed item backs off without blocking the tail, and later resumes without successful same-day IDs', async t => {
    const f = fixture(t);
    const ids = ['101', '102', '103', '104', '105', '106'];
    const morning = Date.parse('2026-10-04T01:00:00Z');
    const attempted = [];
    let pages = 0;
    const first = await f.run({
        now: () => morning,
        search: async () => ++pages === 1 ? { kind: 'success', ids } : { kind: 'empty' },
        detail: async id => { attempted.push(id); return id === '103' ? { kind: 'failure', error: new Error('timeout') } : success(id); }
    });
    assert.equal(first.status, 'partial');
    assert.deepEqual(attempted.sort(), ids);
    const registry = new CatalogRegistry({ dataDir: f.dataDir, now: () => morning }).bootstrap();
    assert.equal(registry.get('103').failures, 1);
    assert.equal(registry.get('103').lastSuccess, null);
    assert.equal(registry.isDue('103', morning), false);
    const resumed = [];
    const second = await f.run({
        now: () => morning + 3600000,
        search: async () => { throw new Error('Completed discovery must not be repeated today'); },
        detail: async id => { resumed.push(id); return success(id); }
    });
    assert.equal(second.status, 'completed');
    assert.deepEqual(resumed, ['103']);
    assert.equal(f.readState().completedDate, '2026-10-04');
});

test('403/429 halt globally while registered IDs remain resumable', async t => {
    for (const reason of ['forbidden', 'rate-limit']) {
        const f = fixture(t);
        let pages = 0;
        const result = await f.run({
            search: async () => ++pages === 1 ? { kind: 'success', ids: ['123'] } : { kind: 'empty' },
            detail: async () => ({ kind: 'failure', error: new CollectionStop(reason, reason, true) })
        });
        assert.equal(result.status, 'partial');
        assert.equal(result.failed, true);
        const registry = new CatalogRegistry({ dataDir: f.dataDir, now: () => START }).bootstrap();
        assert.equal(registry.isDue('123'), true);
        assert.equal(registry.get('123').failures, 0);
    }
});

test('budget/deadline pauses preserve registered pending work without treating it as a product failure', async t => {
    for (const reason of ['deadline', 'request-budget']) {
        const f = fixture(t);
        let pages = 0;
        const result = await f.run({
            search: async () => ++pages === 1 ? { kind: 'success', ids: ['123'] } : { kind: 'empty' },
            detail: async () => ({ kind: 'failure', error: new CollectionStop(reason, reason) })
        });
        assert.equal(result.status, 'paused');
        const registry = new CatalogRegistry({ dataDir: f.dataDir, now: () => START }).bootstrap();
        assert.equal(registry.isDue('123'), true);
        assert.equal(registry.get('123').failures, 0);
    }
});

test('both complete categories and the BOOTH maximum page limit are retained', async t => {
    const f = fixture(t);
    writeJson(f.stateFile, { urlIndex: 0, page: 3333 });
    const urls = [];
    const result = await f.run({ search: async url => { urls.push(url); return urls.length === 1 ? { kind: 'success', ids: ['123'] } : { kind: 'empty' }; }, detail: async id => success(id) });
    assert.equal(result.status, 'completed');
    assert.match(urls[0], /page=3333$/);
    assert.match(urls[1], /page=1$/);
    assert.notEqual(urls[0].split('?')[0], urls[1].split('?')[0]);
    assert.equal(urls.length, 2);
});

test('old MAX_PAGES+1 checkpoint moves to second category without requesting page 3334', async t => {
    const f = fixture(t);
    writeJson(f.stateFile, { urlIndex: 0, page: 3334 });
    const urls = [];
    await f.run({ search: async url => { urls.push(url); return { kind: 'empty' }; } });
    assert.equal(urls.length, 1);
    assert.match(urls[0], /page=1$/);
});

test('unavailable product does not overwrite historical data or pin the cursor', async t => {
    const f = fixture(t);
    writeJson(f.stateFile, { urlIndex: 0, page: 1, pendingIds: ['123'] });
    const productFile = path.join(f.dataDir, '123', '123.json');
    writeJson(productFile, { id: '123', variations: { old: [{ date: '2026-01-01', price: 500 }] } });
    const before = fs.readFileSync(productFile, 'utf8');
    await f.run({ search: async () => ({ kind: 'empty' }), detail: async () => ({ kind: 'unavailable', status: 404 }) });
    assert.equal(fs.readFileSync(productFile, 'utf8'), before);
    assert.equal(f.readState().completedDate, '2026-10-04');
    const record = new CatalogRegistry({ dataDir: f.dataDir, now: () => START }).bootstrap().get('123');
    assert.equal(record.unavailable, true);
    assert.ok(record.nextAttemptAt > START);
});

test('same-day retry is idempotent and variant history remains under its stable key', async t => {
    const f = fixture(t);
    const productFile = path.join(f.dataDir, '123', '123.json');
    writeJson(productFile, { id: '123', name: 'Existing', variation_keys: { v1: 'old name' }, variations: { 'old name': [{ date: '2026-10-03', price: 1500 }] } });
    const product = (await scrapeProductDetails('123', clientFor(productHtml))).product;
    await saveProductData(product, { dataDir: f.dataDir, today: '2026-10-04' });
    await saveProductData(product, { dataDir: f.dataDir, today: '2026-10-04' });
    const saved = JSON.parse(fs.readFileSync(productFile));
    assert.deepEqual(Object.keys(saved.variations), ['old name']);
    assert.equal(saved.variations['old name'].length, 2);
    assert.equal(saved.name, 'Existing');
});

test('unreadable existing product history is preserved and remains pending', async t => {
    const f = fixture(t);
    const productFile = path.join(f.dataDir, '123', '123.json');
    fs.mkdirSync(path.dirname(productFile));
    fs.writeFileSync(productFile, '{truncated');
    const result = await f.run({ search: async () => ({ kind: 'empty' }), detail: async id => success(id) });
    assert.equal(result.status, 'partial');
    assert.equal(fs.readFileSync(productFile, 'utf8'), '{truncated');
    assert.equal(new CatalogRegistry({ dataDir: f.dataDir, now: () => START }).bootstrap().get('123').failures, 1);
});

test('malformed existing checkpoints fail closed and are not overwritten', t => {
    const f = fixture(t);
    for (const value of [{ urlIndex: 5, page: 1 }, { urlIndex: 0, page: 0 }, { urlIndex: 0, page: 1, pendingIds: ['../secret'] }]) {
        writeJson(f.stateFile, value);
        assert.throws(() => loadState(f.stateFile), /Invalid crawl/);
        assert.deepEqual(f.readState(), value);
    }
});

test('CLI refuses unreserved collection before any network activity', () => {
    const env = { ...process.env };
    delete env.SCRAPER_RESERVATION_ID;
    const result = spawnSync(process.execPath, ['src/scraper.js'], { cwd: path.join(__dirname, '..'), env, encoding: 'utf8' });
    assert.equal(result.status, 1);
    assert.match(result.stderr, /committed request reservation/);
});

test('incompatible history container shapes fail without overwriting existing bytes', async t => {
    const f = fixture(t);
    const productFile = path.join(f.dataDir, '123', '123.json');
    for (const history of [null, [], { variations: [] }, { variations: { default: {} } }, { variations: {}, variation_keys: [] }]) {
        writeJson(productFile, history);
        const before = fs.readFileSync(productFile, 'utf8');
        await assert.rejects(saveProductData(success('123').product, { dataDir: f.dataDir, today: '2026-10-04' }), /Cannot read existing history/);
        assert.equal(fs.readFileSync(productFile, 'utf8'), before);
    }
});

test('nested price selectors are read once and preserve named free variants', async () => {
    for (const [text, price] of [['1,200円', 1200], ['無料', 0]]) {
        const html = `<h2>Avatar</h2><div class="variation-item"><span class="variation-name">Named</span><div class="variation-price"><span class="price">${text}</span></div></div>`;
        const result = await scrapeProductDetails('123', clientFor(html));
        assert.equal(result.kind, 'success');
        assert.equal(result.product.variations[0].price, price);
        assert.equal(result.product.variations[0].name, 'Named');
    }
});

test('reserved client and main persist partial batches and resume with exact next-day accounting', async t => {
    const { createRequestClient, jstDate, reserveDailyAllowance } = require('../src/collection-runtime');
    const f = fixture(t);
    const budgetFile = path.join(f.dataDir, 'request_budget.json');
    let time = START;
    const calls = [];
    const ids = ['101', '102', '103', '104', '105', '106'];
    const get = async url => {
        calls.push(url);
        if (url.includes('/items/')) return { status: 200, data: productHtml };
        return {
            status: 200,
            data: calls.length === 1
                ? ids.map(id => `<div class="item-card" data-product-id="${id}"></div>`).join('')
                : emptyHtml
        };
    };
    const run = reservationId => main({
        dataDir: f.dataDir,
        now: () => time,
        reservationId,
        client: createRequestClient({
            get, budgetFile, reservationId, now: () => time,
            deadline: time + 3600000, intervalMs: 0
        })
    });

    writeJson(budgetFile, { date: jstDate(time), requests: 47995, blockedUntil: 0 });
    assert.equal(reserveDailyAllowance({ budgetFile, reservationId: 'first', now: time }).limit, 5);
    assert.equal((await run('first')).status, 'paused');
    const firstBudget = JSON.parse(fs.readFileSync(budgetFile));
    assert.equal(firstBudget.requests, 48000);
    assert.deepEqual(firstBudget.reservation, { id: 'first', limit: 5, used: 5, completed: true });
    assert.equal(f.readState().page, 2);
    const pendingRegistry = new CatalogRegistry({ dataDir: f.dataDir, now: () => time }).bootstrap();
    assert.deepEqual(pendingRegistry.eligible('discovery'), ['105', '106']);
    assert.equal(calls.length, 5); // One search plus four product requests.
    for (const id of ids.slice(0, 4)) {
        assert.ok(fs.existsSync(path.join(f.dataDir, id, `${id}.json`)));
    }
    for (const id of ids.slice(4)) {
        assert.equal(fs.existsSync(path.join(f.dataDir, id, `${id}.json`)), false);
    }

    time += 24 * 3600000;
    assert.equal(reserveDailyAllowance({ budgetFile, reservationId: 'next-day', now: time }).limit, 48000);
    assert.equal((await run('next-day')).status, 'completed');
    const secondBudget = JSON.parse(fs.readFileSync(budgetFile));
    assert.equal(secondBudget.date, jstDate(time));
    assert.equal(secondBudget.requests, 8);
    assert.deepEqual(secondBudget.reservation, { id: 'next-day', limit: 48000, used: 8, completed: true });
    assert.equal(calls.length, 13);
    const resumedCalls = calls.slice(5);
    const resumedIds = resumedCalls.filter(url => url.includes('/items/')).map(url => url.split('/').at(-1)).sort();
    assert.deepEqual(resumedIds, ids);
    const resumedSearches = resumedCalls.filter(url => !url.includes('/items/'));
    assert.match(resumedSearches[0], /page=2$/);
    assert.match(resumedSearches[1], /page=1$/);
    assert.equal(f.readState().completedDate, '2026-10-05');
    for (const id of ids.slice(4)) {
        const saved = JSON.parse(fs.readFileSync(path.join(f.dataDir, id, `${id}.json`)));
        assert.equal(saved.variations.Avatar[0].date, jstDate(time));
    }
});

test('duplicate filtered results never produce repeated detail tasks', async t => {
    const f = fixture(t);
    const pauses = [];
    const details = [];
    let searches = 0;
    const result = await f.run({
        wait: async ms => pauses.push(ms),
        search: async () => ++searches <= 2 ? { kind: 'success', ids: ['123'] } : { kind: 'empty' },
        detail: async id => { details.push(id); return success(id); }
    });
    assert.equal(result.status, 'completed');
    assert.deepEqual(details, ['123']);
    assert.deepEqual(pauses, []); // Refill is paced by the shared HTTP client, not batch sleeps.
    assert.equal(result.metrics.duplicatesAvoided, 1);
});

test('history-read wrappers preserve fatal storage error codes and cause', async t => {
    const f = fixture(t);
    const file = path.join(f.dataDir, '123', '123.json');
    writeJson(file, { id: '123', variations: {} });
    const original = fs.readFileSync;
    const failure = Object.assign(new Error('disk read failed'), { code: 'EIO' });
    t.mock.method(fs, 'readFileSync', function (target, ...args) {
        if (String(target) === file) throw failure;
        return original.call(this, target, ...args);
    });
    await assert.rejects(saveProductData(success('123').product, { dataDir: f.dataDir }), error => {
        assert.equal(error.code, 'EIO');
        assert.equal(error.cause, failure);
        return true;
    });
});
