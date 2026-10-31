const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {scrapeProductDetails,saveProductData}=require('../src/scraper');
const parse = async (name, variant='default', cls='') => (await scrapeProductDetails('2631238',{get:async()=>({status:200,data:`<h2>${name}</h2><div class="variation-item"><span class="variation-name">${variant}</span><span class="variation-price ${cls}">500円</span><button data-product-variant="4318048"></button></div>`})})).product;
test('embedded and descriptive OFF are not sale evidence', async()=>{
 for(const n of ['Coffee Tables','Office Desk','Official 3Ditem','unofficial avatar','Coffin','Turn OFF switch','Off-shoulder dress','OFF SHOULDER','Kick-off','OFFLIMIT','Offset Wear','30% Official product']) assert.equal((await parse(n)).hasSaleKeyword,false,n);
});
test('explicit number and percent or currency OFF remains evidence',async()=>{
 for(const n of ['30%OFF Coffee','Coffee 30% OFF','30％ＯＦＦ','３０％ ＯＦＦ','OFF 30%','500円 OFF','OFF 500円','12.5% off','1,000円OFF','50%OFF対応']) assert.equal((await parse(n)).hasSaleKeyword,true,n);
});
test('existing Japanese and SALE evidence remains intact',async()=>{
 for(const n of ['セール中 Coffee','期間限定 Coffee','割引 Coffee','SALE Coffee','BigSALE']) assert.equal((await parse(n)).hasSaleKeyword,true,n);
});
test('variant sale badge and explicit DOM class stay independent',async()=>{
 const a=await parse('Coffee Tables','default (30% OFF)');assert.equal(a.hasSaleKeyword,false);assert.equal(a.variations[0].isSale,true);
 const b=await parse('Coffee Tables','default','is-sale');assert.equal(b.hasSaleKeyword,false);assert.equal(b.variations[0].isSale,true);
});
test('same price Coffee no longer writes sale; real price drop still does',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'sale-title-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const p=await parse('Coffee Tables');await saveProductData(p,{dataDir:dir,today:'2026-10-30'});await saveProductData(p,{dataDir:dir,today:'2026-10-31'});
 let data=JSON.parse(fs.readFileSync(path.join(dir,'263','2631238.json')));assert.deepEqual(data.variations.default.map(x=>x.is_sale),[false,false]);
 p.variations[0].price=400;await saveProductData(p,{dataDir:dir,today:'2026-11-01'});data=JSON.parse(fs.readFileSync(path.join(dir,'263','2631238.json')));assert.equal(data.variations.default[2].is_sale,true);
});
test('appending corrected observation does not rewrite historical flags',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'sale-title-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 fs.mkdirSync(path.join(dir,'263'));const original=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/sale-evidence/coffee-history.json')));fs.writeFileSync(path.join(dir,'263','2631238.json'),JSON.stringify(original));
 await saveProductData(await parse('Coffee Tables'),{dataDir:dir,today:'2026-10-31'});const out=JSON.parse(fs.readFileSync(path.join(dir,'263','2631238.json')));
 assert.deepEqual(out.variations.default.slice(0,-1),original.variations.default);assert.equal(out.variations.default.at(-1).is_sale,false);
});

test("normalization expands OFF only, not other legacy keyword rules",async()=>{
 for(const n of ["ＳＡＬＥ Coffee", "ｾｰﾙ Coffee"]) assert.equal((await parse(n)).hasSaleKeyword,false,n);
 assert.equal((await parse("３０％ＯＦＦ Coffee")).hasSaleKeyword,true);
});
