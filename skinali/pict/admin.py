from django.contrib import admin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from pict.forms import PictAdminForm
from pict.models import (
    Category,
    Color,
    ContactRequest,
    ContactRequestDelivery,
    FinishedWork,
    Pict,
    TagPict,
)


class AdminImagePreviewMixin:
    @staticmethod
    def render_image_preview(image_field, *, alt_text, width):
        """Формирует одинаковую кликабельную миниатюру для всех admin-таблиц."""
        if not image_field:
            return '—'
        return format_html(
            '<a class="admin-image-preview-link" href="{}" data-image-preview>'
            '<img src="{}" alt="{}" width="{}"></a>',
            image_field.url,
            image_field.url,
            alt_text,
            width,
        )

    class Media:
        css = {'all': ('skinali/css/admin-image-preview.css',)}
        js = ('skinali/js/admin-image-preview.js',)


class PictAdmin(AdminImagePreviewMixin, admin.ModelAdmin):
    list_per_page = 20
    list_display = ['name', 'is_published', 'get_html_photo', 'get_list_category', 'get_list_color']
    list_editable = ['is_published']
    list_display_links = ['name']
    search_fields = ['=name', 'tags__tag']
    list_filter = ['is_published', 'time_update', 'cat__cat', 'color__color']
    fields = [
        'name',
        'is_published',
        'alt',
        'photo',
        'get_html_photo_fields',
        'time_update',
        'color',
        'cat',
        'tags',
    ]
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
        return self.render_image_preview(
            object.photo,
            alt_text=f'Изображение № {object.name}',
            width=150,
        )

    def get_html_photo_fields(self, object):
        return self.render_image_preview(
            object.photo,
            alt_text=f'Изображение № {object.name}',
            width=400,
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
        'is_published',
        'get_html_photo',
        'get_catalog_image_number',
        'get_catalog_categories',
        'created_at',
    ]
    list_editable = ['is_published']
    list_display_links = ['name']
    list_filter = ['is_published', 'created_at']
    search_fields = ['name', 'description', '=catalog_image__name']
    autocomplete_fields = ['catalog_image']
    readonly_fields = ['get_html_photo_fields', 'created_at']
    fields = [
        'name',
        'is_published',
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
        return self.render_image_preview(
            obj.photo,
            alt_text=obj.name,
            width=80,
        )

    @admin.display(description='Миниатюра')
    def get_html_photo_fields(self, obj):
        return self.render_image_preview(
            obj.photo,
            alt_text=obj.name,
            width=200,
        )

    @admin.display(description='Номер изображения', ordering='catalog_image__name')
    def get_catalog_image_number(self, obj):
        return obj.catalog_image.name if obj.catalog_image else '—'

    @admin.display(description='Категории')
    def get_catalog_categories(self, obj):
        if not obj.catalog_image:
            return '—'
        return ', '.join(category.cat for category in obj.catalog_image.cat.all()) or '—'


class ContactRequestDeliveryInline(admin.TabularInline):
    """Показывает служебные данные доставки прямо в карточке заявки."""

    model = ContactRequestDelivery
    extra = 0
    can_delete = False
    fields = [
        'channel',
        'status',
        'attempts',
        'next_attempt_at',
        'sent_at',
        'external_message_id',
        'last_error',
    ]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ContactRequest)
