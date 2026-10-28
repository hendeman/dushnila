# `skinali/skinali/urls.py`

## Назначение

Корневой URLconf проекта. Подключает административную панель, правила для поисковых роботов, XML-карту сайта, маршруты приложения, debug toolbar, media в разработке и обработчики 404/500.

## Маршруты

| Путь | Назначение |
|---|---|
| `/<DJANGO_ADMIN_PATH>/` | Django Admin; локальное значение по умолчанию — `/admin/` |
| `/robots.txt` | Текстовые правила обхода, очистка рекламных параметров для Яндекса и абсолютная ссылка на XML-карту |
| `/sitemap.xml` | XML-карта постоянных страниц, опубликованных изображений и статей, непустых категорий и непустых тегов |
| `/quiz/` | маршруты POST-обработчика из `quiz.urls` |
| `/price/` | публичный калькулятор из `calculator.urls`, имя `price`, расчёт в браузере; `?calculation=...` восстанавливает подписанный расчёт |
| `/price/share/` | POST с JSON и CSRF: создание подписанной ссылки, имя `price_share`, без записи расчёта в БД |
| `/polezno-znat/`, `/polezno-znat/<slug>/` | список и страница опубликованных статей из `sitecontent.urls`, подключённого перед `pict.urls` |
| `/` | все маршруты из `pict.urls` |
| `/__debug__/` | Django Debug Toolbar; добавляется только при `ENABLE_DEBUG_TOOLBAR=True` |

При `settings.DEBUG` к `urlpatterns` добавляется обслуживание `MEDIA_URL` из `MEDIA_ROOT`. Маршрут Debug Toolbar полностью отсутствует в preview- и production-профилях, а не только скрывает панель.

`/robots.txt` принимает безопасные методы GET и HEAD, возвращает `text/plain; charset=utf-8` и кешируется клиентом на один час. Общая группа роботов запрещает обход текущего `ADMIN_URL`, POST-обработчика `/contact/request/` и служебного префикса `/quiz/`, но не закрывает `/favorites/`: персональная страница остаётся доступной роботу, чтобы он прочитал её HTML-директиву `noindex,follow`. Директива `Clean-param` перечисляет `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, `yclid` и `gclid`; неподдерживающие её роботы игнорируют строку. Адрес карты в `robots.txt` и все `<loc>` внутри XML всегда строятся от проверенного `PUBLIC_SITE_ORIGIN`, по умолчанию `https://odium.by`, а не от домена текущего запроса.

В профиле `preview` вместо публичных правил возвращается только `User-agent: *` и `Disallow: /` с `Cache-Control: no-store`; sitemap в этом ответе не раскрывается. Дополнительный middleware ставит `X-Robots-Tag: noindex, nofollow` на все ответы технического сайта.

## Дополнительная конфигурация

В admin калькулятор разделён на `/<DJANGO_ADMIN_PATH>/calculator/calculatorsettings/` («Настройки калькулятора», общий показ) и `/<DJANGO_ADMIN_PATH>/calculator/calculatortariffs/` («Тарифы и услуги»); обе ссылки списка открывают соответствующую singleton-карточку. Проверочный расчёт зарегистрирован в `CalculatorTariffsAdmin.get_urls()` по `/<DJANGO_ADMIN_PATH>/calculator/calculatortariffs/calculate/`, имя `admin:calculator_calculatortariffs_calculate`. Старый `/<DJANGO_ADMIN_PATH>/calculator/calculatorsettings/calculate/`, имя `admin:calculator_calculatorsettings_calculate`, вызывает тот же обработчик напрямую и сохраняет POST. Он принимает GET/POST, требует активного суперпользователя и CSRF. Корневой URLconf не меняется, namespace текущего AdminSite учитывается. В обеих карточках есть взаимные ссылки и «Проверить расчёт». Публичного API расчёта нет; [контракт](../calculator/overview.md).

Общие услуги используют штатные административные маршруты `calculator_calculatorservice_add/change/delete`, открываемые из «Тарифов и услуг». Их список перенаправляет в тарифы, отдельный пункт меню скрыт. Создание/изменение/подтверждённое удаление доступны только активному суперпользователю, защищены CSRF и учитывают namespace `AdminSite`; обычное сохранение возвращает в тарифы.

