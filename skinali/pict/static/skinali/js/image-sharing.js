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

  function getFavoritesShareData() {
    const imageNumbers = Array.from(document.querySelectorAll('[data-favorite-row]'))
      .map((row) => row.dataset.imageNumber)
      .filter(Boolean);
    if (!imageNumbers.length) {
      return null;
    }

    const title = `Избранные изображения: ${imageNumbers.map((number) => `№${number}`).join(', ')}`;
    return {
      sharedUrl: '',
      title,
      message: title
    };
  }

  function prepareShareLinks(shareBlock) {
    const shareData = shareBlock.dataset.shareKind === 'favorites'
      ? getFavoritesShareData()
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
})();
