const { JSDOM, VirtualConsole } = require(process.argv[2] || 'jsdom');
const fs = require('fs'), assert = require('assert/strict');
const root = require('path').join(__dirname, '..');
const source = fs.readFileSync(root + '/extension/content.js', 'utf8').replace('    main();', '    window.review = { injectTracker, getSwitchPalette, parseThemeColor, themeContrast };');
const fixtures = require(root + '/test/fixtures/booth-page-contexts.json');
const history = [2000,2000,2000,2000,2000,9999999].map((price,i)=>({date:`2026-05-0${i+1}`,price}));
(async () => {
for (const locale of ['ja','en','ko','zh-cn','zh-tw']) for (const type of ['shop','marketplace']) {
 const errors=[], virtualConsole=new VirtualConsole(); virtualConsole.on('jsdomError', e => errors.push(e));
 const d=new JSDOM(`<html lang="${locale}"><head><style>${fixtures[type].css} body {background:#fff;color:#333}</style></head><body>${fixtures[type].html}</body></html>`, {url:fixtures[type].url,runScripts:'outside-only',virtualConsole});
 const w=d.window; w.HTMLCanvasElement.prototype.getContext=()=>new Proxy({}, {get:(o,k)=>k==='measureText'?()=>({width:10}):()=>{}});
 w.chrome={storage:{local:{get:(defaults, cb)=>cb(defaults)}}}; w.eval(source);
 w.review.injectTracker({isDemo:false,data:{'長い商品名 한국어 中文 English':history}});
 const c=w.document.querySelector('.booth-price-tracker-container'), b=c.querySelector('[role=switch]');
 assert.equal(c.style.getPropertyValue('--boopa-switch-ink'),'rgb(51, 51, 51)');
 b.focus(); assert.equal(w.document.activeElement,b); assert.equal(b.getAttribute('aria-checked'),'false');
 b.click(); assert.equal(b.getAttribute('aria-checked'),'true');
 w.document.body.style.backgroundColor='#181818'; w.document.body.style.color='#eee';
 await new Promise(r=>setTimeout(r,40));
 assert.equal(c.style.getPropertyValue('--boopa-switch-ink'),'rgb(238, 238, 238)');
 assert.equal(w.document.activeElement,b); assert.equal(b.getAttribute('aria-checked'),'true');
 b.click(); assert.equal(b.getAttribute('aria-checked'),'false');
 w.document.body.style.backgroundColor='#fff'; w.document.body.style.color='#333';
 await new Promise(r=>setTimeout(r,40));
 assert.equal(c.style.getPropertyValue('--boopa-switch-ink'),'rgb(51, 51, 51)');
 let cleaned=false; const cleanup=c.boopaCleanup; c.boopaCleanup=()=>{cleaned=true;cleanup();}; c.remove();
 await new Promise(r=>setTimeout(r,40)); assert.equal(cleaned,true); assert.deepEqual(errors,[]);
 w.close(); console.log(`${type}/${locale}: injection, light/dark/light, both states, focus preservation, removal cleanup PASS`);
}
})().catch(e=>{console.error(e);process.exitCode=1});
