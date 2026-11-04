const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.resolve(__dirname, '../../skinali/pict/static/skinali/js/site-menu.js'), 'utf8',
);

function environment({ width = 1000, required = 800, withShortcut = true, favoriteCount = 0 } = {}) {
  const events = new Map();
  const frames = [];
  const measurements = [];
  const focuses = [];
  const classes = () => {
    const values = new Set();
    return {
      add: (name) => values.add(name),
      remove: (name) => values.delete(name),
      contains: (name) => values.has(name),
      toggle(name, enabled) { enabled ? values.add(name) : values.delete(name); },
    };
  };
  const document = {
    activeElement: null,
    addEventListener: (name, listener) => events.set(`document:${name}`, listener),
  };
  const control = (name) => ({
    focus() { document.activeElement = this; focuses.push(name); },
    addEventListener(type, listener) { this[type] = listener; },
    contains(element) { return element === this; },
  });
  const catalog = control('catalog');
  const first = control('first');
  const quickLink = control('shortcut');
  const favorites = control('favorites');
  const quickFavorites = control('favorites-shortcut');
  const shortcut = {
    classList: classes(),
    width: 180,
    firstElementChild: {
      getBoundingClientRect: () => ({ width: 160 }),
    },
    getBoundingClientRect: () => ({ width: shortcut.width }),
    contains: (element) => element === quickLink,
    querySelector: () => quickLink,
  };
  const item = { contains: (element) => element === catalog, querySelector: () => catalog };
  const favoritesShortcut = {
    contains: (element) => element === quickFavorites,
    querySelector: () => quickFavorites,
  };
  const favoritesItem = {
    hidden: favoriteCount === 0,
    contains: (element) => element === favorites,
    querySelector: () => favorites,
  };
  const menu = {
    classList: classes(),
    required,
    querySelector: (selector) => selector === '[data-favorites-menu]'
      ? favoritesItem : withShortcut ? item : null,
    cloneNode() {
      const clone = {
        classList: classes(),
        setAttribute() {},
        removeAttribute() {},
        querySelectorAll: () => [],
        getBoundingClientRect: () => ({ width: menu.required }),
        remove() { clone.removed = true; },
      };
      return clone;
    },
  };
  const navigation = {
    classList: classes(),
    contains: (element) => element === catalog || element === first || element === favorites,
    querySelector: (selector) => selector === 'ul.mainmenu' ? menu : first,
    querySelectorAll: () => [catalog, first, favorites],
  };
  const container = {
    clientWidth: width,
    classList: classes(),
    querySelector: (selector) => selector === '[data-header-favorites]'
      ? favoritesShortcut : withShortcut ? shortcut : null,
    appendChild(clone) {
      clone.menuPending = container.classList.contains('is-menu-pending');
      measurements.push(clone);
    },
  };
  container.classList.add('is-menu-pending');
  const trigger = control('trigger');
  const attributes = new Map([['aria-expanded', 'false']]);
  trigger.closest = () => container;
  trigger.setAttribute = (name, value) => attributes.set(name, value);
  trigger.getAttribute = (name) => attributes.get(name);
  document.querySelector = () => trigger;
  document.getElementById = () => navigation;
  let mutations;
  class MutationObserver {
    constructor(listener) { mutations = listener; }
    observe() {}
  }
  const window = {
    innerWidth: width,
    innerHeight: 800,
    getComputedStyle: () => ({ paddingLeft: '16', paddingRight: '16' }),
    requestAnimationFrame(callback) { frames.push(callback); return frames.length; },
    addEventListener: (name, listener) => events.set(`window:${name}`, listener),
  };
  vm.runInNewContext(source, { document, window, MutationObserver });
  const flush = () => { while (frames.length) frames.shift()(); };
  return {
    trigger, container, navigation, menu, document, catalog, first, quickLink, focuses, measurements,
    favorites, quickFavorites, shortcut,
    resize(nextWidth, nextHeight = window.innerHeight) {
      window.innerWidth = nextWidth;
      window.innerHeight = nextHeight;
      container.clientWidth = nextWidth;
      events.get('window:resize')();
      flush();
    },
    changeRequired(nextRequired) { menu.required = nextRequired; mutations(); flush(); },
    collapsed: () => container.classList.contains('is-collapsed'),
    expanded: () => trigger.getAttribute('aria-expanded') === 'true',
  };
}

test('menu capacity always measures the complete desktop row and preserves an open menu on recalculation', () => {
  const env = environment({ width: 700 });
  assert.equal(env.measurements[0].menuPending, true);
  assert.equal(env.collapsed(), true);
  assert.equal(env.container.classList.contains('is-menu-pending'), false);
  env.trigger.click();
  assert.equal(env.expanded(), true);
  env.resize(700, 750);
  assert.equal(env.measurements.length, 1);
  env.resize(740, 750);
  assert.equal(env.measurements.length, 2);
  assert.equal(env.collapsed(), true);
  assert.equal(env.expanded(), true);
  env.resize(1000);
  assert.equal(env.collapsed(), false);
  assert.equal(env.expanded(), false);
  env.changeRequired(1100);
  assert.equal(env.collapsed(), true);
  env.changeRequired(800);
  assert.equal(env.collapsed(), false);
  assert.ok(env.measurements.every(clone => clone.removed && clone.inert));
  assert.equal(env.menu.classList.contains('mainmenu--measure'), false);
});

test('catalog focus moves between the normal menu and shortcut when layout changes', () => {
  const env = environment();
  env.document.activeElement = env.catalog;
  env.resize(700);
  assert.deepEqual(env.focuses, ['shortcut']);
  env.resize(1000);
  assert.deepEqual(env.focuses, ['shortcut', 'catalog']);
  env.document.activeElement = env.first;
  env.resize(700);
  assert.equal(env.focuses.at(-1), 'trigger');
  env.resize(1000);
  assert.equal(env.focuses.at(-1), 'first');
});

test('section icon hides and returns as available space changes within the collapsed layout', () => {
  const env = environment({ width: 700 });
  env.trigger.click();
  assert.equal(env.shortcut.classList.contains('is-icon-hidden'), false);

  env.shortcut.width = 140;
  env.changeRequired(850);
  assert.equal(env.shortcut.classList.contains('is-icon-hidden'), true);

  env.shortcut.width = 160;
  env.resize(740);
  assert.equal(env.shortcut.classList.contains('is-icon-hidden'), false);
  assert.equal(env.shortcut.classList.contains('is-measuring'), false);
  assert.equal(env.expanded(), true);
});

test('unselected or hidden shortcut preserves normal menu focus behavior', () => {
  const env = environment({ withShortcut: false });
  env.document.activeElement = env.catalog;
  env.resize(700);
  assert.equal(env.focuses.at(-1), 'trigger');
  env.resize(1000);
  assert.equal(env.focuses.at(-1), 'first');
});

test('favorites focus moves between desktop menu and header without opening the dropdown', () => {
  const env = environment({ favoriteCount: 2 });
  env.document.activeElement = env.favorites;
  env.resize(700);
  assert.deepEqual(env.focuses, ['favorites-shortcut']);
  assert.equal(env.expanded(), false);
  env.resize(1000);
  assert.deepEqual(env.focuses, ['favorites-shortcut', 'favorites']);
});

test('empty favorites shortcut does not return focus to the hidden desktop menu item', () => {
  const env = environment({ width: 700, favoriteCount: 0 });
  env.document.activeElement = env.quickFavorites;
  env.resize(1000);
  assert.deepEqual(env.focuses, ['first']);
});
