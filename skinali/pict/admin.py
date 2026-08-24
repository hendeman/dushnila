from django.contrib import admin
from django.utils.html import format_html, format_html_join

from pict.forms import PictAdminForm
from pict.models import Category, Color, FinishedWork, Pict, TagPict


class AdminImagePreviewMixin:
    class Media:
        css = {'all': ('skinali/css/admin-image-preview.css',)}
        js = ('skinali/js/admin-image-preview.js',)


class PictAdmin(AdminImagePreviewMixin, admin.ModelAdmin):
    list_per_page = 20
    list_display = ['name', 'get_html_photo', 'get_list_category', 'get_list_color']
    # list_editable = ['color']
    list_display_links = ['name']
    search_fields = ['=name', 'tags__tag']
    list_filter = ['time_update', 'cat__cat', 'color__color']
    fields = ['name', 'alt', 'photo', 'get_html_photo_fields', 'time_update', 'color', 'cat', 'tags']
    readonly_fields = ['time_update', 'get_html_photo_fields', 'get_finished_works']
    filter_horizontal = ['color', 'cat', 'tags']
    ordering = ["-id"]
    form = PictAdminForm

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .prefetch_related('cat', 'color', 'finished_works')
        )

    def get_fields(self, request, obj=None):
        fields = list(self.fields)
        if obj and obj.finished_works.exists():
            fields.insert(fields.index('time_update'), 'get_finished_works')
        return fields


    def get_html_photo(self, object):
        if object.photo:
            return format_html(
                '<a class="admin-image-preview-link" href="{}" data-image-preview>'
                '<img src="{}" alt="Изображение № {}" width="150"></a>',
                object.photo.url,
                object.photo.url,
                object.name,
            )

    def get_html_photo_fields(self, object):
        if object.photo:
            return format_html(
                '<a class="admin-image-preview-link" href="{}" data-image-preview>'
                '<img src="{}" alt="Изображение № {}" width="400"></a>',
                object.photo.url,
                object.photo.url,
                object.name,
            )

    def get_list_category(self, object):
        return ", ".join([x.cat for x in object.cat.all()])

    def get_list_color(self, object):
        return ", ".join([x.color for x in object.color.all()])

    @admin.display(description='Готовые работы')
    def get_finished_works(self, obj):
        works = [work for work in obj.finished_works.all() if work.photo]
        if not works:
            return '—'
        return format_html_join(
            '',
            (
                '<a class="admin-image-preview-link" href="{}" '
                'data-image-preview title="{}">'
                '<img src="{}" alt="{}" width="160" '
                'style="margin: 0 8px 8px 0; border-radius: 4px;"></a>'
            ),
            (
                (work.photo.url, work.name, work.photo.url, work.name)
                for work in works
            ),
        )

    get_html_photo.short_description = 'Миниатюра'
    get_html_photo_fields.short_description = 'Миниатюра'
    get_list_category.short_description = 'Категории'
    get_list_color.short_description = 'Цвета'


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


@admin.register(FinishedWork)
class FinishedWorkAdmin(AdminImagePreviewMixin, admin.ModelAdmin):
    list_display = [
        'name',
        'get_html_photo',
        'get_catalog_image_number',
        'get_catalog_categories',
        'created_at',
    ]
    list_display_links = ['name']
    search_fields = ['name', 'description', '=catalog_image__name']
    autocomplete_fields = ['catalog_image']
    readonly_fields = ['get_html_photo_fields', 'created_at']
    fields = [
        'name',
        'description',
        'photo',
        'get_html_photo_fields',
        'catalog_image',
        'created_at',
    ]
    ordering = ['-created_at', '-id']
    list_per_page = 20

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related('catalog_image')
            .prefetch_related('catalog_image__cat')
        )

    @admin.display(description='Миниатюра')
    def get_html_photo(self, obj):
        if obj.photo:
            return format_html(
                '<a class="admin-image-preview-link" href="{}" data-image-preview>'
                '<img src="{}" alt="{}" width="80"></a>',
                obj.photo.url,
                obj.photo.url,
                obj.name,
            )
        return '—'

    @admin.display(description='Миниатюра')
    def get_html_photo_fields(self, obj):
        if obj.photo:
            return format_html(
                '<a class="admin-image-preview-link" href="{}" data-image-preview>'
                '<img src="{}" alt="{}" width="200"></a>',
                obj.photo.url,
                obj.photo.url,
                obj.name,
            )
        return '—'

    @admin.display(description='Номер изображения', ordering='catalog_image__name')
    def get_catalog_image_number(self, obj):
        return obj.catalog_image.name if obj.catalog_image else '—'

    @admin.display(description='Категории')
    def get_catalog_categories(self, obj):
        if not obj.catalog_image:
            return '—'
        return ', '.join(category.cat for category in obj.catalog_image.cat.all()) or '—'


admin.site.register(Pict, PictAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(Color, ColorAdmin)
admin.site.register(TagPict, TagPictAdmin)
