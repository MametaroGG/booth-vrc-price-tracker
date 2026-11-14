const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const runtime = require('../src/collection-runtime');
const NOW=Date.parse('2026-11-14T01:00:00Z');
function fixture(t) {
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'ledger-writers-'));
 t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const budgetFile=path.join(dir,'budget.json');
 runtime.writeJson(budgetFile,{date:runtime.jstDate(NOW),requests:0,blockedUntil:0});
 runtime.reserveDailyAllowance({budgetFile,reservationId:'fixture',now:NOW});
 let calls=0;
 const make=(get=async()=>{calls++;return {status:200};})=>runtime.createRequestClient({budgetFile,reservationId:'fixture',now:()=>NOW,deadline:NOW+100000,get});
 return {dir,budgetFile,make,calls:()=>calls,read:()=>fs.readFileSync(budgetFile,'utf8')};
}
test('external cooldown edit cannot be overwritten by stale finish', t=>{
 const f=fixture(t), stale=f.make();
 const b=JSON.parse(f.read());b.blockedUntil=NOW+900000;runtime.writeJson(f.budgetFile,b);
 const remote=f.read();
 assert.throws(()=>stale.finish(),/changed since/);
 assert.equal(stale.getBudget().reservation.completed,false);
 assert.equal(f.read(),remote);
});
test('stale request start fails before mock transport after external accounting change',async t=>{
 const f=fixture(t), a=f.make();
 const b=JSON.parse(f.read());b.requests=1;b.reservation.used=1;runtime.writeJson(f.budgetFile,b);
 const before=f.read();
 await assert.rejects(a.get('https://example.invalid/b'),/changed since/);
 assert.equal(f.calls(),0); assert.equal(f.read(),before);
});
for(const mutation of ['replace-id','remove','corrupt']) test('finish refuses external '+mutation,t=>{
 const f=fixture(t), a=f.make();
 if(mutation==='remove') fs.unlinkSync(f.budgetFile);
 else if(mutation==='corrupt') fs.writeFileSync(f.budgetFile,'not-json');
 else {const b=JSON.parse(f.read());b.reservation.id='different';runtime.writeJson(f.budgetFile,b);}
 const before=fs.existsSync(f.budgetFile)?f.read():null;
 assert.throws(()=>a.finish(),/changed since/);
 assert.equal(fs.existsSync(f.budgetFile)?f.read():null,before);
});
test('other-process lock blocks reserve and finish without being stolen',t=>{
 const f=fixture(t), a=f.make(), lock=f.budgetFile+'.writer-lock';
 const child=spawnSync(process.execPath,['-e',"require('node:fs').mkdirSync(process.argv[1])",lock]);
 assert.equal(child.status,0);
 const before=f.read();
 assert.throws(()=>a.finish(),/EEXIST/);
 assert.throws(()=>runtime.reserveDailyAllowance({budgetFile:f.budgetFile,reservationId:'new',now:NOW}),/EEXIST/);
 assert.ok(fs.existsSync(lock));assert.equal(f.read(),before);
});
test('writer failure releases its own lock but not another writers data',t=>{
 const f=fixture(t), a=f.make();
 fs.writeFileSync(f.budgetFile,f.read()+'\n');
 assert.throws(()=>a.finish(),/changed since/);
 assert.equal(fs.existsSync(f.budgetFile+'.writer-lock'),false);
});
