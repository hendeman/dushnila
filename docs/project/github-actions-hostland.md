# Автоматическое обновление Odium на Hostland через GitHub Actions

## Назначение

Инструкция описывает настройку автоматического обновления production-сайта `https://odium.by` после push в ветку `master` репозитория `hendeman/dushnila`.

Рабочая последовательность:

1. GitHub Actions получает новый commit ветки `master`.
2. На чистом runner с Python 3.11 устанавливаются зависимости, выполняются `manage.py check` и все Django-тесты.
3. Только после успешных тестов GitHub подключается к Hostland отдельным SSH-ключом.
4. На Hostland создаются резервные копии SQLite и текущего кода.
5. Проверенный commit загружается в отдельную рабочую копию, после чего обновляется production-приложение.
6. Выполняются установка production-зависимостей, проверки Django, сбор статики, миграции и перезапуск Passenger.
7. Главная страница, `robots.txt` и `sitemap.xml` проверяются с самого Hostland через публичный HTTPS-домен.

Если тесты или SSH-деплой завершаются ошибкой, следующий этап не запускается. Статус каждого обновления отображается на вкладке **Actions** репозитория.

## Текущие адреса и пути

| Назначение | Значение |
|---|---|
| GitHub-репозиторий | `https://github.com/hendeman/dushnila` |
| Production-ветка | `master` |
| GitHub Environment | `production` |
| SSH-сервер Hostland | `serv11.hostland.ru` |
| SSH-порт | `1024` |
| SSH-пользователь | `host1889656` |
| Исходники на Hostland | `/home/host1889656/odium.by/repositories/dushnila` |
| Production-приложение | `/home/host1889656/odium.by/projects/odium` |
| Production Python | `/home/host1889656/odium.by/venv/python_3.11/bin/python` |
| Автоматические backup | `/home/host1889656/odium.by/backups/automatic-deploy` |

## Файлы автоматизации в репозитории

- `.github/workflows/deploy-production.yml` — тестирование, SSH-подключение, запуск деплоя и health-check;
- `ops/deploy_hostland.sh` — резервное копирование и обновление production-приложения;
- `requirements.txt` — зависимости runner для тестов;
- `requirements-production.txt` — зависимости production;
- `.gitattributes` — обязательные LF-переносы для shell- и workflow-файлов;
- `.gitignore` — исключение `.env`, SQLite, локальных media и служебных файлов.

## Предварительные требования

На Hostland должны быть доступны:

```console
/usr/local/bin/bash
/usr/bin/git
/usr/bin/rsync
/usr/bin/curl
```

Внешний SSH должен принимать соединения на `serv11.hostland.ru:1024`. Web SSH в панели можно использовать для первоначального редактирования `~/.ssh/authorized_keys`, но GitHub Actions требуется именно внешний SSH-доступ.

Production-приложение, его `.env`, SQLite, `public/media`, virtualenv и Passenger должны быть настроены заранее. Автоматический деплой не выполняет первичное создание сайта.

## 1. Создание отдельного deploy-ключа

Ключ создаётся только для GitHub Actions. Нельзя использовать личный SSH-ключ или ключ от другого сервиса.

В локальном PowerShell:

```powershell
ssh-keygen -t ed25519 `
  -C github-actions-odium-production `
  -f "$env:USERPROFILE\.ssh\odium_github_actions_ed25519"
```

На запрос парольной фразы дважды нажать Enter. CI не может интерактивно вводить пароль, поэтому deploy-ключ должен быть без парольной фразы. Защита обеспечивается отдельным назначением ключа, ограничениями в `authorized_keys` и хранением закрытой части в GitHub Environment secret.

Создаются два файла:

- `odium_github_actions_ed25519` — приватный ключ; не публиковать и не добавлять в Git;
- `odium_github_actions_ed25519.pub` — публичный ключ для Hostland.

Проверить отпечаток публичной части:

```powershell
ssh-keygen -lf "$env:USERPROFILE\.ssh\odium_github_actions_ed25519.pub"
```

