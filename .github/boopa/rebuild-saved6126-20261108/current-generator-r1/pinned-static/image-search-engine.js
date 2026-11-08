// Shared image-search lens. Host initializes catalog, localization and card adapters first.
async function imgSimilar(x){
  const requestId = ++lvRequestId;
  lvRemote = true; lvRect = null; lvShown = null; lvSearched = null; lvZoomReset();
  const img = document.getElementById("lvImg");
  img.onerror = null; // Do not retain a previous local-upload error handler.
  img.onload = () => { lvFitLoop(); lvRenderSvg(); };
  img.src = x.image || "";
  document.getElementById("lvThumb").src = x.image || "";
  document.getElementById("lvTools").style.display = "none";
  const _hint2 = document.getElementById("lvHint"); if (_hint2) _hint2.style.display = "none";
  lvOpen(); lvStageMode("results"); lvSetState("loading");
  try {
    const res = await fetch(IMG_API + "/similar/" + encodeURIComponent(x.id));
    if (requestId !== lvRequestId) return;
    if (res.status === 429) return lvSetState("limit");
    if (res.status === 404) return lvSetState("notindexed");
    if (!res.ok) return lvSetState("error");
    const j = await res.json();
    if (requestId !== lvRequestId) return;
    lvAcceptResults(j.results, requestId);
  } catch { if (requestId === lvRequestId) lvSetState("error"); }
}
// One result-card template for both uploaded and similar-image searches.
function imageResultSafeUrl(url){if(typeof url!=='string'||!/^https?:\/\//i.test(url))return '';try{const u=new URL(url);return /^https?:$/.test(u.protocol)?u.href:'';}catch{return '';}}
function imageResultCard(x, saved, detailUrl){
 const image=imageResultSafeUrl(x.image),price=x.cur==null?'':new Intl.NumberFormat(LANG,{style:'currency',currency:'JPY',maximumFractionDigits:0}).format(x.cur);
 return '<article class="image-result" data-id="'+esc(x.id)+'"><a href="'+esc(detailUrl)+'">'+(image?'<img src="'+esc(image)+'" alt="" loading="lazy" referrerpolicy="no-referrer">':'')+'</a><div class="image-result-body"><h3><a href="'+esc(detailUrl)+'">'+esc(x._infoError&&!x.name?imageInfoText(1):x.name)+'</a></h3><p>'+esc(x.shop)+'</p><div class="image-result-price">'+(x.base>x.cur&&x.cur!=null?'<del>'+esc(new Intl.NumberFormat(LANG,{style:'currency',currency:'JPY',maximumFractionDigits:0}).format(x.base))+'</del> ':'')+esc(price)+(x.base>x.cur&&x.cur!=null?' <small>−'+Math.round((1-x.cur/x.base)*100)+'%</small>':'')+'</div><p><a data-ext href="https://booth.pm/'+LANG+'/items/'+encodeURIComponent(x.id)+'" target="_blank" rel="noopener">'+esc(tr('pp_booth'))+' ↗</a></p>'+ (x._infoError?'<p class="image-info-error">'+esc(imageInfoText(1))+' <button type="button" data-metadata-retry="'+esc(x.id)+'">'+esc(imageInfoText(2))+'</button></p>':'')+'<button type="button" data-bookmark="'+esc(x.id)+'" aria-pressed="'+saved+'">'+esc(tr(saved?'pp_bmed':'pp_bm'))+'</button></div></article>';
}

const imageResultMetadata=new Map(), imageResultPending=new Map();
const IMAGE_ITEM_BASE='https://mametarogg.github.io/booth-vrc-price-tracker/';
const IMAGE_INFO_TEXT={
 ja:['商品情報を読み込み中…','商品情報を取得できませんでした','再試行'],
 en:['Loading product details…','Product details unavailable','Retry'],
 ko:['상품 정보 불러오는 중…','상품 정보를 불러오지 못했습니다','다시 시도'],
 'zh-Hans':['正在加载商品信息…','无法获取商品信息','重试'],
 'zh-Hant':['正在載入商品資訊…','無法取得商品資訊','重試']
};
function imageInfoText(i){return (IMAGE_INFO_TEXT[LANG]||IMAGE_INFO_TEXT.ja)[i];}
function lvMappedResults(){
 return imgHitsFromApi(lvRawResults).map(hit=>{
  const record=imageResultMetadata.get(String(hit.id));
  if(record)return {...hit,...record,name:record.name||imageInfoText(record._infoError?1:0),image:hit.image||record.image,_catalog:!!record.name};
  return hit._catalog?hit:{...hit,name:imageInfoText(0),_infoLoading:true};
 });
}
function imagePriceRecord(d){
 let series=null;
 for(const rows of Object.values(d.variations||{}))if(Array.isArray(rows)&&(!series||rows.length>series.length))series=rows;
 if(!series||!series.length)return {};
 const sorted=[...series].filter(r=>Number.isFinite(r.price)).sort((a,b)=>String(a.date).localeCompare(String(b.date)));
 if(!sorted.length)return {};
 return {cur:sorted[sorted.length-1].price,base:Math.max(...sorted.map(r=>r.price))};
}
function imageNotifyMetadata(){
 imageEnrichBookmarks([...imageResultMetadata.values()].filter(r=>r.name).map(r=>({...r,_catalog:true})));
 if(typeof lvCatalogUpdated==='function')lvCatalogUpdated();
 lvRefreshCatalog();
}
async function imageFetchRecord(id){
 if(imageResultPending.has(id))return imageResultPending.get(id);
 const task=(async()=>{
  const previous=imageResultMetadata.get(id)||{id};let record={...previous,_infoError:false};
  for(const kind of ['meta','data']){
   if(record['_'+kind+'Ready'])continue;
   for(let attempt=0;attempt<2;attempt++){
    try{
     const data=await imageCatalogShard(IMAGE_ITEM_BASE+kind+'/'+id.slice(0,3)+'/'+id+'.json');
     if(String(data.id)!==id)throw new Error('Unexpected product id');
     record=kind==='meta'?{...record,name:data.name||record.name,shop:data.shop&&data.shop.name||'',image:data.image_resized||data.image||''}:{...record,...imagePriceRecord(data),name:record.name||data.name};
     record['_'+kind+'Ready']=true;imageResultMetadata.set(id,{...record});imageNotifyMetadata();break;
    }catch{if(attempt===1)record._infoError=true;else await new Promise(resolve=>setTimeout(resolve,400));}
   }
  }
  imageResultMetadata.set(id,record);imageNotifyMetadata();return record;
 })().finally(()=>imageResultPending.delete(id));
 imageResultPending.set(id,task);return task;
}
async function lvEnrichResults(requestId){
 const ids=[...new Set(lvRawResults.map(r=>String(r.item_id)).filter(id=>/^\d+$/.test(id)))];let next=0;
 async function worker(){while(next<ids.length && requestId===lvRequestId){const id=ids[next++],known=imageResultMetadata.get(id);if(known&&known._metaReady&&known._dataReady)continue;await imageFetchRecord(id);}}
 await Promise.all(Array.from({length:Math.min(4,ids.length)},worker));
}
// Fetch includes JSON decoding in the timeout; a stalled shard cannot pin retry forever.
let imageFetchActive=0;const imageFetchWaiters=[];
async function imageCatalogShard(url){
 await new Promise(resolve=>{if(imageFetchActive<4){imageFetchActive++;resolve();}else imageFetchWaiters.push(resolve);});
 const controller=new AbortController();let timer;
 try{return await Promise.race([fetch(url,{signal:controller.signal}).then(r=>{if(!r.ok)throw new Error('catalog');return r.json();}),new Promise((_,reject)=>{timer=setTimeout(()=>{controller.abort();reject(new Error('catalog timeout'));},10000);})]);}
 finally{clearTimeout(timer);const next=imageFetchWaiters.shift();if(next)next();else imageFetchActive--;}
}
let lvRawResults=[], lvResultsRequest=-1;
function lvAcceptResults(results, requestId){
 if(requestId!==lvRequestId)return;
 lvRawResults=Array.isArray(results)?results:[];lvResultsRequest=requestId;
 lvShowResults(lvMappedResults());
 lvEnrichResults(requestId);
}
function lvRefreshCatalog(){
 if(lvResultsRequest!==lvRequestId || lvEl('lensView').hidden)return;
 const scroll=lvEl('lvSheetBody').scrollTop;
 const focus=document.activeElement && document.activeElement.dataset.bookmark;
 lvRenderResults(lvMappedResults());
 lvEl('lvSheetBody').scrollTop=scroll;
 if(focus){const button=[...lvEl('lvResults').querySelectorAll('[data-bookmark]')].find(b=>b.dataset.bookmark===focus);if(button)button.focus({preventScroll:true});}
}

let lvRequestId = 0;
let lvUrl = null, lvRect = null, lvShown = null, lvDrag = null, lvSearched = null, lvAnim = null, lvRemote = false, lvSettleGen = 0;
const lvEl = id => document.getElementById(id);
let lvReturnFocus = null;
function lvOpen(){ if (lvEl("lensView").hidden) lvReturnFocus = document.activeElement; lvEl("lensView").hidden = false; if (lvEl("imageSearchPage")) lvEl("imageSearchPage").setAttribute("aria-hidden", "true"); veilSync(); window.dispatchEvent(new Event("boopa:lens-open")); lvEl("lvBack").focus({preventScroll:true}); }
function lvClose(){ ++lvRequestId; lvEl("lensView").hidden = true; window.dispatchEvent(new Event("boopa:lens-close")); if (lvEl("imageSearchPage")) lvEl("imageSearchPage").removeAttribute("aria-hidden"); if (lvAnim) { cancelAnimationFrame(lvAnim); lvAnim = null; } lvZoomReset(); veilSync(); if (document.getElementById("imageSearchPage")) document.getElementById("spImgDrop").focus({preventScroll:true}); else if (lvReturnFocus && lvReturnFocus.isConnected) lvReturnFocus.focus({preventScroll:true}); }
function lvStageMode(mode){ lvFitLoop(); }
function lvFitBox(){
  const stage = lvEl("lvStage"), img = lvEl("lvImg"), wrap = lvEl("lvWrap");
  if (!stage || !img || !img.naturalWidth) return;
  const aw = Math.max(60, stage.clientWidth), ah = Math.max(60, stage.clientHeight);
  const s = Math.min(aw / img.naturalWidth, ah / img.naturalHeight);
  img.style.width = Math.max(1, Math.round(img.naturalWidth * s)) + "px";
  img.style.height = Math.max(1, Math.round(img.naturalHeight * s)) + "px";
  wrap.style.width = img.style.width; wrap.style.height = img.style.height;
}
function lvFitLoop(){
  const t0 = performance.now();
  const tick = () => { lvFitBox(); lvRenderSvg(); if (performance.now() - t0 < 420) requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
}
function lvRenderSvg(){
  const wrap = lvEl("lvWrap"), svg = lvEl("lvSvg");
  if (!wrap || !svg) return;
  const W = wrap.clientWidth, H = wrap.clientHeight;
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  if (!W || !H) return;
  svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  if (!lvShown) return;
  const NS = "http://www.w3.org/2000/svg";
  const x = lvShown.x0 * W, y = lvShown.y0 * H, w = (lvShown.x1 - lvShown.x0) * W, h = (lvShown.y1 - lvShown.y0) * H;
  const r = Math.max(3, Math.min(18, Math.min(w, h) * 0.16, w / 2, h / 2));
  const rr = (x, y, w, h, r) => "M " + (x + r) + " " + y + " H " + (x + w - r) + " A " + r + " " + r + " 0 0 1 " + (x + w) + " " + (y + r) + " V " + (y + h - r) + " A " + r + " " + r + " 0 0 1 " + (x + w - r) + " " + (y + h) + " H " + (x + r) + " A " + r + " " + r + " 0 0 1 " + x + " " + (y + h - r) + " V " + (y + r) + " A " + r + " " + r + " 0 0 1 " + (x + r) + " " + y + " Z";
  const dim = document.createElementNS(NS, "path");
  dim.setAttribute("d", "M 0 0 H " + W + " V " + H + " H 0 Z " + rr(x, y, w, h, r));
  dim.setAttribute("fill", "rgba(0,0,0,.48)"); dim.setAttribute("fill-rule", "evenodd");
  svg.appendChild(dim);
  const bd = document.createElementNS(NS, "path");
  bd.setAttribute("d", rr(x, y, w, h, r));
  bd.setAttribute("fill", "none"); bd.setAttribute("stroke", "rgba(255,255,255,.96)"); bd.setAttribute("stroke-width", "2");
  bd.setAttribute("class", "lv-border");
  svg.appendChild(bd);
  const off = Math.max(3, r * 0.4), R = r + off, ex = Math.max(5, r * 0.65);
  const brackets = [
    "M " + (x - off - ex) + " " + (y + r) + " L " + (x - off) + " " + (y + r) + " A " + R + " " + R + " 0 0 1 " + (x + r) + " " + (y - off) + " L " + (x + r) + " " + (y - off - ex),
    "M " + (x + w - r) + " " + (y - off - ex) + " L " + (x + w - r) + " " + (y - off) + " A " + R + " " + R + " 0 0 1 " + (x + w + off) + " " + (y + r) + " L " + (x + w + off + ex) + " " + (y + r),
    "M " + (x + w + off + ex) + " " + (y + h - r) + " L " + (x + w + off) + " " + (y + h - r) + " A " + R + " " + R + " 0 0 1 " + (x + w - r) + " " + (y + h + off) + " L " + (x + w - r) + " " + (y + h + off + ex),
    "M " + (x + r) + " " + (y + h + off + ex) + " L " + (x + r) + " " + (y + h + off) + " A " + R + " " + R + " 0 0 1 " + (x - off) + " " + (y + h - r) + " L " + (x - off - ex) + " " + (y + h - r)
  ];
  for (const d of brackets) {
    const b = document.createElementNS(NS, "path");
    b.setAttribute("d", d); b.setAttribute("class", "lv-bracket");
    b.style.strokeWidth = Math.max(2.2, Math.min(3, r * 0.3)) + "px";
    svg.appendChild(b);
  }
  const TL = Math.max(10, Math.min(22, Math.min(w, h) * 0.22));
  const ticks = [
    [x + w / 2 - TL / 2, y - 2.5], [x + w / 2 - TL / 2, y + h - 2.5],
    [x - 2.5, y + h / 2 - TL / 2], [x + w - 2.5, y + h / 2 - TL / 2]
  ];
  ticks.forEach((t, i) => {
    const tEl = document.createElementNS(NS, "rect");
    tEl.setAttribute("x", t[0]); tEl.setAttribute("y", t[1]);
    tEl.setAttribute("width", i < 2 ? TL : 4); tEl.setAttribute("height", i < 2 ? 4 : TL);
    tEl.setAttribute("rx", 2.5); tEl.setAttribute("class", "lv-tick");
    svg.appendChild(tEl);
  });
}
function lvGlideStart(){
  if (lvAnim) return;
  const step = () => {
    if (!lvRect || !lvShown) { lvAnim = null; return; }
    let done = true;
    for (const k of ["x0", "y0", "x1", "y1"]) {
      const d = lvRect[k] - lvShown[k];
      if (Math.abs(d) > 0.0006) { lvShown[k] += d * 0.38; done = false; } else lvShown[k] = lvRect[k];
    }
    lvRenderSvg();
    if (done) { lvAnim = null; lvMaybeSearch(); } else lvAnim = requestAnimationFrame(step);
  };
  lvAnim = requestAnimationFrame(step);
}
function lvMaybeSearch(){
  if (!lvRect || lvEl("lensView").hidden) return;
  if (lvSearched && ["x0", "y0", "x1", "y1"].every(k => Math.abs(lvSearched[k] - lvRect[k]) < 0.004)) return;
  lvRunSearch();
}
function lvSettle(bbox){
  const pad = 0.012;
  const target = { x0: Math.max(0, bbox.x0 - pad), y0: Math.max(0, bbox.y0 - pad), x1: Math.min(1, bbox.x1 + pad), y1: Math.min(1, bbox.y1 + pad) };
  lvRect = target;
  if (!lvShown) lvShown = {...bbox};
  const gen = ++lvSettleGen;
  const from = {...lvShown}, t0 = performance.now(), cv = lvEl("lvDraw");
  const tick = t => {
    if (gen !== lvSettleGen) return;
    const k = Math.min(1, (t - t0) / 240), e = 1 - Math.pow(1 - k, 3);
    for (const key of ["x0", "y0", "x1", "y1"]) lvShown[key] = from[key] + (target[key] - from[key]) * e;
    cv.style.opacity = String(1 - k);
    lvRenderSvg();
    if (k < 1) requestAnimationFrame(tick);
    else { lvCvClear(); cv.style.opacity = ""; lvMaybeSearch(); }
  };
  requestAnimationFrame(tick);
}
function lvCvSetup(){
  const cv = lvEl("lvDraw"), wrap = lvEl("lvWrap");
  if (!cv || !wrap) return;
  const dpr = Math.min(3, window.devicePixelRatio || 1);
  cv.width = Math.max(1, Math.round(wrap.clientWidth * dpr));
  cv.height = Math.max(1, Math.round(wrap.clientHeight * dpr));
  cv.getContext("2d").setTransform(dpr, 0, 0, dpr, 0, 0);
}
function lvCvClear(){
  const cv = lvEl("lvDraw"), wrap = lvEl("lvWrap");
  if (!cv || !wrap) return;
  const ctx = cv.getContext("2d");
  ctx.clearRect(0, 0, wrap.clientWidth, wrap.clientHeight);
}
function lvDrawTrail(pts){
  const cv = lvEl("lvDraw"), wrap = lvEl("lvWrap");
  if (!cv || !wrap) return;
  const ctx = cv.getContext("2d");
  const W = wrap.clientWidth, H = wrap.clientHeight;
  ctx.clearRect(0, 0, W, H);
  if (pts.length < 2) return;
  const P = pts.map(q => [q.x * W, q.y * H]);
  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9, L = 0;
  for (let i = 0; i < P.length; i++) {
    x0 = Math.min(x0, P[i][0]); y0 = Math.min(y0, P[i][1]);
    x1 = Math.max(x1, P[i][0]); y1 = Math.max(y1, P[i][1]);
    if (i) L += Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]);
  }
  if (L < 2) return;
  const PAL = [[122, 184, 255], [125, 255, 206], [255, 226, 122], [255, 150, 130]];
  const pal = t => {
    const x = Math.min(0.999, Math.max(0, t)) * (PAL.length - 1);
    const k = Math.floor(x), f = x - k;
    const a = PAL[k], b = PAL[Math.min(PAL.length - 1, k + 1)];
    return [Math.round(a[0] + (b[0] - a[0]) * f), Math.round(a[1] + (b[1] - a[1]) * f), Math.round(a[2] + (b[2] - a[2]) * f)];
  };
  ctx.lineJoin = "round"; ctx.lineCap = "round";
  const fullPath = () => {
    ctx.beginPath();
    ctx.moveTo(P[0][0], P[0][1]);
    for (let i = 1; i < P.length - 1; i++) {
      const mx = (P[i][0] + P[i + 1][0]) / 2, my = (P[i][1] + P[i + 1][1]) / 2;
      ctx.quadraticCurveTo(P[i][0], P[i][1], mx, my);
    }
    ctx.lineTo(P[P.length - 1][0], P[P.length - 1][1]);
  };
  // blurred gradient halo around the whole line (layered widths + canvas blur where supported)
  const g = ctx.createLinearGradient(x0, y0, x1, y1);
  const stop = (t, a) => { const c = pal(t); g.addColorStop(t, "rgba(" + c[0] + "," + c[1] + "," + c[2] + "," + a + ")"); };
  stop(0, 1); stop(0.5, 1); stop(1, 1);
  try { ctx.filter = "blur(5px)"; } catch (e) {}
  fullPath(); ctx.strokeStyle = g; ctx.globalAlpha = 0.13; ctx.lineWidth = 26; ctx.stroke();
  fullPath(); ctx.strokeStyle = g; ctx.globalAlpha = 0.18; ctx.lineWidth = 16; ctx.stroke();
  try { ctx.filter = "none"; } catch (e) {}
  fullPath(); ctx.strokeStyle = g; ctx.globalAlpha = 0.22; ctx.lineWidth = 9; ctx.stroke();
  // soft haze blob following the pen tip
  const tip = P[P.length - 1], rad = 46;
  const tc = pal(0.85);
  const rg = ctx.createRadialGradient(tip[0], tip[1], 0, tip[0], tip[1], rad);
  rg.addColorStop(0, "rgba(" + tc[0] + "," + tc[1] + "," + tc[2] + ",0.42)");
  rg.addColorStop(0.55, "rgba(" + tc[0] + "," + tc[1] + "," + tc[2] + ",0.16)");
  rg.addColorStop(1, "rgba(" + tc[0] + "," + tc[1] + "," + tc[2] + ",0)");
  ctx.globalCompositeOperation = "lighter";
  ctx.fillStyle = rg; ctx.globalAlpha = 1;
  ctx.fillRect(tip[0] - rad, tip[1] - rad, rad * 2, rad * 2);
  ctx.globalCompositeOperation = "source-over";
  // the white line itself — kept along the whole stroke
  fullPath(); ctx.strokeStyle = "rgba(255,255,255,.95)"; ctx.globalAlpha = 0.95; ctx.lineWidth = 3; ctx.stroke();
  ctx.globalAlpha = 1;
}
async function lvCropBlob(img, r){
  const sx = Math.round(r.x0 * img.naturalWidth), sy = Math.round(r.y0 * img.naturalHeight);
  const sw = Math.max(8, Math.round((r.x1 - r.x0) * img.naturalWidth)), sh = Math.max(8, Math.round((r.y1 - r.y0) * img.naturalHeight));
  const scale = Math.min(1, 768 / Math.max(sw, sh));
  const cv = document.createElement("canvas");
  cv.width = Math.max(1, Math.round(sw * scale)); cv.height = Math.max(1, Math.round(sh * scale));
  cv.getContext("2d").drawImage(img, sx, sy, sw, sh, 0, 0, cv.width, cv.height);
  try { return await new Promise(res => cv.toBlob(res, "image/jpeg", 0.9)); } catch { return null; }
}
async function lvRunSearch(){
  const requestId = ++lvRequestId;
  const img = lvEl("lvImg");
  const r = lvRect ? {...lvRect} : { x0: 0, y0: 0, x1: 1, y1: 1 };
  lvSearched = {...r};
  lvSetState("loading");
  const blob = await lvCropBlob(img, r);
  if (requestId !== lvRequestId) return;
  if (!blob) { lvSetState("error"); return; }
  try {
    const fd = new FormData(); fd.append("file", blob, "query.jpg");
    const res = await fetch(IMG_API + "/search", { method: "POST", body: fd });
    if (requestId !== lvRequestId) return;
    if (res.status === 429) return lvSetState("limit");
    if (!res.ok) return lvSetState("error");
    const j = await res.json();
    if (requestId !== lvRequestId) return;
    lvAcceptResults(j.results, requestId);
  } catch { if (requestId === lvRequestId) lvSetState("error"); }
}
function lvPeekH(){ return lvSearched || lvEl("lvResults").children.length ? 118 : 34; }
function lvSheetSet(mode){
  const sh = lvEl("lvSheet"); if (!sh) return;
  const view = lvEl("lensView");
  const maxH = Math.max(200, view.clientHeight - 56);
  const h = mode === "max" ? maxH : mode === "mid" ? Math.round(view.clientHeight * 0.52) : lvPeekH();
  sh.classList.add("anim");
  sh.style.height = h + "px";
  setTimeout(() => sh.classList.remove("anim"), 330);
}
function lvSetState(state){
  const note = lvEl("lvNote"), res = lvEl("lvResults"), cnt = lvEl("lvCount");
  if (state === "idle") { note.hidden = true; res.innerHTML = ""; cnt.textContent = ""; return; }
  if (state === "loading") {
    note.hidden = true; cnt.textContent = tr("img_searching");
    res.innerHTML = '<div class="lv-skel"></div>'.repeat(6);
    lvStageMode("results");
    lvSheetSet("peek");
    return;
  }
  res.innerHTML = ""; cnt.textContent = "";
  lvSheetSet("peek");
  note.hidden = false;
  note.textContent = tr(state === "limit" ? "img_limit" : state === "notindexed" ? "img_notindexed" : "img_error");
  lvStageMode("results");
}
function lvShowResults(hits){
  lvSheetSet("mid");
  lvEl("lvNote").hidden = true;
  lvEl("lvCount").textContent = tr("sp_count", {n: hits.length});
  lvRenderResults(hits);
}
function imageEnrichCatalogBookmarks(){
 try{
  const saved=JSON.parse(localStorage.getItem('boopadb_bm')||'[]');if(!Array.isArray(saved))return;
  const rows=new Map((fullIndex||[]).map(row=>[String(row[0]),row]));
  imageEnrichBookmarks(saved.flatMap(b=>{const row=rows.get(String(b.id));return row?[{id:String(b.id),_catalog:true,name:row[1],shop:row[13]||'',image:b.image||row[10]||'',cur:row[3]}]:[];}));
 }catch{ /* Optional metadata refresh must not interrupt search. */ }
}
// Upgrade metadata of already-saved results, without resurrecting removed bookmarks.
function imageEnrichBookmarks(hits){
 try{
  const saved=JSON.parse(localStorage.getItem('boopadb_bm')||'[]');if(!Array.isArray(saved))return;
  const enriched=new Map(hits.filter(h=>h._catalog).map(h=>[String(h.id),h]));
  const next=saved.map(b=>{const h=enriched.get(String(b.id));return h?{...b,...Object.fromEntries(['name','shop','image','cur'].filter(k=>h[k]!==undefined&&h[k]!==null).map(k=>[k,h[k]]))}:b;});
  if(JSON.stringify(next)!==JSON.stringify(saved))localStorage.setItem('boopadb_bm',JSON.stringify(next));
 }catch{ /* Restricted storage must not hide search results. */ }
}
function lvRenderResults(hits){
  lvEl("lvCount").textContent = tr("sp_count", {n:hits.length});
  imageEnrichBookmarks(hits);
  lvEl("lvResults").innerHTML = hits.map(lvResultCard).join("");
  if (!hits.length) { lvEl("lvNote").hidden = false; lvEl("lvNote").textContent = tr("empty_none"); }
  if (typeof lvDecorateResults === "function") lvDecorateResults(hits);
}

function lvOpenUpload(file){
  if (!file) return;
  ++lvRequestId;
  if (lvUrl) URL.revokeObjectURL(lvUrl);
  const uploadUrl = URL.createObjectURL(file);
  lvUrl = uploadUrl;
  lvRemote = false; lvRect = null; lvShown = null; lvSearched = null; lvDrag = null; lvZoomReset();
  lvEl("lvResults").innerHTML = ""; lvEl("lvNote").hidden = true; lvEl("lvCount").textContent = "";
  const img = lvEl("lvImg");
  img.onload = () => { if (lvRemote || lvUrl !== uploadUrl) return; lvOpen(); lvStageMode("select"); lvSetState("idle"); lvFitLoop(); lvRenderSvg(); };
  img.onerror = () => { if (lvRemote || lvUrl !== uploadUrl) return; lvUploadError("img_file_decode"); URL.revokeObjectURL(uploadUrl); lvUrl = null; };
  img.src = lvUrl;
  lvEl("lvThumb").src = lvUrl;
  lvEl("lvTools").style.display = "";
  lvSheetSet("peek");
  const _hint = lvEl("lvHint"); if (_hint) _hint.style.display = "";
  const sb = lvEl("lvSheetBody"); if (sb) sb.scrollTop = 0;
}
let lvZoom = { s: 1, tx: 0, ty: 0 };
function lvApplyZoom(){
  const wrap = lvEl("lvWrap");
  if (!wrap) return;
  if (lvZoom.s <= 1.001) { lvZoom.s = 1; lvZoom.tx = 0; lvZoom.ty = 0; }
  else {
    const mx = wrap.clientWidth * lvZoom.s * 0.5, my = wrap.clientHeight * lvZoom.s * 0.5;
    lvZoom.tx = Math.max(-mx, Math.min(mx, lvZoom.tx));
    lvZoom.ty = Math.max(-my, Math.min(my, lvZoom.ty));
  }
  wrap.style.transform = lvZoom.s === 1 ? "" : "translate(" + lvZoom.tx + "px, " + lvZoom.ty + "px) scale(" + lvZoom.s + ")";
  const fb = lvEl("lvFitBtn"); if (fb) fb.hidden = lvZoom.s <= 1.001;
}
function lvZoomReset(){ lvZoom = { s: 1, tx: 0, ty: 0 }; lvApplyZoom(); }
function lvZoomTo(s, frac){
  const wrap = lvEl("lvWrap");
  lvZoom.s = s;
  lvZoom.tx = (0.5 - frac.x) * wrap.clientWidth * (s - 1) * 0.7;
  lvZoom.ty = (0.5 - frac.y) * wrap.clientHeight * (s - 1) * 0.7;
  lvApplyZoom();
}
function lvBind(){
  const wrap = lvEl("lvWrap"), cv = lvEl("lvDraw");
  if (!wrap || !cv) return;
  const ptrs = new Map();
  let pinch = null, downT = 0;
  const pt = e => {
    const b = lvEl("lvImg").getBoundingClientRect();
    return { x: Math.min(1, Math.max(0, (e.clientX - b.left) / b.width)), y: Math.min(1, Math.max(0, (e.clientY - b.top) / b.height)) };
  };
  const zone = p => {
    if (!lvRect) return "trace";
    const b = lvEl("lvImg").getBoundingClientRect();
    const px = p.x * b.width, py = p.y * b.height;
    const x0 = lvRect.x0 * b.width, x1 = lvRect.x1 * b.width, y0 = lvRect.y0 * b.height, y1 = lvRect.y1 * b.height;
    const M = 26;
    if (px < x0 - M || px > x1 + M || py < y0 - M || py > y1 + M) return "trace";
    const corners = [["nw", x0, y0], ["ne", x1, y0], ["sw", x0, y1], ["se", x1, y1]];
    let best = null, bd = 1e9;
    for (const c of corners) { const d = Math.hypot(px - c[1], py - c[2]); if (d < bd) { bd = d; best = c[0]; } }
    if (bd <= M * 1.15) return best;
    if (Math.abs(py - y0) <= M * 0.7) return "n";
    if (Math.abs(py - y1) <= M * 0.7) return "s";
    if (Math.abs(px - x0) <= M * 0.7) return "w";
    if (Math.abs(px - x1) <= M * 0.7) return "e";
    return "move";
  };
  wrap.addEventListener("pointerdown", e => {
    if (lvRemote) return;
    ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (ptrs.size === 2) {
      lvDrag = null;
      const a = [...ptrs.values()];
      pinch = { d: Math.hypot(a[0].x - a[1].x, a[0].y - a[1].y), s: lvZoom.s, tx: lvZoom.tx, ty: lvZoom.ty, mx: (a[0].x + a[1].x) / 2, my: (a[0].y + a[1].y) / 2 };
      lvCvClear();
      return;
    }
    e.preventDefault();
    try { wrap.setPointerCapture(e.pointerId); } catch {}
    downT = performance.now();
    const p = pt(e), z = zone(p);
    if (z === "trace" && lvZoom.s > 1.02) {
      lvDrag = { mode: "pan", sx: e.clientX, sy: e.clientY, tx: lvZoom.tx, ty: lvZoom.ty };
    } else if (z === "trace") {
      lvSettleGen++;
      cv.style.opacity = "";
      lvDrag = { mode: "trace", pts: [p], lx: e.clientX, ly: e.clientY };
      lvCvSetup();
      lvCvClear();
    } else {
      lvDrag = { mode: z, start: p, orig: {...lvRect} };
    }
  });
  wrap.addEventListener("pointermove", e => {
    if (ptrs.has(e.pointerId)) ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch && ptrs.size === 2) {
      const a = [...ptrs.values()];
      const d = Math.hypot(a[0].x - a[1].x, a[0].y - a[1].y), mx = (a[0].x + a[1].x) / 2, my = (a[0].y + a[1].y) / 2;
      lvZoom.s = Math.min(4, Math.max(1, pinch.s * (d / Math.max(20, pinch.d))));
      lvZoom.tx = pinch.tx + (mx - pinch.mx);
      lvZoom.ty = pinch.ty + (my - pinch.my);
      lvApplyZoom();
      return;
    }
    if (!lvDrag) return;
    if (lvDrag.mode === "pan") {
      lvZoom.tx = lvDrag.tx + (e.clientX - lvDrag.sx);
      lvZoom.ty = lvDrag.ty + (e.clientY - lvDrag.sy);
      lvApplyZoom();
      return;
    }
    const p = pt(e);
    if (lvDrag.mode === "trace") {
      if (Math.hypot(e.clientX - lvDrag.lx, e.clientY - lvDrag.ly) >= 1.5 || lvDrag.pts.length < 2) {
        lvDrag.pts.push(p); lvDrag.lx = e.clientX; lvDrag.ly = e.clientY;
      }
      lvDrawTrail(lvDrag.pts);
      return;
    }
    const o = lvDrag.orig, dx = p.x - lvDrag.start.x, dy = p.y - lvDrag.start.y;
    let r = {...o};
    if (lvDrag.mode === "move") {
      const w = o.x1 - o.x0, h = o.y1 - o.y0;
      r.x0 = Math.min(1 - w, Math.max(0, o.x0 + dx)); r.y0 = Math.min(1 - h, Math.max(0, o.y0 + dy));
      r.x1 = r.x0 + w; r.y1 = r.y0 + h;
    } else {
      if (lvDrag.mode.includes("w")) r.x0 = p.x;
      if (lvDrag.mode.includes("e")) r.x1 = p.x;
      if (lvDrag.mode.includes("n")) r.y0 = p.y;
      if (lvDrag.mode.includes("s")) r.y1 = p.y;
      if (r.x1 - r.x0 < 0.03) { if (lvDrag.mode.includes("w")) r.x0 = r.x1 - 0.03; else r.x1 = r.x0 + 0.03; }
      if (r.y1 - r.y0 < 0.03) { if (lvDrag.mode.includes("n")) r.y0 = r.y1 - 0.03; else r.y1 = r.y0 + 0.03; }
      r.x0 = Math.max(0, Math.min(1, r.x0)); r.y0 = Math.max(0, Math.min(1, r.y0));
      r.x1 = Math.max(0, Math.min(1, r.x1)); r.y1 = Math.max(0, Math.min(1, r.y1));
    }
    lvRect = r;
    if (!lvShown) lvShown = {...r};
    lvGlideStart();
  });
  const up = e => {
    const wasPinch = !!pinch;
    ptrs.delete(e.pointerId);
    if (pinch && ptrs.size < 2) pinch = null;
    if (wasPinch) { lvDrag = null; return; }
    if (!lvDrag) return;
    if (lvDrag.mode === "trace") {
      const pts = lvDrag.pts;
      let x0 = 1, y0 = 1, x1 = 0, y1 = 0;
      for (const q of pts) { x0 = Math.min(x0, q.x); y0 = Math.min(y0, q.y); x1 = Math.max(x1, q.x); y1 = Math.max(y1, q.y); }
      if (x1 - x0 >= 0.025 && y1 - y0 >= 0.025) lvSettle({ x0, y0, x1, y1 });
      else {
        lvCvClear();
        if (performance.now() - downT < 280 && pts.length <= 3) {
          if (lvZoom.s > 1.02) lvZoomReset(); else lvZoomTo(2.4, pts[0]);
        }
      }
    } else if (lvDrag.mode === "pan") {
      if (performance.now() - downT < 280 && Math.hypot(lvZoom.tx - lvDrag.tx, lvZoom.ty - lvDrag.ty) < 6) lvZoomReset();
    } else {
      lvGlideStart();
    }
    lvDrag = null;
  };
  wrap.addEventListener("pointerup", up);
  wrap.addEventListener("pointercancel", up);
}
function lvUploadError(key){
  lvEl("spImgDropError").hidden = !key;
  lvEl("spImgDropErrorText").textContent = key ? tr(key) : "";
}

