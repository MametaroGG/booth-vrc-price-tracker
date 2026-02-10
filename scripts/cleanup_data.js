const fs = require('fs');
const path = require('path');
const axios = require('axios');
const cheerio = require('cheerio');

const DATA_DIR = path.join(__dirname, '..', 'data');

const ALLOWED_CATEGORIES = [
    '3Dモデル', '3D Models',
    'ソフトウェア', 'Software'
];

async function isTargetCategory(productId) {
    const url = `https://booth.pm/ja/items/${productId}`;
    try {
        const response = await axios.get(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            },
            timeout: 8000
        });
        const $ = cheerio.load(response.data);

        // 1. Category Check
        const allBrowseLinks = Array.from($('a[href*="/browse/"]'));
        const validCategoryLinks = allBrowseLinks.filter(a => {
            const $a = $(a);
            const parent = $a.closest('.recommend, .item-recommend, .other-items, .shop-items, .related-tags, .sidebar, .l-side, footer');
            return parent.length === 0;
        });

        const categoryText = validCategoryLinks.map(a => $(a).text().trim());
        const isAllowedCategory = categoryText.some(text => ALLOWED_CATEGORIES.includes(text));

        if (!isAllowedCategory) {
            console.log(`[REJECT] ${productId}: Category "${categoryText.join(', ')}" is not in whitelist.`);
            return false;
        }

        // 2. VRChat Tag/Title Check (Match extension logic)
        const tagLinks = Array.from($('a[href*="tags"]'));
        const hasVrcTag = tagLinks.some(a => {
            const text = $(a).text().trim().toLowerCase();
            return text === 'vrchat' || text === 'vrchat想定';
        });

        const title = $('h2').first().text().toLowerCase() || '';
        const hasVrcTitle = title.includes('vrchat') || title.includes('vrc');

        if (!(hasVrcTag || hasVrcTitle)) {
            console.log(`[REJECT] ${productId}: Category OK (${categoryText.join(', ')}), but no VRChat tag/title.`);
            return false;
        }

        return true;
    } catch (error) {
        console.error(`Error checking product ${productId}:`, error.message);
        if (error.response && error.response.status === 404) return false;
        return true; // Skip if error to be safe
    }
}

async function cleanup() {
    console.log('Starting data cleanup...');
    const shardDirs = fs.readdirSync(DATA_DIR).filter(name => fs.statSync(path.join(DATA_DIR, name)).isDirectory());

    for (const shard of shardDirs) {
        const shardPath = path.join(DATA_DIR, shard);
        const files = fs.readdirSync(shardPath).filter(f => f.endsWith('.json'));

        console.log(`Checking shard ${shard} (${files.length} files)...`);

        for (const file of files) {
            const productId = file.replace('.json', '');
            const target = await isTargetCategory(productId);

            if (!target) {
                console.log(`[DELETE] ${productId} is not in target categories.`);
                fs.unlinkSync(path.join(shardPath, file));
            } else {
                console.log(`[KEEP] ${productId} is in target categories.`);
            }

            // Avoid rate limiting
            await new Promise(resolve => setTimeout(resolve, 500));
        }
    }
    console.log('Cleanup complete.');
}

cleanup();
