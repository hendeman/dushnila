import re
import time

from django import forms
from django.core import signing
from django.core.exceptions import ValidationError

from pict.models import ContactRequest, Integration, Pict


class IntegrationAdminForm(forms.ModelForm):
    class Meta:
        model = Integration
        fields = Integration.SNAPSHOT_FIELDS
        widgets = {
            field: forms.Textarea(attrs={'rows': 12, 'cols': 100, 'spellcheck': 'false', 'style': 'font-family: monospace; max-width: 100%;'})
            for field in ('head_html', 'body_start_html', 'body_end_html')
        }


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
    """Общие поля и антиспам-проверки всех публичных контактных форм."""

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
    # Поле должно оставаться обычным текстовым: многие боты пропускают input type="hidden".
    website = forms.CharField(
        label='Ваш сайт',
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

    def is_suspicious_submission(self):
        """Honeypot и подписанный возраст формы не раскрывают боту причину отказа."""
        if self.data.get(self.add_prefix('website'), '').strip():
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


class PhoneContactForm(BaseContactForm):
    """Общая телефонная часть форм обратного звонка и вопроса."""

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


class CallbackContactForm(PhoneContactForm):
    form_kind = ContactRequest.RequestType.CALLBACK


class QuestionContactForm(PhoneContactForm):
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


class EmailCommentContactForm(BaseContactForm):
    """Форма сообщения с обязательным обратным адресом без поля телефона."""

    form_kind = ContactRequest.RequestType.EMAIL_MESSAGE

    email = forms.EmailField(
        label='Email',
        max_length=254,
        error_messages={
            'required': 'Укажите ваш email.',
            'invalid': 'Введите корректный адрес электронной почты.',
            'max_length': 'Email должен содержать не более 254 символов.',
        },
        widget=forms.EmailInput(attrs={
            'autocomplete': 'email',
            'maxlength': 254,
            'required': True,
            'data-field-name': 'email',
        }),
    )
    comment = forms.CharField(
        label='Комментарий',
        required=False,
        max_length=250,
        error_messages={
            'max_length': 'Комментарий должен содержать не более 250 символов.',
        },
        widget=forms.Textarea(attrs={
            'rows': 5,
            'maxlength': 250,
            'data-field-name': 'comment',
        }),
    )

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()

    def clean_comment(self):
        return self.cleaned_data['comment'].strip()


class ImagePurchaseContactForm(EmailCommentContactForm):
    """Заявка на покупку оригинала конкретного изображения каталога."""

    form_kind = ContactRequest.RequestType.IMAGE_PURCHASE

    email = forms.EmailField(
        label='Email',
        max_length=50,
        error_messages={
            'required': 'Укажите ваш email.',
            'invalid': 'Введите корректный адрес электронной почты.',
            'max_length': 'Email должен содержать не более 50 символов.',
        },
        widget=forms.EmailInput(attrs={
            'autocomplete': 'email',
            'maxlength': 50,
            'required': True,
            'data-field-name': 'email',
        }),
    )
    # В браузер передаётся только первичный ключ; номер повторно берётся из БД.
    pict_id = forms.IntegerField(
        min_value=1,
        widget=forms.HiddenInput(attrs={'data-image-purchase-pict': True}),
        error_messages={
            'required': 'Не удалось определить изображение. Откройте его повторно.',
            'invalid': 'Не удалось определить изображение. Откройте его повторно.',
            'min_value': 'Не удалось определить изображение. Откройте его повторно.',
        },
    )

    def clean_pict_id(self):
        pict_id = self.cleaned_data['pict_id']
        try:
            self.catalog_image = (
                Pict.objects.published()
                .only('id', 'name')
                .get(pk=pict_id)
            )
        except Pict.DoesNotExist as error:
            raise ValidationError(
                'Выбранное изображение больше не доступно. Откройте другое изображение.'
            ) from error
        return pict_id


class PictAdminForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].initial = self.instance + 1  # автоподставление последней записи+1 добавить изображение

    class Meta:
        model = Pict
        fields = ['name', ]
