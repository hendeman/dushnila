from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse

from .models import MenuItem, SiteMenu, SitePage


class SuperuserSiteContentAdminMixin:
    """Содержимое сайта доступно только активному суперпользователю."""

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)


class MenuItemInline(admin.TabularInline):
    model = MenuItem
    extra = 1
    fields = ('position', 'title', 'url', 'open_in_new_tab', 'is_visible')
    ordering = ('position', 'pk')


@admin.register(SitePage)
class SitePageAdmin(SuperuserSiteContentAdminMixin, admin.ModelAdmin):
    fields = ('seo_title', 'seo_description')
    list_display = ('page_name', 'seo_title', 'seo_description')
    search_fields = ('seo_title', 'seo_description')
    actions = None

    @admin.display(description='Страница', ordering='code')
    def page_name(self, obj):
        return obj.get_code_display()

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SiteMenu)
class SiteMenuAdmin(SuperuserSiteContentAdminMixin, admin.ModelAdmin):
    fields = ('name',)
    readonly_fields = ('name',)
    inlines = (MenuItemInline,)
    actions = None

    def has_add_permission(self, request):
        return super().has_add_permission(request) and not SiteMenu.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # Удаляются отдельные строки; системная карточка основного меню сохраняется.
        return False

    def changelist_view(self, request, extra_context=None):
        # Ссылка «Меню» сразу открывает единственную карточку со всеми строками.
        if self.has_view_permission(request):
            menu = SiteMenu.objects.only('pk').first()
            if menu:
                return redirect(reverse('admin:sitecontent_sitemenu_change', args=[menu.pk]))
        return super().changelist_view(request, extra_context=extra_context)
