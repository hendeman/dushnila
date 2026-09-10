from .models import MenuItem, SiteMenu


class VisibleMenuUrls:
    """Лениво проверяет URL по тому же QuerySet, который выводится в меню."""

    def __init__(self, menu_items):
        self.menu_items = menu_items

    def __contains__(self, url):
        return any(item.url == url for item in self.menu_items)


def site_navigation(request):
    """Добавляет видимые пункты меню и набор их адресов без кеширования."""
    menu_items = (
        MenuItem.objects
        .filter(menu__code=SiteMenu.MAIN_CODE, is_visible=True)
        .only('title', 'url', 'open_in_new_tab')
    )
    return {
        'site_menu_items': menu_items,
        'visible_site_menu_urls': VisibleMenuUrls(menu_items),
    }
