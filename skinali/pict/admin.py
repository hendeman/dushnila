import logging
import re
from pathlib import Path

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.http import HttpResponseNotAllowed
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join
from sorl.thumbnail.shortcuts import get_thumbnail
from skinali.admin_order import reorder_admin_objects
from sitecontent.admin_seo import SeoAdminMixin
from sitecontent.models import CatalogSearchSettings

from pict.forms import FinishedWorkAdminForm, PictAdminForm
from pict.models import (
    Category,
    Color,
    FinishedWork,
    Pict,
    TagAlias,
    TagPict,
    finished_work_photo_upload_to,
    pict_photo_upload_to,
)
from pict.services.photo_cleanup import remove_unused_photo


logger = logging.getLogger(__name__)

SEO_LANDING_FIELDS = (
    'seo_h1',
    'seo_title',
    'seo_description',
    'intro_text',
)
CATALOG_ADMIN_THUMBNAIL_GEOMETRY = '760'
FINISHED_WORK_ADMIN_THUMBNAIL_GEOMETRY = '400'


class NeedsAttentionFilter(admin.SimpleListFilter):
    """Объединяет редакторские подсказки без изменения правил сохранения."""

    title = 'Требуют внимания'
    parameter_name = 'attention'
    checks = ()
    # Дополнительные подсказки выбираются отдельно от «Любой причины».
    extra_checks = ()

    def lookups(self, request, model_admin):
        return [('any', 'Любая причина')] + [
            (value, label)
            for value, label, condition in self.checks + self.extra_checks
        ]

    def queryset(self, request, queryset):
        conditions = {
            value: condition
            for value, label, condition in self.checks + self.extra_checks
        }
        if self.value() == 'any':
            condition = Q()
            for value, label, check in self.checks:
                condition |= check
        else:
            condition = conditions.get(self.value())
            if condition is None:
                return queryset
        return queryset.filter(condition)


class PictNeedsAttentionFilter(NeedsAttentionFilter):
    checks = (
        (
            'no_tags',
            'Без тегов',
            Q(~Exists(Pict.tags.through.objects.filter(pict_id=OuterRef('pk')))),
        ),
        (
            'no_colors',
            'Без цветов',
            Q(~Exists(Pict.color.through.objects.filter(pict_id=OuterRef('pk')))),
        ),
        ('no_description', 'Без описания', Q(alt__regex=r'^\s*$')),
    )
    extra_checks = (
        (
            'no_seo',
            'Без SEO',
            Q(seo_h1__regex=r'^\s*$')
            | Q(seo_title__regex=r'^\s*$')
            | Q(seo_description__regex=r'^\s*$')
            | Q(page_description__regex=r'^\s*$'),
        ),
    )


class FinishedWorkNeedsAttentionFilter(NeedsAttentionFilter):
    checks = (
        ('no_description', 'Без описания', Q(description__regex=r'^\s*$')),
        (
            'print_without_catalog',
            'Печать без связи с каталогом',
            Q(
                skinali_type=FinishedWork.SkinaliType.PRINT,
                catalog_image__isnull=True,
            ),
        ),
    )


class AdminImagePreviewMixin:
    def get_object(self, request, object_id, from_field=None):
        obj = super().get_object(request, object_id, from_field)
        if obj is not None:
            # Валидация формы заменяет obj.photo даже при ошибках других полей.
            photo = getattr(obj, 'photo', None)
            if photo is not None:
                obj._admin_saved_photo = photo
            if isinstance(obj, Pict):
                obj._admin_saved_image_number = obj.name
        return obj

    @staticmethod
    def get_cached_preview_url(image_field, geometry):
        """Возвращает URL превью, сохраняя оригинал как резервный вариант."""
        try:
            options = {}
            image_number = getattr(image_field.instance, '_admin_saved_image_number', None)
            if image_number is not None:
                options['catalog_image_number'] = image_number
            return get_thumbnail(image_field, geometry, **options).url
        except Exception:
            logger.exception('Не удалось создать admin-превью для %s.', image_field.name)
            return image_field.url

    @classmethod
    def render_image_preview(cls, image_field, *, alt_text, width, geometry=None):
        """Формирует одинаковую кликабельную миниатюру для всех admin-таблиц."""
        if not image_field:
            return '—'
        if not image_field._committed:
            image_field = getattr(image_field.instance, '_admin_saved_photo', None)
            if not image_field or not image_field._committed:
                return format_html(
                    '<span class="admin-image-preview-error">{}</span>',
                    'Изображение ещё не сохранено. '
                    'Выберите файл повторно после исправления ошибок.',
                )
        preview_url = (
            cls.get_cached_preview_url(image_field, geometry)
            if geometry else image_field.url
        )
        return format_html(
            '<a class="admin-image-preview-link" href="{}" data-image-preview>'
            '<img src="{}" alt="{}" width="{}"></a>',
            image_field.url,
            preview_url,
            alt_text,
            width,
        )

    class Media:
        css = {'all': ('skinali/css/admin-image-preview.css',)}
        js = ('skinali/js/admin-image-preview.js',)


