"""Единые правила оформления и очистки текста визуального редактора."""

import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

import nh3
from django.conf import settings
from django.core.exceptions import ValidationError


MAX_ARTICLE_HTML_LENGTH = 200_000
EDITOR_FONTS = ('arial', 'georgia', 'monospace')
EDITOR_COLORS = ('ink', 'muted', 'green', 'red', 'blue')
EDITOR_BACKGROUNDS = ('yellow', 'green', 'blue', 'pink', 'orange')
EDITOR_CLASSES = {
    *(f'ql-font-{value}' for value in EDITOR_FONTS),
    *(f'ql-color-{value}' for value in EDITOR_COLORS),
    *(f'ql-bg-{value}' for value in EDITOR_BACKGROUNDS),
    *(f'ql-size-{value}' for value in ('small', 'large', 'huge')),
    *(f'ql-align-{value}' for value in ('center', 'right', 'justify')),
    *(f'ql-indent-{value}' for value in range(1, 9)),
}


def article_image_name(url):
    """Допускает только адреса растровых изображений нашего хранилища статей."""
    prefix = f'{settings.MEDIA_URL.rstrip("/")}/articles/content/'
    if not url.startswith(prefix):
        return None
    filename = url[len(prefix):]
    if not re.fullmatch(r'[a-f0-9]{32}\.(?:jpg|png|webp)', filename):
        return None
    return f'articles/content/{filename}'


def _filter_attribute(tag, attribute, value):
    if attribute == 'class':
        return ' '.join(item for item in value.split() if item in EDITOR_CLASSES) or None
    if tag == 'img' and attribute == 'src':
        return value if article_image_name(value) else None
    if tag == 'a' and attribute == 'href':
        if any(char.isspace() or ord(char) < 32 for char in value) or '\\' in value:
            return None
        if value.startswith('//'):
            return None
        if value.startswith(('/', '#')):
            return value
        try:
            parsed = urlsplit(value)
        except ValueError:
            return None
        if parsed.scheme in ('http', 'https') and parsed.netloc:
            return value
        if parsed.scheme == 'mailto' and parsed.path:
            return value
        return None
    return value


def sanitize_article_html(value):
    """Очищает HTML также при повторном открытии и публичном выводе статьи."""
    if len(value) > MAX_ARTICLE_HTML_LENGTH:
        raise ValidationError('Текст статьи слишком большой (максимум 200 000 символов).')
    cleaned = nh3.clean(
        value,
        tags={'p', 'span', 'br', 'h2', 'h3', 'h4', 'strong', 'em', 'u', 's', 'ol', 'ul', 'li',
              'blockquote', 'a', 'img', 'sub', 'sup'},
        clean_content_tags={'script', 'style', 'iframe', 'object', 'embed', 'svg', 'math', 'template'},
        attributes={'*': {'class'}, 'a': {'href', 'title'}, 'img': {'src', 'alt'}},
        attribute_filter=_filter_attribute,
        url_schemes={'http', 'https', 'mailto'},
        link_rel='noopener noreferrer',
        strip_comments=True,
    )
    # Quill экспортирует каждый пробел как &nbsp;, склеивая слова для браузера.
    # Парсер уже привёл именованные, числовые и Unicode-пробелы к одному виду.
    return cleaned.replace('&nbsp;', ' ').replace('\u00a0', ' ')


class ArticleHTMLReferences(HTMLParser):
    """Читает ссылки и текст из уже очищенного HTML без выполнения содержимого."""

    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.image_names = set()
        self.text = []
        self.feed(value)

    def handle_starttag(self, tag, attrs):
        if tag == 'img':
            name = article_image_name(dict(attrs).get('src', ''))
            if name:
                self.image_names.add(name)

    def handle_data(self, data):
        self.text.append(data)

    @property
    def has_content(self):
        return bool(''.join(self.text).strip() or self.image_names)
