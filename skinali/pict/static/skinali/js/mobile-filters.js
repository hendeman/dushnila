(() => {
  const triggers = document.querySelectorAll('[data-mobile-filter-open]');

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
