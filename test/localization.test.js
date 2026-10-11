const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../extension/content.js'), 'utf8');
function fixture({lang='', meta, pathname='/items/123', browser='en-US'}={}) {
    const context = {
        console: {log() {}}, navigator: {language: browser},
        window: {location:{pathname}},
        document: {documentElement:{lang},querySelector:() => meta === undefined ? null : {content:meta}}
    };
    vm.runInNewContext(source.replace('    main();', '    globalThis.i18n = { MESSAGES, normalizeLocale, getPageLocale, t, formatPrice, formatDate, variationLabel };'), context);
    return context;
}
test('rendered HTML language takes precedence over BOOTH metadata, path and browser preferences', () => {
    assert.equal(fixture({lang:'ko',meta:'"en"',pathname:'/ja/items/123',browser:'zh-TW'}).i18n.getPageLocale(),'ko');
});
test('BOOTH locale metadata, localized URL, then Japanese are the fallback order', () => {
    assert.equal(fixture({meta:'"zh-TW"',pathname:'/en/items/123'}).i18n.getPageLocale(),'zh-tw');
    assert.equal(fixture({lang:'fr',meta:'invalid',pathname:'/ko/items/123'}).i18n.getPageLocale(),'ko');
    assert.equal(fixture({meta:'"unknown"',browser:'en-US'}).i18n.getPageLocale(),'ja');
    assert.equal(fixture({meta:'zh-CN'}).i18n.getPageLocale(),'zh-cn');
});
test('all verified BOOTH locale codes and Chinese script/region aliases normalize', () => {
    const {normalizeLocale}=fixture().i18n;
    for(const [input,expected] of Object.entries({ja:'ja','en-GB':'en','KO_kr':'ko','zh-CN':'zh-cn','zh-SG':'zh-cn','zh-Hans':'zh-cn','zh-TW':'zh-tw','zh-Hant-TW':'zh-tw','zh-HK':'zh-tw'})) assert.equal(normalizeLocale(input),expected);
    assert.equal(normalizeLocale('French'),null);
});
test('every site language has complete nonempty strings, eight ranges, and substitutes counts', () => {
    const context=fixture(); const {MESSAGES,t}=context.i18n;
    const keys=Object.keys(MESSAGES.ja).sort();
    assert.deepEqual(Object.keys(MESSAGES).sort(),['en','ja','ko','zh-cn','zh-tw']);
    for(const locale of Object.keys(MESSAGES)) {
        context.document.documentElement.lang=locale;
        assert.deepEqual(Object.keys(MESSAGES[locale]).sort(),keys);
        assert.equal(MESSAGES[locale].ranges.length,8);
        for(const [key,value] of Object.entries(MESSAGES[locale])) if(key!=='ranges') assert.ok(typeof value==='string'&&value.length>0,`${locale}/${key}`);
        assert.ok(t('overflow',{n:7}).includes('7'));
        assert.ok(!t('zoomStatus',{n:7}).includes('{'));
    }
});
test('dates follow site locale and keep observation calendar dates; values remain yen', () => {
    for(const lang of ['ja','en','ko','zh-cn','zh-tw']) {
        const {i18n}=fixture({lang});
        const expected=lang==='ja'?'2026/05/03':new Intl.DateTimeFormat(lang,{year:'numeric',month:'2-digit',day:'2-digit',timeZone:'UTC'}).format(new Date('2026-05-03T00:00:00Z'));
        assert.equal(i18n.formatDate('2026-05-03'),expected);
        assert.equal(i18n.formatPrice(9999999), '¥'+(9999999).toLocaleString(lang));
    }
});
test('product names stay literal including labels that match a Japanese translation key', () => {
    const {i18n}=fixture({lang:'en'});
    for(const name of ['標準価格','<b>name</b>','しなの','한국어 상품']) assert.equal(i18n.variationLabel(name),name);
    assert.equal(i18n.variationLabel('標準価格',true),'Standard price');
});
test('switch has large geometric SVG icons without emoji/font or blend artifacts', () => {
    const css=fs.readFileSync(path.join(__dirname,'../extension/content.css'),'utf8');
    assert.match(source,/<svg class="booth-price-scale-symbol booth-price-scale-triangle" viewBox="0 0 12 12"/);
    assert.match(source,/<path d="M6 1\.34 L11 10 L1 10 Z"/);
    assert.match(source,/<circle cx="6" cy="6" r="4\.8"/);
    assert.match(css,/width: 12px;\s+height: 12px;/);
    assert.doesNotMatch(css,/mix-blend-mode|clip-path: polygon/);
    assert.match(css,/appearance: none/); assert.match(css,/box-shadow: none/);
    assert.match(css,/:focus:not\(:focus-visible\)/); assert.match(css,/:focus-visible/);
    assert.match(css,/overflow: hidden/);
    assert.match(css,/left 280ms ease-in-out, right 280ms ease-in-out 820ms/);
    assert.match(css,/right 280ms ease-in-out, left 280ms ease-in-out 820ms/);
    assert.match(css,/prefers-reduced-motion: reduce/);
});
