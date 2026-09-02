# `skinali/pict/urls.py`

## Назначение

Определяет публичные маршруты приложения `pict`. Подключается без префикса из корневого URLconf.

## Таблица маршрутов

| URL | Имя | View | Назначение |
|---|---|---|---|
| `/` | `home` | `PictHome` | главная страница и поиск |
| `/about/` | `about` | `about` | контакты |
| `/favorites/` | `favorites` | `favorites` | избранные изображения текущей сессии |
| `/favorites/toggle/<int:pict_id>/` | `favorite_toggle` | `toggle_favorite` | добавить изображение в избранное или удалить его; только POST |
| `/contact/request/` | `contact_submit` | `submit_contact_form` | серверная проверка контактной формы; только POST |
| `/foto-skinali-iz-stekla/` | `finished_works` | `FinishedWorkList` | публичная галерея готовых работ |
| `/skinali/` | `skinali` | `SkinaliAll` | весь каталог |
| `/skinali/<slug:slug_cat>/` | `skinali` | `SkinaliSlug` | каталог категории |
| `/designer` | `designer` | `designer` | услуги дизайнера |
| `/cats/<int:catid>/` | `cat` | `cat` | простая тестовая страница категории по ID |
| `/tag/<slug:tag_slug>/` | `tag` | `PictTag` | изображения по тегу |

## Параметры

- Каталог принимает GET-параметр `color` со значением `Color.slug_color`.
- Главная страница принимает GET-параметр `product-number`.
- Стандартный параметр `page` обрабатывается пагинацией `ListView`.
- Переключатель избранного принимает ID `Pict` в URL, возвращает JSON и отклоняет методы, отличные от POST.
- Обработчик контактной формы принимает `form_kind=callback` или `form_kind=question`. AJAX-запрос получает JSON, обычный POST — HTML-страницу результата с сохранением введённых значений при ошибке.
- Страница готовых работ принимает стандартный GET-параметр `page` и выводит по 6 работ.

## Зависимости

- [views.py](views.md).
- [models.py](models.md): `Category.get_absolute_url()` использует имя `skinali`, `TagPict.get_absolute_url()` — имя `tag`.
- [корневой URLconf](../project/urls.md).

## Особенности и риски

- Одно имя `skinali` назначено двум маршрутам. Reverse с аргументом `slug_cat` выбирает маршрут категории, без аргумента — общий каталог.
- У `/designer` нет завершающего `/`, в отличие от большинства маршрутов.
- Последний маршрут не имеет завершающей запятой; синтаксически это допустимо.
- Используется wildcard-импорт из `views`.

## Когда читать исходник

При изменении URL, имен маршрутов, slug/ID-параметров или привязки view.
