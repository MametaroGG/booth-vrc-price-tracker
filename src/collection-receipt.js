'use strict';
// LOCAL PROPOSAL ONLY. This is not present in the inspected producer commit.
const SCHEMA = 'boopa-collection-receipt-v1';
const REPOSITORY = 'MametaroGG/booth-vrc-price-tracker';
const count = v => Number.isSafeInteger(v) && v >= 0;
const id = v => typeof v === 'string' && /^[1-9]\d{0,19}$/.test(v);
function makeReceipt(result, env = process.env) {
    if (!id(env.GITHUB_RUN_ID) || !id(env.GITHUB_RUN_ATTEMPT) ||
        env.SCRAPER_RESERVATION_ID !== `${env.GITHUB_RUN_ID}-${env.GITHUB_RUN_ATTEMPT}` ||
        env.GITHUB_REPOSITORY !== REPOSITORY || !/^[0-9a-f]{40}$/.test(env.COLLECTOR_SOURCE_COMMIT || '')) throw new Error('Invalid collector identity');
    return { ...result, schema: SCHEMA, repository: REPOSITORY, run_id: env.GITHUB_RUN_ID,
        run_attempt: env.GITHUB_RUN_ATTEMPT, source_commit: env.COLLECTOR_SOURCE_COMMIT, reservation_id: env.SCRAPER_RESERVATION_ID,
        scope: 'bounded-filtered-search-observation', whole_catalog_complete: false };
}
function eligible(r) {
    if (!r || r.schema !== SCHEMA || r.repository !== REPOSITORY || !id(r.run_id) ||
        !id(r.run_attempt) || r.reservation_id !== `${r.run_id}-${r.run_attempt}` ||
        !/^[0-9a-f]{40}$/.test(r.source_commit || '') || r.scope !== 'bounded-filtered-search-observation' || r.whole_catalog_complete !== false ||
        r.failed !== false || r.reservation_completed !== true) return false;
    if (![r.started_at_ms, r.stopped_at_ms, r.deadline_ms, r.blocked_until_ms].every(count) ||
        r.stopped_at_ms < r.started_at_ms || r.deadline_ms <= r.started_at_ms ||
        r.blocked_until_ms > r.stopped_at_ms || !count(r.pending_retry_count)) return false;
    const m = r.metrics;
    if (!m || !['searchPages','searchFailures','itemSuccess','itemFailures','unavailable','retries',
        'duplicatesAvoided','chargedHttpAttempts','dailyChargedRequests'].every(k => count(m[k])) ||
        m.chargedHttpAttempts === 0 || m.itemSuccess === 0 || m.itemFailures !== 0 ||
        m.searchFailures !== 0) return false;
    // A completed filtered sweep is still not the BOOTH catalog. A sweep that
    // started mid-way is only this run's bounded segment.
    if (r.status === 'completed') return r.reason === undefined && r.pending_retry_count === 0;
    if (r.status !== 'paused') return false;
    if (r.reason === 'deadline') return r.stopped_at_ms - r.started_at_ms >= 60000 &&
        r.stopped_at_ms >= r.deadline_ms - 2000;
    // Match producer's JST day-boundary semantics, not an arbitrary pause.
    if (r.reason === 'day-boundary') return Math.floor((r.started_at_ms + 32400000) / 86400000) !==
        Math.floor((r.stopped_at_ms + 32400000) / 86400000);
    return false;
}
module.exports = { makeReceipt, eligible };
