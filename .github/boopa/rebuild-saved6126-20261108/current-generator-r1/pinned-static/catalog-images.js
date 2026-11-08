/* Hydrate only rendered search-card images from the pinned static catalog.
   Never changes a title, price, count, filter or item identity. */
(function(root){
 'use strict';
 function createCatalogImages({reader,root:host,resolve,isOpen=()=>true}){
  let epoch=0,controller=null;
  function cancel(){epoch++;if(controller)controller.abort();controller=null;}
  async function hydrate(){
   cancel();if(!reader.isCore()||!isOpen())return;
   const generation=epoch,version=reader.revision(),targets=Array.from(host.querySelectorAll('[data-core-image]'));
   const current=()=>generation===epoch&&version===reader.revision()&&isOpen();
   controller=new AbortController();const requestController=controller,signal=controller.signal,timer=setTimeout(()=>requestController.abort(),8000);let next=0;
   async function worker(){while(next<targets.length&&current()){
    const target=targets[next++],id=target.getAttribute('data-core-image');
    try{
     const raw=await reader.image(id,{signal});
     if(!current()||!target.isConnected||!host.contains(target)||target.getAttribute('data-core-image')!==id)continue;
     if(!raw){target.removeAttribute('data-core-image');continue;}
     const img=host.ownerDocument.createElement('img');img.src=resolve(raw);img.alt='';img.loading='lazy';img.decoding='async';img.referrerPolicy='no-referrer';
     img.onerror=()=>{if(img.isConnected&&host.contains(img)){target.removeAttribute('data-core-image');img.replaceWith(target);}};
     target.replaceWith(img);
    }catch{/* Keep the existing icon/title/price; another render can retry. */}
   }}
   try{await Promise.all(Array.from({length:Math.min(4,targets.length)},worker));}finally{clearTimeout(timer);}
  }
  return {hydrate,cancel};
 }
 if(typeof module==='object'&&module.exports)module.exports={createCatalogImages};
 else root.createBoopaCatalogImages=createCatalogImages;
})(typeof window==='undefined'?globalThis:window);