class AdminPhotoRenameMixin:
    @staticmethod
    def photo_name_matches_storage_variant(current_name, target_name):
        """Учитывает уникальный суффикс, который добавляет FileSystemStorage."""
        current_path = Path(current_name)
        target_path = Path(target_name)
        if (
            current_path.parent != target_path.parent
            or current_path.suffix.lower() != target_path.suffix.lower()
        ):
            return False
        return bool(re.fullmatch(
            rf'{re.escape(target_path.stem)}(?:_[A-Za-z0-9]{{7}})?',
            current_path.stem,
        ))

    def rename_photo_files(
        self,
        request,
        queryset,
        *,
        model,
        upload_to,
        source_value,
        unchanged_description,
        log_description,
    ):
        """Безопасно переименовывает оригиналы выбранных записей."""
        renamed_count = 0
        unchanged_count = 0
        skipped_count = 0
        failed_count = 0

        for item in queryset.iterator(chunk_size=100):
            if not source_value(item).strip() or not item.photo:
                skipped_count += 1
                continue

            old_photo = item.photo
            old_name = old_photo.name
            storage = old_photo.storage
            target_name = upload_to(item, Path(old_name).name)

            if not storage.exists(old_name):
                skipped_count += 1
                continue
            # Суффикс сохраняем только пока имя без него занято другим файлом.
            if (
                self.photo_name_matches_storage_variant(old_name, target_name)
                and (old_name == target_name or storage.exists(target_name))
            ):
                unchanged_count += 1
                continue

            saved_name = None
            try:
                with storage.open(old_name, 'rb') as source_file:
                    saved_name = storage.save(
                        target_name,
                        source_file,
                        max_length=model._meta.get_field('photo').max_length,
                    )
                with transaction.atomic(using=item._state.db):
                    item.photo = saved_name
                    item.save(update_fields=['photo'])
            except Exception:
                failed_count += 1
                logger.exception(
                    'Не удалось переименовать %s pk=%s.',
                    log_description,
                    item.pk,
                )
                if saved_name:
                    remove_unused_photo(saved_name, storage=storage, using=item._state.db)
                continue

            renamed_count += 1

        summary = (
            f'Переименовано: {renamed_count}. '
            f'Уже соответствовали {unchanged_description}: {unchanged_count}. '
            f'Пропущено: {skipped_count}. '
            f'Ошибок: {failed_count}.'
        )

        level = messages.SUCCESS
        if failed_count:
            level = messages.ERROR
        elif skipped_count:
            level = messages.WARNING
        self.message_user(request, summary, level=level)


