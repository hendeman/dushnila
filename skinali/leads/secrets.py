from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ValidationError


def get_secret_cipher():
    """Первый ключ шифрует новые значения, остальные позволяют читать старые."""
    keys = settings.LEAD_DELIVERY_ENCRYPTION_KEYS
    if not keys:
        raise ValidationError('На сервере не настроен ключ шифрования подключений.')
    try:
        return MultiFernet([Fernet(key.encode('ascii')) for key in keys])
    except (ValueError, UnicodeError) as error:
        raise ValidationError('Ключ шифрования подключений имеет неверный формат.') from error


def encrypt_secret(value):
    return get_secret_cipher().encrypt(value.encode('utf-8')).decode('ascii') if value else ''


def decrypt_secret(value):
    if not value:
        return ''
    try:
        return get_secret_cipher().decrypt(value.encode('ascii')).decode('utf-8')
    except (InvalidToken, ValueError, UnicodeError) as error:
        raise ValidationError('Не удалось расшифровать настройки подключения. Проверьте ключ сервера.') from error
