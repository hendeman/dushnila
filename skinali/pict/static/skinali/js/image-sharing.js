(() => {
  const COPY_FEEDBACK_DURATION_MS = 2000;
  const copyFeedbackTimers = new WeakMap();
  const shareSelectors = {
    telegram: ({ sharedUrl, title }) => (
      `https://t.me/share/url?url=${encodeURIComponent(sharedUrl)}&text=${encodeURIComponent(title)}`
    ),
    viber: ({ message }) => `viber://forward?text=${encodeURIComponent(message)}`,
    whatsapp: ({ message }) => `https://wa.me/?text=${encodeURIComponent(message)}`
  };

  function getImageShareData(shareBlock) {
    let imageUrl;
    try {
      imageUrl = new URL(shareBlock.dataset.shareImageUrl, window.location.origin).href;
    } catch (error) {
      return null;
    }

    const imageNumber = shareBlock.dataset.imageNumber.trim();
    const title = `Изображение №${imageNumber} для скинали`;
    return {
      sharedUrl: imageUrl,
      title,
      message: `${title}\n${imageUrl}`
    };
  }

  function getFavoritesShareData(shareBlock) {
    const sharedUrl = shareBlock.dataset.shareUrl;
    if (!sharedUrl) {
      document.dispatchEvent(new CustomEvent('site:toast', {
        detail: { message: shareBlock.dataset.shareUnavailableMessage, kind: 'warning' }
      }));
      return null;
    }

    const title = 'Избранные изображения для скинали';
    return {
      sharedUrl,
      title,
      message: `${title}\n${sharedUrl}`
    };
  }

  function getShareData(shareBlock) {
    return shareBlock.dataset.shareKind === 'favorites'
      ? getFavoritesShareData(shareBlock)
      : getImageShareData(shareBlock);
  }

  async function copyText(text, shareBlock) {
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        return;
      } catch (error) {
        // При недоступности Clipboard API пробуем копирование через выделение.
      }
    }

    const focusedElement = document.activeElement;
    const field = document.createElement('textarea');
    field.value = text;
    field.readOnly = true;
    field.tabIndex = -1;
    field.style.cssText = 'position: fixed; top: 0; left: -9999px; font-size: 16px;';
    shareBlock.append(field);
    try {
      field.focus({ preventScroll: true });
      field.select();
      if (!document.execCommand('copy')) {
        throw new Error('Не удалось скопировать ссылку');
      }
    } finally {
      field.remove();
      focusedElement?.focus({ preventScroll: true });
    }
  }

  function setCopyFeedback(button, copied) {
    const label = copied ? 'Ссылка скопирована' : 'Копировать ссылку';
    button.classList.toggle('is-copied', copied);
    button.setAttribute('aria-label', label);
    button.title = label;
  }

  async function copyShareLink(button, shareBlock) {
    const shareData = getShareData(shareBlock);
    if (!shareData) {
      return;
    }

    window.clearTimeout(copyFeedbackTimers.get(button));
    copyFeedbackTimers.delete(button);
    setCopyFeedback(button, false);
    button.setAttribute('aria-busy', 'true');
    try {
      await copyText(shareData.sharedUrl, shareBlock);
      setCopyFeedback(button, true);
      copyFeedbackTimers.set(button, window.setTimeout(() => {
        setCopyFeedback(button, false);
        copyFeedbackTimers.delete(button);
      }, COPY_FEEDBACK_DURATION_MS));
      document.dispatchEvent(new CustomEvent('site:toast', {
        detail: { message: 'Ссылка скопирована', kind: 'success' }
      }));
    } catch (error) {
      document.dispatchEvent(new CustomEvent('site:toast', {
        detail: { message: 'Не удалось скопировать ссылку. Попробуйте ещё раз.', kind: 'error' }
      }));
    } finally {
      button.removeAttribute('aria-busy');
    }
  }

  function prepareShareLinks(shareBlock) {
    const shareData = getShareData(shareBlock);
    if (!shareData) {
      return false;
    }

    shareBlock.querySelectorAll('[data-share-service]').forEach((link) => {
      const buildShareUrl = shareSelectors[link.dataset.shareService];
      if (buildShareUrl) {
        link.href = buildShareUrl(shareData);
      }
    });
    return true;
  }

  document.addEventListener('click', async (event) => {
    const copyButton = event.target.closest('[data-share-copy]');
    if (copyButton) {
      event.preventDefault();
      const shareBlock = copyButton.closest('[data-share]');
      if (shareBlock && copyButton.getAttribute('aria-busy') !== 'true') {
        await copyShareLink(copyButton, shareBlock);
      }
      return;
    }

    const toggle = event.target.closest('[data-share-toggle]');
    if (!toggle) {
      return;
    }

    event.preventDefault();
    const shareBlock = toggle.closest('[data-share]');
    const services = shareBlock?.querySelector('[data-share-services]');
    if (!shareBlock || !services) {
      return;
    }

    const willOpen = toggle.getAttribute('aria-expanded') !== 'true';
    if (willOpen && !prepareShareLinks(shareBlock)) {
      return;
    }

    toggle.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
    services.hidden = !willOpen;
  });

  document.addEventListener('favorites:updated', (event) => {
    document.querySelectorAll('[data-favorites-share]').forEach((shareBlock) => {
      shareBlock.dataset.shareUrl = event.detail.shareUrl;
      if (shareBlock.querySelector('[data-share-toggle]')?.getAttribute('aria-expanded') === 'true') {
        prepareShareLinks(shareBlock);
      }
    });
  });
})();
