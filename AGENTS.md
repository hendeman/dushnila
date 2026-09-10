# AGENTS.md — навигация по проекту Skinali

Этот файл в корне репозитория — обязательная первая точка входа для ИИ-агента. Проект представляет собой Django-сайт каталога изображений: посетитель ищет опубликованное изображение по номеру, тегу или поисковому синониму, просматривает опубликованную часть каталога, фильтрует её по категории, цвету и тегу, ведет персональное избранное в Django-сессии и смотрит опубликованные элементы фотогалереи готовых работ; контент и его публикация редактируются через Django Admin.

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
| Разделение development/production и HTTPS-защита | [project/settings.md](docs/project/settings.md) | [project/urls.md](docs/project/urls.md), [architecture.md](docs/architecture.md) |
| Корневые URL, robots.txt, sitemap, admin, debug toolbar, обработчики 404 и 500 | [project/urls.md](docs/project/urls.md) | [project/settings.md](docs/project/settings.md), [pict/urls.md](docs/pict/urls.md), [pict/views.md](docs/pict/views.md) |
| Модели изображений, категорий, цветов, тегов и синонимов | [pict/models.md](docs/pict/models.md) | [pict/search.md](docs/pict/search.md), [migrations/README.md](docs/migrations/README.md) |
| Готовые работы, их связь с каталогом и публичная фотогалерея | [pict/models.md](docs/pict/models.md) | [pict/views.md](docs/pict/views.md), [pict/admin.md](docs/pict/admin.md), [pict/urls.md](docs/pict/urls.md) |
| Флаги публикации изображений и готовых работ | [pict/models.md](docs/pict/models.md) | [pict/views.md](docs/pict/views.md), [pict/admin.md](docs/pict/admin.md), [pict/forms.md](docs/pict/forms.md), [pict/tests.md](docs/pict/tests.md) |
| Нормализация, разделители, многословный поиск и релевантность | [pict/search.md](docs/pict/search.md) | [pict/forms.md](docs/pict/forms.md), [pict/models.md](docs/pict/models.md), [pict/views.md](docs/pict/views.md) |
| Каталог, фильтры, пагинация и контекст шаблонов | [pict/views.md](docs/pict/views.md) | [pict/search.md](docs/pict/search.md), [pict/urls.md](docs/pict/urls.md) |
| SEO публичных страниц, управляемые SEO-поля, robots.txt и XML-карта | [pict/views.md](docs/pict/views.md), [pict/models.md](docs/pict/models.md), [pict/admin.md](docs/pict/admin.md), [pict/sitemaps.md](docs/pict/sitemaps.md) | [project/urls.md](docs/project/urls.md), [project/settings.md](docs/project/settings.md) |
| Избранное, Django-сессия, кнопка в модальной галерее | [pict/views.md](docs/pict/views.md) | [pict/urls.md](docs/pict/urls.md), [pict/tests.md](docs/pict/tests.md) |
| URL приложения `pict`, добавление и удаление маршрутов | [pict/urls.md](docs/pict/urls.md) | [pict/views.md](docs/pict/views.md), [architecture.md](docs/architecture.md) |
| Форма добавления изображения | [pict/forms.md](docs/pict/forms.md) | [pict/models.md](docs/pict/models.md), [pict/admin.md](docs/pict/admin.md) |
| Контактные формы, заявки, валидация и антиспам | [pict/forms.md](docs/pict/forms.md) | [pict/models.md](docs/pict/models.md), [pict/views.md](docs/pict/views.md), [pict/admin.md](docs/pict/admin.md), [pict/context_processors.md](docs/pict/context_processors.md), [pict/urls.md](docs/pict/urls.md) |
| Список заявок в admin, статусы Telegram и отметка просмотра | [pict/admin.md](docs/pict/admin.md) | [pict/models.md](docs/pict/models.md), [pict/tests.md](docs/pict/tests.md), [migrations/README.md](docs/migrations/README.md) |
| Очередь и отправка контактных заявок в Telegram | [pict/services.md](docs/pict/services.md) | [pict/management.md](docs/pict/management.md), [pict/models.md](docs/pict/models.md), [project/settings.md](docs/project/settings.md), [pict/admin.md](docs/pict/admin.md) |
| Цена на странице дизайнера | [pict/views.md](docs/pict/views.md) | [pict/tests.md](docs/pict/tests.md) |
| Административная панель | [pict/admin.md](docs/pict/admin.md) | [pict/forms.md](docs/pict/forms.md), [pict/models.md](docs/pict/models.md) |
| Интеграции, вставки HTML/JS, выбор страниц и восстановление версий | [pict/integrations.md](docs/pict/integrations.md) | [pict/admin.md](docs/pict/admin.md), [pict/models.md](docs/pict/models.md), [pict/tests.md](docs/pict/tests.md) |
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
| `skinali/skinali/urls.py` | [project/urls.md](docs/project/urls.md) |
| `skinali/skinali/asgi.py` | [project/asgi.md](docs/project/asgi.md) |
| `skinali/skinali/wsgi.py` | [project/wsgi.md](docs/project/wsgi.md) |
| `skinali/pict/apps.py` | [pict/apps.md](docs/pict/apps.md) |
| `skinali/pict/models.py` | [pict/models.md](docs/pict/models.md) |
| `skinali/pict/forms.py` | [pict/forms.md](docs/pict/forms.md) |
| `skinali/pict/search.py` | [pict/search.md](docs/pict/search.md) |
| `skinali/pict/sitemaps.py` | [pict/sitemaps.md](docs/pict/sitemaps.md) |
| `skinali/pict/context_processors.py` | [pict/context_processors.md](docs/pict/context_processors.md) |
| `skinali/pict/services/contact_delivery.py` | [pict/services.md](docs/pict/services.md) |
| `skinali/pict/management/commands/process_contact_deliveries.py` | [pict/management.md](docs/pict/management.md) |
| `skinali/pict/admin.py` | [pict/admin.md](docs/pict/admin.md) |
| `skinali/pict/templatetags/integrations.py` | [pict/integrations.md](docs/pict/integrations.md) |
| `skinali/pict/urls.py` | [pict/urls.md](docs/pict/urls.md) |
| `skinali/pict/views.py` | [pict/views.md](docs/pict/views.md) |
| `skinali/pict/tests.py` | [pict/tests.md](docs/pict/tests.md) |
| `skinali/pict/migrations/*.py` | [migrations/README.md](docs/migrations/README.md) |
| `skinali/sitecontent/apps.py` | [sitecontent/overview.md](docs/sitecontent/overview.md) |
| `skinali/sitecontent/models.py` | [sitecontent/overview.md](docs/sitecontent/overview.md) |
| `skinali/sitecontent/admin.py` | [sitecontent/overview.md](docs/sitecontent/overview.md) |
| `skinali/sitecontent/context_processors.py` | [sitecontent/overview.md](docs/sitecontent/overview.md) |
| `skinali/sitecontent/tests.py` | [sitecontent/overview.md](docs/sitecontent/overview.md) |
| `skinali/sitecontent/migrations/*.py` | [migrations/README.md](docs/migrations/README.md) |
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
