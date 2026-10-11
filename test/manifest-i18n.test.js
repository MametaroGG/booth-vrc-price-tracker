const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '..');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'extension/manifest.json'), 'utf8'));
const locales = ['en', 'ja', 'ko', 'zh_CN', 'zh_TW'];
test('Chrome manifest declares Japanese default and localized name/description', () => {
    assert.equal(manifest.default_locale, 'ja');
    assert.equal(manifest.name, '__MSG_extensionName__');
    assert.equal(manifest.description, '__MSG_extensionDescription__');
    assert.equal(manifest.version, '1.2.0');
    assert.equal(require('../package.json').version, manifest.version);
    assert.equal(require('../package-lock.json').version, manifest.version);
});
test('five supported Chrome locales resolve every manifest message within limits', () => {
    assert.deepEqual(fs.readdirSync(path.join(root, 'extension/_locales')).sort(), locales);
    const refs = [...JSON.stringify(manifest).matchAll(/__MSG_(\w+)__/g)].map(match => match[1]);
    for (const locale of locales) {
        const messages = JSON.parse(fs.readFileSync(path.join(root, 'extension/_locales', locale, 'messages.json'), 'utf8'));
        assert.deepEqual(Object.keys(messages).sort(), ['extensionDescription', 'extensionName']);
        for (const key of refs) {
            assert.match(key, /^[A-Za-z0-9_]+$/);
            assert.equal(typeof messages[key].message, 'string');
            assert.ok(messages[key].message.trim().length > 0);
            assert.doesNotMatch(messages[key].message, /__MSG_|[\r\n]/);
        }
        assert.ok(messages.extensionName.message.length <= 75, `${locale} name`);
        assert.ok(messages.extensionDescription.message.length <= 132, `${locale} description`);
    }
});
test('bundler includes the locale directory recursively and fails on missing inputs', () => {
    const script = fs.readFileSync(path.join(root, 'scripts/bundle-extension.ps1'), 'utf8');
    assert.match(script, /"_locales"/);
    assert.match(script, /Copy-Item[^\r\n]+-Recurse/);
    assert.match(script, /throw "Required extension file missing:/);
});
