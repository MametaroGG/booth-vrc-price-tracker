const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const os=require('node:os');const path=require('node:path');const {saveProductData}=require('../src/scraper');
function setup(t){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'sale-scope-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));return dir;}
const read=dir=>JSON.parse(fs.readFileSync(path.join(dir,'178','1780665.json')));
test('Neil: real history and four variant groups: no title leakage, discounted history retained',async t=>{
 const dir=setup(t),old=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/sale-evidence/neil-history.json')));fs.mkdirSync(path.join(dir,'178'));fs.writeFileSync(path.join(dir,'178','1780665.json'),JSON.stringify(old));
 const names=['利用規約','旧版','リメイク版（おすすめ）','つぶ貝おいしい（お布施用、中身は旧版と変わりません）'];
 await saveProductData({id:'1780665',name:'セール ニール',hasSaleKeyword:true,variations:names.map(name=>({name,price:old.variations[name].at(-1).price,isSale:false}))},{dataDir:dir,today:'2026-10-31'});
 const out=read(dir);assert.deepEqual(names.map(n=>out.variations[n].at(-1).is_sale),[false,true,true,false]);for(const n of names)assert.deepEqual(out.variations[n].slice(0,-1),old.variations[n]);
});
test('initial multi variant title is insufficient, but scoped badge remains sufficient',async t=>{
 const dir=setup(t);await saveProductData({id:'1780665',hasSaleKeyword:true,variations:[{name:'unknown',price:2500,isSale:false},{name:'badge',price:2500,isSale:true},{name:'free',price:0,isSale:false}]},{dataDir:dir,today:'2026-10-31'});assert.deepEqual(Object.values(read(dir).variations).map(h=>h.at(-1).is_sale),[false,true,false]);
});
test('same variant actual price drop works without title; historical high alone does not',async t=>{
 const dir=setup(t);let p={id:'1780665',hasSaleKeyword:false,variations:[{name:'model',price:5000,isSale:false},{name:'donation',price:6000,isSale:false}]};await saveProductData(p,{dataDir:dir,today:'2026-10-29'});p.variations[0].price=2500;await saveProductData(p,{dataDir:dir,today:'2026-10-30'});assert.equal(read(dir).variations.model.at(-1).is_sale,true);await saveProductData(p,{dataDir:dir,today:'2026-10-31'});assert.equal(read(dir).variations.model.at(-1).is_sale,false);
});
test('known limitation: old higher price plus stale promotional title remains positive',async t=>{
 const dir=setup(t);const p={id:'1780665',hasSaleKeyword:true,variations:[{name:'model',price:5000,isSale:false},{name:'donation',price:6000,isSale:false}]};await saveProductData(p,{dataDir:dir,today:'2020-01-01'});p.variations[0].price=2500;await saveProductData(p,{dataDir:dir,today:'2026-10-31'});assert.equal(read(dir).variations.model.at(-1).is_sale,true);assert.equal(read(dir).variations.donation.at(-1).is_sale,false);
});
test('single variant title behavior intentionally unchanged',async t=>{const dir=setup(t);await saveProductData({id:'1780665',hasSaleKeyword:true,variations:[{name:'only',price:5000,isSale:false}]},{dataDir:dir,today:'2026-10-31'});assert.equal(read(dir).variations.only[0].is_sale,true);});
test('all seven official current Neil IDs retain same-variant scope and history',async t=>{
 const dir=setup(t),old=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/sale-evidence/neil-history.json'))),official=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/sale-evidence/neil-official.json')));fs.mkdirSync(path.join(dir,'178'));fs.writeFileSync(path.join(dir,'178','1780665.json'),JSON.stringify(old));
 await saveProductData({id:'1780665',name:'セール ニール',hasSaleKeyword:true,variations:official.variations.map(v=>({...v,variantId:v.id,isSale:false}))},{dataDir:dir,today:'2026-10-31'});const out=read(dir);
 for(const v of official.variations){const key=out.variation_keys[v.id];assert.equal(out.variations[key].at(-1).is_sale,v.price===2500,v.name);assert.deepEqual(out.variations[key].slice(0,-1),old.variations[key]);}
});
test('future dated high does not corroborate a multi variant title',async t=>{
 const dir=setup(t);fs.mkdirSync(path.join(dir,'178'));fs.writeFileSync(path.join(dir,'178','1780665.json'),JSON.stringify({id:'1780665',variations:{model:[{date:'2027-01-01',price:5000,is_sale:false},{date:'2026-10-30',price:2500,is_sale:false}],donation:[]}}));
 await saveProductData({id:'1780665',hasSaleKeyword:true,variations:[{name:'model',price:2500,isSale:false},{name:'donation',price:6000,isSale:false}]},{dataDir:dir,today:'2026-10-31'});assert.equal(read(dir).variations.model.find(e=>e.date==='2026-10-31').is_sale,false);
});
