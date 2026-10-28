from decimal import Decimal, ROUND_CEILING

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .calculation import MAX_PANELS, Panel, calculate_price
from .models import CalculatorSettings
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

    def test_progressive_discount_starts_only_above_two_square_metres(self):
        self.set_material_prices()
        self.general.area_discount_percent = Decimal('10')
        self.general.save()
        for width, expected in ((500, '50'), (1000, '100'), (1500, '150'),
                                (2000, '200'), (2500, '230.5'), (3000, '271')):
            with self.subTest(width=width):
                result = calculate_price(self.calculation_input(panels=(Panel(width, 1000),)))
                self.assertEqual(result.subtotal, Decimal(expected))
                self.assertEqual(result.total, Decimal(expected).quantize(Decimal('1'), rounding=ROUND_CEILING))
                self.assertEqual(result.materials_discount, result.area_sqm * 100 - Decimal(expected))
                self.assertEqual(sum(line.amount for line in result.lines), result.subtotal)
        for panels, subtotal, discount in (
            ((Panel(1999, 1000), Panel(999, 1)), '200', '0'),
            ((Panel(2000, 1000),), '200', '0'),
            ((Panel(2000, 1000), Panel(1, 1)), '200', '0'),
            ((Panel(2005, 1000),), '190.81', '10.19'),
        ):
            with self.subTest(boundary_panels=panels):
                result = calculate_price(self.calculation_input(panels=panels))
                self.assertEqual(result.subtotal, Decimal(subtotal))
                self.assertEqual(result.materials_discount, Decimal(discount))

    def test_discount_uses_total_area_across_panels_and_saved_percentage(self):
        self.set_material_prices()
        self.general.area_discount_percent = Decimal('10')
        self.general.save()
        combined = calculate_price(self.calculation_input(panels=(Panel(2500, 1000),)))
        split = calculate_price(self.calculation_input(panels=(Panel(1000, 1000), Panel(1500, 1000))))
        self.assertEqual((split.subtotal, split.materials_discount), (combined.subtotal, combined.materials_discount))
        response = self.client.post(self.preview_url, self.post_data(**{
            'panels-0-width_mm': '1000', 'panels-0-height_mm': '1000',
            'panels-1-width_mm': '1500', 'panels-1-height_mm': '1000',
            'area_discount_percent': '99',
        }))
        self.assertEqual(response.context['result'].subtotal, Decimal('230.5'))
        self.assertContains(response, 'Скидка на стекло и декорирование')

    def test_discount_leaves_services_and_stairs_unchanged_and_marketing_uses_discounted_total(self):
        self.set_material_prices()
        data = self.calculation_input(
            panels=(Panel(2500, 1000),), backlight_length_m=Decimal('1.5'), socket_blocks=2,
            hydrophobic=True, delivery_distance_km=Decimal('12.5'), stair_floor=5,
        )
        baseline = calculate_price(data)
        self.general.area_discount_percent = Decimal('10')
        self.general.marketing_discount_percent = Decimal('20')
        self.general.save()
        result = calculate_price(data)
        self.assertEqual(result.materials_discount, Decimal('19.5'))
        self.assertEqual(result.subtotal, Decimal('336.55'))
        self.assertEqual(result.total, Decimal('337'))
        self.assertEqual(result.comparison_total, Decimal('422'))
        self.assertEqual(tuple(line for line in result.lines if line.code != 'materials_discount'), baseline.lines)

    def test_zero_and_full_discount_respect_threshold_and_large_area_is_supported(self):
        self.set_material_prices()
        for percent, expected in (('0', '250'), ('100', '100')):
            with self.subTest(percent=percent):
                self.general.area_discount_percent = Decimal(percent)
                self.general.save()
                result = calculate_price(self.calculation_input(panels=(Panel(2500, 1000),)))
                self.assertEqual(result.subtotal, Decimal(expected))
                self.assertEqual(calculate_price(self.calculation_input(panels=(Panel(500, 1000),))).subtotal, Decimal('50'))
                self.assertEqual(calculate_price(self.calculation_input(panels=(Panel(2000, 1000),))).subtotal, Decimal('200'))
        self.general.area_discount_percent = Decimal('10')
        self.general.save()
        result = calculate_price(self.calculation_input(panels=(Panel(6000, 6000),) * MAX_PANELS))
        self.assertEqual(result.total, Decimal('1000'))

    def test_area_discount_rejects_out_of_range_and_invalid_precision(self):
        for value in ('-0.01', '100.01', '0.001', 'NaN', 'Infinity'):
            with self.subTest(value=value):
                self.general.area_discount_percent = Decimal(value)
                with self.assertRaises(ValidationError) as error:
                    self.general.save()
                self.assertIn('area_discount_percent', error.exception.message_dict)
        for value in ('-1', '101'):
            with self.assertRaises(IntegrityError), transaction.atomic():
                CalculatorSettings.objects.update(area_discount_percent=Decimal(value))

    def test_admin_saves_promotions_and_invalid_values_do_not_overwrite_previous_settings(self):
        url = reverse('admin:calculator_calculatorsettings_change', args=[CalculatorSettings.CODE])
        description = 'Скидка на заказ\nПодробные условия акции'
        data = {'area_discount_percent': '10', 'marketing_discount_percent': '20',
                'marketing_discount_description': description}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.general.refresh_from_db()
        self.assertEqual((self.general.area_discount_percent, self.general.marketing_discount_percent),
                         (Decimal('10'), Decimal('20')))
        self.assertEqual(self.general.marketing_discount_description, description)
        response = self.client.post(url, {**data, 'area_discount_percent': '101', 'marketing_discount_percent': '2'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('area_discount_percent', response.context['adminform'].form.errors)
        self.general.refresh_from_db()
        self.assertEqual(self.general.marketing_discount_percent, Decimal('20'))
        self.assertEqual(self.general.marketing_discount_description, description)

    def test_marketing_description_is_optional_validated_and_does_not_change_quote(self):
        baseline = calculate_price(self.calculation_input())
        self.general.marketing_discount_description = '<Условия акции>\nВторая строка'
        self.general.save()
        self.assertEqual(calculate_price(self.calculation_input()), baseline)
        url = reverse('admin:calculator_calculatorsettings_change', args=[CalculatorSettings.CODE])
        self.assertContains(self.client.get(url), '&lt;Условия акции&gt;')
        data = {'area_discount_percent': '0', 'marketing_discount_percent': '0',
                'marketing_discount_description': 'x' * 2001}
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
