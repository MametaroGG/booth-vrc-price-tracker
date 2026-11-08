/* Pure, shared projection mechanics. Inputs are already manifest-bound payloads. */
function createCurrentPriceProjection(config, clock=()=>Date.now()){
 const entries=config.entries||{};
 const blocked=new Set(),listeners=new Set();
 function invalidate(id){blocked.add(String(id));for(const fn of listeners)fn({type:'snapshot-mismatch',id:String(id)});throw new Error('current price refresh required:'+id);}
 function assertReady(id){if(blocked.has(String(id)))throw new Error('current price refresh required:'+id);}
 function subscribe(fn){listeners.add(fn);return ()=>listeners.delete(fn);}
 function signature(){return Object.entries(entries).map(([id,p])=>id+':'+fresh(p)).join('|');}
 let lastSignature;
 function tick(){const next=signature();if(lastSignature!==undefined&&next!==lastSignature){lastSignature=next;for(const fn of listeners)fn({type:'evidence-expired'});}lastSignature=next;}
 tick();
 function entry(id){return entries[String(id)]||null;}
 function fresh(p){const n=clock();return !!p&&n>=Date.parse(p.selection_observed_at)&&n<Date.parse(p.expires_at);}
 function values(p){return fresh(p)?{cur:p.cur,base:p.base,lowest:p.lowest,sale:true,on_sale:true,pct:100*(1-p.cur/p.base),selected_price:p.cur,selected_sale:true,selected_sale_evidence_id:p.selected_sale_evidence_id,selected_variant_id:p.selected_variant_id,selected_variant_key:p.selected_variant_key,selection_status:'verified'}:{cur:p.cur,base:p.base,lowest:p.lowest,observed_display_variant_id:p.selected_variant_id,observed_display_at:p.selection_observed_at,sale:null,on_sale:null,pct:0,selected_price:null,selected_sale:null,selected_sale_evidence_id:null,selected_variant_id:null,selected_variant_key:null,selection_status:'expired'};}

 function record(x,{trustedLegacy=false}={}){
  if(!x||typeof x!=='object'||Array.isArray(x))return x;
  const p=entry(x.id);if(!p)return x;assertReady(x.id);if(!Number.isFinite(x.cur))return x;
  const selected=x.cur===p.cur&&x.base===p.base;
  const legacy=trustedLegacy&&x.cur===p.legacy.cur&&x.base===p.legacy.base;
  if(!selected&&!legacy)return invalidate(x.id);
  const out={...x,...values(p)};
  if(p.observed_display_spark)out.spark=p.observed_display_spark.map(v=>v.slice());
  for(const key of ['vars','variations'])if(out[key]&&Object.hasOwn(out[key],p.selected_variant_key)){out[key]={[p.selected_variant_key]:out[key][p.selected_variant_key],...out[key]};}
  return out;
 }
 function row(r,layout='search'){
  const p=Array.isArray(r)&&entry(r[0]);if(!p)return r;assertReady(r[0]);
  const c=layout==='shop'||layout==='full'?3:2,b=layout==='shop'||layout==='full'?4:3;
  // A freshly fetched unprojected/global index must not be silently promoted.
  if(r[c]!==p.cur||r[b]!==p.base)return invalidate(r[0]);
  const v=values(p),out=r.slice();out[c]=v.cur;out[b]=v.base;
  if(layout==='search'){out[4]=v.lowest;out[5]=v.sale===true?1:0;}else if(layout==='full'){out[5]=v.lowest;out[6]=v.sale===true?1:0;}else out[5]=v.sale===true?1:0;
  return out;
 }
 function walk(value,{trustedLegacy=false}={}){
  if(Array.isArray(value))return value.map(v=>walk(v,{trustedLegacy}));
  if(!value||typeof value!=='object')return value;
  let out=record(value,{trustedLegacy});out={...out};
  for(const key of Object.keys(out)){
   if(['vars','variations','spark','history','selected_price_projection'].includes(key))continue;
   if(out[key]&&typeof out[key]==='object')out[key]=walk(out[key],{trustedLegacy});
  }
  if(out.stats&&typeof out.stats==='object'&&Number.isFinite(out.stats.sale_now)){const prior=new Set(out.stats._expired_current_prices||[]),newly=Object.entries(entries).filter(([id,p])=>!fresh(p)&&!prior.has(id)).map(([id])=>id);out.stats.sale_now=Math.max(0,out.stats.sale_now-newly.length);out.stats._expired_current_prices=[...prior,...newly];}
  if(Array.isArray(out.on_sale))out.on_sale=out.on_sale.filter(v=>!entry(v.id)||fresh(entry(v.id)));
  if(Array.isArray(out.free))out.free=out.free.filter(v=>v.cur===0);
  return out;
 }
 function canonical(v){if(Array.isArray(v))return '['+v.map(canonical).join(',')+']';if(v&&typeof v==='object')return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}';return JSON.stringify(v);}
 async function rawRecord(raw,buildRecord,crypto){
  const rec=buildRecord(raw),p=entry(raw.id);if(!p)return rec;
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical(raw)))),b=>b.toString(16).padStart(2,'0')).join('');
  const accepted=p.accepted_raw_record_sha256||[p.raw_record_sha256];
  if(!accepted.includes(hash))return invalidate(raw.id); // Never mix a new raw record with an older projected catalog.
  return record(rec,{trustedLegacy:true});
 }
 function current(id){const p=entry(id);return p?record({id:String(id),cur:p.cur,base:p.base}):null;}
 function display(x){const p=x&&entry(x.id);const out=record(p&&x.selection_status==='expired'&&x.cur===p.cur&&x.base===x.cur?{...x,base:p.base}:x);return out&&out.selection_status==='expired'?{...out,base:out.cur,sale:false,on_sale:false,_pct:0,_disc:0,_rib:['',''],_status:'',_reason:'',_tags:[]}:out;}
 return {entry,fresh,record,row,walk,rawRecord,canonical,subscribe,tick,assertReady,current,display};
}
if(typeof module!=='undefined')module.exports={createCurrentPriceProjection};
