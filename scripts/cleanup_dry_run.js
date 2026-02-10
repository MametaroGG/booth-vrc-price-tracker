const fs = require('fs');
const path = require('path');
const axios = require('axios');
const cheerio = require('cheerio');

const DATA_DIR = path.join(__dirname, '..', 'data');
const REPORT_FILE = path.join(__dirname, '..', 'cleanup_report.json');

const ALLOWED_CATEGORIES = [
    '3Dモデル', '3D Models',
    'ソフトウェア', 'Software'
];

async function getProductInfo(productId) {
    const url = `https://booth.pm/ja/items/${productId}`;
    try {
        const response = await axios.get(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            },
            timeout: 10000
        });
        const $ = cheerio.load(response.data);

        // Better Category Detection: Look for breadcrumbs
        // Booth usually has: <nav class="breadcrumb"> or similar
        const breadcrumbs = $('.l-breadcrumb a, .breadcrumb a').map((i, el) => $(el).text().trim()).get();

        // Also check meta tags or JSON-LD if available
        let category = '';
        if (breadcrumbs.length > 0) {
            category = breadcrumbs[breadcrumbs.length - 1]; // Last child is subcategory
        }

        // VRChat Tag Check
        const tags = $('.related-tags a').map((i, el) => $(el).text().trim().toLowerCase()).get();
        const hasVrcTag = tags.some(t => t === 'vrchat' || t === 'vrchat想定');

        const title = $('h2.item-name, h2').first().text().trim();
        const hasVrcTitle = title.toLowerCase().includes('vrchat') || title.toLowerCase().includes('vrc');

        return {
            productId,
            title,
            category,
            breadcrumbs,
            tags,
            isAllowedCategory: ALLOWED_CATEGORIES.includes(category),
            hasVrcTagOrTitle: hasVrcTag || hasVrcTitle,
            url
        };
    } catch (error) {
        return { productId, error: error.message };
    }
}

async function runDryRun() {
    console.log('Starting Dry Run (Analysis Only)...');
    const shardDirs = fs.readdirSync(DATA_DIR).filter(name => fs.statSync(path.join(DATA_DIR, name)).isDirectory());

    let report = [];
    let count = 0;

    for (const shard of shardDirs) {
        const shardPath = path.join(DATA_DIR, shard);
        const files = fs.readdirSync(shardPath).filter(f => f.endsWith('.json'));

        console.log(`Analyzing shard ${shard} (${files.length} files)...`);

        for (const file of files) {
            const productId = file.replace('.json', '');
            const info = await getProductInfo(productId);

            if (info.error) {
                console.log(`[SKIP] ${productId}: Error ${info.error}`);
            } else {
                const isTarget = info.isAllowedCategory && info.hasVrcTagOrTitle;
                if (!isTarget) {
                    console.log(`[NON-TARGET] ${productId}: Title: ${info.title}, Category: ${info.category}`);
                    report.push(info);
                } else {
                    console.log(`[TARGET] ${productId}: Keep.`);
                }
            }

            count++;
            if (count % 10 === 0) {
                fs.writeFileSync(REPORT_FILE, JSON.stringify(report, null, 2));
            }

            await new Promise(resolve => setTimeout(resolve, 1000)); // Be gentle
        }
    }

    fs.writeFileSync(REPORT_FILE, JSON.stringify(report, null, 2));
    console.log(`Review complete. Found ${report.length} potential non-target products.`);
    console.log(`Report saved to: cleanup_report.json`);
}

runDryRun();
