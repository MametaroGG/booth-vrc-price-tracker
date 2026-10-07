const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const cheerio = require('cheerio');
const { scrapeSearchPage, main } = require('../src/scraper');
const { reserveDailyAllowance, writeJson } = require('../src/collection-runtime');

const URL_3055 = 'https://booth.pm/ja/browse/3D%E3%83%A2%E3%83%87%E3%83%AB?sort=new&tags%5B%5D=VRChat&type=digital&page=3055';
const SOFTWARE = 'https://booth.pm/ja/browse/%E3%82%BD%E3%83%95%E3%83%88%E3%82%A6%E3%82%A7%E3%82%A2?sort=new&tags%5B%5D=VRChat&type=digital';
const realEnd = fs.readFileSync(path.join(__dirname, 'fixtures/booth-search-past-end.html'), 'utf8');
const empty = '<title>検索 - BOOTH</title><a href="/ja/browse/test">Browse</a><p>商品が見つかりませんでした</p>';
const parse = (html = realEnd, url = URL_3055, status = 200) => scrapeSearchPage(url, { get: async () => ({ status, data: html }) });
function edit(change) {
    const $ = cheerio.load(realEnd);
    change($);
    return $.html();
}
function lastHref($, transform) {
    const last = $('a.last-page');
    last.attr('href', transform(last.attr('href')));
}

test('real BOOTH DOM beyond the final page is empty despite no empty message and a next link', async () => {
    assert.match(realEnd, /rel="next"/);
    assert.doesNotMatch(realEnd, /商品が見つかりませんでした/);
    assert.deepEqual(await parse(), { kind: 'empty', ids: [] });
    const reordered = URL_3055.replace('?sort=new&tags%5B%5D=VRChat&type=digital&page=3055', '?page=3055&type=digital&tags%5B%5D=VRChat&sort=new');
    assert.equal((await parse(realEnd, reordered)).kind, 'empty');
    const absolute = edit($ => lastHref($, href => `https://booth.pm${href}`));
    assert.equal((await parse(absolute)).kind, 'empty');
});

test('an empty list on or before the advertised last page remains an error', async () => {
    for (const page of [1, 3053, 3054]) {
        const html = edit($ => $('title').text($('title').text().replace(/^3055/, String(page))));
        assert.equal((await parse(html, URL_3055.replace('page=3055', `page=${page}`))).kind, 'failure');
    }
    assert.equal((await parse(realEnd, URL_3055.replace('page=3055', 'page=3056'))).kind, 'failure', 'stale title is not this response');
});

test('cards are still collected and malformed cards or changed result lists cannot become an empty result', async () => {
    const products = edit($ => $('ul.l-cards-5cols').append('<li class="item-card" data-product-id="123"></li>'));
    assert.deepEqual(await parse(products), { kind: 'success', ids: ['123'] });
    for (const content of ['<li class="item-card"></li>', '<li class="new-item-layout" data-product-id="123"></li>', 'Loading products']) {
        assert.equal((await parse(edit($ => $('ul.l-cards-5cols').append(content)))).kind, 'failure');
    }
});

test('foreign, changed-filter and malformed pagination cannot end the current search', async t => {
    const cases = {
        'foreign origin': href => `https://example.com${href}`,
        'different category': href => href.replace('/3D%E3%83%A2%E3%83%87%E3%83%AB?', '/other?'),
        'different sort': href => href.replace('sort=new', 'sort=popular'),
        'missing digital filter': href => href.replace('&type=digital', ''),
        'different tag': href => href.replace('VRChat', 'Other'),
        'duplicate tag': href => `${href}&tags%5B%5D=VRChat`,
        'duplicate page': href => `${href}&page=3054`,
        'zero page': href => href.replace('page=3054', 'page=0'),
        'negative page': href => href.replace('page=3054', 'page=-1'),
        'fractional page': href => href.replace('page=3054', 'page=3054.5'),
        'unsafe page': href => href.replace('page=3054', 'page=9007199254740992'),
        'fragment': href => `${href}#challenge`,
        'credentials': href => `https://name:password@booth.pm${href}`,
        'malformed escape': href => href.replace('VRChat', '%ZZ'),
        'malformed UTF-8': href => href.replace('VRChat', '%E3'),
    };
    for (const [name, transform] of Object.entries(cases)) {
        await t.test(name, async () => assert.equal((await parse(edit($ => lastHref($, transform)))).kind, 'failure'));
    }
    for (const suffix of ['&page=3055', '&tags%5B%5D=VRChat', '&bad=%ZZ']) {
        assert.equal((await parse(realEnd, URL_3055 + suffix)).kind, 'failure');
    }
});

