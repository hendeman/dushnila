from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods

from skinali.admin_mixins import SingletonAdminMixin, SuperuserAdminMixin

from .models import CalculatorService, CalculatorSettings, CalculatorTariffs, DecorationType, GlassType, MeasurementUnit
from .calculation import calculate_price
from .forms import CalculationForm, CalculatorServiceForm, CalculatorServiceInlineForm, CalculatorSettingsAdminForm, CalculatorTariffsAdminForm, PanelFormSet


class PricedOptionAdmin(SuperuserAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'price_per_sqm', 'position', 'is_visible')
    list_display_links = ('name',)
    list_editable = ('price_per_sqm', 'position', 'is_visible')
    list_filter = ('is_visible',)
    search_fields = ('name',)
    fields = ('name', 'price_per_sqm', 'position', 'is_visible')
    list_per_page = 50
    actions = None

    def has_delete_permission(self, request, obj=None):
        return self.has_module_permission(request)


admin.site.register(GlassType, PricedOptionAdmin)
admin.site.register(DecorationType, PricedOptionAdmin)


@admin.register(MeasurementUnit)
class MeasurementUnitAdmin(SuperuserAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'symbol', 'position')
    list_editable = ('symbol', 'position')
    fields = ('name', 'symbol', 'position')
    search_fields = ('name', 'symbol')
    list_per_page = 50
    actions = None

    def has_delete_permission(self, request, obj=None):
        return self.has_module_permission(request)


class CalculatorServiceInline(SuperuserAdminMixin, admin.StackedInline):
    model = CalculatorService
    form = CalculatorServiceInlineForm
    template = 'admin/calculator/service_inline.html'
    fields = ('is_visible', 'price_per_unit', 'position')
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CalculatorService)
class CalculatorServiceAdmin(SuperuserAdminMixin, admin.ModelAdmin):
    form = CalculatorServiceForm
    actions = None
    fieldsets = (
        (None, {'fields': ('name', 'hint', 'visibility_label', 'price_label', 'is_visible', 'has_price', 'fixed_price', 'price_per_unit')}),
        ('Поле количества', {
            'fields': ('quantity_label', 'unit', 'max_quantity', 'use_panel_area', 'whole_quantity'),
            'description': 'Стоимость равна цене за единицу, умноженной на количество. Обозначение единицы — только подпись.',
        }),
    )

    def get_model_perms(self, request):
        return {}

    def save_model(self, request, obj, form, change):
        if not change:
            last_position = (CalculatorService.objects.filter(settings_id=obj.settings_id)
                             .order_by('-position').values_list('position', flat=True).first() or 0)
            obj.position = last_position + 1
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def tariffs_redirect(self):
        return redirect(reverse(f'{self.admin_site.name}:calculator_calculatortariffs_change', args=[CalculatorTariffs.CODE]))

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_permission(request):
            raise PermissionDenied
        return self.tariffs_redirect()

    def response_add(self, request, obj, post_url_continue=None):
        response = super().response_add(request, obj, post_url_continue)
        return response if any(key in request.POST for key in ('_continue', '_addanother', '_popup')) else self.tariffs_redirect()

    def response_change(self, request, obj):
        response = super().response_change(request, obj)
        return response if any(key in request.POST for key in ('_continue', '_addanother', '_popup')) else self.tariffs_redirect()

    def response_delete(self, request, obj_display, obj_id):
        super().response_delete(request, obj_display, obj_id)
        return self.tariffs_redirect()


class CalculatorCardAdmin(SingletonAdminMixin, admin.ModelAdmin):
    change_form_template = 'admin/calculator/change_form.html'
    actions = None

    def has_add_permission(self, request):
        return False

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        counterpart = self.counterpart_model._meta
        return super().changeform_view(request, object_id, form_url, extra_context={
            **(extra_context or {}),
            'counterpart_url': reverse(f'{self.admin_site.name}:calculator_{counterpart.model_name}_changelist'),
            'counterpart_label': counterpart.verbose_name_plural,
            'calculation_url': reverse(f'{self.admin_site.name}:calculator_calculatortariffs_calculate'),
        })


