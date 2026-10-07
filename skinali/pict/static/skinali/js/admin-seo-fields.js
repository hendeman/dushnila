(() => {
  'use strict';

  const initializeCounters = (root) => {
    root.querySelectorAll('[data-seo-counter]').forEach((field, index) => {
      if (field.dataset.seoCounterInitialized === 'true') {
        return;
      }
      field.dataset.seoCounterInitialized = 'true';

      let help = document.getElementById(`${field.id}_helptext`);
      if (!help) {
        help = document.createElement('div');
        help.className = 'help';
        const container = field.closest('.flex-container') || field;
        container.after(help);
      }

      const counter = document.createElement('span');
      counter.id = `${field.id || `admin-seo-field-${index}`}_counter`;
      counter.className = 'admin-seo-counter';
      counter.setAttribute('role', 'status');
      counter.setAttribute('aria-live', 'polite');
      counter.setAttribute('aria-atomic', 'true');
      help.append(counter);

      const describedBy = (field.getAttribute('aria-describedby') || '')
        .split(/\s+/).filter(Boolean);
      if (!describedBy.includes(counter.id)) {
        describedBy.push(counter.id);
      }
      field.setAttribute('aria-describedby', describedBy.join(' '));

      const updateCounter = () => {
        // Считаем Unicode-символы, а не UTF-16 единицы; пробелы учитываются.
        counter.textContent = `Символов: ${Array.from(field.value || '').length}.`;
      };
      field.addEventListener('input', updateCounter);
      field.addEventListener('change', updateCounter);
      if (field.form) {
        field.form.addEventListener('reset', () => setTimeout(updateCounter, 0));
      }
      updateCounter();
    });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => initializeCounters(document));
  } else {
    initializeCounters(document);
  }
  document.addEventListener('formset:added', (event) => initializeCounters(event.target));
})();
