const SCHEDULE_HOURS = [0, 6, 12, 18];
const MAX_EXECUTION_TIME_MS = 5 * 60 * 60 * 1000;

function getStopTargetTime(startTime) {
    const now = new Date(startTime);
    const currentHour = now.getHours();
    let nextHour = SCHEDULE_HOURS.find(h => h > currentHour);
    const nextRun = new Date(now);

    if (nextHour === undefined) {
        nextHour = SCHEDULE_HOURS[0];
        nextRun.setDate(nextRun.getDate() + 1);
    }
    nextRun.setHours(nextHour, 0, 0, 0);

    const targetStopBeforeNextRun = new Date(nextRun.getTime() - 30 * 60 * 1000);
    const hardExecutionLimit = new Date(startTime + MAX_EXECUTION_TIME_MS);

    return targetStopBeforeNextRun < hardExecutionLimit ? targetStopBeforeNextRun : hardExecutionLimit;
}

function test(timeStr) {
    const startTime = new Date(timeStr).getTime();
    const stopTime = getStopTargetTime(startTime);
    console.log(`Start: ${new Date(startTime).toLocaleString()} -> Stop: ${new Date(stopTime).toLocaleString()}`);
}

console.log("Testing timeout logic:");
test("2026-02-10T14:00:00"); // Expected stop: 17:30 (next run 18:00)
test("2026-02-10T01:00:00"); // Expected stop: 05:30 (next run 06:00)
test("2026-02-10T19:00:00"); // Expected stop: 23:30 (next run 00:00)
test("2026-02-10T12:30:00"); // Expected stop: 17:30 (5 hours limit)
