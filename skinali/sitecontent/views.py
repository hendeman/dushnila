from django.urls import reverse
from django.utils.safestring import mark_safe
from django.views.generic import DetailView, ListView

from pict.views import FavoritesContextMixin, resolve_site_page_metadata, set_page_metadata

from .models import Article, SitePage
from .rich_text import sanitize_article_html


class ArticleList(FavoritesContextMixin, ListView):
    model = Article
    context_object_name = 'articles'
    template_name = 'sitecontent/article_list.html'
    paginate_by = 7
    http_method_names = ['get', 'head', 'options']

    def get_queryset(self):
        return Article.objects.published().defer('body')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Полезно знать'
        number = context['page_obj'].number
        default_title = 'Полезно знать'
        if number > 1:
            default_title += f' — страница {number}'
        page_title, description = resolve_site_page_metadata(
            SitePage.Code.ARTICLES, default_page_title=f'{default_title} | ОДИУМ',
            default_meta_description='Полезные статьи о выборе, оформлении и уходе за скинали из стекла.',
            page_number=number,
        )
        return set_page_metadata(
            context, self.request, page_title=page_title, meta_description=description,
            canonical_path=reverse('article_list'), page_number=number,
            breadcrumbs=(('Главная', reverse('home')), ('Полезно знать', '')),
        )


class ArticleDetail(FavoritesContextMixin, DetailView):
    model = Article
    context_object_name = 'article'
    template_name = 'sitecontent/article_detail.html'
    http_method_names = ['get', 'head', 'options']

    def get_queryset(self):
        return Article.objects.published()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        article = self.object
        context['title'] = article.title
        # Повторная очистка защищает вывод также от ручных SQL/QuerySet.update правок.
        context['article_html'] = mark_safe(sanitize_article_html(article.body))
        return set_page_metadata(
            context, self.request,
            page_title=f'{article.resolve_seo_value("seo_title", article.title)} | ОДИУМ',
            meta_description=article.resolve_seo_value('seo_description', article.summary),
            canonical_path=article.get_absolute_url(),
            breadcrumbs=(('Главная', reverse('home')), ('Полезно знать', reverse('article_list')),
                         (article.title, '')),
        )
