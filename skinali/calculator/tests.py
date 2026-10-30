from decimal import Decimal
from unittest.mock import patch

from django.contrib import admin
from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.forms.models import model_to_dict
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from .forms import CalculatorTariffsAdminForm
from .models import (
    CalculatorService, CalculatorSettings, CalculatorTariffs, DecorationType, GlassType, STAIR_PRICE_FIELDS,
    MAX_STAIR_PANELS, MeasurementUnit, StairLiftingRule,
)


UNIQUE_PRICE_FIELDS = (('show_stair_lifting', STAIR_PRICE_FIELDS),)


class CalculatorTariffsTests(TestCase):
    def setUp(self):
        self.settings = CalculatorTariffs.objects.get(pk=CalculatorTariffs.CODE)

    def test_migration_creates_only_settings_without_invented_prices(self):
        self.assertEqual(CalculatorTariffs.objects.count(), 1)
        self.assertEqual(CalculatorSettings.objects.count(), 1)
        self.assertFalse(CalculatorSettings.objects.get().is_enabled)
        self.assertEqual(GlassType.objects.count(), 0)
        self.assertEqual(DecorationType.objects.count(), 0)
        self.assertIsNone(self.settings.default_glass_type_id)
        self.assertIsNone(self.settings.default_decoration_type_id)
        for visibility, fields in UNIQUE_PRICE_FIELDS:
            self.assertFalse(getattr(self.settings, visibility))
            for field in fields:
                self.assertIsNone(getattr(self.settings, field))
        self.assertEqual(self.settings.services.count(), 7)
        self.assertTrue(self.settings.services.get(code='measurement').is_visible)
        self.assertTrue(self.settings.services.get(code='installation').is_visible)
        self.assertFalse(self.settings.services.filter(has_price=True, is_visible=True).exists())
        self.assertFalse(self.settings.services.filter(price_per_unit__isnull=False).exists())
        self.assertEqual(self.settings.get_stair_lifting_rules(), {
            1: (9, Decimal('1')), 2: (4, Decimal('1')),
            3: (3, Decimal('2')), 4: (2, Decimal('2')),
        })

    def test_singleton_is_enforced_by_validation_and_database(self):
        with self.assertRaises(ValidationError):
            CalculatorTariffs(code='other').save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CalculatorTariffs.objects.bulk_create([CalculatorTariffs(code='other')])

    def test_all_services_require_tariffs_when_shown_and_accept_zero(self):
        for visibility, fields in UNIQUE_PRICE_FIELDS:
            with self.subTest(service=visibility):
                self.settings.refresh_from_db()
                setattr(self.settings, visibility, True)
                with self.assertRaises(ValidationError) as error:
                    self.settings.save()
                self.assertEqual(set(error.exception.message_dict), set(fields))
                for field in fields:
                    setattr(self.settings, field, Decimal('0.00'))
                self.settings.save()
                self.settings.refresh_from_db()
                self.assertTrue(getattr(self.settings, visibility))

    def test_each_price_rejects_negative_values_in_validation_and_database(self):
        for _visibility, fields in UNIQUE_PRICE_FIELDS:
            for field in fields:
                with self.subTest(field=field):
                    self.settings.refresh_from_db()
                    setattr(self.settings, field, Decimal('-0.01'))
                    with self.assertRaises(ValidationError) as error:
                        self.settings.save()
                    self.assertIn(field, error.exception.message_dict)
                    with self.assertRaises(IntegrityError), transaction.atomic():
                        CalculatorTariffs.objects.update(**{field: Decimal('-0.01')})

    def test_hiding_service_preserves_its_tariff(self):
        service = self.settings.services.get(code='delivery')
        service.is_visible = True
        service.price_per_unit = Decimal('1.25')
        service.save()
        service.is_visible = False
        service.save()
        service.refresh_from_db()
        self.assertEqual(service.price_per_unit, Decimal('1.25'))
        self.assertFalse(service.is_visible)

    def test_stair_rules_reject_negative_values_in_model_and_database(self):
        for name in ('included_floor', 'multiplier'):
            with self.subTest(field=name):
                rule = self.settings.stair_lifting_rules.get(panel_count=1)
                setattr(rule, name, -1)
                with self.assertRaises(ValidationError) as error:
                    rule.save()
                self.assertIn(name, error.exception.message_dict)
                with self.assertRaises(IntegrityError), transaction.atomic():
                    self.settings.stair_lifting_rules.filter(pk=rule.pk).update(**{name: -1})

    def test_rule_range_and_uniqueness_are_enforced_by_database(self):
        for count in (0, 7, 11, 1):
            with self.subTest(count=count), self.assertRaises(IntegrityError), transaction.atomic():
                StairLiftingRule.objects.bulk_create([
                    StairLiftingRule(settings=self.settings, panel_count=count, included_floor=1, multiplier=1),
                ])

    def test_rule_replacement_requires_contiguous_columns_and_valid_cells(self):
        before = self.settings.get_stair_lifting_rules()
        for rules in ({}, {2: (1, 1)}, {1: (1, 1), 3: (1, 1)},
                      {number: (1, 1) for number in range(1, 8)}, {1: (-1, 1)}, {1: (1, Decimal('1.001'))}):
            with self.subTest(rules=rules), self.assertRaises(ValidationError):
                self.settings.set_stair_lifting_rules(rules)
            self.assertEqual(self.settings.get_stair_lifting_rules(), before)

    def test_hidden_material_selectors_require_explicit_defaults(self):
        for visibility, field in (
            ('show_glass_type', 'default_glass_type'),
            ('show_decoration_type', 'default_decoration_type'),
        ):
            with self.subTest(field=field):
                self.settings.refresh_from_db()
                setattr(self.settings, visibility, False)
                with self.assertRaises(ValidationError) as error:
                    self.settings.save()
                self.assertIn(field, error.exception.message_dict)


