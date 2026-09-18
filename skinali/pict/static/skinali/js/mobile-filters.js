(() => {
  const FILTER_SCROLL_STORAGE_KEY = 'skinali:filter-scroll-position';
  const FILTER_LINK_SELECTOR = [
    '.catalog-categories a',
    '.list-pages-color a',
    '.mobile-filter-dialog a',
    '.finished-work-types a'
  ].join(', ');
  const triggers = document.querySelectorAll('[data-mobile-filter-open]');

  function getPageKey(url) {
    return `${url.pathname}${url.search}`;
  }

  function saveScrollPosition(targetUrl) {
    if (targetUrl.origin !== window.location.origin) {
      return;
    }

    try {
      window.sessionStorage.setItem(FILTER_SCROLL_STORAGE_KEY, JSON.stringify({
        pageKey: getPageKey(targetUrl),
        left: window.scrollX,
        top: window.scrollY
      }));
    } catch (error) {
      // Недоступный sessionStorage не должен мешать обычному переходу.
    }
  }

  function rememberScrollPosition(event) {
    const link = event.currentTarget;
    if (
      event.defaultPrevented
      || event.button !== 0
      || event.ctrlKey
      || event.metaKey
      || event.shiftKey
      || event.altKey
      || link.target === '_blank'
    ) {
      return;
    }

    const targetUrl = new URL(link.href, window.location.href);
    saveScrollPosition(targetUrl);
  }

  function getFormTargetUrl(form) {
    const targetUrl = new URL(form.action, window.location.href);
    targetUrl.search = '';
    new FormData(form).forEach((value, name) => {
      targetUrl.searchParams.append(name, value);
    });
    return targetUrl;
  }

  function restoreScrollPosition() {
    let savedScroll;
    try {
      savedScroll = JSON.parse(
        window.sessionStorage.getItem(FILTER_SCROLL_STORAGE_KEY) || 'null'
      );
      window.sessionStorage.removeItem(FILTER_SCROLL_STORAGE_KEY);
    } catch (error) {
      return;
    }

    if (
      !savedScroll
      || savedScroll.pageKey !== getPageKey(window.location)
      || !Number.isFinite(savedScroll.left)
      || !Number.isFinite(savedScroll.top)
    ) {
      return;
    }

    const previousScrollRestoration = window.history.scrollRestoration;
    window.history.scrollRestoration = 'manual';
    let userInteracted = false;
    const markInteraction = () => {
      userInteracted = true;
    };
    const interactionEvents = ['wheel', 'touchstart', 'keydown', 'pointerdown'];
    interactionEvents.forEach((eventName) => {
      window.addEventListener(eventName, markInteraction, { once: true, passive: true });
    });

    const restore = () => {
      if (!userInteracted) {
        window.scrollTo(savedScroll.left, savedScroll.top);
      }
    };

    window.requestAnimationFrame(() => {
      restore();
      window.requestAnimationFrame(restore);
    });
    window.addEventListener('load', () => {
      restore();
      window.history.scrollRestoration = previousScrollRestoration;
    }, { once: true });
  }

  document.querySelectorAll(FILTER_LINK_SELECTOR).forEach((link) => {
    link.addEventListener('click', rememberScrollPosition);
  });

  document.querySelectorAll('[data-mobile-color-form]').forEach((form) => {
    const checkboxes = Array.from(
      form.querySelectorAll('[data-mobile-color-checkbox]')
    );
    const allColorsButton = form.querySelector('[data-mobile-color-clear]');
    const allColorsCheck = form.querySelector('[data-mobile-color-all-check]');
    const maxColors = Number.parseInt(form.dataset.maxColors, 10) || 3;

    const updateColorSelection = () => {
      const selectedCount = checkboxes.filter((checkbox) => checkbox.checked).length;

      checkboxes.forEach((checkbox) => {
        const item = checkbox.closest('.mobile-filter-dialog__item--color');
        const check = item?.querySelector('[data-mobile-color-check]');
        const isDisabled = !checkbox.checked && selectedCount >= maxColors;
        checkbox.disabled = isDisabled;
        item?.classList.toggle('is-selected', checkbox.checked);
        item?.classList.toggle('is-disabled', isDisabled);
        if (item) {
          item.setAttribute('aria-disabled', isDisabled ? 'true' : 'false');
        }
        if (check) {
          check.hidden = !checkbox.checked;
        }
      });

      const allColorsSelected = selectedCount === 0;
      allColorsButton?.classList.toggle('is-selected', allColorsSelected);
      if (allColorsButton) {
        if (allColorsSelected) {
          allColorsButton.setAttribute('aria-current', 'true');
        } else {
          allColorsButton.removeAttribute('aria-current');
        }
      }
      if (allColorsCheck) {
        allColorsCheck.hidden = !allColorsSelected;
      }
    };

    const clearColorSelection = () => {
      checkboxes.forEach((checkbox) => {
        checkbox.disabled = false;
        checkbox.checked = false;
      });
      updateColorSelection();
    };

    checkboxes.forEach((checkbox) => {
      checkbox.addEventListener('change', updateColorSelection);
    });
    allColorsButton?.addEventListener('click', clearColorSelection);
    form.addEventListener('submit', () => {
      saveScrollPosition(getFormTargetUrl(form));
    });
    form.closest('dialog')?.addEventListener('close', () => {
      form.reset();
      updateColorSelection();
    });
    updateColorSelection();
  });

  restoreScrollPosition();

  function setExpanded(dialogId, isExpanded) {
    document.querySelectorAll(`[data-mobile-filter-open="${dialogId}"]`).forEach((trigger) => {
      trigger.setAttribute('aria-expanded', isExpanded ? 'true' : 'false');
    });
  }

  function closeDialog(dialog) {
    if (typeof dialog.close === 'function') {
      dialog.close();
    } else {
      dialog.removeAttribute('open');
      setExpanded(dialog.id, false);
    }
  }

  triggers.forEach((trigger) => {
    trigger.setAttribute('aria-expanded', 'false');
    trigger.addEventListener('click', () => {
      const dialogId = trigger.dataset.mobileFilterOpen;
      const dialog = document.getElementById(dialogId);
      if (!dialog) {
        return;
      }

      setExpanded(dialogId, true);
      if (typeof dialog.showModal === 'function') {
        dialog.showModal();
      } else {
        dialog.setAttribute('open', '');
      }
    });
  });

  document.querySelectorAll('.mobile-filter-dialog').forEach((dialog) => {
    dialog.querySelectorAll('[data-mobile-filter-close]').forEach((button) => {
      button.addEventListener('click', () => closeDialog(dialog));
    });

    dialog.addEventListener('close', () => {
      setExpanded(dialog.id, false);
    });
  });
})();
