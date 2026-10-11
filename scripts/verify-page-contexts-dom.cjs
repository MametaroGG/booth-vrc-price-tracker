// DOM + computed-style contract, not browser pixel/layout verification.
const {JSDOM}=require(process.argv[2] || 'jsdom');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..');
const source=fs.readFileSync(path.join(root,'extension/content.js'),'utf8');
const css=fs.readFileSync(path.join(root,'extension/content.css'),'utf8');
const fixtures=require('../test/fixtures/booth-page-contexts.json');
const productName='長い商品名_LongUnbrokenProductName'.repeat(8);
const data={[productName]:[2000,2000,9999999,1600,1600,2000].map((price,i)=>({date:`2026-05-${String(i+1).padStart(2,'0')}`,price}))};
// jsdom does not perform container layout. Resolve the query for explicit fixture
// widths to check the CSS cascade/DOM contract, not browser width or wrapping.
const compactRule=css.match(/@container boopa-history \(max-width: 340px\)\s*\{([\s\S]*?\n    \})\s*\}/)[1];
for(const width of [240,295,320,345.594,480])
for(const context of ['marketplace','shop']) for(const lang of ['ja','en','ko','zh-cn','zh-tw']) {
 const f=fixtures[context];
 const dom=new JSDOM(`<html lang="${lang}"><head><style>${f.css}</style><style>${css}</style><style>.variations { width: ${width}px; } ${width<=340?compactRule:""}</style></head><body>${f.html}</body></html>`,{url:f.url,runScripts:'outside-only'});
 const w=dom.window;
 w.console={log(){}};
 w.chrome={storage:{local:{get:(d,cb)=>cb(d),set(){}}}};
 w.HTMLCanvasElement.prototype.getContext=()=>new Proxy({},{get:()=>()=>{}});
 w.eval(source.replace('    main();','    globalThis.review={injectTracker};'));
 w.review.injectTracker({data,isDemo:false});
 const q=s=>w.document.querySelector(s), tracker=q('.booth-price-tracker-container');
 assert.equal(q('.variations').firstElementChild,tracker);
 assert.equal(w.getComputedStyle(tracker).textAlign,'left');
 assert.equal(w.getComputedStyle(tracker).fontWeight,'400');
 assert.equal(w.getComputedStyle(tracker).fontSize,'16px');
 assert.equal(w.getComputedStyle(q('.booth-price-range-btn')).fontWeight,'400');
 const summary=q('.booth-price-overflow-details'); summary.open=true;
 const table=q('.booth-price-history-table');
 assert.equal(table.tagName,'TABLE');
 assert.equal(table.querySelectorAll('th').length,3);
 const cells=table.querySelectorAll('tbody tr:first-child td');
 assert.equal(cells.length,3);
 assert.equal(w.getComputedStyle(cells[0]).padding,width<=340?'7px 4px':'7px 10px');
 assert.equal(cells[0].textContent,productName);
 assert.equal(w.getComputedStyle(cells[0]).overflowWrap,'anywhere');
 assert.equal(w.getComputedStyle(table).minWidth,'0');
 for(const cell of [cells[1],cells[2]]) {
  assert.equal(w.getComputedStyle(cell).whiteSpace,'nowrap');
  assert.equal(w.getComputedStyle(cell).width,'1%');
 }
 assert.equal(w.getComputedStyle(cells[2]).textAlign,'right');
 assert.match(cells[2].textContent,/9,999,999/);
 const switchBtn=q('.booth-price-scale-btn');
 switchBtn.focus();
 for(let i=0;i<4;i++)switchBtn.click();
 assert.equal(w.document.activeElement,switchBtn);
 assert.equal(switchBtn.getAttribute('aria-checked'),'false');
 assert.equal(q('.booth-price-overflow-details').open,true);
 assert.equal(q('.booth-price-range-selector').children.length,8);
 tracker.boopaCleanup(); w.close();
}
console.log('PASS: both observed BOOTH context shells × five languages × five fixture widths (240–480px; container rule resolved explicitly, not browser layout); actual injected DOM/order, explicit typography/alignment, three-column cell spacing/right prices, disclosure, switch/focus, 8 ranges. Not browser pixel QA.');