## 2. Добавление публичного ключа на Hostland

Через Web SSH Hostland:

```console
mkdir -p ~/.ssh
chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
nano ~/.ssh/authorized_keys
```

В конец файла добавить публичный ключ одной строкой с ограничениями:

```text
no-agent-forwarding,no-port-forwarding,no-X11-forwarding,no-pty ssh-ed25519 ПУБЛИЧНЫЙ_КЛЮЧ github-actions-odium-production
```

Существующие строки не перезаписывать. Сохранение в `nano`: `Ctrl+O`, Enter, `Ctrl+X`.

Ограничения запрещают перенаправление портов, SSH-agent, X11 и интерактивный терминал. Ключ сохраняет возможность выполнять неинтерактивные команды деплоя.

## 3. Проверка внешнего SSH

На текущем сервере автоматический выбор `umac-128@openssh.com` приводит к ошибке `Corrupted MAC on input`. Поэтому и локальный тест, и workflow явно используют `aes256-ctr` и `hmac-sha2-256`:

```powershell
ssh `
  -o Ciphers=aes256-ctr `
  -o MACs=hmac-sha2-256 `
  -p 1024 `
  -i "$env:USERPROFILE\.ssh\odium_github_actions_ed25519" `
  host1889656@serv11.hostland.ru `
  "echo SSH_OK"
```

Ожидаемый ответ:

```text
SSH_OK
```

При первом соединении проверить отпечаток сервера через доверенный источник и только затем подтвердить добавление host key. Запись появится в локальном `~/.ssh/known_hosts`.

## 4. Создание GitHub Environment

В репозитории открыть:

**Settings → Environments → New environment**

Создать Environment с точным именем:

```text
production
```

В ограничениях deployment разрешить только ветку `master`.

## 5. Секрет с приватным ключом

Перед копированием проверить структуру локального файла и поместить его в буфер без вывода приватной части в терминал:

```powershell
$keyPath = "$env:USERPROFILE\.ssh\odium_github_actions_ed25519"
$key = [System.IO.File]::ReadAllText($keyPath)

if (
    -not $key.StartsWith("-----BEGIN OPENSSH PRIVATE KEY-----") -or
    -not $key.TrimEnd().EndsWith("-----END OPENSSH PRIVATE KEY-----")
) {
    throw "Файл не является приватным OpenSSH-ключом"
}

Set-Clipboard -Value $key
Write-Host "Приватный ключ проверен и скопирован"
```

В **Environment secrets** окружения `production` создать:

```text
HOSTLAND_SSH_PRIVATE_KEY
```

Вставить содержимое буфера целиком. Значение должно включать строки `BEGIN` и `END`, без кавычек и дополнительного текста. Строка вида `ssh-ed25519 AAAA...` является публичным, а не приватным ключом.

Приватный ключ нельзя отправлять в сообщения, хранить в документации или добавлять в репозиторий.

## 6. Секрет с host key сервера

После успешного доверенного SSH-подключения получить записи Hostland из локального `known_hosts` и скопировать их в буфер:

```powershell
$rows = & "$env:WINDIR\System32\OpenSSH\ssh-keygen.exe" `
  -F '[serv11.hostland.ru]:1024' `
  -f "$env:USERPROFILE\.ssh\known_hosts"

$knownHosts = ($rows | Where-Object { $_ -notmatch '^#' }) `
  -join [Environment]::NewLine

