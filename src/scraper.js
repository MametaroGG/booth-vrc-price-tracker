const axios = require('axios');
const cheerio = require('cheerio');
const fs = require('fs');
const path = require('path');

const SEARCH_URLS = [
    'https://booth.pm/ja/browse/3D%E3%83%A2%E3%83%87%E3%83%AB?sort=new&tags%5B%5D=VRChat&type=digital',
    'https://booth.pm/ja/browse/%E3%82%BD%E3%83%95%E3%83%88%E3%82%A6%E3%82%A7%E3%82%A2%E3%83%BB%E3%83%8F%E3%83%BC%E3%83%89%E3%82%A6%E3%82%A7%E3%82%A2?sort=new&tags%5B%5D=VRChat&type=digital'
];

const DATA_DIR = path.join(__dirname, '..', 'data');
const TODAY = new Date().toISOString().split('T')[0];
const MAX_PAGES = 3333; // BOOTH's search limit
const DELAY_MS = 1500;

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
        const name = $('.item-detail__title').text().trim();
        const variations = [];

        // Variation logic: find prices and variation group
        $('.variation-card').each((i, el) => {
            const vName = $(el).find('.variation-name').text().trim() || 'default';
            const price = parseInt($(el).find('.price').text().replace(/[^\d]/g, ''), 10);
            const isSale = $(el).find('.price').hasClass('is-sale');
            if (!isNaN(price)) {
                variations.push({ name: vName, price, isSale });
            }
        });

        // Fallback for single variation pages
        if (variations.length === 0) {
            const price = parseInt($('.item-detail__price .price').text().replace(/[^\d]/g, ''), 10);
            const isSale = $('.item-detail__price .price').hasClass('is-sale');
            if (!isNaN(price)) {
                variations.push({ name: 'default', price, isSale });
            }
        }

        return { id: productId, name, variations };
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
            result = JSON.parse(fs.readFileSync(filePath, 'utf8'));
        } catch (e) {
            console.error(`Error parsing existing data for ${product.id}`);
        }
    }

    // Update each variation
    product.variations.forEach(v => {
        if (!result.variations[v.name]) {
            result.variations[v.name] = [];
        }

        const history = result.variations[v.name];
        const existingEntryIndex = history.findIndex(entry => entry.date === TODAY);
        const newEntry = {
            date: TODAY,
            price: v.price,
            is_sale: v.isSale
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

async function main() {
    if (!fs.existsSync(DATA_DIR)) {
        fs.mkdirSync(DATA_DIR, { recursive: true });
    }

    const processedIds = new Set();

    for (const baseUrl of SEARCH_URLS) {
        console.log(`Starting crawl for: ${baseUrl}`);
        for (let page = 1; page <= MAX_PAGES; page++) {
            const url = `${baseUrl}&page=${page}`;
            const ids = await scrapeSearchPage(url);
            if (ids.length === 0) break;

            for (const id of ids) {
                if (processedIds.has(id)) continue;

                const details = await scrapeProductDetails(id);
                if (details) {
                    await saveProductData(details);
                    console.log(`Saved: [${id}] ${details.name} (${details.variations.length} vars)`);
                }
                processedIds.add(id);

                // Be polite, wait for 1 second between items
                await new Promise(resolve => setTimeout(resolve, 1000));
            }

            // Small delay between search pages
            await new Promise(resolve => setTimeout(resolve, 2000));
        }
    }

    console.log('Scraping completed.');
}

main();
