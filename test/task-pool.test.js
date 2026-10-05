const assert = require('node:assert/strict');
const test = require('node:test');
const { runTaskPool } = require('../src/task-pool');

function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
}
const tick = () => new Promise(resolve => setImmediate(resolve));
const take = queue => () => queue.shift() || null;

test('default pool caps aggregate active tasks at five and drains all work', async () => {
    const gates = Array.from({ length: 12 }, deferred);
    const started = [];
    let active = 0;
    let maxActive = 0;
    const queue = gates.map((gate, key) => ({ key, run: async () => {
        started.push(key);
        active++;
        maxActive = Math.max(maxActive, active);
        await gate.promise;
        active--;
        return key;
    } }));
    const settled = [];
    const pending = runTaskPool({ nextTask: take(queue), onSettled: (task, result) => settled.push([task.key, result.value]) });
    assert.deepEqual(started, [0, 1, 2, 3, 4]);
    for (const gate of gates) {
        gate.resolve();
        await tick();
        assert.ok(active <= 5);
    }
    assert.deepEqual(await pending, { started: 12, completed: 12, maxActive: 5 });
    assert.equal(maxActive, 5);
    assert.equal(active, 0);
    assert.deepEqual(settled, gates.map((_, key) => [key, key]));
});

test('a settled slot refills immediately without waiting for the whole batch', async () => {
    const gates = Array.from({ length: 7 }, deferred);
    const started = [];
    const queue = gates.map((gate, key) => ({ key, run: () => { started.push(key); return gate.promise; } }));
    const pending = runTaskPool({ nextTask: take(queue) });
    gates[2].resolve();
    await tick();
    assert.deepEqual(started, [0, 1, 2, 3, 4, 5]);
    gates[5].resolve();
    await tick();
    assert.deepEqual(started, [0, 1, 2, 3, 4, 5, 6]);
    for (const gate of gates) gate.resolve();
    await pending;
});

test('async settlement persists before the slot can refill', async () => {
    const saved = deferred();
    const events = [];
    const queue = [1, 2].map(key => ({ key, run: async () => { events.push(`run:${key}`); return key; } }));
    const pending = runTaskPool({ concurrency: 1, nextTask: take(queue), onSettled: async task => {
        events.push(`save:${task.key}`);
        if (task.key === 1) await saved.promise;
        events.push(`saved:${task.key}`);
    } });
    await tick();
    assert.deepEqual(events, ['run:1', 'save:1']);
    saved.resolve();
    assert.deepEqual(await pending, { started: 2, completed: 2, maxActive: 1 });
    assert.deepEqual(events, ['run:1', 'save:1', 'saved:1', 'run:2', 'save:2', 'saved:2']);
});

test('stop prevents new tasks and drains every active task and handler', async () => {
    const gates = Array.from({ length: 6 }, deferred);
    const handler = deferred();
    let stop = false;
    let finished = false;
    const started = [];
    const settled = [];
    const queue = gates.map((gate, key) => ({ key, run: () => { started.push(key); return gate.promise; } }));
    const pending = runTaskPool({ nextTask: take(queue), shouldStop: () => stop, onSettled: async task => {
        if (task.key === 4) await handler.promise;
        settled.push(task.key);
    } }).then(value => { finished = true; return value; });
    stop = true;
    for (const gate of gates.slice(0, 5)) gate.resolve();
    await tick();
    assert.equal(finished, false);
    assert.deepEqual(started, [0, 1, 2, 3, 4]);
    handler.resolve();
    assert.deepEqual(await pending, { started: 5, completed: 5, maxActive: 5 });
    assert.deepEqual(settled, [0, 1, 2, 3, 4]);
    assert.equal(queue.length, 1);
});

test('an initial stop never asks for or starts a task', async () => {
    assert.deepEqual(await runTaskPool({ nextTask: () => assert.fail('must not select work'), shouldStop: () => true }),
        { started: 0, completed: 0, maxActive: 0 });
});

test('temporarily empty queue waits for search settlement to produce details', async () => {
    const search = deferred();
    const started = [];
    const queue = [{ key: 'search', run: async () => { started.push('search'); await search.promise; return ['101', '102']; } }];
    const pending = runTaskPool({ nextTask: take(queue), onSettled: (task, result) => {
        if (task.key === 'search') {
            for (const key of result.value) queue.push({ key, run: async () => started.push(key) });
        }
    } });
    await tick();
    assert.deepEqual(started, ['search']);
    search.resolve();
    assert.deepEqual(await pending, { started: 3, completed: 3, maxActive: 2 });
    assert.deepEqual(started, ['search', '101', '102']);
});

