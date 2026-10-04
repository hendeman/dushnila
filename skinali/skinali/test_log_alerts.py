import logging
from io import StringIO
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from .log_alerts import AlertEmailHandler, read_alert_configuration


VALID_ENVIRONMENT = {
    'LOG_ALERT_SMTP_HOST': 'smtp.example.com',
    'LOG_ALERT_SMTP_PORT': '587',
    'LOG_ALERT_SMTP_USERNAME': 'alerts@example.com',
    'LOG_ALERT_SMTP_PASSWORD': 'test-password',
    'LOG_ALERT_SMTP_SECURITY': 'starttls',
    'LOG_ALERT_FROM_EMAIL': 'alerts@example.com',
    'LOG_ALERT_TO_EMAILS': 'admin@example.com,second@example.com',
}


class AlertConfigurationTests(SimpleTestCase):
    def test_reads_separate_smtp_configuration(self):
        options = read_alert_configuration(VALID_ENVIRONMENT)

        self.assertEqual(options['host'], 'smtp.example.com')
        self.assertEqual(options['port'], 587)
        self.assertEqual(options['security'], 'starttls')
        self.assertEqual(options['to_emails'], ('admin@example.com', 'second@example.com'))
        self.assertEqual(options['timeout'], 5)
        self.assertEqual(options['cooldown_seconds'], 600)

    def test_rejects_missing_and_insecure_configuration(self):
        with self.assertRaisesMessage(ImproperlyConfigured, 'LOG_ALERT_SMTP_PASSWORD'):
            read_alert_configuration({**VALID_ENVIRONMENT, 'LOG_ALERT_SMTP_PASSWORD': ''})
        with self.assertRaisesMessage(ImproperlyConfigured, 'starttls или ssl'):
            read_alert_configuration({**VALID_ENVIRONMENT, 'LOG_ALERT_SMTP_SECURITY': 'none'})
        with self.assertRaisesMessage(ImproperlyConfigured, 'LOG_ALERT_TO_EMAILS'):
            read_alert_configuration({**VALID_ENVIRONMENT, 'LOG_ALERT_TO_EMAILS': 'bad-address'})


class AlertEmailHandlerTests(SimpleTestCase):
    def setUp(self):
        self.handler = AlertEmailHandler(**read_alert_configuration(VALID_ENVIRONMENT))
        self.logger = logging.Logger('tests.alerts', level=logging.DEBUG)
        self.logger.addHandler(self.handler)

    @patch('skinali.log_alerts.monotonic', side_effect=[100, 101, 701])
    @patch('skinali.log_alerts.EmailBackend')
    def test_error_and_critical_are_mailed_with_repeat_count(self, backend_class, _clock):
        backend = backend_class.return_value
        backend.send_messages.return_value = 1

        self.logger.warning('Предупреждение')
        for address in ('secret@example.com', 'other@example.com'):
            self.logger.error('Ошибка %s', address)
        self.logger.critical('Критический сбой')

        self.assertEqual(backend.send_messages.call_count, 2)
        first_message = backend.send_messages.call_args_list[0].args[0][0]
        second_message = backend.send_messages.call_args_list[1].args[0][0]
        self.assertEqual(first_message.to, ['admin@example.com', 'second@example.com'])
        self.assertIn('ERROR', first_message.subject)
        self.assertNotIn('secret@example.com', first_message.body)
        self.assertIn('CRITICAL', second_message.subject)
        self.assertTrue(backend.ssl_context.load_verify_locations.called)

    @patch('skinali.log_alerts.monotonic', side_effect=[100, 101, 701])
    @patch('skinali.log_alerts.EmailBackend')
    def test_repeat_is_reported_after_cooldown(self, backend_class, _clock):
        backend_class.return_value.send_messages.return_value = 1

        for _ in range(3):
            self.logger.error('Повторяющаяся ошибка')

        self.assertEqual(backend_class.return_value.send_messages.call_count, 2)
        message = backend_class.return_value.send_messages.call_args.args[0][0]
        self.assertIn('Повторов с прошлого письма: 1', message.body)

    @patch('skinali.log_alerts.monotonic', side_effect=[100, 101])
    @patch('skinali.log_alerts.EmailBackend')
    def test_smtp_failure_does_not_interrupt_logging(self, backend_class, _clock):
        backend_class.return_value.send_messages.side_effect = OSError('SMTP unavailable')

        with patch('skinali.log_alerts.sys.stderr', new_callable=StringIO) as stderr:
            for _ in range(2):
                self.logger.error('Ошибка сайта')

        self.assertEqual(backend_class.return_value.send_messages.call_count, 1)
        self.assertIn('OSError', stderr.getvalue())
        self.assertNotIn('SMTP unavailable', stderr.getvalue())

    @patch('skinali.log_alerts.monotonic', side_effect=[100, 101, 102])
    @patch('skinali.log_alerts.EmailBackend')
    def test_hourly_limit_bounds_unique_errors(self, backend_class, _clock):
        self.handler.max_per_hour = 2
        backend_class.return_value.send_messages.return_value = 1

        self.logger.error('Первая ошибка')
        self.logger.error('Вторая ошибка')
        self.logger.error('Третья ошибка')

        self.assertEqual(backend_class.return_value.send_messages.call_count, 2)
