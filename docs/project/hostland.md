# Развёртывание на Hostland

Полная пошаговая инструкция со скриншотами и описанием production-настроек: [«Развёртывание сайта Odium на Hostland»](<../Инструкция по деплою Odium на Hostland.docx>).

## Текущее окружение preview

До подключения основного домена проект проверяется на техническом HTTP-адресе Hostland:

- URL: `http://host1889656.hostland.pro/`;
- Python: `3.11`;
- каталог приложения: `/home/host1889656/host1889656.hostland.pro/projects/odium/`;
- virtualenv: `/home/host1889656/host1889656.hostland.pro/venv/python_3.11/`;
- публичные файлы: `/home/host1889656/host1889656.hostland.pro/projects/odium/public/`;
- журнал Passenger: `/home/host1889656/passenger_log`;
- перезапуск: изменение `projects/odium/tmp/restart.txt`.

Preview работает с `DJANGO_ENVIRONMENT=preview`: отладка и инструменты разработки выключены, требуется отдельный секрет, а технический домен закрывается от индексации заголовком `X-Robots-Tag` и полным `Disallow` в `robots.txt`. Поскольку технический адрес не поддерживает HTTPS, на нём используются только тестовые данные и пароли.

## Основное production-приложение

Для `odium.by` создан отдельный сайт Hostland с собственным каталогом и отдельным Python-приложением. Это необходимо, чтобы основной домен мог получить собственный SSL-сертификат и не зависел от технического сайта:

- временный адрес проверки: `http://odium.by.host1889656.serv11.hostland.pro/`;
- каталог приложения: `/home/host1889656/odium.by/projects/odium/`;
- virtualenv: `/home/host1889656/odium.by/venv/python_3.11/`;
- публичные файлы: `/home/host1889656/odium.by/projects/odium/public/`;
- перезапуск: изменение `/home/host1889656/odium.by/projects/odium/tmp/restart.txt`.

До выпуска SSL приложение оставалось в профиле `preview` с выключенным `DJANGO_SECURE_SSL_REDIRECT`. После проверки сертификата основное приложение переведено в `production`: разрешены только `odium.by` и `www.odium.by`, публичный origin равен `https://odium.by`, а CSRF-origin содержат оба HTTPS-адреса. `DJANGO_STATIC_ROOT` и `DJANGO_MEDIA_ROOT` указывают на `public/static` и `public/media` именно внутри каталога `odium.by`.

Перед переключением DNS проверяются оба виртуальных хоста напрямую на IP Hostland `185.26.122.11`. И `odium.by`, и `www.odium.by` должны отдавать приложение, пока публичный DNS ещё направлен на прежний сервер. После копирования базы вместе с `public/media` кеш `sorl-thumbnail` не очищается: записи базы и перенесённые миниатюры остаются согласованными.

DNS продолжает обслуживаться внешними серверами `ns1.activeby.net` и `ns2.activeby.net`. В зоне Activeby настроены отдельные A-записи `odium.by` и `www.odium.by` на `185.26.122.11`; смена NS для работы сайта не потребовалась. Обычный сертификат Let's Encrypt заказан в Hostland на `www.odium.by` и покрывает адреса с `www` и без него. Wildcard `*.odium.by` при внешних NS использовать нельзя.

## Размещение файлов

Содержимое локального каталога `skinali/` размещается непосредственно в `projects/odium/`, чтобы `manage.py` находился по адресу `projects/odium/manage.py`. Созданные Hostland каталоги `public/` и `tmp/` сохраняются.

Локальная база `skinali/db.sqlite3` переносится в `projects/odium/db.sqlite3`. Исходные файлы из `skinali/media/` переносятся в `projects/odium/public/media/`; производный каталог `media/cache/thumbnails/` можно не переносить, поскольку `sorl-thumbnail` создаёт превью заново.

`.env.preview.example` копируется в `projects/odium/.env` и получает уникальный `DJANGO_SECRET_KEY`. Права на `.env` и SQLite должны разрешать чтение и запись только владельцу приложения. Настройки `DJANGO_STATIC_ROOT` и `DJANGO_MEDIA_ROOT` направляют файлы в публичный каталог Hostland.

## Первичная установка

После загрузки файлов через Web SSH:

```console
source /home/host1889656/host1889656.hostland.pro/venv/python_3.11/bin/activate
cd /home/host1889656/host1889656.hostland.pro/projects/odium
python -m pip install -r requirements-production.txt
python manage.py check
python manage.py migrate
python manage.py thumbnail clear
python manage.py collectstatic --noinput
touch tmp/restart.txt
```

