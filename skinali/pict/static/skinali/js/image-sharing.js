(() => {
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

  function prepareShareLinks(shareBlock) {
    const shareData = shareBlock.dataset.shareKind === 'favorites'
      ? getFavoritesShareData(shareBlock)
      : getImageShareData(shareBlock);
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

  document.addEventListener('click', (event) => {
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