test('missing or ambiguous search evidence, error pages and challenges remain failures', async t => {
    const cases = {
        'missing result grid': $ => $('.l-market-grid').remove(),
        'duplicate result grid': $ => $('.l-market-grid').after($('.l-market-grid').clone()),
        'missing result list': $ => $('ul.l-cards-5cols').remove(),
        'duplicate result list': $ => $('ul.l-cards-5cols').after($('ul.l-cards-5cols').clone()),
        'missing heading': $ => $('h1').remove(),
        'wrong heading': $ => $('h1').text('Verify you are human'),
        'wrong title': $ => $('title').text('Just a moment - BOOTH'),
        'duplicate titles': $ => $('title').after($('title').clone()),
        'title does not identify BOOTH': $ => $('title').text($('title').text().replace(/BOOTH$/, 'Elsewhere')),
        'missing count': $ => $('b').remove(),
        'invalid count': $ => $('b').text('対象商品 183,21 件'),
        'zero count with pages': $ => $('b').text('対象商品 0 件'),
        'no last-page control': $ => $('a.last-page').remove(),
        'no last-page href': $ => $('a.last-page').removeAttr('href'),
        'ambiguous last-page controls': $ => $('a.last-page').after($('a.last-page').clone()),
        'no corroborating final numbered link': $ => $('a.nav-item').filter((_, el) => $(el).text() === '3054').remove(),
        'last-page control cannot corroborate itself': $ => {
            $('a.nav-item').filter((_, el) => $(el).text() === '3054').remove();
            $('a.last-page').text('3054');
        },
        'numbered link contradicts final page': $ => {
            const final = $('a.nav-item').filter((_, el) => $(el).text() === '3054');
            final.after(final.clone().text('3056').attr('href', final.attr('href').replace('page=3054', 'page=3056')));
        },
        'numbered label differs from target page': $ => $('a.nav-item').filter((_, el) => $(el).text() === '3053').text('3052'),
        'ordinary numbered link changes filters': $ => {
            const link = $('a.nav-item').filter((_, el) => $(el).text() === '3053');
            link.attr('href', link.attr('href').replace('VRChat', 'Other'));
        },
        'pagination detached from results': $ => $('body').append($('.pager')),
        'unknown error response': $ => $('body').html('<h1>Service unavailable</h1>'),
        'challenge response': $ => $('body').html('<h1>Verify you are human</h1><div class="cf-turnstile"></div>'),
    };
    for (const [name, change] of Object.entries(cases)) {
        await t.test(name, async () => assert.equal((await parse(edit(change))).kind, 'failure'));
    }
    for (const status of [403, 429, 500]) assert.equal((await parse(realEnd, URL_3055, status)).kind, 'failure');
});

