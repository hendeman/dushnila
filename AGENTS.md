# AGENTS.md — навигация по проекту Skinali

Этот файл в корне репозитория — обязательная первая точка входа для ИИ-агента. Проект представляет собой Django-сайт каталога изображений: посетитель ищет опубликованное изображение по номеру, тегу или поисковому синониму, просматривает опубликованную часть каталога, фильтрует её по категории, цвету и тегу, ведет персональное избранное в Django-сессии, смотрит опубликованные элементы фотогалереи готовых работ, читает статьи «Полезно знать» и проходит встроенный модальный квиз; контент, публикация, статьи с редактором Quill 2 и настройки квиза редактируются через Django Admin.

## Порядок работы для ИИ-агента

1. Используй этот файл как карту. Перечитывай только если задача сменила область или предыдущие инструкции не покрывают проблему.
2. Выбрать в таблице минимальный набор профильных документов.
3. Читать исходные `.py` только если документации недостаточно для конкретного изменения или нужно проверить актуальность реализации.
4. При изменении Python-кода одновременно обновить соответствующий документ в `docs/`.
5. Если меняются связи модулей, модели или маршруты, также обновить `docs/architecture.md` и эту карту.

Документация описывает текущее состояние кода, а не желаемое. Разделы «Особенности и риски» фиксируют существующее поведение и не означают, что его следует менять без запроса пользователя.

## Быстрая маршрутизация

