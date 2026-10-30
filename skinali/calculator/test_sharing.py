import copy
import json
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.core import signing
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .calculation import calculate_price
from .models import CalculatorSettings
from .sharing import MAX_SHARE_REQUEST_BYTES, MAX_SHARE_TOKEN_LENGTH, SHARE_SALT, read_calculation_share_token
from .test_calculation import CalculationFixture


class CalculationSharingTests(CalculationFixture, TestCase):
    def setUp(self):
        CalculatorSettings.objects.update(is_enabled=True)
        self.input = {
            'panels': [{'width': '1800', 'height': '600'}, {'width': '1200', 'height': '600'}],
            'glass_type': str(self.glass.pk), 'decoration_type': str(self.decoration.pk),
            'services': [{'id': self.service_ids['backlight'], 'quantity': '1.50'}],
            'stairs': {'floor': '12', 'count': '2'},
        }

    def create_link(self, data=None, client=None):
        return (client or self.client).post(
            reverse('price_share'), json.dumps(self.input if data is None else data), content_type='application/json',
        )

    def shared_path(self, response):
        self.assertEqual(response.status_code, 200, response.content)
        url = urlsplit(response.json()['url'])
        return url.path + '?' + url.query

    def token(self, response):
        return parse_qs(urlsplit(response.json()['url']).query)['calculation'][0]

    def test_link_restores_every_parameter_in_another_browser_without_database_writes(self):
        with CaptureQueriesContext(connection) as queries:
            created = self.create_link()
            received = Client().get(self.shared_path(created))
        self.assertEqual(received.status_code, 200)
        restored = received.context['calculation_initial_input']
        self.assertEqual(restored['panels'], [{'width': 1800, 'height': 600}, {'width': 1200, 'height': 600}])
        self.assertEqual(restored['glass_type'], self.glass.pk)
        self.assertEqual(restored['decoration_type'], self.decoration.pk)
        self.assertEqual(restored['services'], [{'id': self.service_ids['backlight'], 'quantity': '1.50'}])
        self.assertEqual(restored['stairs'], {'floor': 12, 'count': 2})
        self.assertContains(received, 'price-initial-input')
        self.assertContains(received, 'Стоимость пересчитана по действующим тарифам')
        self.assertEqual(received['Referrer-Policy'], 'no-referrer')
        self.assertIn('noindex', received['X-Robots-Tag'])
        self.assertIn('no-store', received['Cache-Control'])
        self.assertFalse(any(query['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for query in queries))

    def test_shared_parameters_use_current_prices_without_saving_a_total(self):
        created = self.create_link()
        data = read_calculation_share_token(self.token(created))
        before = calculate_price(data, settings=self.settings).total
        self.glass.price_per_sqm *= 2
        self.glass.save()
        after = calculate_price(data, settings=self.settings).total
        self.assertGreater(after, before)
        received = Client().get(self.shared_path(created))
        self.assertEqual(received.status_code, 200)
        self.assertEqual(received.context['calculator_config']['glass_type']['options'][0]['price'], str(self.glass.price_per_sqm))
        payload = signing.Signer(salt=SHARE_SALT).unsign_object(self.token(created))
        self.assertEqual(set(payload), {'v', 'input'})
        self.assertNotIn('total', payload['input'])

    def test_existing_link_uses_current_minimum_without_accepting_it_from_visitor(self):
        created = self.create_link()
        data = read_calculation_share_token(self.token(created))
        before = calculate_price(data)
        CalculatorSettings.objects.update(minimum_order_area_sqm=Decimal('2.50'))
        after = calculate_price(data)
        self.assertEqual(before.area_sqm, after.area_sqm)
        self.assertEqual(after.billable_area_sqm, Decimal('2.50'))
        self.assertGreater(after.total, before.total)
        received = self.client.get(self.shared_path(created))
        self.assertEqual(received.status_code, 200)
        self.assertEqual(received.context['calculator_config']['minimum_order_area_sqm'], '2.50')
        self.assertEqual(received.context['calculation_initial_input']['panels'], [
            {'width': 1800, 'height': 600}, {'width': 1200, 'height': 600},
        ])
        self.assertEqual(self.create_link({**self.input, 'minimum_order_area_sqm': '0'}).status_code, 400)

    def test_existing_link_uses_current_discount_mode_and_rules(self):
        self.input['panels'] = [{'width': '3500', 'height': '1000'}]
        created = self.create_link()
        data = read_calculation_share_token(self.token(created))
        baseline = calculate_price(data).subtotal
        self.set_material_discount('stepped', (('2', '10'), ('3', '20')))
        stepped = calculate_price(data).subtotal
        self.assertEqual(baseline - stepped, Decimal('3.5') * Decimal('120.75') * Decimal('.2'))
        response = Client().get(self.shared_path(created))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['calculator_config']['material_discount']['mode'], 'stepped')
        self.set_material_discount('progressive', (('2', '10'), ('3', '20')))
        progressive = calculate_price(data).subtotal
        self.assertEqual(baseline - progressive, Decimal('120.75') * Decimal('.4'))
        self.assertGreater(progressive, stepped)

    def test_signature_origin_and_key_fallbacks(self):
        with override_settings(PUBLIC_SITE_ORIGIN='https://example.org', SECRET_KEY='calculation-old-key'):
            created = self.create_link()
        self.assertTrue(created.json()['url'].startswith('https://example.org/price/?calculation='))
        with override_settings(SECRET_KEY='calculation-new-key', SECRET_KEY_FALLBACKS=['calculation-old-key']):
            self.assertEqual(Client().get(self.shared_path(created)).status_code, 200)

    def test_invalid_signatures_versions_and_payloads_are_rejected_without_restoring(self):
        created = self.create_link()
        malformed = ['', 'wrong', self.token(created) + 'x', 'x' * (MAX_SHARE_TOKEN_LENGTH + 1)]
        for payload in ({'v': 2, 'input': self.input}, {'v': True, 'input': self.input}, {'v': 1, 'input': []}):
            malformed.append(signing.Signer(salt=SHARE_SALT).sign_object(payload, compress=True))
        malformed.append(signing.Signer(salt='pict.shared_favorites.v1').sign_object({'v': 1, 'ids': [1]}))
        for token in malformed:
            with self.subTest(token=token[:25]):
                response = self.client.get(reverse('price'), {'calculation': token})
                self.assertEqual(response.status_code, 400)
                self.assertIsNone(response.context['calculation_initial_input'])
                self.assertContains(response, 'Ссылка на расчёт недействительна', status_code=400)

    def test_invalid_geometry_quantities_services_and_stairs_cannot_be_signed(self):
        cases = []
        for width in (True, 1.2, '0', '6001', '-1'):
            data = copy.deepcopy(self.input)
            data['panels'][0]['width'] = width
            cases.append(data)
        for quantity in ('0', '-1', '1.001', '1e2', True, 1.5):
            data = copy.deepcopy(self.input)
            data['services'][0]['quantity'] = quantity
            cases.append(data)
        for changes in (
            {'panels': []}, {'panels': self.input['panels'] * 6},
            {'services': self.input['services'] * 2},
            {'services': [{'id': 999999, 'quantity': '1'}]},
            {'stairs': {'floor': 1, 'count': 1}}, {'stairs': {'floor': 13, 'count': 1}},
            {'stairs': {'floor': 2, 'count': 7}}, {'total': 1}, {'glass_type': True},
        ):
            cases.append({**self.input, **changes})
        for data in cases:
            with self.subTest(data=data):
                self.assertEqual(self.create_link(data).status_code, 400)

    def test_unavailable_parameters_or_lower_quantity_limit_do_not_silently_change_a_shared_quote(self):
        created = self.create_link()
        service = self.settings.services.get(code='backlight')
        service.max_quantity = '1.00'
        service.save()
        response = self.client.get(self.shared_path(created))
        self.assertEqual(response.status_code, 409)
        self.assertIsNone(response.context['calculation_initial_input'])
        service.max_quantity = '100.00'
        service.is_visible = False
        service.save()
        self.assertEqual(self.client.get(self.shared_path(created)).status_code, 409)
        self.assertEqual(self.create_link().status_code, 400)

    def test_hidden_materials_save_the_current_default_and_maximum_geometry_can_be_shared(self):
        self.settings.show_glass_type = self.settings.show_decoration_type = False
        self.settings.save()
        data = {**self.input, 'glass_type': None, 'decoration_type': None,
                'panels': [{'width': 6000, 'height': 6000}] * 10}
        created = self.create_link(data)
        restored = read_calculation_share_token(self.token(created))
        self.assertEqual(restored.glass_type_id, self.glass.pk)
        self.assertEqual(len(restored.panels), 10)
        self.assertEqual(self.client.get(self.shared_path(created)).status_code, 200)

    def test_post_requires_csrf_and_limits_body_methods_and_disabled_calculator(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.create_link(client=client).status_code, 403)
        client.get(reverse('price'))
        csrf = client.cookies[settings.CSRF_COOKIE_NAME].value
        response = client.post(reverse('price_share'), json.dumps(self.input), content_type='application/json', HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(reverse('price_share')).status_code, 405)
        self.assertEqual(self.client.post(reverse('price_share'), '{}', content_type='text/plain').status_code, 415)
        self.assertEqual(self.client.post(reverse('price_share'), 'x' * (MAX_SHARE_REQUEST_BYTES + 1), content_type='application/json').status_code, 413)
        self.assertEqual(self.client.post(reverse('price_share'), 'invalid json', content_type='application/json').status_code, 400)
        CalculatorSettings.objects.update(is_enabled=False)
        self.assertEqual(self.create_link().status_code, 503)
