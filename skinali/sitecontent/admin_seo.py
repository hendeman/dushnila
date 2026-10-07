"""Единое оформление и подсказки SEO-полей административных форм."""

from django import forms


SEO_RECOMMENDED_LENGTHS = {
    'seo_title': (50, 60),
    'seo_description': (140, 160),
}
SEO_COUNTER_FIELDS = ('seo_h1', *SEO_RECOMMENDED_LENGTHS)
SEO_WIDE_FIELDS = (*SEO_COUNTER_FIELDS, 'intro_text', 'page_description')


class SeoAdminMixin:
    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if field is None or db_field.name not in SEO_WIDE_FIELDS:
            return field
        classes = field.widget.attrs.get('class', '').split()
        if 'admin-seo-field' not in classes:
            classes.append('admin-seo-field')
        field.widget.attrs['class'] = ' '.join(classes)
        if db_field.name in SEO_COUNTER_FIELDS:
            field.widget.attrs['data-seo-counter'] = 'true'
        if db_field.name in SEO_RECOMMENDED_LENGTHS:
            minimum, maximum = SEO_RECOMMENDED_LENGTHS[db_field.name]
            recommendation = f'Рекомендуемая длина: {minimum}–{maximum} символов.'
            field.help_text = f'{recommendation} {field.help_text or ""}'.strip()
        return field

    @property
    def media(self):
        # Дополняем ресурсы admin и других mixin, включая просмотрщик изображений.
        return super().media + forms.Media(
            css={'all': ('skinali/css/admin-seo-landing-fields.css',)},
            js=('skinali/js/admin-seo-fields.js',),
        )
