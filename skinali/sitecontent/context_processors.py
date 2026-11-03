from django.utils.functional import SimpleLazyObject

from .models import CatalogSearchSettings, MenuItem, SiteMenu


class VisibleMenuUrls:
    """Лениво проверяет URL по тому же QuerySet, который выводится в меню."""

    def __init__(self, menu_items):
        self.menu_items = menu_items

    def __contains__(self, url):
        return any(item.url == url for item in self.menu_items)


def site_navigation(request):
    """Лениво добавляет общее меню и настройки шапки без межзапросного кеша."""
    menu_items = (
        MenuItem.objects
        .filter(menu__code=SiteMenu.MAIN_CODE, is_visible=True)
        .only('title', 'url', 'open_in_new_tab')
    )
    header_settings = SimpleLazyObject(lambda: (
        CatalogSearchSettings.objects.only('header_schedule', 'header_menu_item')
        .filter(pk=CatalogSearchSettings.CODE).first() or CatalogSearchSettings()
    ))

    def get_header_menu_item():
        selected_id = header_settings.header_menu_item_id
        if selected_id is None:
            return None
        # Повторно используем видимое меню: скрытый пункт не становится отдельной ссылкой.
        return next((item for item in menu_items if item.pk == selected_id), None)

    return {
        'site_menu_items': menu_items,
        'visible_site_menu_urls': VisibleMenuUrls(menu_items),
        'site_header_settings': header_settings,
        'site_header_menu_item': SimpleLazyObject(get_header_menu_item),
    }
