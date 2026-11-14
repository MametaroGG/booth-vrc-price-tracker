const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {createRequestClient, reserveDailyAllowance, writeJson, jstDate} = require('../src/collection-runtime');
const NOW = Date.parse('2026-11-14T01:00:00Z');
for (const limit of [null, 8]) {
  for (const operation of ['writeFileSync', 'renameSync']) {
    test(`finish retains unresolved state on ${operation} failure, limit=${limit}`, async t => {
      const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'finish-checkpoint-'));
      t.after(() => fs.rmSync(dir, {recursive:true, force:true}));
      const file = path.join(dir, 'budget.json');
      writeJson(file, {date:jstDate(NOW), requests:0, blockedUntil:0, migration:{reason:'retain'}});
      reserveDailyAllowance({budgetFile:file, reservationId:'fixture', now:NOW, dailyLimit:limit});
      let calls = 0;
      const client = createRequestClient({budgetFile:file, reservationId:'fixture', now:()=>NOW,
        dailyLimit:limit, deadline:NOW+100000, get:async()=>{calls++; return {status:200};}});
      await client.get('https://example.invalid/fixture'); // injected function only, never network
      const before = client.getBudget();
      const original = fs[operation];
      const mock = t.mock.method(fs, operation, function(...args) {
        if (args[0] === file+'.tmp') throw Object.assign(new Error('fixture EROFS'), {code:'EROFS'});
        return original.apply(this,args);
      });
      for (let i=0;i<2;i++) {
        assert.throws(()=>client.finish(), /Cannot persist request budget/);
        assert.deepEqual(client.getBudget(), before);
        assert.equal(JSON.parse(fs.readFileSync(file)).reservation.completed, false);
      }
      await assert.rejects(client.get('https://example.invalid/no-send'), {reason:'finished'});
      assert.equal(calls,1);
      mock.mock.restore();
      client.finish();
      assert.equal(client.getBudget().reservation.completed,true);
      assert.equal(client.getBudget().requests,1);
      assert.deepEqual(client.getBudget().migration,{reason:'retain'});
      const persisted = fs.readFileSync(file,'utf8');
      client.finish();
      assert.equal(fs.readFileSync(file,'utf8'),persisted);
    });
  }
}
test('elapsed time cannot clear unresolved unlimited zero-used reservation', t => {
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'hold-preserve-'));
  t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  const file=path.join(dir,'budget.json');
  writeJson(file,{date:jstDate(NOW),requests:90870,blockedUntil:0,
    reservation:{id:'43541811924-1',mode:'unlimited',limit:null,used:0,completed:false}});
  const bytes=fs.readFileSync(file,'utf8');
  for (const days of [0,1,30,365]) {
    assert.throws(()=>reserveDailyAllowance({budgetFile:file,reservationId:'next',now:NOW+days*86400000}),/unresolved/);
    assert.equal(fs.readFileSync(file,'utf8'),bytes);
  }
});
