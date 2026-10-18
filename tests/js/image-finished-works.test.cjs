const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const template = fs.readFileSync(
  path.resolve(__dirname, '../../skinali/pict/templates/pict/base.html'),
  'utf8',
);
const source = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];

function createEnvironment(photos = [{ id: 'first' }, { id: 'second' }]) {
  const bindings = [];
  const opened = [];
  const elements = new Map();
  const listeners = [];
  const focused = [];
  const link = {
    dataset: { imageFinishedWorksOpen: 'image-finished-works-275' },
    isConnected: true,
    addEventListener: (type, listener) => listeners.push(listener),
    focus: (options) => focused.push(options),
  };
  elements.set(link.dataset.imageFinishedWorksOpen, {
    querySelectorAll: (selector) => {
      assert.equal(selector, 'a[data-fancybox]');
      return photos;
    },
  });
  const context = vm.createContext({
    Fancybox: {
      bind: (selector, options) => bindings.push({ selector, options }),
      fromNodes: (nodes, options) => opened.push({ nodes, options }),
    },
    document: {
      getElementById: (id) => elements.get(id),
      addEventListener: () => {},
    },
    window: { queueMicrotask: (callback) => callback() },
  });
  vm.runInContext(source, context);
  const content = { querySelector: () => link };
  const click = () => {
    const event = {
      defaultPrevented: false,
      propagationStopped: false,
      preventDefault() { this.defaultPrevented = true; },
      stopPropagation() { this.propagationStopped = true; },
    };
    listeners[0](event);
    return event;
  };
  return { context, content, link, photos, bindings, opened, elements, listeners, focused, click };
}

test('linked photo groups use the existing finished work viewer', () => {
  const { bindings } = createEnvironment();
  const binding = bindings.find(({ selector }) => selector.includes('image-finished-works-'));
  assert.ok(binding.selector.includes('[data-fancybox="finished-works"]'));
  assert.equal(binding.options.mainClass, 'catalog-gallery-modal finished-works-modal');
  assert.equal(binding.options.Hash, false);
});

test('interior link opens only its photo group and returns focus after closing', () => {
  const env = createEnvironment();
  env.context.enableImageFinishedWorks(env.content);
  const event = env.click();
  assert.equal(event.defaultPrevented, true);
  assert.equal(event.propagationStopped, true);
  assert.deepEqual(Array.from(env.opened[0].nodes), env.photos);
  assert.equal(env.opened[0].options.placeFocusBack, false);
  assert.equal(typeof env.opened[0].options.on.done, 'function');
  env.opened[0].options.on.destroy();
  assert.equal(env.focused.length, 1);
  assert.equal(env.focused[0].preventScroll, true);
});

test('repeated slide preparation does not duplicate the click handler', () => {
  const env = createEnvironment();
  env.context.enableImageFinishedWorks(env.content);
  env.context.enableImageFinishedWorks(env.content);
  assert.equal(env.listeners.length, 1);
  env.click();
  assert.equal(env.opened.length, 1);
});

test('missing and empty galleries preserve the link to the detail page', () => {
  for (const missing of [false, true]) {
    const env = createEnvironment([]);
    if (missing) env.elements.clear();
    env.context.enableImageFinishedWorks(env.content);
    const event = env.click();
    assert.equal(event.defaultPrevented, false);
    assert.equal(env.opened.length, 0);
  }
});

test('closing the photo viewer does not focus a removed catalog card', () => {
  const env = createEnvironment();
  env.context.enableImageFinishedWorks(env.content);
  env.click();
  env.link.isConnected = false;
  env.opened[0].options.on.destroy();
  assert.equal(env.focused.length, 0);
});
