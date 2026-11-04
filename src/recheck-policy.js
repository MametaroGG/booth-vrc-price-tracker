const fs = require('fs');
const path = require('path');
const { writeJson } = require('./collection-runtime');
const FILE = 'recheck_state.json';
function canonicalDate(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const ms = Date.parse(`${value}T00:00:00Z`);
    return Number.isFinite(ms) && new Date(ms).toISOString().slice(0, 10) === value;
}
function plusDays(date, days) {
    return new Date(Date.parse(`${date}T00:00:00Z`) + days * 86400000).toISOString().slice(0, 10);
}
function readRecheckState(metaDir, today) {
    const file = path.join(metaDir, FILE);
    if (!fs.existsSync(file)) return { schema: 1, next_group: 'recheck', entries: {} };
    let value;
    try { value = JSON.parse(fs.readFileSync(file, 'utf8')); }
    catch { throw new Error('Invalid metadata recheck state: unreadable JSON'); }
    if (!value || value.schema !== 1 || !['normal', 'recheck'].includes(value.next_group) ||
        !value.entries || typeof value.entries !== 'object' || Array.isArray(value.entries)) {
        throw new Error('Invalid metadata recheck state: schema');
    }
    for (const [id, entry] of Object.entries(value.entries)) {
        if (!/^[1-9]\d*$/.test(id) || !entry || !Number.isInteger(entry.failures) ||
            entry.failures < 1 || entry.failures > 4 || !canonicalDate(entry.attempt_date) ||
            entry.attempt_date > today || !canonicalDate(entry.retry_after) ||
            entry.retry_after !== plusDays(entry.attempt_date, Math.min(7, 2 ** (entry.failures - 1)))) {
            throw new Error(`Invalid metadata recheck state: entry ${id}`);
        }
    }
    return value;
}
function saveRecheckState(metaDir, state) { writeJson(path.join(metaDir, FILE), state); }
function cooldownActive(state, id, today) {
    return !!state.entries[id] && state.entries[id].retry_after > today;
}
function fairWork(recheck, normal, cap, nextGroup) {
    const out = [];
    let r = 0, n = 0, group = nextGroup;
    while (out.length < cap && (r < recheck.length || n < normal.length)) {
        if ((group === 'recheck' && r < recheck.length) || n >= normal.length) {
            out.push(recheck[r++]); group = 'normal';
        } else {
            out.push(normal[n++]); group = 'recheck';
        }
    }
    return out;
}
function recordOutcome(state, entry, outcome, today) {
    if (outcome === 'stopped') return;
    // Carry fairness across capped runs, including normal work failing.
    state.next_group = entry.recheck ? 'normal' : 'recheck';
    if (outcome === 'success' || outcome === 'unavailable') {
        delete state.entries[entry.id];
    } else if (['failure', 'interrupted'].includes(outcome) && (entry.recheck || state.entries[entry.id])) {
        // Interrupted fetches have uncertain network outcomes: cool down without
        // automatically replaying them or declaring metadata public/unavailable.
        const failures = Math.min(4, (state.entries[entry.id]?.failures || 0) + 1);
        state.entries[entry.id] = { failures, attempt_date: today,
            retry_after: plusDays(today, Math.min(7, 2 ** (failures - 1))) };
    }
}
module.exports = { canonicalDate, readRecheckState, saveRecheckState, cooldownActive, fairWork, recordOutcome };