class PictAdmin(
    SeoAdminMixin,
    AdminImagePreviewMixin,
    AdminPhotoRenameMixin,
    admin.ModelAdmin,
):
    list_per_page = 20
    list_display = ['name', 'is_published', 'get_html_photo', 'get_list_category', 'get_list_color']
    list_editable = ['is_published']
    list_display_links = ['name']
    search_fields = ['=name', 'alt', 'slug', 'tags__tag']
    list_filter = [
        PictNeedsAttentionFilter,
        'is_published',
        'created_at',
        'cat__cat',
        'color__color',
    ]
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'name',
                    'is_published',
                    'alt',
                    'slug',
                    'photo',
                    'is_popular',
                    'get_html_photo_fields',
                    'created_at',
                    'updated_at',
                    'color',
                    'cat',
                    'tags',
                ),
            },
        ),
        (
            'SEO и текст страницы',
            {
                'classes': ('collapse',),
                'fields': (
                    'page_description',
                    'seo_h1',
                    'seo_title',
                    'seo_description',
                ),
                'description': (
                    'Пустые поля используют автоматически сформированные значения.'
                ),
            },
        ),
    )
    readonly_fields = [
        'created_at',
        'updated_at',
        'slug',
        'get_html_photo_fields',
        'get_finished_works',
    ]
    filter_horizontal = ['color', 'cat', 'tags']
    ordering = ["-id"]
    form = PictAdminForm
    actions = ['rename_photos_from_description']

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .prefetch_related('cat', 'color', 'finished_works')
        )

    def get_fieldsets(self, request, obj=None):
        fieldsets = list(super().get_fieldsets(request, obj))
        if not obj or not obj.finished_works.exists():
            return fieldsets

        title, options = fieldsets[0]
        fields = list(options['fields'])
        fields.insert(fields.index('created_at'), 'get_finished_works')
        fieldsets[0] = (title, {**options, 'fields': fields})
        return fieldsets

    @admin.action(
        description='Переименовать файлы по описанию и номеру',
        permissions=['change'],
    )
    def rename_photos_from_description(self, request, queryset):
        self.rename_photo_files(
            request,
            queryset,
            model=Pict,
            upload_to=pict_photo_upload_to,
            source_value=lambda picture: picture.alt,
            unchanged_description='описанию и номеру',
            log_description='изображение каталога',
        )

    def get_html_photo(self, object):
        return self.render_image_preview(
            object.photo,
            alt_text=f'Изображение № {object.name}',
            width=150,
            geometry=CATALOG_ADMIN_THUMBNAIL_GEOMETRY,
        )

    def get_html_photo_fields(self, object):
        return self.render_image_preview(
            object.photo,
            alt_text=f'Изображение № {object.name}',
            width=400,
            geometry=CATALOG_ADMIN_THUMBNAIL_GEOMETRY,
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
                (
                    work.photo.url,
                    work.name,
                    self.get_cached_preview_url(
                        work.photo,
                        FINISHED_WORK_ADMIN_THUMBNAIL_GEOMETRY,
                    ),
                    work.name,
                )
                for work in works
            ),
        )

    get_html_photo.short_description = 'Миниатюра'
    get_html_photo_fields.short_description = 'Миниатюра'
    get_list_category.short_description = 'Категории'
    get_list_color.short_description = 'Цвета'


class CategoryAdmin(SeoAdminMixin, admin.ModelAdmin):
    list_display = ['drag_handle', 'cat', 'slug']
    list_display_links = ['cat']
    sortable_by = []
    search_fields = ['cat', *SEO_LANDING_FIELDS]
    prepopulated_fields = {"slug": ("cat",)}
    ordering = ['position', 'pk']
    fieldsets = (
        (None, {'fields': ('cat', 'slug')}),
        ('SEO и текст страницы', {'fields': SEO_LANDING_FIELDS}),
    )

    class Media:
        css = {'all': (
            'skinali/css/admin-order.css',
            'skinali/css/admin-category-order.css',
            'skinali/css/admin-seo-landing-fields.css',
        )}
        js = ('skinali/js/admin-order.js', 'skinali/js/admin-category-order.js')

    def get_list_display(self, request):
        if self.has_change_permission(request):
            return self.list_display
        return ['cat', 'slug']

    def get_urls(self):
        return [
            path(
                'reorder/',
                self.admin_site.admin_view(self.reorder_view),
                name='pict_category_reorder',
            ),
        ] + super().get_urls()

    @admin.display(description='Порядок')
    def drag_handle(self, obj):
        return format_html(
            '<button type="button" class="category-order-handle admin-order-handle" '
            'draggable="true" data-category-id="{}" '
            'title="Перетащить категорию" '
            'aria-label="Изменить порядок категории {}">⋮⋮</button>',
            obj.pk,
            obj.cat,
        )

    def reorder_view(self, request):
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])
        if not self.has_change_permission(request):
            raise PermissionDenied

        return reorder_admin_objects(request, Category.objects.only('pk', 'position'))

    def save_model(self, request, obj, form, change):
        if not change and obj.position == 0:
            last_position = (
                Category.objects.order_by('-position')
                .values_list('position', flat=True)
                .first()
                or 0
            )
            obj.position = last_position + 1
        super().save_model(request, obj, form, change)