@admin.register(CalculatorSettings)
class CalculatorSettingsAdmin(CalculatorCardAdmin):
    counterpart_model = CalculatorTariffs
    form = CalculatorSettingsAdminForm
    fieldsets = (
        ('Отображение на сайте', {'fields': ('is_enabled',)}),
        ('Акционные настройки', {'fields': (
            'area_discount_percent', 'marketing_discount_percent', 'marketing_discount_description',
        )}),
    )

    def get_urls(self):
        return [path(
            'calculate/', self.admin_site.admin_view(self.admin_site.get_model_admin(CalculatorTariffs).calculate_view),
            name='calculator_calculatorsettings_calculate',
        )] + super().get_urls()


@admin.register(CalculatorTariffs)
class CalculatorTariffsAdmin(CalculatorCardAdmin):
    counterpart_model = CalculatorSettings
    form = CalculatorTariffsAdminForm
    inlines = (CalculatorServiceInline,)
    fieldsets = (
        ('Размеры панелей', {'fields': ('panels_hint',)}),
        ('Стекло', {
            'fields': ('show_glass_type', 'default_glass_type', 'glass_type_hint'),
            'description': 'Тип стекла выбирается сразу для всех панелей. Цены задаются в справочнике «Типы стекла».',
        }),
        ('Декорирование', {
            'fields': ('show_decoration_type', 'default_decoration_type', 'decoration_type_hint'),
            'description': 'Декорирование общее для всех панелей. Доплаты за м² задаются в справочнике «Декорирование».',
        }),
        ('Подъём по лестнице', {
            'fields': (
                'show_stair_lifting', 'stair_lifting_min_price',
                'stair_lifting_price_per_panel_floor', 'stair_lifting_rules', 'stair_lifting_hint',
            ),
            'description': (
                'Стандартный подъём включён в стоимость. Для лестницы отдельно указываются '
                'этаж и количество панелей в пределах сохранённой таблицы. Доплата прибавляется к стандартной стоимости '
                'только за этажи выше включённого порога.'
            ),
        }),
    )

    def get_urls(self):
        return [path(
            'calculate/', self.admin_site.admin_view(self.calculate_view),
            name='calculator_calculatortariffs_calculate',
        )] + super().get_urls()

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        return super().changeform_view(request, object_id, form_url, extra_context={
            **(extra_context or {}),
            'units_url': reverse(f'{self.admin_site.name}:calculator_measurementunit_changelist'),
            'service_add_url': reverse(f'{self.admin_site.name}:calculator_calculatorservice_add'),
            'service_change_url_name': f'{self.admin_site.name}:calculator_calculatorservice_change',
            'service_delete_url_name': f'{self.admin_site.name}:calculator_calculatorservice_delete',
        })

    @method_decorator(require_http_methods(['GET', 'POST']))
    def calculate_view(self, request):
        if not self.has_view_permission(request):
            raise PermissionDenied
        settings = get_object_or_404(
            CalculatorTariffs.objects.select_related('default_glass_type', 'default_decoration_type'),
            pk=CalculatorTariffs.CODE,
        )
        data = request.POST if request.method == 'POST' else None
        form = CalculationForm(data, settings=settings)
        panels = PanelFormSet(data, prefix='panels')
        result = None
        if data is not None:
            form_valid = form.is_valid()
            panels_valid = panels.is_valid()
            if form_valid and panels_valid:
                try:
                    result = calculate_price(form.calculation_input(panels), settings=settings)
                except ValidationError as error:
                    if hasattr(error, 'message_dict'):
                        for field, messages in error.message_dict.items():
                            form.add_error(field if field in form.fields else None, messages)
                    else:
                        form.add_error(None, error)
        request.current_app = self.admin_site.name
        context = {
            **self.admin_site.each_context(request),
            'title': 'Проверочный расчёт скинали', 'opts': self.model._meta,
            'form': form, 'panels': panels, 'result': result,
            'field_groups': [(title, [form[name] for name in names]) for title, names in form.field_groups],
            'tariffs_url': reverse(f'{self.admin_site.name}:calculator_calculatortariffs_change', args=[settings.pk]),
            'glass_url': reverse(f'{self.admin_site.name}:calculator_glasstype_changelist'),
            'decoration_url': reverse(f'{self.admin_site.name}:calculator_decorationtype_changelist'),
        }
        return TemplateResponse(request, 'admin/calculator/calculatortariffs/calculate.html', context)

    class Media:
        css = {'all': ('skinali/css/admin-order.css', 'calculator/css/admin-services.css')}
        js = ('skinali/js/admin-order.js', 'calculator/js/admin-service-order.js')