// Called only after the host has initialized all of its own declarations.
function initImageLens(){
lvEl('lvResults').addEventListener('click',event=>{
 const button=event.target.closest('[data-metadata-retry]');if(!button)return;
 event.preventDefault();button.disabled=true;imageFetchRecord(button.dataset.metadataRetry);
});
window.addEventListener("boopa:catalog-ready",()=>{
  imageEnrichCatalogBookmarks();
  if(typeof lvCatalogUpdated === "function")lvCatalogUpdated();
  lvRefreshCatalog();
});
lvEl("lvBack").addEventListener("click", lvClose);
lvEl("lvFitBtn").addEventListener("click", lvZoomReset);
(function(){
  const grab = lvEl("lvGrab"), sh = lvEl("lvSheet"), view = lvEl("lensView");
  if (!grab || !sh) return;
  let drag = null;
  grab.addEventListener("pointerdown", e => {
    e.preventDefault();
    try { grab.setPointerCapture(e.pointerId); } catch {}
    drag = { y: e.clientY, h: sh.clientHeight, moved: false };
    sh.classList.remove("anim");
  });
  grab.addEventListener("pointermove", e => {
    if (!drag) return;
    const maxH = Math.max(200, view.clientHeight - 56);
    const h = Math.max(34, Math.min(maxH, drag.h + (drag.y - e.clientY)));
    if (Math.abs(h - drag.h) > 4) drag.moved = true;
    sh.style.height = h + "px";
  });
  const end = () => {
    if (!drag) return;
    const maxH = Math.max(200, view.clientHeight - 56);
    if (!drag.moved) {
      lvSheetSet(sh.clientHeight > lvPeekH() + 22 ? "peek" : "max");
    } else {
      lvSheetSet(sh.clientHeight > (lvPeekH() + maxH) / 2 ? "max" : "peek");
    }
    drag = null;
  };
  grab.addEventListener("pointerup", end);
  grab.addEventListener("pointercancel", end);
})();
lvEl("spImgDropErrorClose").addEventListener("click", () => lvUploadError(""));
if (lvEl("spImgDrop")) lvEl("spImgDrop").addEventListener("click", () => lvEl("spImgFile").click());
if (window.BoopaImageDrop) {
  BoopaImageDrop.bind({ zone: lvEl("spImgDrop") || lvEl("lvStage"), input: lvEl("spImgFile"), onFile: lvOpenUpload, onError: lvUploadError });
} else {
  // A failed optional helper download must not stop the main page or file picker.
  lvEl("spImgFile").addEventListener("change", e => { const f = e.target.files && e.target.files[0]; e.target.value = ""; lvOpenUpload(f); });
}
lvEl("lvWhole").addEventListener("click", () => { lvRect = null; lvShown = null; lvRenderSvg(); lvSearched = null; lvRunSearch(); });
lvEl("lvRetake").addEventListener("click", () => { lvClose(); lvEl("spImgFile").click(); });
window.addEventListener("resize", () => { if (!lvEl("lensView").hidden) { lvFitBox(); lvRenderSvg(); } });
lvBind();
document.addEventListener("keydown", e => {
  if (lvEl("lensView").hidden) return;
  if (e.key === "Escape") { lvClose(); return; }
  if (e.key !== "Tab") return;
  const view = lvEl("lensView");
  const items = [...view.querySelectorAll('button, a[href], [tabindex="0"]')].filter(el => {
    if (el.disabled) return false;
    for (let n=el; n && n!==view; n=n.parentElement) if (n.hidden || getComputedStyle(n).display==="none" || getComputedStyle(n).visibility==="hidden") return false;
    return true;
  });
  const first=items[0], last=items[items.length-1];
  if (!first) return;
  if (e.shiftKey && (document.activeElement===first || !items.includes(document.activeElement))) { e.preventDefault(); last.focus({preventScroll:true}); }
  else if (!e.shiftKey && (document.activeElement===last || !view.contains(document.activeElement))) { e.preventDefault(); first.focus({preventScroll:true}); }
});

}
