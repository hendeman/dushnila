(() => {
  const trigger = document.querySelector('[data-mobile-menu-open]');
  const navigation = document.getElementById('mobile-site-menu');
  const container = trigger?.closest('.site-navigation-panel__inner');
  const menu = navigation?.querySelector('ul.mainmenu');

  if (!trigger || !navigation || !container || !menu) {
    return;
  }

  const sectionShortcut = container.querySelector('[data-header-shortcut]');
  const sectionControl = sectionShortcut?.firstElementChild;
  const movedItems = [
    {
      shortcut: sectionShortcut,
      menuItem: menu.querySelector('[data-header-shortcut-item]'),
    },
    {
      shortcut: container.querySelector('[data-header-favorites]'),
      menuItem: menu.querySelector('[data-favorites-menu]'),
    },
  ].filter(({ shortcut, menuItem }) => shortcut && menuItem);

  function setExpanded(isExpanded) {
    trigger.setAttribute('aria-expanded', isExpanded ? 'true' : 'false');
    trigger.setAttribute(
      'aria-label',
      isExpanded ? 'Закрыть главное меню' : 'Открыть главное меню'
    );
    navigation.classList.toggle('is-open', isExpanded);
  }

  function isExpanded() {
    return trigger.getAttribute('aria-expanded') === 'true';
  }

  function updateLayout() {
    const style = window.getComputedStyle(container);
    const availableWidth = container.clientWidth
      - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);

    // Отдельная невидимая строка измеряет пункты, не меняя раскрытое меню и фокус.
    const measurement = menu.cloneNode(true);
    measurement.classList.add('mainmenu--measure');
    measurement.setAttribute('aria-hidden', 'true');
    measurement.inert = true;
    measurement.removeAttribute('id');
    measurement.querySelectorAll('[id]').forEach((element) => {
      element.removeAttribute('id');
    });
    container.appendChild(measurement);
    const requiredWidth = measurement.getBoundingClientRect().width;
    measurement.remove();

    const shouldCollapse = requiredWidth > availableWidth;
    updateMenuMode(shouldCollapse);

    if (shouldCollapse && sectionControl) {
      const availableShortcutWidth = sectionShortcut.getBoundingClientRect().width;
      // Проверяем ширину полной подписи с иконкой, даже если иконка уже скрыта.
      sectionShortcut.classList.add('is-measuring');
      const requiredShortcutWidth = sectionControl.getBoundingClientRect().width;
      sectionShortcut.classList.remove('is-measuring');
      sectionShortcut.classList.toggle('is-icon-hidden', requiredShortcutWidth > availableShortcutWidth);
    }
  }

  function updateMenuMode(shouldCollapse) {
    if (container.classList.contains('is-collapsed') === shouldCollapse) {
      return;
    }

    const focusedElement = document.activeElement;
    setExpanded(false);
    container.classList.toggle('is-collapsed', shouldCollapse);

    const movedItem = movedItems.find(({ shortcut, menuItem }) => (
      shouldCollapse ? menuItem : shortcut
    ).contains(focusedElement));
    if (shouldCollapse && navigation.contains(focusedElement)) {
      const replacement = movedItem?.shortcut.querySelector('a');
      (replacement || trigger).focus({ preventScroll: true });
    } else if (!shouldCollapse && (focusedElement === trigger || movedItem)) {
      const replacement = movedItem && !movedItem.menuItem.hidden
        ? movedItem.menuItem.querySelector('a') : null;
      (replacement || navigation.querySelector('li:not([hidden]) a, li:not([hidden]) button'))
        ?.focus({ preventScroll: true });
    }
  }

  let layoutFrame = null;
  function scheduleLayout() {
    if (layoutFrame !== null) {
      return;
    }
    layoutFrame = window.requestAnimationFrame(() => {
      layoutFrame = null;
      updateLayout();
    });
  }

  trigger.addEventListener('click', () => {
    setExpanded(!isExpanded());
  });

  navigation.querySelectorAll('a, [data-callback-open]').forEach((control) => {
    control.addEventListener('click', () => setExpanded(false));
  });

  document.addEventListener('click', (event) => {
    if (
      isExpanded() &&
      !navigation.contains(event.target) &&
      !trigger.contains(event.target)
    ) {
      setExpanded(false);
    }
  });

  let previousWindowWidth = window.innerWidth;
  window.addEventListener('resize', () => {
    const width = window.innerWidth;
    if (width !== previousWindowWidth) {
      previousWindowWidth = width;
      scheduleLayout();
    }
  });

  if (typeof ResizeObserver === 'function') {
    let previousWidth = null;
    new ResizeObserver(([entry]) => {
      if (entry.contentRect.width !== previousWidth) {
        previousWidth = entry.contentRect.width;
        scheduleLayout();
      }
    }).observe(container);
  }

  new MutationObserver(scheduleLayout).observe(menu, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: ['hidden', 'class', 'style'],
  });

  if (document.fonts) {
    document.fonts.ready.then(scheduleLayout);
    document.fonts.addEventListener('loadingdone', scheduleLayout);
  }

  try {
    updateLayout();
  } finally {
    container.classList.remove('is-menu-pending');
  }
})();
