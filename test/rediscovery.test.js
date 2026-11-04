const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const {hasNewerPriceObservation, buildWorkList, main: runMain, parseItemJson} = require('../src/meta-scraper');
// Test clocks/reservations are local fixtures, never inherited from a live CI job.
const main = options => runMain({ jobStartedAt: null, reservationId: null, ...options });
const fixture = require('./fixtures/booth-item-7918308.json');
const id='7918308', today='2026-11-03';
const marker=()=>({id, unavailable:true,status:404,fetched_at:'2026-11-01'});
function setup(t, history=[{date:'2026-11-02',price:0,is_sale:false}]) {
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'rediscovery-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const dataDir=path.join(root,'data'),metaDir=path.join(root,'meta');
 const write=(base,key,obj)=>{const p=path.join(base,key.slice(0,3),key+'.json');fs.mkdirSync(path.dirname(p),{recursive:true});fs.writeFileSync(p,JSON.stringify(obj));return p};
 const raw=write(dataDir,id,{id,variations:{Free:history}}), meta=write(metaDir,id,marker());
 return {root,dataDir,metaDir,raw,meta,write};
}
test('newer unchanged free observation requests recheck, preserving input bytes',t=>{
 const x=setup(t),a=fs.readFileSync(x.raw),b=fs.readFileSync(x.meta);
 assert.equal(hasNewerPriceObservation(x.dataDir,id,marker(),today),true);
 assert.deepEqual(buildWorkList({...x,today}).map(x=>x.id),[id]);
 assert.deepEqual(fs.readFileSync(x.raw),a);assert.deepEqual(fs.readFileSync(x.meta),b);
});
test('confirmed 410 also qualifies; stale and same day observations do not',t=>{
 const x=setup(t);assert.equal(hasNewerPriceObservation(x.dataDir,id,{...marker(),status:410},today),true);
 for(const date of ['2026-10-31','2026-11-01']){x.write(x.dataDir,id,{id,variations:{x:[{date,price:10}]}});assert.deepEqual(buildWorkList({...x,today}),[]);}
});
test('malformed dates, future observations, invalid prices and wrong IDs cannot accelerate',t=>{
 const x=setup(t);
 for(const entry of [{date:'2026-11-04',price:1},{date:'2026-11-2',price:1},{date:'2026-02-30',price:1},{date:'2026-11-02',price:-1},{date:'2026-11-02',price:'1'},{date:'2026-11-02',price:1.5},{date:'2026-11-02',price:9007199254740992}]){
 x.write(x.dataDir,id,{id,variations:{x:[entry]}});assert.equal(hasNewerPriceObservation(x.dataDir,id,marker(),today),false);
 }
 for(const bad of [{id:123,variations:{x:[{date:'2026-11-02',price:1}]}},{id,variations:[]},{id,variations:{x:{date:'2026-11-02',price:1}}}]) {x.write(x.dataDir,id,bad);assert.equal(hasNewerPriceObservation(x.dataDir,id,marker(),today),false);}
});
test('only strict previous unavailable marker permits accelerated recheck',t=>{
 const x=setup(t);
 for(const patch of [{id:'9999999'},{unavailable:'true'},{status:'404'},{status:503},{name:'Normal item'},{fetched_at:'2026-02-30'},{fetched_at:'2026-11-03'},{fetched_at:'2026-11-04'}]) assert.equal(hasNewerPriceObservation(x.dataDir,id,{...marker(),...patch},today),false);
 fs.writeFileSync(x.raw,'{broken');assert.equal(hasNewerPriceObservation(x.dataDir,id,marker(),today),false);fs.unlinkSync(x.raw);assert.equal(hasNewerPriceObservation(x.dataDir,id,marker(),today),false);
});
test('checks every variation; one later saved observation enough for recheck only',t=>{
 const x=setup(t);x.write(x.dataDir,id,{id,variations:{old:[{date:'2026-11-01',price:1}],paid:[{date:'2026-11-02',price:5000}]}});
 assert.equal(hasNewerPriceObservation(x.dataDir,id,marker(),today),true);
});
test('recheck priority remains capped and monthly retry still works',t=>{
 const x=setup(t);x.write(x.dataDir,'9999999',{id:'9999999'});
 assert.deepEqual(buildWorkList({...x,today,runCap:1}).map(x=>x.id),[id]);
 x.write(x.dataDir,id,{id,variations:{x:[{date:'2026-10-01',price:1}]}});x.write(x.metaDir,id,{...marker(),fetched_at:'2026-10-01'});
 assert.deepEqual(buildWorkList({...x,today}).map(x=>x.id),['9999999',id]);
});
for(const outcome of ['success','unavailable','transient']) test(`normal collector ${outcome} response controls marker, never raw reappearance alone`,async t=>{
 const x=setup(t), raw=fs.readFileSync(x.raw), original=fs.readFileSync(x.meta);let calls=0;
 const result=await main({...x,now:()=>Date.parse('2026-11-03T01:00:00Z'),client:{check(){},finish(){},getAttemptCount(){return calls}},wait:async()=>{},log(){},logError(){},fetchMeta:async()=>{calls++;return outcome==='success'?{kind:'success',meta:parseItemJson(id,fixture)}:outcome==='unavailable'?{kind:'unavailable',id,status:410}:{kind:'failure',error:new Error('503 temporary')};}});
 assert.equal(calls,1);assert.deepEqual(fs.readFileSync(x.raw),raw);
 const after=JSON.parse(fs.readFileSync(x.meta));
 if(outcome==='success'){assert.equal(after.unavailable,undefined);assert.equal(after.name,fixture.name);assert.equal(result.metrics.success,1);}
 if(outcome==='unavailable'){assert.deepEqual(after,{id,unavailable:true,status:410,fetched_at:today});assert.deepEqual(buildWorkList({...x,today}),[]);}
 if(outcome==='transient'){assert.deepEqual(fs.readFileSync(x.meta),original);assert.equal(result.metrics.failures,1);}
});

