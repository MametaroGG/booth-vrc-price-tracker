/* Bounded execution of final emitted guard/cache code with local-file, mock I/O.
 * No network, browser, provider, deployment, source or permission authority.
 */
'use strict';
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert/strict');
const {webcrypto,createHash}=require('crypto');
const [site,pin,output]=process.argv.slice(2);
const sha=b=>createHash('sha256').update(b).digest('hex');
const manifestRaw=fs.readFileSync(path.join(site,'snapshot-manifest.json'));
assert.equal(sha(manifestRaw),pin);
const manifest=JSON.parse(manifestRaw),checks=[];
function check(name,fn){return Promise.resolve().then(fn).then(()=>checks.push(name));}
function bytes(name){assert(Object.hasOwn(manifest.files,name),'Unbound fixture read');const raw=fs.readFileSync(path.join(site,name));assert.equal(sha(raw),manifest.files[name]);return raw;}
const page=bytes('index.html').toString(),cacheCode=bytes('catalog-cache.js').toString();
const payload=JSON.parse(page.match(/(?:^|\n)(?:<script>)?const P\s*=\s*(\{[^\n]*\});/)[1]);
// Only the synthetic harness clock/markers track the validated snapshot day.
const markerDay=payload.stats.max_date;assert(/^\d{4}-\d{2}-\d{2}$/.test(markerDay));
const markerNow=Date.parse(markerDay+'T12:00:00.000Z');assert(Number.isFinite(markerNow));
const staleMarkerDay=new Date(markerNow-86400000).toISOString().slice(0,10);
const futureMarkerDay=new Date(markerNow+86400000).toISOString().slice(0,10);
class SnapshotFixtureDate extends Date { static now(){return markerNow;} }
const pub=page.match(/\/\/ PUBLICATION_RUNTIME_START:.*?\/\/ PUBLICATION_RUNTIME_END/s)[0];
const vis=page.match(/\/\/ VISIBILITY_POLICY_START:.*?\/\/ VISIBILITY_POLICY_END/s)[0];
const allAssets=['lists_full.json','shop_digest.json',...Array.from({length:24},(_,i)=>'search_index_'+i+'.json')];
function harness(opts={}){
 const calls=[];let afterFetch=null;
 const env={Date:SnapshotFixtureDate,URL,AbortController,TextEncoder,TextDecoder,Response,crypto:webcrypto,Uint8Array,ArrayBuffer,setTimeout,clearTimeout,console:{log(){},warn(){},error(){}},location:{href:'https://synthetic.invalid/site/index.html'},document:{querySelectorAll(){return []}},CustomEvent:class {constructor(type,options){this.type=type;this.detail=options.detail;}},dispatchEvent(){}};
 env.window=env;env.caches={async open(){return {async match(){return undefined},async put(){},async keys(){return []},async delete(){return true}}}};
 env.fetch=async(url,options={})=>{
  const u=new URL(url,env.location.href);assert.equal(u.origin,'https://synthetic.invalid');assert(u.pathname.startsWith('/site/'));const name=u.pathname.slice('/site/'.length);
  calls.push({name,url:u.href,cache:options.cache,signal:options.signal});
  if(options.signal?.aborted)throw Error('aborted mock fetch');
  let b=name==='snapshot-manifest.json'?manifestRaw:bytes(name);
  if(opts.transform)b=opts.transform(name,b);
  if(afterFetch)await afterFetch(name);
  return new Response(b,{status:opts.status||200});
 };
 const ctx=vm.createContext(env);vm.runInContext('const P = '+JSON.stringify(payload)+';\n'+pub+'\n'+vis+'\n'+cacheCode,ctx);
 return {env,ctx,calls,run:code=>vm.runInContext(code,ctx),after:fn=>{afterFetch=fn}};
}
(async()=>{
 await check('frozen-bootstrap-statistics-visibility-revision',()=>{
  const h=harness(),previous=h.run('JSON.stringify([P.stats,P.visibility,P.publication_revision])');
  h.run("P.stats={total:1}; P.visibility={schema:1,hidden_ids:[]}; P.publication_revision='bad'; P.stats.total=1");
  assert.throws(()=>h.run('P.visibility.hidden_ids.pop()'), /Cannot delete/);
  assert.equal(h.run('JSON.stringify([P.stats,P.visibility,P.publication_revision])'),previous);
  assert.equal(h.run('Object.isFrozen(P.visibility.hidden_ids)'),true);
  assert.equal(h.run("filterVisibleLists({stats:{total:1},visibility:{hidden_ids:[]},publication_revision:'bad'}).stats.total"),payload.stats.total);
 });
 await check('successful-metadata-cannot-restore-snapshot-hidden',()=>{
  const h=harness(),id=payload.visibility.hidden_ids[0];h.env.BoopaVisibility.acceptMeta(id,{id,name:'synthetic success',fetched_at:markerDay});assert.equal(h.env.BoopaVisibility.isHidden(id),true);
  const filtered=h.env.BoopaVisibility.filter([{id},[id,'synthetic'],{id:'1'}]);assert.equal(filtered.length,1);
 });
 for(const name of allAssets){
  await check('exact-asset:'+name,async()=>{const h=harness();const value=await h.env.BoopaPublication.readJSON(name);assert.deepEqual(JSON.parse(JSON.stringify(value)),JSON.parse(bytes(name)));assert.equal(h.calls.length,1);assert.equal(new URL(h.calls[0].url).searchParams.get('__publication'),payload.publication_revision);assert.equal(h.calls[0].cache,'no-store');});
  await check('altered-asset-refused:'+name,async()=>{const h=harness({transform:(n,b)=>Buffer.concat([b,Buffer.from(' ')])});await assert.rejects(()=>h.env.BoopaPublication.readJSON(name),/revision mismatch/);});
 }
 await check('unbound-asset-refused-before-fetch',async()=>{const h=harness();await assert.rejects(()=>h.env.BoopaPublication.readJSON('private-source.json'),/Unbound/);assert.equal(h.calls.length,0);});
 await check('hash-unavailable-refused',async()=>{const h=harness();h.env.crypto=undefined;await assert.rejects(()=>h.env.BoopaPublication.readJSON('lists_full.json'),/verification unavailable/);});
 await check('oversize-asset-refused',async()=>{const h=harness({transform:()=>Buffer.alloc(32*1024*1024+1)});await assert.rejects(()=>h.env.BoopaPublication.readJSON('lists_full.json'),/revision mismatch/);});
 await check('http-unavailable-refused',async()=>{const h=harness({status:404});await assert.rejects(()=>h.env.BoopaPublication.readJSON('lists_full.json'),/unavailable/);});
 await check('aborted-asset-refused',async()=>{const h=harness(),c=new AbortController();c.abort();await assert.rejects(()=>h.env.BoopaPublication.readJSON('lists_full.json',{signal:c.signal}),/aborted/);});
 await check('exact-catalog-accepted',async()=>{assert.equal(await harness().env.BoopaPublication.acceptCatalog(manifest),true);});
 const changes=[m=>m.publication_composition.composition_id='0'.repeat(64),m=>m.catalog_core.rows++,m=>m.catalog_core.part_rows[0]++,m=>m.catalog_core.format='unknown',m=>m.files['search-core/core_0.json']='0'.repeat(64),m=>m.files['search-core/images_511.json']='0'.repeat(64),m=>m.files['search_index_23.json']='0'.repeat(64)];
 for(let i=0;i<changes.length;i++)await check('catalog-tuple-mutation-refused:'+i,async()=>{const m=structuredClone(manifest);changes[i](m);assert.equal(await harness().env.BoopaPublication.acceptCatalog(m),false);});
 let visibleId;
 await check('all24-exact-core-shards-unique-visible-population',async()=>{
  const h=harness(),reader=h.env.createBoopaCatalogReader(h.env),ids=new Set();assert(await reader.begin());assert.equal(reader.isCore(),true);
  for(let i=0;i<24;i++){const rows=await reader.read(i);assert.equal(rows.length,manifest.catalog_core.part_rows[i]);for(const row of rows){assert(!ids.has(row[0]));assert(!h.env.BoopaVisibility.isHidden(row[0]));ids.add(row[0]);if(!visibleId)visibleId=row[0];}}
  assert.equal(ids.size,payload.stats.total);assert(h.calls.every(c=>c.cache==='no-store'));
 });
 await check('mutated-manifest-no-unverified-fallback',async()=>{
  const h=harness({transform:(name,b)=>{if(name!=='snapshot-manifest.json')return b;const m=JSON.parse(b);m.catalog_core.rows++;return Buffer.from(JSON.stringify(m));}}),reader=h.env.createBoopaCatalogReader(h.env);
  assert.equal(await reader.begin(),null);await assert.rejects(()=>reader.read(0),/publication catalog unavailable/);assert.deepEqual(h.calls.map(c=>c.name),['snapshot-manifest.json']);
 });
 await check('mutated-core-no-fallback',async()=>{const h=harness({transform:(n,b)=>n==='search-core/core_0.json'?Buffer.concat([b,Buffer.from(' ')]):b}),reader=h.env.createBoopaCatalogReader(h.env);await assert.rejects(()=>reader.read(0),/revision mismatch/);assert(!h.calls.some(c=>c.name.startsWith('search_index_')));});
 await check('runtime-hidden-core-row-filter',async()=>{const h=harness();h.run('runtimeHiddenIds.add('+JSON.stringify(visibleId)+')');const reader=h.env.createBoopaCatalogReader(h.env);const rows=await reader.read(0);assert(!rows.some(r=>r[0]===visibleId));assert.equal(rows.length,manifest.catalog_core.part_rows[0]-1);});
 await check('snapshot-hidden-image-no-fetch',async()=>{const h=harness(),reader=h.env.createBoopaCatalogReader(h.env);assert.equal(await reader.image(payload.visibility.hidden_ids[0]),null);assert.equal(h.calls.length,0);});
 await check('visible-image-exact-bound-bytes',async()=>{const h=harness(),reader=h.env.createBoopaCatalogReader(h.env),bucket=Number(visibleId)%512;const expected=JSON.parse(bytes('search-core/images_'+bucket+'.json'))[visibleId];assert.equal(await reader.image(visibleId),expected);});
 await check('becomes-hidden-while-image-awaits',async()=>{const h=harness(),reader=h.env.createBoopaCatalogReader(h.env);h.after(async name=>{if(name.startsWith('search-core/images_'))h.run('runtimeHiddenIds.add('+JSON.stringify(visibleId)+')');});assert.equal(await reader.image(visibleId),null);assert(h.calls.some(c=>c.name.startsWith('search-core/images_')));});
 await check('mutated-image-refused',async()=>{const h=harness({transform:(n,b)=>n.startsWith('search-core/images_')?Buffer.concat([b,Buffer.from(' ')]):b}),reader=h.env.createBoopaCatalogReader(h.env);await assert.rejects(()=>reader.image(visibleId),/revision mismatch/);});
 await check('image-external-marker-prunes-full-card-and-refreshes-count',()=>{
  const h=harness(),engine=bytes('image-search-engine.js').toString(),events=new Map(),nodes={};let articleRemoved=false,linkRemoved=false;
  const article={remove(){articleRemoved=true}},link={dataset:{},getAttribute:k=>k==='href'?'item.html?id='+visibleId:'',closest:s=>s.includes('.image-result')?article:null,remove(){linkRemoved=true}};
  h.env.document={activeElement:null,querySelectorAll:()=>[link],getElementById:id=>nodes[id]||(nodes[id]={hidden:false,scrollTop:17,innerHTML:'',textContent:'',querySelectorAll:()=>[]})};
  h.env.addEventListener=(name,fn)=>events.set(name,fn);h.env.dispatchEvent=event=>events.get(event.type)?.(event);
  h.env.LANG='en';h.env.esc=String;h.env.tr=(k,v)=>v&&v.n!==undefined?String(v.n):k;h.env.imgHitsFromApi=x=>x;h.env.imageEnrichBookmarks=()=>{};h.env.imageInfoText=()=> 'synthetic loading';
  const take=(start,end)=>{const a=engine.indexOf(start),b=engine.indexOf(end,a);assert(a>=0&&b>a);return engine.slice(a,b)};
  h.run(take('function imageResultSafeUrl','const imageResultMetadata'));
  h.run('const imageResultMetadata=new Map();let lvRawResults='+JSON.stringify([{id:visibleId,name:'visible',cur:500,base:900,shop:'shop'},{id:'999999999999',name:'other'}])+';let lvRequestId=2,lvResultsRequest=2;const lvEl=id=>document.getElementById(id);const lvResultCard=x=>imageResultCard(x,false,"item.html?id="+x.id);');
  h.run(take('function lvMappedResults','function imagePriceRecord'));
  h.run(take('function lvRefreshCatalog','let lvRequestId'));
  h.run(take('function lvRenderResults','function lvOpenUpload'));
  const listener='window.addEventListener("boopa:visibility",()=>{ lvRefreshCatalog(); });';assert.equal(engine.split(listener).length,2);h.run(listener);
  h.run('lvRefreshCatalog()');assert.equal(nodes.lvCount.textContent,'2');assert(nodes.lvResults.innerHTML.includes('data-id="'+visibleId+'"'));
  for(const rejectedDate of [staleMarkerDay,futureMarkerDay]){
   h.env.BoopaVisibility.acceptMeta(visibleId,{id:visibleId,unavailable:true,status:404,fetched_at:rejectedDate});
   assert.equal(h.env.BoopaVisibility.isHidden(visibleId),false);assert.equal(articleRemoved,false);assert.equal(nodes.lvCount.textContent,'2');
  }
  h.env.BoopaVisibility.acceptMeta(visibleId,{id:visibleId,unavailable:true,status:404,fetched_at:markerDay});
  assert.equal(articleRemoved,true);assert.equal(linkRemoved,false);assert.equal(nodes.lvCount.textContent,'1');assert(!nodes.lvResults.innerHTML.includes('data-id="'+visibleId+'"'));assert.equal(nodes.lvSheetBody.scrollTop,17);
  h.env.BoopaVisibility.acceptMeta(visibleId,{id:visibleId,name:'later success',fetched_at:markerDay});h.run('lvRefreshCatalog()');assert.equal(nodes.lvCount.textContent,'1');
  h.env.BoopaVisibility.acceptMeta('999999999999',{id:'999999999999',unavailable:true,status:410,fetched_at:markerDay});assert.equal(nodes.lvCount.textContent,'0');assert.equal(nodes.lvResults.innerHTML,'');assert.equal(nodes.lvNote.hidden,false);
 });
 const result={schema:'boopa-final-runtime-execution-qa-r2-source-day-fixture',fixture_marker_day:markerDay,fixture_clock_utc:new Date(markerNow).toISOString(),stale_and_future_marker_refusal_checked:true,status:'PASS',candidate_snapshot_sha256:pin,publication_revision:payload.publication_revision,test_script_sha256:sha(fs.readFileSync(__filename)),checks,check_count:checks.length,scope:'exact emitted code and candidate bytes; synthetic local fetch, no network or browser',real_browser_tested:false,authenticated_transport_proven:false,publication_eligible:false};
 fs.writeFileSync(output,JSON.stringify(result,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify({status:result.status,check_count:checks.length,candidate_snapshot_sha256:pin}));
})().catch(e=>{console.error(e.stack);process.exitCode=1});
