const axios = require('axios');
const cheerio = require('cheerio');
const fs = require('fs');
const path = require('path');

const SEARCH_URLS = [
    'https://booth.pm/ja/browse/3D%E3%83%A2%E3%83%87%E3%83%AB?sort=new&tags%5B%5D=VRChat&type=digital',
    'https://booth.pm/ja/browse/%E3%82%BD%E3%83%95%E3%83%88%E3%82%A6%E3%82%A7%E3%82%A2%E3%83%BB%E3%83%8F%E3%83%BC%E3%83%89%E3%82%A6%E3%82%A7%E3%82%A2?sort=new&tags%5B%5D=VRChat&type=digital'
];

const DATA_DIR = path.join(__dirname, '..', 'data');
const TODAY = new Intl.DateTimeFormat('ja-JP', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
}).format(new Date()).replace(/\//g, '-');
const MAX_PAGES = 3333; // BOOTH's search limit
const DELAY_MS = 1500;
const MAX_EXECUTION_TIME_MS = 5 * 60 * 60 * 1000; // 5 hours
const STATE_FILE = path.join(DATA_DIR, 'crawl_state.json');
const SCHEDULE_HOURS = [0, 6, 12, 18]; // JST schedule

/**
 * Calculates the target time to stop the scraper.
 * It should be at most 5 hours from start, or 30 minutes before the next scheduled run.
 */
function getStopTargetTime(startTime) {
    const now = new Date(startTime);
    
    // Find the next scheduled run in JST
    // Since TZ=Asia/Tokyo is set in environment, Date methods use JST
    const currentHour = now.getHours();
    let nextHour = SCHEDULE_HOURS.find(h => h > currentHour);
    const nextRun = new Date(now);
    
    if (nextHour === undefined) {
        nextHour = SCHEDULE_HOURS[0];
        nextRun.setDate(nextRun.getDate() + 1);
    }
    nextRun.setHours(nextHour, 0, 0, 0);
    
    // 30 minutes before next run
    const targetStopBeforeNextRun = new Date(nextRun.getTime() - 30 * 60 * 1000);
    
    // 5 hours from start
    const hardExecutionLimit = new Date(startTime + MAX_EXECUTION_TIME_MS);
    
    // Use whichever comes first
    return targetStopBeforeNextRun < hardExecutionLimit ? targetStopBeforeNextRun : hardExecutionLimit;
}

async function scrapeSearchPage(url) {
    try {
        console.log(`Scraping Search: ${url}`);
        const response = await axios.get(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        });
        const $ = cheerio.load(response.data);
        const productIds = [];

        $('.item-card').each((i, el) => {
            const id = $(el).attr('data-product-id');
            if (id) productIds.push(id);
        });

        return productIds;
    } catch (error) {
        console.error(`Error scraping search ${url}:`, error.message);
        return [];
    }
}

async function scrapeProductDetails(productId) {
    const url = `https://booth.pm/ja/items/${productId}`;
    try {
        const response = await axios.get(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        });
        const $ = cheerio.load(response.data);

        // New selector: h2 is the title
        const name = $('h2').first().text().trim();
        const variations = [];

        // New selectors: .variation-item, .variation-name, .variation-price
        $('.variation-item').each((i, el) => {
            const vName = $(el).find('.variation-name').text().trim() || 'default';
            const priceText = $(el).find('.variation-price, .price, .text-20.font-bold').text();
            const price = parseInt(priceText.replace(/[^\d]/g, ''), 10);

            // Check for sale class or indicator
            const isSale = $(el).find('.price, .variation-price').hasClass('is-sale') ||
                $(el).find('.is-sale').length > 0;

            if (!isNaN(price)) {
                variations.push({ name: vName, price, isSale });
            }
        });

        // Fallback for older or different layouts if any
        if (variations.length === 0) {
            const priceText = $('.item-detail__price .price, .price, .text-20.font-bold').first().text();
            const price = parseInt(priceText.replace(/[^\d]/g, ''), 10);
            const isSale = $('.price').hasClass('is-sale') || $('.is-sale').length > 0;
            if (!isNaN(price)) {
                variations.push({ name: 'default', price, isSale });
            }
        }

        // Detect sale keywords in title
        const saleKeywords = ['sale', 'セール', '割引', '期間限定', 'off'];
        const hasSaleKeyword = saleKeywords.some(k => name.toLowerCase().includes(k));

        return { id: productId, name, variations, hasSaleKeyword };
    } catch (error) {
        console.error(`Error scraping item ${productId}:`, error.message);
        return null;
    }
}

