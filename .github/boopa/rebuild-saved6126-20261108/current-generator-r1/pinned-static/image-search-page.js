/* Lightweight standalone host. The lens/crop/search engine is shared with index.html. */
'use strict';
const IMG_API = 'https://nucbox-m7.tailb48431.ts.net:8443';
const I18N = window.IMAGE_SEARCH_I18N || {ja:{}};
let LANG = 'ja', THEME = 'dark';
const readStore=(key,fallback)=>{try{return JSON.parse(localStorage.getItem(key)) ?? fallback;}catch{return fallback;}};
try {
 const lang=localStorage.getItem('boopadb_lang'); const n=(navigator.language||'ja').toLowerCase();
 LANG=I18N[lang]?lang:n.startsWith('en')?'en':n.startsWith('ko')?'ko':n.startsWith('zh')?(n.includes('tw')||n.includes('hk')||n.includes('hant')?'zh-Hant':'zh-Hans'):'ja';
 const theme=localStorage.getItem('boopadb_theme');THEME=theme==='light'||theme==='dark'?theme:matchMedia('(prefers-color-scheme: light)').matches?'light':'dark';
}catch{}
function tr(k,v){let s=(I18N[LANG]&&I18N[LANG][k]) || I18N.ja[k] || k;if(v)for(const key in v)s=s.split('{'+key+'}').join(String(v[key]));return s;}
const el=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function applyImageLocale(){
 document.documentElement.lang=LANG;document.title=tr('img_search')+' | BoopaDB';
 document.querySelectorAll('[data-i]').forEach(n=>n.textContent=tr(n.dataset.i));
 document.querySelectorAll('[data-i-al]').forEach(n=>n.setAttribute('aria-label',tr(n.dataset.iAl)));
 const labels={ja:'日本語',en:'English',ko:'한국어','zh-Hans':'简体中文','zh-Hant':'繁體中文'};
 el('langCur').textContent=labels[LANG];
 el('langMenu').innerHTML=Object.entries(labels).map(([code,name])=>'<button type="button" data-lang="'+code+'" class="'+(code===LANG?'on':'')+'">'+name+'</button>').join('');
 const copy=window.IMAGE_SEARCH_FAQ && (window.IMAGE_SEARCH_FAQ[LANG] || window.IMAGE_SEARCH_FAQ.ja);
 if(copy){
  el('imageExplain').innerHTML=copy.cards.map(c=>'<article><h2>'+esc(c.title)+'</h2><p>'+esc(c.body)+'</p></article>').join('');
  el('imageFaq').innerHTML='<h2 id="imageFaqTitle">'+esc(copy.title)+'</h2>'+copy.items.map(f=>'<details><summary>'+esc(f.q)+'</summary><p>'+esc(f.a)+'</p></details>').join('');
 }
}
function applyImageTheme(){document.documentElement.dataset.theme=THEME;document.querySelector('meta[name="color-scheme"]').content=THEME;}
applyImageLocale();applyImageTheme();
function imageLanguageMenu(open){el('langMenu').classList.toggle('open',open);el('langBtn').setAttribute('aria-expanded',String(open));}
el('langBtn').addEventListener('click',e=>{e.stopPropagation();imageLanguageMenu(!el('langMenu').classList.contains('open'));});
el('langMenu').addEventListener('click',e=>{const button=e.target.closest('[data-lang]');if(!button)return;LANG=button.dataset.lang;try{localStorage.setItem('boopadb_lang',LANG);}catch{}applyImageLocale();renderCurrentResults();imageLanguageMenu(false);el('langBtn').focus();});
document.addEventListener('click',e=>{if(!e.target.closest('.langsw'))imageLanguageMenu(false);});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&el('langMenu').classList.contains('open')){imageLanguageMenu(false);el('langBtn').focus();}});
function imageChromeForLens(open){
 imageLanguageMenu(false);
 document.querySelectorAll('body > header, body > footer').forEach(node=>{node.toggleAttribute('inert',open);if(open)node.setAttribute('aria-hidden','true');else node.removeAttribute('aria-hidden');});
}
window.addEventListener('boopa:lens-open',()=>imageChromeForLens(true));
window.addEventListener('boopa:lens-close',()=>imageChromeForLens(false));
el('themeBtn').addEventListener('click',()=>{THEME=THEME==='dark'?'light':'dark';try{localStorage.setItem('boopadb_theme',THEME);}catch{}applyImageTheme();});
function veilSync(){document.body.style.overflow=el('lensView').hidden?'':'hidden';}
function isoFD(n){if(!n)return '';const s=String(n);return s.slice(0,4)+'-'+s.slice(4,6)+'-'+s.slice(6,8);}
function pxImg(v){return !v?'':String(v).includes('://')?String(v):'https://booth.pximg.net/c/620x620/'+v+'_base_resized.jpg';}
let fullIndex=null, currentApiResults=[], resultRecords=new Map();
function imgHitsFromApi(results){
 currentApiResults=Array.isArray(results)?results:[];
 const byId=new Map((fullIndex||[]).map(e=>[e[0],e]));
 const hits=currentApiResults.filter(r=>/^\d+$/.test(String(r.item_id))).map(r=>{
  const id=String(r.item_id),e=byId.get(id);
  return {id,name:e?e[1]:'BOOTH #'+id,shop:e?e[13]||'':'',image:r.image||(e&&e[10])||'',_catalog:!!e,cur:e?e[3]:null,base:e?e[4]:null,sale:e?!!e[6]:false,at_lowest:e?!!e[7]:false};
 });resultRecords=new Map(hits.map(h=>[h.id,h]));return hits;
}
function savedBookmarks(){const b=readStore('boopadb_bm',[]);return Array.isArray(b)?b:[];}
function lvResultCard(x){return imageResultCard(x,savedBookmarks().some(b=>String(b.id)===String(x.id)),'index.html#item-'+encodeURIComponent(x.id));}
function fillCardPrice(){} // Standalone result renderer already includes catalog prices.
function fillImgs(){}
function lvDecorateResults(hits){resultRecords=new Map(hits.map(h=>[String(h.id),h]));}
function renderCurrentResults(){if(typeof lvRefreshCatalog==='function')lvRefreshCatalog();}
el('lvResults').addEventListener('click',e=>{
 const button=e.target.closest('[data-bookmark]');if(!button)return;
 const id=button.dataset.bookmark,record=resultRecords.get(id);if(!record)return;
 let saved=savedBookmarks();const exists=saved.some(b=>String(b.id)===id);
 saved=exists?saved.filter(b=>String(b.id)!==id):[{id:record.id,name:record.name,shop:record.shop,image:record.image,cur:record.cur},...saved];
 try{localStorage.setItem('boopadb_bm',JSON.stringify(saved));button.setAttribute('aria-pressed',String(!exists));button.textContent=tr(exists?'pp_bm':'pp_bmed');}catch{ /* Keep UI unchanged if storage is unavailable. */ }
});
window.addEventListener('storage',e=>{if(e.key==='boopadb_bm')renderCurrentResults();});
