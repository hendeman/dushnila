import re

from django import forms
from django.core.exceptions import ValidationError
from pict.models import ContactRequest

from .models import Article, LeadConnection
from .rich_text import MAX_ARTICLE_HTML_LENGTH, sanitize_article_html
from .widgets import QuillWidget
from .secrets import encrypt_secret


class ArticleAdminForm(forms.ModelForm):
    body = forms.CharField(label='Текст статьи', widget=QuillWidget, max_length=MAX_ARTICLE_HTML_LENGTH)

    class Meta:
        model = Article
        fields = '__all__'

    def clean_body(self):
        return sanitize_article_html(self.cleaned_data['body'])

    def clean_cover(self):
        from .article_media import prepare_article_image

        cover = self.cleaned_data.get('cover')
        if cover and not hasattr(cover, '_committed'):
            # Проверка здесь даёт ошибку рядом с полем, до сохранения admin-формы.
            return prepare_article_image(cover)
        return cover


class LeadConnectionForm(forms.ModelForm):
    request_types = forms.MultipleChoiceField(
        label='Типы заявок',
        choices=[
            (value, f'{label} (форма снята с сайта)' if value == ContactRequest.RequestType.EMAIL_MESSAGE else label)
            for value, label in ContactRequest.RequestType.choices
        ],
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    recipients = forms.CharField(
        label='Получатели', required=False, widget=forms.Textarea(attrs={'rows': 4, 'cols': 50}),
        help_text='Один ID Telegram-чата или email на строку. Изменение списка применяется к новым отправкам; получатели накопленных отправок сохраняются.',
    )
    telegram_token = forms.CharField(label='Токен бота', required=False, max_length=200, widget=forms.PasswordInput(render_value=False))
    proxy_url = forms.CharField(label='HTTP(S)-прокси', required=False, max_length=1000, widget=forms.PasswordInput(render_value=False))
    clear_proxy = forms.BooleanField(label='Удалить сохранённый прокси', required=False)
    smtp_password = forms.CharField(label='Пароль SMTP', required=False, max_length=1000, strip=False, widget=forms.PasswordInput(render_value=False))
    clear_smtp_password = forms.BooleanField(
        label='Удалить сохранённый пароль SMTP',
        required=False,
        help_text='Если подключение включено и указан логин SMTP, пароль удалить нельзя. Сначала очистите логин или выключите подключение.',
    )

    class Meta:
        model = LeadConnection
        exclude = ('telegram_token_encrypted', 'proxy_url_encrypted', 'smtp_password_encrypted', 'configuration_error')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial['recipients'] = '\n'.join(self.instance.recipients or [])
        if not self.is_bound and self.initial.get('all_request_types', self.instance.all_request_types):
            self.initial['request_types'] = list(ContactRequest.RequestType.values)
        for field, stored in (
            ('telegram_token', 'telegram_token_encrypted'),
            ('proxy_url', 'proxy_url_encrypted'),
            ('smtp_password', 'smtp_password_encrypted'),
        ):
            if field not in self.fields:
                continue
            self.fields[field].help_text = (
                'Значение сохранено. Оставьте поле пустым, чтобы сохранить его.'
                if getattr(self.instance, stored) else 'Значение ещё не сохранено.'
            )
            self.fields[field].widget.attrs['autocomplete'] = 'new-password'
        if 'use_environment' in self.fields:
            self.fields['use_environment'].help_text = 'Использовать прежние токен, прокси и тайм-ауты из .env. Пустой список получателей использует TELEGRAM_CHAT_ID.'

    def clean_recipients(self):
        return [value.strip() for value in self.cleaned_data['recipients'].splitlines() if value.strip()]

    def clean_telegram_token(self):
        value = self.cleaned_data['telegram_token']
        if value and not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', value):
            raise ValidationError('Токен должен иметь формат, выданный Telegram BotFather.')
        return value

    def clean(self):
        cleaned = super().clean()
        from pict.services.telegram_delivery import validate_proxy_url

        if cleaned.get('all_request_types'):
            cleaned['request_types'] = list(ContactRequest.RequestType.values)
        if cleaned.get('proxy_url'):
            try:
                validate_proxy_url(cleaned['proxy_url'])
            except ValidationError as error:
                self.add_error('proxy_url', error)
        for field, stored in (
            ('telegram_token', 'telegram_token_encrypted'),
            ('proxy_url', 'proxy_url_encrypted'),
            ('smtp_password', 'smtp_password_encrypted'),
        ):
            value = cleaned.get(field)
            if value:
                try:
                    setattr(self.instance, stored, encrypt_secret(value))
                except ValidationError as error:
                    self.add_error(field, error)
        if cleaned.get('clear_proxy'):
            if cleaned.get('proxy_url'):
                self.add_error('clear_proxy', 'Выберите удаление или ввод нового прокси.')
            else:
                self.instance.proxy_url_encrypted = ''
        if cleaned.get('clear_smtp_password'):
            if cleaned.get('smtp_password'):
                self.add_error('clear_smtp_password', 'Выберите удаление или ввод нового пароля.')
            else:
                self.instance.smtp_password_encrypted = ''
        return cleaned