`requirements-production.txt` не устанавливает `django-extensions` и Debug Toolbar. Он устанавливает Linux-wheel `pysqlite3-binary`, потому что системная SQLite 3.26 на текущем сервере Hostland ниже требуемой Django 5.2 версии 3.31; настройки автоматически подключают совместимый драйвер. Миграции выполняются даже при переносе актуальной SQLite: команда безопасно применит только отсутствующие изменения. Поскольку производные файлы `media/cache/thumbnails/` не переносятся, `thumbnail clear` удаляет из перенесённой SQLite устаревшие ссылки на локальный кеш; исходные изображения команда не затрагивает, а миниатюры создаются заново при первом открытии соответствующих страниц. `collectstatic` собирает `/static/` в `public/static/`; `/media/` уже располагается под `public/media/`.

На тестовом аккаунте Hostland SSH недоступен до оплаты. Файловый менеджер позволяет загрузить код, базу, media и создать `.env`, но не заменяет установку Python-зависимостей: перенос локального Windows virtualenv недопустим из-за платформенных компонентов Pillow. Поддерживаемый вариант до оплаты — попросить службу поддержки Hostland выполнить перечисленные команды в уже созданном `python_3.11` virtualenv. Если поддержка не выполняет команды на тестовом аккаунте, полный запуск откладывается до включения SSH; вендоринг неподтверждённых серверных бинарных пакетов не используется.

## Переход на production

После подключения `odium.by` и SSL файл `.env` получает настройки из `.env.production.example`: `DJANGO_ENVIRONMENT=production`, разрешённые host `odium.by,www.odium.by`, публичный origin `https://odium.by`, HTTPS CSRF-origin и включённый SSL-redirect. TLS завершается на контролируемом nginx Hostland, поэтому для правильного распознавания HTTPS требуется `DJANGO_TRUST_X_FORWARDED_PROTO=True`; значение `False` создаёт циклический редирект HTTPS на тот же URL. `DJANGO_SECURE_HSTS_SECONDS` остаётся равным нулю, поскольку Hostland уже отправляет `Strict-Transport-Security: max-age=31536000` на уровне nginx; предупреждение `security.W004` команды `check --deploy` при такой схеме ожидаемо. Затем выполняются `check --deploy`, `collectstatic` и перезапуск приложения.

Контрольная production-проверка должна подтверждать:

- постоянный редирект HTTP на HTTPS без цикла;
- код `200` для `https://odium.by/` и `https://www.odium.by/`;
- отсутствие preview-заголовка `X-Robots-Tag: noindex, nofollow`;
- `Secure` у CSRF-cookie;
- открытый production-вариант `robots.txt`, sitemap с URL от `https://odium.by` и корректный ответ `404`;
- доступность файлов `/static/` и `/media/` по HTTPS.

При переключении основного домена cron доставки заявок также переводится на отдельное приложение `odium.by`:

```console
/home/host1889656/odium.by/venv/python_3.11/bin/python /home/host1889656/odium.by/projects/odium/manage.py process_contact_deliveries
```

Старый технический cron нельзя оставлять активным одновременно с новым после начала приёма заявок: приложения используют разные копии SQLite, поэтому обработчик должен запускаться только для актуальной базы основного сайта.

Команду доставки заявок можно проверить на preview только с тестовыми данными. После заполнения Telegram-настроек и успешного ручного запуска в панели Hostland создаётся «Произвольная команда» с периодичностью раз в минуту и отключённым почтовым отчётом:

```console
/home/host1889656/host1889656.hostland.pro/venv/python_3.11/bin/python /home/host1889656/host1889656.hostland.pro/projects/odium/manage.py process_contact_deliveries
```

Абсолютный путь к интерпретатору исключает зависимость cron от активации virtualenv. До включения production и HTTPS через технический HTTP-адрес отправляются только тестовые заявки.

## Источники

- [Инструкция Hostland по Django](https://www.hostland.ru/ru/docs/useful/ustanovka-freimvorka-django-i-nastroika-otobrazheniya-staticheskikh-failov)
- [Инструкция Hostland по cron](https://www.hostland.ru/ru/docs/useful/kak-ispolzovat-cron-i-vse-chto-s-nim-svyazano-u-nas-na-khostinge)
- [Инструкция Hostland по SSL](https://www.hostland.ru/ru/docs/services/besplatnyi-ssl-sertifikat)

## Автоматическое обновление production из GitHub

Production обновляется после каждого push в `master`, если тесты успешны и repository variable `PRODUCTION_DEPLOY_ENABLED` равна `true`. Workflow создаёт резервные копии кода и SQLite, сохраняет `.env`, media и production-базу, применяет миграции, собирает статику, перезапускает Passenger и выполняет health-check.

Полная отдельная инструкция по созданию SSH-ключа, GitHub Environment и secrets, первому запуску, ежедневной работе, отключению и диагностике: [«Автоматическое обновление Odium на Hostland через GitHub Actions»](github-actions-hostland.md).
