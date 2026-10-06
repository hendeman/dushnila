# Quill 2.0.3

Локальные файлы официального пакета `quill@2.0.3`:

- https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/quill.js
- https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/quill.snow.css
- https://cdn.jsdelivr.net/npm/quill@2.0.3/LICENSE

Лицензия BSD-3-Clause сохранена рядом. Во время работы сайт не обращается к CDN.
В локальных копиях CSS и JavaScript удалены только комментарии `sourceMappingURL`:
карты исходников `.map` не поставляются, а `ManifestStaticFilesStorage` проверяет
ссылки на них при `collectstatic` и прекращает сборку, если файла нет.
Код редактора, оформление и лицензионные заголовки сохранены.
После обновления версии необходимо проверить экспорт/повторное редактирование HTML,
разрешённые классы, обработчики загрузки изображений и сборку статики в production-профиле.
