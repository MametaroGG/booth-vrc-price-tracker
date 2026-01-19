const fs = require('fs');
const path = require('path');

const DATA_DIR = path.join(__dirname, '..', 'data');

function migrateFile(filePath) {
    try {
        const content = fs.readFileSync(filePath, 'utf8');
        const data = JSON.parse(content);
        let changed = false;

        if (data.variations) {
            Object.keys(data.variations).forEach(vName => {
                const history = data.variations[vName];
                for (let i = 1; i < history.length; i++) {
                    const current = history[i];
                    const previous = history[i - 1];

                    // Heuristic: If price dropped, mark as sale
                    if (!current.is_sale && current.price < previous.price) {
                        current.is_sale = true;
                        changed = true;
                    }
                }
            });
        }

        if (changed) {
            fs.writeFileSync(filePath, JSON.stringify(data, null, 2));
            return true;
        }
    } catch (e) {
        console.error(`Error migrating ${filePath}:`, e.message);
    }
    return false;
}

function walkDir(dir, callback) {
    fs.readdirSync(dir).forEach(f => {
        let dirPath = path.join(dir, f);
        let isDirectory = fs.statSync(dirPath).isDirectory();
        isDirectory ? walkDir(dirPath, callback) : callback(path.join(dir, f));
    });
}

function main() {
    console.log('Starting migration...');
    let totalFiles = 0;
    let updatedFiles = 0;

    walkDir(DATA_DIR, (filePath) => {
        if (filePath.endsWith('.json') && !filePath.endsWith('crawl_state.json')) {
            totalFiles++;
            if (migrateFile(filePath)) {
                updatedFiles++;
                if (updatedFiles % 100 === 0) {
                    console.log(`Progress: Updated ${updatedFiles} files...`);
                }
            }
        }
    });

    console.log(`Migration completed.`);
    console.log(`Total JSON files scanned: ${totalFiles}`);
    console.log(`Files updated with sale flag: ${updatedFiles}`);
}

main();
