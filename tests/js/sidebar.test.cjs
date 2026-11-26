const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');
const source = readFileSync(join(__dirname, '../../static/joatham_dashboard/js/sidebar.js'), 'utf8');

function setup(isMobile) {
    const listeners = {}, attributes = {};
    let focused = false;
    const button = {hidden: true, setAttribute: (key, value) => attributes[key] = value,
        addEventListener: (event, callback) => listeners[event] = callback, focus: () => focused = true};
    const panel = {hidden: false};
    const media = {matches: isMobile, addEventListener: (event, callback) => listeners.resize = callback};
    const sidebar = {querySelector: selector => selector.includes('toggle') ? button : panel,
        addEventListener: (event, callback) => listeners[event] = callback};
    runInNewContext(source, {document: {querySelector: () => sidebar}, window: {matchMedia: () => media}});
    return {button, panel, media, attributes, listeners, focused: () => focused};
}

test('mobile navigation opens, closes and returns keyboard focus with Escape', () => {
    const ui = setup(true);
    assert.equal(ui.panel.hidden, true);
    assert.equal(ui.button.hidden, false);
    ui.listeners.click();
    assert.equal(ui.panel.hidden, false);
    assert.equal(ui.attributes['aria-expanded'], 'true');
    ui.listeners.keydown({key: 'Escape'});
    assert.equal(ui.panel.hidden, true);
    assert.equal(ui.attributes['aria-expanded'], 'false');
    assert.equal(ui.focused(), true);
});

test('desktop navigation remains visible and resizing restores the appropriate state', () => {
    const ui = setup(false);
    assert.equal(ui.panel.hidden, false);
    assert.equal(ui.button.hidden, true);
    ui.listeners.keydown({key: 'Escape'});
    assert.equal(ui.panel.hidden, false);
    ui.media.matches = true;
    ui.listeners.resize();
    assert.equal(ui.panel.hidden, true);
    ui.media.matches = false;
    ui.listeners.resize();
    assert.equal(ui.panel.hidden, false);
    assert.equal(ui.button.hidden, true);
});

test('loading on a page without the shared sidebar is harmless', () => {
    assert.doesNotThrow(() => runInNewContext(source, {document: {querySelector: () => null}}));
});
