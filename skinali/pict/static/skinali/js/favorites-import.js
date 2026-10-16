(async () => {
  const form = document.querySelector('[data-favorites-import-form]');
  if (!form) {
    return;
  }

  try {
    // Сохранение выполняется отдельным POST с CSRF-токеном после загрузки ссылки.
    const response = await fetch(form.action, {
      method: 'POST',
      credentials: 'same-origin',
      body: new FormData(form),
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const result = await response.json();
    // Убираем исходную ссылку из текущей записи истории, чтобы «Назад» не повторял импорт.
    window.location.replace(result.redirect_url);
  } catch (error) {
    document.querySelector('[data-favorites-import-status]').textContent =
      'Не удалось сохранить подборку. Проверьте соединение и повторите добавление.';
    form.hidden = false;
    document.dispatchEvent(new CustomEvent('site:toast', {
      detail: { message: 'Проверьте интернет-соединение', kind: 'error' }
    }));
  }
})();
