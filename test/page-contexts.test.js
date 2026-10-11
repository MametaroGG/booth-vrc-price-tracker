const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const css = fs.readFileSync(path.join(__dirname,'../extension/content.css'),'utf8');
const contexts = require('./fixtures/booth-page-contexts.json');
function rule(selector) {
  const start=css.indexOf(selector+' {');
  assert.ok(start>=0,selector);
  return Object.fromEntries(css.slice(start+selector.length+2,css.indexOf('}',start))
    .replace(/\/\*[\s\S]*?\*\//g,'').split(';').filter(x=>x.includes(':')).map(x=>x.trim().split(/:\s*/)));
}
test('both real BOOTH contexts preserve their distinct parent alignment and table collision fixtures',()=>{
  assert.match(contexts.marketplace.css,/text-align: start/);
  assert.match(contexts.shop.css,/text-align: center/);
  assert.match(contexts.shop.css,/#shop_default[^}]+ td[^}]+th \{ padding: 0.618em 0px; text-align: left;/);
  for(const c of [contexts.marketplace,contexts.shop]) assert.match(c.html,/class="variations"/);
});
test('tracker owns inherited typography and alignment but still follows theme color',()=>{
  const r=rule('.booth-price-tracker-container');
  assert.equal(r['text-align'],'left'); assert.equal(r['font-size'],'16px');
  assert.equal(r['font-weight'],'400'); assert.equal(r['line-height'],'1.5');
  assert.equal(r['letter-spacing'],'normal'); assert.equal(r['text-transform'],'none');
  assert.equal(r.color,'inherit'); assert.equal(r.background,'transparent');
  assert.equal(r.width,undefined); // narrower shop column must stay responsive
});
test('range controls no longer depend on host button font/reset defaults',()=>{
  const r=rule('.booth-price-range-btn');
  assert.equal(r['font-family'],'inherit'); assert.equal(r['font-weight'],'400');
  assert.equal(r['font-size'],'11px'); assert.equal(r['line-height'],'1.5');
  assert.equal(r.margin,'0'); assert.equal(r.padding,'2px 8px');
  assert.equal(r['text-transform'],'none'); assert.equal(r['box-sizing'],'border-box');
});
test('table cell spacing and right-aligned prices override the observed ID-scoped shop rules',()=>{
  const cells=rule('.booth-price-history-table td');
  assert.equal(cells.padding,'7px 10px !important');
  assert.equal(cells['text-align'],'left !important');
  assert.equal(rule('.booth-price-history-table td:last-child')['text-align'],'right !important');
  // Neither a table-wide/global important reset nor a fixed background was added.
  assert.doesNotMatch(css,/(?:^|\n)\s*(?:td|th|button)\s*\{/);
});
test('history table follows its own available width without minimum-width floors',()=>{
  assert.equal(rule('.booth-price-heading-row').container,'boopa-history / inline-size');
  const table=rule('.booth-price-overflow-details .booth-price-history-table');
  assert.equal(table.width,'100%'); assert.equal(table['min-width'],'0');
  const name=rule('.booth-price-history-table td:first-child');
  assert.equal(name['min-width'],'0'); assert.equal(name['max-width'],undefined);
  assert.equal(name['overflow-wrap'],'anywhere');
});
test('dates and prices reserve intrinsic width while product names use the remainder',()=>{
  const numeric=rule('.booth-price-history-table td:nth-child(n+2)');
  assert.equal(numeric.width,'1%'); assert.equal(numeric['white-space'],'nowrap');
  assert.equal(numeric['font-variant-numeric'],'tabular-nums');
});
test('narrow columns compact cell padding without hostname or viewport coupling',()=>{
  assert.match(css,/@container boopa-history \(max-width: 340px\)\s*\{\s*\.booth-price-history-table th,\s*\.booth-price-history-table td\s*\{\s*padding: 7px 4px !important;/);
  assert.ok(parseFloat(contexts.shop.observedVariationWidth)<340);
  assert.ok(parseFloat(contexts.marketplace.observedVariationWidth)>340);
});
test('extreme content stays in a keyboard-accessible local scrolling region',()=>{
  const scroll=rule('.booth-price-overflow-details .booth-price-history-scroll');
  assert.equal(scroll['max-width'],'100%'); assert.equal(scroll.overflow,'auto');
  assert.equal(rule('.booth-price-overflow-details')['min-width'],'0');
});

test('closed disclosure keeps intrinsic width outside containment',()=>{
  assert.equal(rule('.booth-price-overflow-details').container,undefined);
  assert.equal(rule('.booth-price-heading-row').width,'100%');
});
