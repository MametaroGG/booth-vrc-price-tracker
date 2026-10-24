const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
    parseItemJson, buildRecord, resizedImage, fetchItemMeta, readActivity, buildWorkList, main
} = require('../src/meta-scraper');
const { jstDate } = require('../src/collection-runtime');
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'booth-item-7918308.json'), 'utf8'));

test('parseItemJson extracts tags, category, and the wish-list count', () => {
    const parsed = parseItemJson('7918308', fixture);
    assert.equal(parsed.id, '7918308');
    assert.equal(parsed.name, fixture.name);
    assert.equal(parsed.shop.subdomain, 'aziel');
    assert.equal(parsed.likes, 39);
    assert.equal(parsed.category.name, '3D小道具');
    assert.equal(parsed.category.parent, '3Dモデル');
    assert.ok(parsed.tags.includes('VRChat'));
    assert.equal(parsed.tags.length, fixture.tags.length);
    assert.ok(parsed.image.startsWith('https://booth.pximg.net/'));
    assert.ok(parsed.image_resized.includes('/c/620x620/'));
    assert.equal(parsed.published_at, fixture.published_at);
});

test('parseItemJson rejects foreign or shapeless payloads', () => {
    assert.throws(() => parseItemJson('7918308', { ...fixture, id: 123 }), /id mismatch/);
    assert.throws(() => parseItemJson('7918308', null), /Unrecognized/);
    assert.throws(() => parseItemJson('7918308', { id: 7918308, name: '' }), /missing a name/);
});

test('resizedImage only rewrites the canonical pximg shape', () => {
    assert.equal(
        resizedImage('https://booth.pximg.net/af9b37be-077b-48b1-b7b2-29b45407241e/i/7918308/x_base_resized.jpg'),
        'https://booth.pximg.net/c/620x620/af9b37be-077b-48b1-b7b2-29b45407241e/i/7918308/x_base_resized.jpg');
    assert.equal(resizedImage('https://example.com/a.jpg'), 'https://example.com/a.jpg');
    assert.equal(resizedImage(''), '');
});

test('buildRecord appends and replaces likes snapshots by date', () => {
    const parsed = parseItemJson('7918308', fixture);
    const first = buildRecord(parsed, { today: '2026-10-23' });
    assert.deepEqual(first.likes_history, [{ date: '2026-10-23', count: 39 }]);
    const sameDay = buildRecord({ ...parsed, likes: 41 }, { today: '2026-10-23', previous: first });
    assert.deepEqual(sameDay.likes_history, [{ date: '2026-10-23', count: 41 }]);
    const nextDay = buildRecord({ ...parsed, likes: 45 }, { today: '2026-10-24', previous: sameDay });
    assert.deepEqual(nextDay.likes_history, [
        { date: '2026-10-23', count: 41 }, { date: '2026-10-24', count: 45 }]);
    const unknown = buildRecord({ ...parsed, likes: null }, { today: '2026-10-25', previous: nextDay });
    assert.equal(unknown.likes_history.length, 2);
});

test('fetchItemMeta maps statuses and parses string payloads', async () => {
    const ok = await fetchItemMeta('7918308', {
        get: async () => ({ status: 200, data: JSON.stringify(fixture) })
    });
    assert.equal(ok.kind, 'success');
    assert.equal(ok.meta.likes, 39);
    const gone = await fetchItemMeta('7918308', { get: async () => ({ status: 404, data: '' }) });
    assert.deepEqual(gone, { kind: 'unavailable', id: '7918308', status: 404 });
    const rejected = await fetchItemMeta('7918308', {
        get: async () => { const e = new Error('nope'); e.response = { status: 410 }; throw e; }
    });
    assert.equal(rejected.kind, 'unavailable');
    const failed = await fetchItemMeta('7918308', { get: async () => { throw new Error('boom'); } });
    assert.equal(failed.kind, 'failure');
});

function tempTree(t) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'boopa-meta-'));
    t.after(() => fs.rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }));
    const dataDir = path.join(root, 'data');
    const metaDir = path.join(root, 'meta');
    const product = id => {
        const dir = path.join(dataDir, id.substring(0, 3));
        fs.mkdirSync(dir, { recursive: true });
        fs.writeFileSync(path.join(dir, `${id}.json`), '{"id":' + id + '}');
    };
    const meta = (id, record) => {
        const dir = path.join(metaDir, id.substring(0, 3));
        fs.mkdirSync(dir, { recursive: true });
        fs.writeFileSync(path.join(dir, `${id}.json`), JSON.stringify(record));
    };
    return { dataDir, metaDir, product, meta };
}

