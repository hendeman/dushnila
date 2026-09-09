document.addEventListener('DOMContentLoaded', () => {
  if (typeof HTMLDialogElement === 'undefined') {
    return;
  }

  const dialog = document.createElement('dialog');
  dialog.className = 'admin-image-preview-dialog';
  dialog.setAttribute('aria-label', 'Просмотр изображения');
  dialog.innerHTML = `
    <div class="admin-image-preview-dialog__viewer">
      <button class="admin-image-preview-dialog__close" type="button" aria-label="Закрыть">&times;</button>
      <img class="admin-image-preview-dialog__image" alt="">
    </div>
  `;
  document.body.appendChild(dialog);

  const image = dialog.querySelector('.admin-image-preview-dialog__image');
  const closeButton = dialog.querySelector('.admin-image-preview-dialog__close');

  document.addEventListener('click', (event) => {
    const link = event.target.closest('[data-image-preview]');
    if (!link) {
      return;
    }

    event.preventDefault();
    const thumbnail = link.querySelector('img');
    image.src = link.href;
    image.alt = thumbnail ? thumbnail.alt : '';
    if (!dialog.open) {
      dialog.showModal();
    }
  });

  closeButton.addEventListener('click', () => dialog.close());

  dialog.addEventListener('click', (event) => {
    if (
      event.target === dialog ||
      event.target.classList.contains('admin-image-preview-dialog__viewer')
    ) {
      dialog.close();
    }
  });

  dialog.addEventListener('close', () => {
    image.removeAttribute('src');
    image.alt = '';
  });
});
