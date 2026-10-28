from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Max, Q
from django.shortcuts import redirect
from django.urls import path, reverse
from django.http import JsonResponse, HttpResponseNotAllowed
from django.utils.html import format_html, format_html_join
from django.utils import timezone
from skinali.admin_mixins import (
    SingletonAdminMixin as SingletonSiteContentAdminMixin,
    SuperuserAdminMixin as SuperuserSiteContentAdminMixin,
)
from skinali.admin_order import reorder_admin_objects
from pict.services.contact_delivery import enqueue_connection_test, retry_failed_deliveries
from pict.services.delivery_errors import DeliveryConfigurationError

from .forms import ArticleAdminForm, LeadConnectionForm, PriceTableRowForm, PriceTableRowFormSet
from .admin_seo import SeoAdminMixin
from .models import (
    Article, ArticleImage, CatalogSearchSettings, LeadConnection, MenuItem, PriceTable,
    PriceTableRow, SiteMenu, SitePage,
)
from .article_media import prepare_article_image


@admin.register(CatalogSearchSettings)
class CatalogSearchSettingsAdmin(SingletonSiteContentAdminMixin, admin.ModelAdmin):
    fieldsets = (
        ('Поиск по каталогу', {'fields': ('use_lemmatization',)}),
    )
    actions = None

    def has_add_permission(self, request):
        return False


class MenuItemInline(admin.TabularInline):
    model = MenuItem
    extra = 1
    fields = ('position', 'title', 'url', 'open_in_new_tab', 'is_visible')
    ordering = ('position', 'pk')


@admin.register(SitePage)
class SitePageAdmin(SuperuserSiteContentAdminMixin, SeoAdminMixin, admin.ModelAdmin):
    fields = ('seo_title', 'seo_description')
    list_display = ('page_name', 'seo_title', 'seo_description')
    search_fields = ('seo_title', 'seo_description')
    actions = None

    class Media:
        css = {'all': ('skinali/css/admin-seo-landing-fields.css',)}

    @admin.display(description='Страница', ordering='code')
    def page_name(self, obj):
        return obj.get_code_display()

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SiteMenu)
class SiteMenuAdmin(SingletonSiteContentAdminMixin, admin.ModelAdmin):
    fields = ('name',)
    readonly_fields = ('name',)
    inlines = (MenuItemInline,)
    actions = None

    def has_add_permission(self, request):
        return super().has_add_permission(request) and not SiteMenu.objects.exists()


class PriceTableRowInline(SuperuserSiteContentAdminMixin, admin.TabularInline):
    model = PriceTableRow
    form = PriceTableRowForm
    formset = PriceTableRowFormSet
    fields = ('drag_handle', 'description', 'price', 'position')
    readonly_fields = ('drag_handle',)
    extra = 1

    def has_add_permission(self, request, obj=None):
        return self.has_module_permission(request)

    @admin.display(description='Порядок')
    def drag_handle(self, obj=None):
        return format_html(
            '<button type="button" class="admin-order-handle" data-price-row-order '
            'title="{}" aria-label="{}">⋮⋮</button>',
            'Перетащить строку; ↑ и ↓ на клавиатуре', 'Изменить порядок строки',
        )

    def has_delete_permission(self, request, obj=None):
        return self.has_module_permission(request)