| Задача | Сначала читать | Затем при необходимости |
|---|---|---|
| Понять устройство проекта целиком | [architecture.md](docs/architecture.md) | [pict/overview.md](docs/pict/overview.md) |
| Настройки Django, БД, язык, статика, media | [project/settings.md](docs/project/settings.md) | [project/urls.md](docs/project/urls.md) |
| Профили development/preview/production и HTTPS-защита | [project/settings.md](docs/project/settings.md) | [project/middleware.md](docs/project/middleware.md), [project/urls.md](docs/project/urls.md), [architecture.md](docs/architecture.md) |
| Журнал Passenger и почтовые уведомления об ошибках | [project/settings.md](docs/project/settings.md) | [project/hostland.md](docs/project/hostland.md), [architecture.md](docs/architecture.md) |
| Развёртывание на Hostland | [project/hostland.md](docs/project/hostland.md) | [project/settings.md](docs/project/settings.md), [project/wsgi.md](docs/project/wsgi.md), [pict/management.md](docs/pict/management.md) |
| Автоматический деплой из GitHub в production | [project/github-actions-hostland.md](docs/project/github-actions-hostland.md) | [project/hostland.md](docs/project/hostland.md), [project/settings.md](docs/project/settings.md) |
| Корневые URL, robots.txt, sitemap, admin, debug toolbar, обработчики 404 и 500 | [project/urls.md](docs/project/urls.md) | [project/settings.md](docs/project/settings.md), [pict/urls.md](docs/pict/urls.md), [pict/views.md](docs/pict/views.md) |
| Полноценная страница 404 с пользовательской картинкой, меню и подвалом; автономная страница 500 | [pict/views.md](docs/pict/views.md), [project/urls.md](docs/project/urls.md) | `skinali/pict/templates/pict/404.html`, `skinali/pict/static/skinali/css/not-found.css`, [pict/tests.md](docs/pict/tests.md), [architecture.md](docs/architecture.md) |
| Модели изображений, категорий, цветов, тегов и синонимов | [pict/models.md](docs/pict/models.md) | [pict/search.md](docs/pict/search.md), [migrations/README.md](docs/migrations/README.md) |
| Номер изображения, признак популярности, обязательное описание и формирование имени загружаемого файла | [pict/models.md](docs/pict/models.md) | [pict/forms.md](docs/pict/forms.md), [pict/admin.md](docs/pict/admin.md), [pict/tests.md](docs/pict/tests.md), [migrations/README.md](docs/migrations/README.md) |
| Готовые работы, имена файлов фото, admin-переименование, типы стекла/скинали, связь с каталогом и публичная фотогалерея | [pict/models.md](docs/pict/models.md) | [pict/forms.md](docs/pict/forms.md), [pict/views.md](docs/pict/views.md), [pict/admin.md](docs/pict/admin.md), [pict/tests.md](docs/pict/tests.md), [pict/urls.md](docs/pict/urls.md), [migrations/README.md](docs/migrations/README.md) |
| Флаги публикации изображений и готовых работ | [pict/models.md](docs/pict/models.md) | [pict/views.md](docs/pict/views.md), [pict/admin.md](docs/pict/admin.md), [pict/forms.md](docs/pict/forms.md), [pict/tests.md](docs/pict/tests.md) |
| Очистка старых фотографий при замене/удалении, миниатюр и накопившихся файлов без ссылок | [pict/photo-cleanup.md](docs/pict/photo-cleanup.md) | [pict/signals.md](docs/pict/signals.md), [pict/admin.md](docs/pict/admin.md), [pict/management.md](docs/pict/management.md), [pict/tests.md](docs/pict/tests.md) |
| Нормализация, разделители, многословный поиск и релевантность | [pict/search.md](docs/pict/search.md) | [pict/forms.md](docs/pict/forms.md), [pict/models.md](docs/pict/models.md), [pict/views.md](docs/pict/views.md) |
| Лемматизация `pymorphy3`, наиболее вероятный разбор, индекс лемм тегов/синонимов и его перестроение | [pict/search.md](docs/pict/search.md), [pict/models.md](docs/pict/models.md) | [pict/management.md](docs/pict/management.md), [pict/tests.md](docs/pict/tests.md), [project/dependencies.md](docs/project/dependencies.md), [migrations/README.md](docs/migrations/README.md) |
| Единая карточка «Настройки сайта», тематические группы параметров, глобальный переключатель поиска и ссылка из «Ключевых слов» | [sitecontent/overview.md](docs/sitecontent/overview.md), [pict/search.md](docs/pict/search.md) | [pict/admin.md](docs/pict/admin.md), [pict/views.md](docs/pict/views.md), [architecture.md](docs/architecture.md) |
| Каталог, фильтры, пагинация и контекст шаблонов | [pict/views.md](docs/pict/views.md) | [pict/search.md](docs/pict/search.md), [pict/urls.md](docs/pict/urls.md) |
| Общая пагинация каталога, тегов, готовых работ и статей, компактный ряд и кликабельные `...` | [pict/pagination.md](docs/pict/pagination.md) | [pict/views.md](docs/pict/views.md), [pict/tests.md](docs/pict/tests.md) |
| SEO публичных страниц, управляемые SEO-поля, robots.txt и XML-карта | [pict/views.md](docs/pict/views.md), [pict/models.md](docs/pict/models.md), [pict/admin.md](docs/pict/admin.md), [pict/sitemaps.md](docs/pict/sitemaps.md) | [pict/signals.md](docs/pict/signals.md), [project/urls.md](docs/project/urls.md), [project/settings.md](docs/project/settings.md) |
| Индивидуальная страница изображения, стабильный slug, похожие изображения и связанные готовые кухни; «В интерьере» в модальном окне каталога | [pict/views.md](docs/pict/views.md), [pict/models.md](docs/pict/models.md), [pict/urls.md](docs/pict/urls.md) | [pict/favorites.md](docs/pict/favorites.md), [pict/admin.md](docs/pict/admin.md), [pict/sitemaps.md](docs/pict/sitemaps.md), [pict/tests.md](docs/pict/tests.md), [migrations/README.md](docs/migrations/README.md) |
| Крупное превью для модального окна каталога и страницы изображения | [pict/views.md](docs/pict/views.md), [pict/urls.md](docs/pict/urls.md), [project/settings.md](docs/project/settings.md) | [pict/tests.md](docs/pict/tests.md), [architecture.md](docs/architecture.md) |
| Номер изображения в имени кешированных превью, общий backend, переход со старого кеша и восстановление пустых миниатюр после очистки | [pict/thumbnails.md](docs/pict/thumbnails.md) | [project/settings.md](docs/project/settings.md), [pict/photo-cleanup.md](docs/pict/photo-cleanup.md), [pict/views.md](docs/pict/views.md) |
| Избранное, лимит 50, подписанные ссылки без БД, частичный импорт, счётчики прогресса, повтор, полная очистка и Toast | [pict/favorites.md](docs/pict/favorites.md) | [pict/views.md](docs/pict/views.md), [pict/urls.md](docs/pict/urls.md), [pict/tests.md](docs/pict/tests.md) |
| URL приложения `pict`, включая `/designer/`, добавление и удаление маршрутов | [pict/urls.md](docs/pict/urls.md) | [pict/views.md](docs/pict/views.md), [architecture.md](docs/architecture.md) |
| Форма добавления изображения | [pict/forms.md](docs/pict/forms.md) | [pict/models.md](docs/pict/models.md), [pict/admin.md](docs/pict/admin.md) |
| Заказ из калькулятора: немедленное открытие формы, фоновая подготовка ссылки, статусы, тайм-аут 10 секунд и повтор, проверка, сохранение заявки и уведомления | [calculator/overview.md](docs/calculator/overview.md) | [pict/forms.md](docs/pict/forms.md), [pict/models.md](docs/pict/models.md), [pict/views.md](docs/pict/views.md), [pict/admin.md](docs/pict/admin.md), [pict/services.md](docs/pict/services.md), [sitecontent/lead-processing.md](docs/sitecontent/lead-processing.md) |
| Контактные формы, заявки, валидация и антиспам | [pict/forms.md](docs/pict/forms.md) | [pict/models.md](docs/pict/models.md), [pict/views.md](docs/pict/views.md), [pict/admin.md](docs/pict/admin.md), [pict/context_processors.md](docs/pict/context_processors.md), [pict/urls.md](docs/pict/urls.md) |
| Список заявок в admin, статусы доставок и отметка просмотра | [pict/admin.md](docs/pict/admin.md) | [pict/models.md](docs/pict/models.md), [pict/tests.md](docs/pict/tests.md), [migrations/README.md](docs/migrations/README.md) |
| Очередь и отправка контактных заявок в Telegram/email | [pict/services.md](docs/pict/services.md) | [pict/management.md](docs/pict/management.md), [pict/models.md](docs/pict/models.md), [project/settings.md](docs/project/settings.md), [pict/admin.md](docs/pict/admin.md) |
| Цена на странице дизайнера | [pict/views.md](docs/pict/views.md) | [pict/tests.md](docs/pict/tests.md) |
| Независимые таблицы под калькулятором только на странице «Цена», строки услуг с текстовой стоимостью, публикация и перетягивание в admin | [sitecontent/price-tables.md](docs/sitecontent/price-tables.md) | [sitecontent/overview.md](docs/sitecontent/overview.md), [calculator/overview.md](docs/calculator/overview.md), [pict/signals.md](docs/pict/signals.md), [migrations/README.md](docs/migrations/README.md) |
| Редактируемые подсказки «?» параметров и услуг калькулятора, скрытие пустых текстов на сайте | [calculator/overview.md](docs/calculator/overview.md) | [architecture.md](docs/architecture.md), [migrations/README.md](docs/migrations/README.md) |
| Публичная страница «Цена» (`/price/`), мгновенный расчёт в браузере, размеры панелей, округление общей площади до сотых перед стоимостью, услуги, подъём, акции и целый итог | [calculator/overview.md](docs/calculator/overview.md) | [sitecontent/overview.md](docs/sitecontent/overview.md), [pict/sitemaps.md](docs/pict/sitemaps.md), [project/urls.md](docs/project/urls.md), [architecture.md](docs/architecture.md) |
| Поделиться расчётом, подписанные ссылки без БД, восстановление параметров и актуальные тарифы | [calculator/overview.md](docs/calculator/overview.md) | [pict/favorites.md](docs/pict/favorites.md), [project/urls.md](docs/project/urls.md), [architecture.md](docs/architecture.md) |
| Административная панель | [pict/admin.md](docs/pict/admin.md) | [pict/forms.md](docs/pict/forms.md), [pict/models.md](docs/pict/models.md) |
| Админка калькулятора: отдельные «Настройки калькулятора» и «Тарифы и услуги», общий переключатель показа на сайте, прогрессивная скидка при площади больше 2 м² и маркетинговая скидка в процентах с описанием акции, общие услуги с CRUD/подписями/тарифами, индивидуальным максимумом количества, точностью дробного ввода до сотых и перетягиванием, единицы измерения, фиксированная плата за заказ и включённый режим, формула и проверочный расчёт; таблица правил лестницы 1–6 | [calculator/overview.md](docs/calculator/overview.md) | [pict/admin.md](docs/pict/admin.md), [project/settings.md](docs/project/settings.md), [project/urls.md](docs/project/urls.md), [sitecontent/overview.md](docs/sitecontent/overview.md), [architecture.md](docs/architecture.md), [migrations/README.md](docs/migrations/README.md) |
| Единая ширина SEO-полей admin, рекомендации длины и живые счётчики символов | [sitecontent/admin-seo.md](docs/sitecontent/admin-seo.md) | [pict/admin.md](docs/pict/admin.md), [sitecontent/overview.md](docs/sitecontent/overview.md), [sitecontent/articles.md](docs/sitecontent/articles.md) |
| Счётчик новых заявок в меню admin и массовая отметка просмотра | [pict/admin.md](docs/pict/admin.md) | [pict/models.md](docs/pict/models.md), [pict/tests.md](docs/pict/tests.md), [project/settings.md](docs/project/settings.md), [project/urls.md](docs/project/urls.md) |
| Порядок категорий и перетягивание в admin | [pict/admin.md](docs/pict/admin.md) | [pict/models.md](docs/pict/models.md), [pict/views.md](docs/pict/views.md), [pict/tests.md](docs/pict/tests.md), [migrations/README.md](docs/migrations/README.md) |
| Интеграции, вставки HTML/JS, выбор страниц и восстановление версий | [pict/integrations.md](docs/pict/integrations.md) | [pict/admin.md](docs/pict/admin.md), [pict/models.md](docs/pict/models.md), [pict/tests.md](docs/pict/tests.md) |
| Встроенный квиз, `#popup:skinali-quiz`, точные пути и маски страниц `/*`, кнопка запуска и её иконка, автопоказ, вопросы, ответы и заявки типа `quiz` | [quiz/overview.md](docs/quiz/overview.md) | [pict/forms.md](docs/pict/forms.md), [pict/models.md](docs/pict/models.md), [pict/services.md](docs/pict/services.md), [project/settings.md](docs/project/settings.md), [project/urls.md](docs/project/urls.md) |
| Обработка заявок, Telegram/email-подключения, получатели, секреты и тестовые отправки | [sitecontent/lead-processing.md](docs/sitecontent/lead-processing.md) | [pict/services.md](docs/pict/services.md), [pict/models.md](docs/pict/models.md), [pict/admin.md](docs/pict/admin.md), [pict/management.md](docs/pict/management.md) |
| Статьи «Полезно знать», Quill 2, очистка HTML/загрузок, отдельное поле адреса, стабильный slug и проверка его уникальности, публикация, пагинация и SEO | [sitecontent/articles.md](docs/sitecontent/articles.md) | [sitecontent/overview.md](docs/sitecontent/overview.md), [pict/photo-cleanup.md](docs/pict/photo-cleanup.md), [pict/sitemaps.md](docs/pict/sitemaps.md), [architecture.md](docs/architecture.md) |
| Управляемое меню, SEO постоянных страниц и будущие блоки сайта | [sitecontent/overview.md](docs/sitecontent/overview.md) | [pict/views.md](docs/pict/views.md), [pict/models.md](docs/pict/models.md), [project/settings.md](docs/project/settings.md), [architecture.md](docs/architecture.md) |
| Регистрация приложения | [pict/apps.md](docs/pict/apps.md) | [project/settings.md](docs/project/settings.md) |
| Тесты | [pict/tests.md](docs/pict/tests.md) | Документ изменяемого модуля |
| История схемы базы данных | [migrations/README.md](docs/migrations/README.md) | [pict/models.md](docs/pict/models.md) |
| `manage.py` и management-команды | [project/manage.md](docs/project/manage.md) | [project/settings.md](docs/project/settings.md) |
| ASGI-развертывание | [project/asgi.md](docs/project/asgi.md) | [project/settings.md](docs/project/settings.md) |
| WSGI-развертывание | [project/wsgi.md](docs/project/wsgi.md) | [project/settings.md](docs/project/settings.md) |

