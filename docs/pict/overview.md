# Приложение `pict`

## Назначение

Единственное прикладное Django-приложение проекта. Отвечает за хранение изображений и их классификацию, публичный поиск, каталог, избранное и фотогалерею готовых работ, а также управление данными через Django Admin.

## Карта модулей

| Модуль | Ответственность |
|---|---|
| [models.py](models.md) | `Pict`, `FinishedWork`, `Category`, `Color`, `TagPict` и связи ORM |
| [views.py](views.md) | поиск, каталог, готовые работы, избранное, фильтрация, теги, статические страницы и 404 |
| [urls.py](urls.md) | публичные URL приложения |
| [forms.py](forms.md) | форма `PictAdminForm` для поля номера изображения |
| [admin.py](admin.md) | таблицы, фильтры, миниатюры и регистрация моделей в admin |
| [apps.py](apps.md) | конфигурация приложения |
| [tests.py](tests.md) | автоматические тесты каталога, избранного и готовых работ |
| [migrations](../migrations/README.md) | история схемы БД |

## Связанные ресурсы

- Шаблоны: `skinali/pict/templates/pict/`.
- CSS, JavaScript и favicon: `skinali/pict/static/skinali/`.
- Загруженные изображения каталога: `skinali/media/photos/`.
- Фотографии готовых работ: `skinali/media/finished_works/`.
- Подключение приложения: [project/settings.md](../project/settings.md).

## Направление зависимостей

`urls.py → views.py → models.py`; отдельно `admin.py → forms.py → models.py`. Шаблоны потребляют контекст из `views.py`.
