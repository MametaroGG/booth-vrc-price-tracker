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

async function scrapePage(url) {
    try {
        console.log(`Scraping: ${url}`);
        const response = await axios.get(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        });
        const $ = cheerio.load(response.data);
        const products = [];

        $('.item-card').each((i, el) => {
            const productId = $(el).attr('data-product-id');
            const priceText = $(el).find('.price').text().replace(/[^\d]/g, '');
            const price = parseInt(priceText, 10);
            const isSale = $(el).find('.price').hasClass('is-sale') || $(el).find('.on-sale').length > 0;
            const name = $(el).find('.item-card__title').text().trim();

            if (productId && !isNaN(price)) {
                products.push({
                    id: productId,
                    name: name,
                    price: price,
                    is_sale: isSale
                });
            }
        });

        return products;
    } catch (error) {
        console.error(`Error scraping ${url}:`, error.message);
        return [];
    }
}

async function saveProductData(product) {
    // Sharding: Use first 3 characters of ID for directory structure (e.g., data/123/123456.json)
    const shardDir = path.join(DATA_DIR, product.id.substring(0, 3));
    if (!fs.existsSync(shardDir)) {
        fs.mkdirSync(shardDir, { recursive: true });
    }

    const filePath = path.join(shardDir, `${product.id}.json`);
    let history = [];

    if (fs.existsSync(filePath)) {
        try {
            history = JSON.parse(fs.readFileSync(filePath, 'utf8'));
        } catch (e) {
            console.error(`Error parsing existing data for ${product.id}:`, e.message);
        }
    }

    // Check if entry for today already exists
    const existingEntryIndex = history.findIndex(entry => entry.date === TODAY);
    const newEntry = {
        date: TODAY,
        price: product.price,
        is_sale: product.is_sale
    };

    if (existingEntryIndex !== -1) {
        history[existingEntryIndex] = newEntry;
    } else {
        history.push(newEntry);
    }

    // Keep history sorted by date
    history.sort((a, b) => a.date.localeCompare(b.date));

    fs.writeFileSync(filePath, JSON.stringify(history, null, 2));
}

async function main() {
    if (!fs.existsSync(DATA_DIR)) {
        fs.mkdirSync(DATA_DIR, { recursive: true });
    }

    const allProducts = new Map();

    for (const baseUrl of SEARCH_URLS) {
        console.log(`Starting crawl for: ${baseUrl}`);
        for (let page = 1; page <= MAX_PAGES; page++) {
            const url = `${baseUrl}&page=${page}`;
            const products = await scrapePage(url);
            if (products.length === 0) {
                console.log(`No more products found on page ${page}. Moving to next category.`);
                break;
            }

            console.log(`Found ${products.length} products on page ${page}.`);
            for (const product of products) {
                await saveProductData(product);
            }

            // Add a small delay to be polite
            await new Promise(resolve => setTimeout(resolve, DELAY_MS));
        }
    }

    console.log(`Total unique products found: ${allProducts.size}`);

    for (const product of allProducts.values()) {
        await saveProductData(product);
    }

    console.log('Scraping completed.');
}

main();
