import json
from decimal import Decimal
from pathlib import Path
import subprocess
from unittest import skipUnless
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.forms.models import model_to_dict
from django.test import Client, TestCase
from django.urls import reverse

from . import tests as admin_tests
from .calculation import Panel, ServiceSelection, calculate_price
from .forms import CalculationForm, CalculatorServiceForm
from .models import CalculatorService, CalculatorSettings, CalculatorTariffs
from .public import public_configuration
from .test_calculation import CalculationFixture
from .test_public import NODE, browser_results


class OrderDiscountTests(CalculationFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = get_user_model().objects.create_superuser('order-discount-owner', password=None)

    def setUp(self):
        self.general = CalculatorSettings.objects.get(pk=CalculatorSettings.CODE)
        self.general.is_enabled = True
        self.general.save()
        self.glass.price_per_sqm, self.decoration.price_per_sqm = Decimal('800'), Decimal('200')
        self.glass.save()
        self.decoration.save()
        self.client.force_login(self.owner)
        self.panel = Panel(1000, 1000)

    def discount(self, percent='3', **changes):
        return CalculatorService.objects.create(**{
            'settings': self.settings, 'name': 'Скидка за фото-отзыв', 'calculation_type': 'order_discount',
            'discount_percent': Decimal(percent), 'has_price': False, 'is_visible': True, **changes,
        })

    def quote(self, *services, **changes):
        return calculate_price(self.calculation_input(
            panels=(self.panel,), services=tuple(ServiceSelection(service.pk) for service in services), **changes,
        ))

    def test_checkbox_is_required_and_selected_percentages_are_added(self):
        first, second = self.discount('3'), self.discount('5', name='Скидка за рекомендацию')
        self.assertEqual(self.quote().total, 1000)
        single = self.quote(first)
        self.assertEqual((single.order_discount_percent, single.order_discount, single.total), (3, 30, 970))
        combined = self.quote(first, second)
        self.assertEqual((combined.order_discount_percent, combined.order_discount, combined.total), (8, 80, 920))
        self.assertEqual(sum(line.amount for line in combined.lines), combined.subtotal)
        self.assertEqual(self.quote(second, first).total, combined.total)
        first.position, second.position = 100, 0
        first.save()
        second.save()
        self.assertEqual(self.quote(first, second).total, combined.total)

    def test_discount_applies_after_material_discount_services_and_stairs_before_rounding(self):
        first, second = self.discount('3'), self.discount('5')
        fee = CalculatorService.objects.create(settings=self.settings, name='Доплата', price_per_unit=100,
                                               fixed_price=True, is_visible=True, position=999)
        self.set_material_discount('stepped', (('1', '10'),))
        self.general.marketing_discount_percent = Decimal('20')
        self.general.save()
        result = self.quote(first, second, fee, stair_floor=12, stair_panel_count=1)
        self.assertEqual(result.materials_discount, 100)
        self.assertEqual(result.order_discount, Decimal('85.44'))
        self.assertEqual((result.subtotal, result.total, result.comparison_total), (Decimal('982.56'), 983, 1229))

    def test_zero_full_and_over_one_hundred_percent_never_make_total_negative(self):
        first, second = self.discount('0'), self.discount('100')
        self.assertEqual(self.quote(first).total, 1000)
        self.assertEqual(self.quote(second).total, 0)
        first.discount_percent = Decimal('60')
        first.save()
        second.discount_percent = Decimal('60')
        second.save()
        result = self.quote(first, second)
        self.assertEqual((result.order_discount_percent, result.order_discount, result.subtotal, result.total), (100, 1000, 0, 0))
        self.assertIn('ограничена 100%', result.lines[-1].description)

    def test_hidden_services_and_non_applicable_quantities_do_not_change_discount(self):
        service = self.discount('3', fixed_price=True, use_panel_area=True, whole_quantity=True,
                                max_quantity=Decimal('1.5'), price_per_unit=Decimal('999'))
        self.assertTrue(service.is_selectable)
        self.assertFalse(service.requires_manual_quantity)
        for quantity in ('0', '1', '2', '999.99'):
            data = self.calculation_input(panels=(self.panel,), services=(ServiceSelection(service.pk, Decimal(quantity)),))
            self.assertEqual(calculate_price(data).total, 970)
        service.is_visible = False
        service.save()
        self.assertEqual(self.quote(service).total, 1000)

    def test_model_and_database_validate_type_and_discount(self):
        for field, values in {'discount_percent': ('-1', '100.01', '.001', 'NaN', 'Infinity'),
                              'calculation_type': ('unknown', '')}.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    self.discount(**{field: value})
        service = self.discount()
        for change in ({'discount_percent': -1}, {'discount_percent': 101}, {'calculation_type': 'unknown'}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                CalculatorService.objects.filter(pk=service.pk).update(**change)

    def test_admin_creates_discount_without_price_and_preserves_inactive_settings(self):
        add_url = reverse('admin:calculator_calculatorservice_add')
        add_editor = self.client.get(add_url)
        self.assertContains(add_editor, 'data-focus-name="true"')
        self.assertNotContains(add_editor, 'id="django-admin-form-add-constants"')
        data = {'name': 'Скидка 3% за фото-отзыв', 'calculation_type': 'order_discount',
                'discount_percent': '3', 'is_visible': 'on', 'hint': 'Условия получения скидки',
                'price_per_unit': '-100', 'unit': '999999', 'max_quantity': 'не число'}
        invalid_editor = self.client.post(add_url, {**data, 'discount_percent': '101'})
        self.assertContains(invalid_editor, 'data-focus-name="false"')
        self.assertEqual(self.client.post(add_url, data).status_code, 302)
        service = CalculatorService.objects.get(name=data['name'])
        self.assertEqual(service.discount_percent, 3)
        self.assertIsNone(service.price_per_unit)
        change_url = reverse('admin:calculator_calculatorservice_change', args=[service.pk])
        editor = self.client.get(change_url)
        self.assertContains(editor, 'calculator/js/admin-services.js?rev=4')
        self.assertContains(editor, 'data-focus-name="false"')
        self.assertNotContains(editor, 'admin-services.js%3F')
        form = editor.context['adminform'].form
        self.assertTrue(all(form.fields[name].disabled for name in ('price_per_unit', 'unit', 'max_quantity', 'has_price')))
        self.assertFalse(form.fields['discount_percent'].disabled)
        ordinary = self.settings.services.get(code='backlight')
        old = model_to_dict(ordinary)
        post = {**old, 'calculation_type': 'order_discount', 'discount_percent': '5', 'price_per_unit': '-1', 'unit': '999999'}
        post.pop('settings')
        form = CalculatorServiceForm(post, instance=ordinary)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        ordinary.refresh_from_db()
        self.assertEqual((ordinary.price_per_unit, ordinary.unit_id, ordinary.has_price),
                         (old['price_per_unit'], old['unit'], old['has_price']))
        post = {**model_to_dict(ordinary), 'calculation_type': 'standard', 'discount_percent': '99'}
        post.pop('settings')
        form = CalculatorServiceForm(post, instance=ordinary)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        ordinary.refresh_from_db()
        self.assertEqual(ordinary.discount_percent, 5)
        self.assertEqual(ordinary.price_per_unit, old['price_per_unit'])

    def test_inline_edits_percentage_and_rejects_invalid_save_atomically(self):
        service = self.discount()
        card_url = reverse('admin:calculator_calculatortariffs_change', args=[CalculatorTariffs.CODE])
        data = admin_tests.CalculatorAdminTests.settings_data(self, service_changes={
            service.code: {'discount_percent': '5'}, 'backlight': {'discount_percent': '99'}})
        index = list(self.settings.services.values_list('pk', flat=True)).index(service.pk)
        data[f'services-{index}-calculation_type'] = 'standard'
        data[f'services-{index}-price_per_unit'] = '-999'
        self.assertEqual(self.client.post(card_url, data).status_code, 302)
        service.refresh_from_db()
        self.assertEqual(service.discount_percent, 5)
        self.assertTrue(service.is_order_discount)
        self.assertIsNone(service.price_per_unit)
        self.assertEqual(self.settings.services.get(code='backlight').discount_percent, 0)
        data = admin_tests.CalculatorAdminTests.settings_data(self, service_changes={
            service.code: {'discount_percent': '101'}, 'backlight': {'price_per_unit': '99'}})
        self.assertEqual(self.client.post(card_url, data).status_code, 200)
        service.refresh_from_db()
        self.assertEqual(service.discount_percent, 5)
        self.assertEqual(self.settings.services.get(code='backlight').price_per_unit, Decimal('10.20'))

    def test_site_and_admin_preview_show_checkbox_without_quantity(self):
        service = self.discount()
        response = self.client.get(reverse('price'))
        self.assertContains(response, f'id="price-service-{service.pk}"')
        self.assertNotContains(response, f'id="price-quantity-{service.pk}"')
        configuration = response.context['calculator_config']
        item = next(item for item in configuration['services'] if item['id'] == service.pk)
        self.assertTrue(item['selectable'])
        self.assertFalse(item['requires_manual_quantity'])
        self.assertEqual(item['discount_percent'], '3.00')
        form = CalculationForm(settings=self.settings)
        self.assertIn(f'use_service_{service.pk}', form.fields)
        self.assertNotIn(f'service_quantity_{service.pk}', form.fields)
        response = self.client.post(reverse('admin:calculator_calculatortariffs_calculate'), self.post_data(**{
            'panels-0-width_mm': '1000', 'panels-0-height_mm': '1000',
            'panels-1-width_mm': '', 'panels-1-height_mm': '', f'use_service_{service.pk}': 'on'}))
        self.assertEqual(response.context['result'].total, 970)
        self.assertContains(response, service.name)

    def test_signed_link_uses_current_percent_and_rejects_hidden_discount_or_forged_rate(self):
        service = self.discount()
        data = {'panels': [{'width': '1000', 'height': '1000'}], 'glass_type': self.glass.pk,
                'decoration_type': self.decoration.pk, 'services': [{'id': service.pk, 'quantity': '1'}]}
        created = self.client.post(reverse('price_share'), json.dumps(data), content_type='application/json')
        self.assertEqual(created.status_code, 200)
        url = urlsplit(created.json()['url'])
        path = url.path + '?' + url.query
        service.discount_percent = Decimal('5')
        service.save()
        response = Client().get(path)
        self.assertEqual(response.status_code, 200)
        item = next(item for item in response.context['calculator_config']['services'] if item['id'] == service.pk)
        self.assertEqual(item['discount_percent'], '5.00')
        data['services'][0]['discount_percent'] = '99'
        self.assertEqual(self.client.post(reverse('price_share'), json.dumps(data), content_type='application/json').status_code, 400)
        service.is_visible = False
        service.save()
        self.assertEqual(Client().get(path).status_code, 409)

    @skipUnless(NODE, 'Для проверки браузерной арифметики нужен Node.js.')
    def test_admin_type_switch_keeps_values_and_matches_disabled_fields(self):
        script = Path(__file__).parent / 'tests_js' / 'admin_services.cjs'
        subprocess.run([NODE, str(script)], capture_output=True, encoding='utf-8', timeout=10, check=True)

    @skipUnless(NODE, 'Для проверки браузерной арифметики нужен Node.js.')
    def test_browser_matches_server_for_addition_cap_rounding_materials_services_and_stairs(self):
        first, second = self.discount('3'), self.discount('5')
        cases, expected = [], []
        for rates in (('3', '5'), ('0', '0'), ('12.34', '56.78'), ('60', '60'), ('0', '100')):
            first.discount_percent, second.discount_percent = map(Decimal, rates)
            first.save()
            second.save()
            for mode in ('none', 'stepped', 'progressive'):
                self.set_material_discount(mode, () if mode == 'none' else (('1', '10'), ('3', '20')))
                config = public_configuration(self.settings, self.general)
                for width in (999, 1000, 1234, 3000):
                    data = self.calculation_input(panels=(Panel(width, 1000),), stair_floor=12, stair_panel_count=1,
                        services=(ServiceSelection(first.pk), ServiceSelection(second.pk),
                                  ServiceSelection(self.service_ids['backlight'], Decimal('1.5'))))
                    expected.append(calculate_price(data))
                    cases.append({'config': config, 'input': {'panels': [{'width': str(width), 'height': '1000'}],
                        'glass_type': self.glass.pk, 'decoration_type': self.decoration.pk,
                        'services': [{'id': item.service_id, 'quantity': str(item.quantity)} for item in data.services],
                        'stairs': {'floor': '12', 'count': '1'}}})
        for actual, server in zip(browser_results(cases), expected):
            self.assertNotIn('error', actual)
            for field in ('subtotal', 'total', 'order_discount_percent', 'order_discount'):
                self.assertEqual(Decimal(actual[field]), getattr(server, field))
