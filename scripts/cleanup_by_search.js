const fs = require('fs');
const path = require('path');
const axios = require('axios');
const cheerio = require('cheerio');

const DATA_DIR = path.join(__dirname, '..', 'data');

const EXCLUDED_SEARCH_URLS = [
    'https://booth.pm/ja/browse/%E3%83%8F%E3%83%BC%E3%83%89%E3%82%A6%E3%82%A7%E3%82%A2%E3%83%BB%E3%82%AC%E3%82%B8%E3%82%A7%E3%83%83%E3%83%88?tags%5B%5D=VRChat'
];

async function getProductIdsFromSearch(url) {
    console.log(`Scraping search URL: ${url}`);
    try {
        const response = await axios.get(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36'
            }
        });
        const $ = cheerio.load(response.data);
        const ids = [];
        $('.item-card').each((i, el) => {
            const id = $(el).attr('data-product-id');
            if (id) ids.push(id);
        });
        return ids;
    } catch (error) {
        console.error(`Error scraping search ${url}:`, error.message);
        return [];
    }
}

async function runCleanup() {
    console.log('Starting Targeted Cleanup (Search-based)...');

    const allIdsToDelete = new Set();

    for (const baseUrl of EXCLUDED_SEARCH_URLS) {
        // Scrape first few pages (assuming most mistakes are in the first pages)
        // Or we can loop until no more IDs found if we want to be thorough.
        for (let page = 1; page <= 5; page++) {
            const url = `${baseUrl}&page=${page}`;
            const ids = await getProductIdsFromSearch(url);
            if (ids.length === 0) break;
            ids.forEach(id => allIdsToDelete.add(id));
            await new Promise(resolve => setTimeout(resolve, 1000));
        }
    }

    console.log(`Found ${allIdsToDelete.size} products in excluded categories.`);

    let deleteCount = 0;
    allIdsToDelete.forEach(id => {
        const shard = id.slice(0, 3);
        const filePath = path.join(DATA_DIR, shard, `${id}.json`);

        if (fs.existsSync(filePath)) {
            console.log(`[DELETE] ${id}: Hardware/Gadget found in data.`);
            fs.unlinkSync(filePath);
            deleteCount++;
        }
    });

    console.log(`Cleanup complete. Deleted ${deleteCount} files.`);
}

runCleanup();
