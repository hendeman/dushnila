import smtplib
import ssl
import time
import uuid
from datetime import timedelta
from unittest.mock import Mock, patch

import certifi
from cryptography.fernet import Fernet
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import signing
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from pict.forms import CONTACT_FORM_TOKEN_SALT
from pict.models import ContactRequest, ContactRequestDelivery
from pict.services.email_delivery import create_backend
from pict.services.contact_delivery import (
    claim_delivery, enqueue_connection_test, enqueue_contact_request,
    mark_delivery_sent, process_pending_deliveries, recover_stale_deliveries,
    retry_failed_deliveries,
)
from .forms import LeadConnectionForm
from .models import LeadConnection
from .secrets import decrypt_secret, encrypt_secret


TEST_ENCRYPTION_KEY = Fernet.generate_key().decode('ascii')


@override_settings(LEAD_DELIVERY_ENCRYPTION_KEYS=(TEST_ENCRYPTION_KEY,), TELEGRAM_CHAT_ID='123456')
class LeadProcessingTests(TestCase):
    def setUp(self):
        LeadConnection.objects.update(is_enabled=False)

    def telegram(self, **kwargs):
        values = dict(
            name='Менеджеры', provider='telegram', is_enabled=True, recipients=['123456', '-987654'],
            telegram_token_encrypted=encrypt_secret('123:secret-token'),
        )
        values.update(kwargs)
        return LeadConnection.objects.create(**values)

    def email(self, **kwargs):
        values = dict(
            name='Почта', provider='email', is_enabled=True,
            recipients=['first@example.com', 'second@example.com'], smtp_host='smtp.example.com',
            smtp_username='sender@example.com', smtp_password_encrypted=encrypt_secret('smtp-secret'),
            from_email='sender@example.com', from_name='Заявки сайта',
        )
        values.update(kwargs)
        return LeadConnection.objects.create(**values)

    def request(self, **kwargs):
        values = dict(request_type='question', name='Иван', phone='+375 29 111-22-33', question='Когда <замер> & расчёт?')
        values.update(kwargs)
        return ContactRequest.objects.create(**values)

    def form_data(self, **kwargs):
        values = dict(
            name='Новый сервис', provider='telegram', is_enabled='on', all_request_types='on',
            recipients='123456\n123456\n-987654', telegram_token='123:private-token',
            smtp_port='587', smtp_security='starttls', connect_timeout='3', read_timeout='5',
        )
        values.update(kwargs)
        return values

    def test_secret_fields_are_encrypted_and_blank_input_retains_them(self):
        form = LeadConnectionForm(data=self.form_data())
        self.assertTrue(form.is_valid(), form.errors)
        connection = form.save()
        self.assertEqual(connection.request_types, list(ContactRequest.RequestType.values))
        self.assertNotIn('private-token', connection.telegram_token_encrypted)
        self.assertEqual(decrypt_secret(connection.telegram_token_encrypted), '123:private-token')
        self.assertEqual(connection.recipients, ['123456', '-987654'])
        original = connection.telegram_token_encrypted
        edit = LeadConnectionForm(instance=connection, data=self.form_data(telegram_token=''))
        self.assertTrue(edit.is_valid(), edit.errors)
        self.assertEqual(edit.save().telegram_token_encrypted, original)

    def test_selected_forms_limit_delivery_and_empty_selection_is_rejected(self):
        data = self.form_data()
        data.pop('all_request_types')
        data['request_types'] = ['question', 'quiz']
        form = LeadConnectionForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        connection = form.save()
        self.assertFalse(connection.all_request_types)
        self.assertEqual(connection.request_types, ['question', 'quiz'])
        self.assertTrue(connection.accepts('question'))
        self.assertTrue(connection.accepts('quiz'))
        self.assertFalse(connection.accepts('callback'))

        data.pop('request_types')
        empty = LeadConnectionForm(data=data)
        self.assertFalse(empty.is_valid())
        self.assertIn('request_types', empty.errors)

    @override_settings(LEAD_DELIVERY_ENCRYPTION_KEYS=())
    def test_missing_encryption_key_rejects_new_secret_without_echoing_it(self):
        form = LeadConnectionForm(data=self.form_data())
        self.assertFalse(form.is_valid())
        self.assertIn('ключ шифрования', str(form.errors))
        self.assertNotIn('private-token', str(form))

    def test_previous_encryption_key_can_decrypt_after_rotation(self):
        value = encrypt_secret('rotation-secret')
        with override_settings(LEAD_DELIVERY_ENCRYPTION_KEYS=(Fernet.generate_key().decode('ascii'), TEST_ENCRYPTION_KEY)):
            self.assertEqual(decrypt_secret(value), 'rotation-secret')

    def test_provider_and_recipient_validation(self):
        connection = self.telegram()
        connection.provider = 'email'
        with self.assertRaises(ValidationError):
            connection.save()
        with self.assertRaises(ValidationError):
            self.telegram(recipients=['https://example.com'])
        with self.assertRaises(ValidationError):
            self.email(recipients=['wrong'])
        with self.assertRaises(ValidationError):
            self.email(from_name='Sender\r\nBcc: injected@example.com')

    def test_telegram_addresses_are_normalized_before_deduplication(self):
        connection = self.telegram(recipients=['@SalesTeam', '@salesteam', '000123', '123'])
        self.assertEqual(connection.recipients, ['@salesteam', '123'])
        with self.assertRaises(ValidationError):
            self.telegram(recipients=['1' * 5000])

    @patch('pict.services.telegram_delivery.send', return_value='500')
    def test_legacy_queue_survives_switch_from_environment_to_admin(self, send):
        connection = LeadConnection.objects.get(use_environment=True)
        request = self.request()
        ContactRequestDelivery.objects.create(contact_request=request, connection=connection, channel='telegram')
        connection.use_environment = False
        connection.is_enabled = True
        connection.telegram_token_encrypted = encrypt_secret('123:new-token')
        connection.recipients = ['987654']
        connection.save()
        self.assertEqual(enqueue_contact_request(request), 0)
        self.assertEqual(process_pending_deliveries()['sent'], 1)
        self.assertEqual(send.call_args.args[0].recipient, '123456')

    @override_settings(TELEGRAM_CHAT_ID='', TELEGRAM_BOT_TOKEN='123:env-token', TELEGRAM_PROXY_URL='')
    @patch('pict.services.telegram_delivery.send', return_value='500')
    def test_missing_legacy_target_does_not_block_saved_targets(self, send):
        connection = LeadConnection.objects.get(use_environment=True)
        connection.is_enabled = True
        connection.save()
        old_request = self.request()
        ContactRequestDelivery.objects.create(contact_request=old_request, connection=connection, channel='telegram')
        known = ContactRequestDelivery.objects.create(contact_request=self.request(), connection=connection, channel='telegram', recipient='7654321')
        stats = process_pending_deliveries(limit=1)
        self.assertEqual(stats['sent'], 1)
        self.assertEqual(stats['configuration_errors'], 1)
        self.assertEqual(old_request.deliveries.get().attempts, 0)
        known.refresh_from_db()
        self.assertEqual(known.status, 'sent')

    @override_settings(TELEGRAM_CHAT_ID='')
    @patch('pict.services.telegram_delivery.send', return_value='500')
    def test_single_explicit_recipient_can_resolve_old_queue(self, send):
        connection = self.telegram(recipients=['7654321'])
        ContactRequestDelivery.objects.create(contact_request=self.request(), connection=connection, channel='telegram')
        self.assertEqual(process_pending_deliveries()['sent'], 1)
        self.assertEqual(send.call_args.args[0].recipient, '7654321')

    def test_routing_and_repeated_enqueue_are_per_recipient(self):
        telegram = self.telegram(all_request_types=False, request_types=['quiz'])
        email = self.email()
        request = self.request()
        self.assertEqual(enqueue_contact_request(request), 2)
        self.assertEqual(enqueue_contact_request(request), 0)
        self.assertEqual(set(request.deliveries.values_list('connection_id', flat=True)), {email.pk})
        quiz_request = self.request(request_type='quiz')
        self.assertEqual(enqueue_contact_request(quiz_request), 4)
        self.assertEqual(quiz_request.deliveries.filter(connection=telegram).count(), 2)

    def test_changing_recipients_preserves_queued_destination(self):
        connection = self.telegram(recipients=['123456'])
        request = self.request()
        enqueue_contact_request(request)
        connection.recipients = ['654321']
        connection.save()
        self.assertEqual(request.deliveries.get().recipient, '123456')
        new_request = self.request()
        enqueue_contact_request(new_request)
        self.assertEqual(new_request.deliveries.get().recipient, '654321')

    @patch('pict.services.telegram_delivery.send', return_value='500')
    def test_disabled_connection_pauses_queue_and_resumes_without_backfill(self, send):
        connection = self.telegram(recipients=['123456'])
        first = self.request()
        enqueue_contact_request(first)
        connection.is_enabled = False
        connection.save()
        second = self.request()
        self.assertEqual(enqueue_contact_request(second), 0)
        self.assertEqual(process_pending_deliveries()['claimed'], 0)
        send.assert_not_called()
        connection.is_enabled = True
        connection.save()
        self.assertEqual(process_pending_deliveries()['sent'], 1)
        self.assertFalse(second.deliveries.exists())

    @patch('pict.services.telegram_delivery.send', return_value='500')
    def test_invalid_connection_does_not_consume_batch_or_block_other_connection(self, send):
        invalid = self.telegram(name='Неверный', recipients=['111111'])
        good = self.telegram(name='Рабочий', recipients=['222222'])
        enqueue_contact_request(self.request())
        LeadConnection.objects.filter(pk=invalid.pk).update(telegram_token_encrypted='broken-ciphertext')
        stats = process_pending_deliveries(limit=1)
        self.assertEqual(stats['configuration_errors'], 1)
        self.assertEqual(stats['sent'], 1)
        self.assertEqual(invalid.deliveries.get().attempts, 0)
        self.assertEqual(good.deliveries.get().status, 'sent')

    @patch('pict.services.email_delivery.EmailBackend')
    def test_email_tracks_partial_failure_and_retries_only_failed_recipient(self, backend_class):
        connection = self.email()
        request = self.request(email='client@example.com')
        enqueue_contact_request(request)
        backend = backend_class.return_value.__enter__.return_value
        backend.send_messages.side_effect = [1, smtplib.SMTPRecipientsRefused({'second@example.com': (450, b'temporary')})]
        stats = process_pending_deliveries()
        self.assertEqual((stats['sent'], stats['retry']), (1, 1))
        first_message = backend.send_messages.call_args_list[0].args[0][0]
        self.assertEqual(first_message.to, ['first@example.com'])
        self.assertEqual(first_message.reply_to, ['client@example.com'])
        self.assertIn('sender@example.com', first_message.from_email)
        self.assertIn('Когда <замер> & расчёт?', first_message.body)
        self.assertIn('&lt;замер&gt; &amp;', first_message.alternatives[0].content)
        self.assertTrue(backend_class.call_args.kwargs['use_tls'])
        retry_message = backend.send_messages.call_args_list[1].args[0][0]
        self.assertEqual(retry_failed_deliveries(connection.deliveries.all()), 1)
        backend.send_messages.side_effect = None
        backend.send_messages.return_value = 1
        process_pending_deliveries()
        last_message = backend.send_messages.call_args.args[0][0]
        self.assertEqual(last_message.to, ['second@example.com'])
        self.assertEqual(last_message.extra_headers['Message-ID'], retry_message.extra_headers['Message-ID'])
        self.assertEqual(backend.send_messages.call_count, 3)

    def test_email_tls_trusts_system_and_certifi_roots_with_hostname_check(self):
        backend = create_backend({
            'host': 'smtp.example.com', 'port': 465, 'use_ssl': True, 'use_tls': False,
        })
        context = backend.ssl_context
        configured_roots = set(context.get_ca_certs(binary_form=True))
        system_roots = set(ssl.create_default_context().get_ca_certs(binary_form=True))
        certifi_roots = set(ssl.create_default_context(cafile=certifi.where()).get_ca_certs(binary_form=True))
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertTrue(system_roots.issubset(configured_roots))
        self.assertTrue(certifi_roots.issubset(configured_roots))

    @patch('pict.services.telegram_delivery.send', return_value='501')
    def test_test_message_uses_same_queue_even_when_disabled(self, send):
        connection = self.telegram(is_enabled=False)
        self.assertEqual(enqueue_connection_test(connection), 2)
        self.assertEqual(ContactRequest.objects.count(), 0)
        self.assertEqual(process_pending_deliveries()['sent'], 2)
        self.assertTrue(all(call.args[0].contact_request is None for call in send.call_args_list))
        self.assertEqual(connection.deliveries.values('test_batch_id').distinct().count(), 1)

    def test_lease_prevents_double_claim_and_late_result_overwrite(self):
        self.telegram(recipients=['123456'])
        request = self.request()
        enqueue_contact_request(request)
        delivery = claim_delivery(request.deliveries.get().pk, max_attempts=5)
        self.assertIsNone(claim_delivery(delivery.pk, max_attempts=5))
        ContactRequestDelivery.objects.filter(pk=delivery.pk).update(processing_started_at=timezone.now() - timedelta(minutes=11))
        recover_stale_deliveries(stale_after_seconds=600, max_attempts=5)
        current = claim_delivery(delivery.pk, max_attempts=5)
        self.assertEqual(mark_delivery_sent(delivery, 'old'), 0)
        self.assertEqual(mark_delivery_sent(current, 'new'), 1)
        self.assertEqual(request.deliveries.get().external_message_id, 'new')

    def test_connection_with_delivery_cannot_be_deleted(self):
        connection = self.telegram()
        enqueue_contact_request(self.request())
        with self.assertRaises(ProtectedError):
            connection.delete()

    def callback_data(self):
        return {
            'form_kind': 'callback', 'callback-name': 'Иван', 'callback-phone': '+375291112233',
            'callback-website': '', 'callback-form_token': signing.dumps(
                {'issued_at': time.time() - 6}, salt=CONTACT_FORM_TOKEN_SALT, compress=True,
            ),
        }

    def test_public_form_saves_request_without_active_connections(self):
        response = self.client.post(reverse('contact_submit'), self.callback_data(), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ContactRequest.objects.count(), 1)
        self.assertEqual(ContactRequestDelivery.objects.count(), 0)

    @patch('pict.services.contact_delivery.ContactRequestDelivery.objects.get_or_create', side_effect=RuntimeError('queue failure'))
    def test_public_form_rolls_back_request_when_queue_write_fails(self, enqueue):
        self.telegram()
        with self.assertRaises(RuntimeError):
            self.client.post(reverse('contact_submit'), self.callback_data())
        self.assertFalse(ContactRequest.objects.exists())


