const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../extension/content.js'), 'utf8');
const history = prices => prices.map((price, i) => ({
    date: `2026-05-${String(i + 1).padStart(2, '0')}`, price
}));
const spikeHistory = () => history([2000, 2000, 9999999, 1600, 1600, 2000]);

function fixture(lang='ja') {
    const node = tagName => ({
        tagName, style: {}, children: [], attributes: {},
        appendChild(child) { this.children.push(child); },
        replaceChildren(...children) { this.children = children; },
        setAttribute(name, value) { this.attributes[name] = value; }
    });
    const context = {
        window: {
            location: { pathname: '/items/123' }, devicePixelRatio: 2,
            getComputedStyle: () => ({ color: '#333' })
        },
        document: { createElement: node, documentElement: {lang} },
        console: { log() {} }
    };
    vm.runInNewContext(source.replace('    main();', '    globalThis.review = { drawChart };'), context);
    const tooltip = node(), status = node(), toggle = node(), details = node();
    const toggleHiddenWrites = [];
    Object.defineProperty(toggle, 'hidden', {
        get() { return toggleHiddenWrites.at(-1); },
        set(value) { toggleHiddenWrites.push(value); }
    });
    const events = {};
    const ctx = new Proxy({}, {
        get(target, name) { return name in target ? target[name] : () => {}; }
    });
    const selectors = {
        '.booth-chart-tooltip': tooltip,
        '.booth-price-scale-status': status,
        '.booth-price-scale-btn': toggle,
        '.booth-price-overflow-details': details
    };
    const canvas = {
        clientWidth: 360, clientHeight: 150, offsetLeft: 0, offsetTop: 20, dataset: {},
        getContext: () => ctx,
        getBoundingClientRect: () => ({ left: 0, top: 0 }),
        addEventListener(name, handler) {
            assert.equal(events[name], undefined, 'redraw must not register duplicate listeners');
            events[name] = handler;
        },
        parentElement: { querySelector: selector => selectors[selector] }
    };
    const draw = (variations, active = null, fullRange = false) =>
        context.review.drawChart(canvas, variations, 'all', null, active, false, { fullRange });
    const hover = point => events.mousemove({ clientX: point.x, clientY: point.y });
    const nodeText = n => [n.textContent ?? '', ...n.children.map(nodeText)].join(' ').trim();
    const text = () => nodeText(tooltip);
    return { canvas, tooltip, status, toggle, toggleHiddenWrites, details, events, draw, hover, text, nodeText };
}

test('every point tooltip retains its exact date and price, with literal variation names', () => {
    const f = fixture();
    f.draw({ '<b>literal</b>': spikeHistory() });
    assert.equal(f.details.hidden, false);
    assert.equal(f.details.children[1].children[0].children[1].children.length, 1);
    for (const point of f.canvas.pointsToHover) {
        f.hover(point);
        assert.equal(f.tooltip.style.display, 'block');
        assert.ok(f.text().includes('<b>literal</b>'));
        assert.ok(f.text().includes(point.data.date.replaceAll('-', '/')));
        assert.ok(f.text().includes(point.data.price.toLocaleString()));
        if (point.outside) assert.ok(f.text().includes('規格外'));
        assert.ok(f.tooltip.children.every(child => child.innerHTML === undefined));
    }
    f.events.mouseleave();
    assert.equal(f.tooltip.style.display, 'none');
});

test('repeated full-range toggles clear overflow disclosure and use the latest hover targets', () => {
    const f = fixture();
    const data = spikeHistory();
    for (let i = 0; i < 6; i++) {
        const fullRange = i % 2 === 0;
        f.draw({ single: data }, null, fullRange);
        assert.equal(f.canvas.pointsToHover.some(point => point.outside), !fullRange);
        assert.equal(f.details.hidden, fullRange);
        assert.equal(f.toggle.attributes['aria-checked'], String(fullRange));
        if (fullRange) assert.equal(f.details.children.length, 0);
        else assert.equal(f.details.children[1].children[0].children[1].children.length, 1);
        const point = f.canvas.pointsToHover[2];
        f.hover(point);
        assert.ok(f.text().includes('9,999,999'));
        assert.equal(f.text().includes('規格外'), !fullRange);
    }
});

