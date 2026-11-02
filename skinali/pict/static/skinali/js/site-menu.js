(() => {
  const trigger = document.querySelector('[data-mobile-menu-open]');
  const navigation = document.getElementById('mobile-site-menu');
  const container = trigger?.closest('.site-navigation-panel__inner');
  const menu = navigation?.querySelector('ul.mainmenu');

  if (!trigger || !navigation || !container || !menu) {
    return;
  }

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
    if (container.classList.contains('is-collapsed') === shouldCollapse) {
      return;
    }

    const focusedElement = document.activeElement;
    setExpanded(false);
    container.classList.toggle('is-collapsed', shouldCollapse);

    if (shouldCollapse && navigation.contains(focusedElement)) {
      trigger.focus({ preventScroll: true });
    } else if (!shouldCollapse && focusedElement === trigger) {
      navigation.querySelector('li:not([hidden]) a, li:not([hidden]) button')
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

  window.addEventListener('resize', scheduleLayout);

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

  updateLayout();
})();
