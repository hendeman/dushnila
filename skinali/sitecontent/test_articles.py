import re
import tempfile
from datetime import timedelta
from io import BytesIO, StringIO
from unittest.mock import patch

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .article_media import prepare_article_image
from .forms import ArticleAdminForm
from .models import Article, ArticleImage, SitePage
from .rich_text import EDITOR_BACKGROUNDS, MAX_ARTICLE_HTML_LENGTH, sanitize_article_html
from .widgets import QuillWidget


def uploaded_image(name='cover.jpg', image_format='JPEG', size=(80, 50)):
    buffer = BytesIO()
    Image.new('RGB', size, color='green').save(buffer, format=image_format)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/jpeg')


class ArticleTestCase(TestCase):
    def setUp(self):
        self.article_sequence = 0
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.directory.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

    def article(self, **kwargs):
        self.article_sequence += 1
        title = 'Как выбрать скинали'
        if self.article_sequence > 1:
            title += f' {self.article_sequence}'
        return Article.objects.create(**{
            'title': title, 'summary': 'Советы по выбору стекла.',
            'body': '<p>Полезная <strong>статья</strong>.</p>', 'cover': uploaded_image(),
            **kwargs,
        })

    def content_image(self):
        return ArticleImage.objects.create(image=prepare_article_image(uploaded_image()))


class ArticleSanitizationTests(TestCase):
    def test_quill_spaces_allow_word_wrapping_without_decoding_escaped_html(self):
        value = (
            '<p>Первое&nbsp;слово <strong>второе&#160;слово</strong> '
            'и\u00a0третье&#xA0;слово. &amp;nbsp; '
            '&lt;script&gt;example()&lt;/script&gt;</p>'
        )
        clean = sanitize_article_html(value)
        self.assertEqual(clean, (
            '<p>Первое слово <strong>второе слово</strong> '
            'и третье слово. &amp;nbsp; &lt;script&gt;example()&lt;/script&gt;</p>'
        ))
        self.assertEqual(sanitize_article_html(clean), clean)

    def test_removes_scripts_events_embeds_css_and_dangerous_links(self):
        samples = (
            '<p onclick="alert(1)">Текст</p><script>alert(1)</script>',
            '<p>Текст</p><svg><script>alert(1)</script></svg>',
            '<p>Текст</p><iframe srcdoc="<script>alert(1)</script>"></iframe>',
            '<p style="background:url(javascript:alert(1))" id="location">Текст</p>',
            '<p>Текст</p><a href="javascript:alert(1)">Ссылка</a>',
            '<p>Текст</p><a href="jav&#x61;script:alert(1)">Ссылка</a>',
            '<p>Текст</p><a href="data:text/html,test">Ссылка</a>',
            '<p>Текст</p><a href="//example.com">Ссылка</a>',
            '<p>Текст</p><img src="https://evil.example/pixel" onerror="alert(1)">',
            '<p>Текст</p><img src="data:image/svg+xml,test">',
            '<p>Текст</p><math><mtext><table><mglyph><style><!--</style><img title="--><img src=x onerror=alert(1)>">',
        )
        for sample in samples:
            with self.subTest(sample=sample):
                clean = sanitize_article_html(sample)
                for forbidden in ('<script', 'onclick=', 'onerror=', 'style=', '<svg', '<iframe',
                                  '<math', 'javascript:', 'data:', 'id=', 'evil.example', '//example.com'):
                    self.assertNotIn(forbidden, clean)
                self.assertIn('Текст', clean)

    def test_preserves_only_allowed_formatting_links_and_local_images(self):
        name = 'a' * 32
        value = (
            '<h2>Заголовок</h2><p class="ql-align-center evil">'
            '<span class="ql-font-georgia ql-color-green ql-size-large">Текст</span></p>'
            '<ul><li><strong>Пункт</strong></li></ul>'
            '<a href="https://example.com" target="_blank">Ссылка</a>'
            f'<img src="/media/articles/content/{name}.jpg" alt="Пример">'
        )
        clean = sanitize_article_html(value)
        self.assertIn('<h2>Заголовок</h2>', clean)
        self.assertIn('class="ql-align-center"', clean)
        self.assertNotIn('evil', clean)
        self.assertIn('ql-font-georgia ql-color-green ql-size-large', clean)
        self.assertIn('rel="noopener noreferrer"', clean)
        self.assertIn(f'src="/media/articles/content/{name}.jpg"', clean)
        self.assertEqual(sanitize_article_html(clean), clean)

    def test_rejects_oversized_body_and_unsafe_media_paths(self):
        with self.assertRaises(ValidationError):
            sanitize_article_html('a' * (MAX_ARTICLE_HTML_LENGTH + 1))
        for url in ('/media/articles/content/../bad.jpg', '/media/photos/1.jpg',
                    '/media/articles/content/' + 'a' * 32 + '.svg'):
            self.assertNotIn('src=', sanitize_article_html(f'<img src="{url}">'))

    def test_highlighting_preserves_allowed_backgrounds_and_removes_arbitrary_css(self):
        for color in EDITOR_BACKGROUNDS:
            with self.subTest(color=color):
                value = f'<p><span class="ql-bg-{color}">Важный текст</span></p>'
                self.assertEqual(sanitize_article_html(value), value)
        self.assertEqual(sanitize_article_html(
            '<span class="ql-bg-yellow ql-bg-black evil" '
            'style="background-image:url(javascript:bad())" onclick="bad()">Текст</span>'
        ), '<span class="ql-bg-yellow">Текст</span>')


