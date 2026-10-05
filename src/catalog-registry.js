const fs = require('node:fs');
const path = require('node:path');
const { jstDate, writeJson } = require('./collection-runtime');

const VERSION = 1;
const HOUR = 60 * 60 * 1000;
const WEEK = 7 * 24 * HOUR;
const MAX_TIME = Date.parse('9999-12-31T14:59:59.999Z');
const FATAL_STORAGE_CODES = new Set(['EIO', 'ENOSPC', 'EROFS', 'EMFILE', 'ENFILE']);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const timestamp = value => Number.isSafeInteger(value) && value >= 0 && value <= MAX_TIME;

function productId(value) {
    if (typeof value === 'number' && Number.isSafeInteger(value) && value > 0) value = String(value);
    if (typeof value !== 'string' || !/^[1-9]\d*$/.test(value)) {
        throw new Error('Invalid catalog product ID');
    }
    return value;
}

function compareIds(a, b) {
    // Do not lose precision when an ID is too large for a JavaScript number.
    return a.length - b.length || (a < b ? -1 : a > b ? 1 : 0);
}

function initialRecord(source, lastSuccess = null) {
    return { source, lastSuccess, lastAttempt: lastSuccess, failures: 0, unavailable: false, nextAttemptAt: 0 };
}

function validateRecord(record) {
    if (!object(record) || !['existing', 'filtered-search'].includes(record.source) ||
        !(record.lastSuccess === null || timestamp(record.lastSuccess)) ||
        !(record.lastAttempt === null || timestamp(record.lastAttempt)) ||
        !Number.isSafeInteger(record.failures) || record.failures < 0 ||
        typeof record.unavailable !== 'boolean' || !timestamp(record.nextAttemptAt) ||
        (record.lastSuccess !== null && (record.lastAttempt === null || record.lastAttempt < record.lastSuccess)) ||
        (record.failures === 0 && (record.unavailable || record.nextAttemptAt !== 0 || record.lastAttempt !== record.lastSuccess)) ||
        (record.failures > 0 && (record.lastAttempt === null || record.nextAttemptAt <= record.lastAttempt))) {
        throw new Error('Invalid catalog registry record; refusing to reset it');
    }
    return record;
}

function readMetadata(file) {
    try {
        if (!fs.lstatSync(file).isFile()) throw new Error('Metadata is not a regular file');
        return JSON.parse(fs.readFileSync(file, 'utf8'));
    } catch (error) {
        throw new Error(`Cannot read catalog registry metadata ${path.basename(file)}; refusing to reset it: ${error.message}`);
    }
}

function historySuccess(file, now) {
    // Product histories are inputs, never repair targets. A broken individual
    // file must remain in the refresh lane so its save failure can back off.
    try {
        const product = JSON.parse(fs.readFileSync(file, 'utf8'));
        if (!object(product) || !object(product.variations)) return null;
        let latest = null;
        for (const history of Object.values(product.variations)) {
            if (!Array.isArray(history)) continue;
            for (const entry of history) {
                if (!object(entry) || typeof entry.date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(entry.date)) continue;
                const time = Date.parse(`${entry.date}T00:00:00+09:00`);
                if (timestamp(time) && time <= now && jstDate(time) === entry.date &&
                    (latest === null || time > latest)) latest = time;
            }
        }
        return latest;
    } catch (error) {
        // A corrupt/missing individual history is recoverable work. A failing
        // storage device or exhausted process/file capacity is a run-wide fault.
        if (FATAL_STORAGE_CODES.has(error.code)) throw error;
        return null;
    }
}

/**
 * A single-writer durable catalog, sharded like the existing product directory.
 * Only bootstrap's existing product files and explicitly supplied filtered-search
 * IDs can introduce records. There is deliberately no HTTP or global ID source.
 */
class CatalogRegistry {
    constructor({ dataDir, now = Date.now }) {
        if (typeof dataDir !== 'string' || !dataDir || typeof now !== 'function') throw new Error('Invalid catalog registry options');
        this.dataDir = dataDir;
        this.registryDir = path.join(dataDir, 'crawl_registry');
        this.now = now;
        this.shards = new Map();
        this.indexedShards = new Set();
        this.ready = false;
        this.failed = false;
    }