@override_settings(LEAD_DELIVERY_ENCRYPTION_KEYS=(TEST_ENCRYPTION_KEY,))
class LeadConnectionAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_superuser('delivery-owner', 'owner@example.com', 'password')
        cls.staff = get_user_model().objects.create_user('delivery-staff', password='password', is_staff=True)
        cls.staff.user_permissions.set(Permission.objects.filter(content_type__app_label='sitecontent'))

    def test_admin_supports_both_providers_and_hides_stored_secrets(self):
        self.client.force_login(self.owner)
        add_url = reverse('admin:sitecontent_leadconnection_add')
        response = self.client.post(add_url, {
            'name': 'Рабочая почта', 'provider': 'email', 'is_enabled': 'on', 'all_request_types': 'on',
            'recipients': 'manager@example.com', 'smtp_host': 'smtp.example.com', 'smtp_port': '587',
            'smtp_security': 'starttls', 'smtp_username': 'sender@example.com', 'smtp_password': 'hidden-password',
            'from_email': 'sender@example.com', 'connect_timeout': '3', 'read_timeout': '5', '_save': '1',
        })
        self.assertEqual(response.status_code, 302)
        connection = LeadConnection.objects.get(provider='email')
        editor = self.client.get(reverse('admin:sitecontent_leadconnection_change', args=[connection.pk]))
        self.assertEqual(editor.status_code, 200)
        self.assertNotContains(editor, 'hidden-password')
        self.assertNotContains(editor, 'name="telegram_token"')
        self.assertContains(editor, 'Сохранить и отправить тест')
        self.assertContains(self.client.get(reverse('admin:app_list', args=['sitecontent'])), 'Обработка заявок')
        self.assertEqual(self.client.get(reverse('admin:sitecontent_leadconnection_changelist')).status_code, 200)
        legacy = LeadConnection.objects.get(use_environment=True)
        self.assertEqual(self.client.get(reverse('admin:sitecontent_leadconnection_change', args=[legacy.pk])).status_code, 200)

    def test_admin_shows_every_request_form_with_all_checked_by_default(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('admin:sitecontent_leadconnection_add'))
        self.assertEqual(response.status_code, 200)
        form = response.context['adminform'].form
        self.assertTrue(form['all_request_types'].value())
        self.assertEqual(set(form['request_types'].value()), set(ContactRequest.RequestType.values))
        self.assertEqual(
            {value for value, _ in form.fields['request_types'].choices},
            set(ContactRequest.RequestType.values),
        )
        self.assertContains(response, 'Сообщение по email (форма снята с сайта)')
        legacy = LeadConnection.objects.get(use_environment=True)
        legacy_response = self.client.get(reverse('admin:sitecontent_leadconnection_change', args=[legacy.pk]))
        self.assertEqual(
            set(legacy_response.context['adminform'].form['request_types'].value()),
            set(ContactRequest.RequestType.values),
        )

    def test_failed_tests_do_not_count_as_request_delivery_errors(self):
        self.client.force_login(self.owner)
        connection = LeadConnection.objects.get(use_environment=True)
        ContactRequestDelivery.objects.create(
            connection=connection, channel='telegram', recipient='123456',
            test_batch_id=uuid.uuid4(), status='failed', last_error='Ошибка теста',
        )
        model_admin = admin.site._registry[LeadConnection]
        changelist_url = reverse('admin:sitecontent_leadconnection_changelist')
        change_url = reverse('admin:sitecontent_leadconnection_change', args=[connection.pk])
        response = self.client.get(changelist_url)
        item = next(item for item in response.context['cl'].result_list if item.pk == connection.pk)
        self.assertEqual(model_admin.failed_count(item), 0)
        self.assertNotEqual(model_admin.connection_status(item), 'Есть ошибки отправки')
        editor = self.client.get(change_url)
        self.assertContains(editor, 'Ошибок: 0')
        self.assertContains(editor, 'Ошибка теста')

        request = ContactRequest.objects.create(request_type='question', name='Иван', phone='+375 29 111-22-33')
        ContactRequestDelivery.objects.create(
            connection=connection, channel='telegram', recipient='123456',
            contact_request=request, status='failed', last_error='Ошибка заявки',
        )
        response = self.client.get(changelist_url)
        item = next(item for item in response.context['cl'].result_list if item.pk == connection.pk)
        self.assertEqual(model_admin.failed_count(item), 1)
        self.assertEqual(model_admin.connection_status(item), 'Есть ошибки отправки')
        self.assertContains(self.client.get(change_url), 'Ошибок: 1')

    def test_staff_cannot_read_change_or_test_connections_even_with_permissions(self):
        self.client.force_login(self.staff)
        connection = LeadConnection.objects.get(use_environment=True)
        url = reverse('admin:sitecontent_leadconnection_change', args=[connection.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {'_test_connection': '1'}).status_code, 403)
        self.assertEqual(self.client.get(reverse('admin:sitecontent_leadconnection_add')).status_code, 403)
        self.assertFalse(ContactRequestDelivery.objects.exists())

    def test_test_button_is_csrf_protected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        connection = LeadConnection.objects.get(use_environment=True)
        self.assertEqual(client.post(reverse('admin:sitecontent_leadconnection_change', args=[connection.pk]), {'_test_connection': '1'}).status_code, 403)

    @patch('pict.services.telegram_delivery.requests.Session')
    def test_admin_test_button_only_enqueues_and_result_page_renders(self, session):
        self.client.force_login(self.owner)
        response = self.client.post(reverse('admin:sitecontent_leadconnection_add'), {
            'name': 'Тест Telegram', 'provider': 'telegram', 'all_request_types': 'on',
            'recipients': '123456', 'telegram_token': '123:admin-token', 'smtp_port': '587',
            'smtp_security': 'starttls', 'connect_timeout': '3', 'read_timeout': '5', '_test_connection': '1',
        })
        self.assertEqual(response.status_code, 302)
        session.assert_not_called()
        self.assertEqual(ContactRequestDelivery.objects.count(), 1)
        editor = self.client.get(response.url)
        self.assertContains(editor, 'Ожидает отправки')
        self.assertNotContains(editor, 'admin-token')
