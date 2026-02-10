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
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36'
            },
            timeout: 10000
        });
        const $ = cheerio.load(response.data);

        let category = '';
        let tags = [];
        let title = '';

        // 1. Try JSON-LD (Most reliable)
        const jsonLd = $('script[type="application/ld+json"]');
        jsonLd.each((i, el) => {
            try {
                const data = JSON.parse($(el).html());
                if (data['@type'] === 'Product') {
                    title = data.name || title;
                    if (data.category) category = data.category;
                }
            } catch (e) { }
        });

        // 2. Breadcrumb Fallback
        if (!category) {
            const breadcrumbLinks = $('.l-breadcrumb a, .breadcrumb a, .nav-breadcrumb a, a[href*="/browse/"]').filter((i, el) => {
                const parent = $(el).closest('.recommend, .item-recommend, .other-items, .shop-items, .related-tags, .sidebar, .l-side, footer');
                return parent.length === 0;
            });
            const breadcrumbs = breadcrumbLinks.map((i, el) => $(el).text().trim()).get();
            if (breadcrumbs.length > 0) {
                category = breadcrumbs[breadcrumbs.length - 1];
            }
        }

        // 3. Title Check
        if (!title) {
            title = $('.item-name, h2').first().text().trim();
        }

        // 4. Tags
        tags = $('.related-tags a, .item-tags a').map((i, el) => $(el).text().trim().toLowerCase()).get();
        if (tags.length === 0) {
            // Check meta tags
            const metaKeywords = $('meta[name="keywords"]').attr('content');
            if (metaKeywords) tags = metaKeywords.split(',').map(s => s.trim().toLowerCase());
        }

        const hasVrcTag = tags.some(t => t.includes('vrchat') || t.includes('vrchat想定'));
        const hasVrcTitle = title.toLowerCase().includes('vrchat') || title.toLowerCase().includes('vrc');

        return {
            productId,
            title,
            category,
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

    // Load existing report to resume
    let report = [];
    if (fs.existsSync(REPORT_FILE)) {
        try {
            report = JSON.parse(fs.readFileSync(REPORT_FILE, 'utf8'));
            console.log(`Loaded existing report with ${report.length} entries. Sorting and filtering...`);
            // We'll resume from the last shard/file not in the report.
        } catch (e) {
            console.log('Error loading report, starting fresh.');
        }
    }

    const processedIds = new Set(report.map(r => r.productId));
    const shardDirs = fs.readdirSync(DATA_DIR).filter(name => fs.statSync(path.join(DATA_DIR, name)).isDirectory()).sort();

    let count = 0;

    for (const shard of shardDirs) {
        const shardPath = path.join(DATA_DIR, shard);
        const files = fs.readdirSync(shardPath).filter(f => f.endsWith('.json')).sort();

        for (const file of files) {
            const productId = file.replace('.json', '');
            if (processedIds.has(productId)) continue;

            const info = await getProductInfo(productId);

            if (info.error) {
                console.log(`[SKIP] ${productId}: Error ${info.error}`);
            } else {
                const isTarget = info.isAllowedCategory && info.hasVrcTagOrTitle;
                if (!isTarget) {
                    console.log(`[NON-TARGET] ${productId}: Title: ${info.title}, Category: ${info.category}`);
                    report.push(info);
                } else {
                    console.log(`[TARGET] ${productId}: Keep. (Cat: ${info.category})`);
                    // We mark it to keep track that we've processed it
                    info.KEEP = true;
                    report.push(info);
                }
            }

            count++;
            if (count % 10 === 0) {
                fs.writeFileSync(REPORT_FILE, JSON.stringify(report, null, 2));
                console.log(`Progress: Investigated ${report.length} items total.`);
            }

            await new Promise(resolve => setTimeout(resolve, 1200));
        }
    }

    fs.writeFileSync(REPORT_FILE, JSON.stringify(report, null, 2));
    const nonTargets = report.filter(r => !r.KEEP && !r.error);
    console.log(`Review complete. Found ${nonTargets.length} potential non-target products.`);
    console.log(`Report saved to: cleanup_report.json`);
}

runDryRun();
