const { JSDOM } = require(process.argv[2] || 'jsdom');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const source = fs.readFileSync(require('node:path').join(__dirname,'../extension/content.js'),'utf8');
const dom = new JSDOM('<div class="item-detail"><div class="variation-price">¥2,000</div></div>', {url:'https://booth.pm/ja/items/123',runScripts:'outside-only'});
const {window:w}=dom;
w.chrome={storage:{local:{get:(d,cb)=>cb(d),set:()=>{}}}};
w.HTMLCanvasElement.prototype.getContext=()=>new Proxy({}, {get:()=>()=>{}});
w.eval(source.replace('    main();','    globalThis.review = { injectTracker };'));
const data={Single:[2000,2000,9999999,1600,1600,2000].map((price,i)=>({date:`2026-05-${String(i+1).padStart(2,'0')}`,price}))};
const original=JSON.stringify(data);
w.review.injectTracker({data,isDemo:false});
const d=w.document, q=s=>d.querySelector(s), btn=q('.booth-price-scale-btn'), row=q('.booth-price-heading-row'), details=q('details'), canvas=q('canvas');
assert.equal(row.textContent.includes('価格推移'),true);
assert.equal(row.contains(btn),true);
assert.equal(btn.tagName,'BUTTON'); assert.equal(btn.type,'button');
assert.equal(btn.getAttribute('role'),'switch'); assert.equal(btn.getAttribute('aria-label'),'全価格を表示');
assert.equal(btn.getAttribute('aria-checked'),'false'); assert.equal(btn.hidden,false);
assert.equal(btn.querySelector('[aria-hidden=true]').className,'booth-price-scale-track');
assert.equal(btn.querySelectorAll('.booth-price-scale-symbol').length,2);
assert.equal(btn.hasAttribute('data-animated'),false);
assert.equal(btn.textContent,'');
assert.equal(canvas.previousElementSibling,null);
assert.deepEqual([...canvas.parentElement.children].filter(el=>el.className!=='booth-chart-tooltip').map(el=>el.className), ['booth-price-tracker-canvas','booth-legend-toggle','booth-price-legend collapsed','booth-lowest-toggle','booth-price-tracker-title']);
assert.equal(row.parentElement.previousElementSibling.className,'booth-lowest-toggle');
assert.equal(q('.item-detail').firstElementChild,canvas.parentElement);
assert.equal(row.nextElementSibling.className,'booth-price-range-selector');
assert.equal(details.hidden,false); assert.match(details.textContent,/9,999,999/);
const markup=btn.innerHTML;
btn.focus();assert.equal(d.activeElement,btn);
for(let i=0;i<12;i++) {btn.click();const full=i%2===0;assert.equal(btn.getAttribute('aria-checked'),String(full));assert.equal(details.hidden,full);assert.equal(canvas.pointsToHover.some(p=>p.outside),!full);assert.equal(btn.innerHTML,markup);assert.equal(btn.getAttribute('data-animated'),'true');assert.equal(d.activeElement,btn);}
details.open=true;assert.equal(details.open,true);details.open=false;
const ranges=[...d.querySelectorAll('.booth-price-range-btn')];ranges[0].click();assert.equal(btn.hidden,true);assert.equal(details.hidden,true);assert.equal(canvas.pointsToHover.length,0);ranges.at(-1).click();assert.equal(btn.hidden,false);assert.equal(btn.getAttribute('aria-checked'),'false');
const legend=q('.booth-price-legend').firstChild;legend.click();assert.equal(btn.hidden,true);legend.click();assert.equal(btn.hidden,false);assert.equal(btn.getAttribute('aria-checked'),'false');
assert.equal(JSON.stringify(data),original);
console.log('PASS: real DOM heading placement, semantic switch, accessible name/state, focus retention, 12 toggles, disclosure, date filter/restore, variation hide/restore, immutable data.');

// Same DOM regression applies to the no-controls demo branch.
q('.booth-price-tracker-container').remove();
w.review.injectTracker({data,isDemo:true});
assert.deepEqual([...q('.booth-price-tracker-container').children].map(el=>el.className),
    ['booth-price-tracker-canvas','booth-price-tracker-title']);
assert.equal(q('.booth-price-scale-btn'),null);
console.log('PASS: demo DOM order and absence of live controls.');
