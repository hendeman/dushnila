from decimal import Decimal, ROUND_CEILING

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from .calculation import CalculatorConfigurationError, MAX_PANELS, Panel, calculate_price
from .models import CalculatorSettings, MaterialDiscountRule
from .test_calculation import CalculationFixture


class PromotionTests(CalculationFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = get_user_model().objects.create_superuser('promotion-owner', password=None)

    def setUp(self):
        self.general = CalculatorSettings.objects.get(pk=CalculatorSettings.CODE)
        self.client.force_login(self.owner)
        self.preview_url = reverse('admin:calculator_calculatortariffs_calculate')

    def set_material_prices(self):
        self.glass.price_per_sqm = Decimal('60')
        self.glass.save()
        self.decoration.price_per_sqm = Decimal('40')
        self.decoration.save()

    def admin_data(self, **values):
        data = {'material_discount_mode': 'none', 'marketing_discount_percent': '0'}
        for mode in ('stepped', 'progressive'):
            data.update({f'{mode}_discounts-TOTAL_FORMS': '0', f'{mode}_discounts-INITIAL_FORMS': '0'})
        return {**data, **values}

    def quote_area(self, width):
        return calculate_price(self.calculation_input(panels=(Panel(width, 1000),)))

    def test_progressive_starts_at_two_inclusive_and_last_rate_is_fixed(self):
        self.set_material_prices()
        self.set_material_discount(rules=(('2', '10'), ('3', '20')))
        for width, expected in ((500, '50'), (1500, '150'), (1990, '199'), (2000, '190'), (2010, '190.8'),
                                (2500, '230'), (3000, '270'), (3500, '310'), (4000, '350'),
                                (5000, '430'), (6000, '510')):
            with self.subTest(width=width):
                result = self.quote_area(width)
                self.assertEqual(result.subtotal, Decimal(expected))
                self.assertEqual(result.total, Decimal(expected).quantize(Decimal('1'), rounding=ROUND_CEILING))
                self.assertEqual(result.materials_discount, result.area_sqm * 100 - Decimal(expected))
                self.assertEqual(sum(line.amount for line in result.lines), result.subtotal)

    def test_stepped_discount_applies_to_whole_area_from_two_inclusive(self):
        self.set_material_prices()
        self.set_material_discount('stepped', (('2', '2'), ('3', '3'), ('4', '4')))
        for width, expected in ((1500, '150'), (1990, '199'), (2000, '196'), (2010, '196.98'),
                                (2500, '245'), (3000, '291'), (4000, '384'), (5000, '480')):
            with self.subTest(width=width):
                self.assertEqual(self.quote_area(width).subtotal, Decimal(expected))

    def test_fractional_thresholds_and_rounded_area_at_inclusive_start(self):
        self.set_material_prices()
        self.set_material_discount(rules=(('2.5', '10'), ('3.25', '20')))
        for width, expected in ((2000, '200'), (2500, '237.5'), (2750, '257.5'), (3500, '317.5')):
            self.assertEqual(self.quote_area(width).subtotal, Decimal(expected))
        self.set_material_discount()
        for panels, expected in (((Panel(2000, 1000), Panel(1, 1)), '190'),
                                 ((Panel(2005, 1000),), '190.9')):
            self.assertEqual(calculate_price(self.calculation_input(panels=panels)).subtotal, Decimal(expected))

    def test_first_rule_sets_start_at_one_or_at_a_higher_value_for_each_mode(self):
        self.set_material_prices()
        examples = {
            'stepped': {
                '1': ((990, '99'), (1000, '90'), (1500, '135'), (2000, '160')),
                '3': ((2000, '200'), (2990, '299'), (3000, '270'), (3500, '315'), (4000, '320')),
            },
            'progressive': {
                '1': ((990, '99'), (1000, '90'), (1500, '130'), (2000, '170')),
                '3': ((2000, '200'), (2990, '299'), (3000, '290'), (3500, '330'), (4000, '370')),
            },
        }
        for mode, thresholds in examples.items():
            for start, cases in thresholds.items():
                self.set_material_discount(mode, ((str(Decimal(start) + 1), '20'), (start, '10')))
                for width, expected in cases:
                    with self.subTest(mode=mode, start=start, width=width):
                        self.assertEqual(self.quote_area(width).subtotal, Decimal(expected))

    def test_admin_accepts_first_rule_at_one_in_both_tables(self):
        self.set_material_prices()
        url = reverse('admin:calculator_calculatorsettings_change', args=[CalculatorSettings.CODE])
        for mode in ('stepped', 'progressive'):
            self.set_material_discount('none', ())
            data = self.admin_data(material_discount_mode=mode, **{
                f'{mode}_discounts-TOTAL_FORMS': '1', f'{mode}_discounts-0-area_from': '1',
                f'{mode}_discounts-0-discount_percent': '10'})
            with self.subTest(mode=mode):
                response = self.client.post(url, data)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(self.general.discount_rules.get(mode=mode).area_from, 1)
                self.assertEqual(self.quote_area(1000).subtotal, Decimal('90'))
                card = self.client.get(url)
                self.assertContains(card, 'min="1"')
                self.assertNotContains(card, 'При общей площади меньше 2 м² скидки нет.')

    def test_discount_uses_saved_rules_and_total_area_across_panels(self):
        self.set_material_prices()
        self.set_material_discount()
        combined = self.quote_area(2500)
        split = calculate_price(self.calculation_input(panels=(Panel(1000, 1000), Panel(1500, 1000))))
        self.assertEqual(split.materials_discount, combined.materials_discount)
        response = self.client.post(self.preview_url, self.post_data(**{
            'panels-0-width_mm': '2500', 'panels-0-height_mm': '1000',
            'panels-1-width_mm': '', 'panels-1-height_mm': '',
            'material_discount_mode': 'none', 'area_discount_percent': '99',
        }))
        self.assertEqual(response.context['result'].subtotal, Decimal('235'))
        self.assertContains(response, 'Скидка на стекло и декорирование')

    def test_services_stairs_and_marketing_keep_their_own_calculation(self):
        self.set_material_prices()
        data = self.calculation_input(panels=(Panel(2500, 1000),), backlight_length_m=Decimal('1.5'),
                                      socket_blocks=2, hydrophobic=True, delivery_distance_km=Decimal('12.5'), stair_floor=5)
        baseline = calculate_price(data)
        self.set_material_discount()
        self.general.marketing_discount_percent = Decimal('20')
        self.general.save()
        result = calculate_price(data)
        self.assertEqual(result.materials_discount, Decimal('15'))
        self.assertEqual(result.subtotal, baseline.subtotal - 15)
        self.assertEqual(result.comparison_total, (result.total / Decimal('.8')).to_integral_value(rounding=ROUND_CEILING))
        self.assertEqual(tuple(line for line in result.lines if line.code != 'materials_discount'), baseline.lines)

    def test_zero_full_discount_large_area_and_disabled_mode(self):
        self.set_material_prices()
        for mode in ('stepped', 'progressive'):
            for percent in ('0', '100'):
                self.set_material_discount(mode, (('2', percent),))
                self.assertEqual(self.quote_area(2000).subtotal, Decimal('200') if percent == '0' else (Decimal('0') if mode == 'stepped' else Decimal('100')))
                expected = '250' if percent == '0' else ('0' if mode == 'stepped' else '100')
                self.assertEqual(self.quote_area(2500).subtotal, Decimal(expected))
        self.set_material_discount()
        large = calculate_price(self.calculation_input(panels=(Panel(6000, 6000),) * MAX_PANELS))
        self.assertEqual(large.total, Decimal('32410'))
        self.general.material_discount_mode = 'none'
        self.general.save()
        self.assertEqual(self.quote_area(2500).subtotal, Decimal('250'))
        self.assertEqual(self.general.discount_rules.count(), 1)

    def test_rule_model_and_database_reject_invalid_values_and_duplicate_thresholds(self):
        for field, values in {'discount_percent': ('-0.01', '100.01', '.001', 'NaN', 'Infinity'),
                              'area_from': ('0.99', '1.001', '2.001', 'NaN', 'Infinity'), 'mode': ('none', 'unknown')}.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    MaterialDiscountRule.objects.create(**{
                        'settings': self.general, 'mode': 'stepped', 'area_from': 2, 'discount_percent': 10, field: value})
        rule = MaterialDiscountRule.objects.create(settings=self.general, mode='stepped', area_from=2, discount_percent=10)
        with self.assertRaises(ValidationError):
            MaterialDiscountRule.objects.create(settings=self.general, mode='stepped', area_from=2, discount_percent=20)
        for changes in ({'area_from': Decimal('0.99')}, {'discount_percent': -1}, {'discount_percent': 101}, {'mode': 'none'}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                MaterialDiscountRule.objects.filter(pk=rule.pk).update(**changes)
        self.general.material_discount_mode = 'invalid'
        with self.assertRaises(ValidationError):
            self.general.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CalculatorSettings.objects.update(material_discount_mode='invalid')

    def test_admin_adds_updates_deletes_rules_and_saves_marketing_atomically(self):
        url = reverse('admin:calculator_calculatorsettings_change', args=[CalculatorSettings.CODE])
        data = self.admin_data(material_discount_mode='stepped', marketing_discount_percent='20',
                               marketing_discount_description='Условия акции', **{
            'stepped_discounts-TOTAL_FORMS': '2', 'stepped_discounts-0-area_from': '2',
            'stepped_discounts-0-discount_percent': '2', 'stepped_discounts-1-area_from': '3',
            'stepped_discounts-1-discount_percent': '3'})
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        rules = list(self.general.discount_rules.order_by('area_from'))
        data.update({'stepped_discounts-INITIAL_FORMS': '2', 'stepped_discounts-0-id': rules[0].pk,
                     'stepped_discounts-1-id': rules[1].pk, 'stepped_discounts-0-discount_percent': '5',
                     'stepped_discounts-1-DELETE': 'on'})
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.general.discount_rules.count(), 1)
        self.assertEqual(self.general.discount_rules.get().discount_percent, 5)
        invalid = {**data, 'stepped_discounts-INITIAL_FORMS': '1', 'stepped_discounts-TOTAL_FORMS': '1',
                   'stepped_discounts-0-discount_percent': '101', 'marketing_discount_percent': '7'}
        self.assertEqual(self.client.post(url, invalid).status_code, 200)
        self.general.refresh_from_db()
        self.assertEqual(self.general.marketing_discount_percent, 20)
        self.assertEqual(self.general.discount_rules.get().discount_percent, 5)
        card = self.client.get(url)
        self.assertContains(card, 'Прогрессивная (скользящая) скидка')
        self.assertContains(card, 'Начало скидки задаёт первая строка таблицы.')
        self.assertContains(card, 'Начиная с м² №')

    def test_admin_requires_active_rules_rejects_duplicates_and_preserves_inactive_table(self):
        url = reverse('admin:calculator_calculatorsettings_change', args=[CalculatorSettings.CODE])
        self.assertEqual(self.client.post(url, self.admin_data(material_discount_mode='progressive')).status_code, 200)
        data = self.admin_data(material_discount_mode='stepped', **{
            'stepped_discounts-TOTAL_FORMS': '2', 'stepped_discounts-0-area_from': '2',
            'stepped_discounts-0-discount_percent': '10', 'stepped_discounts-1-area_from': '2',
            'stepped_discounts-1-discount_percent': '20'})
        self.assertEqual(self.client.post(url, data).status_code, 200)
        self.assertFalse(self.general.discount_rules.exists())
        data.update({'stepped_discounts-1-area_from': '3', 'progressive_discounts-TOTAL_FORMS': '1',
                     'progressive_discounts-0-area_from': '2', 'progressive_discounts-0-discount_percent': '20'})
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.set_material_prices()
        self.assertEqual(self.quote_area(2500).subtotal, Decimal('225'))
        self.general.refresh_from_db()
        self.general.material_discount_mode = 'progressive'
        self.general.save()
        self.assertEqual(self.quote_area(2500).subtotal, Decimal('220'))
        self.assertEqual(self.general.discount_rules.count(), 3)

    def test_active_mode_without_rules_fails_safely(self):
        self.general.material_discount_mode = 'progressive'
        self.general.save()
        with self.assertRaises(CalculatorConfigurationError):
            self.quote_area(2500)

    def test_admin_swaps_thresholds_and_can_reuse_deleted_threshold_in_one_save(self):
        self.set_material_discount('stepped', (('2', '10'), ('3', '20')))
        first, second = self.general.discount_rules.order_by('area_from')
        url = reverse('admin:calculator_calculatorsettings_change', args=[CalculatorSettings.CODE])
        data = self.admin_data(material_discount_mode='stepped', **{
            'stepped_discounts-TOTAL_FORMS': '2', 'stepped_discounts-INITIAL_FORMS': '2',
            'stepped_discounts-0-id': first.pk, 'stepped_discounts-0-area_from': '3',
            'stepped_discounts-0-discount_percent': '10',
            'stepped_discounts-1-id': second.pk, 'stepped_discounts-1-area_from': '2',
            'stepped_discounts-1-discount_percent': '20'})
        self.assertEqual(self.client.post(url, data).status_code, 302)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.area_from, second.area_from), (3, 2))
        data.update({'stepped_discounts-0-area_from': '2', 'stepped_discounts-1-DELETE': 'on'})
        self.assertEqual(self.client.post(url, data).status_code, 302)
        first.refresh_from_db()
        self.assertEqual(first.area_from, 2)
        self.assertFalse(self.general.discount_rules.filter(pk=second.pk).exists())

    def test_marketing_description_is_optional_validated_and_does_not_change_quote(self):
        baseline = calculate_price(self.calculation_input())
        self.general.marketing_discount_description = '<Условия акции>\nВторая строка'
        self.general.save()
        self.assertEqual(calculate_price(self.calculation_input()), baseline)
        url = reverse('admin:calculator_calculatorsettings_change', args=[CalculatorSettings.CODE])
        self.assertContains(self.client.get(url), '&lt;Условия акции&gt;')
        data = self.admin_data(marketing_discount_description='x' * 2001)
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('marketing_discount_description', response.context['adminform'].form.errors)
        self.general.refresh_from_db()
        self.assertEqual(self.general.marketing_discount_description, '<Условия акции>\nВторая строка')
        with self.assertRaises(ValidationError):
            self.general.marketing_discount_description = 'x' * 2001
            self.general.save()
        self.assertEqual(self.client.post(url, {**data, 'marketing_discount_description': ''}).status_code, 302)
        self.general.refresh_from_db()
        self.assertEqual(self.general.marketing_discount_description, '')

    def test_marketing_discount_percent_changes_only_comparison_price_after_final_rounding(self):
        data = self.calculation_input(
            backlight_length_m=Decimal('1.5'), railing_length_m=Decimal('0.75'),
            socket_blocks=2, hydrophobic=True, delivery_distance_km=Decimal('12.5'), stair_floor=5,
        )
        baseline = calculate_price(data)
        self.assertEqual(baseline.comparison_total, baseline.total)
        self.general.marketing_discount_percent = Decimal('20')
        self.general.save()
        result = calculate_price(data)
        self.assertEqual(result.total, Decimal('201'))
        self.assertEqual(result.comparison_total, Decimal('252'))
        self.assertEqual((result.lines, result.subtotal, result.rounding_adjustment),
                         (baseline.lines, baseline.subtotal, baseline.rounding_adjustment))

    def test_comparison_price_is_rendered_only_when_higher_and_post_cannot_override_discount(self):
        self.assertNotContains(self.client.post(self.preview_url, self.post_data()), 'Цена для зачёркивания')
        self.general.marketing_discount_percent = Decimal('20')
        self.general.save()
        response = self.client.post(self.preview_url, self.post_data(marketing_discount_percent='10', comparison_total='99999'))
        self.assertEqual(response.context['result'].total, Decimal('97'))
        self.assertEqual(response.context['result'].comparison_total, Decimal('122'))
        self.assertContains(response, '<s>122</s>', html=True)
        self.assertContains(response, 'маркетинговая скидка 20%')

    def test_marketing_discount_rejects_out_of_range_and_invalid_precision(self):
        for value in ('-0.01', '100', '100.01', '0.001', 'NaN', 'Infinity'):
            with self.subTest(value=value):
                self.general.marketing_discount_percent = Decimal(value)
                with self.assertRaises(ValidationError) as error:
                    self.general.save()
                self.assertIn('marketing_discount_percent', error.exception.message_dict)
        for value in ('-1', '100'):
            with self.assertRaises(IntegrityError), transaction.atomic():
                CalculatorSettings.objects.update(marketing_discount_percent=Decimal(value))

    def test_marketing_discount_matches_percentage_of_comparison_price_and_accepts_boundaries(self):
        self.set_material_prices()
        for percent, expected in (('0', '800'), ('20', '1000'), ('99.99', '8000000')):
            with self.subTest(percent=percent):
                self.general.marketing_discount_percent = Decimal(percent)
                self.general.save()
                result = calculate_price(self.calculation_input(panels=(Panel(4000, 2000),)))
                self.assertEqual(result.total, Decimal('800'))
                self.assertEqual(result.comparison_total, Decimal(expected))
        self.glass.price_per_sqm = Decimal('0')
        self.glass.save()
        self.decoration.price_per_sqm = Decimal('0')
        self.decoration.save()
        response = self.client.post(self.preview_url, self.post_data())
        self.assertEqual(response.context['result'].comparison_total, Decimal('0'))
        self.assertNotContains(response, 'Цена для зачёркивания')