test('buildWorkList prioritizes missing (newest first), then stalest refreshes', t => {
    const { dataDir, metaDir, product, meta } = tempTree(t);
    for (const id of ['1000001', '1000009', '1000005', '1000003', '1000007']) product(id);
    meta('1000005', { id: '1000005', fetched_at: '2026-10-22' }); // fresh: skipped
    meta('1000003', { id: '1000003', fetched_at: '2026-09-01' }); // stale refresh
    meta('1000007', { id: '1000007', unavailable: true, fetched_at: '2026-10-01' }); // too soon to retry
    const work = buildWorkList({ dataDir, metaDir, today: '2026-10-23', runCap: 10 });
    assert.deepEqual(work.map(w => w.id), ['1000009', '1000001', '1000003']);
    const capped = buildWorkList({ dataDir, metaDir, today: '2026-10-23', runCap: 2 });
    assert.deepEqual(capped.map(w => w.id), ['1000009', '1000001']);
});

test('readActivity detects sale, price change, and newness inside the window', t => {
    const { dataDir, product } = tempTree(t);
    const write = (id, entries) => {
        const dir = path.join(dataDir, id.substring(0, 3));
        fs.mkdirSync(dir, { recursive: true });
        fs.writeFileSync(path.join(dir, `${id}.json`),
            JSON.stringify({ id: Number(id), variations: { default: entries } }));
    };
    const cutoff = '2026-10-09'; // today 2026-10-23, 14-day window
    write('2000001', [{ date: '2026-08-01', price: 500, is_sale: false },
        { date: '2026-10-20', price: 500, is_sale: true }]);
    assert.equal(readActivity(dataDir, '2000001', cutoff), true); // on sale now
    write('2000002', [{ date: '2026-08-01', price: 500, is_sale: false },
        { date: '2026-10-15', price: 400, is_sale: false }]);
    assert.equal(readActivity(dataDir, '2000002', cutoff), true); // price changed in window
    write('2000003', [{ date: '2026-10-21', price: 500, is_sale: false }]);
    assert.equal(readActivity(dataDir, '2000003', cutoff), true); // newly tracked
    write('2000004', [{ date: '2026-08-01', price: 500, is_sale: false },
        { date: '2026-10-20', price: 500, is_sale: false }]);
    assert.equal(readActivity(dataDir, '2000004', cutoff), false); // quiet
    write('2000005', [{ date: '2026-08-01', price: 500, is_sale: true },
        { date: '2026-09-01', price: 500, is_sale: true }]);
    assert.equal(readActivity(dataDir, '2000005', cutoff), false); // sale is stale news
    product('2000006'); // shapeless price file must not throw
    assert.equal(readActivity(dataDir, '2000006', cutoff), false);
});

test('buildWorkList gives hot items a daily snapshot ahead of the quiet refresh', t => {
    const { dataDir, metaDir, meta } = tempTree(t);
    const write = (id, entries) => {
        const dir = path.join(dataDir, id.substring(0, 3));
        fs.mkdirSync(dir, { recursive: true });
        fs.writeFileSync(path.join(dir, `${id}.json`),
            JSON.stringify({ id: Number(id), variations: { default: entries } }));
    };
    write('3000001', [{ date: '2026-08-01', price: 500, is_sale: false },
        { date: '2026-10-22', price: 500, is_sale: true }]); // hot, meta from yesterday
    write('3000002', [{ date: '2026-08-01', price: 500, is_sale: false },
        { date: '2026-10-22', price: 500, is_sale: false }]); // quiet, meta 2 days old
    write('3000003', [{ date: '2026-08-01', price: 500, is_sale: false },
        { date: '2026-09-01', price: 500, is_sale: false }]); // quiet, meta 30 days old
    meta('3000001', { id: '3000001', fetched_at: '2026-10-22' });
    meta('3000002', { id: '3000002', fetched_at: '2026-10-21' });
    meta('3000003', { id: '3000003', fetched_at: '2026-09-23' });
    const work = buildWorkList({ dataDir, metaDir, today: '2026-10-23', runCap: 10 });
    assert.deepEqual(work.map(w => w.id), ['3000001', '3000003']);
});

