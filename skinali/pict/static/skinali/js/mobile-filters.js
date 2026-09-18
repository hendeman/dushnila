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
      // Недоступный sessionStorage не должен мешать обычному переходу по ссылке.
    }
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
