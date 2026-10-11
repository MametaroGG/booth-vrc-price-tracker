const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../extension/content.js'), 'utf8');
const context = { window: { location: { pathname: '/items/7635325' } }, console };
vm.runInNewContext(source.replace('    main();', '    globalThis.chart = { findSeparatedHighPoints, getLowestPriceInfo, mergeVariations, drawChart };'), context);
const { findSeparatedHighPoints, getLowestPriceInfo, mergeVariations, drawChart } = context.chart;
const history = prices => prices.map((price, i) => ({ date: `2026-05-${String(i + 1).padStart(2, '0')}`, price }));

test('separated high observations need five distinct ordinary dates and 80% support', () => {
    assert.equal(findSeparatedHighPoints(history([2000, 2000, 1600, 1600, 2000, 9999999])).size, 1);
    assert.equal(findSeparatedHighPoints(history([2000, 2000, 1600, 2000, 9999999])).size, 0);
    assert.equal(findSeparatedHighPoints(history([2000, 2000, 2000, 2000, 2000, 9999999, 9999999])).size, 0);
    assert.equal(findSeparatedHighPoints(history([2000, 2000, 2000, 2000, 2000, 9999999]).map(d => ({...d, date: '2026-05-01'}))).size, 0);
});
test('ordinary sales, legitimate tiers, and zero values remain intact', () => {
    for (const prices of [[1600, 2000, 3200, 4000, 1600, 4000], [0,0,0,0,0,2000], [2000], []]) {
        assert.equal(findSeparatedHighPoints(history(prices)).size, 0);
    }
    assert.equal(findSeparatedHighPoints(history([0, 2000, 2000, 2000, 2000, 2000, 9999999])).size, 1);
});
test('minimum badge suppresses unsupported extreme comparisons and never claims a regular price', () => {
    const info = getLowestPriceInfo(history([2000, 9999999, 1600, 0]));
    assert.equal(info.minPrice, 1600);
    assert.equal(info.minDate, '2026-05-03');
    assert.equal(info.regularPrice, undefined);
    assert.equal(info.discountPct, undefined);
    assert.equal(info.comparisonPct, undefined);
    assert.equal(getLowestPriceInfo(history([0])), null);
    assert.equal(getLowestPriceInfo(history([Infinity, NaN])), null);
});
test('ordinary repeated 4000 reference restores the original minus 20 percent chip for 3200', () => {
    const data = history([4000, 4000, 3200, 4000]);
    const before = JSON.stringify(data);
    const info = getLowestPriceInfo(data);
    assert.equal(info.comparisonPrice, 4000);
    assert.equal(info.comparisonPct, 20);
    assert.equal(info.minPrice, 3200);
    assert.equal(info.minDate, '2026-05-03');
    assert.equal(info.regularPrice, undefined);
    assert.equal(JSON.stringify(data), before);
});
test('comparison evidence requires distinct dates and suppresses sparse or unresolved extreme baselines', () => {
    for (const prices of [[4000,3200],[4000],[3200,3200],[9999999,9999999,3200], [64000,64000,3200]])
        assert.equal(getLowestPriceInfo(history(prices)).comparisonPct, undefined);
    const sameDate=history([4000,4000,3200]); sameDate[1].date=sameDate[0].date;
    assert.equal(getLowestPriceInfo(sameDate).comparisonPct, undefined);
    const missingDates=[{price:4000},{price:4000},{price:3200}];
    assert.equal(getLowestPriceInfo(missingDates).comparisonPct, undefined);
    assert.equal(getLowestPriceInfo([]),null);
    assert.equal(getLowestPriceInfo(history([0,0])),null);
});
test('classified high records do not become comparison baselines or alter factual minimum', () => {
    const data=history([4000,4000,3200,3200,4000,9999999]);
    const before=JSON.stringify(data), info=getLowestPriceInfo(data);
    assert.equal(findSeparatedHighPoints(data).size,1);
    assert.equal(info.comparisonPrice,4000); assert.equal(info.comparisonPct,20);
    assert.equal(info.minDate,'2026-05-04'); assert.equal(info.current,9999999);
    assert.equal(JSON.stringify(data),before);
    assert.equal(getLowestPriceInfo(history([3200,3200,3200,3200,4000,9999999])).comparisonPct,undefined);
});
function canvasFixture() {
    const paths = [];
    const ctx = new Proxy({}, { get(target, name) {
        if (name in target) return target[name];
        return (...args) => paths.push([name, ...args]);
    } });
    const status = {}; const toggle = {setAttribute() {}}; const tip = {style: {}};
    context.window.devicePixelRatio = 1;
    context.window.getComputedStyle = () => ({color: '#333'});
    const canvas = { clientWidth: 360, clientHeight: 150, dataset: {hasListener: 'true'}, getContext: () => ctx,
        parentElement: {querySelector: selector => ({'.booth-price-scale-status': status, '.booth-price-scale-btn': toggle, '.booth-chart-tooltip': tip})[selector]} };
    return {canvas, paths, status, toggle};
}
test('chart zooms with overflow data, restores full range, and never bridges excluded point', () => {
    const data = history([2000, 2000, 9999999, 1600, 1600, 2000]);
    const original = JSON.stringify(data);
    const f = canvasFixture();
    drawChart(f.canvas, {single: data}, 'all', null);
    assert.match(f.status.textContent, /上限外 1 件/);
    assert.equal(f.canvas.pointsToHover.filter(p => p.outside).length, 1);
    assert.equal(f.canvas.pointsToHover[2].data.price, 9999999);
    assert.ok(f.paths.filter(p => p[0] === 'moveTo').length >= 5);
    assert.equal(f.paths.filter(p => p[0] === 'lineTo').length, 7); // 2 grid + 3 series + 2 triangle
    drawChart(f.canvas, {single: data}, 'all', null, null, false, {fullRange: true});
    assert.equal(f.status.textContent, '全価格表示');
    assert.equal(f.canvas.pointsToHover.some(p => p.outside), false);
    assert.equal(JSON.stringify(data), original);
});
test('each variation is classified independently and hidden/date-filtered points do not affect axis', () => {
    const f = canvasFixture();
    const cheap = history([100,100,100,100,100,100]);
    const premium = history([10000,10000,10000,10000,10000,10000]);
    drawChart(f.canvas, {cheap, premium}, 'all', null);
    assert.equal(f.status.textContent, '全価格表示');
    const spike = history([2000,2000,2000,2000,2000,9999999]);
    drawChart(f.canvas, {cheap, spike}, 'all', null, new Set(['cheap']));
    assert.equal(f.canvas.pointsToHover.length, 6);
    assert.equal(f.status.textContent, '全価格表示');
    drawChart(f.canvas, {spike}, 1, null);
    assert.equal(f.canvas.pointsToHover.length, 0);
    assert.equal(f.toggle.hidden, true);
    drawChart(f.canvas, {cheap}, 'all', null, new Set());
    assert.equal(f.canvas.pointsToHover.length, 0);
});
test('sale-suffix merging is unchanged and does not mutate source histories', () => {
    const input = {'Single': history([2000]), 'Single (20% OFF)': history([1600]), 'Full set': history([4000])};
    const before = JSON.stringify(input);
    const result = mergeVariations(input);
    assert.equal(Object.keys(result).length, 2);
    assert.equal(result.Single[0].price, 1600);
    assert.equal(result['Full set'][0].price, 4000);
    assert.equal(JSON.stringify(input), before);
});

test('multiple separated high tiers cannot leave a second extreme flattening the chart', () => {
    assert.equal(findSeparatedHighPoints(history([2000,2000,2000,2000,2000,2000,2000,2000,1000000,1000000000])).size, 2);
});

test('the 20x threshold is inclusive and read-only with frozen observations', () => {
    const atBoundary = history([100,100,100,100,100,2000]).map(Object.freeze);
    Object.freeze(atBoundary);
    assert.equal(findSeparatedHighPoints(atBoundary).size, 1);
    assert.equal(findSeparatedHighPoints(history([100,100,100,100,100,1999])).size, 0);
});
