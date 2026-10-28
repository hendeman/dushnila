// Кодовая проверка настоящих обработчиков порядка в jsdom, без запуска браузера.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require(process.argv[2] || 'jsdom');
const root = path.resolve(__dirname, '../..');
const common = fs.readFileSync(path.join(root, 'pict/static/skinali/js/admin-order.js'), 'utf8');
const adapter = fs.readFileSync(path.join(root, 'sitecontent/static/sitecontent/js/admin-price-tables.js'), 'utf8');
const djangoStatic = path.join(root, '../venv/Lib/site-packages/django/contrib/admin/static/admin/js');

function setup(html) {
    const dom = new JSDOM(html, {url: 'http://localhost/admin/sitecontent/pricetable/', runScripts: 'outside-only'});
    Object.defineProperty(dom.window.document, 'readyState', {value: 'complete'});
    dom.window.eval(common);
    dom.window.eval(adapter);
    return dom;
}

function row(index, position, empty = false) {
    return `<tr class="form-row${empty ? ' empty-form' : ''}" id="rows-${index}"><td>
        <input name="rows-${index}-id" value="${empty ? '' : index + 1}">
        <button type="button" data-price-row-order></button></td>
        <td><textarea name="rows-${index}-description">${empty ? '' : 'Услуга ' + index}</textarea></td>
        <td><textarea name="rows-${index}-price">${empty ? '' : 'Бесплатно'}</textarea></td>
        <td><input name="rows-${index}-position" value="${position}"></td></tr>`;
}

function key(window, element, name) {
    element.dispatchEvent(new window.KeyboardEvent('keydown', {key: name, bubbles: true, cancelable: true}));
}

function drag(window, handle, target) {
    const event = new window.Event('dragstart', {bubbles: true});
    event.dataTransfer = {setData() {}};
    handle.dispatchEvent(event);
    const over = new window.Event('dragover', {bubbles: true, cancelable: true});
    over.clientY = 1;
    target.dispatchEvent(over);
    handle.dispatchEvent(new window.Event('dragend', {bubbles: true}));
}

async function checkInline() {
    const dom = setup(`<form><div id="rows-group"><table><tbody>${row(0, 2)}${row(1, 1)}${row('empty', 0, true)}</tbody></table></div></form>`);
    const {window} = dom;
    const {document} = window;
    document.dispatchEvent(new window.Event('DOMContentLoaded'));
    const container = document.querySelector('tbody');
    const ids = () => [...container.querySelectorAll('.form-row:not(.empty-form)')].map((element) => element.id);
    assert.deepEqual(ids(), ['rows-1', 'rows-0'], 'Порядок восстанавливается после ошибки валидации');
    key(window, document.querySelector('#rows-0 button'), 'ArrowUp');
    assert.deepEqual(ids(), ['rows-0', 'rows-1']);
    assert.equal(document.querySelector('[name="rows-0-position"]').value, '1');
    assert.match(document.querySelector('[role="status"]').textContent, /Сохранить/);

    const added = document.createElement('tbody');
    added.innerHTML = row(2, 0);
    const addedRow = added.firstElementChild;
    container.insertBefore(addedRow, document.getElementById('rows-empty'));
    addedRow.dispatchEvent(new window.CustomEvent('formset:added', {bubbles: true, detail: {formsetName: 'rows'}}));
    key(window, addedRow.querySelector('button'), 'ArrowUp');
    assert.deepEqual(ids(), ['rows-0', 'rows-2', 'rows-1'], 'Новая строка получает обработчики');
    key(window, document.querySelector('#rows-0 button'), 'ArrowDown');
    assert.deepEqual(ids(), ['rows-2', 'rows-0', 'rows-1'], 'Повторное подключение не дублирует обработчики');
    drag(window, document.querySelector('#rows-2 button'), document.getElementById('rows-1'));
    assert.deepEqual(ids(), ['rows-0', 'rows-1', 'rows-2'], 'Перетягивание меняет порядок');
    document.querySelector('form').dispatchEvent(new window.Event('submit'));
    assert.equal(document.querySelector('[name="rows-2-position"]').value, '3');
    assert.equal(document.querySelector('[name="rows-empty-position"]').value, '0', 'Шаблон новой строки не меняется');
    dom.window.close();

    const single = setup(`<form><div id="rows-group"><table><tbody>${row(0, 1)}${row('empty', 0, true)}</tbody></table></div></form>`);
    single.window.document.dispatchEvent(new single.window.Event('DOMContentLoaded'));
    assert.ok(single.window.document.querySelector('#rows-0 button').disabled);
    const singleContainer = single.window.document.querySelector('tbody');
    const extra = single.window.document.createElement('tbody');
    extra.innerHTML = row(1, 2);
    const extraRow = extra.firstElementChild;
    singleContainer.insertBefore(extraRow, single.window.document.getElementById('rows-empty'));
    extraRow.dispatchEvent(new single.window.CustomEvent('formset:added', {bubbles: true, detail: {formsetName: 'rows'}}));
    assert.equal(single.window.document.querySelector('#rows-0 button').disabled, false);
    extraRow.remove();
    single.window.document.dispatchEvent(new single.window.CustomEvent('formset:removed', {detail: {formsetName: 'rows'}}));
    assert.ok(single.window.document.querySelector('#rows-0 button').disabled);
    single.window.close();
}