@admin.register(PriceTable)
class PriceTableAdmin(SuperuserSiteContentAdminMixin, admin.ModelAdmin):
    list_display = ('drag_handle', 'title', 'is_published', 'row_count')
    list_display_links = ('title',)
    list_filter = ('is_published',)
    search_fields = ('title',)
    sortable_by = ()
    ordering = ('position', 'pk')
    inlines = (PriceTableRowInline,)
    fields = ('title', 'service_column', 'price_column', 'note', 'is_published')

    class Media:
        css = {'all': ('skinali/css/admin-order.css', 'sitecontent/css/admin-price-tables.css')}
        js = ('skinali/js/admin-order.js', 'sitecontent/js/admin-price-tables.js')

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_row_count=Count('rows'))

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == 'note':
            kwargs['widget'] = forms.Textarea(attrs={'rows': 3, 'cols': 70})
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    @admin.display(description='Строк')
    def row_count(self, obj):
        return obj._row_count

    @admin.display(description='Порядок')
    def drag_handle(self, obj):
        return format_html(
            '<button type="button" class="admin-order-handle" data-price-table-id="{}" '
            'data-reorder-url="{}" title="Перетащить таблицу; ↑ и ↓ на клавиатуре" '
            'aria-label="Изменить порядок таблицы {}">⋮⋮</button>',
            obj.pk, reverse(f'{self.admin_site.name}:sitecontent_pricetable_reorder'), obj.title,
        )

    def has_delete_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def get_urls(self):
        return [path(
            'reorder/', self.admin_site.admin_view(self.reorder_view),
            name='sitecontent_pricetable_reorder',
        )] + super().get_urls()

    def reorder_view(self, request):
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])
        if not self.has_change_permission(request):
            raise PermissionDenied

        def on_reorder(objects, using):
            from pict.signals import touch_site_pages

            touch_site_pages((SitePage.Code.PRICE,), changed_at=timezone.now(), using=using)
            for obj in objects:
                self.log_change(request, obj, 'Изменён порядок таблиц страницы «Цена».')

        return reorder_admin_objects(
            request, PriceTable.objects.all(), on_reorder=on_reorder,
        )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.position = (PriceTable.objects.aggregate(last=Max('position'))['last'] or 0) + 1
        super().save_model(request, obj, form, change)


@admin.register(Article)
class ArticleAdmin(SuperuserSiteContentAdminMixin, SeoAdminMixin, admin.ModelAdmin):
    form = ArticleAdminForm
    list_display = ('title', 'is_published', 'published_at', 'updated_at')
    list_editable = ('is_published',)
    list_display_links = ('title',)
    list_filter = ('is_published',)
    search_fields = ('title', 'summary')
    list_per_page = 30
    readonly_fields = ('slug',)
    fieldsets = (
        (None, {'fields': ('title', 'slug', 'summary', 'cover', 'body')}),
        ('Публикация', {'fields': ('is_published', 'published_at')}),
        ('SEO', {'fields': ('seo_title', 'seo_description')}),
    )

    class Media:
        css = {'all': ('skinali/css/admin-seo-landing-fields.css',)}

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields if obj else ()

    def has_delete_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def get_urls(self):
        return [path(
            'upload-image/', self.admin_site.admin_view(self.upload_image),
            name='sitecontent_article_upload_image',
        )] + super().get_urls()

    def upload_image(self, request):
        if not self.has_add_permission(request):
            return JsonResponse({'error': 'Недостаточно прав.'}, status=403)
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])
        upload = request.FILES.get('image')
        if upload is None:
            return JsonResponse({'error': 'Выберите изображение.'}, status=400)
        try:
            prepared = prepare_article_image(upload)
        except ValidationError as error:
            return JsonResponse({'error': ' '.join(error.messages)}, status=400)
        image = ArticleImage.objects.create(image=prepared)
        return JsonResponse({'url': image.image.url}, status=201)