class CalculatorOptionTests(TestCase):
    def test_options_are_independent_editable_lists_with_stable_order(self):
        for model in (GlassType, DecorationType):
            with self.subTest(model=model.__name__):
                later = model.objects.create(name=' Позже ', price_per_sqm='120.75', position=20)
                first = model.objects.create(name='Первый', price_per_sqm='0', position=10)
                second = model.objects.create(name='Второй', price_per_sqm='10', position=10)
                self.assertEqual(list(model.objects.all()), [first, second, later])
                later.refresh_from_db()
                self.assertEqual(later.name, 'Позже')
                self.assertEqual(later.price_per_sqm, Decimal('120.75'))

    def test_names_are_required_and_unique_after_trimming(self):
        for model in (GlassType, DecorationType):
            model.objects.create(name='Вариант', price_per_sqm=0)
            for name in (' ', None, ' Вариант '):
                with self.subTest(model=model.__name__, name=name), self.assertRaises(ValidationError):
                    model.objects.create(name=name, price_per_sqm=0)

    def test_option_price_validation_and_database_constraints(self):
        for model in (GlassType, DecorationType):
            option = model.objects.create(name='Вариант', price_per_sqm=0)
            for price in ('-1', '1.001', 'NaN', 'Infinity', '100000000.00'):
                with self.subTest(model=model.__name__, price=price), self.assertRaises(ValidationError):
                    option.price_per_sqm = price
                    option.save()
            with self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.filter(pk=option.pk).update(price_per_sqm=-1)

    def test_defaults_are_protected_and_visibility_stays_consistent(self):
        for model, field, visibility in (
            (GlassType, 'default_glass_type', 'show_glass_type'),
            (DecorationType, 'default_decoration_type', 'show_decoration_type'),
        ):
            with self.subTest(model=model.__name__):
                option = model.objects.create(name='Основной', price_per_sqm='123.45')
                settings = CalculatorTariffs.objects.get(pk=CalculatorTariffs.CODE)
                setattr(settings, field, option)
                settings.save()
                with self.assertRaises(ProtectedError):
                    option.delete()
                with self.assertRaises(ProtectedError):
                    model.objects.filter(pk=option.pk).delete()
                option.is_visible = False
                with self.assertRaises(ValidationError) as error:
                    option.save()
                self.assertIn('is_visible', error.exception.message_dict)
                setattr(settings, visibility, False)
                settings.save()
                option.save()
                settings.refresh_from_db()
                self.assertEqual(getattr(settings, f'{field}_id'), option.pk)
                setattr(settings, visibility, True)
                with self.assertRaises(ValidationError) as error:
                    settings.save()
                self.assertIn(field, error.exception.message_dict)


class CalculatorAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.superuser = users.objects.create_superuser('calculator-owner', password=None)
        cls.staff = users.objects.create_user('calculator-staff', is_staff=True)
        cls.staff.user_permissions.set(Permission.objects.filter(content_type__app_label='calculator'))
        cls.glass = GlassType.objects.create(name='Обычное', price_per_sqm='100.00')
        cls.decoration = DecorationType.objects.create(name='Печать', price_per_sqm='20.00')
        settings = CalculatorTariffs.objects.get(pk=CalculatorTariffs.CODE)
        settings.default_glass_type = cls.glass
        settings.default_decoration_type = cls.decoration
        settings.save()
        cls.card_url = reverse('admin:calculator_calculatortariffs_change', args=[settings.pk])
        cls.list_url = reverse('admin:calculator_calculatortariffs_changelist')
        cls.settings_url = reverse('admin:calculator_calculatorsettings_change', args=[CalculatorSettings.CODE])

    def setUp(self):
        self.client.force_login(self.superuser)

    def settings_data(self, *, rules=None, service_changes=None, **changes):
        settings = CalculatorTariffs.objects.get(pk=CalculatorTariffs.CODE)
        values = model_to_dict(settings)
        values.update(changes)
        rules = settings.get_stair_lifting_rules() if rules is None else rules
        services = list(settings.services.all())
        inline = {'services-TOTAL_FORMS': str(len(services)), 'services-INITIAL_FORMS': str(len(services)),
                  'services-MIN_NUM_FORMS': '0', 'services-MAX_NUM_FORMS': '1000'}
        for index, service in enumerate(services):
            data = {**model_to_dict(service), **(service_changes or {}).get(service.code, {})}
            inline.update({f'services-{index}-{name}': 'on' if value is True else '' if value is False or value is None else str(value)
                           for name, value in data.items() if name in ('id', 'settings', 'is_visible', 'price_per_unit', 'discount_percent', 'position')})
        return {
            **inline,
            **{key: 'on' if value is True else '' if value is None else str(value)
               for key, value in values.items() if value is not False},
            'stair_lifting_rules_count': str(len(rules)),
            **{f'stair_lifting_rules_{field}_{number}': str(value)
               for number, pair in rules.items()
               for field, value in zip(('included_floor', 'multiplier'), pair)},
            '_save': 'Сохранить',
        }

    def test_index_contains_all_three_sections_and_settings_opens_directly(self):
        index = self.client.get(reverse('admin:index'))
        for text in ('Калькулятор скинали', 'Настройки калькулятора', 'Тарифы и услуги', 'Типы стекла', 'Декорирование'):
            self.assertContains(index, text)
        self.assertRedirects(self.client.get(self.list_url), self.card_url, fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse('admin:calculator_calculatorsettings_changelist')),
                             self.settings_url, fetch_redirect_response=False)

    def test_settings_form_has_expected_tariffs_and_fixed_included_services(self):
        response = self.client.get(self.card_url)
        self.assertEqual(response.status_code, 200)
        fields = response.context['adminform'].form.fields
        self.assertNotIn('is_enabled', fields)
        for visibility, prices in UNIQUE_PRICE_FIELDS:
            self.assertIn(visibility, fields)
            for field in prices:
                self.assertIn(field, fields)
        for forbidden in ('measurement_price', 'installation_price', 'delivery_base_price', 'lifting_workers'):
            self.assertNotIn(forbidden, fields)
        self.assertContains(response, 'Включено в стоимость')
        model_admin = admin.site._registry[CalculatorTariffs]
        for text in ('Количество работников', 'Бригада', 'Работников'):
            self.assertNotContains(response, text)
        self.assertEqual(len(response.context['inline_admin_formsets'][0].formset.forms), 7)
        self.assertContains(response, 'Добавить услугу')
        self.assertContains(response, 'aria-label="Редактировать услугу ', count=7)
        self.assertContains(response, 'aria-label="Удалить услугу ', count=7)
        self.assertContains(response, 'data-service-order-handle', count=7)
        self.assertContains(response, 'skinali/js/admin-order.js')
        self.assertContains(response, 'calculator/js/admin-service-order.js')
        for form in response.context['inline_admin_formsets'][0].formset.forms:
            self.assertTrue(form.fields['position'].widget.is_hidden)

    def test_settings_save_tariffs_and_visibility_with_admin_history(self):
        data = self.settings_data(
            service_changes={'delivery': {'is_visible': True, 'price_per_unit': '1.25'}},
            show_stair_lifting=True, stair_lifting_min_price='50.00',
            stair_lifting_price_per_panel_floor='6.00', show_glass_type=False,
        )
        self.assertEqual(self.client.post(self.card_url, data).status_code, 302)
        settings = CalculatorTariffs.objects.get(pk=CalculatorTariffs.CODE)
        self.assertEqual(settings.services.get(code='delivery').price_per_unit, Decimal('1.25'))
        self.assertEqual(settings.stair_lifting_min_price, Decimal('50.00'))
        self.assertFalse(settings.show_glass_type)
        self.assertTrue(LogEntry.objects.filter(
            content_type__app_label='calculator', action_flag=CHANGE,
            object_id=CalculatorTariffs.CODE,
        ).exists())

    def test_stair_rules_render_as_editable_table_with_saved_values(self):
        settings = CalculatorTariffs.objects.get(pk=CalculatorTariffs.CODE)
        settings.stair_lifting_rules.filter(panel_count=2).update(included_floor=5, multiplier=Decimal('1.25'))
        response = self.client.get(self.card_url)
        form = response.context['adminform'].form
        self.assertContains(response, 'calculator/css/admin-stair-lifting-rules.css')
        self.assertContains(response, 'calculator/js/admin-stair-lifting-rules.js')
        self.assertContains(response, 'Добавить столбец')
        self.assertContains(response, 'Удалить столбец')
        self.assertContains(response, 'data-max="6"')
        self.assertContains(response, 'От 1 до 6 панелей.')
        self.assertNotContains(response, 'data-rule-column="7"')
        self.assertContains(response, '<th scope="row">Этаж</th>', html=True)
        self.assertContains(response, '<th scope="row">Коэффициент сложности</th>', html=True)
        context = form.fields['stair_lifting_rules'].widget.get_context(
            'stair_lifting_rules', form['stair_lifting_rules'].value(), {},
        )['widget']
        self.assertEqual(context['count'], 4)
        self.assertEqual(len(context['columns']), MAX_STAIR_PANELS)
        self.assertEqual(context['rule_rows'][0][1][1][1]['value'], '5')
        self.assertEqual(context['rule_rows'][1][1][1][1]['value'], '1.25')
        for label, cells in context['rule_rows']:
            for index, (hidden, subwidget) in enumerate(cells):
                self.assertEqual(hidden, index >= 4)
                self.assertEqual(subwidget['attrs']['disabled'], hidden)
                self.assertEqual(subwidget['attrs']['required'], not hidden)

    def test_stair_rules_save_all_cells_and_preserve_tariffs_when_hidden(self):
        data = self.settings_data(
            rules={1: (2, '0.50'), 2: (5, '1.25'), 3: (7, '2.50'), 4: (11, '3.75')},
            stair_lifting_min_price='50.00', stair_lifting_price_per_panel_floor='6.00',
        )
        self.assertEqual(self.client.post(self.card_url, data).status_code, 302)
        settings = CalculatorTariffs.objects.get(pk=CalculatorTariffs.CODE)
        self.assertEqual(settings.get_stair_lifting_rules(), {
            1: (2, Decimal('0.50')), 2: (5, Decimal('1.25')),
            3: (7, Decimal('2.50')), 4: (11, Decimal('3.75')),
        })
        self.assertFalse(settings.show_stair_lifting)
        self.assertEqual(settings.stair_lifting_min_price, Decimal('50'))
        self.assertEqual(settings.stair_lifting_price_per_panel_floor, Decimal('6'))

    def test_invalid_stair_cell_keeps_table_values_and_does_not_save_other_changes(self):
        for field, value in (
            ('included_floor', ''), ('included_floor', '-1'), ('included_floor', '1.5'), ('included_floor', '1000000000'),
            ('multiplier', ''), ('multiplier', '-0.01'), ('multiplier', '1.001'),
            ('multiplier', '10000'), ('multiplier', 'NaN'), ('multiplier', 'Infinity'),
        ):
            with self.subTest(field=field, value=value):
                data = self.settings_data(show_glass_type=False)
                data.update(stair_lifting_rules_included_floor_2='17', **{f'stair_lifting_rules_{field}_1': value})
                response = self.client.post(self.card_url, data)
                self.assertEqual(response.status_code, 200)
                form = response.context['adminform'].form
                self.assertIn('stair_lifting_rules', form.errors)
                self.assertEqual(form['stair_lifting_rules'].value()['rules'][2][0], '17')
                settings = CalculatorTariffs.objects.get(pk=CalculatorTariffs.CODE)
                self.assertTrue(settings.show_glass_type)
                self.assertEqual(settings.get_stair_lifting_rules()[2][0], 4)

    def test_public_visibility_toggle_keeps_admin_preview_and_tariffs_available(self):
        settings = CalculatorSettings.objects.get(pk=CalculatorSettings.CODE)
        tariffs = CalculatorTariffs.objects.get(pk=CalculatorTariffs.CODE)
        tariffs_before = model_to_dict(tariffs)
        services_before = list(tariffs.services.values())
        rules_before = tariffs.get_stair_lifting_rules()
        preview_url = reverse('admin:calculator_calculatortariffs_calculate')
        card = self.client.get(self.settings_url)
        self.assertEqual(list(card.context['adminform'].form.fields), [
            'is_enabled', 'material_discount_mode', 'marketing_discount_percent', 'marketing_discount_description',
        ])
        self.assertEqual(len(card.context['inline_admin_formsets']), 2)
        self.assertContains(card, self.list_url)
        self.assertContains(self.client.get(self.card_url), reverse('admin:calculator_calculatorsettings_changelist'))
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                response = self.client.post(self.settings_url, {
                    **model_to_dict(settings),
                    **{f'{mode}_discounts-{key}': '0' for mode in ('stepped', 'progressive') for key in ('TOTAL_FORMS', 'INITIAL_FORMS')},
                    'is_enabled': 'on' if enabled else '', 'show_glass_type': '',
                    'stair_lifting_min_price': '999',
                })
                self.assertEqual(response.status_code, 302)
                settings.refresh_from_db()
                self.assertEqual(settings.is_enabled, enabled)
                tariffs.refresh_from_db()
                self.assertEqual(model_to_dict(tariffs), tariffs_before)
                self.assertEqual(list(tariffs.services.values()), services_before)
                self.assertEqual(tariffs.get_stair_lifting_rules(), rules_before)
                self.assertEqual(self.client.post(self.card_url, self.settings_data(is_enabled=not enabled)).status_code, 302)
                settings.refresh_from_db()
                self.assertEqual(settings.is_enabled, enabled)
                self.assertEqual(self.client.get(preview_url).status_code, 200)
                result = self.client.post(preview_url, {
                    'panels-TOTAL_FORMS': '1', 'panels-INITIAL_FORMS': '0',
                    'panels-0-width_mm': '1000', 'panels-0-height_mm': '1000',
                    'glass_type': self.glass.pk, 'decoration_type': self.decoration.pk,
                })
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.context['result'].total, Decimal('120'))

    def test_stair_table_commit_false_defers_database_write(self):
        settings = CalculatorTariffs.objects.get(pk=CalculatorTariffs.CODE)
        form = CalculatorTariffsAdminForm(
            self.settings_data(rules={1: (0, '0.00')}),
            instance=settings,
        )
        self.assertTrue(form.is_valid(), form.errors)
        unsaved = form.save(commit=False)
        self.assertEqual(unsaved.get_stair_lifting_rules()[1], (9, Decimal('1')))
        unsaved.save()
        form.save_m2m()
        settings.refresh_from_db()
        self.assertEqual(settings.get_stair_lifting_rules()[1], (0, Decimal('0')))

    def test_columns_can_expand_to_six_and_shrink_to_one(self):
        for count in (6, 1):
            with self.subTest(count=count):
                rules = {number: (number + 1, Decimal(number) / 2) for number in range(1, count + 1)}
                data = self.settings_data(rules=rules)
                data['stair_lifting_rules_multiplier_7'] = '-1'
                if count == 1:
                    data['stair_lifting_rules_multiplier_2'] = '-1'
                response = self.client.post(self.card_url, data)
                self.assertEqual(response.status_code, 302)
                settings = CalculatorTariffs.objects.get(pk=CalculatorTariffs.CODE)
                self.assertEqual(settings.get_stair_lifting_rules(), rules)
                form = self.client.get(self.card_url).context['adminform'].form
                self.assertEqual(len(form.initial['stair_lifting_rules']), count)
                self.assertNotIn('stair_lifting_rules', CalculatorTariffsAdminForm(data, instance=settings).changed_data)
                settings.show_stair_lifting = True
                settings.stair_lifting_min_price = settings.stair_lifting_price_per_panel_floor = Decimal('0')
                settings.save()
                preview = self.client.get(reverse('admin:calculator_calculatortariffs_calculate'))
                self.assertEqual(preview.context['form'].fields['stair_panel_count'].max_value, count)

    def test_invalid_column_count_and_empty_new_column_do_not_change_rules(self):
        before = CalculatorTariffs.objects.get(pk=CalculatorTariffs.CODE).get_stair_lifting_rules()
        for count in ('', '0', '7', '11', '-1', '1.5', '1000000000', '5'):
            with self.subTest(count=count):
                data = self.settings_data(show_glass_type=False)
                if count == '7':
                    data = self.settings_data(rules={number: (1, '1') for number in range(1, 8)}, show_glass_type=False)
                data['stair_lifting_rules_count'] = count
                response = self.client.post(self.card_url, data)
                self.assertEqual(response.status_code, 200)
                self.assertIn('stair_lifting_rules', response.context['adminform'].form.errors)
                settings = CalculatorTariffs.objects.get(pk=CalculatorTariffs.CODE)
                self.assertTrue(settings.show_glass_type)
                self.assertEqual(settings.get_stair_lifting_rules(), before)

    def test_direct_form_save_rolls_back_card_and_rules_if_inserting_rules_fails(self):
        settings = CalculatorTariffs.objects.get(pk=CalculatorTariffs.CODE)
        before = settings.get_stair_lifting_rules()
        form = CalculatorTariffsAdminForm(
            self.settings_data(rules={1: (1, '1.25')}, show_glass_type=False), instance=settings,
        )
        self.assertTrue(form.is_valid(), form.errors)
        with patch('django.db.models.query.QuerySet.bulk_create', side_effect=IntegrityError), self.assertRaises(IntegrityError):
            form.save()
        settings.refresh_from_db()
        self.assertTrue(settings.show_glass_type)
        self.assertEqual(settings.get_stair_lifting_rules(), before)

    def test_invalid_tariff_stays_on_form_and_does_not_change_settings(self):
        for value in ('', '-0.01', '1.001'):
            with self.subTest(value=value):
                response = self.client.post(self.card_url, self.settings_data(
                    show_stair_lifting=True, stair_lifting_min_price='50', stair_lifting_price_per_panel_floor=value,
                ))
                self.assertEqual(response.status_code, 200)
                self.assertIn('stair_lifting_price_per_panel_floor', response.context['adminform'].form.errors)
                settings = CalculatorTariffs.objects.get(pk=CalculatorTariffs.CODE)
                self.assertFalse(settings.show_stair_lifting)
                self.assertIsNone(settings.stair_lifting_price_per_panel_floor)

    def test_invalid_service_inline_does_not_save_card_or_stair_rules(self):
        data = self.settings_data(
            rules={1: (1, '1')}, show_glass_type=False,
            service_changes={'delivery': {'is_visible': True, 'price_per_unit': None}},
        )
        response = self.client.post(self.card_url, data)
        self.assertEqual(response.status_code, 200)
        formset = response.context['inline_admin_formsets'][0].formset
        self.assertTrue(any('price_per_unit' in form.errors for form in formset.forms))
        settings = CalculatorTariffs.objects.get(pk=CalculatorTariffs.CODE)
        self.assertTrue(settings.show_glass_type)
        self.assertEqual(settings.stair_lifting_rules.count(), 4)
        self.assertEqual(settings.get_stair_lifting_rules()[1][0], 9)
        self.assertFalse(settings.services.get(code='delivery').is_visible)

    def test_dragged_service_order_saves_with_card_and_is_used_by_preview(self):
        CalculatorService.objects.filter(has_price=True).update(is_visible=True, price_per_unit=0)
        rows = list(CalculatorService.objects.all())
        expected = [service.pk for service in reversed(rows)]
        changes = {service.code: {'position': index} for index, service in enumerate(reversed(rows), 1)}
        response = self.client.post(self.card_url, self.settings_data(service_changes=changes))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(CalculatorService.objects.values_list('pk', flat=True)), expected)
        self.assertEqual(list(CalculatorService.objects.values_list('position', flat=True)), list(range(1, 8)))
        response = self.client.get(reverse('admin:calculator_calculatortariffs_calculate'))
        self.assertEqual([row['service'].pk for row in response.context['form'].service_rows], expected)

    def test_invalid_service_price_preserves_unsaved_order_without_partial_database_changes(self):
        rows = list(CalculatorService.objects.all())
        expected = [service.pk for service in rows]
        changes = {service.code: {'position': index} for index, service in enumerate(reversed(rows), 1)}
        changes['delivery'].update(is_visible=True, price_per_unit=None)
        response = self.client.post(self.card_url, self.settings_data(service_changes=changes))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(CalculatorService.objects.values_list('pk', flat=True)), expected)
        forms = response.context['inline_admin_formsets'][0].formset.forms
        self.assertTrue(any('price_per_unit' in form.errors for form in forms))
        self.assertEqual([int(form['position'].value()) for form in forms], list(range(7, 0, -1)))

    def test_unknown_inline_service_id_returns_validation_error(self):
        data = self.settings_data(show_glass_type=False)
        data['services-0-id'] = '99999999'
        response = self.client.post(self.card_url, data)
        self.assertEqual(response.status_code, 200)
        formset = response.context['inline_admin_formsets'][0].formset
        self.assertTrue(any('id' in form.errors for form in formset.forms))
        self.assertTrue(CalculatorTariffs.objects.get(pk=CalculatorTariffs.CODE).show_glass_type)
        self.assertEqual(CalculatorService.objects.count(), 7)

    def test_materials_can_be_added_edited_and_deleted_in_admin(self):
        for model in (GlassType, DecorationType):
            model_name = model._meta.model_name
            with self.subTest(model=model_name):
                add_url = reverse(f'admin:calculator_{model_name}_add')
                data = {'name': 'Новый вариант', 'price_per_sqm': '130.25', 'position': '10',
                        'is_visible': 'on', '_save': 'Сохранить'}
                self.assertEqual(self.client.post(add_url, data).status_code, 302)
                option = model.objects.get(name='Новый вариант')
                data.update(price_per_sqm='140.50')
                data.pop('is_visible')
                change_url = reverse(f'admin:calculator_{model_name}_change', args=[option.pk])
                self.assertEqual(self.client.post(change_url, data).status_code, 302)
                option.refresh_from_db()
                self.assertEqual(option.price_per_sqm, Decimal('140.50'))
                self.assertFalse(option.is_visible)
                self.assertEqual(LogEntry.objects.filter(
                    content_type__app_label='calculator', content_type__model=model_name,
                    object_id=str(option.pk), action_flag__in=(ADDITION, CHANGE),
                ).count(), 2)
                delete_url = reverse(f'admin:calculator_{model_name}_delete', args=[option.pk])
                self.assertEqual(self.client.post(delete_url, {'post': 'yes'}).status_code, 302)
                self.assertFalse(model.objects.filter(pk=option.pk).exists())

    def test_default_cannot_be_hidden_via_list_editable_or_deleted(self):
        for model, option in ((GlassType, self.glass), (DecorationType, self.decoration)):
            model_name = model._meta.model_name
            list_url = reverse(f'admin:calculator_{model_name}_changelist')
            response = self.client.post(list_url, {
                'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '1',
                'form-MIN_NUM_FORMS': '0', 'form-MAX_NUM_FORMS': '1000',
                'form-0-id': str(option.pk), 'form-0-price_per_sqm': '100.00',
                'form-0-position': '0', '_save': 'Сохранить',
            })
            self.assertEqual(response.status_code, 200)
            self.assertIn('is_visible', response.context['cl'].formset.forms[0].errors)
            option.refresh_from_db()
            self.assertTrue(option.is_visible)
            delete_url = reverse(f'admin:calculator_{model_name}_delete', args=[option.pk])
            response = self.client.post(delete_url, {'post': 'yes'})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['protected'])
            self.assertTrue(model.objects.filter(pk=option.pk).exists())

    def test_singleton_cannot_be_added_or_deleted(self):
        for model in (CalculatorSettings, CalculatorTariffs):
            for action in ('add', 'delete'):
                url = reverse(f'admin:calculator_{model._meta.model_name}_{action}',
                              args=[model.CODE] if action == 'delete' else [])
                self.assertEqual(self.client.post(url, {'post': 'yes'}).status_code, 403)

    def test_staff_with_all_model_permissions_cannot_access_any_calculator_action(self):
        self.client.force_login(self.staff)
        self.assertNotContains(self.client.get(reverse('admin:index')), 'Калькулятор скинали')
        for model, pk in ((CalculatorSettings, CalculatorSettings.CODE), (CalculatorTariffs, CalculatorTariffs.CODE),
                          (GlassType, self.glass.pk), (DecorationType, self.decoration.pk),
                          (CalculatorService, CalculatorService.objects.first().pk),
                          (MeasurementUnit, MeasurementUnit.objects.first().pk)):
            for action in ('changelist', 'add', 'change', 'delete'):
                url = reverse(f'admin:calculator_{model._meta.model_name}_{action}',
                              args=[pk] if action in ('change', 'delete') else [])
                with self.subTest(model=model.__name__, action=action):
                    self.assertEqual(self.client.get(url).status_code, 403)
                    self.assertEqual(self.client.post(url, {'post': 'yes'}).status_code, 403)

    def test_anonymous_and_inactive_users_cannot_edit_settings(self):
        self.client.logout()
        self.assertEqual(self.client.post(self.card_url, self.settings_data()).status_code, 302)
        request = RequestFactory().get(self.card_url)
        self.superuser.is_active = False
        request.user = self.superuser
        for model in (CalculatorSettings, CalculatorTariffs, GlassType, DecorationType, CalculatorService, MeasurementUnit):
            model_admin = admin.site._registry[model]
            for action in ('module', 'view', 'add', 'change', 'delete'):
                self.assertFalse(getattr(model_admin, f'has_{action}_permission')(request))

    def test_csrf_protects_settings_and_price_changes(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.superuser)
        self.assertEqual(client.post(self.card_url, self.settings_data(show_glass_type=False)).status_code, 403)
        self.assertEqual(client.post(self.settings_url, {'is_enabled': 'on'}).status_code, 403)
        self.assertFalse(CalculatorSettings.objects.get().is_enabled)
        self.assertTrue(CalculatorTariffs.objects.get(pk=CalculatorTariffs.CODE).show_glass_type)
        url = reverse('admin:calculator_glasstype_change', args=[self.glass.pk])
        self.assertEqual(client.post(url, {'price_per_sqm': '0'}).status_code, 403)
        self.glass.refresh_from_db()
        self.assertEqual(self.glass.price_per_sqm, Decimal('100.00'))
