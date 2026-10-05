const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { CatalogRegistry } = require('../src/catalog-registry');
const { writeJson } = require('../src/collection-runtime');

const START = Date.parse('2026-10-05T03:00:00Z');
const HOUR = 3600000;
const DAY = 24 * HOUR;
const jstMidnight = date => Date.parse(`${date}T00:00:00+09:00`);

function fixture(t) {
    const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'boopa-catalog-'));
    t.after(() => fs.rmSync(dataDir, { recursive: true, force: true }));
    let time = START;
    const make = () => new CatalogRegistry({ dataDir, now: () => time });
    const productFile = id => path.join(dataDir, id.slice(0, 3), `${id}.json`);
    const product = (id, variations = {}) => {
        const file = productFile(id);
        writeJson(file, { id, name: `Product ${id}`, variations });
        return file;
    };
    const metadata = prefix => path.join(dataDir, 'crawl_registry', `${prefix}.json`);
    return { dataDir, product, productFile, metadata, make, setTime: value => { time = value; } };
}

test('bootstrap imports only canonical numeric product files and never mutates histories', t => {
    const f = fixture(t);
    const oldFile = f.product('1234567', { old: [{ date: '2026-10-01', price: 500 }] });
    f.product('98');
    writeJson(path.join(f.dataDir, 'crawl_state.json'), { pendingIds: ['7000001'] });
    writeJson(path.join(f.dataDir, 'arbitrary', '8000001.json'), { id: '8000001' });
    writeJson(path.join(f.dataDir, '999', '8888888.json'), { id: '8888888' });
    writeJson(path.join(f.dataDir, '123', 'not-an-id.json'), { id: '9000001' });
    writeJson(path.join(f.dataDir, '123', 'nested', '1230000.json'), { id: '1230000' });
    const before = fs.readFileSync(oldFile, 'utf8');
    const registry = f.make().bootstrap();
    assert.deepEqual(registry.eligible('refresh'), ['98', '1234567']);
    assert.deepEqual(registry.eligible('discovery'), []);
    for (const id of ['7000001', '8000001', '8888888', '9000001', '1230000']) assert.equal(registry.has(id), false);
    assert.equal(fs.readFileSync(oldFile, 'utf8'), before);
    assert.equal(registry.get('1234567').lastSuccess, jstMidnight('2026-10-01'));
    assert.equal(registry.bootstrap(), registry);
});

test('history migration uses the maximum valid date across all variations and excludes successful-today IDs', t => {
    const f = fixture(t);
    f.product('101', {
        first: [{ date: '2026-10-02' }, { date: '2026-02-30' }, { date: 'not-a-date' }],
        renamed: [{ date: '2026-10-04' }, { date: '2026-10-01' }, null, {}]
    });
    f.product('102', { first: [{ date: '2026-10-05' }], second: [{ date: '2026-10-03' }] });
    f.product('103', { first: [{ date: '2026-10-03' }] });
    f.product('104', { first: [{ date: '2026-10-4' }, { date: '2026-13-01' }, { date: null }] });
    const registry = f.make().bootstrap();
    assert.equal(registry.get('101').lastSuccess, jstMidnight('2026-10-04'));
    assert.equal(registry.get('102').lastSuccess, jstMidnight('2026-10-05'));
    assert.equal(registry.get('104').lastSuccess, null);
    assert.deepEqual(registry.eligible('refresh'), ['104', '103', '101']);
    assert.equal(registry.isDue('102'), false);
    assert.equal(registry.isDue('102', Date.parse('2026-10-05T15:00:00Z')), true);
});

test('malformed individual products retain known IDs with unknown last success', t => {
    const f = fixture(t);
    const corrupt = f.product('101');
    fs.writeFileSync(corrupt, '{truncated');
    writeJson(f.productFile('102'), null);
    writeJson(f.productFile('103'), { variations: [] });
    f.product('104', { healthy: [{ date: '2026-10-04' }] });
    const registry = f.make().bootstrap();
    for (const id of ['101', '102', '103']) {
        assert.equal(registry.has(id), true);
        assert.equal(registry.get(id).lastSuccess, null);
    }
    registry.recordFailure('101');
    assert.equal(registry.get('101').nextAttemptAt, START + HOUR);
    assert.deepEqual(registry.eligible('refresh'), ['102', '103', '104']);
    assert.equal(fs.readFileSync(corrupt, 'utf8'), '{truncated');
});

