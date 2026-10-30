const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const priceSection = {hidden: false}, quantitySection = {hidden: false};
function input(id, value = '', checked = false) {
    const row = {hidden: false};
    return {id, value, checked, disabled: false, dataset: {}, listeners: {},
        addEventListener(type, listener) { this.listeners[type] = listener; },
        focus(options) { this.focused = true; this.focusOptions = options; },
        closest(selector) { return selector === 'fieldset' ? (id === 'id_quantity_label' ? quantitySection : priceSection) : row; },
    };
}
const fields = Object.fromEntries([
    input('id_name', 'Фото-отзыв'),
    input('id_price_label', 'Цена за единицу'), input('id_has_price', '', false),
    input('id_price_per_unit', '37.50'), input('id_fixed_price'), input('id_use_panel_area'),
    input('id_whole_quantity'), input('id_max_quantity', '100'), input('id_quantity_label', 'Количество'),
    input('id_unit', '1'), input('id_discount_percent', '3'),
].map(field => [field.id, field]));
fields.id_max_quantity.dataset.quantityStep = '0.01';
fields['calculator-service-editor-script'] = {dataset: {focusName: 'true'}};
const ordinary = input('type_standard', 'standard');
const discount = input('type_discount', 'order_discount', true);
const labels = {};
const document = {
    readyState: 'complete', getElementById: id => fields[id],
    querySelectorAll: () => [ordinary, discount],
    querySelector: selector => labels[selector] ||= {},
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/calculator/js/admin-services.js'), 'utf8'), {document});
assert.equal(fields.id_name.focused, true);
assert.equal(fields.id_name.focusOptions.preventScroll, true);
assert.equal(ordinary.focused, undefined);
assert.equal(discount.focused, undefined);
fields.id_price_label.value = '';
fields.id_price_label.listeners.input();
fields.id_name.value = 'Новый тариф';
fields.id_name.listeners.input();
assert.equal(fields.id_price_label.value, 'Новый тариф');
assert.equal(labels['label[for="id_price_per_unit"]'].textContent, 'Новый тариф:');
assert.equal(labels['label[for="id_is_visible"]'], undefined);
assert.equal(priceSection.hidden, true);
assert.equal(quantitySection.hidden, true);
assert.equal(fields.id_discount_percent.disabled, false);
for (const name of ['has_price', 'price_label', 'price_per_unit', 'fixed_price', 'unit', 'max_quantity', 'quantity_label']) {
    assert.equal(fields['id_' + name].disabled, true, name);
}
function selectDiscount(selected) {
    ordinary.checked = !selected;
    discount.checked = selected;
    (selected ? discount : ordinary).listeners.change();
}
selectDiscount(false);
assert.equal(priceSection.hidden, false);
assert.equal(fields.id_has_price.disabled, false);
assert.equal(fields.id_discount_percent.disabled, true);
assert.equal(fields.id_price_per_unit.disabled, true);
fields.id_has_price.checked = true;
fields.id_has_price.listeners.change();
assert.equal(quantitySection.hidden, false);
assert.equal(fields.id_price_per_unit.disabled, false);
assert.equal(fields.id_unit.disabled, false);
fields.id_fixed_price.checked = true;
fields.id_fixed_price.listeners.change();
assert.equal(quantitySection.hidden, true);
selectDiscount(true);
fields.id_discount_percent.value = '5';
selectDiscount(false);
assert.equal(fields.id_fixed_price.checked, true);
assert.equal(fields.id_price_per_unit.value, '37.50');
assert.equal(fields.id_discount_percent.value, '5');
assert.equal(quantitySection.hidden, true);
fields.id_fixed_price.checked = false;
fields.id_fixed_price.listeners.change();
fields.id_whole_quantity.checked = true;
fields.id_whole_quantity.listeners.change();
assert.equal(fields.id_max_quantity.step, '1');
assert.equal(fields.id_max_quantity.value, '100');
fields.id_use_panel_area.checked = true;
fields.id_use_panel_area.listeners.change();
assert.equal(fields.id_max_quantity.disabled, true);
console.log('Admin type switch preserves values and hides/disables inapplicable fields: OK');
