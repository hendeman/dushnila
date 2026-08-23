# AGENTS.md — навигация по проекту Skinali

Этот файл в корне репозитория — обязательная первая точка входа для ИИ-агента. Проект представляет собой Django-сайт каталога изображений: посетитель ищет изображение по номеру или тегу, просматривает каталог, фильтрует его по категории, цвету и тегу, ведет персональное избранное в Django-сессии и смотрит фотогалерею готовых работ; контент редактируется через Django Admin.

## Порядок работы для ИИ-агента

1. В начале каждой новой задачи пользователя сначала заново прочитать этот файл, даже если он уже читался в текущей сессии.
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
| Корневые URL, admin, debug toolbar, обработчик 404 | [project/urls.md](docs/project/urls.md) | [pict/urls.md](docs/pict/urls.md), [pict/views.md](docs/pict/views.md) |
| Модели изображений, категорий, цветов и тегов | [pict/models.md](docs/pict/models.md) | [migrations/README.md](docs/migrations/README.md) |
| Готовые работы, их связь с каталогом и публичная фотогалерея | [pict/models.md](docs/pict/models.md) | [pict/views.md](docs/pict/views.md), [pict/admin.md](docs/pict/admin.md), [pict/urls.md](docs/pict/urls.md) |
| Поиск, каталог, фильтры, пагинация, контекст шаблонов | [pict/views.md](docs/pict/views.md) | [pict/models.md](docs/pict/models.md), [pict/urls.md](docs/pict/urls.md) |
| Избранное, Django-сессия, кнопка в модальной галерее | [pict/views.md](docs/pict/views.md) | [pict/urls.md](docs/pict/urls.md), [pict/tests.md](docs/pict/tests.md) |
| URL приложения `pict` | [pict/urls.md](docs/pict/urls.md) | [pict/views.md](docs/pict/views.md) |
| Форма добавления изображения | [pict/forms.md](docs/pict/forms.md) | [pict/models.md](docs/pict/models.md), [pict/admin.md](docs/pict/admin.md) |
| Административная панель | [pict/admin.md](docs/pict/admin.md) | [pict/forms.md](docs/pict/forms.md), [pict/models.md](docs/pict/models.md) |
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
| `skinali/pict/admin.py` | [pict/admin.md](docs/pict/admin.md) |
| `skinali/pict/urls.py` | [pict/urls.md](docs/pict/urls.md) |
| `skinali/pict/views.py` | [pict/views.md](docs/pict/views.md) |
| `skinali/pict/tests.py` | [pict/tests.md](docs/pict/tests.md) |
| `skinali/pict/migrations/*.py` | [migrations/README.md](docs/migrations/README.md) |
| Пустые `__init__.py` | [architecture.md](docs/architecture.md) |

## Границы документации

Сейчас подробно документируются Python-модули. HTML-шаблоны, CSS, JavaScript, изображения, SQLite-файл и зависимости перечислены в архитектурном обзоре только как связанные ресурсы. Если задача напрямую касается их содержимого, агент должен открыть соответствующий исходный файл.


Проверять в браузере ничего не нужно.
Если будешь добавлять комментарии в коде, то пиши это на русском языке.