test('bootstrap ignores future history dates and keeps past dates or unknown success eligible', t => {
    const f = fixture(t);
    const mixedFile = f.product('101', {
        futureFirst: [{ date: '9999-12-31' }, { date: '2026-10-03' }],
        another: [{ date: '2026-10-04' }, { date: '2027-01-01' }]
    });
    const futureFile = f.product('102', { allFuture: [{ date: '2026-10-06' }, { date: '9999-12-31' }] });
    f.product('103', { today: [{ date: '2026-10-05' }] });
    const before = [mixedFile, futureFile].map(file => fs.readFileSync(file, 'utf8'));
    const registry = f.make().bootstrap();
    assert.equal(registry.get('101').lastSuccess, jstMidnight('2026-10-04'));
    assert.equal(registry.get('102').lastSuccess, null);
    assert.equal(registry.get('103').lastSuccess, jstMidnight('2026-10-05'));
    assert.deepEqual(registry.eligible('refresh'), ['102', '101']);
    assert.deepEqual([mixedFile, futureFile].map(file => fs.readFileSync(file, 'utf8')), before);
});

test('a product that disappears or cannot be read during bootstrap does not stop the catalog', t => {
    const f = fixture(t);
    const lost = f.product('101');
    f.product('102');
    const read = fs.readFileSync;
    const mock = t.mock.method(fs, 'readFileSync', function(file, ...args) {
        if (file === lost) throw Object.assign(new Error('disappeared'), { code: 'ENOENT' });
        return read.call(this, file, ...args);
    });
    const registry = f.make().bootstrap();
    mock.mock.restore();
    assert.equal(registry.get('101').lastSuccess, null);
    assert.deepEqual(registry.eligible('refresh'), ['101', '102']);
});

test('fatal history storage errors abort bootstrap before any metadata write', t => {
    for (const code of ['EIO', 'ENOSPC', 'EROFS', 'EMFILE', 'ENFILE']) {
        const f = fixture(t);
        f.product('101', { old: [{ date: '2026-10-04' }] });
        const failingFile = f.product('202', { old: [{ date: '2026-10-03' }] });
        const failure = Object.assign(new Error(`Fatal storage error: ${code}`), { code });
        const reads = [];
        const writes = [];
        const read = fs.readFileSync;
        const write = fs.writeFileSync;
        const readMock = t.mock.method(fs, 'readFileSync', function(file, ...args) {
            reads.push(file);
            if (file === failingFile) throw failure;
            return read.call(this, file, ...args);
        });
        const writeMock = t.mock.method(fs, 'writeFileSync', function(file, ...args) {
            writes.push(file);
            return write.call(this, file, ...args);
        });
        const registry = f.make();
        assert.throws(() => registry.bootstrap(), error => error === failure && error.code === code);
        assert.ok(reads.includes(f.productFile('101')));
        assert.deepEqual(writes, []);
        assert.equal(fs.existsSync(path.join(f.dataDir, 'crawl_registry')), false);
        assert.throws(() => registry.eligible('refresh'), /bootstrapped first/);
        readMock.mock.restore();
        writeMock.mock.restore();
    }
});

test('EIO during an existing catalog migration leaves all metadata and histories unchanged', t => {
    const f = fixture(t);
    const originalHistory = f.product('101', { old: [{ date: '2026-10-03' }] });
    f.make().bootstrap();
    const files = [originalHistory, f.metadata('101'), f.metadata('index')];
    const before = files.map(file => fs.readFileSync(file, 'utf8'));
    f.product('102');
    const failingFile = f.product('999');
    const read = fs.readFileSync;
    const mock = t.mock.method(fs, 'readFileSync', function(file, ...args) {
        if (file === failingFile) throw Object.assign(new Error('storage offline'), { code: 'EIO' });
        return read.call(this, file, ...args);
    });
    assert.throws(() => f.make().bootstrap(), error => error.code === 'EIO');
    mock.mock.restore();
    assert.deepEqual(files.map(file => fs.readFileSync(file, 'utf8')), before);
    assert.equal(fs.existsSync(f.metadata('102')), false);
    assert.equal(fs.existsSync(f.metadata('999')), false);
});

