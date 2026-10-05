// One shared pool for every collection lane. HTTP pacing and request accounting
// belong to the request client, not to individual tasks or batches here.
async function runTaskPool({
    concurrency = 5, nextTask, onSettled = () => {}, onReleased = () => {}, shouldStop = () => false
} = {}) {
    if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > 5) {
        throw new RangeError('concurrency must be an integer between 1 and 5');
    }
    if (typeof nextTask !== 'function' || typeof onSettled !== 'function' ||
        typeof onReleased !== 'function' || typeof shouldStop !== 'function') {
        throw new TypeError('nextTask, onSettled, onReleased and shouldStop must be functions');
    }

    const activeKeys = new Set();
    const counts = { started: 0, completed: 0, maxActive: 0 };
    let stopped = false;
    let failed = false;
    let failure;
    let wake;

    function fail(error) {
        if (!failed) {
            failed = true;
            failure = error;
        }
    }

    async function execute(task, key) {
        let result;
        try {
            result = { status: 'fulfilled', value: await task.run() };
        } catch (reason) {
            // An ordinary task failure is a result for the caller to checkpoint.
            result = { status: 'rejected', reason };
        }
        try {
            await onSettled(task, result);
        } catch (error) {
            fail(error);
        } finally {
            // Hold the slot and duplicate guard until the checkpoint is saved.
            counts.completed++;
            activeKeys.delete(key);
            try {
                // Requeue eligibility must change only after the active key is
                // released, synchronously before any selector can refill it.
                const released = onReleased(task);
                if (released && typeof released.then === 'function') {
                    // An accidentally async hook must not leak a rejection.
                    Promise.resolve(released).catch(() => {});
                    throw new TypeError('onReleased must be synchronous and must not return a thenable');
                }
            } catch (error) {
                fail(error);
            }
            if (wake) {
                const resolve = wake;
                wake = undefined;
                resolve();
            }
        }
    }

    while (true) {
        try {
            while (!failed && !stopped && activeKeys.size < concurrency) {
                if (shouldStop()) {
                    stopped = true;
                    break;
                }
                const task = nextTask();
                // Work can appear later, for example when a search finishes.
                if (task === null) break;
                if (!task || task.key == null || typeof task.run !== 'function') {
                    throw new TypeError('nextTask must return a task with a key and run function, or null');
                }
                const key = task.key;
                if (activeKeys.has(key)) throw new Error(`Duplicate active task key: ${String(key)}`);
                activeKeys.add(key);
                counts.started++;
                counts.maxActive = Math.max(counts.maxActive, activeKeys.size);
                // execute handles task/handler failures itself and releases its
                // slot only after the handler finishes. No HTTP starts here.
                void execute(task, key);
            }
        } catch (error) {
            fail(error);
        }
        if (activeKeys.size === 0) break;
        // A single completion signal avoids repeatedly attaching Promise.race
        // listeners to a slow task while many quicker tasks refill other slots.
        await new Promise(resolve => { wake = resolve; });
    }

    if (failed) throw failure;
    return counts;
}

module.exports = { runTaskPool };
