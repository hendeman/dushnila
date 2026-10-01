import smtplib
import ssl
from email.utils import formataddr
from html import unescape

import certifi
from django.core.mail import EmailMultiAlternatives
from django.core.mail.backends.smtp import EmailBackend
from django.utils.html import strip_tags
from sitecontent.models import LeadConnection
from sitecontent.secrets import decrypt_secret

from .delivery_errors import DeliveryConfigurationError, DeliveryError
from .delivery_messages import format_contact_request_message


def get_configuration(connection):
    if not connection.smtp_host or not connection.from_email:
        raise DeliveryConfigurationError('Заполните SMTP-сервер и адрес отправителя.')
    password = decrypt_secret(connection.smtp_password_encrypted)
    if connection.smtp_username and not password:
        raise DeliveryConfigurationError('Не задан пароль для SMTP-логина.')
    return {
        'host': connection.smtp_host,
        'port': connection.smtp_port,
        'username': connection.smtp_username,
        'password': password,
        'use_tls': connection.smtp_security == LeadConnection.EmailSecurity.STARTTLS,
        'use_ssl': connection.smtp_security == LeadConnection.EmailSecurity.SSL,
        'timeout': connection.read_timeout,
        'fail_silently': False,
    }


def create_backend(configuration):
    backend = EmailBackend(**configuration)
    backend.ssl_context.load_verify_locations(cafile=certifi.where())
    return backend


def send(delivery, configuration):
    connection = delivery.connection
    contact_request = delivery.contact_request
    if contact_request is None:
        subject = 'Проверка подключения сайта'
        html = 'Сайт успешно отправил тестовое сообщение.'
    else:
        subject = f'Новая заявка №{contact_request.pk} — {contact_request.get_request_type_display()}'
        html = format_contact_request_message(contact_request)
    message_id = f'<{delivery.message_key}@{connection.from_email.rsplit("@", 1)[1]}>'
    message = EmailMultiAlternatives(
        subject=subject,
        body=unescape(strip_tags(html)),
        from_email=formataddr((connection.from_name, connection.from_email)),
        to=[delivery.recipient],
        reply_to=[contact_request.email] if contact_request and contact_request.email else [],
        headers={'Message-ID': message_id},
    )
    message.attach_alternative(html.replace('\n', '<br>\n'), 'text/html')
    try:
        # По одному получателю на письмо: повтор ошибки не затрагивает успешные отправки.
        with create_backend(configuration) as backend:
            sent = backend.send_messages([message])
        if sent != 1:
            raise DeliveryError('SMTP-сервер не подтвердил приём письма.', retryable=True)
    except smtplib.SMTPRecipientsRefused as error:
        codes = [value[0] for value in error.recipients.values()]
        raise DeliveryError('SMTP-сервер отклонил получателя.', retryable=any(400 <= code < 500 for code in codes)) from error
    except smtplib.SMTPResponseException as error:
        raise DeliveryError(f'SMTP-сервер отклонил отправку (код {error.smtp_code}).', retryable=400 <= error.smtp_code < 500) from error
    except (ssl.SSLError, smtplib.SMTPNotSupportedError) as error:
        raise DeliveryError('Не удалось установить защищённое SMTP-соединение. Проверьте сервер, порт и способ защиты.', retryable=False) from error
    except (OSError, smtplib.SMTPException) as error:
        raise DeliveryError('Сетевая ошибка SMTP-соединения.', retryable=True) from error
    return message_id
