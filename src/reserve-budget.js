const path = require('node:path');
const fs = require('node:fs');
const { reserveDailyAllowance } = require('./collection-runtime');

if (require.main === module) {
    try {
        const budgetFile = path.join(__dirname, '..', 'data', 'request_budget.json');
        if (!fs.existsSync(budgetFile)) {
            console.log('Initializing request budget: earlier traffic is unknown, so collection waits until the next JST day.');
        }
        const reservation = reserveDailyAllowance({
            budgetFile,
            reservationId: process.env.SCRAPER_RESERVATION_ID
        });
        console.log(`Reserved at most ${reservation.limit} requests for this run, including searches, redirects and retries.`);
    } catch (error) {
        console.error(`Cannot reserve request budget: ${error.message}`);
        process.exitCode = 1;
    }
}
