/* Complete reviewed child-search scope. Separate from capped product previews. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.BoopaRelationshipSearch=factory();})(typeof globalThis!=='undefined'?globalThis:this,function(){
 'use strict';
 const schema='boopadb-children-search-v1',valid=id=>typeof id==='string'&&/^[1-9]\d{0,15}$/.test(id),hex=s=>typeof s==='string'&&/^[a-f0-9]{64}$/.test(s);
 function create(options={}){
  const cache=new Map(),request=options.fetch||((...args)=>fetch(...args));
  function json(url){
   if(!cache.has(url)){
    const task=(async()=>{let timer;const ctl=typeof AbortController!=='undefined'?new AbortController():null;
     try{return await Promise.race([(async()=>{const r=await request(url,{cache:'no-store',signal:ctl&&ctl.signal});if(!r.ok)throw Error('HTTP '+r.status);return r.json();})(),new Promise((_,reject)=>{timer=setTimeout(()=>{if(ctl)ctl.abort();reject(Error('timeout'));},options.timeoutMs||10000);})]);}finally{clearTimeout(timer);}
    })();cache.set(url,task);task.catch(()=>cache.delete(url));
   }return cache.get(url);
  }
  async function get(id){
   if(!valid(id))return {status:'error',reason:'invalid-id'};
   try{
    const [m,source]=await Promise.all([json('relation-search/manifest.json'),json('relation-data/manifest.json')]);
    if(m.schema!==schema||m.complete!==true||m.shards!==8||!hex(m.version)||!hex(m.sourceVersion)||source.schema!=='boopadb-relations-v1'||source.version!==m.sourceVersion)throw Error('manifest/source mismatch');
    const shard=await json(`relation-search/children_${Number(BigInt(id)%8n)}.json?v=${m.version}`);
    if(shard.schema!==schema||shard.version!==m.version||shard.sourceVersion!==m.sourceVersion||!shard.items||Array.isArray(shard.items)||typeof shard.items!=='object')throw Error('mixed generation');
    const v=Object.prototype.hasOwnProperty.call(shard.items,id)?shard.items[id]:[0,[]];
    if(!Array.isArray(v)||v.length!==2||!Number.isSafeInteger(v[0])||v[0]<0||!Array.isArray(v[1])||v[1].length!==v[0]||!v[1].every(x=>valid(x)&&x!==id)||new Set(v[1]).size!==v[1].length)throw Error('incomplete/invalid scope');
    return {status:'ready',id,total:v[0],ids:v[1],version:m.version};
   }catch(error){cache.clear();return {status:'error',reason:String(error.message||error)};}
  }
  return {get,clear:()=>cache.clear()};
 }
 return {create};
});
