from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Max, Q
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from pict.admin import AdminImagePreviewMixin
from pict.services.contact_delivery import enqueue_connection_test, enqueue_contact_request, retry_failed_deliveries
from pict.services.delivery_errors import DeliveryConfigurationError
from skinali.admin_mixins import SuperuserAdminMixin

from .forms import LeadConnectionForm
from .models import ContactRequest, ContactRequestDelivery, LeadConnection


class ContactRequestDeliveryInline(admin.TabularInline):
    """Показывает служебные данные доставки прямо в карточке заявки."""

    model = ContactRequestDelivery
    extra = 0
    can_delete = False
    fields = [
        'connection',
        'channel',
        'recipient',
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
        ContactRequest.RequestType.QUIZ: [
            'name',
            'phone',
            'get_quiz_answers',
        ],
        ContactRequest.RequestType.CALCULATOR_ORDER: [
            'name', 'phone', 'get_calculation_link',
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
    list_filter = ['request_type', 'created_at', ('deliveries__connection', admin.RelatedOnlyFieldListFilter)]
    search_fields = ['name', 'phone', 'email', 'question', 'comment', '=image_number']
    readonly_fields = [
        'get_catalog_image_thumbnail',
        'get_quiz_answers',
        'get_calculation_link',
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
        'mark_selected_as_viewed',
        'queue_missing_deliveries',
        'retry_failed_deliveries',
    ]

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related('catalog_image', 'quiz_submission')
            .prefetch_related('deliveries__connection')
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
            updated = ContactRequest.objects.filter(
                pk=object_id,
                viewed_at__isnull=True,
            ).update(viewed_at=timezone.now())
            if updated:
                # Контекст бокового меню формируется до отметки просмотра.
                if hasattr(request, '_unviewed_contact_request_count'):
                    del request._unviewed_contact_request_count
                response.context_data['available_apps'] = self.admin_site.get_app_list(request)
        return response

    @admin.display(description='Имя', ordering='name')
    def get_request_name(self, obj):
        change_url = reverse('admin:leads_contactrequest_change', args=[obj.pk], current_app=self.admin_site.name)
        if obj.viewed_at:
            return format_html(
                '<a class="contact-request-name--viewed" href="{}">{}</a>',
                change_url,
                obj.name,
            )
        return format_html('<a href="{}">{}</a>', change_url, obj.name)

    @admin.display(description='Каналы')
    def get_delivery_channel(self, obj):
        return ', '.join(sorted({delivery.get_channel_display() for delivery in obj.deliveries.all()})) or '—'

    @admin.display(description='Статус')
    def get_delivery_status(self, obj):
        deliveries = list(obj.deliveries.all())
        if not deliveries:
            return 'Не поставлено в очередь'
        if len({delivery.status for delivery in deliveries}) == 1:
            return deliveries[0].get_status_display()
        sent = sum(delivery.status == ContactRequestDelivery.Status.SENT for delivery in deliveries)
        failed = sum(delivery.status == ContactRequestDelivery.Status.FAILED for delivery in deliveries)
        return f'Отправлено {sent} из {len(deliveries)}; ошибок: {failed}'

    @admin.display(description='Миниатюра')
    def get_catalog_image_thumbnail(self, obj):
        if not obj or not obj.catalog_image:
            return '—'
        return self.render_image_preview(
            obj.catalog_image.photo,
            alt_text=f'Изображение № {obj.image_number or obj.catalog_image.name}',
            width=150,
        )

    @admin.display(description='Ответы квиза')
    def get_quiz_answers(self, obj):
        submission = getattr(obj, 'quiz_submission', None) if obj else None
        if submission is None:
            return '—'
        rows = (
            (
                answer.get('question', 'Вопрос'),
                answer.get('answer') or 'Не указано',
            )
            for answer in submission.answers
        )
        return format_html_join(
            '',
            '<div style="margin-bottom:10px"><strong>{}</strong><br>{}</div>',
            rows,
        )

    @admin.display(description='Ссылка на расчёт')
    def get_calculation_link(self, obj):
        if not obj or not obj.calculation_url:
            return '—'
        return format_html(
            '<a href="{}" target="_blank" rel="noopener noreferrer">Открыть расчёт</a>',
            obj.calculation_url,
        )

    @admin.action(description='Отправить выбранные заявки в активные подключения')
    def queue_missing_deliveries(self, request, queryset):
        created_count = sum(enqueue_contact_request(item) for item in queryset.iterator())
        self.message_user(request, f'Создано доставок: {created_count}.')

    @admin.action(description='Просмотреть выбранные заявки', permissions=['change'])
    def mark_selected_as_viewed(self, request, queryset):
        updated = queryset.filter(viewed_at__isnull=True).update(viewed_at=timezone.now())
        self.message_user(request, f'Отмечено как просмотренные: {updated}.')

    @admin.action(description='Повторить выбранные неотправленные доставки')
    def retry_failed_deliveries(self, request, queryset):
        updated = retry_failed_deliveries(ContactRequestDelivery.objects.filter(contact_request__in=queryset))
        self.message_user(request, f'Поставлено в очередь: {updated}.')


@admin.register(LeadConnection)
class LeadConnectionAdmin(SuperuserAdminMixin, admin.ModelAdmin):
    form = LeadConnectionForm
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
            obj._pending, obj._failed, self.last_success(obj), reverse('admin:leads_contactrequest_changelist', current_app=self.admin_site.name), obj.pk,
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
        return redirect(reverse('admin:leads_leadconnection_change', args=[obj.pk], current_app=self.admin_site.name))

    def response_add(self, request, obj, post_url_continue=None):
        return self.handle_delivery_action(request, obj) or super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        return self.handle_delivery_action(request, obj) or super().response_change(request, obj)
