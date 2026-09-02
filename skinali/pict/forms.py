import re
import time

from django import forms
from django.core import signing
from django.core.exceptions import ValidationError

from pict.models import ContactRequest, Pict


CONTACT_FORM_TOKEN_SALT = 'pict.contact-form'
CONTACT_FORM_MIN_AGE_SECONDS = 2
CONTACT_FORM_MAX_AGE_SECONDS = 24 * 60 * 60


def create_contact_form_token():
    """Создает подписанную метку времени без хранения состояния на сервере."""
    return signing.dumps(
        {'issued_at': time.time()},
        salt=CONTACT_FORM_TOKEN_SALT,
        compress=True,
    )


class BaseContactForm(forms.Form):
    """Общие поля, валидация и антиспам-проверки контактных форм."""

    form_kind = ''

    name = forms.CharField(
        label='Ваше имя',
        min_length=3,
        max_length=20,
        error_messages={
            'required': 'Укажите ваше имя.',
            'min_length': 'Имя должно содержать не менее 3 символов.',
            'max_length': 'Имя должно содержать не более 20 символов.',
        },
        widget=forms.TextInput(attrs={
            'autocomplete': 'name',
            'minlength': 3,
            'maxlength': 20,
            'required': True,
            'data-field-name': 'name',
        }),
    )
    phone = forms.CharField(
        label='Номер телефона',
        max_length=20,
        error_messages={
            'required': 'Укажите номер телефона.',
            'max_length': 'Номер телефона должен содержать не более 20 символов.',
        },
        widget=forms.TextInput(attrs={
            'type': 'tel',
            'autocomplete': 'tel',
            'inputmode': 'tel',
            'maxlength': 20,
            'pattern': r'[0-9+() \-]+',
            'title': 'Используйте только цифры, +, круглые скобки, пробел и дефис.',
            'required': True,
            'data-field-name': 'phone',
        }),
    )
    # Поле должно оставаться обычным текстовым: многие боты пропускают input type="hidden".
    email = forms.CharField(
        label='Email',
        required=False,
        widget=forms.TextInput(attrs={
            'autocomplete': 'off',
            'tabindex': '-1',
            'data-contact-honeypot': True,
        }),
    )
    form_token = forms.CharField(widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.setdefault('form_token', create_contact_form_token())

    def clean_name(self):
        name = ' '.join(self.cleaned_data['name'].split())
        if not 3 <= len(name) <= 20:
            raise ValidationError('Имя должно содержать от 3 до 20 символов.')

        allowed_separators = {' ', '-', "'", '’'}
        if not all(character.isalpha() or character in allowed_separators for character in name):
            raise ValidationError(
                'Используйте только буквы, пробел, дефис или апостроф.'
            )
        return name

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        if not re.fullmatch(r'[0-9+() \-]+', phone):
            raise ValidationError(
                'Используйте только цифры, +, круглые скобки, пробел и дефис.'
            )

        if phone.count('+') > 1 or ('+' in phone and not phone.startswith('+')):
            raise ValidationError('Символ + можно указать только один раз в начале номера.')

        digits_count = sum(character.isdigit() for character in phone)
        if not 7 <= digits_count <= 15:
            raise ValidationError('Номер должен содержать от 7 до 15 цифр.')
        return phone

    def is_suspicious_submission(self):
        """Honeypot и подписанный возраст формы не раскрывают боту причину отказа."""
        if self.data.get(self.add_prefix('email'), '').strip():
            return True

        token = self.data.get(self.add_prefix('form_token'), '')
        try:
            payload = signing.loads(
                token,
                salt=CONTACT_FORM_TOKEN_SALT,
                max_age=CONTACT_FORM_MAX_AGE_SECONDS,
            )
            form_age = time.time() - float(payload['issued_at'])
        except (signing.BadSignature, signing.SignatureExpired, KeyError, TypeError, ValueError):
            return True

        return form_age < CONTACT_FORM_MIN_AGE_SECONDS


class CallbackContactForm(BaseContactForm):
    form_kind = ContactRequest.RequestType.CALLBACK


class QuestionContactForm(BaseContactForm):
    form_kind = ContactRequest.RequestType.QUESTION

    question = forms.CharField(
        label='Ваш вопрос',
        required=False,
        max_length=250,
        error_messages={
            'max_length': 'Вопрос должен содержать не более 250 символов.',
        },
        widget=forms.Textarea(attrs={
            'rows': 5,
            'maxlength': 250,
            'data-field-name': 'question',
        }),
    )

    def clean_question(self):
        return self.cleaned_data['question'].strip()


class PictAdminForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].initial = self.instance + 1  # автоподставление последней записи+1 добавить изображение

    class Meta:
        model = Pict
        fields = ['name', ]