async function saveProductData(product) {
    const shard = product.id.toString().substring(0, 3);
    const shardDir = path.join(DATA_DIR, shard);
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
            if (existing && typeof existing === 'object') {
                result = existing;
                // [Self-Healing] Update name if it's missing or empty
                if (product.name && (!result.name || result.name.trim() === "")) {
                    result.name = product.name;
                }
            }
        } catch (e) {
            console.error(`Error parsing existing data for ${product.id}`);
        }
    }

    if (!result.variations) {
        result.variations = {};
    }

    // Update each variation
    product.variations.forEach(v => {
        if (!result.variations[v.name]) {
            result.variations[v.name] = [];
        }

        const history = result.variations[v.name];
        const existingEntryIndex = history.findIndex(entry => entry.date === TODAY);

        // Price drop heuristic
        const lastValidEntry = [...history].reverse().find(entry => entry.date !== TODAY);
        let isSaleFinal = v.isSale || product.hasSaleKeyword;
        if (!isSaleFinal && lastValidEntry && v.price < lastValidEntry.price) {
            isSaleFinal = true;
        }

        const newEntry = {
            date: TODAY,
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

    fs.writeFileSync(filePath, JSON.stringify(result, null, 2));
}

function loadState() {
    if (fs.existsSync(STATE_FILE)) {
        try {
            return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
        } catch (e) {
            console.error('Failed to load state file:', e);
        }
    }
    return { urlIndex: 0, page: 1 };
}

function saveState(urlIndex, page) {
    fs.writeFileSync(STATE_FILE, JSON.stringify({ urlIndex, page }, null, 2));
}

async function main() {
    if (!fs.existsSync(DATA_DIR)) {
        fs.mkdirSync(DATA_DIR, { recursive: true });
    }

    const processedIds = new Set();
    const startTime = Date.now();
    const stopTargetTime = getStopTargetTime(startTime);
    let state = loadState();

    console.log(`Current Time: ${new Date(startTime).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })}`);
    console.log(`Target Stop Time: ${stopTargetTime.toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })}`);
    console.log(`Resuming from URL Index: ${state.urlIndex}, Page: ${state.page}`);

    for (let uIdx = state.urlIndex; uIdx < SEARCH_URLS.length; uIdx++) {
        const baseUrl = SEARCH_URLS[uIdx];
        console.log(`Starting crawl for URL [${uIdx}]: ${baseUrl}`);

        // Start from saved page if resuming, otherwise page 1
        const startPage = (uIdx === state.urlIndex) ? state.page : 1;

        for (let page = startPage; page <= MAX_PAGES; page++) {
            // Check time limit
            if (Date.now() > stopTargetTime.getTime()) {
                console.log(`[Time Limit] Target stop time reached (${stopTargetTime.toLocaleString()}). Saving state and stopping safely.`);
                saveState(uIdx, page);
                return;
            }

            const url = `${baseUrl}&page=${page}`;
            const ids = await scrapeSearchPage(url);
            if (ids.length === 0) {
                console.log(`No more items found at page ${page}. Moving to next category.`);
                break;
            }

            // Parallel processing in batches
            const CONCURRENCY = 5;
            for (let i = 0; i < ids.length; i += CONCURRENCY) {
                const chunk = ids.slice(i, i + CONCURRENCY);
                const promises = chunk.map(async (id) => {
                    if (processedIds.has(id)) return;

                    const details = await scrapeProductDetails(id);
                    if (details) {
                        await saveProductData(details);
                        console.log(`Saved: [${id}] ${details.name} (${details.variations.length} vars)`);
                    }
                    processedIds.add(id);
                });

                await Promise.all(promises);

                // Reduced delay for faster processing
                await new Promise(resolve => setTimeout(resolve, 1000));
            }

            // Save state after every successful page crawl
            saveState(uIdx, page + 1);

            // Small delay between search pages
            await new Promise(resolve => setTimeout(resolve, 2000));
        }
    }

    console.log('Scraping completed. Clearing state.');
    if (fs.existsSync(STATE_FILE)) {
        fs.unlinkSync(STATE_FILE);
    }
}

main();
