# Приложение `pict`

## Назначение

Единственное прикладное Django-приложение проекта. Отвечает за хранение изображений и их классификацию, публичный поиск, каталог, избранное, фотогалерею готовых работ и контактные заявки, а также управление данными через Django Admin.

## Карта модулей

| Модуль | Ответственность |
|---|---|
| [models.py](models.md) | `Pict`, `FinishedWork`, `ContactRequest`, `ContactRequestDelivery`, `Category`, `Color`, `TagPict` и связи ORM |
| [views.py](views.md) | поиск, каталог, готовые работы, избранное, фильтрация, теги, статические страницы и 404 |
| [urls.py](urls.md) | публичные URL приложения |
| [forms.py](forms.md) | `PictAdminForm` и публичные контактные формы с валидацией |
| [context_processors.py](context_processors.md) | глобальная форма обратного звонка для базового шаблона |
| [services/contact_delivery.py](services.md) | Telegram API, статусы, повторные попытки и обработка очереди доставок |
| [management/commands/process_contact_deliveries.py](management.md) | разовый запуск отправителя из cron или systemd timer |
| [admin.py](admin.md) | таблицы, фильтры, миниатюры и регистрация моделей в admin |
| [apps.py](apps.md) | конфигурация приложения |
| [tests.py](tests.md) | автоматические тесты каталога, избранного, готовых работ и контактных заявок |
| [migrations](../migrations/README.md) | история схемы БД |

## Связанные ресурсы

- Шаблоны: `skinali/pict/templates/pict/`.
- CSS, JavaScript и favicon: `skinali/pict/static/skinali/`.
- Загруженные изображения каталога: `skinali/media/photos/`.
- Фотографии готовых работ: `skinali/media/finished_works/`.
- Подключение приложения: [project/settings.md](../project/settings.md).

## Направление зависимостей

`urls.py → views.py → models.py`; отдельно `admin.py → forms.py → models.py`. Шаблоны потребляют контекст из `views.py`, а базовая форма обратного звонка поступает через `context_processors.py`. Очередь обрабатывается по цепочке `management command → contact_delivery service → ContactRequestDelivery → Telegram Bot API`.