class ContactRequestAdmin(AdminImagePreviewMixin, admin.ModelAdmin):
    request_fields_by_type = {
        ContactRequest.RequestType.CALLBACK: [
            'name',
            'phone',
        ],
        ContactRequest.RequestType.QUESTION: [
            'name',
            'phone',
            'question',
        ],
        ContactRequest.RequestType.EMAIL_MESSAGE: [
            'name',
            'email',
            'comment',
        ],
        ContactRequest.RequestType.IMAGE_PURCHASE: [
            'name',
            'email',
            'comment',
            'image_number',
            'get_catalog_image_thumbnail',
        ],
    }
    service_fields = ['request_type', 'get_delivery_status', 'created_at']
    list_display = [
        'get_request_name',
        'phone',
        'email',
        'request_type',
        'get_delivery_channel',
        'get_delivery_status',
        'created_at',
    ]
    # Ссылку формируем сами, чтобы CSS-класс просмотра находился на самом <a>.
    list_display_links = None
    list_filter = ['request_type', 'created_at']
    search_fields = ['name', 'phone', 'email', 'question', 'comment', '=image_number']
    readonly_fields = [
        'get_catalog_image_thumbnail',
        'get_delivery_status',
        'created_at',
    ]
    add_fields = [
        'request_type',
        'name',
        'phone',
        'email',
        'question',
        'comment',
        'catalog_image',
        'image_number',
        'get_catalog_image_thumbnail',
        'created_at',
    ]
    ordering = ['-created_at', '-id']
    list_per_page = 50
    inlines = [ContactRequestDeliveryInline]
    actions = [
        'queue_missing_telegram_deliveries',
        'retry_failed_telegram_deliveries',
    ]

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related('catalog_image')
            .prefetch_related('deliveries')
        )

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            fields.append('request_type')
        return fields

    def get_fields(self, request, obj=None):
        if obj is None:
            return self.add_fields
        request_fields = self.request_fields_by_type.get(obj.request_type)
        if request_fields is None:
            return self.add_fields
        return [self.service_fields[0], *request_fields, *self.service_fields[1:]]

    def change_view(self, request, object_id, form_url='', extra_context=None):
        response = super().change_view(request, object_id, form_url, extra_context)
        if request.method == 'GET' and response.status_code == 200:
            ContactRequest.objects.filter(
                pk=object_id,
                viewed_at__isnull=True,
            ).update(viewed_at=timezone.now())
        return response

    @admin.display(description='Имя', ordering='name')
    def get_request_name(self, obj):
        change_url = reverse('admin:pict_contactrequest_change', args=[obj.pk])
        if obj.viewed_at:
            return format_html(
                '<a class="contact-request-name--viewed" href="{}">{}</a>',
                change_url,
                obj.name,
            )
        return format_html('<a href="{}">{}</a>', change_url, obj.name)

    @staticmethod
    def get_telegram_delivery(obj):
        return next(
            (
                delivery for delivery in obj.deliveries.all()
                if delivery.channel == ContactRequestDelivery.Channel.TELEGRAM
            ),
            None,
        )

    @admin.display(description='Канал')
    def get_delivery_channel(self, obj):
        delivery = self.get_telegram_delivery(obj)
        return delivery.get_channel_display() if delivery else '—'

    @admin.display(description='Статус')
    def get_delivery_status(self, obj):
        delivery = self.get_telegram_delivery(obj)
        return delivery.get_status_display() if delivery else 'Не поставлено в очередь'

    @admin.display(description='Миниатюра')
    def get_catalog_image_thumbnail(self, obj):
        if not obj or not obj.catalog_image:
            return '—'
        return self.render_image_preview(
            obj.catalog_image.photo,
            alt_text=f'Изображение № {obj.image_number or obj.catalog_image.name}',
            width=150,
        )

    @admin.action(description='Поставить выбранные заявки в очередь Telegram')
    def queue_missing_telegram_deliveries(self, request, queryset):
        created_count = 0
        for contact_request_id in queryset.values_list('pk', flat=True):
            _, created = ContactRequestDelivery.objects.get_or_create(
                contact_request_id=contact_request_id,
                channel=ContactRequestDelivery.Channel.TELEGRAM,
            )
            created_count += int(created)
        self.message_user(request, f'Создано доставок: {created_count}.')

    @admin.action(description='Повторить выбранные неотправленные доставки')
    def retry_failed_telegram_deliveries(self, request, queryset):
        updated = ContactRequestDelivery.objects.filter(
            contact_request__in=queryset,
            channel=ContactRequestDelivery.Channel.TELEGRAM,
            status__in=[
                ContactRequestDelivery.Status.RETRY,
                ContactRequestDelivery.Status.FAILED,
            ],
        ).update(
            status=ContactRequestDelivery.Status.RETRY,
            attempts=0,
            next_attempt_at=timezone.now(),
            processing_started_at=None,
            last_error='',
            updated_at=timezone.now(),
        )
        self.message_user(request, f'Поставлено в очередь: {updated}.')


admin.site.register(Pict, PictAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(Color, ColorAdmin)
admin.site.register(TagPict, TagPictAdmin)
