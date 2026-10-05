// Legacy entry point retained, now checking the actual production deadline code.
const assert = require('node:assert/strict');
const { getStopTargetTime } = require('../src/collection-runtime');

for (const start of ['2026-02-10T14:00:00+09:00', '2026-02-10T01:00:00+09:00',
    '2026-02-10T19:00:00+09:00', '2026-02-10T12:30:00+09:00', '2026-10-04T23:32:00+09:00']) {
    const startTime = Date.parse(start);
    assert.equal(getStopTargetTime(startTime).getTime(), startTime + 5 * 60 * 60 * 1000);
}
console.log('Production deadline checks passed. Run npm test for full offline coverage.');
