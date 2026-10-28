import json
from pathlib import Path
import random
import shutil
import subprocess
from decimal import Decimal
from unittest import skipUnless

from django.test import TestCase
from django.urls import reverse

from sitecontent.models import MenuItem, SitePage

from .calculation import MAX_PANELS, Panel, ServiceSelection, calculate_price
from .models import CalculatorSettings
from .public import public_configuration
from .test_calculation import CalculationFixture


NODE = shutil.which('node')
ENGINE = Path(__file__).parent / 'static' / 'calculator' / 'js' / 'price-engine.js'


def browser_results(cases):
    result = subprocess.run(
        [NODE, '-e', "require(process.argv[1]); const fs = require('node:fs'); "
         "const cases = JSON.parse(fs.readFileSync(0, 'utf8')); "
         "process.stdout.write(JSON.stringify(cases.map(item => { try { "
         "return SkinaliPrice.calculate(item.config, item.input); "
         "} catch (error) { return {error: error.message}; } })));", str(ENGINE)],
        input=json.dumps(cases), text=True, encoding='utf-8', capture_output=True, timeout=20, check=True,
    )
    return json.loads(result.stdout)


class PublicCalculatorTests(CalculationFixture, TestCase):
    def setUp(self):
        self.general = CalculatorSettings.objects.get(pk=CalculatorSettings.CODE)
        self.general.is_enabled = True
        self.general.save()

    def test_public_page_has_menu_seo_favorites_and_safe_json_configuration(self):
        self.glass.name = '</script><script>alert(1)</script>'
        self.glass.save()
        SitePage.objects.filter(pk='price').update(seo_title='Расчёт цены', seo_description='Описание цены')
        response = self.client.get(reverse('price'))
        self.assertContains(response, '<h1>Рассчитайте стоимость скинали</h1>', html=True)
        self.assertContains(response, '<title>Расчёт цены | ОДИУМ</title>', html=True)
        self.assertContains(response, 'Описание цены')
        self.assertContains(response, 'price-calculator-config')
        self.assertEqual(response.context['calculator_config']['max_panel_dimension_mm'], 6000)
        self.assertEqual(response.context['calculator_config']['max_panels'], 10)
        self.assertContains(response, 'max="6000"', count=2)
        self.assertContains(response, '\\u003C/script\\u003E')
        self.assertNotContains(response, self.glass.name)
        self.assertEqual(response.context['favorites_count'], 0)
        self.assertContains(response, 'href="/price/"', count=2)
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertTrue(MenuItem.objects.filter(title='Цена', url='/price/', is_visible=True).exists())
        self.assertContains(self.client.get(reverse('sitemap')), '/price/</loc>')

    def test_disabled_missing_or_incomplete_settings_hide_inputs_and_prices(self):
        for mode in ('disabled', 'missing', 'incomplete'):
            with self.subTest(mode=mode):
                if mode == 'disabled':
                    CalculatorSettings.objects.update(is_enabled=False)
                elif mode == 'missing':
                    CalculatorSettings.objects.all().delete()
                else:
                    CalculatorSettings.objects.create(is_enabled=True)
                    self.settings.default_glass_type = None
                    self.settings.show_glass_type = False
                    type(self.settings).objects.filter(pk=self.settings.pk).update(
                        default_glass_type=None, show_glass_type=False,
                    )
                if mode == 'incomplete':
                    with self.assertLogs('calculator.views', level='WARNING'):
                        response = self.client.get(reverse('price'))
                else:
                    response = self.client.get(reverse('price'))
                self.assertContains(response, 'Узнать стоимость')
                self.assertNotContains(response, 'price-calculator-config')
                self.assertNotContains(response, 'price-engine.js')

    def test_marketing_description_is_current_heading_with_safe_line_breaks_and_blank_fallback(self):
        self.general.marketing_discount_description = '  <script>alert(1)</script>\nВторая строка  '
        self.general.save()
        response = self.client.get(reverse('price'))
        self.assertEqual(response.context['calculator_config']['marketing_discount_description'],
                         '<script>alert(1)</script>\nВторая строка')
        self.assertContains(response, '<h2 id="price-summary-title">&lt;script&gt;alert(1)&lt;/script&gt;<br>Вторая строка</h2>')
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertNotContains(response, 'Ваш расчёт')
        self.assertContains(response, '\\u003Cscript\\u003E')
        for value in ('', ' \n\t '):
            with self.subTest(value=value):
                self.general.marketing_discount_description = value
                self.general.save()
                response = self.client.get(reverse('price'))
                self.assertEqual(response.context['calculator_config']['marketing_discount_description'], '')
                self.assertContains(response, '<h2 id="price-summary-title" class="price-sr-only">Расчёт стоимости</h2>')

    def test_configuration_respects_visibility_modes_order_and_current_saved_values(self):
        self.settings.show_glass_type = False
        self.settings.save()
        self.glass.is_visible = False
        self.glass.save()
        self.settings.services.filter(code='railing').update(is_visible=False)
        self.settings.services.filter(code='sockets').update(position=0, name='Новая услуга')
        config = public_configuration(self.settings, self.general)
        self.assertFalse(config['glass_type']['visible'])
        self.assertEqual([item['id'] for item in config['glass_type']['options']], [self.glass.pk])
        self.assertNotIn(self.service_ids['railing'], [item['id'] for item in config['services']])
        self.assertEqual(config['services'][0]['name'], 'Новая услуга')
        self.settings.services.filter(code='sockets').update(price_per_unit='123.45')
        response = self.client.get(reverse('price'))
        service = next(item for item in response.context['calculator_config']['services'] if item['id'] == self.service_ids['sockets'])
        self.assertEqual(service['price'], '123.45')
        self.assertEqual(self.client.head(reverse('price')).status_code, 200)
        self.assertEqual(self.client.post(reverse('price'), {}).status_code, 405)

    @skipUnless(NODE, 'Для проверки браузерной арифметики нужен Node.js.')
    def test_browser_totals_match_decimal_server_for_promotions_services_stairs_and_boundaries(self):
        generator = random.Random(25)
        self.settings.services.filter(code='delivery').update(fixed_price=True)
        self.settings.services.filter(code='installation').update(has_price=False, is_visible=True)
        cases, expected = [], []
        for percent in ('0', '0.01', '3.33', '10', '100'):
            self.general.area_discount_percent = Decimal(percent)
            self.general.marketing_discount_percent = Decimal('12.34')
            self.general.save()
            config = public_configuration(self.settings, self.general)
            for index in range(32):
                panels = ((Panel(6000, 6000),) * MAX_PANELS if index == 31 else
                          (Panel(generator.randint(1, 6000), generator.randint(1, 1500)), Panel(1000, 1000)))
                services = (ServiceSelection(self.service_ids['backlight'], Decimal('1.55')),
                            ServiceSelection(self.service_ids['sockets'], 2),
                            ServiceSelection(self.service_ids['hydrophobic']),
                            ServiceSelection(self.service_ids['delivery'], 999))
                data = self.calculation_input(panels=panels, services=services, stair_floor=5, stair_panel_count=index % 4 + 1)
                server = calculate_price(data)
                expected.append((str(server.total), str(server.comparison_total)))
                cases.append({'config': config, 'input': {
                    'panels': [{'width': str(panel.width_mm), 'height': str(panel.height_mm)} for panel in panels],
                    'glass_type': self.glass.pk, 'decoration_type': self.decoration.pk,
                    'services': [{'id': item.service_id, 'quantity': str(item.quantity)} for item in services],
                    'stairs': {'floor': '5', 'count': str(index % 4 + 1)},
                }})
        actual = browser_results(cases)
        for index, (result, totals) in enumerate(zip(actual, expected)):
            with self.subTest(index=index):
                self.assertNotIn('error', result)
                self.assertEqual((result['total'], result['comparison']), totals)

    @skipUnless(NODE, 'Для проверки браузерной арифметики нужен Node.js.')
    def test_browser_and_server_discount_starts_only_above_two_square_metres(self):
        self.glass.price_per_sqm = Decimal('60')
        self.glass.save()
        self.decoration.price_per_sqm = Decimal('40')
        self.decoration.save()
        self.general.area_discount_percent = Decimal('10')
        self.general.save()
        config = public_configuration(self.settings, self.general)
        cases, expected = [], []
        for panels, subtotal in (
            ((Panel(1500, 1000),), '150'),
            ((Panel(1999, 1000), Panel(999, 1)), '200'),
            ((Panel(1000, 1000), Panel(1000, 1000)), '200'),
            ((Panel(2000, 1000), Panel(1, 1)), '200'),
            ((Panel(2005, 1000),), '190.81'),
            ((Panel(2500, 1000),), '230.5'),
        ):
            server = calculate_price(self.calculation_input(panels=panels))
            self.assertEqual(server.subtotal, Decimal(subtotal))
            expected.append(server)
            cases.append({'config': config, 'input': {
                'panels': [{'width': str(panel.width_mm), 'height': str(panel.height_mm)} for panel in panels],
                'glass_type': self.glass.pk, 'decoration_type': self.decoration.pk, 'services': [],
            }})
        for result, server in zip(browser_results(cases), expected):
            self.assertNotIn('error', result)
            self.assertEqual(Decimal(result['subtotal']), server.subtotal)
            self.assertEqual(Decimal(result['materials_discount']), server.materials_discount)
            self.assertEqual(Decimal(result['total']), server.total)
            self.assertEqual(Decimal(result['comparison']), server.comparison_total)

    @skipUnless(NODE, 'Для проверки браузерной арифметики нужен Node.js.')
    def test_browser_and_server_round_total_area_before_materials_and_area_services(self):
        service = self.settings.services.get(code='hydrophobic')
        config = public_configuration(self.settings, self.general)
        self.assertEqual(config['area_decimal_places'], 2)
        cases, expected = [], []
        for panels, area in (
            ((Panel(1111, 1111),), '1.23'),
            ((Panel(1004, 1000), Panel(999, 1)), '1.00'),
            ((Panel(1005, 1000),), '1.01'),
            ((Panel(1015, 1000),), '1.02'),
            ((Panel(1006, 500), Panel(1006, 500)), '1.01'),
            ((Panel(6, 1000), Panel(6, 1000)), '0.01'),
            ((Panel(1, 1),), '0.00'),
        ):
            server = calculate_price(self.calculation_input(
                panels=panels, services=(ServiceSelection(service.pk),),
            ))
            self.assertEqual(server.area_sqm, Decimal(area))
            expected.append(server)
            cases.append({'config': config, 'input': {
                'panels': [{'width': str(panel.width_mm), 'height': str(panel.height_mm)} for panel in panels],
                'glass_type': self.glass.pk, 'decoration_type': self.decoration.pk,
                'services': [{'id': service.pk, 'quantity': '1'}],
            }})
        for result, server in zip(browser_results(cases), expected):
            self.assertNotIn('error', result)
            self.assertEqual(Decimal(result['area']), server.area_sqm)
            self.assertEqual(Decimal(result['subtotal']), server.subtotal)
            self.assertEqual(Decimal(result['total']), server.total)
            for line in (line for line in server.lines if not line.included):
                browser_line = next(item for item in result['lines'] if item['label'] == line.label)
                self.assertEqual(Decimal(browser_line['amount']), line.amount)

    def test_whole_service_maximum_is_sent_without_decimal_zeros_for_input_clamping(self):
        service = self.settings.services.get(code='delivery')
        service.whole_quantity = True
        for limit in ('1', '100', '999999999'):
            with self.subTest(limit=limit):
                service.max_quantity = Decimal(limit)
                service.save()
                response = self.client.get(reverse('price'))
                item = next(item for item in response.context['calculator_config']['services']
                            if item['id'] == service.pk)
                self.assertEqual(item['max_quantity'], limit)
                self.assertEqual(item['initial_quantity'], '1')
                self.assertContains(response, f'max="{limit}"')
                self.assertNotContains(response, f'max="{limit}.000"')
        service.whole_quantity = False
        service.max_quantity = Decimal('100.5')
        service.save()
        response = self.client.get(reverse('price'))
        item = next(item for item in response.context['calculator_config']['services']
                    if item['id'] == service.pk)
        self.assertEqual(item['max_quantity'], '100.50')
        self.assertEqual(item['initial_quantity'], '1.00')
        self.assertEqual(response.context['calculator_config']['quantity_step'], '0.01')
        self.assertEqual(response.context['calculator_config']['quantity_decimal_places'], 2)
        self.assertContains(response, 'max="100.50"')

    @skipUnless(NODE, 'Для проверки браузерной арифметики нужен Node.js.')
    def test_custom_service_limits_match_server_and_ignore_nonmanual_modes(self):
        panels = (Panel(1000, 600), Panel(500, 400))
        cases, expected = [], []
        def add_case(config, service, quantity, valid):
            cases.append({'config': config, 'input': {
                'panels': [{'width': str(panel.width_mm), 'height': str(panel.height_mm)} for panel in panels],
                'glass_type': self.glass.pk, 'decoration_type': self.decoration.pk,
                'services': [{'id': service.pk, 'quantity': quantity}],
            }})
            expected.append(calculate_price(self.calculation_input(
                panels=panels, services=(ServiceSelection(service.pk, Decimal(quantity)),),
            )) if valid else None)

        for code, limit, invalid in (('backlight', '2.5', '2.51'), ('sockets', '3', '4'),
                                      ('backlight', '0.5', '0.51')):
            service = self.settings.services.get(code=code)
            service.max_quantity = Decimal(limit)
            service.save()
            config = public_configuration(self.settings, self.general)
            item = next(item for item in config['services'] if item['id'] == service.pk)
            self.assertEqual(Decimal(item['max_quantity']), Decimal(limit))
            self.assertLessEqual(Decimal(item['initial_quantity']), Decimal(limit))
            add_case(config, service, limit, True)
            add_case(config, service, invalid, False)

        page = self.client.get(reverse('price'))
        self.assertContains(page, 'max="0.50"')
        self.assertContains(page, 'value="0.50"')
        service = self.settings.services.get(code='backlight')
        for changes in ({'has_price': False}, {'fixed_price': True}, {'use_panel_area': True}):
            for name, value in {'has_price': True, 'fixed_price': False, 'use_panel_area': False, **changes}.items():
                setattr(service, name, value)
            service.save()
            config = public_configuration(self.settings, self.general)
            item = next(item for item in config['services'] if item['id'] == service.pk)
            self.assertIsNone(item['max_quantity'])
            add_case(config, service, '99', True)
        for result, server in zip(browser_results(cases), expected):
            if server is None:
                self.assertIn('error', result)
            else:
                self.assertNotIn('error', result)
                self.assertEqual(Decimal(result['subtotal']), server.subtotal)
                self.assertEqual(Decimal(result['total']), server.total)

    @skipUnless(NODE, 'Для проверки браузерной арифметики нужен Node.js.')
    def test_stair_floor_limits_are_two_to_twelve_in_configuration_and_browser(self):
        config = public_configuration(self.settings, self.general)
        self.assertEqual(config['max_stair_floor'], 12)
        self.assertEqual(config['min_stair_floor'], 2)
        data = {
            'panels': [{'width': '1000', 'height': '600'}, {'width': '500', 'height': '400'}],
            'glass_type': self.glass.pk, 'decoration_type': self.decoration.pk,
        }
        minimum, result, below, invalid = browser_results([
            {'config': config, 'input': {**data, 'stairs': {'floor': str(floor), 'count': '1'}}}
            for floor in (2, 12, 1, 13)
        ])
        self.assertNotIn('error', minimum)
        self.assertIn('error', below)
        expected = calculate_price(self.calculation_input(stair_floor=12, stair_panel_count=1))
        self.assertEqual(Decimal(result['total']), expected.total)
        self.assertIn('error', invalid)

    @skipUnless(NODE, 'Для проверки браузерной арифметики нужен Node.js.')
    def test_browser_exact_integer_rounding_free_services_and_invalid_input(self):
        self.glass.price_per_sqm = Decimal('60')
        self.glass.save()
        self.decoration.price_per_sqm = Decimal('40')
        self.decoration.save()
        self.general.area_discount_percent = Decimal('10')
        self.general.marketing_discount_percent = Decimal('20')
        self.general.save()
        config = public_configuration(self.settings, self.general)
        base = {'panels': [{'width': '3000', 'height': '1000'}], 'glass_type': self.glass.pk,
                'decoration_type': self.decoration.pk, 'services': []}
        invalid = [
            {'panels': []}, {'panels': [{'width': '0', 'height': '1'}]},
            {'panels': [{'width': '1000', 'height': '1000'}] * 11},
            {'panels': [{'width': '1.5', 'height': '1'}]}, {'glass_type': '999999'},
            {'panels': [{'width': '6001', 'height': '1'}]},
            {'panels': [{'width': '1', 'height': '6001'}]},
            {'services': [{'id': self.service_ids['sockets'], 'quantity': '1.5'}]},
            {'services': [{'id': self.service_ids['backlight'], 'quantity': '0'}]},
            {'services': [{'id': self.service_ids['backlight'], 'quantity': '1.005'}]},
            {'stairs': {'floor': '1', 'count': '6'}},
        ]
        results = browser_results([{'config': config, 'input': base}]
                                  + [{'config': config, 'input': {**base, **change}} for change in invalid])
        self.assertEqual((results[0]['total'], results[0]['comparison']), ('271', '339'))
        self.assertTrue(all('error' in item for item in results[1:]))