test('collector sends no HTTP or item work when history bootstrap encounters EIO', async t => {
    const { main } = require('../src/scraper');
    const f = fixture(t);
    f.product('101');
    const failingFile = f.product('202');
    const read = fs.readFileSync;
    const mock = t.mock.method(fs, 'readFileSync', function(file, ...args) {
        if (file === failingFile) throw Object.assign(new Error('storage offline'), { code: 'EIO' });
        return read.call(this, file, ...args);
    });
    const calls = [];
    await assert.rejects(main({
        dataDir: f.dataDir,
        now: () => START,
        client: { get: async () => { calls.push('http'); }, check() {}, finish() {} },
        search: async () => { calls.push('search'); return { kind: 'empty', ids: [] }; },
        detail: async () => { calls.push('detail'); return { kind: 'failure', error: new Error('unexpected detail') }; },
        save: async () => { calls.push('save'); }
    }), error => error.code === 'EIO');
    mock.mock.restore();
    assert.deepEqual(calls, []);
    assert.equal(fs.existsSync(path.join(f.dataDir, 'crawl_registry')), false);
});

test('discovery is explicit, validated, durable, deduplicated and separate from existing refresh', t => {
    const f = fixture(t);
    f.product('101');
    const registry = f.make().bootstrap();
    assert.deepEqual(registry.discover(['202', '201', '202', 101]), ['202', '201']);
    assert.deepEqual(registry.eligible('discovery'), ['201', '202']);
    assert.deepEqual(registry.eligible('refresh'), ['101']);
    assert.deepEqual(registry.discover(['201', '202']), []);
    assert.throws(() => registry.recordSuccess('999'), /Unknown catalog ID/);
    assert.throws(() => registry.recordFailure('999'), /Unknown catalog ID/);
    for (const bad of ['../123', 'https://booth.pm/items/1', '', '01', '0', '-1', '1.5', null, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
        assert.throws(() => registry.discover(['301', bad]), /Invalid catalog product ID/);
        assert.equal(registry.has('301'), false);
    }
    assert.throws(() => registry.discover('301'), /must be an array/);
    assert.equal(registry.isDue('999'), false);
    const restarted = f.make().bootstrap();
    assert.deepEqual(restarted.eligible('discovery'), ['201', '202']);
    assert.deepEqual(restarted.eligible('refresh'), ['101']);
});

test('success promotes discovery to refresh, uses JST days and resets prior backoff', t => {
    const f = fixture(t);
    const registry = f.make().bootstrap();
    registry.discover(['101']);
    registry.recordFailure('101');
    const successTime = START + HOUR;
    const record = registry.recordSuccess('101', successTime);
    assert.deepEqual(record, {
        id: '101', source: 'filtered-search', lastSuccess: successTime,
        lastAttempt: successTime, failures: 0, unavailable: false, nextAttemptAt: 0
    });
    assert.equal(registry.isDue('101', successTime), false);
    assert.deepEqual(registry.eligible('discovery', successTime + DAY), []);
    assert.deepEqual(registry.eligible('refresh', successTime + DAY), ['101']);
    assert.equal(registry.isDue('101', Date.parse('2026-10-05T14:59:59Z')), false);
    assert.equal(registry.isDue('101', Date.parse('2026-10-05T15:00:00Z')), true);
    f.setTime(successTime);
    assert.equal(f.make().bootstrap().get('101').lastSuccess, successTime);
});

test('transient, parse and save failures use durable bounded backoff without changing last success', t => {
    const f = fixture(t);
    f.product('101', { old: [{ date: '2026-01-01' }] });
    let registry = f.make().bootstrap();
    let time = START;
    const expected = [HOUR, 6 * HOUR, DAY, 2 * DAY, 4 * DAY, 7 * DAY, 7 * DAY];
    for (let i = 0; i < expected.length; i++) {
        const record = registry.recordFailure('101', time);
        assert.equal(record.failures, i + 1);
        assert.equal(record.lastSuccess, jstMidnight('2026-01-01'));
        assert.equal(record.nextAttemptAt, time + expected[i]);
        registry = f.make().bootstrap();
        assert.equal(registry.isDue('101', time + expected[i] - 1), false);
        assert.equal(registry.isDue('101', time + expected[i]), true);
        time += expected[i];
    }
});

test('failed items use last attempt for fairness instead of permanently leading with ancient success', t => {
    const f = fixture(t);
    f.product('101', { old: [{ date: '2020-01-01' }] });
    f.product('102', { old: [{ date: '2026-10-03' }] });
    f.product('103', { old: [{ date: '2026-10-04' }] });
    const registry = f.make().bootstrap();
    assert.deepEqual(registry.eligible('refresh'), ['101', '102', '103']);
    registry.recordFailure('101');
    assert.deepEqual(registry.eligible('refresh', START + HOUR), ['102', '103', '101']);
    registry.discover(['201', '202']);
    registry.recordFailure('201');
    assert.deepEqual(registry.eligible('discovery', START + HOUR), ['202', '201']);
    assert.deepEqual(f.make().bootstrap().eligible('refresh', START + HOUR), ['102', '103', '101']);
});

test('unavailable and deleted products retain history and catalog membership with weekly retries', t => {
    const f = fixture(t);
    const file = f.product('101', { old: [{ date: '2026-01-01', price: 500 }] });
    const before = fs.readFileSync(file, 'utf8');
    const registry = f.make().bootstrap();
    const record = registry.recordFailure('101', START, { unavailable: true });
    assert.equal(record.lastSuccess, jstMidnight('2026-01-01'));
    assert.equal(record.nextAttemptAt, START + 7 * DAY);
    assert.equal(fs.readFileSync(file, 'utf8'), before);
    fs.rmSync(file);
    const restarted = f.make().bootstrap();
    assert.equal(restarted.has('101'), true);
    assert.equal(restarted.isDue('101', START + 7 * DAY - 1), false);
    assert.deepEqual(restarted.eligible('refresh', START + 7 * DAY), ['101']);
    restarted.discover(['101']);
    assert.deepEqual(restarted.get('101'), record);
    assert.equal(restarted.recordFailure('101', START + 7 * DAY, { unavailable: true }).nextAttemptAt, START + 14 * DAY);
});

test('rediscovery and repeated bootstrap never clear backoff or requeue completed-today work', t => {
    const f = fixture(t);
    f.product('101');
    const registry = f.make().bootstrap();
    registry.discover(['201', '202']);
    registry.recordFailure('101');
    registry.recordFailure('201', START, { unavailable: true });
    registry.recordSuccess('202');
    const snapshot = ['101', '201', '202'].map(id => registry.get(id));
    assert.deepEqual(registry.discover(['101', '201', '202']), []);
    registry.bootstrap();
    const restarted = f.make().bootstrap();
    assert.deepEqual(['101', '201', '202'].map(id => restarted.get(id)), snapshot);
    assert.deepEqual(restarted.eligible('refresh'), []);
    assert.deepEqual(restarted.eligible('discovery'), []);
});

test('numeric ID ties are deterministic without floating-point rounding', t => {
    const f = fixture(t);
    const registry = f.make().bootstrap();
    registry.discover(['9007199254740993', '100', '2', '9007199254740992', '10']);
    assert.deepEqual(registry.eligible('discovery'), ['2', '10', '100', '9007199254740992', '9007199254740993']);
});

test('corrupt shard and index metadata fail closed before any migration writes', t => {
    const f = fixture(t);
    const registry = f.make().bootstrap();
    registry.discover(['101']);
    const original = fs.readFileSync(f.metadata('101'), 'utf8');
    f.product('202');
    const invalid = ['{truncated', 'null', '[]', JSON.stringify({ version: 2, entries: {} }),
        JSON.stringify({ version: 1, entries: { 101: {} } }),
        JSON.stringify({ version: 1, entries: { 102: registry.get('101') } })];
    for (const value of invalid) {
        fs.writeFileSync(f.metadata('101'), value);
        assert.throws(() => f.make().bootstrap(), /catalog registry/i);
        assert.equal(fs.readFileSync(f.metadata('101'), 'utf8'), value);
        assert.equal(fs.existsSync(f.metadata('202')), false);
    }
    fs.writeFileSync(f.metadata('101'), original);
    const indexFile = f.metadata('index');
    for (const value of ['{truncated', '{}', JSON.stringify({ version: 1, shards: ['../101'] })]) {
        fs.writeFileSync(indexFile, value);
        assert.throws(() => f.make().bootstrap(), /catalog registry/i);
        assert.equal(fs.readFileSync(indexFile, 'utf8'), value);
    }
});

test('invalid persisted attempts and backoffs are rejected rather than reset', t => {
    const f = fixture(t);
    const registry = f.make().bootstrap();
    registry.discover(['101']);
    const original = JSON.parse(fs.readFileSync(f.metadata('101'), 'utf8'));
    for (const changes of [
        { lastSuccess: '2026-10-01' }, { failures: -1 }, { unavailable: 'true' },
        { nextAttemptAt: -1 }, { source: 'global-search' },
        { failures: 1, lastAttempt: START, nextAttemptAt: START },
        { lastSuccess: START, lastAttempt: START - 1 }, { unavailable: true }
    ]) {
        writeJson(f.metadata('101'), { ...original, entries: { 101: { ...original.entries['101'], ...changes } } });
        assert.throws(() => f.make().bootstrap(), /Invalid catalog registry record/);
    }
});

test('future successful timestamps in existing registry metadata fail closed without modifying history or metadata', t => {
    const f = fixture(t);
    const file = f.product('101', { current: [{ date: '2026-10-04' }] });
    f.make().bootstrap();
    const shard = JSON.parse(fs.readFileSync(f.metadata('101'), 'utf8'));
    const future = jstMidnight('2027-01-01');
    shard.entries['101'].lastSuccess = future;
    shard.entries['101'].lastAttempt = future;
    writeJson(f.metadata('101'), shard);
    const before = [file, f.metadata('101'), f.metadata('index')].map(file => fs.readFileSync(file, 'utf8'));
    assert.throws(() => f.make().bootstrap(), /Future success in catalog registry for 101; refusing to reset it/);
    assert.deepEqual([file, f.metadata('101'), f.metadata('index')].map(file => fs.readFileSync(file, 'utf8')), before);
});

test('a missing indexed metadata shard fails closed instead of losing new IDs', t => {
    const f = fixture(t);
    f.make().bootstrap().discover(['101']);
    fs.rmSync(f.metadata('101'));
    assert.throws(() => f.make().bootstrap(), /Missing catalog registry shard 101/);
});

test('a shard durably written before an interrupted index update is recovered', t => {
    const f = fixture(t);
    const registry = f.make().bootstrap();
    registry.discover(['101']);
    writeJson(f.metadata('index'), { version: 1, shards: [] });
    const restarted = f.make().bootstrap();
    assert.deepEqual(restarted.eligible('discovery'), ['101']);
    assert.deepEqual(JSON.parse(fs.readFileSync(f.metadata('index'))).shards, ['101']);
});

test('bootstrap and discovery batch shard writes and a single outcome rewrites only its own shard', t => {
    const f = fixture(t);
    for (let i = 0; i < 80; i++) f.product(`123${1000 + i}`);
    f.product('4561000');
    const renamed = [];
    const rename = fs.renameSync;
    const mock = t.mock.method(fs, 'renameSync', function(from, to) {
        renamed.push(path.basename(to));
        return rename.call(this, from, to);
    });
    const registry = f.make().bootstrap();
    assert.equal(renamed.filter(file => file === '123.json').length, 1);
    assert.equal(renamed.filter(file => file === '456.json').length, 1);
    assert.equal(renamed.filter(file => file === 'index.json').length, 1);
    renamed.length = 0;
    registry.discover(Array.from({ length: 80 }, (_, i) => `789${1000 + i}`));
    assert.equal(renamed.filter(file => file === '789.json').length, 1);
    renamed.length = 0;
    registry.recordSuccess('1231000');
    assert.deepEqual(renamed, ['123.json']);
    renamed.length = 0;
    f.make().bootstrap();
    assert.deepEqual(renamed, []);
    mock.mock.restore();
});

test('atomic write failure cannot advertise an unpersisted success and a restart retains prior state', t => {
    const f = fixture(t);
    const registry = f.make().bootstrap();
    registry.discover(['101']);
    const before = fs.readFileSync(f.metadata('101'), 'utf8');
    const rename = fs.renameSync;
    const mock = t.mock.method(fs, 'renameSync', function(from, to) {
        if (to === f.metadata('101')) throw new Error('disk failure');
        return rename.call(this, from, to);
    });
    assert.throws(() => registry.recordSuccess('101'), /disk failure/);
    assert.equal(fs.readFileSync(f.metadata('101'), 'utf8'), before);
    assert.throws(() => registry.has('101'), /write failed/);
    mock.mock.restore();
    const restarted = f.make().bootstrap();
    assert.equal(restarted.get('101').lastSuccess, null);
    assert.deepEqual(restarted.eligible('discovery'), ['101']);
});

test('saved discovery history can recover a crash before recording success without losing an existing backoff', t => {
    const f = fixture(t);
    const registry = f.make().bootstrap();
    registry.discover(['101', '102']);
    registry.recordFailure('102');
    f.product('101', { old: [{ date: '2026-10-05' }] });
    f.product('102');
    const restarted = f.make().bootstrap();
    assert.equal(restarted.get('101').source, 'existing');
    assert.equal(restarted.get('101').lastSuccess, jstMidnight('2026-10-05'));
    assert.equal(restarted.isDue('101'), false);
    assert.equal(restarted.get('102').nextAttemptAt, START + HOUR);
    assert.equal(restarted.get('102').lastSuccess, null);
    assert.deepEqual(restarted.eligible('discovery'), []);
});

test('a newer product history cannot invalidate an authoritative failed-attempt backoff on restart', t => {
    const f = fixture(t);
    const registry = f.make().bootstrap();
    registry.discover(['101']);
    registry.recordFailure('101');
    f.product('101', { future: [{ date: '2026-10-10' }] });
    const first = f.make().bootstrap().get('101');
    assert.equal(first.source, 'existing');
    assert.equal(first.lastSuccess, null);
    assert.equal(first.nextAttemptAt, START + HOUR);
    assert.deepEqual(f.make().bootstrap().get('101'), first);
});

test('failed index update preserves already committed discovery IDs for recovery', t => {
    const f = fixture(t);
    const registry = f.make().bootstrap();
    const rename = fs.renameSync;
    const mock = t.mock.method(fs, 'renameSync', function(from, to) {
        if (to === f.metadata('index')) throw new Error('index disk failure');
        return rename.call(this, from, to);
    });
    assert.throws(() => registry.discover(['101', '201']), /index disk failure/);
    mock.mock.restore();
    assert.deepEqual(f.make().bootstrap().eligible('discovery'), ['101', '201']);
});

test('invalid API use cannot silently initialize records or move attempt times backward', t => {
    const f = fixture(t);
    const registry = f.make();
    assert.throws(() => registry.discover(['101']), /bootstrapped first/);
    registry.bootstrap().discover(['101']);
    assert.throws(() => registry.eligible('anything'), /Invalid catalog lane/);
    assert.throws(() => registry.isDue('101', NaN), /Invalid catalog attempt time/);
    assert.throws(() => registry.recordFailure('101', START, { unavailable: 'yes' }), /unavailable status/);
    registry.recordFailure('101');
    assert.throws(() => registry.recordSuccess('101', START - 1), /moved backwards/);
    const copy = registry.get('101');
    copy.nextAttemptAt = 0;
    assert.equal(registry.isDue('101'), false);
});