## Покрытие Python-файлов

| Исходник | Документация |
|---|---|
| `skinali/manage.py` | [project/manage.md](docs/project/manage.md) |
| `skinali/skinali/settings.py` | [project/settings.md](docs/project/settings.md) |
| `skinali/skinali/log_alerts.py`, `test_log_alerts.py` | [project/settings.md](docs/project/settings.md) |
| `skinali/skinali/admin_config.py` | [project/settings.md](docs/project/settings.md) |
| `skinali/skinali/admin_mixins.py` | [project/settings.md](docs/project/settings.md), [sitecontent/overview.md](docs/sitecontent/overview.md), [calculator/overview.md](docs/calculator/overview.md) |
| `skinali/skinali/admin_order.py` | [sitecontent/price-tables.md](docs/sitecontent/price-tables.md), [pict/admin.md](docs/pict/admin.md) |
| `skinali/skinali/admin_site.py` | [project/urls.md](docs/project/urls.md), [pict/admin.md](docs/pict/admin.md) |
| `skinali/skinali/middleware.py` | [project/middleware.md](docs/project/middleware.md) |
| `skinali/skinali/urls.py` | [project/urls.md](docs/project/urls.md) |
| `skinali/skinali/asgi.py` | [project/asgi.md](docs/project/asgi.md) |
| `skinali/skinali/wsgi.py` | [project/wsgi.md](docs/project/wsgi.md) |
| `skinali/pict/apps.py` | [pict/apps.md](docs/pict/apps.md) |
| `skinali/pict/models.py` | [pict/models.md](docs/pict/models.md) |
| `skinali/pict/forms.py` | [pict/forms.md](docs/pict/forms.md) |
| `skinali/pict/search.py` | [pict/search.md](docs/pict/search.md) |
| `skinali/pict/test_search_lemmas.py` | [pict/search.md](docs/pict/search.md), [pict/tests.md](docs/pict/tests.md) |
| `skinali/pict/page_paths.py` | [pict/integrations.md](docs/pict/integrations.md), [quiz/overview.md](docs/quiz/overview.md) |
| `skinali/pict/sitemaps.py` | [pict/sitemaps.md](docs/pict/sitemaps.md) |
| `skinali/pict/signals.py` | [pict/signals.md](docs/pict/signals.md) |
| `skinali/pict/context_processors.py` | [pict/context_processors.md](docs/pict/context_processors.md) |
| `skinali/pict/services/contact_delivery.py` | [pict/services.md](docs/pict/services.md) |
| `skinali/pict/services/favorites.py`, `test_favorites.py` | [pict/favorites.md](docs/pict/favorites.md), [pict/tests.md](docs/pict/tests.md) |
| `skinali/pict/services/photo_cleanup.py`, `test_photo_cleanup.py` | [pict/photo-cleanup.md](docs/pict/photo-cleanup.md), [pict/tests.md](docs/pict/tests.md) |
| `skinali/pict/services/telegram_delivery.py`, `email_delivery.py`, `delivery_messages.py`, `delivery_errors.py` | [pict/services.md](docs/pict/services.md) |
| `skinali/pict/management/commands/process_contact_deliveries.py` | [pict/management.md](docs/pict/management.md) |
| `skinali/pict/management/commands/rebuild_search_lemmas.py` | [pict/management.md](docs/pict/management.md), [pict/search.md](docs/pict/search.md) |
| `skinali/pict/management/commands/cleanup_unused_photos.py` | [pict/management.md](docs/pict/management.md), [pict/photo-cleanup.md](docs/pict/photo-cleanup.md) |
| `skinali/pict/admin.py` | [pict/admin.md](docs/pict/admin.md) |
| `skinali/pict/templatetags/integrations.py` | [pict/integrations.md](docs/pict/integrations.md) |
| `skinali/pict/templatetags/pagination.py` | [pict/pagination.md](docs/pict/pagination.md) |
| `skinali/pict/urls.py` | [pict/urls.md](docs/pict/urls.md) |
| `skinali/pict/views.py` | [pict/views.md](docs/pict/views.md) |
| `skinali/pict/thumbnails.py`, `test_thumbnails.py` | [pict/thumbnails.md](docs/pict/thumbnails.md), [pict/tests.md](docs/pict/tests.md) |
| `skinali/pict/tests.py` | [pict/tests.md](docs/pict/tests.md) |
| `skinali/pict/migrations/*.py` | [migrations/README.md](docs/migrations/README.md) |
| `skinali/sitecontent/apps.py` | [sitecontent/overview.md](docs/sitecontent/overview.md) |
| `skinali/sitecontent/models.py` | [sitecontent/overview.md](docs/sitecontent/overview.md), [sitecontent/articles.md](docs/sitecontent/articles.md), [sitecontent/lead-processing.md](docs/sitecontent/lead-processing.md), [sitecontent/price-tables.md](docs/sitecontent/price-tables.md) |
| `skinali/sitecontent/test_price_tables.py` | [sitecontent/price-tables.md](docs/sitecontent/price-tables.md) |
| `skinali/sitecontent/forms.py` | [sitecontent/articles.md](docs/sitecontent/articles.md), [sitecontent/lead-processing.md](docs/sitecontent/lead-processing.md), [sitecontent/price-tables.md](docs/sitecontent/price-tables.md) |
| `skinali/sitecontent/secrets.py`, `test_lead_processing.py` | [sitecontent/lead-processing.md](docs/sitecontent/lead-processing.md) |
| `skinali/sitecontent/views.py`, `urls.py`, `sitemaps.py`, `widgets.py`, `rich_text.py`, `article_media.py`, `test_articles.py` | [sitecontent/articles.md](docs/sitecontent/articles.md) |
| `skinali/sitecontent/querysets.py` | [sitecontent/articles.md](docs/sitecontent/articles.md), [pict/models.md](docs/pict/models.md) |
| `skinali/sitecontent/management/commands/cleanup_article_images.py` | [sitecontent/articles.md](docs/sitecontent/articles.md) |
| `skinali/sitecontent/admin.py` | [sitecontent/overview.md](docs/sitecontent/overview.md), [sitecontent/articles.md](docs/sitecontent/articles.md), [sitecontent/lead-processing.md](docs/sitecontent/lead-processing.md), [sitecontent/price-tables.md](docs/sitecontent/price-tables.md) |
| `skinali/sitecontent/admin_seo.py`, `test_admin_seo.py` | [sitecontent/admin-seo.md](docs/sitecontent/admin-seo.md) |
| `skinali/sitecontent/context_processors.py` | [sitecontent/overview.md](docs/sitecontent/overview.md) |
| `skinali/sitecontent/tests.py` | [sitecontent/overview.md](docs/sitecontent/overview.md) |
| `skinali/sitecontent/test_catalog_search_settings.py` | [sitecontent/overview.md](docs/sitecontent/overview.md), [pict/search.md](docs/pict/search.md) |
| `skinali/sitecontent/migrations/*.py` | [migrations/README.md](docs/migrations/README.md) |
| `skinali/quiz/apps.py` | [quiz/overview.md](docs/quiz/overview.md) |
| `skinali/calculator/apps.py`, `models.py`, `admin.py`, `tests.py` | [calculator/overview.md](docs/calculator/overview.md) |
| `skinali/calculator/public.py`, `views.py`, `urls.py`, `test_public.py`, `test_hints.py` | [calculator/overview.md](docs/calculator/overview.md) |
| `skinali/calculator/sharing.py`, `test_sharing.py`, `test_orders.py` | [calculator/overview.md](docs/calculator/overview.md) |
| `skinali/calculator/calculation.py`, `forms.py`, `widgets.py`, `test_calculation.py`, `test_services.py`, `test_units.py`, `test_promotions.py`, `templatetags/calculator_numbers.py` | [calculator/overview.md](docs/calculator/overview.md) |
| `skinali/calculator/migrations/*.py` | [calculator/overview.md](docs/calculator/overview.md), [migrations/README.md](docs/migrations/README.md) |
| `skinali/quiz/models.py` | [quiz/overview.md](docs/quiz/overview.md) |
| `skinali/quiz/forms.py` | [quiz/overview.md](docs/quiz/overview.md) |
| `skinali/quiz/context_processors.py` | [quiz/overview.md](docs/quiz/overview.md) |
| `skinali/quiz/views.py` | [quiz/overview.md](docs/quiz/overview.md) |
| `skinali/quiz/urls.py` | [quiz/overview.md](docs/quiz/overview.md) |
| `skinali/quiz/admin.py` | [quiz/overview.md](docs/quiz/overview.md) |
| `skinali/quiz/tests.py` | [quiz/overview.md](docs/quiz/overview.md) |
| `skinali/quiz/migrations/*.py` | [migrations/README.md](docs/migrations/README.md), [quiz/overview.md](docs/quiz/overview.md) |
| Пустые `__init__.py` | [architecture.md](docs/architecture.md) |

