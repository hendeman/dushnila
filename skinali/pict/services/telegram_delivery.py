import math
import re
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from sitecontent.secrets import decrypt_secret

from .delivery_errors import DeliveryConfigurationError, DeliveryError
from .delivery_messages import format_contact_request_message


def validate_proxy_url(value):
    if not value:
        return
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in {'http', 'https'} and parsed.hostname and parsed.port
            and parsed.path in {'', '/'} and not parsed.query and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid or any(char.isspace() for char in value):
        raise ValidationError('Прокси должен иметь формат http(s)://host:port без пути и параметров.')


def get_configuration(connection):
    if connection.use_environment:
        token = settings.TELEGRAM_BOT_TOKEN
        proxy = settings.TELEGRAM_PROXY_URL
        timeout = (settings.TELEGRAM_CONNECT_TIMEOUT, settings.TELEGRAM_READ_TIMEOUT)
    else:
        token = decrypt_secret(connection.telegram_token_encrypted)
        proxy = decrypt_secret(connection.proxy_url_encrypted)
        timeout = (connection.connect_timeout, connection.read_timeout)
    if not token or not re.fullmatch(r'[A-Za-z0-9:_-]+', token):
        raise DeliveryConfigurationError('Не задан корректный токен Telegram-бота.')
    if any(not math.isfinite(value) or not 0 < value <= 30 for value in timeout):
        raise DeliveryConfigurationError('Тайм-ауты Telegram должны быть больше нуля и не более 30 секунд.')
    validate_proxy_url(proxy)
    return {'token': token, 'proxy_url': proxy, 'timeout': timeout}


def send(delivery, configuration):
    text = (
        format_contact_request_message(delivery.contact_request)
        if delivery.contact_request_id else 'Проверка подключения: сайт успешно отправил тестовое сообщение.'
    )
    session = requests.Session()
    session.trust_env = False
    proxy = configuration['proxy_url']
    try:
        response = session.post(
            f"https://api.telegram.org/bot{configuration['token']}/sendMessage",
            json={'chat_id': delivery.recipient, 'text': text, 'parse_mode': 'HTML'},
            timeout=configuration['timeout'],
            proxies={'http': proxy, 'https': proxy} if proxy else None,
        )
    except requests.Timeout as error:
        raise DeliveryError('Telegram не ответил за отведённое время.', retryable=True) from error
    except requests.RequestException as error:
        raise DeliveryError('Сетевая ошибка при обращении к Telegram.', retryable=True) from error
    finally:
        session.close()
    try:
        payload = response.json()
    except ValueError as error:
        raise DeliveryError(
            f'Telegram вернул некорректный ответ (HTTP {response.status_code}).',
            retryable=response.status_code == 429 or response.status_code >= 500,
        ) from error
    if not isinstance(payload, dict) or payload.get('ok') is not True:
        code = payload.get('error_code') if isinstance(payload, dict) else None
        code = code if isinstance(code, int) and not isinstance(code, bool) else response.status_code
        parameters = payload.get('parameters', {}) if isinstance(payload, dict) else {}
        retry_after = parameters.get('retry_after') if isinstance(parameters, dict) else None
        try:
            retry_after = min(7 * 86400, max(1, int(retry_after))) if retry_after is not None else None
        except (ValueError, TypeError):
            retry_after = None
        # Ответ внешнего сервиса может повторять секреты или данные заявки.
        raise DeliveryError(
            f'Telegram отклонил запрос (код {code}).',
            retryable=code == 429 or code >= 500 or code < 400,
            retry_after=retry_after,
        )
    result = payload.get('result')
    message_id = result.get('message_id') if isinstance(result, dict) else None
    if not isinstance(message_id, int) or isinstance(message_id, bool):
        raise DeliveryError('Telegram подтвердил запрос без корректного ID сообщения.', retryable=True)
    return str(message_id)
