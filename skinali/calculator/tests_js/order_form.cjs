const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function element(values = {}) {
    return {
        value: '', disabled: false, hidden: false, dataset: {}, listeners: {},
        addEventListener(type, listener) { this.listeners[type] = listener; },
        setAttribute(name, value) { this[name] = value; },
        removeAttribute(name) { delete this[name]; },
        focus() { this.focused = true; },
        dispatchEvent() {},
        ...values,
    };
}

async function main() {
    const configuration = {
        max_panels: 10, max_panel_dimension_mm: 6000, area_decimal_places: 2,
        quantity_step: '0.01', quantity_decimal_places: 2,
        area_discount_percent: '0', area_discount_threshold: '2', marketing_discount_percent: '0',
        glass_type: {visible: true, options: [{id: 1, name: 'Стекло', price: '100'}]},
        decoration_type: {visible: true, options: [{id: 1, name: 'Декор', price: '20'}]},
        services: [], stairs: null,
    };
    const panels = element({children: [], append(row) { this.children.push(row); }});
    function panel() {
        const parts = {};
        const row = element({
            querySelector: selector => parts[selector],
            querySelectorAll: () => [parts['[data-width]'], parts['[data-height]']],
        });
        for (const dimension of ['width', 'height']) {
            const input = element({
                max: '6000', validity: {badInput: false}, closest: () => row,
                checkValidity() { return /^\d+$/.test(this.value) && Number(this.value) >= 1 && Number(this.value) <= 6000; },
            });
            parts[`[data-${dimension}]`] = input;
            parts[`[data-${dimension}-label]`] = element();
            parts[`[data-${dimension}-caption]`] = element();
        }
        parts.input = parts['[data-width]'];
        parts['[data-panel-title]'] = element();
        parts['[data-remove-panel]'] = element();
        return row;
    }
    const toggle = element();
    const services = element();
    const share = element({
        dataset: {shareUrl: '', shareEndpoint: '/price/share/'},
        querySelector: selector => selector === '[data-share-toggle]' ? toggle : services,
    });
    const order = element();
    const orderUrl = element();
    const name = element();
    const dialog = element({
        open: false, showModal() { this.open = true; },
        querySelector: selector => selector === '[data-calculation-url]' ? orderUrl : name,
    });
    const inputs = () => panels.children.flatMap(row => row.querySelectorAll('input'));
    const form = element({
        elements: {}, querySelector: () => share,
        querySelectorAll: selector => ['input, select', 'input[type="number"][max]:not(:disabled)'].includes(selector) ? inputs() : [],
    });
    const amount = element({
        clientWidth: 500, style: {removeProperty() {}, setProperty() {}},
        querySelector: () => ({getBoundingClientRect: () => ({width: 100})}),
    });
    const nodes = {
        'price-calculator': form, 'price-calculator-config': {textContent: JSON.stringify(configuration)},
        'price-panels': panels, 'price-panel-template': {content: {firstElementChild: {cloneNode: panel}}},
        'price-add-panel': element(), 'price-order': order, 'calculator-order-dialog': dialog,
        'price-amount': amount, 'price-panel-limit': element(),
        'price-glass_type': element({value: '1'}), 'price-decoration_type': element({value: '1'}),
    };
    for (const key of ['total', 'old-total', 'comparison', 'area', 'status']) nodes[`price-${key}`] = element();
    const toasts = [];
    const calls = [];
    let handler = async () => ({ok: true, json: async () => ({url: 'https://example.org/price/?calculation=first'})});
    const context = vm.createContext({
        Intl, Event: class {}, CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
        document: {
            getElementById: id => nodes[id] ?? null,
            querySelector: () => ({content: 'csrf-token'}),
            dispatchEvent: event => toasts.push(event.detail),
        },
        window: {addEventListener() {}},
        fetch: async (url, options) => { calls.push({url, options}); return handler(); },
    });
    const directory = path.join(__dirname, '..', 'static', 'calculator', 'js');
    vm.runInContext(fs.readFileSync(path.join(directory, 'price-engine.js'), 'utf8'), context);
    vm.runInContext(fs.readFileSync(path.join(directory, 'price.js'), 'utf8'), context);
    assert.equal(order.disabled, true);
    await order.listeners.click();
    assert.equal(calls.length, 0);
    const first = panels.children[0];
    first.querySelector('[data-width]').value = '1000';
    first.querySelector('[data-height]').value = '600';
    form.listeners.input();
    assert.equal(order.disabled, false);
    await order.listeners.click();
    assert.equal(dialog.open, true);
    assert.equal(name.focused, true);
    assert.equal(orderUrl.value, 'https://example.org/price/?calculation=first');
    assert.equal(calls.length, 1);
    const posted = JSON.parse(calls[0].options.body);
    assert.deepEqual(posted.panels, [{width: '1000', height: '600'}]);
    assert.equal(posted.total, undefined);
    assert.equal(posted.price, undefined);
    assert.equal(calls[0].options.headers['X-CSRFToken'], 'csrf-token');
    dialog.open = false;
    orderUrl.value = '';
    await order.listeners.click();
    assert.equal(calls.length, 1);
    assert.equal(dialog.open, true);
    assert.equal(orderUrl.value, 'https://example.org/price/?calculation=first');
    dialog.open = false;
    first.querySelector('[data-width]').value = '2000';
    form.listeners.input();
    assert.equal(orderUrl.value, '');
    let complete;
    handler = () => new Promise(resolve => { complete = resolve; });
    const pending = order.listeners.click();
    assert.equal(order.disabled, true);
    await order.listeners.click();
    assert.equal(calls.length, 2);
    first.querySelector('[data-height]').value = '900';
    form.listeners.input();
    complete({ok: true, json: async () => ({url: 'https://example.org/price/?calculation=stale'})});
    await pending;
    assert.equal(dialog.open, false);
    assert.equal(orderUrl.value, '');
    assert.equal(toasts.at(-1).kind, 'error');
    assert.equal(order.disabled, false);
    handler = async () => { throw new Error('offline'); };
    await order.listeners.click();
    assert.equal(dialog.open, false);
    assert.equal(orderUrl.value, '');
    assert.equal(order.disabled, false);
    handler = async () => ({ok: false, json: async () => ({message: 'Unavailable'})});
    await order.listeners.click();
    assert.equal(dialog.open, false);
    assert.equal(toasts.at(-1).message, 'Unavailable');
    handler = async () => ({ok: true, json: async () => ({url: 'https://example.org/price/?calculation=current'})});
    await order.listeners.click();
    assert.equal(dialog.open, true);
    assert.equal(orderUrl.value, 'https://example.org/price/?calculation=current');
    console.log('Calculator order: valid input, current URL, cache, duplicate clicks, stale response and failures: OK');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
