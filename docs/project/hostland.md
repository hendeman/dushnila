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

### Журнал Passenger

Проверка по SSH 4 октября 2026 года подтвердила, что сообщения основного приложения также попадают в общий для аккаунта `/home/host1889656/passenger_log`: в текущем файле есть строки с production-каталогом `/home/host1889656/odium.by/`. Рядом находятся сжатые архивы `passenger_log.1.gz`, `.2.gz` и `.3.gz`, созданные 2, 3 и 4 октября примерно в 02:00 по московскому времени. По наблюдению ротация выполняется ежедневно; точное правило и срок хранения из доступной конфигурации Hostland подтвердить не удалось. Файлы `/home/host1889656/odium.by/logs/error_log` и `access_log` на момент проверки пусты; для диагностики Django на них не следует полагаться.

Для почтовых уведомлений об `ERROR`/`CRITICAL` заполните отдельные `LOG_ALERT_*` в закрытом `/home/host1889656/odium.by/projects/odium/.env`, затем установите `LOG_ALERT_ENABLED=True` и перезапустите Passenger. Набор полей и пределы отправки описаны в [настройках Django](settings.md#уведомления-об-ошибках-на-почту). Локальный `.env` не переносится автоматическим деплоем: серверный файл сохраняется отдельно. Почта заявок из admin от этих переменных не зависит.

### Оповещения о недоступности

По публичной документации Hostland, проверенной 4 октября 2026 года, в панели есть [настройки уведомлений аккаунта](https://www.hostland.ru/ru/platform-info), а [SMS-уведомления](https://www.hostland.ru/ru/docs/useful/dopolnitelnye-nastroiki-i-instrumenty) охватывают состояние аккаунта, баланс и домены. Настройка клиентского оповещения о недоступности конкретного сайта или сервера **виртуального хостинга** в этих материалах не описана; наличие такой функции в текущей панели без проверки аккаунта не подтверждено. [Инструкция Hostland по Uptime Kuma](https://www.hostland.ru/ru/docs/manual/uptimekuma) относится к самостоятельной установке мониторинга на VDS.

Для `odium.by` проверку внешней доступности следует выполнять сервисом вне инфраструктуры Hostland: запрашивать `https://odium.by/` по HTTPS, отслеживать неуспешные ответы и восстановление, отправлять уведомление на внешнюю почту или в мессенджер. Это обнаружит также отказ DNS, TLS или приложения. Почтовые уведомления Django об ошибках приложения не заменяют такую проверку: при недоступности сервера приложение может не выполнить отправку. Возможность уведомлений именно о сбоях оборудования Hostland нужно уточнять у поддержки для текущего тарифа.

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

`requirements-production.txt` не устанавливает `django-extensions` и Debug Toolbar. Он устанавливает Linux-wheel `pysqlite3-binary`, потому что системная SQLite 3.26 на текущем сервере Hostland ниже требуемой Django 5.2 версии 3.31; настройки автоматически подключают совместимый драйвер. Миграции выполняются даже при переносе актуальной SQLite: команда безопасно применит только отсутствующие изменения. Поскольку производные файлы `media/cache/thumbnails/` не переносятся, `thumbnail clear` удаляет из перенесённой SQLite устаревшие ссылки на локальный кеш; исходные изображения команда не затрагивает, а миниатюры создаются заново при первом открытии соответствующих страниц. `collectstatic` собирает `/static/` в `public/static/`, создаёт `staticfiles.json` и версии CSS, JavaScript и изображений с хешем содержимого в имени; `/media/` уже располагается под `public/media/`. Поэтому `collectstatic` должен завершиться успешно до перезапуска Passenger, а ручные параметры `?v=...` для очистки браузерного кеша не нужны.

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

При переключении основного домена cron доставки заявок также переведён на отдельное приложение `odium.by`. Проверка 4 октября 2026 года показала фактический запуск каждые пять минут; текущая строка выполняет команду ниже и дважды перенаправляет весь вывод в `/dev/null`:

```console
/home/host1889656/odium.by/venv/python_3.11/bin/python /home/host1889656/odium.by/projects/odium/manage.py process_contact_deliveries
```

Старый технический cron нельзя оставлять активным одновременно с новым: приложения используют разные копии SQLite, поэтому обработчик должен запускаться только для актуальной базы основного сайта.

Для ввода секретов подключений в admin задайте `LEAD_DELIVERY_ENCRYPTION_KEYS` в закрытом `.env` сервера и сохраните ключ отдельно от базы; инструкция — [Обработка заявок](../sitecontent/lead-processing.md). Telegram из прежнего окружения работает без нового ключа. Команду доставки заявок можно проверить на preview только с тестовыми данными. Исторически для технического сайта в панели Hostland создавалась «Произвольная команда» с периодичностью раз в минуту и отключённым почтовым отчётом:

```console
/home/host1889656/host1889656.hostland.pro/venv/python_3.11/bin/python /home/host1889656/host1889656.hostland.pro/projects/odium/manage.py process_contact_deliveries
```

Абсолютный путь к интерпретатору исключает зависимость cron от активации virtualenv. До включения production и HTTPS через технический HTTP-адрес отправляются только тестовые заявки.

## Источники

- [Инструкция Hostland по Django](https://www.hostland.ru/ru/docs/useful/ustanovka-freimvorka-django-i-nastroika-otobrazheniya-staticheskikh-failov)
- [Инструкция Hostland по cron](https://www.hostland.ru/ru/docs/useful/kak-ispolzovat-cron-i-vse-chto-s-nim-svyazano-u-nas-na-khostinge)
- [Инструкция Hostland по SSL](https://www.hostland.ru/ru/docs/services/besplatnyi-ssl-sertifikat)

## Автоматическое обновление production из GitHub

Production обновляется после каждого push в `master`, если тесты успешны и repository variable `PRODUCTION_DEPLOY_ENABLED` равна `true`. Workflow создаёт резервные копии кода и SQLite, сохраняет `.env`, media и production-базу, синхронизирует приложения `pict`, `quiz`, `sitecontent` и конфигурационный пакет `skinali`, применяет миграции, собирает статику, перезапускает Passenger и выполняет health-check. Каталог нового приложения создаётся при первом успешном обновлении и удаляется откатом, если этот деплой завершится ошибкой.

Полная отдельная инструкция по созданию SSH-ключа, GitHub Environment и secrets, первому запуску, ежедневной работе, отключению и диагностике: [«Автоматическое обновление Odium на Hostland через GitHub Actions»](github-actions-hostland.md).