    bootstrap() {
        if (this.failed) throw new Error('Catalog registry write failed; reopen it before continuing');
        if (this.ready) return this;
        const bootstrapTime = this.now();
        if (!timestamp(bootstrapTime)) throw new Error('Invalid catalog bootstrap time');
        let files = [];
        try { files = fs.readdirSync(this.registryDir, { withFileTypes: true }); }
        catch (error) { if (error.code !== 'ENOENT') throw error; }
        const indexFile = path.join(this.registryDir, 'index.json');
        const hasIndex = files.some(file => file.name === 'index.json');
        if (hasIndex) {
            const index = readMetadata(indexFile);
            if (!object(index) || index.version !== VERSION || !Array.isArray(index.shards) ||
                !index.shards.every(prefix => typeof prefix === 'string' && /^[1-9]\d{0,2}$/.test(prefix)) ||
                new Set(index.shards).size !== index.shards.length) {
                throw new Error('Invalid catalog registry index; refusing to reset it');
            }
            this.indexedShards = new Set(index.shards);
        }
        // Validate every metadata shard before making any bootstrap writes. An
        // index also detects a deleted shard instead of forgetting pending IDs.
        for (const file of files) {
            if (file.name === 'index.json' || file.name.endsWith('.tmp')) continue;
            if (!/^[1-9]\d{0,2}\.json$/.test(file.name) || !file.isFile()) {
                throw new Error(`Invalid catalog registry shard ${file.name}; refusing to reset it`);
            }
            const prefix = file.name.slice(0, -5);
            const shard = readMetadata(path.join(this.registryDir, file.name));
            if (!object(shard) || shard.version !== VERSION || !object(shard.entries)) {
                throw new Error(`Invalid catalog registry shard ${file.name}; refusing to reset it`);
            }
            for (const [id, record] of Object.entries(shard.entries)) {
                if (productId(id).slice(0, 3) !== prefix) throw new Error('Invalid catalog registry ID/shard; refusing to reset it');
                validateRecord(record);
                if (record.lastSuccess !== null && record.lastSuccess > bootstrapTime) {
                    throw new Error(`Future success in catalog registry for ${id}; refusing to reset it`);
                }
            }
            this.shards.set(prefix, shard);
        }
        for (const prefix of this.indexedShards) {
            if (!this.shards.has(prefix)) throw new Error(`Missing catalog registry shard ${prefix}; refusing to reset it`);
        }

        let directories = [];
        try { directories = fs.readdirSync(this.dataDir, { withFileTypes: true }); }
        catch (error) { if (error.code !== 'ENOENT') throw error; }
        const updates = new Map();
        for (const directory of directories) {
            if (!directory.isDirectory() || !/^[1-9]\d{0,2}$/.test(directory.name)) continue;
            const prefix = directory.name;
            const existing = this.shards.get(prefix);
            const entries = { ...(existing?.entries || {}) };
            let changed = false;
            for (const file of fs.readdirSync(path.join(this.dataDir, prefix), { withFileTypes: true })) {
                if (!file.isFile() || !/^[1-9]\d*\.json$/.test(file.name)) continue;
                const id = file.name.slice(0, -5);
                if (id.slice(0, 3) !== prefix) continue;
                const previous = entries[id];
                // Cached records avoid reading the whole product catalog again
                // on restart; a newly saved discovery may need crash recovery.
                if (previous?.source === 'existing') continue;
                const lastSuccess = historySuccess(path.join(this.dataDir, prefix, file.name), bootstrapTime);
                if (!previous) entries[id] = initialRecord('existing', lastSuccess);
                else {
                    entries[id] = { ...previous, source: 'existing' };
                    if (lastSuccess !== null && (previous.lastSuccess === null || lastSuccess > previous.lastSuccess) &&
                        (previous.failures === 0 || lastSuccess <= previous.lastAttempt)) {
                        entries[id].lastSuccess = lastSuccess;
                        entries[id].lastAttempt = Math.max(previous.lastAttempt ?? 0, lastSuccess);
                        // A recorded failure/backoff remains authoritative. The
                        // on-disk history alone is not proof it was recovered.
                        if (previous.failures === 0) entries[id].lastAttempt = lastSuccess;
                    }
                }
                changed = true;
            }
            if (changed) updates.set(prefix, { version: VERSION, entries });
        }
        // Finish all input reads before writing any migration metadata. A fatal
        // storage error in a later prefix must abort bootstrap without commits.
        for (const [prefix, shard] of updates) this.persist(prefix, shard, false);
        if (!hasIndex || this.shards.size !== this.indexedShards.size) this.persistIndex();
        this.ready = true;
        return this;
    }

    assertReady() {
        if (this.failed) throw new Error('Catalog registry write failed; reopen it before continuing');
        if (!this.ready) throw new Error('Catalog registry must be bootstrapped first');
    }

    persistIndex() {
        const prefixes = [...this.shards.keys()].sort(compareIds);
        try { writeJson(path.join(this.registryDir, 'index.json'), { version: VERSION, shards: prefixes }); }
        catch (error) { this.failed = true; throw error; }
        this.indexedShards = new Set(prefixes);
    }

