const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const template = fs.readFileSync(
  path.resolve(__dirname, '../../skinali/pict/templates/pict/base.html'),
  'utf8',
);
const source = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1]
  .replaceAll("{% url 'skinali' %}", '/skinali/');

function createEnvironment({ rows = 1, isFavorite = false, ok = true } = {}) {
  const listeners = [];
  const redirects = [];
  const requests = [];
  const classes = new Set(['is-active']);
  const button = {
    disabled: false,
    dataset: { pictId: '301', favoriteUrl: '/favorites/toggle/301/' },
    classList: {
      contains: (name) => classes.has(name),
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      toggle: (name, enabled) => enabled ? classes.add(name) : classes.delete(name),
    },
    hasAttribute: () => false,
    setAttribute: () => {},
    querySelector: () => ({}),
  };
  const share = { hidden: false };
  const empty = { hidden: true };
  const count = { textContent: String(rows) };
  const row = { remove: () => { rows -= 1; } };
  const context = vm.createContext({
    Fancybox: { bind: () => {} },
    CustomEvent: class {
      constructor(type, options) {
        this.type = type;
        this.detail = options.detail;
      }
    },
    document: {
      addEventListener: (type, handler) => {
        if (type === 'click') listeners.push(handler);
      },
      dispatchEvent: () => {},
      querySelectorAll: (selector) => {
        if (selector.startsWith('[data-favorite-toggle]')) return [button];
        if (selector === '[data-favorites-count]') return [count];
        return [];
      },
      querySelector: (selector) => {
        if (selector === 'meta[name="csrf-token"]') return { content: 'csrf-token' };
        if (selector.startsWith('[data-favorite-row]')) return rows > 0 ? row : null;
        if (selector === '[data-favorites-share]') return share;
        if (selector === '[data-favorites-empty]') return empty;
        throw new Error(`Unexpected selector: ${selector}`);
      },
    },
    window: {
      location: { replace: (url) => redirects.push(url) },
      setTimeout: () => {},
    },
    fetch: async (url, options) => {
      requests.push({ url, options });
      return {
        ok,
        status: ok ? 200 : 500,
        json: async () => ({
          pict_id: 301,
          is_favorite: isFavorite,
          favorites_count: isFavorite ? rows + 1 : Math.max(0, rows - 1),
          favorites_share_url: '',
          has_pending_favorites: false,
        }),
      };
    },
  });
  vm.runInContext(source, context);
  assert.equal(listeners.length, 1);
  const click = () => listeners[0]({
    target: { closest: () => button },
    preventDefault: () => {},
  });
  return { click, redirects, requests, share, empty, count, button, classes };
}

test('removing the last favorite opens the catalog without showing the empty page', async () => {
  const env = createEnvironment();
  await env.click();
  assert.deepEqual(env.redirects, ['/skinali/']);
  assert.equal(env.count.textContent, 0);
  assert.equal(env.share.hidden, true);
  assert.equal(env.empty.hidden, true);
  assert.equal(env.requests[0].options.method, 'POST');
  assert.equal(env.requests[0].options.headers['X-CSRFToken'], 'csrf-token');
});

test('removing one of several favorites stays on the page', async () => {
  const env = createEnvironment({ rows: 2 });
  await env.click();
  assert.deepEqual(env.redirects, []);
  assert.equal(env.count.textContent, 1);
  assert.equal(env.share.hidden, false);
});

test('removing a favorite outside the favorites page does not redirect', async () => {
  const env = createEnvironment({ rows: 0 });
  await env.click();
  assert.deepEqual(env.redirects, []);
});

test('adding a favorite does not redirect', async () => {
  const env = createEnvironment({ rows: 0, isFavorite: true });
  await env.click();
  assert.deepEqual(env.redirects, []);
  assert.equal(env.count.textContent, 1);
});

test('a failed removal leaves the card available for retry', async () => {
  const env = createEnvironment({ ok: false });
  await env.click();
  assert.deepEqual(env.redirects, []);
  assert.equal(env.button.disabled, false);
  assert.equal(env.classes.has('has-error'), true);
  assert.equal(env.share.hidden, false);
});
