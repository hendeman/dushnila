from django import forms
from django.urls import reverse

from .rich_text import EDITOR_BACKGROUNDS, EDITOR_COLORS, EDITOR_FONTS, sanitize_article_html


class QuillWidget(forms.Textarea):
    """Переиспользуемый локальный редактор HTML с серверной загрузкой изображений."""

    template_name = 'sitecontent/widgets/quill.html'

    class Media:
        css = {'all': (
            'sitecontent/vendor/quill/quill.snow.css',
            'sitecontent/css/article-content.css',
            'sitecontent/css/quill-admin.css',
        )}
        js = ('sitecontent/vendor/quill/quill.js', 'sitecontent/js/quill-editor.js')

    def get_context(self, name, value, attrs):
        context = super().get_context(name, sanitize_article_html(value or ''), attrs)
        context['widget']['upload_url'] = reverse('admin:sitecontent_article_upload_image')
        context['widget']['fonts'] = ','.join(EDITOR_FONTS)
        context['widget']['colors'] = ','.join(EDITOR_COLORS)
        context['widget']['backgrounds'] = ','.join(EDITOR_BACKGROUNDS)
        return context