test('ordinary tooltip preserves product and red SALE header, then separate date and price lines', () => {
    const f = fixture();
    const data = history([4000, 3200, 4000]);
    data[1].is_sale = true;
    f.draw({ '<b>literal</b>': data });
    f.hover(f.canvas.pointsToHover[1]);
    assert.deepEqual(f.tooltip.children.map(n => n.tagName), ['strong','span','br','span','br','span']);
    assert.equal(f.tooltip.children[0].textContent, '<b>literal</b>');
    assert.equal(f.tooltip.children[1].textContent, 'SALE');
    assert.match(f.tooltip.children[1].style.cssText, /background:#ff3838/);
    assert.equal(f.tooltip.children[3].textContent, '2026/05/02');
    assert.equal(f.tooltip.children[5].textContent, '¥3,200');
    assert.ok(f.tooltip.children.every(n => n.innerHTML === undefined));
    f.hover(f.canvas.pointsToHover[0]);
    assert.deepEqual(f.tooltip.children.map(n => n.tagName), ['strong','br','span','br','span']);
});
test('overflow tooltip puts yellow outlier and red SALE badges beside the name with only three lines', () => {
    const f=fixture(), data=spikeHistory(); data[2].is_sale=true;
    f.draw({'<img src=x>':data});
    f.hover(f.canvas.pointsToHover.find(p=>p.outside));
    const row=f.tooltip.children[0];
    assert.deepEqual(row.children.map(n=>n.tagName),['strong','span','span','br','span','br','span']);
    assert.equal(row.children[0].textContent,'<img src=x>');
    assert.equal(row.children[1].textContent,'規格外');
    assert.match(row.children[1].style.cssText,/background:#ffdf00; color:#000/);
    assert.equal(row.children[1].title,'（表示上限外）');
    assert.equal(row.children[2].textContent,'SALE');
    assert.match(row.children[2].style.cssText,/background:#ff3838/);
    assert.equal(row.children[4].textContent,'2026/05/03');
    assert.equal(row.children[6].textContent,'¥9,999,999');
    assert.equal(f.text().includes('表示上限外'),false);
    assert.ok(row.children.every(n=>n.innerHTML===undefined));
});

test('hiding all variations removes stale tooltip targets and overflow disclosure', () => {
    const f = fixture();
    const data = spikeHistory();
    f.draw({ single: data });
    const point = f.canvas.pointsToHover.find(point => point.outside);
    f.hover(point);
    assert.equal(f.tooltip.style.display, 'block');
    f.draw({ single: data }, new Set());
    assert.equal(f.canvas.pointsToHover.length, 0);
    assert.equal(f.tooltip.style.display, 'none');
    assert.equal(f.details.hidden, true);
    assert.equal(f.details.children.length, 0);
    assert.equal(f.toggle.hidden, true);
    f.hover(point);
    assert.equal(f.tooltip.style.display, 'none');
});

test('coincident overflow markers expose both exact recorded prices and clear hidden variations', () => {
    const f = fixture();
    const a = spikeHistory();
    const b = a.map(point => ({ ...point, price: point.price * 2 }));
    f.draw({ a, b });
    f.hover(f.canvas.pointsToHover.find(point => point.outside));
    assert.equal(f.tooltip.children.length, 2);
    assert.equal(f.tooltip.children[0].children[0].textContent, 'a');
    assert.equal(f.tooltip.children[1].children[0].textContent, 'b');
    assert.ok(f.text().includes('¥9,999,999'));
    assert.ok(f.text().includes('¥19,999,998'));
    for (const row of f.tooltip.children) {
        assert.deepEqual(row.children.map(n=>n.tagName),['strong','span','br','span','br','span']);
        assert.equal(row.children[3].textContent,'2026/05/03');
        assert.equal(row.children[1].textContent,'規格外');
    }
    assert.equal(f.details.children[1].children[0].children[1].children.length, 2);
    f.draw({ a, b }, new Set(['b']));
    f.hover(f.canvas.pointsToHover.find(point => point.outside));
    assert.equal(f.tooltip.children.length, 1);
    assert.equal(f.tooltip.children[0].children[0].textContent,'b');
    assert.ok(f.text().includes('¥19,999,998'));
    assert.equal(f.details.children[1].children[0].children[1].children.length, 1);
});

test('all-zero history has finite hover coordinates and exact zero-price tooltips', () => {
    const f = fixture();
    f.draw({ free: history([0, 0, 0, 0, 0, 0]) });
    assert.equal(f.canvas.pointsToHover.length, 6);
    assert.equal(f.details.hidden, true);
    for (const point of f.canvas.pointsToHover) {
        assert.ok(Number.isFinite(point.x) && Number.isFinite(point.y));
        f.hover(point);
        assert.ok(f.text().includes('¥0'));
        assert.ok(f.text().includes(point.data.date.replaceAll('-', '/')));
    }
});


test('unchanged overflow records preserve disclosure nodes across hover redraws', () => {
    const f = fixture();
    const variations = { single: spikeHistory() };
    f.draw(variations);
    const summary = f.details.children[0], list = f.details.children[1];
    f.details.open = true;
    f.draw(variations);
    assert.equal(f.details.children[0], summary);
    assert.equal(f.details.children[1], list);
    assert.equal(f.details.open, true);
    f.draw({ single: history([2000, 2000, 8888888, 1600, 1600, 2000]) });
    assert.equal(f.details.children[0], summary);
    assert.match(f.nodeText(f.details.children[1]), /8,888,888/);
});

test('redrawing a visible switch never transiently hides it and risks keyboard focus', () => {
    const f = fixture();
    const variations = { single: spikeHistory() };
    f.draw(variations);
    f.toggleHiddenWrites.length = 0;
    for (let i = 0; i < 12; i++) f.draw(variations, null, i % 2 === 0);
    assert.equal(f.toggleHiddenWrites.length, 12);
    assert.ok(f.toggleHiddenWrites.every(hidden => hidden === false));
});

for (const [locale, label, count] of [
    ['ja', '規格外', '▲ 規格外2件'], ['en', 'Outlier', '▲ Outliers: 2'],
    ['ko', '이상치', '▲ 이상치 2건'], ['zh-cn', '离群值', '▲ 离群值2条'],
    ['zh-tw', '離群值', '▲ 離群值2筆']
]) test(`outlier badges and disclosure counts follow ${locale} without a fourth line`, () => {
    const f = fixture(locale), a = spikeHistory(), b = spikeHistory();
    b[2].is_sale = true;
    f.draw({ a, b });
    f.hover(f.canvas.pointsToHover.find(p => p.outside));
    assert.equal(f.details.children[0].textContent, count);
    assert.equal(f.tooltip.children.length, 2);
    for (const row of f.tooltip.children) {
        assert.equal(row.children[1].className, 'booth-chart-outlier-badge');
        assert.equal(row.children[1].textContent, label);
        assert.match(row.children[1].style.cssText, /background:#ffdf00; color:#000/);
        assert.ok(row.children[1].attributes['aria-label'].includes(label));
        assert.equal(row.children.filter(n => n.tagName === 'br').length, 2);
        assert.equal(row.children.some(n => n.tagName === 'small'), false);
    }
    assert.equal(f.tooltip.children[1].children[2].textContent, 'SALE');
    f.hover(f.canvas.pointsToHover.find(p => !p.outside));
    assert.equal(f.text().includes(label), false);
    f.draw({a, b}, null, true);
    f.hover(f.canvas.pointsToHover.find(p => p.data.price === 9999999));
    assert.equal(f.text().includes(label), false);
    assert.equal(f.details.hidden, true);
});

for (const [locale, headers] of [
    ['ja', ['商品名', '日付', '価格']], ['en', ['Product', 'Date', 'Price']],
    ['ko', ['상품명', '날짜', '가격']], ['zh-cn', ['商品名称', '日期', '价格']],
    ['zh-tw', ['商品名稱', '日期', '價格']]
]) test(`history table exposes semantic localized columns and literal exact records in ${locale}`, () => {
    const f=fixture(locale), name='<img src=x onerror=alert(1)>長い商品名'.repeat(4);
    const a=spikeHistory(), b=spikeHistory(); b[2].price=19999998;
    f.draw({[name]:a, b});
    const scroll=f.details.children[1], table=scroll.children[0];
    assert.equal(scroll.attributes.tabindex,'0');
    assert.equal(scroll.attributes.role,'region');
    assert.ok(scroll.attributes['aria-label']);
    assert.equal(table.tagName,'table');
    assert.deepEqual(table.children[0].children[0].children.map(n=>n.textContent),headers);
    assert.ok(table.children[0].children[0].children.every(n=>n.tagName==='th'&&n.attributes.scope==='col'));
    const rows=table.children[1].children;
    assert.equal(rows.length,2);
    assert.equal(rows[0].children[0].textContent,name);
    assert.equal(rows[0].children[0].innerHTML,undefined);
    assert.equal(rows[0].children[2].textContent,'¥9,999,999');
    assert.equal(rows[1].children[2].textContent,'¥19,999,998');
    assert.equal(rows.every(r=>r.children.length===3),true);
});
