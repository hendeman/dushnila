document.querySelector('[data-search-back]')?.addEventListener('click', (event) => {
  if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) {
    return;
  }

  // При прямом открытии без истории ссылка ведёт в каталог.
  if (window.history.length > 1) {
    event.preventDefault();
    window.history.back();
  }
});
