const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawnSync}=require('node:child_process');
const rt=require('../src/collection-runtime');
const now=Date.parse('2026-11-14T01:00:00Z');
function fixture(t){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'session-owner-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));const budgetFile=path.join(dir,'budget.json');rt.writeJson(budgetFile,{date:rt.jstDate(now),requests:0,blockedUntil:0});rt.reserveDailyAllowance({budgetFile,reservationId:'same',now});return {budgetFile,reservationId:'same',now:()=>now,deadline:now+100000};}
test('review race: second owner forbidden, early finish cannot lose late 429',async t=>{
 const opts=fixture(t);let rejectHttp,started;const ready=new Promise(r=>started=r);
 const a=rt.createRequestClient({...opts,get:()=>{started();return new Promise((_,r)=>rejectHttp=r);}});
 const pending=a.get('https://example.invalid/mock').catch(e=>e);await ready;
 assert.throws(()=>rt.createRequestClient({...opts,get:()=>{throw Error('no network');}}),/EEXIST/);
 assert.throws(()=>a.finish(),e=>e.reason==='drain-pending');
 assert.equal(JSON.parse(fs.readFileSync(opts.budgetFile)).reservation.completed,false);
 assert.ok(fs.existsSync(opts.budgetFile+'.session-lock'));
 rejectHttp({response:{status:429,headers:{'retry-after':'3600'}}});await pending;
 a.finish();const saved=JSON.parse(fs.readFileSync(opts.budgetFile));
 assert.equal(saved.blockedUntil,now+3600000);assert.equal(saved.reservation.completed,true);
 assert.equal(fs.existsSync(opts.budgetFile+'.session-lock'),false);
 assert.throws(()=>rt.reserveDailyAllowance({budgetFile:opts.budgetFile,reservationId:'next',now}),/paused until/);
});
test('immediate finish accounts for queued requests before first microtask',async t=>{
 const opts=fixture(t);let calls=0;const a=rt.createRequestClient({...opts,get:async()=>{calls++;return {status:200};}});
 const p=a.get('https://example.invalid/mock').catch(e=>e);
 assert.throws(()=>a.finish(),e=>e.reason==='drain-pending');await p;a.finish();assert.equal(calls,0);
});
test('owner exclusion spans processes; crash lock is never auto-stolen',t=>{
 const opts=fixture(t);const a=rt.createRequestClient({...opts,get:async()=>({status:200})});
 const modulePath=require.resolve('../src/collection-runtime');
 const child=spawnSync(process.execPath,['-e',`const r=require(process.argv[1]);try{r.createRequestClient({budgetFile:process.argv[2],reservationId:'same',now:()=>${now},deadline:${now+10000},get:()=>{throw Error('must not call')}});process.exit(9)}catch(e){if(e.code!=='EEXIST')throw e}`,modulePath,opts.budgetFile]);
 assert.equal(child.status,0,child.stderr.toString());
 assert.throws(()=>rt.reserveDailyAllowance({budgetFile:opts.budgetFile,reservationId:'next',now:now+365*86400000}),/owner/);
 a.finish();
});
test('finish write failure retains ownership until successful checkpoint',t=>{
 const opts=fixture(t), a=rt.createRequestClient({...opts,get:async()=>({status:200})});
 fs.mkdirSync(opts.budgetFile+'.writer-lock');
 assert.throws(()=>a.finish(),/EEXIST/);assert.ok(fs.existsSync(opts.budgetFile+'.session-lock'));
 fs.rmdirSync(opts.budgetFile+'.writer-lock');a.finish();
 assert.equal(fs.existsSync(opts.budgetFile+'.session-lock'),false);
});
test('unreserved inflight client blocks transition to reservation and preserves late429',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'unreserved-owner-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const budgetFile=path.join(dir,'b');rt.writeJson(budgetFile,{date:rt.jstDate(now),requests:0,blockedUntil:0});
 let rejectHttp,started;const ready=new Promise(r=>started=r);
 const legacy=rt.createRequestClient({budgetFile,now:()=>now,deadline:now+10000,get:()=>{started();return new Promise((_,r)=>rejectHttp=r);}});
 const p=legacy.get('https://example.invalid/mock').catch(e=>e);await ready;
 assert.throws(()=>rt.reserveDailyAllowance({budgetFile,reservationId:'reserved',now}),/owner/);
 assert.throws(()=>rt.createRequestClient({budgetFile,now:()=>now,deadline:now+10000,get:()=>{throw Error('no send')}}),/owner|EEXIST/);
 assert.throws(()=>legacy.finish(),e=>e.reason==='drain-pending');
 rejectHttp({response:{status:429,headers:{'retry-after':'3600'}}});await p;legacy.finish();
 assert.equal(JSON.parse(fs.readFileSync(budgetFile)).blockedUntil,now+3600000);
 assert.throws(()=>rt.reserveDailyAllowance({budgetFile,reservationId:'next',now}),/paused until/);
});
