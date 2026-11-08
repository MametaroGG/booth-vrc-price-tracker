/* Lifecycle adapter: refresh cached projections before repainting any surface. */
(function(){
 let blocked=false;
 function failClosed(){
  if(blocked)return;blocked=true;
  const panel=document.createElement('div');panel.id='current-price-refresh';
  panel.setAttribute('role','alert');panel.style.cssText='position:fixed;inset:0;z-index:2147483647;background:var(--bg,#17171b);color:var(--text,#fff);display:grid;place-content:center;gap:12px';
  let lang='ja';try{lang=localStorage.getItem('boopadb_lang')||'ja';}catch{}
  const labels=({ja:['商品情報の再取得が必要です','再読み込み'],en:['Product information needs refreshing','Reload'],ko:['상품 정보를 다시 불러와야 합니다','새로고침'],'zh-Hans':['需要重新获取商品信息','重新加载'],'zh-Hant':['需要重新取得商品資訊','重新載入']})[lang]||['Product information needs refreshing','Reload'];
  const message=document.createElement('p');message.textContent=labels[0];
  const retry=document.createElement('button');retry.textContent=labels[1];retry.onclick=()=>location.reload();panel.append(message,retry);for(const el of document.body.children)el.inert=true;document.body.append(panel);retry.focus();
 }
 function update(){
  if(blocked)return;
  if(typeof P!=='undefined')Object.assign(P,CurrentPrices.walk(P));
  if(typeof FULL_LISTS!=='undefined'&&FULL_LISTS)FULL_LISTS=CurrentPrices.walk(FULL_LISTS);
  if(typeof LISTS!=='undefined')LISTS=CurrentPrices.walk(LISTS);
  if(typeof SALE_HOME!=='undefined')SALE_HOME=CurrentPrices.walk({on_sale:SALE_HOME}).on_sale;
  if(typeof SALE!=='undefined')SALE=CurrentPrices.walk({on_sale:SALE}).on_sale;
  if(typeof pgItems!=='undefined')pgItems=CurrentPrices.walk(pgItems);
  if(typeof POP!=='undefined')POP=CurrentPrices.walk(POP);
  if(typeof RISING!=='undefined')RISING=CurrentPrices.walk(RISING);
  if(typeof NEWEST!=='undefined')NEWEST=CurrentPrices.walk(NEWEST);
  if(typeof PROD!=='undefined')for(const [id,x] of PROD)PROD.set(id,CurrentPrices.record(x));
  if(typeof spIndex!=='undefined')for(let i=0;i<spIndex.length;i++)spIndex[i]=CurrentPrices.record(spIndex[i]);
  if(typeof fullIndex!=='undefined'&&fullIndex)fullIndex=fullIndex.map(r=>CurrentPrices.row(r,'full'));
  if(typeof spCatalogCache!=='undefined')spCatalogCache={idx:null,hits:null};
  if(typeof _saleIds!=='undefined')_saleIds=null;
  if(typeof _saleSrc!=='undefined')_saleSrc=null;
  if(typeof imageResultMetadata!=='undefined')for(const [id,x] of imageResultMetadata)imageResultMetadata.set(id,CurrentPrices.record(x));
  if(typeof spImgHits!=='undefined')spImgHits=CurrentPrices.walk(spImgHits);
  if(typeof renderStats==='function')renderStats((typeof FULL_LISTS!=='undefined'&&FULL_LISTS||P).stats);
  if(typeof renderSale==='function')renderSale();
  if(typeof renderPersonal==='function')renderPersonal();
  if(typeof setBTab==='function')setBTab(bTab);
  if(typeof renderHeroFromLists==='function')renderHeroFromLists(FULL_LISTS||P);
  if(typeof buildHero==='function'&&typeof heroItems!=='undefined'&&heroItems.length)buildHero(heroItems.map(x=>CurrentPrices.display(x)),true);
  if(typeof renderFeatFromNewest==='function')renderFeatFromNewest((FULL_LISTS||P).newest);
  if(typeof spRender==='function'&&spage.classList.contains('open'))spRender(false);
  if(typeof ppX!=='undefined'&&ppX)renderProdPage(CurrentPrices.record(ppX));
  if(typeof curProd!=='undefined'&&curProd)renderPPBody(CurrentPrices.record(curProd));
  if(typeof rkBuild==='function'){rkBuild();renderRk();}
  if(typeof pgRender==='function')pgRender();
  if(typeof bmRender==='function')bmRender();
  if(typeof histRender==='function')histRender();
  if(typeof renderMosaic==='function')renderMosaic();
  if(typeof renderGrid==='function')renderGrid();
  if(typeof renderSaleList==='function')renderSaleList();
  if(typeof buildFeed==='function'){const f=typeof FULL_LISTS!=='undefined'&&FULL_LISTS||P;buildFeed(f.drops,f.on_sale,f.newest);renderFeed();}
  if(typeof lvRenderResults==='function'&&typeof lvMappedResults==='function')lvRenderResults(lvMappedResults());
 }
 CurrentPrices.subscribe(event=>{if(event.type==='snapshot-mismatch')failClosed();else try{update();}catch(error){failClosed();console.error(error);}});
 const check=()=>CurrentPrices.tick();
 window.addEventListener('pageshow',check);document.addEventListener('visibilitychange',check);
 // Capture runs before click handlers, including repeated taps after sleep.
 for(const event of ['click','input','change','keydown'])document.addEventListener(event,check,true);window.addEventListener('focus',check);
 setInterval(check,1000);check();
})();
