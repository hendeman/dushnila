const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.resolve(__dirname, '../../skinali/pict/static/skinali/js/admin-seo-fields.js'),
  'utf8',
);

class Element {
  constructor(id = '', value = '') {
    this.id = id;
    this.value = value;
    this.dataset = {};
    this.attributes = new Map();
    this.listeners = new Map();
    this.children = [];
    this.afterElements = [];
    this.textContent = '';
    this.flexContainer = null;
    this.form = null;
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  setAttribute(name, value) {
    this.attributes.set(name, value);
  }

  addEventListener(name, listener) {
    const listeners = this.listeners.get(name) || [];
    listeners.push(listener);
    this.listeners.set(name, listeners);
  }

  dispatch(name, target = this) {
    (this.listeners.get(name) || []).forEach((listener) => listener({ target }));
  }

  append(element) {
    this.children.push(element);
  }

  after(element) {
    this.afterElements.push(element);
  }

  closest(selector) {
    assert.equal(selector, '.flex-container');
    return this.flexContainer;
  }
}

function createEnvironment(specs = [], readyState = 'complete') {
  const document = new Element();
  document.readyState = readyState;
  const elements = new Map();
  const form = new Element();
  const fields = specs.map(({ id, value = '', help = true, flex = true }) => {
    const field = new Element(id, value);
    field.form = form;
    if (flex) {
      field.flexContainer = new Element();
    }
    if (help) {
      const helpElement = new Element(`${id}_helptext`);
      helpElement.textContent = 'Исходная подсказка';
      elements.set(helpElement.id, helpElement);
    }
    return field;
  });
  const root = (rootFields) => ({
    querySelectorAll(selector) {
      assert.equal(selector, '[data-seo-counter]');
      return rootFields;
    },
  });
  document.querySelectorAll = root(fields).querySelectorAll;
  document.getElementById = (id) => elements.get(id) || null;
  document.createElement = () => new Element();
  const run = () => vm.runInNewContext(source, { document, setTimeout });
  const helpFor = (field) => (
    elements.get(`${field.id}_helptext`)
    || (field.flexContainer || field).afterElements[0]
  );
  const counterFor = (field) => helpFor(field).children[0];
  return { document, fields, form, root, run, helpFor, counterFor };
}

test('счётчики сразу показывают длину сохранённых и пустых SEO-полей', () => {
  const env = createEnvironment([
    { id: 'id_seo_title', value: 'Каталог' },
    { id: 'id_seo_description' },
    { id: 'id_seo_h1', value: 'Готовые работы' },
  ]);
  env.run();
  assert.deepEqual(
    env.fields.map((field) => env.counterFor(field).textContent),
    ['Символов: 7.', 'Символов: 0.', 'Символов: 14.'],
  );
});

test('ввод, удаление, вставка и change обновляют длину с учётом пробелов и Unicode', () => {
  const env = createEnvironment([{ id: 'id_seo_title' }]);
  env.run();
  const field = env.fields[0];
  for (const [value, event, length] of [
    ['Кухня 😀', 'input', 7],
    ['  Кухня 😀  ', 'input', 11],
    ['А', 'input', 1],
    ['', 'input', 0],
    ['Вставленный текст', 'input', 17],
    ['12345', 'change', 5],
  ]) {
    field.value = value;
    field.dispatch(event);
    assert.equal(env.counterFor(field).textContent, `Символов: ${length}.`);
    assert.equal(field.value, value);
  }
});

test('счётчик не обрезает текст и не меняет ограничения поля', () => {
  const value = 'З'.repeat(180);
  const env = createEnvironment([{ id: 'id_seo_description', value }]);
  const field = env.fields[0];
  field.setAttribute('maxlength', '320');
  env.run();
  assert.equal(field.value, value);
  assert.equal(field.getAttribute('maxlength'), '320');
  assert.equal(env.counterFor(field).textContent, 'Символов: 180.');
});

test('исходная подсказка и ссылки доступности сохраняются', () => {
  const env = createEnvironment([{ id: 'id_seo_title', value: 'SEO' }]);
  const field = env.fields[0];
  field.setAttribute('aria-describedby', 'id_seo_title_helptext id_seo_title_error');
  env.run();
  const counter = env.counterFor(field);
  assert.equal(env.helpFor(field).textContent, 'Исходная подсказка');
  assert.equal(counter.getAttribute('role'), 'status');
  assert.equal(counter.getAttribute('aria-live'), 'polite');
  assert.equal(counter.getAttribute('aria-atomic'), 'true');
  assert.equal(
    field.getAttribute('aria-describedby'),
    'id_seo_title_helptext id_seo_title_error id_seo_title_counter',
  );
});

test('для поля без подсказки создаётся контейнер, включая старую разметку без flex', () => {
  const env = createEnvironment([
    { id: 'id_seo_h1', help: false },
    { id: 'id_seo_title', help: false, flex: false },
  ]);
  env.run();
  for (const field of env.fields) {
    assert.equal(env.helpFor(field).className, 'help');
    assert.equal(env.counterFor(field).textContent, 'Символов: 0.');
    assert.equal(field.getAttribute('aria-describedby'), `${field.id}_counter`);
  }
});

test('инициализация ждёт DOM и не дублирует счётчики при повторных событиях', () => {
  const env = createEnvironment([{ id: 'id_seo_title', value: 'SEO' }], 'loading');
  const field = env.fields[0];
  env.run();
  assert.equal(env.helpFor(field).children.length, 0);
  env.document.dispatch('DOMContentLoaded');
  env.document.dispatch('DOMContentLoaded');
  env.document.dispatch('formset:added', env.root([field]));
  assert.equal(env.helpFor(field).children.length, 1);
  assert.equal(field.listeners.get('input').length, 1);
  assert.equal(env.counterFor(field).textContent, 'Символов: 3.');
});

test('динамически добавленные поля получают отдельные счётчики', () => {
  const env = createEnvironment();
  env.run();
  const field = new Element('id_form-1-seo_title', 'Новое');
  env.document.dispatch('formset:added', env.root([field]));
  assert.equal(env.counterFor(field).textContent, 'Символов: 5.');
  field.value = 'Новое поле';
  field.dispatch('input');
  assert.equal(env.counterFor(field).textContent, 'Символов: 10.');
});

test('после сброса формы длина обновляется после восстановления значений', async () => {
  const env = createEnvironment([{ id: 'id_seo_title', value: 'Изменено' }]);
  env.run();
  env.form.dispatch('reset');
  env.fields[0].value = 'SEO';
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(env.counterFor(env.fields[0]).textContent, 'Символов: 3.');
});

test('форма без SEO-полей не требует дополнительных элементов', () => {
  const env = createEnvironment();
  assert.doesNotThrow(env.run);
});