test('the real terminal page advances to the original software filter and preserves prior history', async t => {
    const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'boopa-search-end-'));
    t.after(() => fs.rmSync(dataDir, { recursive: true, force: true }));
    const stateFile = path.join(dataDir, 'crawl_state.json');
    const budgetFile = path.join(dataDir, 'request_budget.json');
    writeJson(stateFile, { urlIndex: 0, page: 3055, retries: [] });
    const previous = { id: '123', name: 'Existing', variations: { default: [{ date: '2026-10-07', price: 120, isSale: false }] } };
    writeJson(path.join(dataDir, '123', '123.json'), previous);
    const now = Date.parse('2026-10-07T17:00:00Z');
    reserveDailyAllowance({ budgetFile, reservationId: 'boundary-test', now });
    const urls = [];
    const get = async url => {
        urls.push(url);
        if (url === URL_3055) return { status: 200, data: realEnd };
        if (url === `${SOFTWARE}&page=1`) return { status: 200, data: '<div class="item-card" data-product-id="123"></div>' };
        if (url === 'https://booth.pm/ja/items/123') return { status: 200, data: '<h2>Existing</h2><div class="variation-item"><span class="variation-name">default</span><span class="variation-price">100円</span></div>' };
        if (url === `${SOFTWARE}&page=2`) return { status: 200, data: empty };
        throw new Error(`Unexpected request: ${url}`);
    };
    const result = await main({ dataDir, get, now: () => now, jobStartedAt: now, reservationId: 'boundary-test', wait: async () => {}, log: () => {}, logError: () => {} });
    assert.equal(result.status, 'completed');
    assert.equal(result.failed, false);
    assert.equal(result.continueCollection, true);
    assert.equal(result.metrics.itemSuccess, 1);
    assert.equal(result.metrics.chargedHttpAttempts, 4);
    assert.deepEqual(urls, [URL_3055, `${SOFTWARE}&page=1`, 'https://booth.pm/ja/items/123', `${SOFTWARE}&page=2`]);
    assert.deepEqual(JSON.parse(fs.readFileSync(stateFile)), { urlIndex: 0, page: 1, retries: [] });
    const saved = JSON.parse(fs.readFileSync(path.join(dataDir, '123', '123.json')));
    assert.deepEqual(saved.variations.default[0], previous.variations.default[0]);
    assert.equal(saved.variations.default.length, 2);
    assert.equal(saved.variations.default[1].date, '2026-10-08');
    assert.equal(saved.variations.default[1].price, 100);
    assert.equal(JSON.parse(fs.readFileSync(budgetFile)).reservation.completed, true);
});

test('unproven end-of-results preserves the current category, page and history without continuing', async t => {
    const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'boopa-search-unknown-'));
    t.after(() => fs.rmSync(dataDir, { recursive: true, force: true }));
    const stateFile = path.join(dataDir, 'crawl_state.json');
    const budgetFile = path.join(dataDir, 'request_budget.json');
    const state = { urlIndex: 0, page: 3055, retries: [] };
    writeJson(stateFile, state);
    const historyFile = path.join(dataDir, '123', '123.json');
    writeJson(historyFile, { id: '123', variations: { default: [{ date: '2026-10-07', price: 120, isSale: false }] } });
    const history = fs.readFileSync(historyFile);
    const now = Date.parse('2026-10-07T17:00:00Z');
    reserveDailyAllowance({ budgetFile, reservationId: 'unknown-test', now });
    const urls = [];
    const result = await main({ dataDir, now: () => now, jobStartedAt: now, reservationId: 'unknown-test',
        get: async url => {
            urls.push(url);
            return { status: 200, data: edit($ => lastHref($, href => href.replace('VRChat', 'Other'))) };
        }, wait: async () => {}, log: () => {}, logError: () => {} });
    assert.equal(result.status, 'partial');
    assert.equal(result.reason, 'search-failure');
    assert.equal(result.failed, true);
    assert.equal(result.continueCollection, false);
    assert.equal(result.metrics.itemSuccess, 0);
    assert.equal(result.metrics.chargedHttpAttempts, 1);
    assert.deepEqual(urls, [URL_3055]);
    assert.deepEqual(JSON.parse(fs.readFileSync(stateFile)), state);
    assert.deepEqual(fs.readFileSync(historyFile), history);
    assert.equal(JSON.parse(fs.readFileSync(budgetFile)).reservation.completed, true);
});
