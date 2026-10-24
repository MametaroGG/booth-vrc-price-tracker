const path = require('node:path');
const { reserveDailyAllowance } = require('./collection-runtime');

// The metadata job keeps its OWN request ledger under meta/. Sharing the
// price scraper's data/request_budget.json would let two workflows reserve
// against one file (its push script rightly refuses to merge a changed
// ledger), and the combined BOOTH-facing volume stays visible per job, not
// hidden inside the price crawl's accounting. Like the price job, the
// default session is unlimited: the sweep is paced by the run envelope and
// the JST day boundary (full-catalog daily collection, decided 2026-10-24).
// META_DAILY_LIMIT can still impose a finite ceiling for a run.
if (require.main === module) {
    try {
        if (!process.env.META_RESERVATION_ID) throw new Error('META_RESERVATION_ID is required');
        const dailyLimit = process.env.META_DAILY_LIMIT === undefined
            ? null : Number(process.env.META_DAILY_LIMIT);
        if (dailyLimit !== null && (!Number.isSafeInteger(dailyLimit) || dailyLimit < 0)) {
            throw new Error('META_DAILY_LIMIT must be a non-negative integer');
        }
        const reservation = reserveDailyAllowance({
            budgetFile: path.join(__dirname, '..', 'meta', 'request_budget.json'),
            reservationId: process.env.META_RESERVATION_ID,
            dailyLimit
        });
        console.log(reservation.mode === 'unlimited'
            ? 'Opened an unlimited daily metadata session; all requests, redirects and retries remain recorded.'
            : `Reserved at most ${reservation.limit} item-metadata requests for this run, including retries and redirects.`);
    } catch (error) {
        console.error(`Cannot reserve metadata request budget: ${error.message}`);
        process.exitCode = 1;
    }
}
