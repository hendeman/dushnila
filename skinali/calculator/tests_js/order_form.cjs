const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function element(values = {}) {
    return {
        value: '', disabled: false, hidden: false, dataset: {}, listeners: {},
        addEventListener(type, listener) { this.listeners[type] = listener; },
        setAttribute(name, value) { this[name] = value; },
        getAttribute(name) { return this[name] ?? null; },
        toggleAttribute(name, force) { if (force) this[name] = true; else delete this[name]; },
        removeAttribute(name) { delete this[name]; },
        focus() { this.focused = true; },
        dispatchEvent(event) { this.listeners[event.type]?.(event); },
        ...values,
    };
}

async function main() {
    const configuration = {
        max_panels: 10, max_panel_dimension_mm: 6000, area_decimal_places: 2,
        quantity_step: '0.01', quantity_decimal_places: 2,
        material_discount: {mode: 'none', minimum_area: null, rules: []}, marketing_discount_percent: '0',
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
    const orderUrl = element({dataset: {fieldName: 'calculation_url'}});
    const name = element({dataset: {fieldName: 'name'}});
    const phone = element({dataset: {fieldName: 'phone'}});
    const submit = element();
    const retry = element();
    const title = element();
    const detail = element();
    const icons = ['loading', 'ready', 'error'].map(orderStateIcon => element({dataset: {orderStateIcon}}));
    const status = element({
        querySelector: selector => selector === '[data-order-status-title]' ? title : detail,
        querySelectorAll: () => icons,
    });
    const orderForm = element({
        action: '/contact/submit/', dataset: {submitBlocked: 'true'},
        querySelector: selector => selector === '[type="submit"]' ? submit : null,
        querySelectorAll: selector => selector === '[data-field-name]' ? [name, phone, orderUrl] : [],
        reset() { name.value = ''; phone.value = ''; orderUrl.value = ''; },
    });
    const dialog = element({
        open: false, showModal() { this.open = true; },
        close() { this.open = false; this.listeners.close?.(); },
        querySelector: selector => ({
            '[data-calculation-url]': orderUrl, '[data-field-name="name"]': name,
            '[data-contact-form]': orderForm, '[data-order-status]': status, '[data-order-retry]': retry,
        })[selector] ?? null,
    });
    orderForm.closest = () => dialog;
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
    const timers = new Map();
    let timerId = 0;
    const setTimer = (callback, delay) => { timers.set(++timerId, {callback, delay}); return timerId; };
    const clearTimer = id => timers.delete(id);
    let handler = async () => ({ok: true, json: async () => ({url: 'https://example.org/price/?calculation=first'})});
    let submitHandler = async () => ({ok: true, json: async () => ({ok: true, message: 'Saved'})});
    const shareCalls = () => calls.filter(call => call.url === '/price/share/');
    const orderCalls = () => calls.filter(call => call.url === orderForm.action);
    const flush = () => new Promise(resolve => setImmediate(resolve));
    const expire = () => {
        const pending = Array.from(timers.entries()).find(([, timer]) => timer.delay === 10000);
        assert.ok(pending, 'A ten-second preparation deadline must be scheduled');
        timers.delete(pending[0]);
        pending[1].callback();
    };
    const context = vm.createContext({
        Intl, AbortController, Event: class { constructor(type) { this.type = type; } },
        CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
        FormData: class { constructor() { this.url = orderUrl.value; this.name = name.value; this.phone = phone.value; } },
        document: {
            getElementById: id => nodes[id] ?? null,
            querySelector: selector => selector === 'meta[name="csrf-token"]' ? {content: 'csrf-token'} : null,
            querySelectorAll: selector => selector === '[data-contact-form]' ? [orderForm] : selector === '.contact-dialog' ? [dialog] : [],
            addEventListener() {},
            dispatchEvent: event => toasts.push(event.detail),
        },
        window: {addEventListener() {}, setTimeout: setTimer, clearTimeout: clearTimer},
        setTimeout: setTimer, clearTimeout: clearTimer,
        fetch: async (url, options) => {
            calls.push({url, options});
            return url === orderForm.action ? submitHandler() : handler();
        },
    });
    const directory = path.join(__dirname, '..', 'static', 'calculator', 'js');
    vm.runInContext(fs.readFileSync(path.join(directory, 'price-engine.js'), 'utf8'), context);
    vm.runInContext(fs.readFileSync(path.join(directory, 'price.js'), 'utf8'), context);
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'pict', 'static', 'skinali', 'js', 'contact-forms.js'), 'utf8'), context);
    assert.equal(order.disabled, true);
    await order.listeners.click();
    assert.equal(calls.length, 0);
    const first = panels.children[0];
    first.querySelector('[data-width]').value = '1000';
    first.querySelector('[data-height]').value = '600';
    form.listeners.input();
    assert.equal(order.disabled, false);
    let complete;
    handler = () => new Promise(resolve => { complete = resolve; });
    const firstAttempt = order.listeners.click();
    assert.equal(dialog.open, true);
    assert.equal(name.focused, true);
    assert.equal(status.dataset.state, 'loading');
    assert.equal(icons.find(icon => icon.dataset.orderStateIcon === 'ready').hidden, true);
    assert.equal(submit.disabled, true);
    assert.equal(name.disabled, false);
    assert.equal(phone.disabled, false);
    name.value = 'Anna'; phone.value = '+375 29 1234567';
    await orderForm.listeners.submit({preventDefault() {}});
    assert.equal(orderCalls().length, 0);
    await order.listeners.click();
    assert.equal(shareCalls().length, 1);
    complete({ok: true, json: async () => ({url: 'https://example.org/price/?calculation=first'})});
    await firstAttempt;
    assert.equal(orderUrl.value, 'https://example.org/price/?calculation=first');
    assert.equal(status.dataset.state, 'ready');
    assert.equal(icons.find(icon => icon.dataset.orderStateIcon === 'ready').getAttribute('hidden'), null);
    assert.equal(icons.find(icon => icon.dataset.orderStateIcon === 'loading').hidden, true);
    assert.equal(submit.disabled, false);
    assert.equal(name.value, 'Anna');
    assert.equal(orderForm.dataset.submitBlocked, 'false');
    assert.equal(timers.size, 0);
    assert.equal(calls.length, 1);
    const posted = JSON.parse(calls[0].options.body);
    assert.deepEqual(posted.panels, [{width: '1000', height: '600'}]);
    assert.equal(posted.total, undefined);
    assert.equal(posted.price, undefined);
    assert.equal(calls[0].options.headers['X-CSRFToken'], 'csrf-token');
    dialog.close();
    assert.equal(submit.disabled, true);
    await order.listeners.click();
    assert.equal(calls.length, 1);
    assert.equal(dialog.open, true);
    assert.equal(orderUrl.value, 'https://example.org/price/?calculation=first');
    dialog.close();
    first.querySelector('[data-width]').value = '2000';
    form.listeners.input();
    assert.equal(orderUrl.value, '');
    handler = () => new Promise(resolve => { complete = resolve; });
    const pending = order.listeners.click();
    assert.equal(status.dataset.state, 'loading');
    await order.listeners.click();
    assert.equal(calls.length, 2);
    first.querySelector('[data-height]').value = '900';
    form.listeners.input();
    complete({ok: true, json: async () => ({url: 'https://example.org/price/?calculation=stale'})});
    await pending;
    assert.equal(dialog.open, true);
    assert.equal(status.dataset.state, 'error');
    assert.equal(submit.disabled, true);
    assert.equal(calls.at(-1).options.signal.aborted, true);
    assert.equal(orderUrl.value, '');
    assert.equal(order.disabled, false);
    handler = async () => { throw new Error('offline'); };
    await retry.listeners.click();
    assert.equal(dialog.open, true);
    assert.equal(status.dataset.state, 'error');
    assert.equal(retry.hidden, false);
    assert.equal(submit.disabled, true);
    assert.equal(name.value, 'Anna');
    assert.equal(orderUrl.value, '');
    assert.equal(order.disabled, false);
    handler = async () => ({ok: false, json: async () => ({message: 'Unavailable'})});
    await retry.listeners.click();
    assert.equal(status.dataset.state, 'error');
    assert.equal(detail.textContent, 'Unavailable');
    handler = () => new Promise(resolve => { complete = resolve; });
    const timedOut = retry.listeners.click();
    const expiredCall = shareCalls().at(-1);
    expire();
    await timedOut;
    assert.equal(expiredCall.options.signal.aborted, true);
    assert.equal(status.dataset.state, 'error');
    assert.equal(detail.textContent, 'Ответ не получен вовремя. Попробуйте ещё раз.');
    assert.equal(orderUrl.value, '');
    assert.equal(name.value, 'Anna');
    assert.equal(phone.value, '+375 29 1234567');
    const countAfterTimeout = shareCalls().length;
    await flush();
    assert.equal(shareCalls().length, countAfterTimeout);
    handler = async () => ({ok: true, json: async () => ({url: 'https://example.org/price/?calculation=current'})});
    await retry.listeners.click();
    assert.equal(dialog.open, true);
    assert.equal(orderUrl.value, 'https://example.org/price/?calculation=current');
    complete({ok: true, json: async () => ({url: 'https://example.org/price/?calculation=late'})});
    await flush();
    assert.equal(orderUrl.value, 'https://example.org/price/?calculation=current');
    assert.equal(share.dataset.shareUrl, orderUrl.value);
    assert.equal(status.dataset.state, 'ready');

    dialog.close(); first.querySelector('[data-width]').value = '1500'; form.listeners.input();
    let finishJson;
    handler = async () => ({ok: true, json: () => new Promise(resolve => { finishJson = resolve; })});
    const slowBody = order.listeners.click();
    await flush();
    expire(); await slowBody;
    assert.equal(status.dataset.state, 'error');
    finishJson({url: 'https://example.org/price/?calculation=late-body'});
    await flush();
    assert.equal(share.dataset.shareUrl, '');
    assert.equal(orderUrl.value, '');

    handler = () => new Promise(resolve => { complete = resolve; });
    const closedAttempt = retry.listeners.click();
    dialog.close();
    complete({ok: true, json: async () => ({url: 'https://example.org/price/?calculation=closed'})});
    await closedAttempt;
    assert.equal(dialog.open, false);
    assert.equal(submit.disabled, true);
    assert.equal(orderUrl.value, '');
    assert.equal(name.value, 'Anna');
    await order.listeners.click();
    assert.equal(orderUrl.value, 'https://example.org/price/?calculation=closed');
    assert.equal(status.dataset.state, 'ready');
    dialog.close(); first.querySelector('[data-width]').value = '1800'; form.listeners.input();
    handler = () => new Promise(resolve => { complete = resolve; });
    const countBeforeJoin = shareCalls().length;
    const shareEvent = {detail: {promises: []}};
    share.listeners['share:prepare'](shareEvent);
    const shared = Promise.all(shareEvent.detail.promises);
    const joinedOrder = order.listeners.click();
    assert.equal(shareCalls().length, countBeforeJoin + 1);
    assert.equal(dialog.open, true);
    assert.equal(status.dataset.state, 'loading');
    complete({ok: true, json: async () => ({url: 'https://example.org/price/?calculation=joined'})});
    await Promise.all([shared, joinedOrder]);
    assert.equal(orderUrl.value, 'https://example.org/price/?calculation=joined');
    assert.equal(status.dataset.state, 'ready');
    let finishSubmission;
    submitHandler = () => new Promise(resolve => { finishSubmission = resolve; });
    const submission = orderForm.listeners.submit({preventDefault() {}});
    assert.equal(submit.disabled, true);
    await orderForm.listeners.submit({preventDefault() {}});
    assert.equal(orderCalls().length, 1);
    finishSubmission({ok: true, json: async () => ({ok: true, message: 'Saved'})});
    await submission;
    assert.equal(orderCalls()[0].options.body.url, 'https://example.org/price/?calculation=joined');
    assert.equal(orderCalls()[0].options.body.name, 'Anna');
    assert.equal(dialog.open, false);
    assert.equal(submit.disabled, true);
    assert.equal(name.value, '');
    assert.equal(timers.size, 0);
    assert.equal(toasts.length, 0);
    console.log('Order opens immediately; status, ten-second deadline, retry, slow JSON, late response, contacts, close and guarded submit: OK');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