test('transient rechecks cool down while normal work proceeds on repeated runs',async t=>{
 const x=setup(t);x.write(x.dataDir,'9999999',{id:'9999999'});const seen=[];
 const args={...x,runCap:1,now:()=>Date.parse('2026-11-03T01:00:00Z'),client:{check(){},finish(){}},wait:async()=>{},log(){},logError(){},fetchMeta:async key=>{seen.push(key);return {kind:'failure',error:new Error('503')};}};
 await main(args);await main(args);await main(args);
 assert.deepEqual(seen,[id,'9999999','9999999']);
 const state=JSON.parse(fs.readFileSync(path.join(x.metaDir,'recheck_state.json')));
 assert.deepEqual(state.entries[id],{failures:1,attempt_date:today,retry_after:'2026-11-04'});
 assert.equal(JSON.parse(fs.readFileSync(x.meta)).unavailable,true);
});
test('bounded fair allocation with cap one carries alternate group across runs',async t=>{
 const x=setup(t);x.write(x.dataDir,'8888888',{id:'8888888',variations:{v:[{date:'2026-11-02',price:1}]}});x.write(x.metaDir,'8888888',{...marker(),id:'8888888'});x.write(x.dataDir,'9999999',{id:'9999999'});const seen=[];
 const args={...x,runCap:1,now:()=>Date.parse('2026-11-03T01:00:00Z'),client:{check(){},finish(){}},wait:async()=>{},log(){},logError(){},fetchMeta:async key=>{seen.push(key);return {kind:'failure',error:new Error('temporary')};}};
 await main(args);await main(args);await main(args);
 assert.deepEqual(seen,[id,'9999999','8888888']);
});
test('cooldown grows 1,2,4,7 days and does not bypass monthly fallback',async t=>{
 const x=setup(t);for(const [date,retry,failures] of [['2026-11-03','2026-11-04',1],['2026-11-04','2026-11-06',2],['2026-11-06','2026-11-10',3],['2026-11-10','2026-11-17',4],['2026-11-17','2026-11-24',4]]){
 await main({...x,now:()=>Date.parse(date+'T01:00:00Z'),client:{check(){},finish(){}},wait:async()=>{},log(){},logError(){},fetchMeta:async()=>({kind:'failure',error:new Error('503')})});
 const state=JSON.parse(fs.readFileSync(path.join(x.metaDir,'recheck_state.json')));assert.deepEqual(state.entries[id],{failures,attempt_date:date,retry_after:retry});
 assert.deepEqual(buildWorkList({...x,today:date}),[]);
 }
 x.write(x.metaDir,id,{...marker(),fetched_at:'2026-10-01'});assert.deepEqual(buildWorkList({...x,today:'2026-11-18'}),[]);
});
test('recovery clears cooldown only on actual metadata success',async t=>{
 const x=setup(t),args={...x,client:{check(){},finish(){}},wait:async()=>{},log(){},logError(){}};
 await main({...args,now:()=>Date.parse('2026-11-03T01:00:00Z'),fetchMeta:async()=>({kind:'failure',error:new Error('503')})});
 await main({...args,now:()=>Date.parse('2026-11-04T01:00:00Z'),fetchMeta:async()=>({kind:'success',meta:parseItemJson(id,fixture)})});
 assert.deepEqual(JSON.parse(fs.readFileSync(path.join(x.metaDir,'recheck_state.json'))).entries,{});assert.equal(JSON.parse(fs.readFileSync(x.meta)).unavailable,undefined);
});
test('corrupt retry state fails closed before network and remains unchanged',async t=>{
 const x=setup(t),p=path.join(x.metaDir,'recheck_state.json');
 for(const raw of ['{broken',JSON.stringify({schema:1,next_group:'recheck',entries:{[id]:{failures:100,attempt_date:today,retry_after:'2026-12-03'}}}),JSON.stringify({schema:1,next_group:'recheck',entries:{[id]:{failures:1,attempt_date:today,retry_after:'2026-11-05'}}})]){
 fs.writeFileSync(p,raw);let calls=0;await assert.rejects(main({...x,now:()=>Date.parse('2026-11-03T01:00:00Z'),fetchMeta:async()=>{calls++;}}),/Invalid metadata recheck state/);assert.equal(calls,0);assert.equal(fs.readFileSync(p,'utf8'),raw);
 }
});
test('fair allocation alternates while preserving each ordinary queue order',t=>{
 const x=setup(t);for(const key of ['8888888','8888889']){x.write(x.dataDir,key,{id:key,variations:{v:[{date:'2026-11-02',price:1}]}});x.write(x.metaDir,key,{...marker(),id:key});}for(const key of ['9999997','9999998','9999999'])x.write(x.dataDir,key,{id:key});
 assert.deepEqual(buildWorkList({...x,today,runCap:6}).map(x=>x.id),[id,'9999999','8888888','9999998','8888889','9999997']);
});
test('interrupted recheck advances fairness and cools down uncertain request outcome',async t=>{
 const {CollectionStop}=require('../src/collection-runtime');const x=setup(t);x.write(x.dataDir,'9999999',{id:'9999999'});const seen=[];
 const args={...x,runCap:1,now:()=>Date.parse('2026-11-03T01:00:00Z'),client:{check(){},finish(){}},wait:async()=>{},log(){},logError(){}};
 const first=await main({...args,fetchMeta:async key=>{seen.push(key);throw new CollectionStop('circuit-breaker','injected circuit breaker');}});
 assert.equal(first.status,'paused');assert.equal(first.metrics.failures,0);assert.equal(first.metrics.success,0);
 const state=JSON.parse(fs.readFileSync(path.join(x.metaDir,'recheck_state.json')));assert.equal(state.next_group,'normal');assert.equal(state.entries[id].retry_after,'2026-11-04');
 await main({...args,fetchMeta:async key=>{seen.push(key);return {kind:'failure',error:new Error('503')};}});assert.deepEqual(seen,[id,'9999999']);assert.equal(JSON.parse(fs.readFileSync(x.meta)).unavailable,true);
});
test('deadline before any fetch does not claim attempted recheck or create cooldown',async t=>{
 const x=setup(t);let calls=0;
 const result=await main({...x,maxRunMs:0,now:()=>Date.parse('2026-11-03T01:00:00Z'),client:{check(){},finish(){}},wait:async()=>{},log(){},logError(){},fetchMeta:async()=>{calls++;}});
 assert.equal(result.status,'paused');assert.equal(calls,0);assert.equal(fs.existsSync(path.join(x.metaDir,'recheck_state.json')),false);
});
test('corrupt retry state finalizes real existing reservation with zero requests',async t=>{
 const {reserveDailyAllowance}=require('../src/collection-runtime');const x=setup(t),start=Date.parse('2026-11-03T01:00:00Z');const budgetFile=path.join(x.metaDir,'request_budget.json');
 fs.writeFileSync(budgetFile,JSON.stringify({date:today,requests:0,blockedUntil:0}));
 reserveDailyAllowance({budgetFile,reservationId:'corrupt-preflight',now:start,dailyLimit:100});fs.writeFileSync(path.join(x.metaDir,'recheck_state.json'),'{broken');let calls=0;
 await assert.rejects(main({...x,reservationId:'corrupt-preflight',now:()=>start,get:async()=>{calls++;}}),/Invalid metadata recheck state/);
 const budget=JSON.parse(fs.readFileSync(budgetFile));assert.equal(calls,0);assert.equal(budget.reservation.completed,true);assert.equal(budget.reservation.used,0);assert.equal(budget.requests,0);assert.equal(fs.readFileSync(path.join(x.metaDir,'recheck_state.json'),'utf8'),'{broken');
 assert.doesNotThrow(()=>reserveDailyAllowance({budgetFile,reservationId:'after-repair',now:start,dailyLimit:100}));
});
