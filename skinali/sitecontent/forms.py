from django import forms
from django.core.exceptions import ValidationError

from .models import Article, Integration, PriceTableRow
from .rich_text import MAX_ARTICLE_HTML_LENGTH, sanitize_article_html
from .widgets import QuillWidget


class PriceTableRowForm(forms.ModelForm):
    class Meta:
        model = PriceTableRow
        fields = '__all__'
        widgets = {
            'position': forms.HiddenInput,
            'description': forms.Textarea(attrs={'rows': 3, 'cols': 50}),
            'price': forms.Textarea(attrs={'rows': 3, 'cols': 25}),
        }

    def has_changed(self):
        # Перестановка пустой дополнительной строки не должна требовать её заполнения.
        if not self.instance.pk:
            return any(name != 'position' for name in self.changed_data)
        return super().has_changed()


class PriceTableRowFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        if self.instance.is_published and not any(
            form.cleaned_data.get('description') and not form.cleaned_data.get('DELETE')
            for form in self.forms
        ):
            raise ValidationError('Добавьте хотя бы одну строку перед публикацией таблицы.')


class ArticleAdminForm(forms.ModelForm):
    slug = forms.CharField(
        label=Article._meta.get_field('slug').verbose_name,
        max_length=Article._meta.get_field('slug').max_length,
        required=False, help_text=Article._meta.get_field('slug').help_text,
    )
    body = forms.CharField(label='Текст статьи', widget=QuillWidget, max_length=MAX_ARTICLE_HTML_LENGTH)

    class Meta:
        model = Article
        fields = '__all__'

    def clean_slug(self):
        value = self.cleaned_data['slug']
        return Article.slug_from_text(value) if value else ''

    def clean_body(self):
        return sanitize_article_html(self.cleaned_data['body'])

    def clean_cover(self):
        from .article_media import prepare_article_image

        cover = self.cleaned_data.get('cover')
        if cover and not hasattr(cover, '_committed'):
            # Проверка здесь даёт ошибку рядом с полем, до сохранения admin-формы.
            return prepare_article_image(cover)
        return cover


class IntegrationAdminForm(forms.ModelForm):
    class Meta:
        model = Integration
        fields = Integration.SNAPSHOT_FIELDS
        widgets = {
            field: forms.Textarea(attrs={'rows': 12, 'cols': 100, 'spellcheck': 'false', 'style': 'font-family: monospace; max-width: 100%;'})
            for field in ('head_html', 'body_start_html', 'body_end_html')
        }