test('main re-collects a hot item the next day so likes deltas accrue', async t => {
    const { dataDir, metaDir, meta } = tempTree(t);
    const today = jstDate(Date.now());
    const yesterday = new Date(Date.parse(`${today}T00:00:00Z`) - 86400000).toISOString().slice(0, 10);
    const dir = path.join(dataDir, '791');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, '7918308.json'), JSON.stringify({
        id: 7918308,
        variations: { default: [{ date: yesterday, price: 0, is_sale: true }] }
    }));
    meta('7918308', {
        id: '7918308', name: fixture.name, likes: 30,
        likes_history: [{ date: yesterday, count: 30 }], fetched_at: yesterday
    });
    const get = async () => ({ status: 200, data: fixture, headers: {} });
    const result = await main({ dataDir, metaDir, get, wait: async () => {}, log: () => {}, logError: () => {} });
    assert.equal(result.metrics.success, 1);
    const saved = JSON.parse(fs.readFileSync(path.join(metaDir, '791', '7918308.json'), 'utf8'));
    assert.deepEqual(saved.likes_history, [
        { date: yesterday, count: 30 }, { date: today, count: 39 }]);
});

test('main continuation is granted for a cap-bound run of successes', async t => {
    const { dataDir, metaDir, product } = tempTree(t);
    product('7918308');
    product('8328795');
    product('8639887');
    const parsed = parseItemJson('7918308', fixture);
    const fetchMeta = async id => ({ kind: 'success', meta: { ...parsed, id } });
    // fetchMeta bypasses the transport, so the client stub reports the
    // attempts the real client would have counted.
    const client = {
        check() {}, finish() {},
        getAttemptCount: () => 2,
        getBudget: () => ({ blockedUntil: 0 })
    };
    const result = await main({
        dataDir, metaDir, fetchMeta, client, runCap: 2, wait: async () => {}, log: () => {}, logError: () => {}
    });
    assert.equal(result.status, 'completed');
    assert.equal(result.metrics.success, 2);
    assert.equal(result.continueCollection, true);
    const drained = await main({
        dataDir, metaDir, fetchMeta, client, wait: async () => {}, log: () => {}, logError: () => {}
    });
    assert.equal(drained.continueCollection, false); // one item remained; now drained
});

test('main stops gracefully at its own run cap instead of being hard-killed', async t => {
    const { dataDir, metaDir, product } = tempTree(t);
    product('7918308');
    const get = async () => ({ status: 200, data: fixture, headers: {} });
    const result = await main({
        dataDir, metaDir, get, maxRunMs: 0, wait: async () => {}, log: () => {}, logError: () => {}
    });
    assert.equal(result.status, 'paused');
    assert.equal(result.reason, 'deadline');
    assert.equal(result.metrics.success, 0);
    const state = JSON.parse(fs.readFileSync(path.join(metaDir, 'meta_state.json'), 'utf8'));
    assert.equal(state.status, 'paused');
});

test('main collects into meta/ through an injected transport', async t => {
    const { dataDir, metaDir, product } = tempTree(t);
    product('7918308');
    product('5620940'); // deleted on BOOTH in reality; here the fake returns 404
    const get = async url => {
        if (url.endsWith('/7918308.json')) return { status: 200, data: fixture, headers: {} };
        const error = new Error('not found');
        error.response = { status: 404, headers: {} };
        throw error;
    };
    const result = await main({ dataDir, metaDir, get, wait: async () => {}, log: () => {}, logError: () => {} });
    assert.equal(result.status, 'completed');
    assert.equal(result.continueCollection, false); // drained below the cap
    const saved = JSON.parse(fs.readFileSync(path.join(metaDir, '791', '7918308.json'), 'utf8'));
    assert.equal(saved.likes, 39);
    assert.equal(saved.category.parent, '3Dモデル');
    assert.deepEqual(saved.likes_history, [{ date: saved.fetched_at, count: 39 }]);
    const missing = JSON.parse(fs.readFileSync(path.join(metaDir, '562', '5620940.json'), 'utf8'));
    assert.equal(missing.unavailable, true);
    const state = JSON.parse(fs.readFileSync(path.join(metaDir, 'meta_state.json'), 'utf8'));
    assert.equal(state.success, 1);
    assert.equal(state.unavailable, 1);
});
