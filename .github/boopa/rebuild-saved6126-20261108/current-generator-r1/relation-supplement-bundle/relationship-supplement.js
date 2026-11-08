/* Small, reviewed positive-only supplement. Never infer relationships from absence. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory(require('./relationship-ui-draft'));else root.BoopaRelationshipSupplement=factory(root.BoopaRelationshipDraft);})(typeof globalThis!=='undefined'?globalThis:this,function(cardUI){
 'use strict';
 const schema='boopadb-relation-supplement-v1',id=x=>typeof x==='string'&&/^[1-9]\d{0,15}$/.test(x),hex=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
 const text=x=>typeof x==='string'&&x.length>0&&x.length<=300;
 const esc=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const reviewedCopy={ja:['商品説明に記載された参考リンクです。対応・必須を意味するものではありません。','確認'],en:['References stated in the product description; not claims of compatibility or requirements.','Reviewed'],ko:['상품 설명에 기재된 참고 링크입니다. 호환 또는 필수를 의미하지 않습니다.','확인'],'zh-Hans':['商品说明中的参考链接，不表示兼容或必需。','确认'],'zh-Hant':['商品說明中的參考連結，不表示相容或必要。','確認']};
 const copy={ja:['別途導入が必要な外部ツール','その他の参考リンク','公式サイト（日本語）','保存された商品説明に基づく参考情報です。説明の取得時点は不明で、現在の内容とは異なる場合があります。','外部ツール・参考リンクを読み込めませんでした。'],en:['External tools requiring separate installation','Other reference links','Official site (Japanese)','References from archived product descriptions. Capture dates are unknown; current details may differ.','Could not load external tools and reference links.'],ko:['별도 설치가 필요한 외부 도구','기타 참고 링크','공식 사이트 (일본어)','저장된 상품 설명을 바탕으로 한 참고 정보입니다. 수집 시점은 알 수 없으며 현재 내용과 다를 수 있습니다.','외부 도구 및 참고 링크를 불러오지 못했습니다.'],'zh-Hans':['需要单独安装的外部工具','其他参考链接','官方网站（日语）','参考信息来自存档商品说明。采集时间未知，可能与当前内容不同。','无法加载外部工具及参考链接。'],'zh-Hant':['需要另行安裝的外部工具','其他參考連結','官方網站（日語）','參考資訊來自封存商品說明。擷取時間不明，可能與目前內容不同。','無法載入外部工具及參考連結。']};
 function validate(row,self){
  if(!row||!Array.isArray(row.tools)||!Array.isArray(row.references)||row.tools.length>20||row.references.length>30)throw Error('invalid supplement row');
  const seen=new Set();
  for(const t of row.tools){if(!t||t.kind!=='external_tool'||t.toolKey!=='modular_avatar'||t.status!=='reviewed_required'||t.url!=='https://modular-avatar.nadena.dev/ja'||t.name!=='Modular Avatar'||!/^\d{4}-\d{2}-\d{2}$/.test(t.observedAt)||!hex(t.evidenceSha256)||seen.has(t.toolKey))throw Error('unreviewed or unsafe tool');seen.add(t.toolKey);}
  for(const r of row.references){if(!r||r.kind!=='booth_reference'||!id(r.id)||r.id===self||!text(r.name)||r.status!=='reviewed_reference'||!['historical_capture_unknown','seller_reviewed_at'].includes(r.sourceAge)||(r.sourceAge==='seller_reviewed_at'&&!/^\d{4}-\d{2}-\d{2}$/.test(r.observedAt))||!hex(r.evidenceSha256)||seen.has(r.id))throw Error('unreviewed or invalid reference');seen.add(r.id);}
  return row;
 }
 function create(options={}){
  const cache=new Map(),request=options.fetch||((...args)=>fetch(...args));
  function json(url){if(!cache.has(url)){const task=(async()=>{const ctl=typeof AbortController!=='undefined'?new AbortController():null;let timer;try{return await Promise.race([(async()=>{const r=await request(url,{cache:'no-store',signal:ctl&&ctl.signal});if(!r.ok)throw Error('HTTP '+r.status);return r.json();})(),new Promise((_,reject)=>{timer=setTimeout(()=>{if(ctl)ctl.abort();reject(Error('timeout'));},options.timeoutMs||8000);})]);}finally{clearTimeout(timer);}})();cache.set(url,task);task.catch(()=>cache.delete(url));}return cache.get(url);}
  async function get(self,sourceVersion){if(!id(self))return {status:'error'};try{const m=await json('relation-supplement/manifest.json');if(m.schema!==schema||!hex(m.version)||!hex(m.sourceVersion)||m.sourceVersion!==sourceVersion||!Array.isArray(m.itemIds)||m.itemIds.length>1000||!m.itemIds.every(id)||new Set(m.itemIds).size!==m.itemIds.length)throw Error('supplement source mismatch');if(!m.itemIds.includes(self))return {status:'absent'};const d=await json('relation-supplement/items.json?v='+m.version);if(d.schema!==schema||d.version!==m.version||d.sourceVersion!==m.sourceVersion||!d.items||typeof d.items!=='object'||Array.isArray(d.items)||Object.keys(d.items).length!==m.itemIds.length||!m.itemIds.every(k=>Object.hasOwn(d.items,k)))throw Error('supplement generation mismatch');return {status:'ready',...validate(d.items[self],self)};}catch(e){cache.clear();return {status:'error'};}}
  return {get};
 }
 function render(result,options={}){
  const l=copy[options.lang]||copy.ja,rc=reviewedCopy[options.lang]||reviewedCopy.ja;
  if(result.status==='absent')return '';
  if(result.status==='ready'){try{validate(result,options.selfId);}catch{result={status:'error'};}}
  if(result.status!=='ready'||!cardUI)return `<p role="status" data-supplement-error>${esc(l[4])}</p>`;
  if(!result.references.length)return '';
  const cards=result.references.map((r,i)=>cardUI.card(r.id,{name:r.name,...(options.metadata&&options.metadata[r.id]||{})},i,options)).join('');
  return `<section data-supplement-kind="references" aria-label="${esc(l[1])}" aria-description="${esc(rc[0])}"><div class="pp-sec" title="${esc(rc[0])}">${esc(l[1])}（${result.references.length}）</div>${cardUI.rail(cards,options)}</section>`;
 }
 const states=new WeakMap();
 function removeTools(host){
  host.querySelectorAll('[data-external-tool]').forEach(x=>x.remove());
  const sec=host.querySelector('[data-relation-kind="prerequisites"]');
  if(sec&&sec.dataset.supplementOnly)sec.remove();
  else if(sec){const heading=sec.querySelector('.pp-sec');if(heading)heading.textContent=(cardUI.labels[states.get(host)?.options.lang]||cardUI.labels.ja)[1]+'（'+sec.dataset.relationTotal+'）';}
 }
 function clear(host){if(!host)return;removeTools(host);const old=states.get(host);if(old&&old.observer)old.observer.disconnect();states.delete(host);const next=host.nextElementSibling;if(next&&next.hasAttribute('data-relation-supplement'))next.remove();}
 function current(host,state){return states.get(host)===state&&host.isConnected&&(!state.options.isCurrent||state.options.isCurrent());}
 function sync(host){
  const state=states.get(host);if(!state||!current(host,state)||state.result.status!=='ready')return;
  const {result,options}=state,l=cardUI.labels[options.lang]||cardUI.labels.ja;removeTools(host);
  if(result.tools.length){let section=host.querySelector('[data-relation-kind="prerequisites"]');if(!section){section=host.ownerDocument.createElement('section');section.dataset.relationKind='prerequisites';section.dataset.relationTotal='0';section.dataset.supplementOnly='true';section.setAttribute('aria-label',l[1]);section.innerHTML='<div class="pp-sec"></div>'+cardUI.rail('',options);const before=host.querySelector('[data-relation-kind="thumbnail"],[data-relation-kind="children"]');host.insertBefore(section,before);}
   const row=section.querySelector('.relrow');result.tools.forEach((tool,i)=>row.insertAdjacentHTML('beforeend',cardUI.externalToolCard(tool,i,options)));section.querySelector('.pp-sec').textContent=l[1]+'（'+(Number(section.dataset.relationTotal)+result.tools.length)+'）';section.querySelectorAll('[data-external-tool]').forEach(x=>x.title='Modular Avatar · '+result.tools[0].observedAt);
  }
  if(result.tools.length||result.references.length)host.querySelectorAll('[data-relation-status="outgoing-missing"],[data-relation-status="outgoing-empty"]').forEach(x=>x.remove());
  host.querySelectorAll('.relrow').forEach(row=>row.parentElement.classList.toggle('hasmore',row.scrollWidth-row.clientWidth>8));
 }
 function mount(host,result,options={}){
  if(!host||!host.isConnected||options.isCurrent&&!options.isCurrent())return Promise.resolve();
  if(result.status==='ready'){try{validate(result,options.selfId);}catch{result={status:'error'};}}
  const old=states.get(host);if(old&&old.result===result&&old.options.isCurrent===options.isCurrent){sync(host);return old.pending||Promise.resolve();}
  clear(host);const state={result,options,metadata:Object.create(null)};states.set(host,state);sync(host);
  const html=render(result,options);if(!html)return Promise.resolve();const box=host.ownerDocument.createElement('div');box.dataset.relationSupplement='';box.style.minWidth='0';box.innerHTML=html;host.after(box);
  const update=()=>{if(!current(host,state))return;box.querySelectorAll('.relrow').forEach(row=>row.parentElement.classList.toggle('hasmore',row.scrollWidth-row.clientWidth>8));box.querySelectorAll('img').forEach(img=>{img.onerror=()=>{const span=host.ownerDocument.createElement('span');span.className='phcard';img.replaceWith(span);};});if(result.status==='ready')result.references.forEach(r=>box.querySelectorAll(`[data-pid="${r.id}"]`).forEach(x=>x.title=r.name+' · '+(r.observedAt||'historical')));};
  box.onclick=e=>{const b=e.target.closest('[data-draft-rel-scroll]');if(!b||!box.contains(b))return;const row=b.parentElement.querySelector('.relrow');row.scrollBy({left:Number(b.dataset.draftRelScroll)*row.clientWidth*.9,behavior:'smooth'});};update();
  const RO=host.ownerDocument.defaultView.ResizeObserver;if(RO){state.observer=new RO(update);state.observer.observe(box);}
  if(result.status!=='ready'||!options.fetchMeta)return Promise.resolve();
  let cursor=0;state.pending=Promise.all(Array.from({length:Math.min(3,result.references.length)},async()=>{while(current(host,state)&&cursor<result.references.length){const ref=result.references[cursor++];let timer,value;try{value=await Promise.race([options.fetchMeta(ref.id),new Promise(resolve=>{timer=setTimeout(()=>resolve(null),options.metadataTimeoutMs||8000);})]);}catch{value=null;}finally{clearTimeout(timer);}if(!current(host,state))return;state.metadata[ref.id]={...(value||{}),name:value&&value.name||ref.name};box.querySelectorAll(`[data-pid="${ref.id}"]`).forEach(node=>node.outerHTML=cardUI.card(ref.id,state.metadata[ref.id],0,options));update();}}));return state.pending;
 }
 return {create,validate,render,mount,clear,sync};
});