Set-Clipboard -Value $knownHosts
```

В Environment secrets создать:

```text
HOSTLAND_KNOWN_HOSTS
```

Вставить все найденные строки целиком. Формат каждой строки:

```text
[serv11.hostland.ru]:1024 ТИП_КЛЮЧА КЛЮЧ
```

Нельзя вставлять только закодированную часть ключа: SSH требуется адрес с портом, тип и значение. Workflow использует `StrictHostKeyChecking=yes` и прекращает соединение при несовпадении server host key.

## 7. Предохранитель production-деплоя

В репозитории открыть:

**Settings → Secrets and variables → Actions → Variables**

Создать repository variable:

```text
Name: PRODUCTION_DEPLOY_ENABLED
Value: true
```

Используется именно repository variable, не secret и не environment variable. При отсутствующем значении или `false` GitHub выполняет тесты, но пропускает production-job.

Для первоначальной проверки workflow переменную рекомендуется оставить отсутствующей или равной `false`, выполнить первый push, убедиться в успешных тестах, а затем переключить значение на `true`.

## 8. Первый безопасный запуск

1. Зафиксировать workflow, deploy-скрипт, зависимости и документацию отдельным commit.
2. Выполнить push в `master` при выключенном `PRODUCTION_DEPLOY_ENABLED`.
3. На вкладке **Actions** убедиться, что `Django checks and tests` завершён успешно, а `Deploy to Hostland` пропущен.
4. Проверить Environment secrets и публичный ключ в `authorized_keys`.
5. Установить `PRODUCTION_DEPLOY_ENABLED=true`.
6. Открыть **Actions → Deploy production → Run workflow**, выбрать `master` и запустить workflow вручную.
7. Убедиться, что оба job завершились со статусом `success`.

После первого успешного запуска отдельная рабочая копия репозитория находится в:

```text
/home/host1889656/odium.by/repositories/dushnila
```

Редактировать её вручную нельзя: workflow принудительно переключает её на проверенный commit и очищает незакоммиченные файлы.

## 9. Обычное обновление production

После завершения настройки достаточно отправить commit в `master`:

```console
git status
git add ПУТИ_ИЗМЕНЁННЫХ_ФАЙЛОВ
git commit -m "Описание изменения"
git push origin master
```

`git add .` нежелателен в рабочем каталоге с посторонними незакоммиченными файлами. Следует добавлять только проверенные пути.

Push в другую ветку production не обновляет. Merge pull request в `master` считается push в `master` и запускает тот же workflow.

При успешных тестах GitHub автоматически выполняет деплой. Если тесты падают, production остаётся на предыдущем commit.

## 10. Что обновляется на сервере

`ops/deploy_hostland.sh` синхронизирует из проверенного commit:

- `skinali/pict/` → `projects/odium/pict/`;
- `skinali/sitecontent/` → `projects/odium/sitecontent/`;
- `skinali/skinali/` → `projects/odium/skinali/`;
- `skinali/manage.py` → `projects/odium/manage.py`;
- `requirements-production.txt` → `projects/odium/requirements-production.txt`.

Деплой не заменяет:

- `projects/odium/.env`;
- `projects/odium/db.sqlite3`;
- `projects/odium/public/media/`;
- `projects/odium/passenger_wsgi.py`;
- содержимое `projects/odium/tmp/`, кроме обновления `tmp/restart.txt`.

После синхронизации выполняются:

```console
python -m pip install -r requirements-production.txt
python manage.py check
python manage.py check --deploy
python manage.py collectstatic --noinput
python manage.py migrate --noinput
touch tmp/restart.txt
```

Предупреждение `security.W004` о нулевом `SECURE_HSTS_SECONDS` ожидаемо: production nginx Hostland уже отправляет `Strict-Transport-Security`.

## 11. Резервные копии и восстановление

Перед заменой кода создаются:

- online-backup SQLite через Python `sqlite3.backup()`;
- копия текущего production-кода;
- файл с SHA разворачиваемого commit.

Каталог:

```text
/home/host1889656/odium.by/backups/automatic-deploy/ДАТА-COMMIT
```

Хранятся последние пять автоматических backup.

При ошибке после начала синхронизации предыдущий код восстанавливается автоматически и Passenger перезапускается. SQLite автоматически не откатывается, чтобы не потерять заявки, поступившие во время обновления. Поэтому несовместимые удаления и переименования таблиц или полей требуют отдельного согласованного плана миграции.

## 12. Health-check

После деплоя проверяются:

- `https://odium.by/`;
- `https://odium.by/robots.txt` и строка `Sitemap: https://odium.by/sitemap.xml`;
- `https://odium.by/sitemap.xml`.

