const path = require('node:path');
const { reserveDailyAllowance } = require('./collection-runtime');

// The metadata job keeps its OWN request ledger under meta/. Sharing the
// price scraper's data/request_budget.json would let two workflows reserve
// against one file (its push script rightly refuses to merge a changed
// ledger), and BOOTH-facing politeness needs the combined volume visible
// per job, not hidden inside the price crawl's accounting.
if (require.main === module) {
    try {
        if (!process.env.META_RESERVATION_ID) throw new Error('META_RESERVATION_ID is required');
        const dailyLimit = process.env.META_DAILY_LIMIT === undefined
            ? 12000 : Number(process.env.META_DAILY_LIMIT);
        if (!Number.isSafeInteger(dailyLimit) || dailyLimit < 0) {
            throw new Error('META_DAILY_LIMIT must be a non-negative integer');
        }
        const reservation = reserveDailyAllowance({
            budgetFile: path.join(__dirname, '..', 'meta', 'request_budget.json'),
            reservationId: process.env.META_RESERVATION_ID,
            dailyLimit
        });
        console.log(`Reserved at most ${reservation.limit} item-metadata requests for this run, including retries and redirects.`);
    } catch (error) {
        console.error(`Cannot reserve metadata request budget: ${error.message}`);
        process.exitCode = 1;
    }
}
