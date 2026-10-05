const axios = require('axios');
const cheerio = require('cheerio');
const fs = require('fs');
const path = require('path');

const SEARCH_URLS = [
    'https://booth.pm/ja/browse/3D%E3%83%A2%E3%83%87%E3%83%AB?sort=new&tags%5B%5D=VRChat&type=digital',
    'https://booth.pm/ja/browse/%E3%82%BD%E3%83%95%E3%83%88%E3%82%A6%E3%82%A7%E3%82%A2?sort=new&tags%5B%5D=VRChat&type=digital'
];

const {
    getStopTargetTime, jstDate, writeJson
} = require('./collection-runtime');

const DATA_DIR = path.join(__dirname, '..', 'data');
const MAX_PAGES = 3333; // BOOTH's search limit; keep both full categories.

async function scrapeSearchPage(url, client) {
    try {
        console.log(`Scraping Search: ${url}`);
        const response = await client.get(url, { redirectPolicy: 'same-url' });
        if (response.status !== 200) throw new Error(`Search returned HTTP ${response.status}`);
        const $ = cheerio.load(response.data);
        const productIds = [];
        let invalidCard = false;
        $('.item-card').each((i, el) => {
            const id = $(el).attr('data-product-id');
            if (id && /^[1-9]\d*$/.test(id)) productIds.push(id);
            else invalidCard = true;
        });
        if (invalidCard) throw new Error('Search card is missing a valid product ID');
        if (productIds.length > 0) return { kind: 'success', ids: [...new Set(productIds)] };
        // A failed/challenge/unrecognized response is not proof of an empty page.
        const searchShell = $('title').text().includes('BOOTH') &&
            $('a[href*="/browse/"], form[action*="/search"], form[action*="/browse/"]').length > 0;
        const explicitEmpty = /(?:商品が見つかりませんでした|検索結果はありません|検索結果がありません|該当する商品[はが]ありません)/.test($('body').text());
        if (!searchShell || !explicitEmpty) throw new Error('Unrecognized search page markup');
        return { kind: 'empty', ids: [] };
    } catch (error) {
        console.error(`Error scraping search ${url}:`, error.message);
        return { kind: 'failure', error };
    }
}

// A trailing shop sale badge: a final (...) containing a number, a %/円, and a discount
// word (OFF/オフ/SALE/セール) in any order — "(30% OFF)", "(30% SALE)", "(890円 OFF)".
// Requiring all three keeps real names like "(コットン100%)" or "(…100％割引)" intact.
// No /g flag, so .test() is stateless and safe to reuse.
const SALE_BADGE_RE = /\s*[\(（](?=[^)）]*\d)(?=[^)）]*[%％円])(?=[^)）]*(?:OFF|オフ|SALE|セール))[^)）]*[\)）]\s*$/i;

/**
 * Removes a trailing sale badge AND collapses stray whitespace so a variation's price
 * history stays under one stable key, e.g. "✧ Shinano | しなの (30% OFF)" -> "✧ Shinano | しなの".
 */
function normalizeVariationName(name) {
    return name
        .replace(SALE_BADGE_RE, '')
        .replace(/\s{2,}/g, ' ')
        .trim();
}

async function scrapeProductDetails(productId, client) {
    const url = `https://booth.pm/ja/items/${productId}`;
    try {
        const response = await client.get(url, { productId: String(productId) });
        if (response.status === 404 || response.status === 410) {
            return { kind: 'unavailable', id: productId, status: response.status };
        }
        const $ = cheerio.load(response.data);

        // New selector: h2 is the title
        const name = $('h2').first().text().trim();
        const variations = [];

        // New selectors: .variation-item, .variation-name, .variation-price
        $('.variation-item').each((i, el) => {
            const rawName = $(el).find('.variation-name').text().trim() || 'default';
            // BOOTH gives every variation a stable internal ID (data-product-variant, aka
            // cart_item_variation_id) that does NOT change when the shop renames the
            // variation. Some shops rewrite the name on every sale (e.g.
            // "✧ Shinano | しなの (30% OFF)"), which would otherwise spawn a brand new key
            // each time. Capturing the ID lets us anchor history to identity, not name.
            const variantId = $(el).find('[data-product-variant]').first().attr('data-product-variant') || null;
            // Strip a trailing discount badge for a clean, stable display label. The
            // presence of that badge (not mere whitespace cleanup) tells us it's on sale.
            const vName = normalizeVariationName(rawName);
            const nameImpliesSale = SALE_BADGE_RE.test(rawName);
            const priceText = $(el).find('.variation-price, .price, .text-20.font-bold').first().text();
            const price = /^\s*無料\s*$/.test(priceText) ? 0 : parseInt(priceText.replace(/[^\d]/g, ''), 10);

            // Check for sale class or indicator
            const isSale = nameImpliesSale ||
                $(el).find('.price, .variation-price').hasClass('is-sale') ||
                $(el).find('.is-sale').length > 0;

            if (!isNaN(price)) {
                variations.push({ name: vName, price, isSale, variantId });
            }
        });

        // Fallback for older or different layouts if any
        if (variations.length === 0) {
            const priceText = $('.item-detail__price .price, .price, .text-20.font-bold').first().text();
            const price = /^\s*無料\s*$/.test(priceText) ? 0 : parseInt(priceText.replace(/[^\d]/g, ''), 10);
            const isSale = $('.price').hasClass('is-sale') || $('.is-sale').length > 0;
            if (!isNaN(price)) {
                variations.push({ name: 'default', price, isSale });
            }
        }

        // Detect sale keywords in title
        const saleKeywords = ['sale', 'セール', '割引', '期間限定', 'off'];
        const hasSaleKeyword = saleKeywords.some(k => name.toLowerCase().includes(k));

        if (!name || variations.length === 0) throw new Error('Unrecognized product page or missing price');
        return { kind: 'success', product: { id: productId, name, variations, hasSaleKeyword } };
    } catch (error) {
        console.error(`Error scraping item ${productId}:`, error.message);
        return { kind: 'failure', error };
    }
}

