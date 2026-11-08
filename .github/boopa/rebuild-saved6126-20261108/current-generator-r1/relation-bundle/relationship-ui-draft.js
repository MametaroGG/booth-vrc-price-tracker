/* Reviewed relationship UI. Production activation remains separately gated.
 * Snapshot provenance approved; runtime integration still under local review.
 * Never map refs/base_refs/category heuristics into this model.
 */
(function(root, factory){
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.BoopaRelationshipDraft = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function(){
  'use strict';
  const kinds = ['parents', 'prerequisites', 'thumbnail'];
  const labels = {
    ja: ['親作品', '動作に必要な作品・ツール', 'サムネイルに使用された作品', 'この作品の親作品・前提商品・サムネイル使用作品のデータは、まだ収録されていません。', '現在の登録データには、この作品の親作品・前提商品・サムネイル使用作品がありません。実際に関係がないとは限りません。', '商品情報を取得できません', '無料', '前へ', '次へ'],
    en: ['Parent works', 'Required works and tools', 'Works used in the thumbnail', 'Parent, prerequisite, and thumbnail-use data for this item has not been recorded yet.', 'No parent, prerequisite, or thumbnail-use entries are currently stored for this item. Relationships may still exist.', 'Product information unavailable', 'Free', 'Previous', 'Next'],
    ko: ['부모 작품', '작동에 필요한 작품·도구', '썸네일에 사용된 작품', '이 작품의 부모 작품·필수 작품·썸네일 사용 작품 데이터가 아직 등록되지 않았습니다.', '현재 등록된 데이터에는 이 작품의 부모 작품·필수 작품·썸네일 사용 작품이 없습니다. 실제 관계가 없다는 뜻은 아닙니다.', '상품 정보를 가져올 수 없습니다', '무료', '이전', '다음'],
    'zh-Hans': ['父作品', '运行所需的作品和工具', '缩略图中使用的作品', '本作品的父作品、前置作品及缩略图使用作品数据尚未收录。', '当前数据未记录本作品的父作品、前置作品或缩略图使用作品。这不代表实际没有相关作品。', '无法获取商品信息', '免费', '上一页', '下一页'],
    'zh-Hant': ['父作品', '執行所需的作品與工具', '縮圖中使用的作品', '本作品的父作品、前置作品及縮圖使用作品資料尚未收錄。', '目前資料未記錄本作品的父作品、前置作品或縮圖使用作品。這不代表實際沒有相關作品。', '無法取得商品資訊', '免費', '上一頁', '下一頁']
  };
  const childrenLabels = {ja:['子作品','もっと見る','表示'],en:['Derivative works','Show more','Shown'],ko:['파생 작품','더 보기','표시'], 'zh-Hans':['子作品','查看更多','显示'],'zh-Hant':['子作品','查看更多','顯示']};
  const childrenNotes = {
    ja:'子作品は、他の作品に登録された親作品の情報から表示しています。',
    en:"Derivative works are listed from other items' recorded parent links.",
    ko:'파생 작품은 다른 작품에 등록된 부모 작품 정보를 바탕으로 표시합니다.',
    'zh-Hans':'子作品根据其他作品中记录的父作品信息列出。',
    'zh-Hant':'子作品依據其他作品中記錄的父作品資訊列出。'
  };
  const loadingLabels={ja:'関連作品データを読み込んでいます…',en:'Loading related-work data…',ko:'관련 작품 데이터를 불러오는 중…','zh-Hans':'正在加载相关作品数据…','zh-Hant':'正在載入相關作品資料…'};
  const errorLabels={
    ja:['親作品・前提商品・サムネイル使用作品のデータを読み込めませんでした。','子作品のデータを読み込めませんでした。'],
    en:['Could not load parent, prerequisite, and thumbnail-use data.','Could not load derivative-work data.'],
    ko:['부모 작품·필수 작품·썸네일 사용 작품 데이터를 불러오지 못했습니다.','파생 작품 데이터를 불러오지 못했습니다.'],
    'zh-Hans':['无法加载父作品、前置作品及缩略图使用作品数据。','无法加载子作品数据。'],
    'zh-Hant':['無法載入父作品、前置作品及縮圖使用作品資料。','無法載入子作品資料。']
  };
  const allKinds = [...kinds, 'children'];
  const visibleIds = (model,kind,options) => (model.groups[kind] || []).slice(0,kind === 'children' ? 30 : (options.limits && options.limits[kind]) || 30);
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const idOf = value => typeof value === 'string' && /^[1-9]\d{0,15}$/.test(value) ? value : null;
  // All three groups must have explicit reviewed arrays. {} is UNKNOWN, not empty.
  function adaptSynthetic(input, selfId){
    const unknown = {status:'unknown', groups:{}};
    if (!input || input.schema !== 'synthetic-relationship-view-v1' || input.reviewed !== true || !kinds.every(k => Array.isArray(input[k]))) return unknown;
    return normalizeGroups(input, selfId);
  }
  function normalizeGroups(input, selfId){
    const unknown = {status:'unknown', groups:{}};
    const groups = {};
    for (const kind of kinds) {
      const seen = new Set(); groups[kind] = [];
      for (const raw of input[kind]) {
        const id = idOf(raw);
        if (!id) return unknown; // malformed data is not evidence of absence
        if (id !== selfId && !seen.has(id)) { seen.add(id); groups[kind].push(id); }
      }
    }
    return {status:'verified', groups};
  }
  // Approval belongs to the caller; passing structural checks is NOT approval.
  // Optional correctedVerdicts provides explicit reviewed-none coverage. An
  // absent full row alone never proves absence; nonempty omitted rows are errors.
  function adaptGenerated(full, selfId, options = {}){
    const unknown = {status:'unknown', groups:{}};
    const has = (o,k) => o && Object.prototype.hasOwnProperty.call(o,k);
    const shape = v => v && typeof v === 'object' && !Array.isArray(v) && kinds.every(k => has(v,k) && Array.isArray(v[k]));
    if (options.artifactVerified !== true || !idOf(selfId) || !full || typeof full !== 'object' || Array.isArray(full)) return unknown;
    const master = options.correctedVerdicts;
    if (!has(full,selfId)) {
      const none = has(master,selfId) && master[selfId];
      return shape(none) && kinds.every(k => none[k].length === 0) ? normalizeGroups(none,selfId) : unknown;
    }
    const entry = full[selfId];
    if (!shape(entry)) return unknown;
    const model = normalizeGroups(entry,selfId);
    if (master) {
      if (!has(master,selfId) || !shape(master[selfId])) return unknown;
      const reviewed = normalizeGroups(master[selfId],selfId);
      if (reviewed.status !== 'verified' || JSON.stringify(reviewed.groups) !== JSON.stringify(model.groups)) return unknown;
    }
    return model;
  }
  function safeImage(value){
    try { const u = new URL(value); return u.protocol === 'https:' && !u.username && !u.password ? u.href : ''; } catch { return ''; }
  }
  function cardFrame(attrs,href,media,name,shop,footer,index,linkAttrs='',extraStyle=''){
    return `<div class="card" ${attrs} style="animation-delay:${index % 30 * 45}ms;${extraStyle}"><a class="thumbwrap" href="${esc(href)}" ${linkAttrs}>${media}</a><div class="cbody"><div class="cname"><a href="${esc(href)}" ${linkAttrs}>${esc(name)}</a></div><div class="cshop">${esc(shop)}</div><div class="crow">${footer}</div></div></div>`;
  }
  function card(id, meta, index, options){
    if(!idOf(id))return '';
    const l=labels[options.lang]||labels.ja,img=safeImage(meta&&(meta.image_resized||meta.image));
    const bookmark=options.bookmarkHTML?options.bookmarkHTML(id):'';
    const price=meta&&typeof meta.price==='number'&&Number.isFinite(meta.price)&&meta.price>=0?meta.price:null;
    const priceText=price===null?'—':price===0?l[6]:'¥'+price.toLocaleString('ja-JP');
    const media=(img?`<img decoding="async" src="${esc(img)}" alt="" loading="lazy" referrerpolicy="no-referrer">`:'<span class="phcard" aria-hidden="true"></span>')+bookmark;
    return cardFrame(`data-pid="${id}"`,'item.html?id='+id,media,meta&&meta.name||l[5]+' (#'+id+')',meta&&meta.shop&&meta.shop.name,`<span class="price solo">${esc(priceText)}</span>`,index);
  }
  function externalToolCard(tool,index,options={}){
    if(!tool||tool.toolKey!=='modular_avatar'||tool.url!=='https://modular-avatar.nadena.dev/ja'||tool.status!=='reviewed_required')return '';
    const l={ja:['外部ツール','公式サイト（日本語）'],en:['External tool','Official site (Japanese)'],ko:['외부 도구','공식 사이트 (일본어)'],'zh-Hans':['外部工具','官方网站（日语）'],'zh-Hant':['外部工具','官方網站（日語）']}[options.lang]||['外部ツール','公式サイト（日本語）'];
    const media='<img src="relation-supplement/assets/modular-avatar-logo.png?v=19e09e96c1fdbe4f" alt="Modular Avatar" width="2057" height="572" decoding="async" loading="lazy" style="object-fit:contain;box-sizing:border-box;padding:12px;background:#131316;transform:none;transition:none">';
    return cardFrame('data-external-tool="modular_avatar"',tool.url,media,'Modular Avatar',l[0],`<span class="cshop">${esc(l[1])}</span>`,index,'target="_blank" rel="noopener noreferrer"','animation:none;transform:none;transition:none;');
  }
  function rail(cards,options={}){
    const l=labels[options.lang]||labels.ja;
    return `<div class="relwrap"><div class="relrow">${cards}</div><button type="button" class="relbtn prev" data-draft-rel-scroll="-1" aria-label="${esc(l[7])}">‹</button><button type="button" class="relbtn next" data-draft-rel-scroll="1" aria-label="${esc(l[8])}">›</button></div>`;
  }
  function render(model, metadata, options = {}){
    model = {...model,groups:model.groups || {}};
    const l = labels[options.lang] || labels.ja;
    const cl = childrenLabels[options.lang] || childrenLabels.ja;
    const hasAny = allKinds.some(kind => (model.groups[kind] || []).length > 0);
    const errors=errorLabels[options.lang]||errorLabels.ja;
    let html=model.status==='loading'?`<p role="status" data-relation-status="loading">${esc(loadingLabels[options.lang]||loadingLabels.ja)}</p>`:'';
    if(model.outgoingStatus==='error')html+=`<p role="status" data-relation-status="outgoing-error">${esc(errors[0])}</p>`;
    if(model.childrenStatus==='error')html+=`<p role="status" data-relation-status="children-error">${esc(errors[1])}</p>`;
    // Missing coverage is not an error, and must not contradict visible sections.
    if(!hasAny && !html)html=model.status!=='verified'?`<p role="status" data-relation-status="outgoing-missing">${esc(l[3])}</p>`:`<p role="status" data-relation-status="outgoing-empty">${esc(l[4])}</p>`;
    allKinds.forEach((kind, index) => {
      const ids = visibleIds(model,kind,options);
      const total = kind === 'children' ? model.childrenTotal : (model.groups[kind] || []).length;
      const title = kind === 'children' ? cl[0] : l[index];
      if (!ids.length) return;
      // data attribute, rather than a global ID, supports independently mounted hosts.
      html += `<section data-relation-kind="${kind}" data-relation-total="${total}" aria-label="${esc(title)}"><div class="pp-sec">${esc(title)}（${total}）</div>${kind === 'children' ? `<p data-relation-direction="inverse">${esc(childrenNotes[options.lang] || childrenNotes.ja)}</p>` : ''}${rail(ids.map((id,i) => card(id, metadata[id], i, options)).join(''),options)}${kind === 'children' && total > ids.length && idOf(options.selfId) ? `<a class="relmore" data-relation-search="children" href="index.html?children=${options.selfId}">${esc(cl[1])}</a>` : kind !== 'children' && (model.groups[kind] || []).length > ids.length ? `<button type="button" class="relmore" data-relation-more="${kind}">${esc(cl[1])}</button>` : ''}${kind === 'children' && total > ids.length ? `<span class="cshop">${esc(cl[2])}: ${ids.length} / ${total}</span>` : ''}</section>`;
    });
    return html;
  }
  // Every mount invalidates older responses, including A -> B -> A and same-ID retries.
  const mounts = new WeakMap();
  async function mountModel(host, model, options = {}){
    const previous=mounts.get(host);if(previous && previous.observer)previous.observer.disconnect();
    const token = {}; mounts.set(host, token);
    const current = () => mounts.get(host) === token && host.isConnected && (!options.isCurrent || options.isCurrent());
    if (!current()) return false;
    const metadata=options._metadata || Object.create(null);
    const sync=()=>host.querySelectorAll('.relrow').forEach(row=>row.parentElement.classList.toggle('hasmore',row.scrollWidth-row.clientWidth>8));
    const imageFallback=()=>host.querySelectorAll('img').forEach(img=>{img.onerror=()=>{const placeholder=host.ownerDocument.createElement('span');placeholder.className='phcard';img.replaceWith(placeholder);};});
    // Render relationships immediately: slow metadata must not hide known edges.
    host.innerHTML = render(model, metadata, options);
    if(options.onRender)options.onRender();
    host.onclick = e => {
      const more=e.target.closest('[data-relation-more]');
      if(more && host.contains(more)){const k=more.dataset.relationMore;const limits={...options.limits,[k]:((options.limits&&options.limits[k])||30)+30};mountModel(host,model,{...options,limits,_metadata:metadata});return;}
      const b=e.target.closest('[data-draft-rel-scroll]');if(!b||!host.contains(b))return;
      const row=b.parentElement.querySelector('.relrow');row.scrollBy({left:Number(b.dataset.draftRelScroll)*row.clientWidth*.9,behavior:'smooth'});
    };
    sync();imageFallback();
    const ViewResizeObserver=host.ownerDocument.defaultView.ResizeObserver;
    if(ViewResizeObserver){token.observer=new ViewResizeObserver(sync);token.observer.observe(host);}
    const ids=[...new Set(allKinds.flatMap(k=>visibleIds(model,k,options)))].filter(id=>!Object.prototype.hasOwnProperty.call(metadata,id));
    let cursor=0;
    await Promise.all(Array.from({length:Math.min(6,ids.length)},async()=>{
      while(current() && cursor<ids.length){const id=ids[cursor++];let timer;let value;
        try{value=options.fetchMeta?await Promise.race([options.fetchMeta(id),new Promise(resolve=>{timer=setTimeout(()=>resolve(null),options.metadataTimeoutMs||8000);})]):null;}
        catch{value=null;}finally{clearTimeout(timer);}
        if(!current())return;
        metadata[id]=value;
        host.querySelectorAll(`[data-pid="${id}"]`).forEach(node=>{node.outerHTML=card(id,value,0,options);});
        imageFallback();sync();
      }
    }));
    if(!current() && token.observer)token.observer.disconnect();
    return current();
  }
  function mount(host, selfId, input, options = {}){
    return mountModel(host, adaptSynthetic(input, selfId), options);
  }
  function mountGenerated(host, selfId, full, options = {}){
    return mountModel(host, adaptGenerated(full, selfId, options), options);
  }
  function mountSnapshot(host,selfId,snapshot,options={}){
    const full = snapshot.status==='loaded' && snapshot.entry ? {[selfId]:snapshot.entry} : {};
    const model = adaptGenerated(full,selfId,{artifactVerified:snapshot.status==='loaded'});
    model.groups.children = snapshot.status==='loaded' ? snapshot.children : [];
    model.childrenTotal = snapshot.status==='loaded' ? snapshot.childrenTotal : 0;
    model.outgoingStatus=snapshot.outgoingStatus || (snapshot.status==='loaded' ? snapshot.entry ? 'loaded':'missing' : 'error');
    model.childrenStatus=snapshot.childrenStatus || (snapshot.status==='loaded'?'loaded':'error');
    return mountModel(host,model,{...options,selfId});
  }
  function cancel(host){ const token=mounts.get(host);if(token&&token.observer)token.observer.disconnect();mounts.delete(host); host.onclick = null; host.innerHTML = ''; }
  return {adaptSynthetic, adaptGenerated, render, mount, mountGenerated, mountSnapshot, cancel, labels, card, externalToolCard, rail};
});
