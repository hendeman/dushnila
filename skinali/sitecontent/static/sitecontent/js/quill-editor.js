(() => {
  'use strict';

  const initialize = () => {
    if (!window.Quill) return;
    document.querySelectorAll('[data-quill-field]').forEach((field) => {
      if (field.dataset.initialized) return;
      field.dataset.initialized = 'true';
      const textarea = field.querySelector('textarea');
      const target = field.querySelector('[data-quill-editor]');
      const picker = field.querySelector('[data-quill-image]');
      const status = field.querySelector('[data-quill-status]');
      const form = field.closest('form');
      let uploading = false;

      const Font = Quill.import('attributors/class/font');
      Font.whitelist = field.dataset.fonts.split(',');
      const Color = Quill.import('attributors/class/color');
      Color.whitelist = field.dataset.colors.split(',');
      const Background = Quill.import('attributors/class/background');
      Background.whitelist = field.dataset.backgrounds.split(',');
      Quill.register(Font, true);
      Quill.register(Color, true);
      Quill.register(Background, true);
      const editor = new Quill(target, {
        theme: 'snow',
        placeholder: 'Напишите текст статьи…',
        formats: ['header', 'bold', 'italic', 'underline', 'strike', 'list', 'blockquote',
          'link', 'image', 'align', 'indent', 'font', 'size', 'color', 'background'],
        modules: {
          toolbar: {
            container: [
              [{header: [2, 3, false]}],
              [{font: [false, ...Font.whitelist]}, {size: ['small', false, 'large', 'huge']}],
              ['bold', 'italic', 'underline', 'strike'],
              [{color: [false, ...Color.whitelist]}, {background: [false, ...Background.whitelist]}],
              [{list: 'ordered'}, {list: 'bullet'}, 'blockquote'],
              [{align: []}, {indent: '-1'}, {indent: '+1'}],
              ['link', 'image', 'clean'],
            ],
            handlers: {image: () => { if (!uploading) picker.click(); }},
          },
          history: {userOnly: true},
        },
      });
      editor.setContents(editor.clipboard.convert({html: textarea.value}), 'silent');
      textarea.hidden = true;
      const content = target.querySelector('.ql-editor');
      content.setAttribute('aria-label', 'Текст статьи');
      content.setAttribute('aria-multiline', 'true');
      content.setAttribute('role', 'textbox');
      content.setAttribute('spellcheck', 'true');
      const sync = () => { textarea.value = editor.getSemanticHTML(); };
      editor.on('text-change', sync);

      const labels = {bold: 'Полужирный', italic: 'Курсив', underline: 'Подчёркнутый',
        strike: 'Зачёркнутый', blockquote: 'Цитата', link: 'Ссылка', image: 'Загрузить изображение',
        clean: 'Сбросить оформление', header: 'Заголовок', font: 'Шрифт', size: 'Размер текста',
        color: 'Цвет текста', background: 'Выделение маркером',
        align: 'Выравнивание', list: 'Список', indent: 'Отступ'};
      const toolbar = field.querySelector('.ql-toolbar');
      toolbar.querySelectorAll('button, .ql-picker').forEach((element) => {
        const key = Object.keys(labels).find((name) => element.classList.contains(`ql-${name}`));
        if (key) {
          element.setAttribute('title', labels[key]);
          element.setAttribute('aria-label', labels[key]);
        }
      });
      const backgroundLabels = {yellow: 'Жёлтый', green: 'Зелёный', blue: 'Голубой',
        pink: 'Розовый', orange: 'Оранжевый'};
      toolbar.querySelectorAll('.ql-background .ql-picker-item').forEach((element) => {
        const label = backgroundLabels[element.dataset.value] || 'Убрать выделение';
        element.setAttribute('title', label);
        element.setAttribute('aria-label', label);
      });
      field.querySelector('.ql-tooltip input[data-link]')?.setAttribute('placeholder', 'https://example.com');

      const uploadImage = async (file, range) => {
        if (uploading) return;
        if (file.size > 5 * 1024 * 1024) {
          status.textContent = 'Изображение должно быть не больше 5 МБ.';
          return;
        }
        uploading = true;
        status.textContent = 'Изображение загружается…';
        editor.enable(false);
        try {
          const data = new FormData();
          data.append('image', file);
          const response = await fetch(field.dataset.uploadUrl, {
            method: 'POST', body: data, credentials: 'same-origin',
            headers: {'X-CSRFToken': form.querySelector('[name="csrfmiddlewaretoken"]').value},
          });
          if (!response.headers.get('Content-Type')?.includes('application/json')) {
            throw new Error('Войдите в админку и повторите загрузку.');
          }
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || 'Не удалось загрузить изображение.');
          const index = Math.min(range?.index ?? editor.getLength() - 1, editor.getLength() - 1);
          editor.enable(true);
          editor.insertEmbed(index, 'image', result.url, 'user');
          editor.getLeaf(index)[0]?.domNode?.setAttribute('alt', 'Изображение к статье');
          sync();
          editor.setSelection(index + 1, 0, 'silent');
          status.textContent = 'Изображение добавлено.';
        } catch (error) {
          status.textContent = error.message || 'Не удалось загрузить изображение.';
        } finally {
          uploading = false;
          editor.enable(true);
          picker.value = '';
        }
      };

      picker.addEventListener('change', () => {
        if (picker.files[0]) uploadImage(picker.files[0], editor.getSelection());
      });
      // Вставка файла и перетягивание используют тот же защищённый серверный маршрут.
      content.addEventListener('paste', (event) => {
        const file = [...(event.clipboardData?.files || [])].find((item) => item.type.startsWith('image/'));
        if (file) {
          event.preventDefault();
          event.stopImmediatePropagation();
          uploadImage(file, editor.getSelection());
        }
      }, true);
      content.addEventListener('dragover', (event) => {
        if (event.dataTransfer?.types.includes('Files')) event.preventDefault();
      });
      content.addEventListener('drop', (event) => {
        if (event.dataTransfer?.files.length) {
          event.preventDefault();
          event.stopImmediatePropagation();
          uploadImage(event.dataTransfer.files[0], editor.getSelection());
        }
      }, true);
      // Скрытое обязательное textarea проверяет сервер; иначе браузер не сможет дать ему фокус.
      textarea.required = false;
      form.addEventListener('submit', (event) => {
        sync();
        if (uploading) {
          event.preventDefault();
          event.stopImmediatePropagation();
          status.textContent = 'Дождитесь загрузки изображения и сохраните статью.';
        }
      }, true);
    });
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
  else initialize();
})();
