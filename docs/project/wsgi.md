# `skinali/skinali/wsgi.py`

## Назначение

WSGI-точка входа для традиционных Python web-серверов.

## Поведение

- Устанавливает `DJANGO_SETTINGS_MODULE=skinali.settings`, если переменная еще не определена.
- Создает экспортируемый объект `application` через `django.core.wsgi.get_wsgi_application()`.

## Зависимости

- Django.
- [settings.py](settings.md).

## Особенности

Пользовательский WSGI middleware отсутствует.

## Когда читать исходник

При настройке WSGI-сервера или оберток вокруг Django application.