class ArticleModelTests(ArticleTestCase):
    def test_slug_is_latin_unique_and_unchanged_when_title_changes(self):
        first = self.article()
        second = self.article(title='Панели из стекла')
        self.assertEqual(first.slug, 'kak-vybrat-skinali')
        self.assertEqual(second.slug, 'paneli-iz-stekla')
        slug = first.slug
        first.title = second.title
        first.slug = 'attempt-to-change-url'
        first.save()
        first.refresh_from_db()
        self.assertEqual(first.slug, slug)

    def test_new_article_rejects_duplicate_transliterated_slug_including_drafts(self):
        first = self.article(title='Типы стёкол')
        for title in ('Типы стёкол', 'Tipy styokol', 'ТИПЫ СТЁКОЛ!'):
            with self.subTest(title=title):
                with self.assertRaises(ValidationError) as error:
                    self.article(title=title)
                self.assertEqual(set(error.exception.error_dict), {'slug'})
                self.assertIn(first.slug, str(error.exception))
        self.assertEqual(Article.objects.count(), 1)

    def test_custom_address_is_transliterated_and_independent_of_title(self):
        first = self.article(title='Большой заголовок', slug='Типы стёкол!')
        second = self.article(title=first.title, slug='Уход за стеклом')
        self.assertEqual(first.slug, 'tipy-styokol')
        self.assertEqual(second.slug, 'ukhod-za-steklom')
        first.title = 'Обновлённый заголовок'
        first.slug = 'Попытка поменять адрес'
        first.save()
        first.refresh_from_db()
        self.assertEqual(first.slug, 'tipy-styokol')

    def test_custom_address_collision_is_rejected_even_with_different_titles(self):
        first = self.article(title='Первая статья', slug='Типы стекол')
        with self.assertRaises(ValidationError) as error:
            self.article(title='Другая статья', slug='TIPY STEKOL!')
        self.assertEqual(set(error.exception.error_dict), {'slug'})
        self.assertIn(first.slug, str(error.exception))
        self.assertEqual(Article.objects.count(), 1)

    def test_slug_length_and_fallback_collisions_are_checked(self):
        first = self.article(title='щ' * 199 + 'а')
        self.assertEqual(len(first.slug), Article._meta.get_field('slug').max_length)
        with self.assertRaises(ValidationError):
            self.article(title='щ' * 199 + 'б')
        self.assertEqual(self.article(title='✨').slug, 'statya')
        with self.assertRaises(ValidationError):
            self.article(title='🎨')

    def test_existing_random_suffix_survives_editing_and_partial_save(self):
        article = self.article()
        old_slug = 'kak-vybrat-skinali-bfc882f4a1c5'
        Article.objects.filter(pk=article.pk).update(slug=old_slug)
        article.refresh_from_db()
        article.title = 'Другое название'
        article.slug = 'attempt-to-change-url'
        article.save(update_fields=['title'])
        article.refresh_from_db()
        self.assertEqual(article.slug, old_slug)
        self.assertTrue(article.get_absolute_url().endswith(f'/{old_slug}/'))

    def test_first_publication_date_is_preserved_and_can_be_edited(self):
        article = self.article()
        self.assertIsNone(article.published_at)
        article.is_published = True
        article.save(update_fields=['is_published'])
        article.refresh_from_db()
        first_date = article.published_at
        self.assertIsNotNone(first_date)
        article.title = 'Обновлённый заголовок'
        article.save(update_fields=['title'])
        self.assertEqual(article.published_at, first_date)
        article.is_published = False
        article.save()
        article.is_published = True
        article.save()
        self.assertEqual(article.published_at, first_date)
        chosen_date = timezone.now() - timedelta(days=7)
        article.published_at = chosen_date
        article.save()
        article.refresh_from_db()
        self.assertEqual(article.published_at, chosen_date)

    def test_model_cleans_html_and_rejects_empty_content(self):
        article = self.article(body='<p onclick="alert(1)">Текст&nbsp;статьи</p><script>bad()</script>')
        self.assertEqual(article.body, '<p>Текст статьи</p>')
        for body in ('<p><br></p>', '<script>alert(1)</script>', '   '):
            with self.assertRaises(ValidationError):
                self.article(body=body)

    def test_model_validates_cover_outside_admin(self):
        with self.assertRaises(ValidationError):
            self.article(cover=SimpleUploadedFile('x.jpg', b'<script>bad()</script>'))
        with self.assertRaises(ValidationError):
            ArticleImage.objects.create(image=SimpleUploadedFile('x.svg', b'<svg/>'))

    def test_article_changes_update_section_lastmod(self):
        page = SitePage.objects.get(code=SitePage.Code.ARTICLES)
        before = page.updated_at
        article = self.article(is_published=True)
        page.refresh_from_db()
        self.assertGreater(page.updated_at, before)
        before = page.updated_at
        article.delete()
        page.refresh_from_db()
        self.assertGreater(page.updated_at, before)

    def test_replacing_cover_deletes_old_file_only_after_commit(self):
        article = self.article()
        previous = article.cover.name
        with self.captureOnCommitCallbacks(execute=True):
            article.cover = uploaded_image()
            article.save()
            self.assertTrue(article.cover.storage.exists(previous))
        self.assertFalse(article.cover.storage.exists(previous))
        self.assertTrue(article.cover.storage.exists(article.cover.name))

    def test_shared_images_survive_until_last_article_removes_them(self):
        image = self.content_image()
        image_id, name = image.pk, image.image.name
        body = f'<p>Текст</p><img src="{image.image.url}" alt="Пример">'
        first = self.article(body=body)
        second = self.article(body=body)
        self.assertEqual(first.images.get().pk, image_id)
        with self.captureOnCommitCallbacks(execute=True):
            first.body = '<p>Только текст</p>'
            first.save()
        self.assertTrue(ArticleImage.objects.filter(pk=image_id).exists())
        with self.captureOnCommitCallbacks(execute=True):
            second.delete()
        self.assertFalse(ArticleImage.objects.filter(pk=image_id).exists())
        self.assertFalse(image.image.storage.exists(name))

    def test_rollback_does_not_delete_previous_images(self):
        image = self.content_image()
        article = self.article(body=f'<p>Текст</p><img src="{image.image.url}">')
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                article.body = '<p>Замена</p>'
                article.save()
                raise RuntimeError('rollback')
        article.refresh_from_db()
        self.assertTrue(article.images.filter(pk=image.pk).exists())
        self.assertTrue(image.image.storage.exists(image.image.name))

    def test_abandoned_upload_cleanup_preserves_recent_and_linked_files(self):
        abandoned, recent, linked = [self.content_image() for _ in range(3)]
        ArticleImage.objects.filter(pk__in=[abandoned.pk, linked.pk]).update(
            created_at=timezone.now() - timedelta(days=2),
        )
        self.article(body=f'<p>Текст</p><img src="{linked.image.url}">')
        output = StringIO()
        call_command('cleanup_article_images', stdout=output)
        self.assertIn(abandoned.image.name, output.getvalue())
        self.assertTrue(ArticleImage.objects.filter(pk=abandoned.pk).exists())
        with self.captureOnCommitCallbacks(execute=True):
            call_command('cleanup_article_images', delete=True, stdout=StringIO())
        self.assertFalse(ArticleImage.objects.filter(pk=abandoned.pk).exists())
        self.assertFalse(abandoned.image.storage.exists(abandoned.image.name))
        self.assertEqual(set(ArticleImage.objects.values_list('pk', flat=True)), {recent.pk, linked.pk})


