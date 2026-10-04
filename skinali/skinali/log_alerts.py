"""Почтовые уведомления о production-ошибках без зависимости от базы заявок."""

import logging
import sys
import threading
from collections import deque
from datetime import datetime, timezone
from time import monotonic

import certifi
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.mail import EmailMessage
from django.core.mail.backends.smtp import EmailBackend
from django.core.validators import validate_email


def read_alert_configuration(environ):
    """Проверяет отдельные параметры SMTP-уведомлений из окружения."""
    required = (
        'LOG_ALERT_SMTP_HOST',
        'LOG_ALERT_SMTP_PORT',
        'LOG_ALERT_SMTP_USERNAME',
        'LOG_ALERT_SMTP_PASSWORD',
        'LOG_ALERT_SMTP_SECURITY',
        'LOG_ALERT_FROM_EMAIL',
        'LOG_ALERT_TO_EMAILS',
    )
    values = {name: environ.get(name, '').strip() for name in required}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ImproperlyConfigured(
            'Для LOG_ALERT_ENABLED=True заполните: ' + ', '.join(missing)
        )

    security = values['LOG_ALERT_SMTP_SECURITY'].lower()
    if security not in {'starttls', 'ssl'}:
        raise ImproperlyConfigured(
            'LOG_ALERT_SMTP_SECURITY должен быть starttls или ssl.'
        )

    def read_int(name, default, minimum, maximum):
        raw_value = environ.get(name, '').strip() or str(default)
        try:
            value = int(raw_value)
        except ValueError as error:
            raise ImproperlyConfigured(f'{name} должен быть целым числом.') from error
        if not minimum <= value <= maximum:
            raise ImproperlyConfigured(
                f'{name} должен быть от {minimum} до {maximum}.'
            )
        return value

    recipients = tuple(
        address.strip()
        for address in values['LOG_ALERT_TO_EMAILS'].split(',')
        if address.strip()
    )
    if not recipients:
        raise ImproperlyConfigured('LOG_ALERT_TO_EMAILS не содержит адресов.')
    for address in (values['LOG_ALERT_FROM_EMAIL'], *recipients):
        try:
            validate_email(address)
        except ValidationError as error:
            raise ImproperlyConfigured(
                'LOG_ALERT_FROM_EMAIL и LOG_ALERT_TO_EMAILS должны содержать email-адреса.'
            ) from error

    return {
        'host': values['LOG_ALERT_SMTP_HOST'],
        'port': read_int('LOG_ALERT_SMTP_PORT', 0, 1, 65535),
        'username': values['LOG_ALERT_SMTP_USERNAME'],
        'password': values['LOG_ALERT_SMTP_PASSWORD'],
        'security': security,
        'from_email': values['LOG_ALERT_FROM_EMAIL'],
        'to_emails': recipients,
        'timeout': read_int('LOG_ALERT_SMTP_TIMEOUT', 5, 1, 30),
        'cooldown_seconds': read_int('LOG_ALERT_COOLDOWN_SECONDS', 600, 1, 86400),
        'max_per_hour': read_int('LOG_ALERT_MAX_PER_HOUR', 20, 1, 1000),
    }


class AlertEmailHandler(logging.Handler):
    """Посылает краткие письма и ограничивает повторы в одном Python-процессе."""

    def __init__(
        self,
        *,
        host,
        port,
        username,
        password,
        security,
        from_email,
        to_emails,
        timeout,
        cooldown_seconds,
        max_per_hour,
    ):
        super().__init__(level=logging.ERROR)
        self.smtp_options = {
            'host': host,
            'port': port,
            'username': username,
            'password': password,
            'use_tls': security == 'starttls',
            'use_ssl': security == 'ssl',
            'timeout': timeout,
            'fail_silently': False,
        }
        self.from_email = from_email
        self.to_emails = tuple(to_emails)
        self.cooldown_seconds = cooldown_seconds
        self.max_per_hour = max_per_hour
        self._recent = {}
        self._attempts = deque()
        self._sending = threading.local()
        self._last_failure_notice = float('-inf')

    def emit(self, record):
        if getattr(self._sending, 'active', False):
            return

        now = monotonic()
        while self._attempts and now - self._attempts[0] >= 3600:
            self._attempts.popleft()
        expiry = max(self.cooldown_seconds * 2, 3600)
        self._recent = {
            key: state
            for key, state in self._recent.items()
            if now - state[0] < expiry
        }
        exception_type = record.exc_info[0].__name__ if record.exc_info else ''
        fingerprint = (
            record.name,
            record.pathname,
            record.lineno,
            str(record.msg),
            exception_type,
        )
        previous = self._recent.get(fingerprint)
        if previous and now - previous[0] < self.cooldown_seconds:
            self._recent[fingerprint] = (previous[0], previous[1] + 1)
            return
        if len(self._attempts) >= self.max_per_hour:
            return

        suppressed = previous[1] if previous else 0
        self._attempts.append(now)
        self._recent[fingerprint] = (now, 0)
        self._sending.active = True
        try:
            backend = EmailBackend(**self.smtp_options)
            backend.ssl_context.load_verify_locations(cafile=certifi.where())
            subject = f'[Odium] {record.levelname} {record.name}'
            # Аргументы записи могут содержать URL, контакты или данные запроса.
            message = str(record.msg)[:1000]
            body = '\n'.join((
                f'Время (UTC): {datetime.fromtimestamp(record.created, timezone.utc).isoformat()}',
                f'Уровень: {record.levelname}',
                f'Логгер: {record.name}',
                f'Процесс: {record.process}',
                f'Место: {record.pathname}:{record.lineno}',
                f'Тип исключения: {exception_type or "не указан"}',
                f'Сообщение: {message}',
                f'Повторов с прошлого письма: {suppressed}',
                '',
                'Подробности: журнал Passenger на сервере.',
            ))
            with backend:
                sent = EmailMessage(
                    subject=subject,
                    body=body,
                    from_email=self.from_email,
                    to=self.to_emails,
                    connection=backend,
                ).send()
            if sent != 1:
                raise RuntimeError('SMTP-сервер не подтвердил отправку уведомления.')
        except Exception as error:
            # Не вызываем logging: при сбое SMTP это привело бы к рекурсии.
            if now - self._last_failure_notice >= 60:
                try:
                    sys.stderr.write(
                        'Не удалось отправить почтовое уведомление об ошибке: '
                        f'{type(error).__name__}.\n'
                    )
                except OSError:
                    pass
                self._last_failure_notice = now
        finally:
            self._sending.active = False
