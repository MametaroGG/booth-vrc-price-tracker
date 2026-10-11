const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../extension/content.js'), 'utf8');
function fixture({ color = 'rgb(51, 51, 51)', background = 'rgb(255, 255, 255)', dark = false } = {}) {
    const listeners = new Map(), headListeners = new Map(), mediaListeners = new Map(), frames = new Map(), observations = [], writes = [];
    let observer, serial = 0;
    const node = (style, parentElement = null) => ({ computed: style, parentElement });
    const html = node({ backgroundColor: 'transparent' });
    const body = node({ backgroundColor: background }, html);
    const host = node({ color, backgroundColor: 'rgba(0, 0, 0, 0)', colorScheme: dark ? 'dark' : 'light' }, body);
    const values = {};
    const container = { parentElement: host, isConnected: true, style: {
        getPropertyValue: key => values[key] || '',
        setProperty: (key, value) => { values[key] = value; writes.push([key, value]); }
    }};
    const events = map => ({ addEventListener: (key, fn) => map.set(key, fn), removeEventListener: key => map.delete(key) });
    const context = { console: { log() {} }, document: { head: events(headListeners) }, window: {
        location: { pathname: '/items/123' }, getComputedStyle: n => n.computed,
        matchMedia: () => ({ matches: dark, ...events(mediaListeners) }), ...events(listeners),
        requestAnimationFrame: fn => { frames.set(++serial, fn); return serial; }, cancelAnimationFrame: id => frames.delete(id)
    }, MutationObserver: class {
        constructor(callback) { observer = this; this.callback = callback; this.disconnected = false; }
        observe(target, options) { observations.push({ target, options }); }
        disconnect() { this.disconnected = true; }
    }};
    vm.runInNewContext(source.replace('    main();', '    globalThis.theme = { parseThemeColor, themeContrast, getSwitchPalette, watchSwitchTheme };'), context);
    return { ...context.theme, host, body, html, container, listeners, headListeners, mediaListeners, frames, observations, writes, values,
        get observer() { return observer; }, flush() { const pending = [...frames.values()]; frames.clear(); pending.forEach(fn => fn()); } };
}
test('light, dark, tinted and low-contrast shop palettes retain readable symbols', () => {
    for (const options of [ {}, { color: '#eee', background: '#181818', dark: true },
        { color: 'rgb(50, 30, 90)', background: '#f7ecff' }, { color: '#888', background: '#888' },
        { color: 'rgba(255,255,255,.1)', background: '#ffffff' }, { color: 'color(display-p3 1 0 0)', background: '#262626', dark: true } ]) {
        const f = fixture(options), palette = f.getSwitchPalette(f.container);
        assert.ok(f.themeContrast(f.parseThemeColor(palette.track), f.parseThemeColor(palette.ink)) >= 4.5, JSON.stringify(options));
    }
    const light = fixture(), dark = fixture({ color: '#eee', background: '#181818', dark: true });
    assert.equal(light.getSwitchPalette(light.container).ink, 'rgb(51, 51, 51)');
    assert.equal(dark.getSwitchPalette(dark.container).ink, 'rgb(238, 238, 238)');
    assert.notEqual(light.getSwitchPalette(light.container).track, dark.getSwitchPalette(dark.container).track);
});
test('nested translucent surfaces composite over host ancestors', () => {
    const f = fixture(); f.host.computed.backgroundColor = 'rgba(0,0,0,0.5)';
    const track = f.parseThemeColor(f.getSwitchPalette(f.container).track);
    assert.ok(track[0] > 110 && track[0] < 130);
});
test('malformed or unsupported computed colors safely fall back', () => {
    const f = fixture();
    for (const value of ['transparent', '', 'red', 'rgb(NaN, 0, 1)', 'rgb(1,2)', 'url(evil)']) assert.equal(f.parseThemeColor(value), null);
    assert.deepEqual(Array.from(f.parseThemeColor('rgb(100% 0% 0% / 50%)')).map(Math.round), [255, 0, 0, 1]);
});
test('theme changes coalesce, own styles are not observed, no-op refreshes do not write', () => {
    const f = fixture(); const cleanup = f.watchSwitchTheme(f.container);
    assert.equal(f.writes.length, 2);
    assert.ok(!f.observations.some(o => o.target === f.container));
    assert.ok(f.observations.filter(o => [f.host, f.body, f.html].includes(o.target)).every(o => !o.options.subtree));
    f.observer.callback(); f.observer.callback(); f.listeners.get('resize')();
    assert.equal(f.frames.size, 1); f.flush(); assert.equal(f.writes.length, 2);
    f.host.computed.color = '#eee'; f.body.computed.backgroundColor = '#181818';
    f.mediaListeners.get('change')(); f.flush();
    assert.equal(f.values['--boopa-switch-ink'], 'rgb(238, 238, 238)');
    f.observer.callback(); assert.equal(f.frames.size, 1); cleanup();
    assert.equal(f.frames.size, 0); assert.equal(f.observer.disconnected, true);
    assert.equal(f.listeners.size + f.headListeners.size + f.mediaListeners.size, 0);
    f.observer.callback(); assert.equal(f.frames.size, 0);
});
test('detached tracker requests full cleanup rather than retaining theme observers', () => {
    const f = fixture(); let cleaned = false;
    const cleanup = f.watchSwitchTheme(f.container);
    f.container.boopaCleanup = () => { cleaned = true; cleanup(); };
    f.container.isConnected = false; f.observer.callback(); f.flush();
    assert.equal(cleaned, true); assert.equal(f.observer.disconnected, true);
});
test('fallback symbol contrast holds across every neutral surface luminance', () => {
    const f = fixture();
    for (let n = 0; n <= 255; n++) {
        f.host.computed.color = `rgb(${n}, ${n}, ${n})`;
        f.body.computed.backgroundColor = `rgb(${n}, ${n}, ${n})`;
        const p = f.getSwitchPalette(f.container);
        assert.ok(f.themeContrast(f.parseThemeColor(p.track), f.parseThemeColor(p.ink)) >= 4.5, `gray ${n}`);
    }
});
test('host color transition endpoints refresh, unrelated and switch transitions do not', () => {
    const f = fixture(); const cleanup = f.watchSwitchTheme(f.container);
    const end = f.listeners.get('transitionend'), cancel = f.listeners.get('transitioncancel');
    end({ target: f.container, propertyName: 'color' });
    end({ target: f.host, propertyName: 'width' });
    assert.equal(f.frames.size, 0);
    f.host.computed.color = '#eee'; f.body.computed.backgroundColor = '#181818';
    end({ target: f.body, propertyName: 'background-color' }); f.flush();
    assert.equal(f.values['--boopa-switch-ink'], 'rgb(238, 238, 238)');
    cancel({ target: f.host, propertyName: 'color' }); assert.equal(f.frames.size, 1);
    cleanup(); assert.equal(f.listeners.size, 0); assert.equal(f.frames.size, 0);
});