async function checkList() {
    const dom = setup(`<div><form id="changelist-form"><input name="csrfmiddlewaretoken" value="csrf-test">
        <table><tbody>${[1, 2, 3].map((id) => `<tr id="table-${id}"><td><button data-price-table-id="${id}"
        data-reorder-url="/admin/sitecontent/pricetable/reorder/"></button></td></tr>`).join('')}</tbody></table></form></div>`);
    const {window} = dom;
    const {document} = window;
    let finish;
    const calls = [];
    window.fetch = (url, options) => {
        calls.push({url, options});
        return new Promise((resolve) => { finish = resolve; });
    };
    document.dispatchEvent(new window.Event('DOMContentLoaded'));
    const ids = () => [...document.querySelectorAll('tbody tr')].map((element) => element.id);
    const handle = document.querySelector('#table-3 button');
    key(window, handle, 'ArrowUp');
    assert.deepEqual(ids(), ['table-1', 'table-3', 'table-2']);
    assert.deepEqual(JSON.parse(calls[0].options.body), {ordered_ids: [1, 3, 2]});
    assert.equal(calls[0].url, '/admin/sitecontent/pricetable/reorder/');
    assert.equal(calls[0].options.headers['X-CSRFToken'], 'csrf-test');
    assert.ok(handle.disabled);
    key(window, handle, 'ArrowUp');
    assert.equal(calls.length, 1, 'Во время сохранения новые перестановки блокируются');
    finish({ok: true, json: async () => ({saved: true})});
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(handle.disabled, false);
    assert.match(document.querySelector('[role="status"]').textContent, /сохранён/);
    key(window, handle, 'ArrowUp');
    finish({ok: false});
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(ids(), ['table-1', 'table-3', 'table-2'], 'Ошибка возвращает прежний порядок');
    assert.match(document.querySelector('[role="status"]').textContent, /не сохранён/);
    key(window, handle, 'ArrowDown');
    finish({ok: true, json: async () => { throw new Error('HTML страницы входа'); }});
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(ids(), ['table-1', 'table-3', 'table-2']);
    dom.window.close();
}

async function checkDjangoInlineDeletion() {
    const dom = setup(`<form><input id="id_rows-TOTAL_FORMS" value="3">
        <input id="id_rows-INITIAL_FORMS" value="2"><input id="id_rows-MIN_NUM_FORMS" value="0">
        <input id="id_rows-MAX_NUM_FORMS" value="1000"><div class="inline-group" id="rows-group">
        <table><tbody>${row(0, 1).replace('form-row', 'form-row has_original')}
        ${row(1, 2).replace('form-row', 'form-row has_original')}
        ${row(2, 3).replace('value="3"', 'value=""')}
        ${row('empty', 0, true).replaceAll('rows-empty-', 'rows-__prefix__-')}</tbody></table></div></form>`);
    const {window} = dom;
    const {document} = window;
    window.eval(fs.readFileSync(path.join(djangoStatic, 'vendor/jquery/jquery.js'), 'utf8'));
    window.django = {jQuery: window.jQuery};
    window.eval(fs.readFileSync(path.join(djangoStatic, 'inlines.js'), 'utf8'));
    window.jQuery('#rows-group tr.form-row').tabularFormset('#rows-group', {
        prefix: 'rows', addText: 'Добавить строку', deleteText: 'Удалить', addButton: null,
    });
    const newRow = document.getElementById('rows-2');
    const newHandle = newRow.querySelector('button');
    key(window, newHandle, 'ArrowUp');
    key(window, newHandle, 'ArrowUp');
    document.querySelector('.add-row a').click();
    const extraRow = document.getElementById('rows-3');
    extraRow.querySelector('.inline-deletelink').click();
    assert.equal(newRow.querySelector('input[name$="-id"]').name, 'rows-0-id', 'Настоящий Django перенумеровал формы по DOM');
    document.querySelector('form').dispatchEvent(new window.Event('submit'));
    assert.equal(newRow.querySelector('input[name$="-id"]').name, 'rows-2-id', 'Перед POST новая строка вернулась за INITIAL_FORMS');
    assert.equal(newRow.querySelector('input[name$="-position"]').value, '1', 'Видимый порядок новой строки сохранён');
    assert.equal(document.querySelector('[name="rows-0-id"]').value, '1');
    assert.equal(document.querySelector('[name="rows-1-id"]').value, '2');
    dom.window.close();
}

(async () => {
    await checkInline();
    await checkList();
    await checkDjangoInlineDeletion();
    console.log('Порядок таблиц и строк: клавиатура, drag-and-drop, динамические строки, CSRF, блокировка и откат — OK.');
})().catch((error) => { console.error(error); process.exitCode = 1; });
