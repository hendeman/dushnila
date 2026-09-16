# Python-зависимости SKINALI

Корневой `requirements.txt` содержит прямые зависимости сайта и подключённых инструментов разработки. `requirements-production.txt` повторяет четыре необходимые web-приложению версии без `django-extensions` и Debug Toolbar; он используется на Hostland. `skinali/requirements.txt` ссылается на полный корневой файл для локальной разработки.

| Пакет | Версия | Использование |
|---|---|---|
| Django | 5.2.17 | ORM, маршрутизация, формы, шаблоны, admin, management-команды и тесты |
| Pillow | 12.3.0 | `ImageField`, обработка изображений и создание тестовых JPEG |
| sorl-thumbnail | 13.1.0 | Приложение `sorl.thumbnail` и тег `thumbnail` в карточках каталога |
| requests | 2.34.2 | HTTPS-запросы доставки заявок в Telegram |
| pysqlite3-binary | 0.5.4.post2 | Самодостаточная современная SQLite для Linux-хостингов со старой системной библиотекой; на других ОС не устанавливается |
| django-extensions | 4.1 | Приложение `django_extensions`, включаемое настройкой `ENABLE_DJANGO_EXTENSIONS` |
| django-debug-toolbar | 7.0.0 | Приложение, middleware и маршруты панели отладки при `ENABLE_DEBUG_TOOLBAR` |

Версии сверены с рабочим окружением Python 3.11; Pillow и requests обновлены до актуальных релизов. Очистка списка не обновляет остальные версии библиотек. Оба инструмента разработки оставлены, поскольку они включены по умолчанию в development-профиле.

`pysqlite3-binary` ограничен маркером `platform_system == "Linux"`: локальная Windows-среда продолжает использовать встроенный `sqlite3`, а Linux также оставляет его активным, если системная версия уже не ниже 3.31. `asgiref`, `sqlparse`, `tzdata` (для Windows), `certifi`, `charset-normalizer`, `idna` и `urllib3` устанавливает pip по метаданным Django, Debug Toolbar и requests. Отдельных импортов этих библиотек в прикладном коде нет. Их версии здесь не фиксируются: это список прямых зависимостей, а не полный lock-файл окружения.

Библиотеки CAPTCHA, Selenium, Telegram-клиенты, pandas, NumPy, PyInstaller, аудиообработки и прочие пакеты старого общего окружения сайтом не используются. Telegram вызывается через requests, а `.env` загружается собственным кодом на стандартной библиотеке. Оставшийся в корне `validation.spec` относится к сборке отсутствующего `validation.py` и не является точкой входа SKINALI.

## Установка и проверка

Из корня репозитория в отдельном виртуальном окружении Python 3.11:

```text
python -m pip install -r requirements.txt
python skinali/manage.py check
python skinali/manage.py test pict
```

В preview и production на Hostland используется сокращённая установка:

```text
python -m pip install -r requirements-production.txt
```

Из каталога `skinali/` также можно выполнять `python -m pip install -r requirements.txt`: pip разрешает вложенную ссылку относительно requirements-файла.

Установка очищенного списка не удаляет лишние пакеты из уже существующего общего окружения. Для окружения только с зависимостями SKINALI следует использовать новый virtualenv.
