# Миграции приложения `pict`

## Назначение

Сводка всех Python-файлов в `skinali/pict/migrations/`. Миграции образуют линейную цепочку от `0001` до `0018`; `__init__.py` пуст и только обозначает пакет.

Текущую итоговую схему удобнее смотреть в [models.md](../pict/models.md). Этот документ нужен для истории изменения БД и выбора миграции при диагностике.

## История

| Миграция | Изменение |
|---|---|
| `0001_initial.py` | Созданы `Category` и `Pict`; у `Pict` были строковые `name`, `title`, изображение, дата и M2M-категории. |
| `0002_alter_category_options_alter_pict_options_and_more.py` | Добавлены русские verbose names моделям и полям. |
| `0003_alter_pict_options_category_slug.py` | Добавлена сортировка `Pict` по `id`; в `Category` добавлен slug с временным default. |
| `0004_alter_category_slug.py` | Slug категории сделан уникальным. |
| `0005_color.py` | Создана модель `Color` с названием и уникальным slug. |
| `0006_pict_color.py` | В `Pict` добавлен nullable ForeignKey на `Color` с `CASCADE`. |
| `0007_rename_slug_color_slug_color.py` | Поле `Color.slug` переименовано в `slug_color`. |
| `0008_pict_alt_alter_pict_color.py` | Добавлено nullable-описание `Pict.alt`; цвет получил verbose name. |
| `0009_alter_pict_color.py` | Удаление цвета стало устанавливать ForeignKey в `NULL` (`SET_NULL`). |
| `0010_tagpict_pict_tags.py` | Создан `TagPict`; в `Pict` добавлена необязательная M2M-связь `tags`. |
| `0011_alter_tagpict_options_alter_tagpict_slug.py` | Добавлены verbose names тегов; slug преобразован в `SlugField`. |
| `0012_alter_pict_alt.py` | `alt` стал `blank=True` с временным default пустой строки. |
| `0013_alter_pict_name.py` | Строковый `name` стал уникальным и индексированным. |
| `0014_remove_pict_title.py` | Удалено поле `Pict.title`. |
| `0015_alter_pict_options_alter_pict_alt.py` | Сортировка изменена на `-id`; временный default у `alt` удален. |
| `0016_alter_pict_tags.py` | Для тегов добавлен `related_name='tags'`. |
| `0017_alter_category_slug_alter_color_slug_color_and_more.py` | Slug-поля получили текущие verbose names; `Pict.name` преобразован в integer; цвет заменен с ForeignKey на M2M; связи получили verbose names. |
| `0018_finishedwork.py` | Создана модель `FinishedWork` с именем, описанием, фотографией, датой создания и необязательной связью `ForeignKey` на `Pict` с `SET_NULL`. |

## Итог после `0018`

- `Category`, `Color`, `TagPict` — отдельные справочники с уникальными slug.
- `Pict.name` — уникальное индексированное целое число.
- Категории, цвета и теги связаны с изображениями many-to-many.
- `Pict.title` отсутствует.
- Изображения сортируются по убыванию `id`.
- `FinishedWork` хранит одну фотографию готовой работы и при необходимости ссылается на одно изображение каталога; обратная связь — `Pict.finished_works`.
- Удаление связанного `Pict` не удаляет готовую работу, а обнуляет `catalog_image`.
- Готовые работы сортируются по убыванию времени создания и ID.

## Правила для ИИ-агента

- Не редактировать примененные исторические миграции для обычного изменения схемы; менять модель и создавать новую миграцию.
- Перед изменением схемы проверить [models.md](../pict/models.md), фактический `models.py` и состояние миграций через `python manage.py showmigrations pict`.
- После создания миграции добавить ее в эту таблицу и обновить итоговую схему при необходимости.
- При проблеме перехода между конкретными версиями открыть соответствующий исходный файл миграции: сводка не содержит всех сериализованных параметров полей.