@admin.register(LeadConnection)
class LeadConnectionAdmin(SuperuserSiteContentAdminMixin, admin.ModelAdmin):
    form = LeadConnectionForm
    change_form_template = 'admin/sitecontent/leadconnection/change_form.html'
    list_display = ('name', 'provider', 'recipient_summary', 'is_enabled', 'connection_status', 'pending_count', 'failed_count', 'last_success')
    list_filter = ('provider', 'is_enabled')
    search_fields = ('name',)
    readonly_fields = ('connection_status', 'delivery_summary', 'last_test_result', 'updated_at')
    list_per_page = 50

    class Media:
        js = ('sitecontent/js/lead-connection.js',)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _pending=Count('deliveries', filter=Q(deliveries__status__in=['pending', 'processing', 'retry'])),
            _failed=Count('deliveries', filter=Q(deliveries__status='failed', deliveries__contact_request__isnull=False)),
            _last_success=Max('deliveries__sent_at'),
        )

    def get_readonly_fields(self, request, obj=None):
        return (*self.readonly_fields, 'provider') if obj else self.readonly_fields

    def get_fieldsets(self, request, obj=None):
        fieldsets = [
            ('Основное', {'fields': ('name', 'provider', 'is_enabled')}),
            ('Получатели и правила', {'fields': ('recipients', 'all_request_types', 'request_types')}),
        ]
        if obj is None or obj.provider == LeadConnection.Provider.TELEGRAM:
            fieldsets.append(('Telegram', {'fields': ('use_environment', 'telegram_token', 'proxy_url', 'clear_proxy'), 'classes': ('lead-telegram',)}))
        if obj is None or obj.provider == LeadConnection.Provider.EMAIL:
            fieldsets.append(('Email', {'fields': ('smtp_host', 'smtp_port', 'smtp_security', 'smtp_username', 'smtp_password', 'clear_smtp_password', 'from_email', 'from_name'), 'classes': ('lead-email',)}))
        fieldsets.extend([
            ('Дополнительные настройки', {'fields': ('connect_timeout', 'read_timeout'), 'classes': ('collapse',), 'description': 'Для SMTP используется тайм-аут ответа. Настройки Telegram из окружения имеют собственные тайм-ауты.'}),
            ('Проверка и состояние', {'fields': ('connection_status', 'delivery_summary', 'last_test_result', 'updated_at')}),
        ])
        return fieldsets

    def has_delete_permission(self, request, obj=None):
        return self.has_module_permission(request) and (obj is None or not obj.deliveries.exists())

    def save_model(self, request, obj, form, change):
        obj.configuration_error = ''
        super().save_model(request, obj, form, change)

    @admin.display(description='Получатели')
    def recipient_summary(self, obj):
        return ', '.join(obj.get_recipients()) or 'Не указаны'

    @admin.display(description='Состояние')
    def connection_status(self, obj):
        if obj.configuration_error:
            return obj.configuration_error
        if not obj.is_enabled:
            return 'Выключено; обычные отправки приостановлены'
        if getattr(obj, '_failed', 0):
            return 'Есть ошибки отправки'
        if getattr(obj, '_last_success', None):
            return 'Есть успешные отправки'
        return 'Ожидает отправки или проверки'

    @admin.display(description='В очереди', ordering='_pending')
    def pending_count(self, obj):
        return obj._pending

    @admin.display(description='Ошибок', ordering='_failed')
    def failed_count(self, obj):
        return obj._failed

    @admin.display(description='Последняя успешная отправка', ordering='_last_success')
    def last_success(self, obj):
        return timezone.localtime(obj._last_success).strftime('%d.%m.%Y %H:%M') if obj._last_success else '—'

    @admin.display(description='Доставки')
    def delivery_summary(self, obj):
        if not obj.pk:
            return 'Сохраните подключение.'
        return format_html(
            'В очереди: {}. Ошибок: {}. Последняя успешная отправка: {}. <a href="{}?deliveries__connection__id__exact={}">Открыть заявки</a>',
            obj._pending, obj._failed, self.last_success(obj), reverse('admin:pict_contactrequest_changelist'), obj.pk,
        )

    @admin.display(description='Последняя проверка')
    def last_test_result(self, obj):
        if not obj.pk:
            return 'Проверка ещё не выполнялась.'
        latest = obj.deliveries.filter(test_batch_id__isnull=False).order_by('-created_at', '-pk').first()
        if latest is None:
            return 'Проверка ещё не выполнялась.'
        return format_html_join('', '<div>{} — {} ({}) {}</div>', (
            (delivery.recipient, delivery.get_status_display(), timezone.localtime(delivery.updated_at).strftime('%d.%m.%Y %H:%M'), delivery.last_error)
            for delivery in obj.deliveries.filter(test_batch_id=latest.test_batch_id).order_by('pk')
        ))

    def handle_delivery_action(self, request, obj):
        if '_test_connection' in request.POST:
            try:
                count = enqueue_connection_test(obj)
            except (ValidationError, DeliveryConfigurationError) as error:
                text = '; '.join(error.messages) if isinstance(error, ValidationError) else str(error)
                self.message_user(request, text, level=messages.ERROR)
            else:
                self.log_change(request, obj, 'Запрошена тестовая отправка.')
                self.message_user(request, f'Тестовых сообщений в очереди: {count}. Результат появится после запуска обработчика; обновите страницу.')
        elif '_retry_deliveries' in request.POST:
            count = retry_failed_deliveries(obj.deliveries.filter(contact_request__isnull=False))
            self.log_change(request, obj, f'Повторно поставлено доставок: {count}.')
            self.message_user(request, f'Повторно поставлено доставок: {count}. Выключенные подключения ожидают включения.')
        else:
            return None
        return redirect('admin:sitecontent_leadconnection_change', obj.pk)

    def response_add(self, request, obj, post_url_continue=None):
        return self.handle_delivery_action(request, obj) or super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        return self.handle_delivery_action(request, obj) or super().response_change(request, obj)