    persist(prefix, shard, updateIndex = true) {
        try { writeJson(path.join(this.registryDir, `${prefix}.json`), shard); }
        catch (error) { this.failed = true; throw error; }
        this.shards.set(prefix, shard);
        // Write the shard first. An interruption before the index update leaves
        // a valid extra shard, which bootstrap loads and adds to the index.
        if (updateIndex && !this.indexedShards.has(prefix)) this.persistIndex();
    }

    has(id) {
        this.assertReady();
        id = productId(id);
        return Object.hasOwn(this.shards.get(id.slice(0, 3))?.entries || {}, id);
    }

    get(id) {
        if (!this.has(id)) return undefined;
        id = productId(id);
        return { id, ...this.shards.get(id.slice(0, 3)).entries[id] };
    }

    discover(ids) {
        this.assertReady();
        if (!Array.isArray(ids)) throw new Error('Filtered-search discovery IDs must be an array');
        // Validate the entire supplied batch before any write.
        const unique = [...new Set(ids.map(productId))];
        const updates = new Map();
        const added = [];
        for (const id of unique) {
            if (this.has(id)) continue;
            const prefix = id.slice(0, 3);
            if (!updates.has(prefix)) updates.set(prefix, { version: VERSION, entries: { ...(this.shards.get(prefix)?.entries || {}) } });
            updates.get(prefix).entries[id] = initialRecord('filtered-search');
            added.push(id);
        }
        for (const [prefix, shard] of updates) this.persist(prefix, shard, false);
        if (this.shards.size !== this.indexedShards.size) this.persistIndex();
        return added;
    }

    isDue(id, time = this.now()) {
        this.assertReady();
        if (!timestamp(time)) throw new Error('Invalid catalog attempt time');
        const record = this.get(id);
        if (!record) return false;
        return record.nextAttemptAt <= time &&
            (record.lastSuccess === null || jstDate(record.lastSuccess) < jstDate(time));
    }

    eligible(lane, time = this.now()) {
        this.assertReady();
        if (!['refresh', 'discovery'].includes(lane)) throw new Error('Invalid catalog lane');
        if (!timestamp(time)) throw new Error('Invalid catalog attempt time');
        const candidates = [];
        const today = jstDate(time);
        for (const shard of this.shards.values()) {
            for (const [id, record] of Object.entries(shard.entries)) {
                const refresh = record.source === 'existing' || record.lastSuccess !== null;
                if (refresh !== (lane === 'refresh') || record.nextAttemptAt > time ||
                    (record.lastSuccess !== null && jstDate(record.lastSuccess) >= today)) continue;
                // Once an item fails, rank its next attempt by its last attempt
                // instead of letting its ancient success monopolize the queue.
                const anchor = record.failures > 0 ? record.lastAttempt : record.lastSuccess;
                candidates.push({ id, anchor: anchor ?? -1 });
            }
        }
        candidates.sort((a, b) => a.anchor - b.anchor || compareIds(a.id, b.id));
        return candidates.map(candidate => candidate.id);
    }

    update(id, time, makeRecord) {
        this.assertReady();
        id = productId(id);
        if (!timestamp(time)) throw new Error('Invalid catalog attempt time');
        const prefix = id.slice(0, 3);
        const shard = this.shards.get(prefix);
        const previous = shard?.entries[id];
        if (!previous) throw new Error('Unknown catalog ID; use approved filtered-search discovery first');
        if (previous.lastAttempt !== null && time < previous.lastAttempt) throw new Error('Catalog attempt time moved backwards');
        const record = validateRecord(makeRecord(previous));
        this.persist(prefix, { version: VERSION, entries: { ...shard.entries, [id]: record } });
        return { id, ...record };
    }

    recordSuccess(id, time = this.now()) {
        return this.update(id, time, previous => ({ ...initialRecord(previous.source, time) }));
    }

    recordFailure(id, time = this.now(), { unavailable = false } = {}) {
        if (typeof unavailable !== 'boolean') throw new Error('Invalid catalog unavailable status');
        return this.update(id, time, previous => {
            const failures = Math.min(previous.failures + 1, Number.MAX_SAFE_INTEGER);
            const delay = unavailable ? WEEK : failures === 1 ? HOUR : failures === 2 ? 6 * HOUR :
                Math.min(WEEK, 24 * HOUR * 2 ** Math.min(failures - 3, 3));
            return { ...previous, lastAttempt: time, failures, unavailable, nextAttemptAt: time + delay };
        });
    }
}

module.exports = { CatalogRegistry };
