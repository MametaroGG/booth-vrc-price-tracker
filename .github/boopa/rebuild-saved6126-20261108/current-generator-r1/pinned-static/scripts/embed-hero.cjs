// Run after generating index.html + lists_full.json, before publishing both.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const file = path.join(root, 'index.html');
const html = fs.readFileSync(file, 'utf8');
const selector = html.match(/\/\/ HERO_SELECTOR_START[^\n]*\n([\s\S]*?)\/\/ HERO_SELECTOR_END/);
if (!selector) throw new Error('Missing shared hero selector');
const select = vm.runInNewContext(selector[1] + '\nhomeCandidatePools');
const entries = select(JSON.parse(fs.readFileSync(path.join(root, 'lists_full.json'), 'utf8')));
if (entries.newest.length + entries.on_sale.length < 3) throw new Error('Catalog has too few valid hero items');
// Escape script delimiters and line separators when embedding catalog text.
const json = JSON.stringify(entries).replace(/</g, '\\u003c').replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');
const marker = /^const HERO_BOOTSTRAP = .*; \/\/ HERO_BOOTSTRAP_DATA$/m;
if (!marker.test(html)) throw new Error('Missing hero bootstrap marker');
const output = html.replace(marker, () => `const HERO_BOOTSTRAP = ${json}; // HERO_BOOTSTRAP_DATA`);
if (process.argv.includes('--check')) {
  if (html !== output) throw new Error('Hero bootstrap is stale; run node scripts/embed-hero.cjs');
} else fs.writeFileSync(file, output);
console.log(`Hero bootstrap: ${entries.newest.length + entries.on_sale.length} candidates (${Buffer.byteLength(json)} bytes)`);
