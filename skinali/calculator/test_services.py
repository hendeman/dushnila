from decimal import Decimal

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.forms.models import model_to_dict
from django.test import Client, TestCase
from django.urls import reverse

from .calculation import Panel, ServiceSelection, calculate_price
from .forms import CalculatorServiceForm, CalculationForm
from .models import CalculatorService, CalculatorTariffs, MeasurementUnit
from .test_calculation import CalculationFixture


class EditableServiceTests(CalculationFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = get_user_model().objects.create_superuser('service-owner', password=None)

    def setUp(self):
        self.client.force_login(self.owner)
        self.card_url = reverse('admin:calculator_calculatortariffs_change', args=[CalculatorTariffs.CODE])
        self.preview_url = reverse('admin:calculator_calculatortariffs_calculate')
        self.add_url = reverse('admin:calculator_calculatorservice_add')

    def service_data(self, service=None, **changes):
        data = model_to_dict(service) if service else {
            'name': 'Обработка', 'visibility_label': '', 'price_label': '',
            'is_visible': True, 'has_price': True, 'price_per_unit': '12.50',
            'quantity_label': 'Количество', 'unit': MeasurementUnit.objects.get(symbol='ед.').pk, 'position': 15,
        }
        data.update(changes)
        return {key: 'on' if value is True else '' if value is None or value is False else str(value)
                for key, value in data.items() if key not in ('id', 'settings', 'code')}

    def test_create_edit_and_delete_service_from_settings_links_with_history(self):
        last_position = CalculatorService.objects.order_by('-position').first().position
        self.assertEqual(self.client.post(self.add_url, self.service_data()).status_code, 302)
        service = CalculatorService.objects.get(name='Обработка')
        self.assertEqual(service.position, last_position + 1)
        self.assertEqual(service.visibility_label, 'Показать: Обработка')
        self.assertEqual(service.price_label, 'Обработка')
        change_url = reverse('admin:calculator_calculatorservice_change', args=[service.pk])
        self.assertNotIn('position', self.client.get(change_url).context['adminform'].form.fields)
        delete_url = reverse('admin:calculator_calculatorservice_delete', args=[service.pk])
        response = self.client.get(self.card_url)
        self.assertContains(response, change_url)
        self.assertContains(response, delete_url)
        code = service.code
        data = self.service_data(service, name='Крепёж', visibility_label='Показывать крепёж',
                                 price_label='Цена за один комплект', price_per_unit='21.75', position=5)
        self.assertRedirects(self.client.post(change_url, data), self.card_url, fetch_redirect_response=False)
        service.refresh_from_db()
        self.assertEqual(service.position, last_position + 1)
        self.assertEqual(service.code, code)
        self.assertEqual(service.price_label, 'Цена за один комплект')
        self.assertContains(self.client.get(self.card_url), 'Показывать крепёж')
        self.assertEqual(self.client.get(delete_url).status_code, 200)
        self.assertTrue(CalculatorService.objects.filter(pk=service.pk).exists())
        self.assertRedirects(self.client.post(delete_url, {'post': 'yes'}), self.card_url, fetch_redirect_response=False)
        self.assertFalse(CalculatorService.objects.filter(pk=service.pk).exists())
        self.assertEqual(LogEntry.objects.filter(content_type__model='calculatorservice', object_id=str(service.pk)).count(), 3)
        self.assertEqual(self.settings.stair_lifting_rules.count(), 4)

    def test_switching_to_included_preserves_tariff_and_removes_selection_and_quantity(self):
        service = self.settings.services.get(code='backlight')
        quantity_fields = ('quantity_label', 'unit', 'use_panel_area', 'whole_quantity')
        before = (service.quantity_label, service.unit_id, service.use_panel_area, service.whole_quantity)
        url = reverse('admin:calculator_calculatorservice_change', args=[service.pk])
        data = self.service_data(service, has_price=False, price_per_unit='не число',
                                 quantity_label='', unit='999999', use_panel_area=True, whole_quantity=True)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        service.refresh_from_db()
        self.assertFalse(service.has_price)
        self.assertEqual(service.price_per_unit, Decimal('10.20'))
        self.assertEqual((service.quantity_label, service.unit_id, service.use_panel_area, service.whole_quantity), before)
        editor = self.client.get(url).context['adminform'].form
        self.assertTrue(all(editor.fields[name].disabled for name in quantity_fields))
        form = CalculationForm(settings=self.settings)
        self.assertNotIn(f'use_service_{service.pk}', form.fields)
        self.assertNotIn(f'service_quantity_{service.pk}', form.fields)
        line = next(line for line in calculate_price(self.calculation_input()).lines if line.code == 'backlight')
        self.assertTrue(line.included)
        self.assertEqual(line.amount, 0)
        self.assertEqual(self.client.post(url, self.service_data(service, has_price=True)).status_code, 302)
        service.refresh_from_db()
        self.assertTrue(service.has_price)
        self.assertEqual((service.quantity_label, service.unit_id, service.use_panel_area, service.whole_quantity), before)
        editor = self.client.get(url).context['adminform'].form
        self.assertTrue(all(not editor.fields[name].disabled for name in quantity_fields))
        result = calculate_price(self.calculation_input(services=(ServiceSelection(service.pk, Decimal('2')),)))
        self.assertEqual(next(line.amount for line in result.lines if line.code == 'backlight'), Decimal('20.40'))

    def test_name_labels_price_and_visibility_are_validated(self):
        for changes, field in (({'name': ' '}, 'name'), ({'price_per_unit': ''}, 'price_per_unit'),
                               ({'price_per_unit': '-1'}, 'price_per_unit'), ({'price_per_unit': '1.001'}, 'price_per_unit'),
                               ({'price_per_unit': 'NaN'}, 'price_per_unit'), ({'price_per_unit': 'Infinity'}, 'price_per_unit')):
            with self.subTest(changes=changes):
                form = CalculatorServiceForm(self.service_data(**changes))
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)
        form = CalculatorServiceForm(self.service_data(has_price=False, price_per_unit=''))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.save().price_per_unit)

    def test_negative_price_is_rejected_by_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            CalculatorService.objects.filter(code='backlight').update(price_per_unit=-1)

    def test_paid_service_requires_checkbox_and_positive_quantity(self):
        service = self.settings.services.get(code='backlight')
        selected, quantity = f'use_service_{service.pk}', f'service_quantity_{service.pk}'
        response = self.client.post(self.preview_url, self.post_data(**{quantity: '-100'}))
        self.assertEqual(response.context['result'].subtotal, Decimal('96.6'))
        self.assertContains(response, 'data-service-quantity hidden')
        for value in ('', '0', '-1', 'NaN'):
            with self.subTest(value=value):
                response = self.client.post(self.preview_url, self.post_data(**{selected: 'on', quantity: value}))
                self.assertIsNone(response.context['result'])
                self.assertIn(quantity, response.context['form'].errors)
        response = self.client.post(self.preview_url, self.post_data(**{selected: 'on', quantity: '2.5'}))
        self.assertEqual(response.context['result'].subtotal, Decimal('122.10'))

    def test_area_quantity_comes_from_panels_and_whole_count_rejects_fraction(self):
        area_service = self.settings.services.get(code='hydrophobic')
        result = calculate_price(self.calculation_input(services=(ServiceSelection(area_service.pk, Decimal('999')),)))
        line = next(line for line in result.lines if line.code == 'hydrophobic')
        self.assertEqual(line.quantity, Decimal('0.8'))
        self.assertEqual(line.amount, Decimal('2.60'))
        count_service = self.settings.services.get(code='sockets')
        with self.assertRaises(ValidationError):
            calculate_price(self.calculation_input(services=(ServiceSelection(count_service.pk, Decimal('1.5')),)))

    def test_custom_description_and_unit_do_not_change_formula(self):
        service = CalculatorService.objects.create(
            settings=self.settings, name='Новая услуга', price_label='Любое пояснение', unit=MeasurementUnit.objects.get(symbol='км'),
            price_per_unit=Decimal('1.25'), is_visible=True,
        )
        result = calculate_price(self.calculation_input(services=(ServiceSelection(service.pk, Decimal('2.5')),)))
        line = next(line for line in result.lines if line.code == service.code)
        self.assertEqual(line.amount, Decimal('3.125'))
        self.assertEqual(line.description, '')
        self.assertEqual(result.subtotal, Decimal('99.725'))
        self.assertEqual(result.total, 100)

    def test_fixed_price_is_charged_once_independently_of_geometry_and_submitted_quantity(self):
        service = self.settings.services.get(code='hydrophobic')
        service.fixed_price = True
        service.whole_quantity = True
        service.price_per_unit = Decimal('150.25')
        service.save()
        for panels in ((Panel(1000, 600),), (Panel(2000, 1000), Panel(500, 1000))):
            for quantity in (Decimal('0'), Decimal('1.5'), Decimal('999')):
                with self.subTest(panels=panels, quantity=quantity):
                    result = calculate_price(self.calculation_input(panels=panels, services=(ServiceSelection(service.pk, quantity),)))
                    line = next(line for line in result.lines if line.code == service.code)
                    self.assertEqual((line.quantity, line.unit, line.unit_price, line.amount),
                                     (Decimal('1'), 'заказ', Decimal('150.25'), Decimal('150.25')))
                    self.assertEqual(len([line for line in result.lines if line.code == service.code]), 1)
        self.assertNotIn(service.code, [line.code for line in calculate_price(self.calculation_input()).lines])

    def test_fixed_price_has_only_checkbox_and_ignores_forged_quantity(self):
        service = self.settings.services.get(code='hydrophobic')
        service.fixed_price, service.price_per_unit = True, Decimal('150.25')
        service.save()
        selected, quantity = f'use_service_{service.pk}', f'service_quantity_{service.pk}'
        response = self.client.get(self.preview_url)
        self.assertIn(selected, response.context['form'].fields)
        self.assertNotIn(quantity, response.context['form'].fields)
        self.assertNotContains(response, f'name="{quantity}"')
        self.assertNotContains(response, 'Количество определяется по общей площади панелей.')
        for enabled, expected in ((False, '96.6'), (True, '246.85')):
            with self.subTest(enabled=enabled):
                data = self.post_data(**{quantity: 'не число', selected: 'on' if enabled else ''})
                response = self.client.post(self.preview_url, data)
                self.assertFalse(response.context['form'].errors)
                self.assertEqual(response.context['result'].subtotal, Decimal(expected))
                self.assertNotContains(response, f'name="{quantity}"')

    def test_fixed_price_editor_preserves_quantity_settings_and_can_restore_manual_input(self):
        service = self.settings.services.get(code='hydrophobic')
        before = (service.quantity_label, service.unit_id, service.use_panel_area, service.whole_quantity)
        url = reverse('admin:calculator_calculatorservice_change', args=[service.pk])
        data = self.service_data(service, fixed_price=True, price_per_unit='77.75',
                                 quantity_label='', unit='999999', use_panel_area=False, whole_quantity=True)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        service.refresh_from_db()
        self.assertTrue(service.fixed_price)
        self.assertEqual(service.price_per_unit, Decimal('77.75'))
        self.assertEqual((service.quantity_label, service.unit_id, service.use_panel_area, service.whole_quantity), before)
        data = self.service_data(service, fixed_price=False, quantity_label='Длина', use_panel_area=False)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        service.refresh_from_db()
        self.assertTrue(service.requires_manual_quantity)
        self.assertIn(f'service_quantity_{service.pk}', CalculationForm(settings=self.settings).fields)
        result = calculate_price(self.calculation_input(services=(ServiceSelection(service.pk, Decimal('2')),)))
        self.assertEqual(next(line.amount for line in result.lines if line.code == service.code), Decimal('155.50'))

    def test_included_mode_overrides_fixed_price_and_zero_fixed_price_is_allowed(self):
        service = self.settings.services.get(code='backlight')
        service.fixed_price, service.price_per_unit = True, Decimal('0')
        service.save()
        result = calculate_price(self.calculation_input(services=(ServiceSelection(service.pk, Decimal('99')),)))
        line = next(line for line in result.lines if line.code == service.code)
        self.assertFalse(line.included)
        self.assertEqual((line.quantity, line.amount), (Decimal('1'), Decimal('0')))
        service.has_price = False
        service.save()
        form = CalculationForm(settings=self.settings)
        self.assertNotIn(f'use_service_{service.pk}', form.fields)
        result = calculate_price(self.calculation_input())
        self.assertTrue(next(line for line in result.lines if line.code == service.code).included)
        self.assertEqual(result.subtotal, Decimal('96.6'))

    def test_order_is_shared_by_settings_form_preview_and_result(self):
        self.settings.services.filter(code='delivery').update(position=1, has_price=False)
        expected = list(self.settings.services.values_list('pk', flat=True))
        formset = self.client.get(self.card_url).context['inline_admin_formsets'][0].formset
        self.assertEqual([form.instance.pk for form in formset.forms], expected)
        self.assertEqual([row['service'].pk for row in CalculationForm(settings=self.settings).service_rows], expected)
        result = calculate_price(self.calculation_input())
        included = [line.code for line in result.lines if line.included and line.code != 'standard_lifting']
        self.assertEqual(included, ['delivery', 'measurement', 'installation'])

    def test_deleted_hidden_and_included_service_inputs_do_not_add_a_price(self):
        service = self.settings.services.get(code='delivery')
        data = self.calculation_input(services=(ServiceSelection(service.pk, Decimal('5')),))
        service.is_visible = False
        service.save()
        self.assertEqual(calculate_price(data).subtotal, Decimal('96.6'))
        service.delete()
        self.assertEqual(calculate_price(data).subtotal, Decimal('96.6'))
        included = self.settings.services.get(code='measurement')
        self.assertEqual(calculate_price(self.calculation_input(services=(ServiceSelection(included.pk, Decimal('99')),))).subtotal,
                         Decimal('96.6'))

    def test_duplicate_and_untyped_service_selections_are_rejected(self):
        selection = ServiceSelection(self.service_ids['delivery'], Decimal('2'))
        for services in ((selection, selection), ({'service_id': selection.service_id, 'quantity': '2'},)):
            with self.subTest(services=services), self.assertRaises(ValidationError):
                self.calculation_input(services=services)

    def test_service_name_is_escaped_and_tariff_description_stays_in_settings(self):
        service = self.settings.services.get(code='backlight')
        service.name = '<script>alert(1)</script>'
        service.price_label = '<img src=x onerror=alert(1)>'
        for fixed_price, use_panel_area in ((False, False), (False, True), (True, False)):
            with self.subTest(fixed_price=fixed_price, use_panel_area=use_panel_area):
                service.fixed_price, service.use_panel_area = fixed_price, use_panel_area
                service.save()
                responses = (
                    self.client.get(self.preview_url),
                    self.client.post(self.preview_url, self.post_data(**{
                        f'use_service_{service.pk}': 'on', f'service_quantity_{service.pk}': '1',
                    })),
                )
                self.assertIsNotNone(responses[1].context['result'])
                for response in responses:
                    self.assertNotContains(response, service.name)
                    self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
                    self.assertNotContains(response, service.price_label)
                    self.assertNotContains(response, '&lt;img src=x onerror=alert(1)&gt;')
        self.assertContains(self.client.get(self.card_url), '&lt;img src=x onerror=alert(1)&gt;')

    def test_service_mutations_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        service = self.settings.services.get(code='backlight')
        for url in (self.add_url, reverse('admin:calculator_calculatorservice_change', args=[service.pk]),
                    reverse('admin:calculator_calculatorservice_delete', args=[service.pk])):
            self.assertEqual(client.post(url, self.service_data(service)).status_code, 403)

    def test_manual_service_limit_is_saved_and_enforced_by_form_and_calculation(self):
        service = self.settings.services.get(code='backlight')
        url = reverse('admin:calculator_calculatorservice_change', args=[service.pk])
        selected, quantity = f'use_service_{service.pk}', f'service_quantity_{service.pk}'
        for limit, invalid in (('2.5', '2.51'), ('0.5', '0.51')):
            with self.subTest(limit=limit):
                self.assertEqual(self.client.post(url, self.service_data(service, max_quantity=limit)).status_code, 302)
                service.refresh_from_db()
                self.assertEqual(service.max_quantity, Decimal(limit))
                field = self.client.get(self.preview_url).context['form'].fields[quantity]
                self.assertEqual(field.max_value, Decimal(limit))
                self.assertEqual(field.initial, min(Decimal('1'), Decimal(limit)))
                response = self.client.post(self.preview_url, self.post_data(**{selected: 'on', quantity: limit}))
                self.assertFalse(response.context['form'].errors)
                line = next(line for line in response.context['result'].lines if line.code == service.code)
                self.assertEqual(line.quantity, Decimal(limit))
                response = self.client.post(self.preview_url, self.post_data(**{
                    selected: 'on', quantity: invalid, 'max_quantity': '99999',
                }))
                self.assertIsNone(response.context['result'])
                self.assertIn(quantity, response.context['form'].errors)
                with self.assertRaises(ValidationError):
                    calculate_price(self.calculation_input(services=(ServiceSelection(service.pk, Decimal(invalid)),)))
                response = self.client.post(self.preview_url, self.post_data(**{quantity: '99999'}))
                self.assertEqual(response.context['result'].subtotal, Decimal('96.6'))

    def test_whole_quantity_requires_whole_limit_and_blank_removes_custom_limit(self):
        service = self.settings.services.get(code='sockets')
        url = reverse('admin:calculator_calculatorservice_change', args=[service.pk])
        self.assertEqual(self.client.post(url, self.service_data(service, max_quantity='4')).status_code, 302)
        service.refresh_from_db()
        result = calculate_price(self.calculation_input(services=(ServiceSelection(service.pk, Decimal('4')),)))
        self.assertEqual(next(line.quantity for line in result.lines if line.code == service.code), 4)
        with self.assertRaises(ValidationError):
            calculate_price(self.calculation_input(services=(ServiceSelection(service.pk, Decimal('5')),)))
        response = self.client.post(url, self.service_data(service, max_quantity='2.5'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('max_quantity', response.context['adminform'].form.errors)
        service.refresh_from_db()
        self.assertEqual(service.max_quantity, Decimal('4'))
        self.assertEqual(self.client.post(url, self.service_data(service, max_quantity='')).status_code, 302)
        service.refresh_from_db()
        self.assertIsNone(service.max_quantity)
        result = calculate_price(self.calculation_input(services=(ServiceSelection(service.pk, Decimal('5')),)))
        self.assertEqual(next(line.quantity for line in result.lines if line.code == service.code), 5)

    def test_whole_limit_displays_as_integer_after_save_and_on_form_errors(self):
        service = self.settings.services.get(code='delivery')
        url = reverse('admin:calculator_calculatorservice_change', args=[service.pk])
        self.assertEqual(self.client.post(url, self.service_data(
            service, whole_quantity=True, max_quantity='100',
        )).status_code, 302)
        service.refresh_from_db()
        self.assertEqual(service.max_quantity, Decimal('100.00'))
        editor = self.client.get(url).context['adminform'].form
        self.assertIn('value="100"', str(editor['max_quantity']))
        self.assertEqual(editor.fields['max_quantity'].widget.attrs['step'], 1)
        response = self.client.post(url, self.service_data(service, name='', max_quantity='100.00'))
        self.assertIn('value="100"', str(response.context['adminform'].form['max_quantity']))
        response = self.client.post(url, self.service_data(service, max_quantity='100.5'))
        editor = response.context['adminform'].form
        self.assertIn('max_quantity', editor.errors)
        self.assertIn('value="100.5"', str(editor['max_quantity']))
        self.assertEqual(self.client.post(url, self.service_data(
            service, whole_quantity=False, max_quantity='100.5',
        )).status_code, 302)
        editor = self.client.get(url).context['adminform'].form
        self.assertIn('value="100.50"', str(editor['max_quantity']))
        self.assertEqual(editor.fields['max_quantity'].widget.attrs['step'], '0.01')

    def test_service_limit_rejects_invalid_values_in_editor_model_and_database(self):
        for value in ('0', '-1', '0.001', '0.0001', '1000000000', 'NaN', 'Infinity'):
            with self.subTest(value=value):
                form = CalculatorServiceForm(self.service_data(max_quantity=value))
                self.assertFalse(form.is_valid())
                self.assertIn('max_quantity', form.errors)
        self.assertTrue(CalculatorServiceForm(self.service_data(max_quantity='0.01')).is_valid())
        service = self.settings.services.get(code='sockets')
        service.max_quantity = Decimal('2.5')
        with self.assertRaises(ValidationError) as error:
            service.save()
        self.assertIn('max_quantity', error.exception.message_dict)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.settings.services.filter(code='backlight').update(max_quantity=Decimal('0'))

    def test_fractional_service_uses_two_places_in_editor_preview_and_calculation(self):
        service = self.settings.services.get(code='backlight')
        url = reverse('admin:calculator_calculatorservice_change', args=[service.pk])
        self.assertEqual(self.client.post(url, self.service_data(service, max_quantity='2.55')).status_code, 302)
        service.refresh_from_db()
        editor = self.client.get(url).context['adminform'].form
        self.assertIn('value="2.55"', str(editor['max_quantity']))
        selected, quantity = f'use_service_{service.pk}', f'service_quantity_{service.pk}'
        field = self.client.get(self.preview_url).context['form'][quantity]
        self.assertIn('step="0.01"', str(field))
        self.assertIn('value="1.00"', str(field))
        response = self.client.post(self.preview_url, self.post_data(**{selected: 'on', quantity: '1.55'}))
        line = next(line for line in response.context['result'].lines if line.code == service.code)
        self.assertEqual(line.quantity, Decimal('1.55'))
        self.assertEqual(line.amount, Decimal('15.8100'))
        response = self.client.post(self.preview_url, self.post_data(**{selected: 'on', quantity: '1.555'}))
        self.assertIsNone(response.context['result'])
        self.assertIn(quantity, response.context['form'].errors)
        with self.assertRaises(ValidationError):
            ServiceSelection(service.pk, Decimal('1.555'))

    def test_service_limit_is_preserved_and_ignored_for_nonmanual_modes(self):
        service = self.settings.services.get(code='backlight')
        service.max_quantity = Decimal('0.5')
        service.save()
        url = reverse('admin:calculator_calculatorservice_change', args=[service.pk])
        for changes in ({'has_price': False}, {'fixed_price': True}, {'use_panel_area': True}):
            with self.subTest(changes=changes):
                data = self.service_data(service, max_quantity='не число', **changes)
                self.assertEqual(self.client.post(url, data).status_code, 302)
                service.refresh_from_db()
                self.assertEqual(service.max_quantity, Decimal('0.5'))
                self.assertTrue(self.client.get(url).context['adminform'].form.fields['max_quantity'].disabled)
                calculate_price(self.calculation_input(services=(ServiceSelection(service.pk, Decimal('99')),)))
                data = self.service_data(service, has_price=True, fixed_price=False, use_panel_area=False)
                self.assertEqual(self.client.post(url, data).status_code, 302)
                service.refresh_from_db()
                self.assertEqual(service.max_quantity, Decimal('0.5'))
                with self.assertRaises(ValidationError):
                    calculate_price(self.calculation_input(services=(ServiceSelection(service.pk, Decimal('0.51')),)))
