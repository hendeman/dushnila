# `skinali/skinali/settings.py`

## Назначение

Центральная конфигурация Django-проекта.

## Ключевые настройки

| Область | Текущее значение |
|---|---|
| Django | проект создан на Django `4.1.5` |
| База | SQLite: `skinali/db.sqlite3` |
| Сессии | подписанные cookies: `django.contrib.sessions.backends.signed_cookies` |
| Язык | `ru-ru` |
| Часовой пояс Django | `UTC` |
| `USE_TZ` | `True` |
| Разрешенные хосты | только `127.0.0.1` |
| Режим отладки | `DEBUG = True` |
| Корневой URLconf | `skinali.urls` |
| WSGI | `skinali.wsgi.application` |
| Медиаданные | URL `/media/`, каталог `skinali/media/` |
| Статика | URL `static/`, `STATIC_ROOT` указывает в соседний `pict/static` относительно `BASE_DIR` |
| Первичный ключ по умолчанию | `BigAutoField` |

## Установленные приложения

Помимо стандартных приложений Django зарегистрированы:

- `pict.apps.PictConfig` — каталог изображений;
- `django_extensions`;
- `debug_toolbar`.

В конце middleware подключен `debug_toolbar.middleware.DebugToolbarMiddleware`. `INTERNAL_IPS` содержит `127.0.0.1`.

## Шаблоны

`APP_DIRS = True`, поэтому Django ищет шаблоны внутри приложений. Дополнительные каталоги в `TEMPLATES[0]['DIRS']` не заданы. Используются стандартные context processors для debug, request, auth и messages.

## Сессии

`SESSION_ENGINE` использует backend `django.contrib.sessions.backends.signed_cookies`. Данные сессии подписываются Django и хранятся в cookie браузера, поэтому действия с избранным не записывают таблицу `django_session` в SQLite. Подпись защищает данные от незаметной подмены, но не шифрует их.

Такое хранилище подходит для небольшого списка ID изображений. Следует учитывать ограничение браузера на размер cookie (обычно около 4 КБ), отсутствие синхронизации между браузерами и устройствами и удаление избранного при очистке cookies.

## Зависимости

- `pathlib.Path` вычисляет `BASE_DIR`.
- `os.path.join` формирует пути статики и media.
- Корневая маршрутизация описана в [urls.md](urls.md).

## Особенности и риски

- `SECRET_KEY` хранится непосредственно в репозитории.
- `DEBUG=True`, узкий `ALLOWED_HOSTS` и SQLite соответствуют локальной разработке, не production-конфигурации.
- Часовой пояс среды пользователя может отличаться от Django `TIME_ZONE='UTC'`.
- Значение `STATIC_ROOT` вычисляется как каталог вне `BASE_DIR`; перед изменением сборки статики нужно проверить фактический абсолютный путь.
- В сессию нельзя помещать большие данные: весь сериализованный набор отправляется с каждым HTTP-запросом внутри cookie.

## Когда читать исходник

При любых изменениях окружения, приложений, middleware, БД, шаблонов, локализации, безопасности, статики, media или развертывания.
