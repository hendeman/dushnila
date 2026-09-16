# `skinali/pict/context_processors.py`

## Назначение

Добавляет в контекст всех Django-шаблонов единую публичную идентичность сайта и общие модальные формы обратного звонка и покупки изображения.

## `site_identity(request)`

Берёт название «ОДИУМ», основной телефон, email, путь и размеры логотипа, а также официальные профили Instagram и ВКонтакте из `settings.SITE_IDENTITY`. На основе `PUBLIC_SITE_ORIGIN` и настроенного static URL дополнительно формирует:

- `url` — абсолютный URL главной с завершающим `/`;
- `website_id` и `organization_id` — стабильные JSON-LD-идентификаторы `#website` и `#organization`;
- `logo_url` — абсолютный публичный URL логотипа.

Все значения возвращаются под ключом `site_identity`. Базовый шаблон использует их для основного логотипа, телефона, email и ссылок на социальные профили, а главная — для структурированных данных `WebSite` и `Organization`. Процессор не выполняет запросов к базе данных.

## `contact_forms(request)`

Возвращает два небound-экземпляра:

- `CallbackContactForm(prefix='callback')` под ключом `callback_form`;
- `ImagePurchaseContactForm(prefix='image_purchase')` под ключом `image_purchase_form`.

Префиксы предотвращают совпадение `name` и `id` между глобальными и встроенными в страницу контактов формами. Скрытый `pict_id` формы покупки изначально пуст и заполняется JavaScript при нажатии кнопки текущей Fancybox-карточки.

Процессор зарегистрирован в `TEMPLATES[0]['OPTIONS']['context_processors']` и не выполняет запросов к базе данных.

## Зависимости

- [forms.py](forms.md): `CallbackContactForm`, `ImagePurchaseContactForm`.
- [настройки проекта](../project/settings.md): `SITE_IDENTITY`, `PUBLIC_SITE_ORIGIN` и регистрация context processors.
- `pict/base.html`: реквизиты сайта, социальные ссылки и модальные окна.
- `pict/index.html`: JSON-LD-граф главной страницы.

## Когда читать исходник

При изменении глобальных форм, состава контекста базового шаблона или настройки template backend.