## Границы документации

Не читай все документы подряд; сначала определи минимальный нужный набор. Если увидишь несоответствия — сообщай об этом и предлагай исправления и доработки. Если всё очевидно и понятно — в конце каждого подхода к работе дополняй документацию в папке doc (актуализируй существующую, создавай новую)

Сейчас подробно документируются Python-модули. HTML-шаблоны, CSS, JavaScript, изображения, SQLite-файл и зависимости перечислены в архитектурном обзоре только как связанные ресурсы. Если задача напрямую касается их содержимого, агент должен открыть соответствующий исходный файл.


Комментарии в коде — на русском, только полезные.

В локальной среде сервер запускается на порту 8000.
Локальный сервер всегда считается уже поднятым на http://127.0.0.1:8000

Codex не должен запускать, перезапускать или останавливать dev-сервер без прямого запроса пользователя. Для проверки фронтенда использовать существующий сервер на 8000. Если он не отвечает в течение 5 секунд — сообщить об этом и продолжить без попытки запуска. Не запускать долгоживущие команды вроде manage.py runserver в foreground.

Browser-use / Playwright / in-app browser использовать только по прямой просьбе пользователя: «открой в браузере», «проверь визуально», «сделай скриншот», «протестируй фронт». Для обычных мелких HTML/CSS/JS-правок не запускать browser-use/Playwright автоматически; ограничиваться кодовой проверкой и сообщать, что визуальная проверка не выполнялась.

Не используй термин MVP при работе над новыми частями и функциями проекта. У нас нет задачи проверять гипотезы и делать минимальные жизнеспособные версии — мы сразу работаем в парадигме «делаем правильно, надолго и архитектурно устойчиво». Наши компоненты готовы к масштабированию, учитывают вопросы безопасности, переиспользования в других участках системы. Во время проектирования мы стараемся не обрезать функционал, а, наоборот, думать на несколько шагов вперёд. В случае чего, я самостоятельно обозначу границы ближайшей реализуемой версии.


При принятии продуктовых решений по коду, архитектуре и прочему — ориентируйся на то, что одномоментно сервером будут пользоваться 10-20 человек. Сейчас у нас одно ядро и 1 гиг оперативки — сигнализируй, когда увидишь, что этих мощностей недостаточно для нашего очередного нововведения.

При разработке используй DRY-подход. Прежде чем разрабатывать новую функцию или придумывать новый стиль — обязательно убедись в том, что чего-то похожего уже нет в проекте.

Выполняй все задачи строго в текущем основном контексте (main thread). Не делегируй подзадачи субагентам и не запускай форки/новые сессии