Hostland отвечает кодом `403` на запросы с IP GitHub-hosted runner, поэтому workflow выполняет проверки с самого Hostland через второе доверенное SSH-соединение. Запросы всё равно проходят через публичные DNS, TLS и nginx и подтверждают запуск production-приложения.

## 13. Отключение автоматического деплоя

Для временного отключения изменить repository variable:

```text
PRODUCTION_DEPLOY_ENABLED=false
```

Новые push продолжат запускать тесты, но production-job будет пропущен. Уже запущенный workflow при необходимости отменяется отдельно на вкладке Actions.

Удалять workflow, SSH-ключи или server checkout для временной паузы не нужно.

## 14. Замена SSH-ключа

1. Создать новый ключ под новым локальным именем.
2. Добавить новую публичную строку в `~/.ssh/authorized_keys`, не удаляя старую.
3. Проверить новое подключение командой `echo SSH_OK`.
4. Обновить `HOSTLAND_SSH_PRIVATE_KEY` в GitHub Environment.
5. Выполнить ручной workflow и дождаться успеха.
6. Только после этого удалить старую строку из `authorized_keys` и старые локальные файлы ключа.

Одновременная замена server key и GitHub secret без промежуточной проверки может полностью заблокировать автоматический деплой.

## 15. Диагностика типовых ошибок

### `Corrupted MAC on input`

Причина: несовместимый автоматически выбранный MAC на текущем сервере Hostland.

Решение: использовать `Ciphers=aes256-ctr` и `MACs=hmac-sha2-256`. Эти параметры уже зафиксированы в workflow.

### Запрос `Enter passphrase for key`

Причина: deploy-ключ создан с парольной фразой.

Решение: создать отдельный CI-ключ без парольной фразы, добавить его публичную часть на Hostland и заменить GitHub secret. Не удалять рабочий старый ключ до успешного теста нового.

### `Load key ...: error in libcrypto`

Причина: в `HOSTLAND_SSH_PRIVATE_KEY` вставлен публичный ключ, обрезанное значение или приватный ключ без строк `BEGIN`/`END`.

Решение: повторно скопировать весь приватный файл через проверяющий PowerShell-скрипт из раздела 5.

### `Permission denied (publickey,...)`

Проверить:

- соответствует ли приватный ключ публичной строке Hostland;
- сохранена ли строка в `/home/host1889656/.ssh/authorized_keys` без переносов;
- права `700` на `~/.ssh` и `600` на `authorized_keys`;
- используется ли новый ключ после ротации.

### `Host key verification failed`

Проверить полные строки `HOSTLAND_KNOWN_HOSTS`, включая `[serv11.hostland.ru]:1024` и тип ключа. При реальной смене server host key сначала подтвердить новый отпечаток через Hostland, затем обновлять secret.

### Тесты успешны, а `Deploy to Hostland` имеет статус `skipped`

Проверить repository variable `PRODUCTION_DEPLOY_ENABLED`. Для запуска требуется точное строковое значение `true`.

### Workflow успешен, но ожидаемое изменение не появилось

Проверить:

- был ли commit отправлен именно в `master`;
- SHA commit на странице Actions;
- входит ли изменённый файл в синхронизируемые каталоги;
- не относится ли изменение к `.env`, SQLite или media, которые намеренно не обновляются из Git;
- журнал `Deploy to Hostland` и результат `Check production health`.

## Источники

- [Git на Hostland](https://www.hostland.ru/ru/docs/useful/sistema-kontrolya-versiy-git)
- [Вопросы Hostland о SSH](https://www.hostland.ru/ru/docs/useful/voprosy-o-rabote-s-ssh)
- [GitHub: управление Environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)
- [GitHub: использование secrets в Actions](https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions)
