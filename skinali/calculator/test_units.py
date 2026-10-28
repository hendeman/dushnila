from decimal import Decimal

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.forms.models import model_to_dict
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .calculation import calculate_price
from .forms import CalculatorServiceForm
from .models import CalculatorService, MeasurementUnit
from .test_calculation import CalculationFixture


class MeasurementUnitTests(CalculationFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = get_user_model().objects.create_superuser('unit-owner', password=None)

    def setUp(self):
        self.client.force_login(self.owner)
        self.list_url = reverse('admin:calculator_measurementunit_changelist')
        self.add_url = reverse('admin:calculator_measurementunit_add')

    def test_seeded_units_and_shared_service_references(self):
        self.assertEqual(set(MeasurementUnit.objects.values_list('symbol', flat=True)),
                         {'ед.', 'м²', 'пог. м', 'шт.', 'км', 'заказ', 'мм', 'доп. этаж'})
        self.assertEqual(self.settings.services.get(code='backlight').unit_id,
                         self.settings.services.get(code='railing').unit_id)
        self.assertContains(self.client.get(reverse('admin:index')), 'Единицы измерения')
        self.assertContains(self.client.get(self.list_url), 'Погонный метр')

    def test_names_and_symbols_are_trimmed_required_and_unique(self):
        unit = MeasurementUnit.objects.create(name=' Упаковка ', symbol=' упак. ', position=3)
        unit.refresh_from_db()
        self.assertEqual((unit.name, unit.symbol), ('Упаковка', 'упак.'))
        for name, symbol in ((' ', 'нов.'), ('Новое', ' '), (' Упаковка ', 'другое'), ('Другое', ' упак. ')):
            with self.subTest(name=name, symbol=symbol), self.assertRaises(ValidationError):
                MeasurementUnit.objects.create(name=name, symbol=symbol)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MeasurementUnit.objects.filter(symbol='км').update(symbol='упак.')

    def test_admin_can_create_edit_reorder_and_delete_unused_unit_with_history(self):
        response = self.client.post(self.add_url, {'name': 'Упаковка', 'symbol': 'упак.', 'position': '1'})
        self.assertEqual(response.status_code, 302)
        unit = MeasurementUnit.objects.get(symbol='упак.')
        url = reverse('admin:calculator_measurementunit_change', args=[unit.pk])
        self.assertEqual(self.client.post(url, {'name': 'Комплект', 'symbol': 'компл.', 'position': '2'}).status_code, 302)
        unit.refresh_from_db()
        self.assertEqual((unit.name, unit.symbol, unit.position), ('Комплект', 'компл.', 2))
        self.assertEqual(MeasurementUnit.objects.filter(pk=unit.pk).count(), 1)
        delete = reverse('admin:calculator_measurementunit_delete', args=[unit.pk])
        self.assertEqual(self.client.post(delete, {'post': 'yes'}).status_code, 302)
        self.assertFalse(MeasurementUnit.objects.filter(pk=unit.pk).exists())
        self.assertEqual(LogEntry.objects.filter(content_type__model='measurementunit', object_id=str(unit.pk)).count(), 3)

    def test_used_unit_is_protected_in_admin_and_orm_even_for_hidden_included_service(self):
        service = self.settings.services.get(code='delivery')
        unit = service.unit
        service.is_visible, service.has_price = False, False
        service.save()
        with self.assertRaises(ProtectedError):
            unit.delete()
        with self.assertRaises(ProtectedError):
            MeasurementUnit.objects.filter(pk=unit.pk).delete()
        url = reverse('admin:calculator_measurementunit_delete', args=[unit.pk])
        response = self.client.post(url, {'post': 'yes'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['protected'])
        self.assertTrue(MeasurementUnit.objects.filter(pk=unit.pk).exists())

    def test_service_uses_dropdown_default_and_rejects_unknown_unit(self):
        unit = MeasurementUnit.objects.get(symbol='ед.')
        form = CalculatorServiceForm()
        self.assertEqual(form.initial['unit'], unit.pk)
        self.assertEqual(form.fields['unit'].queryset.model, MeasurementUnit)
        service = self.settings.services.get(code='delivery')
        data = model_to_dict(service)
        data['unit'] = '99999999'
        form = CalculatorServiceForm(data, instance=service)
        self.assertFalse(form.is_valid())
        self.assertIn('unit', form.errors)
        unit.delete()
        self.assertIsNone(CalculatorServiceForm().initial['unit'])

    def test_symbol_edit_changes_all_service_outputs_without_affecting_amounts(self):
        data = self.calculation_input(backlight_length_m=Decimal('2'), railing_length_m=Decimal('3'))
        before = calculate_price(data)
        unit = self.settings.services.get(code='backlight').unit
        response = self.client.post(reverse('admin:calculator_measurementunit_change', args=[unit.pk]), {
            'name': 'Погонный метр', 'symbol': 'п. м', 'position': '20',
        })
        self.assertEqual(response.status_code, 302)
        after = calculate_price(data)
        self.assertEqual(before.subtotal, after.subtotal)
        self.assertEqual(before.total, after.total)
        for code in ('backlight', 'railing'):
            self.assertEqual(next(line.unit for line in after.lines if line.code == code), 'п. м')

    def test_units_are_loaded_in_one_query_for_many_services(self):
        unit = MeasurementUnit.objects.get(symbol='ед.')
        for number in range(10):
            CalculatorService.objects.create(settings=self.settings, name=f'Услуга {number}',
                                             has_price=False, is_visible=True, unit=unit)
        with CaptureQueriesContext(connection) as queries:
            calculate_price(self.calculation_input())
        self.assertEqual(sum('calculator_measurementunit' in query['sql'] for query in queries), 1)

    def test_unit_mutations_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        unit = MeasurementUnit.objects.get(symbol='км')
        for url in (self.add_url, reverse('admin:calculator_measurementunit_change', args=[unit.pk]),
                    reverse('admin:calculator_measurementunit_delete', args=[unit.pk])):
            self.assertEqual(client.post(url, {'name': 'Новое', 'symbol': 'н.', 'position': 1}).status_code, 403)