class ArticlePublicTests(ArticleTestCase):
    def test_list_contains_seven_newest_articles_and_shared_pagination(self):
        for number in range(11):
            self.article(title=f'Статья {number}', summary=f'Описание статьи {number}', is_published=True,
                         published_at=timezone.now() - timedelta(days=number))
        draft = self.article(title='Скрытый черновик')
        first = self.client.get(reverse('article_list'))
        self.assertEqual(len(first.context['articles']), 7)
        self.assertEqual(
            [article.title for article in first.context['articles']],
            [f'Статья {number}' for number in range(7)],
        )
        self.assertContains(first, 'catalog-pagination')
        self.assertNotContains(first, draft.title)
        self.assertNotContains(first, 'quill.js')
        self.assertContains(first, 'article-card--featured', count=1)
        self.assertNotContains(first, 'Описание статьи 0')
        self.assertContains(first, 'Описание статьи 1')
        self.assertNotContains(first, 'Читать статью')
        cover_links = re.findall(
            r'<a\b[^>]*class="article-card__cover"[^>]*>(.*?)</a>', first.content.decode(), re.S,
        )
        self.assertEqual(len(cover_links), 7)
        self.assertIn('<h2', cover_links[0])
        for content in cover_links[1:]:
            self.assertNotIn('<h2', content)
        for article in first.context['articles']:
            self.assertContains(first, f'href="{article.get_absolute_url()}"', count=1)
            self.assertContains(first, f'alt="{article.title}"', count=1)
        second = self.client.get(reverse('article_list'), {'page': 2})
        self.assertEqual(
            [article.title for article in second.context['articles']],
            [f'Статья {number}' for number in range(7, 11)],
        )
        self.assertContains(second, 'Статья 10')
        self.assertContains(second, 'article-card--featured', count=1)
        self.assertContains(second, '?page=2"', count=1)
        self.assertContains(second, 'страница 2 | ОДИУМ')
        self.assertEqual(self.client.get(reverse('article_list'), {'page': 99}).status_code, 404)

    def test_detail_excludes_cover_date_and_drafts_and_has_seo(self):
        article = self.article(is_published=True, seo_title='Выбор стекла', seo_description='Описание для SEO')
        response = self.client.get(article.get_absolute_url())
        self.assertContains(response, '<title>Выбор стекла | ОДИУМ</title>')
        self.assertContains(response, 'content="Описание для SEO"')
        self.assertContains(response, '<strong>статья</strong>')
        self.assertNotContains(response, article.cover.url)
        self.assertNotContains(response, '<time')
        self.assertNotContains(response, 'quill.js')
        self.assertEqual(self.client.get(self.article().get_absolute_url()).status_code, 404)
        article.is_published = False
        article.save()
        self.assertEqual(self.client.get(article.get_absolute_url()).status_code, 404)

    def test_public_output_sanitizes_bypassed_model_save_and_escapes_metadata(self):
        article = self.article(is_published=True, title='<script>bad()</script>', summary='<img onerror=bad()>')
        Article.objects.filter(pk=article.pk).update(body='<p onmouseover="bad()">Текст&nbsp;статьи</p><script>bad()</script>')
        response = self.client.get(article.get_absolute_url())
        self.assertContains(response, '&lt;script&gt;bad()&lt;/script&gt;')
        self.assertNotContains(response, '<script>bad()')
        self.assertNotContains(response, 'onmouseover=')
        self.assertContains(response, '<p>Текст статьи</p>')

    def test_list_seo_and_sitemap_include_only_published_articles(self):
        published = self.article(is_published=True)
        draft = self.article()
        SitePage.objects.filter(code=SitePage.Code.ARTICLES).update(
            seo_title='Советы о скинали', seo_description='Описание раздела',
        )
        listing = self.client.get(reverse('article_list'))
        self.assertContains(listing, 'Советы о скинали | ОДИУМ')
        self.assertContains(listing, 'content="Описание раздела"')
        sitemap = self.client.get(reverse('sitemap'))
        self.assertContains(sitemap, published.get_absolute_url())
        self.assertNotContains(sitemap, draft.get_absolute_url())


