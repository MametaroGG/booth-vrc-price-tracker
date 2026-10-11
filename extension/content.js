// content.js
(async function () {
    console.log('[Boopa] Script initialized for ID:', window.location.pathname);
    const pathSegments = window.location.pathname.split('/');
    const itemsIndex = pathSegments.indexOf('items');
    const productId = itemsIndex !== -1 ? pathSegments[itemsIndex + 1] : null;
    console.log('[Boopa] Extracted Product ID:', productId);
    if (!productId || isNaN(productId)) {
        console.log('[Boopa] Invalid Product ID, stopping.');
        return;
    }

    // BOOTH's rendered page language wins over browser preferences. Verified on
    // booth.pm: HTML lang + js_const_user_locale; menu codes ja/en/ko/zh-cn/zh-tw.
    const MESSAGES = {
        ja: {
            comparison: '比較対象の記録価格 {price}（複数日の記録。現在の販売割引率ではありません）',
            heading: '価格推移', demo: '(収集待ち: デモ表示)', noCollection: 'データ収集はされていません。', noData: 'データがありません',
            historyProduct: '商品名', historyDate: '日付', historyPrice: '価格', historyLabel: '規格外の価格履歴',
            ranges: ['1日', '5日', '1か月', '6か月', '年初来', '1年', '5年', '最大'],
            showLegend: '商品一覧を表示', hideLegend: '商品一覧を閉じる', lowestToggle: '各バリエーションに記録上の最安値を表示',
            lowest: '記録上の最安値', lowestNow: '最安値圏', today: '本日', daysAgo: '{n}日前', asOf: '{date}・{relative}時点',
            fullLabel: '全価格を表示', fullStatus: '全価格表示', zoomStatus: '通常範囲を拡大中・上限外 {n} 件（▲）',
            fullTitle: '全価格を表示（現在は通常範囲を拡大）', zoomTitle: '通常範囲を拡大（現在は全価格を表示）',
            overflow: '▲ 規格外{n}件', outlier: '規格外', outside: '（表示上限外）', sale: 'セール', standard: '標準価格'
        },
        en: {
            comparison: 'Compared with recorded price {price} (observed on multiple dates; not a current sale discount)',
            heading: 'Price Tracker', demo: '(Awaiting data: demo)', noCollection: 'Price data has not been collected yet.', noData: 'No data available',
            historyProduct: 'Product', historyDate: 'Date', historyPrice: 'Price', historyLabel: 'Outlier price history',
            ranges: ['1D', '5D', '1M', '6M', 'YTD', '1Y', '5Y', 'Max'],
            showLegend: 'Show products', hideLegend: 'Hide products', lowestToggle: 'Show the lowest recorded price for each variation',
            lowest: 'Lowest recorded price', lowestNow: 'At recorded low', today: 'Today', daysAgo: '{n} days ago', asOf: '{date} · {relative}',
            fullLabel: 'Show all prices', fullStatus: 'Showing all prices', zoomStatus: 'Normal range enlarged · {n} above range (▲)',
            fullTitle: 'Show all prices (normal range is enlarged)', zoomTitle: 'Enlarge normal range (showing all prices)',
            overflow: '▲ Outliers: {n}', outlier: 'Outlier', outside: ' (above displayed range)', sale: 'SALE', standard: 'Standard price'
        },
        ko: {
            comparison: '비교 기준 기록 가격 {price} (여러 날짜에 기록됨; 현재 판매 할인율이 아님)',
            heading: '가격 변동', demo: '(데이터 수집 대기: 데모)', noCollection: '아직 가격 데이터가 수집되지 않았습니다.', noData: '데이터가 없습니다',
            historyProduct: '상품명', historyDate: '날짜', historyPrice: '가격', historyLabel: '이상치 가격 기록',
            ranges: ['1일', '5일', '1개월', '6개월', '연초부터', '1년', '5년', '전체'],
            showLegend: '상품 목록 보기', hideLegend: '상품 목록 닫기', lowestToggle: '각 옵션에 기록된 최저가 표시',
            lowest: '기록된 최저가', lowestNow: '최저가 수준', today: '오늘', daysAgo: '{n}일 전', asOf: '{date} · {relative} 기준',
            fullLabel: '전체 가격 표시', fullStatus: '전체 가격 표시 중', zoomStatus: '일반 범위 확대 중 · 상한 초과 {n}건 (▲)',
            fullTitle: '전체 가격 표시 (현재 일반 범위 확대 중)', zoomTitle: '일반 범위 확대 (현재 전체 가격 표시 중)',
            overflow: '▲ 이상치 {n}건', outlier: '이상치', outside: ' (표시 상한 초과)', sale: '할인', standard: '기본 가격'
        },
        'zh-cn': {
            comparison: '对比记录价格 {price}（在多个日期记录；并非当前销售折扣）',
            heading: '价格走势', demo: '（等待收集数据：演示）', noCollection: '尚未收集价格数据。', noData: '暂无数据',
            historyProduct: '商品名称', historyDate: '日期', historyPrice: '价格', historyLabel: '离群价格记录',
            ranges: ['1天', '5天', '1个月', '6个月', '年初至今', '1年', '5年', '全部'],
            showLegend: '显示商品列表', hideLegend: '收起商品列表', lowestToggle: '显示各款式的历史最低价',
            lowest: '历史最低价', lowestNow: '处于历史低位', today: '今天', daysAgo: '{n}天前', asOf: '{date} · {relative}',
            fullLabel: '显示所有价格', fullStatus: '正在显示所有价格', zoomStatus: '已放大常规范围 · {n}条超出上限（▲）',
            fullTitle: '显示所有价格（当前已放大常规范围）', zoomTitle: '放大常规范围（当前显示所有价格）',
            overflow: '▲ 离群值{n}条', outlier: '离群值', outside: '（超出显示上限）', sale: '促销', standard: '标准价格'
        },
        'zh-tw': {
            comparison: '比較記錄價格 {price}（於多個日期記錄；並非目前銷售折扣）',
            heading: '價格走勢', demo: '（等待蒐集資料：示範）', noCollection: '尚未蒐集價格資料。', noData: '暫無資料',
            historyProduct: '商品名稱', historyDate: '日期', historyPrice: '價格', historyLabel: '離群價格記錄',
            ranges: ['1天', '5天', '1個月', '6個月', '年初至今', '1年', '5年', '全部'],
            showLegend: '顯示商品列表', hideLegend: '收起商品列表', lowestToggle: '顯示各款式的歷史最低價',
            lowest: '歷史最低價', lowestNow: '處於歷史低點', today: '今天', daysAgo: '{n}天前', asOf: '{date} · {relative}',
            fullLabel: '顯示所有價格', fullStatus: '正在顯示所有價格', zoomStatus: '已放大一般範圍 · {n}筆超出上限（▲）',
            fullTitle: '顯示所有價格（目前已放大一般範圍）', zoomTitle: '放大一般範圍（目前顯示所有價格）',
            overflow: '▲ 離群值{n}筆', outlier: '離群值', outside: '（超出顯示上限）', sale: '特價', standard: '標準價格'
        }
    };
    function normalizeLocale(value) {
        const locale = String(value || '').trim().replace(/_/g, '-').toLowerCase();
        if (/^zh-(tw|hk|mo|hant)(-|$)/.test(locale)) return 'zh-tw';
        if (/^zh(?:$|-(?:cn|sg|hans)(?:-|$))/.test(locale)) return 'zh-cn';
        const base = locale.split('-')[0];
        return ['ja', 'en', 'ko'].includes(base) ? base : null;
    }
    function getPageLocale() {
        const doc = typeof document === 'undefined' ? null : document;
        const htmlLocale = normalizeLocale(doc?.documentElement?.lang);
        if (htmlLocale) return htmlLocale;
        const raw = doc?.querySelector?.('meta[name="js_const_user_locale"]')?.content;
        let metaLocale;
        try { metaLocale = normalizeLocale(JSON.parse(raw)); } catch { metaLocale = normalizeLocale(raw); }
        return metaLocale || normalizeLocale(window.location?.pathname?.split('/')[1]) || 'ja';
    }
    function t(key, params = {}) {
        return MESSAGES[getPageLocale()][key].replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? ''));
    }
    function formatPrice(price) {
        // Currency remains JPY; localization must never convert recorded values.
        return `¥${price.toLocaleString(getPageLocale())}`;
    }
    function formatDate(value) {
        // Interpret date-only observations in UTC to avoid shifting their calendar day.
        const date = new Date(`${value}T00:00:00Z`);
        if (!Number.isFinite(date.getTime())) return String(value);
        if (getPageLocale() === 'ja') return value.replace(/-/g, '/');
        return new Intl.DateTimeFormat(getPageLocale(), { year: 'numeric', month: '2-digit', day: '2-digit', timeZone: 'UTC' }).format(date);
    }
    function variationLabel(name, syntheticStandard = false) {
        return syntheticStandard ? t('standard') : name;
    }

    // Sharding: Use first 3 characters of ID for directory structure
    const shard = productId.toString().substring(0, 3);
    const GITHUB_PAGES_URL = `https://mametarogg.github.io/booth-vrc-price-tracker/data/${shard}/${productId}.json?t=${new Date().getTime()}`;

    function isTargetProduct() {
        // Collect category links, but exclude those in sidebars/recommendations
        const allBrowseLinks = Array.from(document.querySelectorAll('a[href*="/browse/"]'));
        const validCategoryLinks = allBrowseLinks.filter(a => {
            const parent = a.closest('.recommend, .item-recommend, .other-items, .shop-items, .related-tags, .sidebar, .l-side, footer');
            return !parent;
        });

        const excludedCategories = [
            'ハードウェア・ガジェット', 'Hardware / Gadgets', 'Hardware & Gadgets',
            '写真作品', 'Photography',
            '素材データ', 'Materials',
            '小説・書籍', 'Novels / Books',
            'ゲーム', 'Games'
        ];

        // 1. Check for Excluded Categories first
        const isExcluded = validCategoryLinks.some(a => {
            const text = a.textContent.trim();
            return excludedCategories.includes(text);
        });

        if (isExcluded) {
            console.log('[Boopa] Excluded category detected, skipping.');
            return false;
        }

        const allowedCategories = [
            '3Dモデル', '3D Models',
            'ソフトウェア', 'Software'
        ];

        // 2. Check for Allowed Categories
        const isAllowedCategory = validCategoryLinks.some(a => {
            const text = a.textContent.trim();
            return allowedCategories.includes(text);
        });

        if (!isAllowedCategory) {
            console.log('[Boopa] Category not in whitelist (3D Models/Software), skipping.');
            return false;
        }
        // Tag check: specific tag links
        const tagLinks = Array.from(document.querySelectorAll('a[href*="tags"]'));
        const hasVrcTag = tagLinks.some(a => {
            const text = a.textContent.trim().toLowerCase();
            return text === 'vrchat' || text === 'vrchat想定';
        });

        // Title check: h2 usually contains the title
        const title = document.querySelector('h2')?.innerText.toLowerCase() || '';
        const hasVrcTitle = title.includes('vrchat') || title.includes('vrc');

        // Combined stricter check: Must have explicit Tag OR Title mentioning VRChat.
        // Removed broad document.body check to avoid false positives from footers/ads.
        return hasVrcTag || hasVrcTitle;
    }

    async function fetchPriceHistory() {
        const target = isTargetProduct();
        try {
            // Using sendMessage to bypass CORS/CSP issues in content script
            const result = await new Promise((resolve) => {
                chrome.runtime.sendMessage(
                    { type: 'FETCH_PRICE_HISTORY', url: GITHUB_PAGES_URL },
                    (response) => {
                        if (chrome.runtime.lastError) {
                            console.error('[Boopa] Message error:', chrome.runtime.lastError);
                            resolve({ success: false });
                        } else {
                            resolve(response);
                        }
                    }
                );
            });

            if (!result || !result.success) {
                if (target) {
                    console.log('[Boopa] Target product found but fetch failed, showing demo data.');
                    return {
                        isDemo: true,
                        data: {
                            "商品1": [
                                { "date": "2026-01-01", "price": 6000, "is_sale": false },
                                { "date": "2026-01-15", "price": 5000, "is_sale": true }
                            ],
                            "商品2": [
                                { "date": "2026-01-01", "price": 2000, "is_sale": false },
                                { "date": "2026-01-15", "price": 2000, "is_sale": false }
                            ]
                        }
                    };
                }
                return null;
            }

            const json = result.data;
            // Handle both old and new formats (new has .variations)
            return {
                isDemo: false,
                syntheticStandard: !json.variations,
                data: json.variations || { "標準価格": json }
            };
        } catch (e) {
            console.error('[Boopa] fetchPriceHistory exception:', e);
            return null;
        }
    }

    // BOOTH appends a discount badge to a variation's name while it is on sale, so
    // "✧ Shinano | しなの" temporarily becomes "✧ Shinano | しなの (30% OFF)". The history is
    // keyed by that raw name, so every sale spawned a *separate* variation key — splitting
    // one product into multiple lines and multiple legend rows (26 keys for what is really
    // 13 variations). Stripping the trailing badge reunites the sale and non-sale periods.
    // The pattern is deliberately strict (digits + %/円 + OFF/オフ) so genuine names that
    // merely contain words like "割引" or "SALE" are left untouched.
    function normalizeVariationName(name) {
        // Strip a trailing sale badge — a final (...) that contains a number, a %/円, and a
        // discount word (OFF/オフ/SALE/セール) in any order: "(30% OFF)", "(30% SALE)",
        // "(890円 OFF)". Requiring all three keeps real names like "(コットン100%)" or
        // "(…100％割引)" intact.
        return name
            .replace(/\s*[\(（](?=[^)）]*\d)(?=[^)）]*[%％円])(?=[^)）]*(?:OFF|オフ|SALE|セール))[^)）]*[\)）]\s*$/i, '')
            .replace(/\s{2,}/g, ' ')
            .trim();
    }

    function mergeVariations(rawVariations) {
        const merged = {};
        Object.keys(rawVariations).forEach(rawName => {
            const base = normalizeVariationName(rawName) || rawName;
            if (!merged[base]) merged[base] = [];
            merged[base].push(...rawVariations[rawName]);
        });
        // Sort each reunited series by date and collapse duplicate dates (prefer the lower
        // i.e. sale price if a single day ever appears under two source keys).
        Object.keys(merged).forEach(base => {
            const byDate = {};
            merged[base].forEach(entry => {
                const existing = byDate[entry.date];
                if (!existing || entry.price < existing.price) byDate[entry.date] = entry;
            });
            merged[base] = Object.values(byDate).sort((a, b) => a.date.localeCompare(b.date));
        });
        return merged;
    }

    // Presentation-only upper-tail detection, independently for each variation.
    // Require >=5 ordinary dates, >=80% ordinary observations, and a >=20x gap.
    // Zeros remain visible and never form the denominator. A flag is NOT evidence
    // of an invalid price or the duration of a sale. Sparse histories stay full-range.
    function findSeparatedHighPoints(history) {
        const positive = history.filter(d => Number.isFinite(d.price) && d.price > 0)
            .slice().sort((a, b) => a.price - b.price);
        for (let split = Math.max(5, Math.ceil(positive.length * 0.8)); split < positive.length; split++) {
            const ordinary = positive.slice(0, split);
            if (positive[split].price / positive[split - 1].price >= 20 &&
                new Set(ordinary.map(d => d.date)).size >= 5) {
                return new Set(positive.slice(split));
            }
        }
        return new Set();
    }

    // ===== Optional, user-toggled feature: lowest recorded price per variation =====
    const LOWEST_PREF_KEY = 'showLowestPrice';

    // SteamDB-style: the lowest price ever recorded for one variation's merged history.
    function getLowestPriceInfo(history) {
        if (!Array.isArray(history) || history.length === 0) return null;
        // Preserve the existing positive-price-only badge policy. Zero observations
        // remain available on the chart; this does not classify them as invalid.
        const valid = history.filter(d => Number.isFinite(d.price) && d.price > 0);
        if (valid.length === 0) return null;
        let low = valid[0];
        for (const d of valid) {
            // Lowest price; on ties keep the most recent date ("as of" semantics).
            if (d.price < low.price || (d.price === low.price && d.date > low.date)) low = d;
        }
        // Preserve the original comparison chip only with a supported reference:
        // discard chart-classified high points from this calculation (not the
        // history), require the remaining maximum on two distinct dates, and
        // suppress unresolved extreme ratios. This is a historical comparison,
        // never a claim about the merchant's regular price/current sale discount.
        const separated = findSeparatedHighPoints(valid);
        const ordinary = valid.filter(d => !separated.has(d));
        const reference = ordinary.reduce((max, d) => Math.max(max, d.price), 0);
        const dates = new Set(ordinary.filter(d => d.price === reference &&
            typeof d.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(d.date)).map(d => d.date));
        const pct = reference > 0 ? Math.round((1 - low.price / reference) * 100) : 0;
        const supported = dates.size >= 2 && reference / low.price < 20 && pct > 0 && pct < 100;
        const current = valid[valid.length - 1].price;
        return { minPrice: low.price, minDate: low.date, current, isCurrentlyLowest: current <= low.price,
            comparisonPrice: supported ? reference : undefined, comparisonPct: supported ? pct : undefined };
    }

    const TREND_DOWN_ICON = `<svg class="booth-lowest-icon" xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 17 13.5 8.5 8.5 13.5 2 7"></polyline><polyline points="16 17 22 17 22 11"></polyline></svg>`;

    // Inject (or, when show=false, clear) a "lowest recorded price" badge under each
    // variation on the page. Page names are normalized so they match the merged history
    // even while the shop has a sale badge like "(840円 OFF)" appended live.
    function renderLowestBadges(variations, show) {
        document.querySelectorAll('.booth-lowest-badge').forEach(el => el.remove());
        if (!show) return;

        const today = new Date();
        const keys = Object.keys(variations);
        document.querySelectorAll('.variation-item').forEach(item => {
            const nameEl = item.querySelector('.variation-name');
            let history;
            if (nameEl) {
                history = variations[normalizeVariationName(nameEl.textContent.trim())];
            }
            // Single-item products still render one .variation-item but have NO
            // .variation-name. There is exactly one tracked series in that case, so fall back
            // to it instead of bailing out (which hid the badge on single products). Also
            // covers a lone named variation whose label drifted from the stored key.
            if (!history && keys.length === 1) {
                history = variations[keys[0]];
            }
            const info = getLowestPriceInfo(history);
            if (!info) return;

            const dateStr = formatDate(info.minDate);
            const days = Math.max(0, Math.floor((today - new Date(info.minDate)) / 86400000));
            const daysLabel = days === 0 ? t('today') : t('daysAgo', { n: days });
            const off = info.comparisonPct > 0 ? ` <span class="booth-lowest-off">-${info.comparisonPct}%</span>` : '';
            const nowTag = info.isCurrentlyLowest ? ` <span class="booth-lowest-now">${t('lowestNow')}</span>` : '';

            const badge = document.createElement('div');
            badge.className = 'booth-lowest-badge';
            badge.title = `${t('lowest')} ${formatPrice(info.minPrice)}／ ${t('asOf', { date: dateStr, relative: daysLabel })}`;
            if (off) badge.title += `／ ${t('comparison', { price: formatPrice(info.comparisonPrice) })}`;
            badge.innerHTML = `${TREND_DOWN_ICON}<span class="booth-lowest-label">${t('lowest')}</span> <strong>${formatPrice(info.minPrice)}</strong>${off}${nowTag} <small>${dateStr}</small>`;
            // Place it at the very bottom of the variation block (below the gift button), out
            // of the name → price → buttons flow, so it no longer crowds the layout.
            item.appendChild(badge);
        });
    }

    // Resolve only computed host colors, never shop-provided strings as CSS. RGB
    // and hex cover ordinary computed styles; unsupported color spaces fall back
    // to a safe neutral pair rather than risking unreadable state symbols.
    function parseThemeColor(value) {
        const text = String(value || '').trim();
        const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(text);
        if (hex) {
            const digits = hex[1].length === 3 ? [...hex[1]].map(x => x + x).join('') : hex[1];
            return [0, 2, 4].map(i => parseInt(digits.slice(i, i + 2), 16)).concat(1);
        }
        const rgb = /^rgba?\(([^)]+)\)$/i.exec(text);
        if (!rgb) return null;
        const parts = rgb[1].trim().split(/[\s,/]+/);
        if (parts.length < 3 || parts.length > 4) return null;
        const numbers = parts.map((part, i) => Number(part.replace('%', '')) * (part.endsWith('%') ? (i < 3 ? 2.55 : 0.01) : 1));
        if (!numbers.every(Number.isFinite)) return null;
        return numbers.slice(0, 3).map(x => Math.max(0, Math.min(255, x))).concat(Math.max(0, Math.min(1, numbers[3] ?? 1)));
    }
    function blendThemeColor(front, back, alpha = front[3] ?? 1) {
        return front.slice(0, 3).map((x, i) => x * alpha + back[i] * (1 - alpha));
    }
    function themeLuminance(color) {
        const linear = color.slice(0, 3).map(x => x / 255).map(x => x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4);
        return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
    }
    function themeContrast(a, b) {
        const x = themeLuminance(a), y = themeLuminance(b);
        return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
    }
    function getSwitchPalette(container) {
        const host = container.parentElement;
        const style = window.getComputedStyle(host || container);
        const dark = style.colorScheme === 'dark' || (style.colorScheme !== 'light' && window.matchMedia?.('(prefers-color-scheme: dark)').matches);
        let surface = dark ? [24, 24, 24] : [255, 255, 255];
        const layers = [];
        for (let node = host; node; node = node.parentElement) {
            const color = parseThemeColor(window.getComputedStyle(node).backgroundColor);
            if (color) layers.push(color);
        }
        layers.reverse().forEach(color => { surface = blendThemeColor(color, surface); });
        const text = parseThemeColor(style.color);
        let ink = text ? blendThemeColor(text, surface) : (dark ? [238, 238, 238] : [51, 51, 51]);
        const black = [0, 0, 0], white = [255, 255, 255];
        // A subtly tinted track belongs to the surrounding shop; the selected
        // half uses its text tone. Both symbols have at least 4.5:1 contrast.
        let track = blendThemeColor(ink, surface, 0.08).map(Math.round);
        ink = ink.map(Math.round);
        if (themeContrast(ink, track) < 4.5) ink = themeContrast(black, track) >= themeContrast(white, track) ? black : white;
        const cssColor = color => `rgb(${color.join(', ')})`;
        return { track: cssColor(track), ink: cssColor(ink) };
    }
    function watchSwitchTheme(container) {
        let stopped = false, pending = null;
        const requestFrame = window.requestAnimationFrame?.bind(window) || (callback => window.setTimeout(callback, 16));
        const cancelFrame = window.cancelAnimationFrame?.bind(window) || window.clearTimeout.bind(window);
        const refresh = () => {
            pending = null;
            if (stopped) return;
            if (!container.isConnected) { container.boopaCleanup?.(); return; }
            const palette = getSwitchPalette(container);
            for (const [name, value] of Object.entries(palette)) {
                const property = `--boopa-switch-${name}`;
                if (container.style.getPropertyValue(property) !== value) container.style.setProperty(property, value);
            }
        };
        const schedule = () => {
            if (!stopped && pending === null) pending = requestFrame(refresh);
        };
        // Watch host ancestors, not our own style/animation attributes. This
        // prevents theme updates from observing themselves or chart redraws.
        const observer = new MutationObserver(schedule);
        const ancestors = new Set();
        for (let node = container.parentElement; node; node = node.parentElement) {
            ancestors.add(node);
            observer.observe(node, { attributes: true });
        }
        // A class change may begin a CSS transition; sample its final colors
        // too, without reacting to our knob/symbol transitions or other widgets.
        const transitionFinished = event => {
            if (ancestors.has(event.target) && ['color', 'background-color'].includes(event.propertyName)) schedule();
        };
        window.addEventListener('transitionend', transitionFinished, true);
        window.addEventListener('transitioncancel', transitionFinished, true);
        if (document.head) observer.observe(document.head, { attributes: true, childList: true, characterData: true, subtree: true });
        const media = window.matchMedia?.('(prefers-color-scheme: dark)');
        media?.addEventListener?.('change', schedule);
        window.addEventListener('resize', schedule);
        window.addEventListener('pageshow', schedule);
        document.head?.addEventListener('load', schedule, true);
        refresh();
        return () => {
            stopped = true;
            observer.disconnect();
            if (pending !== null) cancelFrame(pending);
            media?.removeEventListener?.('change', schedule);
            window.removeEventListener('transitionend', transitionFinished, true);
            window.removeEventListener('transitioncancel', transitionFinished, true);
            window.removeEventListener('resize', schedule);
            window.removeEventListener('pageshow', schedule);
            document.head?.removeEventListener('load', schedule, true);
        };
    }

    function injectTracker(result) {
        console.log('[Boopa] Injecting tracker. isDemo:', result.isDemo);
        const variations = mergeVariations(result.data);
        const isDemo = result.isDemo;
        let currentRange = 'all';
        const scaleState = { fullRange: false, syntheticStandard: !!result.syntheticStandard };
        const localeUpdates = [];
        let redraw = () => drawChart(canvas, variations, currentRange, null, null, isDemo, scaleState);

        // Find price elements on the page
        const priceElements = document.querySelectorAll('.variation-price');
        if (priceElements.length === 0) return;

        // Create container for the graph
        const container = document.createElement('div');
        container.className = 'booth-price-tracker-container';

        const titleArea = document.createElement('div');
        titleArea.className = 'booth-price-tracker-title';
        const chartIcon = `
            <svg class="booth-price-tracker-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"></polyline>
                <polyline points="16 7 22 7 22 13"></polyline>
            </svg>
        `;

        const heading = document.createElement('span');
        const updateHeading = () => {
            heading.innerHTML = `${chartIcon} ${t('heading')}${isDemo ? ` <small style="color: #999; font-weight: normal;">${t('demo')}</small>` : ''}`;
        };
        updateHeading();
        localeUpdates.push(updateHeading);
        titleArea.appendChild(heading);

        const headingRow = document.createElement('div');
        headingRow.className = 'booth-price-heading-row';
        while (titleArea.firstChild) headingRow.appendChild(titleArea.firstChild);
        titleArea.appendChild(headingRow);

        const canvas = document.createElement('canvas');
        canvas.className = 'booth-price-tracker-canvas';
        container.appendChild(canvas);

        // Only show controls if NOT in demo mode
        if (!isDemo) {
            const selector = document.createElement('div');
            selector.className = 'booth-price-range-selector';

            const ranges = [1, 5, 30, 180, 'ytd', 365, 1825, 'all'].map((value, index) => ({ value, index }));

            const legendToggle = document.createElement('div');
            legendToggle.className = 'booth-legend-toggle';
            legendToggle.innerHTML = `<span>▼</span> ${t('showLegend')}`;
            container.appendChild(legendToggle);

            const legendArea = document.createElement('div');
            legendArea.className = 'booth-price-legend collapsed'; // Default to collapsed
            legendArea.style.cssText = 'display: flex; flex-wrap: wrap; gap: 10px; margin-top: 10px; font-size: 11px; opacity: 0.8; color: inherit;';
            container.appendChild(legendArea);

            // --- Optional: per-variation "lowest recorded price" badges (off by default) ---
            const lowestToggle = document.createElement('label');
            lowestToggle.className = 'booth-lowest-toggle';
            lowestToggle.innerHTML = `<input type="checkbox"><span>${t('lowestToggle')}</span>`;
            localeUpdates.push(() => {
                lowestToggle.querySelector('span').textContent = t('lowestToggle');
                renderLowestBadges(variations, lowestCheckbox.checked);
            });
            container.appendChild(lowestToggle);
            const lowestCheckbox = lowestToggle.querySelector('input');
            lowestCheckbox.addEventListener('change', () => {
                const show = lowestCheckbox.checked;
                try { chrome.storage?.local?.set({ [LOWEST_PREF_KEY]: show }); } catch (e) { /* ignore */ }
                renderLowestBadges(variations, show);
            });
            // Restore the saved preference (global across products) and render accordingly.
            try {
                chrome.storage.local.get({ [LOWEST_PREF_KEY]: false }, (res) => {
                    const show = !!(res && res[LOWEST_PREF_KEY]);
                    lowestCheckbox.checked = show;
                    renderLowestBadges(variations, show);
                });
            } catch (e) { /* storage unavailable; feature stays off */ }

            legendToggle.onclick = () => {
                const isCollapsed = legendArea.classList.toggle('collapsed');
                legendToggle.querySelector('span').textContent = isCollapsed ? '▼' : '▲';
                legendToggle.querySelector('span').nextSibling.textContent = ` ${t(isCollapsed ? 'showLegend' : 'hideLegend')}`;
            };

            localeUpdates.push(() => {
                legendToggle.querySelector('span').nextSibling.textContent = ` ${t(legendArea.classList.contains('collapsed') ? 'showLegend' : 'hideLegend')}`;
            });

            const allVarNames = Object.keys(variations);
            // Initialize all as active
            const activeVariations = new Set(allVarNames);
            redraw = () => drawChart(canvas, variations, currentRange, null, activeVariations, isDemo, scaleState);

            const scaleControls = document.createElement('div');
            scaleControls.className = 'booth-price-scale-controls';
            const scaleStatus = document.createElement('span');
            scaleStatus.className = 'booth-price-scale-status';
            scaleStatus.setAttribute('aria-live', 'polite');
            const scaleToggle = document.createElement('button');
            scaleToggle.type = 'button';
            scaleToggle.className = 'booth-price-scale-btn';
            scaleToggle.setAttribute('role', 'switch');
            scaleToggle.setAttribute('aria-label', t('fullLabel'));
            scaleToggle.innerHTML = '<span class="booth-price-scale-track" aria-hidden="true"><span class="booth-price-scale-knob"></span><svg class="booth-price-scale-symbol booth-price-scale-triangle" viewBox="0 0 12 12" focusable="false"><path d="M6 1.34 L11 10 L1 10 Z"/></svg><svg class="booth-price-scale-symbol booth-price-scale-circle" viewBox="0 0 12 12" focusable="false"><circle cx="6" cy="6" r="4.8"/></svg></span>';
            scaleToggle.onclick = () => {
                scaleToggle.setAttribute('data-animated', 'true');
                scaleState.fullRange = !scaleState.fullRange;
                drawChart(canvas, variations, currentRange, null, activeVariations, isDemo, scaleState);
            };
            const overflowDetails = document.createElement('details');
            overflowDetails.className = 'booth-price-overflow-details';
            overflowDetails.hidden = true;
            scaleControls.append(scaleToggle, scaleStatus);
            headingRow.append(scaleControls, overflowDetails);

            // Map to keep track of legend items to update styles
            const legendItems = {};

            allVarNames.forEach((vName, idx) => {
                const color = COLORS[idx % COLORS.length];
                const item = document.createElement('div');
                item.style.cssText = 'display: flex; align-items: center; gap: 4px; cursor: pointer; padding: 2px 4px; border-radius: 4px; transition: opacity 0.2s, background 0.2s; user-select: none;';
                item.innerHTML = `<span style="width: 8px; height: 8px; background: ${color}; border-radius: 50%;"></span><span></span>`;

                const updateName = () => { item.lastElementChild.textContent = variationLabel(vName, scaleState.syntheticStandard); };
                updateName();
                localeUpdates.push(updateName);

                // Helper to update style based on active state
                const updateStyle = () => {
                    item.style.opacity = activeVariations.has(vName) ? '1.0' : '0.4';
                    item.style.textDecoration = activeVariations.has(vName) ? 'none' : 'line-through';
                };

                // Click Interaction: Toggle visibility
                item.onclick = () => {
                    if (activeVariations.has(vName)) {
                        activeVariations.delete(vName);
                    } else {
                        activeVariations.add(vName);
                    }
                    updateStyle();
                    // Redraw with current active set
                    drawChart(canvas, variations, currentRange, null, activeVariations, isDemo, scaleState);
                };

                // Hover Interaction: Highlight specific variation TEMPORARILY
                item.onmouseenter = () => {
                    if (!activeVariations.has(vName)) return; // Don't highlight if hidden
                    item.style.background = 'rgba(128, 128, 128, 0.1)';
                    drawChart(canvas, variations, currentRange, vName, activeVariations, isDemo, scaleState);
                };
                item.onmouseleave = () => {
                    item.style.background = 'transparent';
                    drawChart(canvas, variations, currentRange, null, activeVariations, isDemo, scaleState);
                };

                updateStyle();
                legendItems[vName] = item;
                legendArea.appendChild(item);
            });

            ranges.forEach(r => {
                const btn = document.createElement('button');
                btn.className = 'booth-price-range-btn' + (r.value === currentRange ? ' active' : '');
                const updateRange = () => { btn.textContent = MESSAGES[getPageLocale()].ranges[r.index]; };
                updateRange();
                localeUpdates.push(updateRange);
                btn.onclick = () => {
                    currentRange = r.value;
                    container.querySelectorAll('.booth-price-range-btn').forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    drawChart(canvas, variations, currentRange, null, activeVariations, isDemo, scaleState);
                };
                selector.appendChild(btn);
            });

            titleArea.appendChild(selector);
        }
        // Preserve the original order: chart, legend, lowest-price option, then heading/ranges.
        container.appendChild(titleArea);

        // Inject into the first variation or a prominent place
        const target = document.querySelector('.item-detail, .variations');
        if (target) {
            target.prepend(container);
        } else {
            priceElements[0].closest('li')?.appendChild(container) || document.body.appendChild(container);
        }

        const cleanupTheme = watchSwitchTheme(container);
        redraw();
        let lastLocale = getPageLocale();
        container.lang = lastLocale;
        const refreshLocale = () => {
            if (!container.isConnected) { container.boopaCleanup?.(); return; }
            const next = getPageLocale();
            if (next === lastLocale) return;
            lastLocale = next;
            container.lang = next;
            localeUpdates.forEach(update => update());
            redraw();
        };
        // BOOTH currently navigates on language selection. Also support live language
        // metadata replacement and back/forward without rebuilding controls or losing focus.
        const observer = new MutationObserver(refreshLocale);
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['lang', 'content'], childList: true, subtree: true });
        window.addEventListener('popstate', refreshLocale);
        window.addEventListener('pageshow', refreshLocale);
        container.boopaCleanup = () => {
            cleanupTheme();
            observer.disconnect();
            window.removeEventListener('popstate', refreshLocale);
            window.removeEventListener('pageshow', refreshLocale);
        };
    }

    const COLORS = ['#fc4d50', '#4a90e2', '#7fb800', '#f5a623', '#9013fe', '#bd10e0'];

    function drawChart(canvas, variations, range, highlightName, activeVariations = null, isDemo = false, scaleState = { fullRange: false }) {
        // Clear stale hover targets and tooltip even when the next view is empty.
        canvas.pointsToHover = [];
        const oldTooltip = canvas.parentElement.querySelector('.booth-chart-tooltip');
        if (oldTooltip) oldTooltip.style.display = 'none';
        const scaleStatus = canvas.parentElement.querySelector('.booth-price-scale-status');
        const scaleToggle = canvas.parentElement.querySelector('.booth-price-scale-btn');
        if (scaleStatus) scaleStatus.textContent = t('fullStatus');
        const overflowDetails = canvas.parentElement.querySelector('.booth-price-overflow-details');
        const clearOverflowDetails = () => {
            if (!overflowDetails) return;
            overflowDetails.hidden = true;
            overflowDetails.replaceChildren();
            overflowDetails.boopaRecordsKey = null;
        };
        const ctx = canvas.getContext('2d');
        const containerWidth = canvas.clientWidth || 300;
        const containerHeight = canvas.clientHeight || 150;
        canvas.width = containerWidth * window.devicePixelRatio;
        canvas.height = containerHeight * window.devicePixelRatio;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.scale(window.devicePixelRatio, window.devicePixelRatio);

        if (isDemo) {
            if (scaleToggle) scaleToggle.hidden = true;
            clearOverflowDetails();
            ctx.fillStyle = '#999';
            ctx.font = '12px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(t('noCollection'), containerWidth / 2, containerHeight / 2);
            return;
        }

        const now = new Date();
        const filteredVars = {};
        let allPoints = [];

        Object.keys(variations).forEach(vName => {
            // Skip if not active (and active set is provided)
            if (activeVariations && !activeVariations.has(vName)) return;

            let data = variations[vName].filter(d => Number.isFinite(d.price) && d.price >= 0);
            if (range !== 'all') {
                let cutoff = new Date();
                if (range === 'ytd') {
                    cutoff = new Date(now.getFullYear(), 0, 1);
                } else {
                    cutoff.setDate(now.getDate() - range);
                }
                data = data.filter(d => new Date(d.date) >= cutoff);
            }
            if (data.length > 0) {
                filteredVars[vName] = data;
                allPoints = allPoints.concat(data);
            }
        });

        if (allPoints.length === 0) {
            if (scaleToggle) scaleToggle.hidden = true;
            clearOverflowDetails();
            ctx.fillStyle = '#999';
            ctx.font = '12px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(t('noData'), containerWidth / 2, containerHeight / 2);
            return;
        }

        const separated = new Set();
        Object.values(filteredVars).forEach(data => {
            findSeparatedHighPoints(data).forEach(point => separated.add(point));
        });
        const zoomed = separated.size > 0 && !scaleState.fullRange;
        const axisPoints = zoomed ? allPoints.filter(d => !separated.has(d)) : allPoints;
        const prices = axisPoints.map(d => d.price);
        const minPrice = Math.min(...prices) * 0.95;
        const maxPrice = Math.max(...prices) * 1.05;
        const overflow = zoomed ? allPoints.filter(d => d.price > maxPrice) : [];
        if (scaleStatus) scaleStatus.textContent = zoomed
            ? t('zoomStatus', { n: overflow.length })
            : t('fullStatus');
        if (scaleToggle) {
            scaleToggle.hidden = separated.size === 0;
            scaleToggle.setAttribute('aria-checked', String(scaleState.fullRange));
            scaleToggle.setAttribute('aria-label', t('fullLabel'));
            scaleToggle.title = t(zoomed ? 'fullTitle' : 'zoomTitle');
        }
        if (overflowDetails && overflow.length) {
            const records = [];
            Object.entries(filteredVars).forEach(([name, data]) => data.forEach(d => {
                if (d.price > maxPrice) records.push({ name: variationLabel(name, scaleState.syntheticStandard), date: d.date, price: d.price });
            }));
            const recordsKey = getPageLocale() + JSON.stringify(records);
            // Hover redraws must not replace the focused summary or collapse the list.
            if (overflowDetails.boopaRecordsKey !== recordsKey) {
                const summary = overflowDetails.children?.[0] || document.createElement('summary');
                summary.textContent = t('overflow', { n: overflow.length });
                const list = document.createElement('div');
                list.className = 'booth-price-history-scroll';
                list.setAttribute('tabindex', '0');
                list.setAttribute('role', 'region');
                list.setAttribute('aria-label', t('historyLabel'));
                const table = document.createElement('table');
                table.className = 'booth-price-history-table';
                table.setAttribute('aria-label', t('historyLabel'));
                const head = document.createElement('thead');
                const headings = document.createElement('tr');
                ['historyProduct', 'historyDate', 'historyPrice'].forEach(key => {
                    const cell = document.createElement('th');
                    cell.setAttribute('scope', 'col');
                    cell.textContent = t(key);
                    headings.appendChild(cell);
                });
                head.appendChild(headings);
                table.appendChild(head);
                const body = document.createElement('tbody');
                records.forEach(record => {
                    const row = document.createElement('tr');
                    [record.name, formatDate(record.date), formatPrice(record.price)].forEach(value => {
                        const cell = document.createElement('td');
                        cell.textContent = value;
                        row.appendChild(cell);
                    });
                    body.appendChild(row);
                });
                table.appendChild(body);
                list.appendChild(table);
                if (overflowDetails.children?.[0] === summary) {
                    // Keep the focused summary mounted during locale/data changes.
                    const oldList = overflowDetails.children[1];
                    if (oldList?.replaceWith) oldList.replaceWith(list);
                    else overflowDetails.replaceChildren(summary, list);
                } else {
                    overflowDetails.replaceChildren(summary, list);
                }
                overflowDetails.boopaRecordsKey = recordsKey;
            }
            overflowDetails.hidden = false;
        } else {
            clearOverflowDetails();
        }
        const padding = 35;
        const bottomPadding = 30;

        const chartHeight = containerHeight - padding - bottomPadding;
        const chartWidth = containerWidth - padding * 2;

        const allDates = [...new Set(allPoints.map(d => d.date))].sort();
        const startDate = new Date(allDates[0]);
        const endDate = new Date(allDates[allDates.length - 1]);
        const timeRange = (endDate - startDate) || 1;

        const getX = (dateStr) => {
            if (timeRange === 1) return padding + chartWidth / 2;
            const d = new Date(dateStr);
            return padding + ((d - startDate) / timeRange) * chartWidth;
        };

        const getY = (price) => {
            if (maxPrice === minPrice) return padding + chartHeight / 2;
            return padding + chartHeight - ((price - minPrice) / (maxPrice - minPrice)) * chartHeight;
        };

        // Detect text color from computed style for labels
        const compStyle = window.getComputedStyle(canvas.parentElement);
        const labelColor = compStyle.color || '#999';

        // Draw background lines
        ctx.strokeStyle = 'rgba(128, 128, 128, 0.2)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(padding, getY(minPrice / 0.95));
        ctx.lineTo(padding + chartWidth, getY(minPrice / 0.95));
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(padding, getY(maxPrice / 1.05));
        ctx.lineTo(padding + chartWidth, getY(maxPrice / 1.05));
        ctx.stroke();

        ctx.fillStyle = labelColor;
        ctx.globalAlpha = 0.6;
        ctx.font = '9px sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(formatPrice(Math.round(minPrice / 0.95)), 0, getY(minPrice / 0.95));
        ctx.fillText(formatPrice(Math.round(maxPrice / 1.05)), 0, getY(maxPrice / 1.05));

        ctx.textAlign = 'left';
        ctx.fillText(formatDate(allDates[0]), padding, containerHeight - 10);
        if (allDates.length > 1) {
            ctx.textAlign = 'right';
            ctx.fillText(formatDate(allDates[allDates.length - 1]), padding + chartWidth, containerHeight - 10);
        }

        const pointsToHover = [];
        const allVarNames = Object.keys(variations); // Stable order for colors based on full data set

        Object.keys(filteredVars).forEach((vName) => {
            const data = filteredVars[vName];
            const colorIndex = allVarNames.indexOf(vName);
            const color = COLORS[colorIndex % COLORS.length];

            // Determine visibility/emphasis
            let alpha = 0.8;
            let lineWidth = 2;
            if (highlightName) {
                if (vName === highlightName) {
                    alpha = 1.0;
                    lineWidth = 3; // Emphasize
                } else {
                    return; // Strictly hide others
                }
            }

            ctx.globalAlpha = alpha;
            ctx.beginPath();
            ctx.strokeStyle = color;
            ctx.lineWidth = lineWidth;
            ctx.lineJoin = 'round';
            ctx.lineCap = 'round';
            let segmentOpen = false;
            data.forEach((d, i) => {
                const x = getX(d.date);
                const outside = zoomed && d.price > maxPrice;
                const y = outside ? padding : getY(d.price);
                if (outside) {
                    // Do not connect the ordinary readings across an off-scale interval.
                    segmentOpen = false;
                } else {
                    if (!segmentOpen) ctx.moveTo(x, y);
                    else ctx.lineTo(x, y);
                    segmentOpen = true;
                }
                // Keep every day hoverable even though we only draw markers at key points.
                pointsToHover.push({ x, y, data: d, vName, color, outside });
            });
            ctx.stroke();

            // Markers: only at meaningful points — the first reading, the last reading,
            // and any day the price actually changed. Long flat stretches previously drew
            // a dot every single day, so daily data collapsed into a solid bar of circles.
            // Drawing only the "corners" keeps the line clean even on the 最大 (all) range.
            // A pixel-gap filter guarantees markers never overlap when changes cluster.
            const isEmphasized = highlightName === vName;
            const markerRadius = isEmphasized ? 4 : 3;
            const minMarkerGap = markerRadius * 2 + 2; // px between adjacent markers
            let lastMarkerX = -Infinity;

            ctx.globalAlpha = 1.0;
            ctx.fillStyle = color;
            data.forEach((d, i) => {
                if (zoomed && d.price > maxPrice) {
                    const x = getX(d.date);
                    ctx.beginPath();
                    ctx.moveTo(x, padding - 5);
                    ctx.lineTo(x - 4, padding + 3);
                    ctx.lineTo(x + 4, padding + 3);
                    ctx.closePath();
                    ctx.fill();
                    return;
                }
                const isFirst = i === 0 || (zoomed && data[i - 1].price > maxPrice);
                const isLast = i === data.length - 1;
                const priceChanged = i > 0 && d.price !== data[i - 1].price;
                if (!isFirst && !isLast && !priceChanged) return;

                const x = getX(d.date);
                // Thin out markers that would visually collide, but always keep the last
                // point so the current price is marked.
                if (!isLast && x - lastMarkerX < minMarkerGap) return;
                lastMarkerX = x;

                ctx.beginPath();
                ctx.arc(x, getY(d.price), markerRadius, 0, Math.PI * 2);
                ctx.fill();
            });
            ctx.globalAlpha = 1.0;
        });

        let tooltip = canvas.parentElement.querySelector('.booth-chart-tooltip');
        if (!tooltip) {
            tooltip = document.createElement('div');
            tooltip.className = 'booth-chart-tooltip';
            canvas.parentElement.appendChild(tooltip);
        }

        // Attach current points to canvas for the event listener to access
        canvas.pointsToHover = pointsToHover;

        if (!canvas.dataset.hasListener) {
            canvas.addEventListener('mousemove', (e) => {
                const rect = canvas.getBoundingClientRect();
                const mx = e.clientX - rect.left;
                const my = e.clientY - rect.top;

                let hoveredPoint = null;
                let minDist = 20;

                // Use the latest points attached to the canvas
                const currentPoints = canvas.pointsToHover || [];

                currentPoints.forEach(p => {
                    const dx = mx - p.x;
                    const dy = my - p.y;
                    const dist = Math.sqrt(dx * dx + dy * dy);
                    if (dist < minDist) {
                        minDist = dist;
                        hoveredPoint = p;
                    }
                });

                if (hoveredPoint) {
                    tooltip.style.display = 'block';
                    tooltip.style.left = `${canvas.offsetLeft + hoveredPoint.x}px`;
                    tooltip.style.top = `${canvas.offsetTop + hoveredPoint.y - 5}px`;
                    tooltip.style.borderLeft = `3px solid ${hoveredPoint.color}`;
                    tooltip.replaceChildren();
                    // Use the original product / date / price stack for both
                    // normal points and ▲ records; never interpret names as HTML.
                    const appendPoint = (target, point) => {
                        const name = document.createElement('strong');
                        name.textContent = variationLabel(point.vName, scaleState.syntheticStandard);
                        target.appendChild(name);
                        if (point.outside) {
                            const outlier = document.createElement('span');
                            outlier.className = 'booth-chart-outlier-badge';
                            outlier.textContent = t('outlier');
                            outlier.title = t('outside').trim();
                            outlier.setAttribute('aria-label', `${t('outlier')} ${t('outside').trim()}`);
                            outlier.style.cssText = 'background:#ffdf00; color:#000; padding:1px 4px; border-radius:3px; font-size:10px; margin-left:5px; font-weight:bold; vertical-align:middle;';
                            target.appendChild(outlier);
                        }
                        if (point.data.is_sale) {
                            const sale = document.createElement('span');
                            sale.textContent = 'SALE';
                            sale.style.cssText = 'background:#ff3838; color:white; padding:1px 4px; border-radius:3px; font-size:10px; margin-left:5px; font-weight:bold; vertical-align:middle;';
                            target.appendChild(sale);
                        }
                        target.appendChild(document.createElement('br'));
                        const date = document.createElement('span');
                        date.textContent = formatDate(point.data.date);
                        target.appendChild(date);
                        target.appendChild(document.createElement('br'));
                        const price = document.createElement('span');
                        price.textContent = formatPrice(point.data.price);
                        target.appendChild(price);
                    };
                    if (hoveredPoint.outside) {
                        // Keep every coincident record accessible, one stack per
                        // product. The disclosure also supports touch/keyboard use.
                        currentPoints.filter(p => p.outside && Math.abs(p.x - hoveredPoint.x) < 1)
                            .forEach((p, index) => {
                                const row = document.createElement('div');
                                if (index > 0) row.style.marginTop = '8px';
                                appendPoint(row, p);
                                tooltip.appendChild(row);
                            });
                    } else {
                        appendPoint(tooltip, hoveredPoint);
                    }
                } else {
                    tooltip.style.display = 'none';
                }
            });

            canvas.addEventListener('mouseleave', () => tooltip.style.display = 'none');
            canvas.dataset.hasListener = 'true';
        }
    }

    async function main(retryCount = 0) {
        const result = await fetchPriceHistory();
        if (result && result.data && Object.keys(result.data).length > 0) {
            injectTracker(result);
        } else if (retryCount < 3) {
            console.log(`[Boopa] No data/target found, retrying... (${retryCount + 1}/3)`);
            setTimeout(() => main(retryCount + 1), 1000);
        } else {
            console.log('[Boopa] Giving up after 3 retries.');
        }
    }

    main();
})();
