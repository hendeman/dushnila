(() => {
  const trigger = document.querySelector('[data-mobile-menu-open]');
  const dialog = document.getElementById('mobile-site-menu');

  if (!trigger || !dialog) {
    return;
  }

  function setExpanded(isExpanded) {
    trigger.setAttribute('aria-expanded', isExpanded ? 'true' : 'false');
  }

  function closeDialog() {
    if (typeof dialog.close === 'function') {
      dialog.close();
    } else {
      dialog.removeAttribute('open');
      setExpanded(false);
    }
  }

  trigger.addEventListener('click', () => {
    setExpanded(true);
    if (typeof dialog.showModal === 'function') {
      dialog.showModal();
    } else {
      dialog.setAttribute('open', '');
    }
  });

  dialog.querySelectorAll('[data-mobile-menu-close]').forEach((button) => {
    button.addEventListener('click', closeDialog);
  });

  dialog.addEventListener('close', () => {
    setExpanded(false);
  });

  const mobileViewport = window.matchMedia('(max-width: 700px)');
  if (typeof mobileViewport.addEventListener === 'function') {
    mobileViewport.addEventListener('change', (event) => {
      if (!event.matches && dialog.open) {
        closeDialog();
      }
    });
  }
})();