class ArticleAdminTests(ArticleTestCase):
    def setUp(self):
        super().setUp()
        self.superuser = get_user_model().objects.create_superuser('article-admin', 'admin@example.com', 'test-password')
        self.client.force_login(self.superuser)
        self.upload_url = reverse('admin:sitecontent_article_upload_image')

    def test_publication_checkboxes_save_changes_and_preserve_first_publication_dates(self):
        publication_date = timezone.now() - timedelta(days=3)
        published = self.article(is_published=True, published_at=publication_date)
        draft = self.article()
        unchanged = self.article(is_published=True)
        unchanged_updated_at = unchanged.updated_at
        SitePage.objects.filter(code=SitePage.Code.ARTICLES).update(updated_at=publication_date)
        changelist_url = reverse('admin:sitecontent_article_changelist')
        listing = self.client.get(changelist_url)
        self.assertContains(listing, 'name="form-0-is_published"')
        self.assertContains(listing, 'value="delete_selected"')
        self.assertNotContains(listing, 'Снять выделенные с публикации')
        formset = listing.context['cl'].formset
        data = {
            'form-TOTAL_FORMS': str(len(formset.forms)),
            'form-INITIAL_FORMS': str(len(formset.forms)),
            'form-MIN_NUM_FORMS': '0', 'form-MAX_NUM_FORMS': '1000',
            '_save': 'Сохранить',
        }
        for index, form in enumerate(formset.forms):
            data[f'form-{index}-id'] = str(form.instance.pk)
            if form.instance.pk != published.pk:
                data[f'form-{index}-is_published'] = 'on'
        started_at = timezone.now()
        response = self.client.post(changelist_url, data)
        self.assertRedirects(response, changelist_url)
        published.refresh_from_db()
        draft.refresh_from_db()
        unchanged.refresh_from_db()
        self.assertFalse(published.is_published)
        self.assertEqual(published.published_at, publication_date)
        self.assertGreaterEqual(published.updated_at, started_at)
        self.assertTrue(draft.is_published)
        self.assertGreaterEqual(draft.published_at, started_at)
        self.assertTrue(unchanged.is_published)
        self.assertEqual(unchanged.updated_at, unchanged_updated_at)
        page_updated_at = SitePage.objects.get(code=SitePage.Code.ARTICLES).updated_at
        self.assertGreater(page_updated_at, publication_date)
        self.assertEqual(self.client.get(published.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(draft.get_absolute_url()).status_code, 200)
        listing = self.client.get(reverse('article_list'))
        sitemap = self.client.get(reverse('sitemap'))
        self.assertNotContains(listing, published.get_absolute_url())
        self.assertNotContains(sitemap, published.get_absolute_url())
        self.assertContains(listing, draft.get_absolute_url())
        self.assertContains(sitemap, draft.get_absolute_url())
        logs = LogEntry.objects.filter(content_type__app_label='sitecontent', content_type__model='article')
        self.assertEqual(set(logs.values_list('object_id', 'action_flag')), {(str(article.pk), CHANGE) for article in (published, draft)})
        first_publication_date = draft.published_at
        self.assertRedirects(self.client.post(changelist_url, data), changelist_url)
        draft.refresh_from_db()
        self.assertEqual(draft.published_at, first_publication_date)
        self.assertEqual(logs.count(), 2)
        self.assertEqual(SitePage.objects.get(code=SitePage.Code.ARTICLES).updated_at, page_updated_at)

    def test_publication_list_editing_is_denied_to_staff_even_with_change_permission(self):
        article = self.article(is_published=True)
        staff = get_user_model().objects.create_user('publication-staff', password='test-password', is_staff=True)
        staff.user_permissions.set(Permission.objects.filter(content_type__app_label='sitecontent'))
        self.client.force_login(staff)
        response = self.client.post(reverse('admin:sitecontent_article_changelist'), {
            'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '1',
            'form-0-id': str(article.pk), '_save': 'Сохранить',
        })
        self.assertEqual(response.status_code, 403)
        article.refresh_from_db()
        self.assertTrue(article.is_published)

    def test_widget_assets_are_local_and_initial_html_is_sanitized(self):
        response = self.client.get(reverse('admin:sitecontent_article_add'))
        self.assertContains(response, '/static/sitecontent/vendor/quill/quill.js')
        self.assertContains(response, 'article-content.css')
        self.assertContains(response, self.upload_url)
        self.assertContains(response, 'data-fonts="arial,georgia,monospace"')
        self.assertContains(response, 'data-backgrounds="yellow,green,blue,pink,orange"')
        self.assertNotContains(response, 'cdn.jsdelivr.net')
        html = QuillWidget().render('body', '<script>bad()</script><p>Текст</p>', {'id': 'id_body'})
        self.assertNotIn('bad()', html)
        self.assertIn('&lt;p&gt;Текст&lt;/p&gt;', html)

    def test_admin_creates_article_with_cover_clean_html_and_publication(self):
        response = self.client.post(reverse('admin:sitecontent_article_add'), {
            'title': 'Новая статья', 'summary': 'Описание', 'cover': uploaded_image(),
            'body': '<p onmouseover="bad()">Текст</p><script>bad()</script>',
            'is_published': 'on', 'seo_title': '', 'seo_description': '',
            'published_at_0': '', 'published_at_1': '', '_save': 'Сохранить',
        })
        self.assertEqual(response.status_code, 302)
        article = Article.objects.get()
        self.assertEqual(article.body, '<p>Текст</p>')
        self.assertIsNotNone(article.published_at)
        self.assertTrue(article.cover.name.startswith('articles/covers/'))
        self.assertEqual(article.slug, 'novaya-statya')

    def test_admin_rejects_duplicate_slug_at_address_and_preserves_submitted_text(self):
        article = self.article(title='Типы стёкол')
        response = self.client.post(reverse('admin:sitecontent_article_add'), {
            'title': 'ТИПЫ СТЁКОЛ!', 'summary': 'Новое описание', 'cover': uploaded_image(),
            'body': '<p>Текст&nbsp;новой статьи</p>',
            'published_at_0': '', 'published_at_1': '', 'seo_title': '', 'seo_description': '',
            '_save': 'Сохранить',
        })
        self.assertEqual(response.status_code, 200)
        form = response.context['adminform'].form
        self.assertEqual(set(form.errors), {'slug'})
        self.assertIn(article.slug, form.errors['slug'][0])
        self.assertContains(response, 'Текст новой статьи')
        self.assertEqual(Article.objects.count(), 1)

    def test_admin_accepts_separate_address_and_locks_it_after_creation(self):
        add_url = reverse('admin:sitecontent_article_add')
        self.assertContains(self.client.get(add_url), 'name="slug"')
        data = {
            'title': 'Длинный заголовок для посетителей', 'slug': 'Типы стекол',
            'summary': 'Описание', 'body': '<p>Текст статьи</p>',
            'published_at_0': '', 'published_at_1': '', 'seo_title': '', 'seo_description': '',
            '_save': 'Сохранить',
        }
        response = self.client.post(add_url, {**data, 'cover': uploaded_image()})
        self.assertEqual(response.status_code, 302)
        article = Article.objects.get()
        self.assertEqual(article.slug, 'tipy-stekol')
        self.assertEqual(article.title, data['title'])
        change_url = reverse('admin:sitecontent_article_change', args=[article.pk])
        self.assertNotContains(self.client.get(change_url), 'name="slug"')
        response = self.client.post(change_url, {**data, 'title': 'Новый заголовок', 'slug': 'drugoy-adres'})
        self.assertEqual(response.status_code, 302)
        article.refresh_from_db()
        self.assertEqual(article.title, 'Новый заголовок')
        self.assertEqual(article.slug, 'tipy-stekol')

    def test_invalid_cover_is_a_form_error(self):
        form = ArticleAdminForm(data={
            'title': 'Статья', 'summary': 'Описание', 'body': '<p>Текст</p>',
        }, files={'cover': SimpleUploadedFile('evil.svg', b'<svg/>')})
        self.assertFalse(form.is_valid())
        self.assertIn('cover', form.errors)

    def test_upload_checks_permission_method_and_csrf(self):
        self.assertEqual(self.client.get(self.upload_url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.superuser)
        self.assertEqual(csrf_client.post(self.upload_url, {'image': uploaded_image()}).status_code, 403)
        csrf_client.get(reverse('admin:sitecontent_article_add'))
        self.assertEqual(csrf_client.post(
            self.upload_url, {'image': uploaded_image()},
            HTTP_X_CSRFTOKEN=csrf_client.cookies['csrftoken'].value,
        ).status_code, 201)
        staff = get_user_model().objects.create_user('article-staff', password='test-password', is_staff=True)
        staff.user_permissions.set(Permission.objects.filter(content_type__app_label='sitecontent'))
        self.client.force_login(staff)
        for url in (reverse('admin:sitecontent_article_add'), reverse('admin:sitecontent_article_changelist')):
            self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(self.upload_url, {'image': uploaded_image()}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.post(self.upload_url, {'image': uploaded_image()}).status_code, 302)

    def test_upload_accepts_real_content_and_rejects_fake_svg_and_oversized_files(self):
        response = self.client.post(self.upload_url, {'image': uploaded_image('evil.php')})
        self.assertEqual(response.status_code, 201)
        image = ArticleImage.objects.get()
        self.assertRegex(image.image.name, r'^articles/content/[a-f0-9]{32}\.jpg$')
        self.assertEqual(response.json()['url'], image.image.url)
        for upload in (
            SimpleUploadedFile('fake.jpg', b'<script>bad()</script>', content_type='image/jpeg'),
            SimpleUploadedFile('evil.svg', b'<svg onload="bad()"/>', content_type='image/svg+xml'),
            SimpleUploadedFile('huge.jpg', b'a' * (5 * 1024 * 1024 + 1)),
        ):
            self.assertEqual(self.client.post(self.upload_url, {'image': upload}).status_code, 400)
        with patch('sitecontent.article_media.MAX_ARTICLE_IMAGE_PIXELS', 100):
            self.assertEqual(self.client.post(self.upload_url, {'image': uploaded_image()}).status_code, 400)
        self.assertEqual(ArticleImage.objects.count(), 1)

    def test_reencoding_discards_appended_payload(self):
        upload = uploaded_image()
        poisoned = SimpleUploadedFile('poisoned.jpg', upload.read() + b'<script>payload()</script>')
        prepared = prepare_article_image(poisoned)
        self.assertNotIn(b'payload()', prepared.read())

    def test_reencoding_limits_dimensions_preserves_transparency_and_is_not_repeated(self):
        prepared = prepare_article_image(uploaded_image(size=(2400, 1200)))
        with Image.open(prepared) as image:
            self.assertEqual(image.size, (1920, 960))
        self.assertIs(prepare_article_image(prepared), prepared)
        buffer = BytesIO()
        Image.new('RGBA', (10, 10), color=(10, 20, 30, 0)).save(buffer, format='PNG')
        transparent = prepare_article_image(SimpleUploadedFile('transparent.png', buffer.getvalue()))
        with Image.open(transparent) as image:
            self.assertEqual(image.getpixel((0, 0))[3], 0)

    def test_admin_delete_is_denied_to_staff_even_with_delete_permission(self):
        article = self.article()
        staff = get_user_model().objects.create_user('delete-staff', password='test-password', is_staff=True)
        staff.user_permissions.set(Permission.objects.filter(content_type__app_label='sitecontent'))
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse('admin:sitecontent_article_delete', args=[article.pk])).status_code, 403)