Справочник единиц доступен по `/<DJANGO_ADMIN_PATH>/calculator/measurementunit/`, имя `admin:calculator_measurementunit_changelist`, и через стандартные add/change/delete модели. Ссылка на него есть в меню и карточке «Тарифы и услуги»; поле единицы услуги использует связанный выбор Django Admin. Доступ открыт активному суперпользователю, удаления используемых единиц защищены `PROTECT`.

- Заголовок admin: `Админка skinali`.
- Заголовок главной страницы admin: `Админка`.
- `admin.site` создаётся через `SkinaliAdminConfig` как `SkinaliAdminSite`. Его `get_app_list()` добавляет к названию модели `ContactRequest` положительное число непросмотренных заявок, если у пользователя есть доступ к списку; при нуле оставляет обычное название. Маршруты admin остаются штатными.
- `handler404` ссылается на `pict.views.pageNotFound`: при `DEBUG=False` неизвестный URL получает полноценную страницу сайта через `pict/base.html` с шапкой, меню, контактами, подвалом, счётчиком избранного и обычными context processors. В контенте находятся пользовательская PNG «404», сообщение об ошибке и переходы на главную и в «Каталог скинали». Сохраняются настоящий статус 404, `noindex,follow`, отсутствие canonical и JSON-LD; в отличие от автономной 500, вывод 404 использует БД для публичной оболочки.
- `handler500` ссылается на `pict.views.serverError`: необработанная серверная ошибка в production получает автономную страницу без запросов к БД, с настоящим статусом 500, `noindex,nofollow`, нейтральным сообщением и ссылкой на главную без технических деталей, canonical и JSON-LD.

## Зависимости

- [Настройки](settings.md), особенно `DEBUG`, `SITE_NOINDEX`, `MEDIA_URL`, `MEDIA_ROOT`, `ADMIN_URL` и `PUBLIC_SITE_ORIGIN`.
- [Middleware технического preview](middleware.md).
- [URL приложения](../pict/urls.md).
- [Встроенный квиз](../quiz/overview.md).
- [Представления](../pict/views.md) для обработчиков 404/500.
- [Карта индексируемых страниц](../pict/sitemaps.md).

## Особенности и риски

- Значение `DJANGO_ADMIN_PATH` меняет только адрес admin и не заменяет аутентификацию, HTTPS и ограничение попыток входа.
- Путь admin намеренно публикуется в `robots.txt` по решению владельца; запрет обхода не является механизмом контроля доступа.
- Обслуживание media через Django предназначено только для разработки.

## Когда читать исходник

При добавлении приложения, изменении верхнеуровневого префикса, robots.txt, sitemap, admin, debug toolbar, media или обработчиков ошибок.

## Административная загрузка статей

`ArticleAdmin.get_urls()` добавляет `/<ADMIN_URL>/sitecontent/article/upload-image/` внутри штатного AdminSite. Маршрут принимает только POST, использует `admin_view`/CSRF и дополнительное ограничение активного суперпользователя; в публичный URLconf не вынесен. `sitecontent.sitemaps.ArticleSitemap` подключён как секция `articles`. Полный контракт: [Статьи](../sitecontent/articles.md).

## Публичная страница цены

`calculator.urls` подключён без префикса перед `sitecontent.urls` и `pict.urls`. Маршрут `/price/` с именем `price` вызывает `calculator.views.price`, принимает GET/HEAD, остальные методы возвращают 405. Он входит в постоянную секцию sitemap, имеет SEO-карточку и общий пункт меню. Тарифы и акции передаются безопасным JSON непосредственно в HTML только при включённом и настроенном калькуляторе; изменение полей рассчитывается в браузере. Отдельный POST `/price/share/` создаёт подписанную ссылку; `/price/?calculation=...` проверяет параметры, восстанавливает форму и использует актуальные тарифы. Эти ссылки не индексируются, canonical остаётся `/price/`. Ответ не кешируется. [Контракт](../calculator/overview.md#публичная-страница-цена).