class MaterialDiscountMigrationTests(TransactionTestCase):
    serialized_rollback = True
    previous = ('calculator', '0017_service_quantity_two_decimals')
    current = ('calculator', '0018_material_discount_rules')

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.migrate([target])
        return executor.loader.project_state([target]).apps

    def test_new_minimum_preserves_existing_rules_and_accepts_one(self):
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes('calculator')[0]
        self.addCleanup(self.migrate, latest)
        apps = self.migrate(('calculator', '0019_material_discount_inclusive_threshold'))
        settings = apps.get_model('calculator', 'CalculatorSettings').objects.get()
        rule_model = apps.get_model('calculator', 'MaterialDiscountRule')
        original = rule_model.objects.create(settings=settings, mode='stepped', area_from=2, discount_percent=15)
        with self.assertRaises(IntegrityError), transaction.atomic():
            rule_model.objects.create(settings=settings, mode='stepped', area_from=1, discount_percent=10)
        apps = self.migrate(('calculator', '0020_discount_start_from_first_rule'))
        rule_model = apps.get_model('calculator', 'MaterialDiscountRule')
        kept = rule_model.objects.get(pk=original.pk)
        self.assertEqual((kept.area_from, kept.discount_percent), (2, 15))
        added = rule_model.objects.create(settings_id=settings.pk, mode='stepped', area_from=1, discount_percent=10)
        self.assertEqual(added.area_from, 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            rule_model.objects.filter(pk=added.pk).update(area_from=Decimal('.99'))

    def test_old_percentage_is_preserved_and_zero_does_not_create_rules(self):
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes('calculator')[0]
        self.addCleanup(self.migrate, latest)
        old_apps = self.migrate(self.previous)
        old_settings = old_apps.get_model('calculator', 'CalculatorSettings')
        old_settings.objects.update(area_discount_percent=Decimal('5.50'), is_enabled=True,
                                    marketing_discount_percent=20, marketing_discount_description='Описание')
        apps = self.migrate(self.current)
        settings = apps.get_model('calculator', 'CalculatorSettings').objects.get()
        rule = apps.get_model('calculator', 'MaterialDiscountRule').objects.get()
        self.assertEqual(settings.material_discount_mode, 'progressive')
        self.assertEqual((rule.mode, rule.area_from, rule.discount_percent), ('progressive', 2, Decimal('5.50')))
        self.assertTrue(settings.is_enabled)
        self.assertEqual((settings.marketing_discount_percent, settings.marketing_discount_description), (20, 'Описание'))
        old_apps = self.migrate(self.previous)
        old_settings = old_apps.get_model('calculator', 'CalculatorSettings')
        self.assertEqual(old_settings.objects.get().area_discount_percent, Decimal('5.50'))
        old_settings.objects.update(area_discount_percent=0)
        apps = self.migrate(self.current)
        self.assertEqual(apps.get_model('calculator', 'CalculatorSettings').objects.get().material_discount_mode, 'none')
        self.assertFalse(apps.get_model('calculator', 'MaterialDiscountRule').objects.exists())