async function saveProductData(product, { dataDir = DATA_DIR, today = jstDate(Date.now()) } = {}) {
    const shard = product.id.toString().substring(0, 3);
    const shardDir = path.join(dataDir, shard);
    if (!fs.existsSync(shardDir)) {
        fs.mkdirSync(shardDir, { recursive: true });
    }

    const filePath = path.join(shardDir, `${product.id}.json`);
    let result = {
        id: product.id,
        name: product.name,
        variations: {}
    };

    if (fs.existsSync(filePath)) {
        try {
            const existing = JSON.parse(fs.readFileSync(filePath, 'utf8'));
            if (existing && typeof existing === 'object' && !Array.isArray(existing)) {
                const record = value => value && typeof value === 'object' && !Array.isArray(value);
                if ((existing.variations !== undefined && (!record(existing.variations) ||
                    !Object.values(existing.variations).every(Array.isArray))) ||
                    (existing.variation_keys !== undefined && (!record(existing.variation_keys) ||
                        !Object.values(existing.variation_keys).every(key => typeof key === 'string')))) {
                    throw new Error('History has incompatible variation records');
                }
                result = existing;
                // [Self-Healing] Update name if it's missing or empty
                if (product.name && (!result.name || result.name.trim() === "")) {
                    result.name = product.name;
                }
            } else {
                throw new Error('History must be a JSON object');
            }
        } catch (e) {
            const error = new Error(`Cannot read existing history for ${product.id}: ${e.message}`, { cause: e });
            error.code = e.code;
            throw error;
        }
    }

    if (!result.variations) {
        result.variations = {};
    }
    // Map of BOOTH's stable variation ID -> the canonical key we store its history under.
    // Anchoring identity to the ID means a shop renaming a variation (sale badges, emoji,
    // reworded names) can never split one variation into multiple keys / chart lines.
    if (!result.variation_keys) {
        result.variation_keys = {};
    }

    // Update each variation
    product.variations.forEach(v => {
        // Resolve the stable storage key for this variation.
        let key = (v.variantId && result.variation_keys[v.variantId]) || null;
        if (!key) {
            key = v.name;
            // First time we see this ID and there is no clean bucket yet: adopt an existing
            // bucket that normalizes to the same name (older data collected before
            // ID-anchoring, possibly fragmented by sale badges) so history stays continuous.
            if (!result.variations[key]) {
                const match = Object.keys(result.variations)
                    .find(k => normalizeVariationName(k) === v.name);
                if (match) key = match;
            }
            if (v.variantId) {
                result.variation_keys[v.variantId] = key;
            }
        }

        if (!result.variations[key]) {
            result.variations[key] = [];
        }

        const history = result.variations[key];
        const existingEntryIndex = history.findIndex(entry => entry.date === today);

        // Price drop heuristic
        const lastValidEntry = [...history].reverse().find(entry => entry.date !== today);
        let isSaleFinal = v.isSale || product.hasSaleKeyword;
        if (!isSaleFinal && lastValidEntry && v.price < lastValidEntry.price) {
            isSaleFinal = true;
        }

        const newEntry = {
            date: today,
            price: v.price,
            is_sale: isSaleFinal
        };

        if (existingEntryIndex !== -1) {
            history[existingEntryIndex] = newEntry;
        } else {
            history.push(newEntry);
        }
        history.sort((a, b) => a.date.localeCompare(b.date));
    });

    writeJson(filePath, result);
}

function loadState(stateFile) {
    return require('./collector').loadDiscoveryState(stateFile);
}

async function main(options = {}) {
    return require('./collector').runCollector({
        dataDir: DATA_DIR, searchUrls: SEARCH_URLS, maxPages: MAX_PAGES,
        get: axios.get, search: scrapeSearchPage, detail: scrapeProductDetails, save: saveProductData,
        ...options
    });
}

// Importing the module for offline tests never starts network collection.
if (require.main === module) {
    // Workflow reserves and pushes quota before starting. Refuse an accidental
    // unbudgeted manual CLI collection; tests use the injected main() interface.
    const run = process.env.SCRAPER_RESERVATION_ID
        ? main()
        : Promise.reject(new Error('Run through the workflow with a committed request reservation'));
    run.then(result => {
        console.log(`Collection result: ${result.status}${result.reason ? ` (${result.reason})` : ''}`);
        if (result.failed || result.status === 'failed') process.exitCode = 1;
    }).catch(error => {
        console.error('Scraper failed:', error);
        process.exitCode = 1;
    });
}

module.exports = {
    normalizeVariationName, scrapeSearchPage, scrapeProductDetails, saveProductData,
    loadState, main, getStopTargetTime
};