test('task rejection and synchronous throws are passed to settlement and do not abort', async () => {
    const failure = new Error('detail failed');
    const queue = [
        { key: 'async', run: async () => { throw failure; } },
        { key: 'sync', run: () => { throw failure; } },
        { key: 'ok', run: async () => 42 }
    ];
    const results = new Map();
    const counts = await runTaskPool({ concurrency: 1, nextTask: take(queue), onSettled: (task, result) => results.set(task.key, result) });
    assert.deepEqual(counts, { started: 3, completed: 3, maxActive: 1 });
    assert.deepEqual(results.get('async'), { status: 'rejected', reason: failure });
    assert.deepEqual(results.get('sync'), { status: 'rejected', reason: failure });
    assert.deepEqual(results.get('ok'), { status: 'fulfilled', value: 42 });
});

test('fatal settlement stops refills and rejects only after all active handlers drain', async () => {
    const taskGates = Array.from({ length: 3 }, deferred);
    const handlerGate = deferred();
    const failure = new Error('checkpoint failed');
    const started = [];
    const saved = [];
    let finished = false;
    const queue = taskGates.map((gate, key) => ({ key, run: () => { started.push(key); return gate.promise; } }));
    const pending = runTaskPool({ concurrency: 2, nextTask: take(queue), onSettled: async task => {
        if (task.key === 0) throw failure;
        await handlerGate.promise;
        saved.push(task.key);
    } });
    const checked = assert.rejects(pending, error => error === failure).then(() => { finished = true; });
    taskGates[0].resolve();
    await tick();
    assert.equal(finished, false);
    assert.deepEqual(started, [0, 1]);
    taskGates[1].resolve();
    await tick();
    assert.equal(finished, false);
    handlerGate.resolve();
    await checked;
    assert.deepEqual(saved, [1]);
    assert.deepEqual(started, [0, 1]);
});

test('selector and stop callback exceptions drain active tasks before rejecting', async () => {
    for (const source of ['nextTask', 'shouldStop']) {
        const gate = deferred();
        const failure = new Error(`${source} failed`);
        let selected = false;
        let settled = false;
        let finished = false;
        const pending = runTaskPool({
            nextTask: () => {
                if (selected) throw failure;
                selected = true;
                return { key: 'active', run: () => gate.promise };
            },
            shouldStop: () => { if (source === 'shouldStop' && selected) throw failure; return false; },
            onSettled: () => { settled = true; }
        });
        const checked = assert.rejects(pending, error => error === failure).then(() => { finished = true; });
        await tick();
        assert.equal(finished, false);
        assert.equal(settled, false);
        gate.resolve();
        await checked;
        assert.equal(settled, true);
    }
});

test('duplicate active keys fail without running the duplicate, then drain', async () => {
    const gate = deferred();
    const started = [];
    const queue = [
        { key: '101', run: () => { started.push('first'); return gate.promise; } },
        { key: '101', run: () => started.push('duplicate') }
    ];
    let finished = false;
    const pending = runTaskPool({ nextTask: take(queue) });
    const checked = assert.rejects(pending, /Duplicate active task key: 101/).then(() => { finished = true; });
    await tick();
    assert.equal(finished, false);
    assert.deepEqual(started, ['first']);
    gate.resolve();
    await checked;
});

test('a key can be reused after its prior task and handler have settled', async () => {
    const queue = [1, 2].map(value => ({ key: 'search', run: async () => value }));
    const values = [];
    assert.deepEqual(await runTaskPool({ concurrency: 1, nextTask: take(queue), onSettled: (_, result) => values.push(result.value) }),
        { started: 2, completed: 2, maxActive: 1 });
    assert.deepEqual(values, [1, 2]);
});

test('duplicate protection lasts through an unfinished settlement handler', async () => {
    const firstSaved = deferred();
    const anotherFinished = deferred();
    const started = [];
    const queue = [
        { key: 'product', run: async () => { started.push('product'); } },
        { key: 'other', run: () => { started.push('other'); return anotherFinished.promise; } },
        { key: 'product', run: async () => { started.push('duplicate'); } }
    ];
    let finished = false;
    const pending = runTaskPool({ concurrency: 2, nextTask: take(queue), onSettled: async task => {
        if (task.key === 'product') await firstSaved.promise;
    } });
    const checked = assert.rejects(pending, /Duplicate active task key: product/).then(() => { finished = true; });
    await tick();
    anotherFinished.resolve();
    await tick();
    assert.equal(finished, false);
    assert.deepEqual(started, ['product', 'other']);
    firstSaved.resolve();
    await checked;
});

