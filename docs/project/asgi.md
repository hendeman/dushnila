# `skinali/skinali/asgi.py`

## Назначение

ASGI-точка входа для асинхронно-совместимых серверов и инфраструктуры.

## Поведение

- Устанавливает `DJANGO_SETTINGS_MODULE=skinali.settings`, если переменная еще не определена.
- Создает экспортируемый объект `application` через `django.core.asgi.get_asgi_application()`.

## Зависимости

- Django.
- [settings.py](settings.md).

## Особенности

Дополнительные websocket-маршруты, Channels или собственный ASGI middleware не настроены.

## Когда читать исходник

При настройке ASGI-сервера, websocket/Channels, lifespan или асинхронного middleware.

