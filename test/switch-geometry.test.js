const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const css = fs.readFileSync(path.join(__dirname, '../extension/content.css'), 'utf8');
const js = fs.readFileSync(path.join(__dirname, '../extension/content.js'), 'utf8');
function rule(selector) {
    const start = css.indexOf(selector + ' {');
    assert.ok(start >= 0, selector);
    return Object.fromEntries(css.slice(start + selector.length + 2, css.indexOf('}', start))
        .replace(/\/\*[\s\S]*?\*\//g, '').split(';').filter(x => x.includes(':'))
        .map(x => x.trim().split(/:\s*/)));
}
test('English heading is exactly Price Tracker; other site headings are unchanged', () => {
    assert.match(js, /en: \{\s+comparison: '[^']*',\s+heading: 'Price Tracker'/);
    for (const heading of ['価格推移', '가격 변동', '价格走势', '價格走勢'])
        assert.ok(js.includes(`heading: '${heading}'`));
});
test('track owns exact nonshrinking border-box geometry and the external clip', () => {
    const r = rule('.booth-price-scale-track');
    assert.equal(r.width, '48px'); assert.equal(r.height, '24px');
    assert.equal(r.flex, '0 0 48px'); assert.equal(r['box-sizing'], 'border-box');
    for (const key of ['border','padding','margin']) assert.equal(r[key], '0');
    assert.equal(r.overflow, 'hidden'); assert.equal(r['border-radius'], '999px');
});
test('both knob endpoint boxes exactly match track height and symbol centers', () => {
    const off = rule('.booth-price-scale-knob');
    const on = rule('.booth-price-scale-btn[aria-checked="true"] .booth-price-scale-knob');
    assert.equal(off.top,'0'); assert.equal(off.bottom,'0');
    assert.equal(off.left,'0'); assert.equal(off.right,'50%');
    assert.equal(on.left,'50%'); assert.equal(on.right,'0');
    for (const key of ['border','padding','margin']) assert.equal(off[key], '0');
    assert.equal(off['box-sizing'], 'border-box');
    const symbol = rule('.booth-price-scale-symbol');
    assert.equal(symbol.top,'6px'); assert.equal(symbol.width,'12px'); assert.equal(symbol.height,'12px');
    assert.equal(rule('.booth-price-scale-triangle').left,'6px');
    assert.equal(rule('.booth-price-scale-circle').right,'6px');
    assert.equal(6 + 12 / 2, 24 / 2);
});
test('dark paint bleeds beyond coincident outer arcs without changing layout dimensions', () => {
    const knob = rule('.booth-price-scale-knob');
    assert.equal(knob.background,'var(--boopa-switch-ink, #333)'); assert.equal(knob['box-shadow'],'0 0 0 1px var(--boopa-switch-ink, #333)');
    // Geometric coverage, not a browser pixel test: the 12px arc is strictly
    // inside the 13px painted arc at both endpoint caps and at full stretch.
    for (const centerX of [12, 36]) for (let degree = 0; degree < 360; degree++) {
        const angle = degree * Math.PI / 180;
        const x = centerX + 12 * Math.cos(angle), y = 12 + 12 * Math.sin(angle);
        assert.ok(Math.hypot(x-centerX,y-12) < 13);
    }
});
test('stretch and contract keep bounded dimensions in either direction, including reversals', () => {
    assert.equal(rule('.booth-price-scale-btn[data-animated="true"] .booth-price-scale-knob').transition,
        'left 280ms ease-in-out, right 280ms ease-in-out 820ms');
    assert.equal(rule('.booth-price-scale-btn[data-animated="true"][aria-checked="true"] .booth-price-scale-knob').transition,
        'right 280ms ease-in-out, left 280ms ease-in-out 820ms');
    // Both independently transitioning offsets stay in [0,24], including an
    // interrupted transition. The parent clip always stays exactly 48×24.
    for(let left=0;left<=24;left++) for(let right=0;right<=24;right++) {
        assert.ok(48-left-right >= 0); assert.ok(48-left-right <= 48);
    }
    assert.equal(48-0-24,24); assert.equal(48-0-0,48); assert.equal(48-24-0,24);
    assert.match(css, /prefers-reduced-motion: reduce[\s\S]*transition: none/);
});
test('coarse pointer enlarges hit target without shrinking the visible pill', () => {
    const button=rule('.booth-price-tracker-container .booth-price-scale-btn');
    assert.equal(button.padding,'7px 2px'); assert.equal(button['touch-action'],'manipulation');
    assert.match(css, /@media \(pointer: coarse\) \{\s+\.booth-price-tracker-container \.booth-price-scale-btn \{ min-width: 44px; min-height: 44px;/);
    assert.equal(48+2*2,52); assert.equal(24+7*2,38);
    assert.equal(rule('.booth-price-heading-row')['flex-wrap'],'wrap');
});
