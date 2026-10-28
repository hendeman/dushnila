import json
from pathlib import Path
import shutil
import subprocess
import time
from html import escape
from unittest import skipUnless
from unittest.mock import patch
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.test import Client, TestCase
from django.urls import reverse

from pict.forms import CONTACT_FORM_TOKEN_SALT
from pict.models import ContactRequest, ContactRequestDelivery
from pict.services import email_delivery, telegram_delivery
from pict.services.delivery_messages import format_contact_request_message
from sitecontent.models import LeadConnection

from .models import CalculatorSettings
from .test_calculation import CalculationFixture


class CalculatorOrderTests(CalculationFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = get_user_model().objects.create_superuser('order-owner', password=None)

    def setUp(self):
        CalculatorSettings.objects.update(is_enabled=True)
        LeadConnection.objects.update(is_enabled=False)
        self.connection = LeadConnection.objects.create(
            name='Заявки калькулятора', provider=LeadConnection.Provider.EMAIL,
            is_enabled=True, recipients=['orders@example.com'],
            smtp_host='smtp.example.com', from_email='site@example.com',
        )
        response = self.client.post(reverse('price_share'), json.dumps({
            'panels': [{'width': '1111', 'height': '1111'}],
            'glass_type': self.glass.pk, 'decoration_type': self.decoration.pk,
            'services': [{'id': self.service_ids['backlight'], 'quantity': '1.50'}],
            'stairs': {'floor': '2', 'count': '1'},
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.calculation_url = response.json()['url']

    def order_data(self, **changes):
        data = {
            'form_kind': 'calculator_order', 'calculator_order-name': 'Анна',
            'calculator_order-phone': '+375 (29) 123-45-67',
            'calculator_order-calculation_url': self.calculation_url,
            'calculator_order-website': '',
            'calculator_order-form_token': signing.dumps(
                {'issued_at': time.time() - 6}, salt=CONTACT_FORM_TOKEN_SALT, compress=True,
            ),
        }
        data.update(changes)
        return data

    def submit(self, data=None, client=None, **kwargs):
        return (client or self.client).post(
            reverse('contact_submit'), self.order_data() if data is None else data,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest', **kwargs,
        )

    def test_page_reuses_contact_dialog_with_two_visible_fields_and_hidden_calculation(self):
        response = self.client.get(reverse('price'))
        form = response.context['calculator_order_form']
        self.assertEqual([field.name for field in form.visible_fields() if field.name != 'website'], ['name', 'phone'])
        self.assertEqual({field.name for field in form.hidden_fields()}, {'form_token', 'calculation_url'})
        self.assertContains(response, 'id="calculator-order-dialog"')
        self.assertContains(response, 'aria-controls="calculator-order-dialog"')
        self.assertContains(response, '<h2 id="calculator-order-title">Заказать скинали</h2>')
        self.assertContains(response, 'name="calculator_order-calculation_url"')
        self.assertContains(response, 'data-calculation-url')
        self.assertContains(response, 'data-order-status ', count=1)
        self.assertContains(response, 'data-order-retry ', count=1)
        self.assertContains(response, 'data-submit-blocked="true"', count=1)
        self.assertContains(response, 'Подготавливаем расчёт…')
        self.assertContains(response, 'Вы можете заполнить имя и телефон.')
        CalculatorSettings.objects.update(is_enabled=False)
        self.assertNotContains(self.client.get(reverse('price')), 'id="calculator-order-dialog"')

    def test_order_saves_verified_url_and_queues_only_matching_connections(self):
        explicit = LeadConnection.objects.create(
            name='Только калькулятор', provider='email', is_enabled=True, all_request_types=False,
            request_types=[ContactRequest.RequestType.CALCULATOR_ORDER], recipients=['calculator@example.com'],
            smtp_host='smtp.example.com', from_email='site@example.com',
        )
        LeadConnection.objects.create(
            name='Только звонки', provider='email', is_enabled=True, all_request_types=False,
            request_types=[ContactRequest.RequestType.CALLBACK], recipients=['callback@example.com'],
            smtp_host='smtp.example.com', from_email='site@example.com',
        )
        response = self.submit(self.order_data(total='1', price='0', calculation_url='https://example.net'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        order = ContactRequest.objects.get()
        self.assertEqual(order.request_type, ContactRequest.RequestType.CALCULATOR_ORDER)
        self.assertEqual(order.name, 'Анна')
        self.assertEqual(order.phone, '+375 (29) 123-45-67')
        self.assertEqual(order.calculation_url, self.calculation_url)
        self.assertEqual(set(order.deliveries.values_list('connection_id', flat=True)),
                         {self.connection.pk, explicit.pk})
        self.assertTrue(all(item.attempts == 0 for item in order.deliveries.all()))

    def test_bad_or_foreign_urls_and_missing_or_invalid_contacts_are_rejected(self):
        parsed = urlsplit(self.calculation_url)
        for changes in (
            {'calculator_order-name': '1'}, {'calculator_order-phone': '123'},
            {'calculator_order-calculation_url': ''},
            {'calculator_order-calculation_url': self.calculation_url + 'x'},
            {'calculator_order-calculation_url': self.calculation_url.replace(parsed.netloc, 'example.net')},
            {'calculator_order-calculation_url': parsed.path + '?' + parsed.query},
            {'calculator_order-calculation_url': self.calculation_url + '&total=1'},
            {'calculator_order-calculation_url': self.calculation_url + '&' + parsed.query},
            {'calculator_order-calculation_url': self.calculation_url + '#fragment'},
            {'calculator_order-calculation_url': 'javascript:alert(1)'},
            {'calculator_order-calculation_url': 'x' * 8193},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(self.submit(self.order_data(**changes)).status_code, 422)
                self.assertFalse(ContactRequest.objects.exists())
                self.assertFalse(ContactRequestDelivery.objects.exists())

    def test_disabled_calculator_and_changed_or_hidden_services_reject_old_links(self):
        service = self.settings.services.get(code='backlight')
        for changes in ({'max_quantity': '1.00'}, {'is_visible': False}):
            with self.subTest(changes=changes):
                self.settings.services.filter(pk=service.pk).update(**changes)
                response = self.submit()
                self.assertEqual(response.status_code, 422)
                self.assertIn('calculation_url', response.json()['errors'])
                self.assertFalse(ContactRequest.objects.exists())
                self.settings.services.filter(pk=service.pk).update(max_quantity=None, is_visible=True)
        CalculatorSettings.objects.update(is_enabled=False)
        self.assertEqual(self.submit().status_code, 422)
        self.assertFalse(ContactRequest.objects.exists())

    def test_standard_post_preserves_hidden_url_on_error_and_accepts_valid_order(self):
        response = self.client.post(reverse('contact_submit'), self.order_data(**{'calculator_order-name': ''}))
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, escape(self.calculation_url, quote=True), status_code=422)
        self.assertEqual(response.context['form_kind'], 'calculator_order')
        response = self.client.post(reverse('contact_submit'), self.order_data())
        self.assertContains(response, 'Заявка принята')
        self.assertEqual(ContactRequest.objects.get().calculation_url, self.calculation_url)

    def test_antispam_keeps_success_response_without_saving_or_queueing(self):
        for changes in (
            {'calculator_order-website': 'spam'}, {'calculator_order-form_token': 'invalid'},
            {'calculator_order-form_token': signing.dumps(
                {'issued_at': time.time() - 1}, salt=CONTACT_FORM_TOKEN_SALT,
            )},
        ):
            with self.subTest(changes=changes):
                response = self.submit(self.order_data(**changes))
                self.assertTrue(response.json()['ok'])
                self.assertFalse(ContactRequest.objects.exists())
                self.assertFalse(ContactRequestDelivery.objects.exists())

    def test_csrf_is_required_and_valid_csrf_uses_the_same_contact_handler(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.submit(client=client).status_code, 403)
        client.get(reverse('price'))
        token = client.cookies[settings.CSRF_COOKIE_NAME].value
        self.assertEqual(self.submit(client=client, HTTP_X_CSRFTOKEN=token).status_code, 200)
        self.assertEqual(ContactRequest.objects.count(), 1)

    def test_admin_displays_readonly_link_and_notifications_include_it(self):
        self.assertEqual(self.submit().status_code, 200)
        order = ContactRequest.objects.get()
        self.client.force_login(self.owner)
        url = reverse('admin:pict_contactrequest_change', args=[order.pk])
        response = self.client.get(url)
        self.assertContains(response, 'Заказ из калькулятора')
        self.assertContains(response, 'Открыть расчёт')
        self.assertContains(response, escape(order.calculation_url, quote=True))
        self.assertNotIn('calculation_url', response.context['adminform'].form.fields)
        data = {'name': 'Иван', 'phone': order.phone, 'calculation_url': 'https://example.net'}
        for inline in response.context['inline_admin_formsets']:
            for field in inline.formset.management_form:
                data[field.html_name] = field.value()
            for form in inline.formset.forms:
                for field in form.hidden_fields():
                    data[field.html_name] = field.value()
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.calculation_url, self.calculation_url)
        self.assertIn(self.calculation_url, format_contact_request_message(order))
        compact = format_contact_request_message(order, compact_links=True)
        self.assertIn(f'<a href="{escape(self.calculation_url)}">Открыть расчёт</a>', compact)

    def test_email_and_telegram_adapters_preserve_calculation_url_without_external_sends(self):
        self.submit()
        delivery = ContactRequestDelivery.objects.get(connection=self.connection)
        with patch('pict.services.email_delivery.create_backend') as create_backend:
            backend = create_backend.return_value.__enter__.return_value
            backend.send_messages.return_value = 1
            email_delivery.send(delivery, {})
            message = backend.send_messages.call_args.args[0][0]
            self.assertIn(self.calculation_url, message.body)
            self.assertIn(self.calculation_url, message.alternatives[0].content)
            self.assertIn('Заказ из калькулятора', message.subject)
        with patch('pict.services.telegram_delivery.requests.Session') as session_class:
            session = session_class.return_value
            session.post.return_value.json.return_value = {'ok': True, 'result': {'message_id': 1}}
            telegram_delivery.send(delivery, {'token': 'test-token', 'proxy_url': '', 'timeout': (1, 1)})
            text = session.post.call_args.kwargs['json']['text']
            self.assertIn(f'<a href="{escape(self.calculation_url)}">Открыть расчёт</a>', text)

    @skipUnless(shutil.which('node'), 'Для проверки клиентского сценария нужен Node.js.')
    def test_order_button_uses_current_quote_and_handles_async_failures(self):
        subprocess.run(
            [shutil.which('node'), str(Path(__file__).parent / 'tests_js' / 'order_form.cjs')],
            capture_output=True, text=True, encoding='utf-8', timeout=10, check=True,
        )
