from django.contrib import admin
from django.utils.safestring import mark_safe

from pict.forms import PictAdminForm
from pict.models import Pict, Category, Color, TagPict


class PictAdmin(admin.ModelAdmin):
    list_per_page = 20
    list_display = ['name', 'color', 'get_html_photo', 'get_list_category']
    # list_editable = ['color']
    list_display_links = ['name']
    search_fields = ['name', 'tags__tag']
    list_filter = ['time_update']
    fields = ['name', 'alt', 'color', 'photo', 'get_html_photo_fields', 'time_update', 'cat', 'tags']
    readonly_fields = ['time_update', 'get_html_photo_fields']
    filter_horizontal = ['cat', 'tags']
    ordering = ["-id"]
    form = PictAdminForm


    def get_html_photo(self, object):
        if object.photo:
            return mark_safe(
                f"<a href = '{object.photo.url}' target=_blank><img src='{object.photo.url}' width=150></a>")

    def get_html_photo_fields(self, object):
        if object.photo:
            return mark_safe(
                f"<a href = '{object.photo.url}' target=_blank><img src='{object.photo.url}' width=400></a>")

    def get_list_category(self, object):
        a = Pict.objects.get(name=object.name)
        return ", ".join([x.cat for x in a.cat.all()])

    get_html_photo.short_description = 'Миниатюра'
    get_html_photo_fields.short_description = 'Миниатюра'
    get_list_category.short_description = 'Категории'


class CategoryAdmin(admin.ModelAdmin):
    list_display = ['cat', 'slug']
    list_display_links = ['cat']
    search_fields = ['cat']
    prepopulated_fields = {"slug": ("cat",)}


class TagPictAdmin(admin.ModelAdmin):
    list_display = ['tag', 'slug']
    list_display_links = ['tag']
    search_fields = ['tag']
    prepopulated_fields = {"slug": ("tag",)}


class ColorAdmin(admin.ModelAdmin):
    list_display = ['color', 'slug_color']
    list_display_links = ['color']
    ordering = ['color']
    # prepopulated_fields = {"slug_color": ("color",)}


admin.site.register(Pict, PictAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(Color, ColorAdmin)
admin.site.register(TagPict, TagPictAdmin)
