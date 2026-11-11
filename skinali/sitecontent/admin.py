from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Max
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join
from django.utils import timezone
from skinali.admin_mixins import (
    SingletonAdminMixin as SingletonSiteContentAdminMixin,
    SuperuserAdminMixin as SuperuserSiteContentAdminMixin,
)
from skinali.admin_order import reorder_admin_objects

from .admin_seo import SeoAdminMixin
from .article_media import prepare_article_image
from .forms import (
    ArticleAdminForm, IntegrationAdminForm, PriceTableRowForm, PriceTableRowFormSet,
)
from .models import (
    Article, ArticleImage, CatalogSearchSettings, Integration, IntegrationRevision, MenuItem, PriceTable,
    PriceTableRow, SiteMenu, SitePage,
)


@admin.register(CatalogSearchSettings)
class CatalogSearchSettingsAdmin(SingletonSiteContentAdminMixin, admin.ModelAdmin):
    fieldsets = (
        ('Шапка сайта', {'fields': ('header_schedule', 'header_menu_item')}),
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
    search_fields = ('menu_item__title', 'seo_title', 'seo_description')
    actions = None

    class Media:
        css = {'all': ('skinali/css/admin-seo-landing-fields.css',)}

    @admin.display(description='Страница', ordering='code')
    def page_name(self, obj):
        return obj.navigation_title

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('menu_item')

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


class SuperuserIntegrationAdminMixin(SuperuserSiteContentAdminMixin):
    def has_delete_permission(self, request, obj=None):
        # Отключение сохраняет историю и позволяет вернуть интеграцию позже.
        return False


@admin.register(Integration)
class IntegrationAdmin(SuperuserIntegrationAdminMixin, admin.ModelAdmin):
    form = IntegrationAdminForm
    list_display = ['name', 'is_enabled', 'position', 'updated_at', 'versions_link']
    list_filter = ['is_enabled']
    search_fields = ['name', 'description']
    list_per_page = 30
    readonly_fields = ['updated_at', 'versions_link']
    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'is_enabled', 'position', 'page_paths'),
            'description': 'Код применяется к публичным страницам сразу после сохранения включённой интеграции. '
                           'Вставляйте код только доверенных сервисов. Меньшее число порядка подключается раньше.',
        }),
        ('Код в head', {'fields': ('head_html',)}),
        ('Код в начале body', {'fields': ('body_start_html',)}),
        ('Код в конце body', {'fields': ('body_end_html',)}),
        ('История', {'fields': ('updated_at', 'versions_link')}),
    )

    @admin.display(description='Версии')
    def versions_link(self, obj):
        if not obj.pk:
            return 'История появится после сохранения.'
        return format_html(
            '<a href="{}?integration__id__exact={}">Открыть историю версий</a>',
            reverse('admin:sitecontent_integrationrevision_changelist', current_app=self.admin_site.name), obj.pk,
        )

    def save_model(self, request, obj, form, change):
        obj.save_with_revision(request.user, 'Изменение' if change else 'Создание')


@admin.register(IntegrationRevision)
class IntegrationRevisionAdmin(SuperuserIntegrationAdminMixin, admin.ModelAdmin):
    list_display = ['__str__', 'integration', 'created_at', 'author', 'note']
    list_select_related = ['integration', 'author']
    list_per_page = 30
    fields = ['integration', 'created_at', 'author', 'note', 'snapshot_display', 'restore_link']
    readonly_fields = fields
    actions = None

    def get_model_perms(self, request):
        # Версии открываются из интеграции и не создают лишний раздел главного меню.
        return {}

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_urls(self):
        return [path('<int:object_id>/restore/', self.admin_site.admin_view(self.restore_view),
                     name='sitecontent_integrationrevision_restore')] + super().get_urls()

    @admin.display(description='Сохранённые настройки')
    def snapshot_display(self, obj):
        # format_html_join экранирует значения: HTML/JS из снимка в admin не исполняется.
        return format_html_join('', '<p><strong>{}</strong></p><pre style="white-space: pre-wrap">{}</pre>', (
            (Integration._meta.get_field(field).verbose_name, obj.snapshot[field])
            for field in Integration.SNAPSHOT_FIELDS
        ))

    @admin.display(description='Восстановление')
    def restore_link(self, obj):
        return format_html(
            '<a href="{}">Восстановить эту версию…</a>',
            reverse('admin:sitecontent_integrationrevision_restore', args=[obj.pk], current_app=self.admin_site.name),
        )

    def restore_view(self, request, object_id):
        if not self.has_module_permission(request):
            raise PermissionDenied
        if request.method not in ('GET', 'POST'):
            return HttpResponseNotAllowed(['GET', 'POST'])
        revision = get_object_or_404(IntegrationRevision.objects.select_related('integration'), pk=object_id)
        integration_url = reverse(
            'admin:sitecontent_integration_change', args=[revision.integration_id], current_app=self.admin_site.name,
        )
        if request.method == 'POST':
            with transaction.atomic():
                integration = revision.restore(request.user)
                self.log_change(request, integration, f'Восстановлена версия № {revision.pk}')
            self.message_user(request, 'Версия восстановлена. Текущее состояние сохранено в новой версии.')
            return redirect(integration_url)
        request.current_app = self.admin_site.name
        return TemplateResponse(request, 'admin/sitecontent/integration/restore.html', {
            **self.admin_site.each_context(request),
            'title': f'Восстановить версию № {revision.pk}',
            'opts': Integration._meta,
            'revision': revision,
            'snapshot_display': self.snapshot_display(revision),
            'integration_url': integration_url,
        })