class TagAliasInline(admin.TabularInline):
    model = TagAlias
    extra = 1
    fields = ['alias', 'normalized_alias']
    readonly_fields = ['normalized_alias']


class TagPictAdmin(SeoAdminMixin, admin.ModelAdmin):
    change_list_template = 'admin/pict/tagpict/change_list.html'
    list_display = ['tag', 'normalized_tag', 'slug', 'get_search_aliases']
    list_display_links = ['tag']
    search_fields = [
        'tag',
        'normalized_tag',
        'search_aliases__alias',
        'search_aliases__normalized_alias',
        *SEO_LANDING_FIELDS,
    ]
    prepopulated_fields = {"slug": ("tag",)}
    readonly_fields = ['normalized_tag']
    inlines = [TagAliasInline]
    fieldsets = (
        (None, {'fields': ('tag', 'normalized_tag', 'slug')}),
        ('SEO и текст страницы', {'fields': SEO_LANDING_FIELDS}),
    )

    class Media:
        css = {'all': ('skinali/css/admin-seo-landing-fields.css',)}

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('search_aliases')

    def changelist_view(self, request, extra_context=None):
        context = dict(extra_context or {})
        settings_admin = self.admin_site._registry.get(CatalogSearchSettings)
        if settings_admin and settings_admin.has_view_permission(request):
            context['catalog_search_settings_url'] = reverse(
                f'{self.admin_site.name}:sitecontent_catalogsearchsettings_changelist',
            )
        return super().changelist_view(request, extra_context=context)

    @admin.display(description='Синонимы')
    def get_search_aliases(self, obj):
        return ', '.join(alias.alias for alias in obj.search_aliases.all()) or '—'


class ColorAdmin(admin.ModelAdmin):
    list_display = ['color', 'slug_color']
    list_display_links = ['color']
    ordering = ['color']
    # prepopulated_fields = {"slug_color": ("color",)}


@admin.register(FinishedWork)
class FinishedWorkAdmin(
    AdminImagePreviewMixin,
    AdminPhotoRenameMixin,
    admin.ModelAdmin,
):
    form = FinishedWorkAdminForm
    list_display = [
        'name',
        'is_published',
        'get_html_photo',
        'glass_type',
        'skinali_type',
        'created_at',
        'updated_at',
    ]
    list_editable = ['is_published']
    list_display_links = ['name']
    list_filter = [
        FinishedWorkNeedsAttentionFilter,
        'is_published',
        'glass_type',
        'skinali_type',
        'created_at',
    ]
    search_fields = ['name', 'description', '=catalog_image__name']
    autocomplete_fields = ['catalog_image']
    readonly_fields = ['get_html_photo_fields', 'created_at', 'updated_at']
    fields = [
        'name',
        'is_published',
        'glass_type',
        'skinali_type',
        'catalog_image',
        'paint_color',
        'description',
        'photo',
        'get_html_photo_fields',
        'created_at',
        'updated_at',
    ]
    ordering = ['-created_at', '-id']
    list_per_page = 20
    actions = ['rename_photos_from_name']

    class Media(AdminImagePreviewMixin.Media):
        js = AdminImagePreviewMixin.Media.js + (
            'skinali/js/admin-finished-work.js',
        )

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related('catalog_image')
            .prefetch_related('catalog_image__cat')
        )

    @admin.action(
        description='Переименовать файлы по имени',
        permissions=['change'],
    )
    def rename_photos_from_name(self, request, queryset):
        self.rename_photo_files(
            request,
            queryset,
            model=FinishedWork,
            upload_to=finished_work_photo_upload_to,
            source_value=lambda work: work.name,
            unchanged_description='имени',
            log_description='фотографию готовой работы',
        )

    @admin.display(description='Миниатюра')
    def get_html_photo(self, obj):
        return self.render_image_preview(
            obj.photo,
            alt_text=obj.name,
            width=80,
            geometry=FINISHED_WORK_ADMIN_THUMBNAIL_GEOMETRY,
        )

    @admin.display(description='Миниатюра')
    def get_html_photo_fields(self, obj):
        return self.render_image_preview(
            obj.photo,
            alt_text=obj.name,
            width=200,
            geometry=FINISHED_WORK_ADMIN_THUMBNAIL_GEOMETRY,
        )

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
