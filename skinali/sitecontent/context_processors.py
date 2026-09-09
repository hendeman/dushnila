from .models import MenuItem, SiteMenu


def site_navigation(request):
    """Добавляет видимые пункты единого меню без межзапросного кеша."""
    menu_items = (
        MenuItem.objects
        .filter(menu__code=SiteMenu.MAIN_CODE, is_visible=True)
        .only('title', 'url', 'open_in_new_tab')
    )
    return {'site_menu_items': menu_items}