test('simultaneous immediate completions never lose a wake or exceed the cap', async () => {
    const queue = Array.from({ length: 1000 }, (_, key) => ({ key, run: async () => key }));
    let settled = 0;
    assert.deepEqual(await runTaskPool({ nextTask: take(queue), onSettled: () => { settled++; } }),
        { started: 1000, completed: 1000, maxActive: 5 });
    assert.equal(settled, 1000);
});

test('release hook runs after settlement and allows the selector to reuse the key', async () => {
    const saved = deferred();
    const events = [];
    let followup;
    const first = { key: 'product', run: async () => { events.push('first:run'); } };
    const queue = [first];
    const pending = runTaskPool({
        concurrency: 1,
        nextTask: () => {
            if (queue.length) return queue.shift();
            if (first.poolReleased && !followup) {
                followup = { key: 'product', run: async () => { events.push('followup:run'); } };
                return followup;
            }
            return null;
        },
        onSettled: async task => {
            if (task === first) {
                events.push('first:saving');
                await saved.promise;
                events.push('first:saved');
            }
        },
        onReleased: task => {
            events.push(task === first ? 'first:released' : 'followup:released');
            task.poolReleased = true;
        }
    });
    await tick();
    assert.equal(first.poolReleased, undefined);
    assert.deepEqual(events, ['first:run', 'first:saving']);
    saved.resolve();
    assert.deepEqual(await pending, { started: 2, completed: 2, maxActive: 1 });
    assert.deepEqual(events, ['first:run', 'first:saving', 'first:saved', 'first:released', 'followup:run', 'followup:released']);
    assert.equal(followup.poolReleased, true);
});

test('release hook exceptions prevent refills and drain remaining tasks and handlers', async () => {
    const gates = Array.from({ length: 3 }, deferred);
    const saved = deferred();
    const failure = new Error('release failed');
    const started = [];
    const released = [];
    const queue = gates.map((gate, key) => ({ key, run: () => { started.push(key); return gate.promise; } }));
    let finished = false;
    const pending = runTaskPool({
        concurrency: 2,
        nextTask: take(queue),
        onSettled: async task => { if (task.key === 1) await saved.promise; },
        onReleased: task => { released.push(task.key); if (task.key === 0) throw failure; }
    });
    const checked = assert.rejects(pending, error => error === failure).then(() => { finished = true; });
    gates[0].resolve();
    await tick();
    assert.equal(finished, false);
    assert.deepEqual(released, [0]);
    assert.deepEqual(started, [0, 1]);
    gates[1].resolve();
    await tick();
    assert.equal(finished, false);
    assert.deepEqual(released, [0]);
    saved.resolve();
    await checked;
    assert.deepEqual(released, [0, 1]);
    assert.deepEqual(started, [0, 1]);
});

test('release hooks reject thenables and consume their rejection', async () => {
    for (const onReleased of [
        async () => {},
        async () => { throw new Error('async release rejected'); },
        () => ({ then: (_, reject) => reject(new Error('custom thenable rejected')) })
    ]) {
        const started = [];
        const queue = [0, 1].map(key => ({ key, run: async () => { started.push(key); } }));
        await assert.rejects(runTaskPool({ concurrency: 1, nextTask: take(queue), onReleased }), /onReleased must be synchronous/);
        await tick(); // node:test would fail if the invalid hook leaked a rejection.
        assert.deepEqual(started, [0]);
    }
});

test('concurrency must be an integer from one through five', async () => {
    for (const concurrency of [0, -1, 6, 1.5, NaN, Infinity, '5', null]) {
        await assert.rejects(runTaskPool({ concurrency, nextTask: () => null }), /integer between 1 and 5/);
    }
    for (const concurrency of [1, 2, 3, 4, 5]) {
        assert.deepEqual(await runTaskPool({ concurrency, nextTask: () => null }), { started: 0, completed: 0, maxActive: 0 });
    }
});

test('invalid callbacks and malformed task definitions fail closed', async () => {
    await assert.rejects(runTaskPool(), /must be functions/);
    for (const option of ['nextTask', 'onSettled', 'onReleased', 'shouldStop']) {
        await assert.rejects(runTaskPool({ nextTask: () => null, [option]: null }), /must be functions/);
    }
    for (const task of [undefined, false, {}, { key: 'x' }, { run: async () => {} }, { key: null, run: async () => {} }]) {
        await assert.rejects(runTaskPool({ nextTask: () => task }), /task with a key and run function, or null/);
    }
});
