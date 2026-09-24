from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction
from django.db.models import Count, F, IntegerField, Q, Value
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView, TemplateView
from sitecontent.models import SitePage

from .forms import (
    CallbackContactForm,
    CatalogSearchForm,
    EmailCommentContactForm,
    ImagePurchaseContactForm,
    QuestionContactForm,
)
from .models import *
from .search import (
    SEARCH_QUERY_PARAMETER,
    apply_catalog_search,
    format_image_count,
)
FAVORITES_SESSION_KEY = 'favorite_pict_ids'
CONTACT_SUCCESS_MESSAGE = (
    'Спасибо! Заявка отправлена.\n'
    'Скоро мы с Вами свяжемся😊'
)
CATALOG_PAGE_SIZE = 30
MAX_CATALOG_COLORS = 3
CONTACT_FORM_CLASSES = {
    CallbackContactForm.form_kind: CallbackContactForm,
    QuestionContactForm.form_kind: QuestionContactForm,
    EmailCommentContactForm.form_kind: EmailCommentContactForm,
    ImagePurchaseContactForm.form_kind: ImagePurchaseContactForm,
}


def set_page_metadata(
    context,
    request,
    *,
    page_title,
    meta_description,
    canonical_path,
    page_number=1,
    noindex=False,
    breadcrumbs=(),
):
    """Добавляет единообразные SEO-метаданные и хлебные крошки странице."""
    if page_number > 1:
        canonical_path += '?' + urlencode({'page': page_number})
    public_origin = settings.PUBLIC_SITE_ORIGIN.rstrip('/')

    # Видимые ссылки остаются относительными, а поисковые сигналы всегда указывают
    # на единственный публичный домен независимо от Host входящего запроса.
    def public_url(path):
        return f'{public_origin}/{path.lstrip("/")}'

    context['page_title'] = page_title
    context['meta_description'] = meta_description
    context['canonical_url'] = public_url(canonical_path)
    context['meta_robots'] = 'noindex,follow' if noindex else ''
    context['breadcrumbs'] = tuple(
        {
            'name': name,
            'url': path or canonical_path,
            'absolute_url': public_url(path or canonical_path),
        }
        for name, path in breadcrumbs
    )
    return context


def resolve_site_page_metadata(
    page_code,
    *,
    default_page_title,
    default_meta_description,
    page_number=1,
):
    """Подставляет управляемые SEO-поля постоянной страницы при их наличии."""
    site_page = (
        SitePage.objects
        .only('seo_title', 'seo_description')
        .filter(pk=page_code)
        .first()
    )
    if site_page is None:
        return default_page_title, default_meta_description

    custom_title = site_page.seo_title.strip()
    if custom_title:
        if page_number > 1:
            custom_title += f' — страница {page_number}'
        page_title = f'{custom_title} | ОДИУМ'
    else:
        page_title = default_page_title

    return (
        page_title,
        site_page.resolve_seo_value(
            'seo_description',
            default_meta_description,
        ),
    )


def get_favorite_ids(request):
    raw_ids = request.session.get(FAVORITES_SESSION_KEY, [])
    if not isinstance(raw_ids, (list, tuple)):
        raw_ids = []

    favorite_ids = []
    for raw_id in raw_ids:
        try:
            pict_id = int(raw_id)
        except (TypeError, ValueError):
            continue

        if pict_id > 0 and pict_id not in favorite_ids:
            favorite_ids.append(pict_id)

    # Снятые с публикации изображения не должны оставаться доступными через сессию.
    published_ids = set(
        Pict.objects.published()
        .filter(pk__in=favorite_ids)
        .values_list('pk', flat=True)
    ) if favorite_ids else set()
    favorite_ids = [pict_id for pict_id in favorite_ids if pict_id in published_ids]

    if favorite_ids != raw_ids:
        request.session[FAVORITES_SESSION_KEY] = favorite_ids

    return favorite_ids


def get_finished_work_gallery_queryset():
    # Главная и полная галерея используют одну сортировку и один JOIN для номера изображения.
    return (
        FinishedWork.objects.published()
        .select_related('catalog_image')
        .order_by('-created_at', '-id')
    )


def get_similar_picture_queryset(picture, *, limit=8):
    """Ранжирует опубликованные изображения по общим тегам и справочникам."""
    category_ids = [category.pk for category in picture.cat.all()]
    tag_ids = [tag.pk for tag in picture.tags.all()]
    color_ids = [color.pk for color in picture.color.all()]

    def match_count(relation, values):
        if not values:
            return Value(0, output_field=IntegerField())
        return Count(
            relation,
            filter=Q(**{f'{relation}__in': values}),
            distinct=True,
        )

    return (
        Pict.objects.published()
        .exclude(pk=picture.pk)
        .annotate(
            matching_tags=match_count('tags', tag_ids),
            matching_categories=match_count('cat', category_ids),
            matching_colors=match_count('color', color_ids),
        )
        .annotate(
            similarity_score=(
                F('matching_tags') * 3
                + F('matching_categories') * 2
                + F('matching_colors')
            ),
        )
        .filter(similarity_score__gt=0)
        .order_by('-similarity_score', '-updated_at', '-id')
        .prefetch_related('tags', 'cat')[:limit]
    )


class FavoritesContextMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        favorite_ids = get_favorite_ids(self.request)
        context['favorite_ids'] = favorite_ids
        context['favorites_count'] = len(favorite_ids)
        return context


class PictHome(FavoritesContextMixin, TemplateView):
    template_name = 'pict/index.html'

    def get(self, request, *args, **kwargs):
        if 'product-number' in request.GET:
            query_string = urlencode({
                SEARCH_QUERY_PARAMETER: request.GET.get('product-number', ''),
            })
            return redirect(f'{reverse("skinali")}?{query_string}')
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Главная страница'
        context['recent_finished_works'] = get_finished_work_gallery_queryset()[:3]
        page_title, meta_description = resolve_site_page_metadata(
            SitePage.Code.HOME,
            default_page_title='Скинали из стекла для кухни | ОДИУМ',
            default_meta_description=(
                'Скинали из стекла для кухни: каталог изображений, '
                'услуги дизайнера и примеры готовых работ ОДИУМ.'
            ),
        )
        return set_page_metadata(
            context,
            self.request,
            page_title=page_title,
            meta_description=meta_description,
            canonical_path=reverse('home'),
        )


class SkinaliMix(FavoritesContextMixin, ListView):
    template_name = 'pict/skinali.html'
    paginate_by = CATALOG_PAGE_SIZE

    @staticmethod
    def get_catalog_queryset():
        # Данные модальной карточки загружаются заранее и не создают N+1 запросов.
        return Pict.objects.published().prefetch_related('tags', 'cat')

    def is_search_requested(self):
        return SEARCH_QUERY_PARAMETER in self.request.GET

    def get_search_form(self):
        if not hasattr(self, 'search_form'):
            data = self.request.GET if self.is_search_requested() else None
            self.search_form = CatalogSearchForm(data=data)
        return self.search_form

    def filter_catalog_queryset(self, queryset):
        return queryset

    def get_selected_color_slugs(self):
        if not hasattr(self, 'selected_color_slugs'):
            selected_slugs = []
            for raw_slug in self.request.GET.getlist('color'):
                slug = raw_slug.strip()
                if slug and slug not in selected_slugs:
                    selected_slugs.append(slug)
                if len(selected_slugs) == MAX_CATALOG_COLORS:
                    break
            self.selected_color_slugs = tuple(selected_slugs)
        return self.selected_color_slugs

    def filter_queryset_by_selected_colors(self, queryset):
        # Последовательные M2M-фильтры создают отдельное соединение для каждого
        # цвета: изображение обязано иметь все выбранные цвета одновременно.
        for color_slug in self.get_selected_color_slugs():
            queryset = queryset.filter(color__slug_color=color_slug)
        return queryset

    @staticmethod
    def build_color_query(color_slugs):
        return urlencode([('color', color_slug) for color_slug in color_slugs])

    def build_color_url(self, color_slugs):
        color_query = self.build_color_query(color_slugs)
        return (
            f'{self.request.path}?{color_query}'
            if color_query else self.request.path
        )

    def get_route_category(self):
        category_slug = self.kwargs.get('slug_cat')
        if not category_slug:
            return None
        if not hasattr(self, 'route_category'):
            self.route_category = get_object_or_404(Category, slug=category_slug)
        return self.route_category

    def get_queryset(self):
        # URL категории остается валидируемым ресурсом даже при глобальном поиске.
        self.get_route_category()
        queryset = self.get_catalog_queryset()
        if not self.is_search_requested():
            return self.filter_catalog_queryset(queryset)

        search_form = self.get_search_form()
        if not search_form.is_valid():
            return queryset.none()
        return apply_catalog_search(queryset, search_form.parsed_query)

    def get_popular_tags(self):
        publication_filter = Q(tags__is_published=True)

        return TagPict.objects.annotate(
            total=Count('tags', filter=publication_filter, distinct=True)
        ).filter(total__gt=0).order_by('-total', 'tag')[:10]

    @staticmethod
    def get_catalog_categories():
        return Category.objects.order_by('pk')

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(**kwargs)
        is_search = self.is_search_requested()
        search_form = self.get_search_form()
        search_is_valid = is_search and search_form.is_valid()
        selected_color_slugs = (
            () if is_search else self.get_selected_color_slugs()
        )
        route_category = self.get_route_category()
        selected_category = None if is_search else route_category
        context['title'] = 'Результаты поиска' if is_search else 'Каталог скинали'
        default_catalog_heading = (
            f'Изображения для скинали: {selected_category}'
            if selected_category else 'Каталог изображений для скинали'
        )
        context['catalog_heading'] = (
            selected_category.resolve_seo_value('seo_h1', default_catalog_heading)
            if selected_category else default_catalog_heading
        )
        context['catalog_intro'] = (
            selected_category.intro_text.strip() if selected_category else ''
        )
        context['cat_name'] = selected_category or 'Каталог скинали'
        context['selected_category'] = selected_category
        context['search_form'] = search_form
        context['is_search'] = is_search
        context['search_is_valid'] = search_is_valid
        color_list = [] if is_search else list(Color.objects.all())
        color_by_slug = {color.slug_color: color for color in color_list}
        selected_colors = tuple(
            color_by_slug[color_slug]
            for color_slug in selected_color_slugs
            if color_slug in color_by_slug
        )
        selected_color_set = set(selected_color_slugs)
        color_options = []
        for color in color_list:
            is_selected = color.slug_color in selected_color_set
            if is_selected:
                target_slugs = tuple(
                    color_slug for color_slug in selected_color_slugs
                    if color_slug != color.slug_color
                )
                toggle_url = self.build_color_url(target_slugs)
                can_toggle = True
            elif len(selected_color_slugs) < MAX_CATALOG_COLORS:
                target_slugs = selected_color_slugs + (color.slug_color,)
                toggle_url = self.build_color_url(target_slugs)
                can_toggle = True
            else:
                toggle_url = ''
                can_toggle = False
            color_options.append({
                'color': color,
                'is_selected': is_selected,
                'can_toggle': can_toggle,
                'toggle_url': toggle_url,
            })

        color_query = self.build_color_query(selected_color_slugs)
        context['col'] = (
            selected_color_slugs[0] if len(selected_color_slugs) == 1 else ''
        )
        context['color_list'] = color_list
        context['color_options'] = color_options
        context['selected_color_slugs'] = selected_color_slugs
        context['selected_colors'] = selected_colors
        context['selected_color_names'] = ', '.join(
            str(color) for color in selected_colors
        )
        context['color_query'] = color_query
        context['color_reset_url'] = self.request.path
        context['max_catalog_colors'] = MAX_CATALOG_COLORS
        context['list_cat'] = (
            Category.objects.none()
            if is_search else self.get_catalog_categories()
        )
        context['list_tag'] = () if is_search else self.get_popular_tags()

        if search_is_valid:
            parsed_query = search_form.parsed_query
            context['search_query'] = self.request.GET.get(SEARCH_QUERY_PARAMETER, '')
            context['col_tag'] = '&' + urlencode({
                SEARCH_QUERY_PARAMETER: parsed_query.normalized,
            })
            context['search_result_count'] = context['paginator'].count
            context['search_result_summary'] = format_image_count(
                context['search_result_count'],
            )
            context['search_terms'] = self.get_search_term_links(parsed_query.terms)
        else:
            context['search_query'] = self.request.GET.get(SEARCH_QUERY_PARAMETER, '')
            context['col_tag'] = f'&{color_query}' if color_query else ''
            context['search_result_count'] = 0
            context['search_terms'] = ()

        context['col_ru'] = selected_colors[0] if len(selected_colors) == 1 else ''

        result_count = context['paginator'].count
        is_empty_category = bool(selected_category) and result_count == 0
        noindex = is_search or bool(selected_color_slugs) or is_empty_category
        if selected_category:
            category_name = str(selected_category)
            canonical_path = selected_category.get_absolute_url()
            page_title = selected_category.resolve_seo_value(
                'seo_title',
                default_catalog_heading,
            )
            default_meta_description = (
                f'Изображения для скинали в категории «{category_name}». '
                'Выберите подходящий вариант в каталоге ОДИУМ.'
            )
            meta_description = selected_category.resolve_seo_value(
                'seo_description',
                default_meta_description,
            )
        else:
            canonical_path = reverse('skinali')
            page_title = context['catalog_heading']
            meta_description = (
                'Каталог изображений для скинали из стекла: '
                'сюжеты по темам, категориям и цветам.'
            )

        page_number = context['page_obj'].number if not noindex else 1
        if page_number > 1:
            page_title += f' — страница {page_number}'
        full_page_title = f'{page_title} | ОДИУМ'
        if not selected_category:
            full_page_title, meta_description = resolve_site_page_metadata(
                SitePage.Code.CATALOG,
                default_page_title=full_page_title,
                default_meta_description=meta_description,
                page_number=page_number,
            )
        breadcrumbs = [
            ('Главная', reverse('home')),
            (
                'Каталог',
                None if not selected_category and not is_search else reverse('skinali'),
            ),
        ]
        if is_search:
            breadcrumbs.append(('Результаты поиска', None))
        elif selected_category:
            breadcrumbs.append((str(selected_category), None))
        return set_page_metadata(
            context,
            self.request,
            page_title=full_page_title,
            meta_description=meta_description,
            canonical_path=canonical_path,
            page_number=page_number,
            noindex=noindex,
            breadcrumbs=breadcrumbs,
        )

    @staticmethod
    def get_search_term_links(terms):
        catalog_url = reverse('skinali')
        links = []
        for index, term in enumerate(terms):
            remaining_terms = terms[:index] + terms[index + 1:]
            remove_url = catalog_url
            if remaining_terms:
                remove_url += '?' + urlencode({
                    SEARCH_QUERY_PARAMETER: ' '.join(remaining_terms),
                })
            links.append({'label': term, 'remove_url': remove_url})
        return links


class SkinaliAll(SkinaliMix):

    def filter_catalog_queryset(self, queryset):
        return self.filter_queryset_by_selected_colors(queryset)


class PictDetail(FavoritesContextMixin, DetailView):
    model = Pict
    template_name = 'pict/pict_detail.html'
    context_object_name = 'picture'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def get_queryset(self):
        return Pict.objects.published().prefetch_related('cat', 'tags', 'color')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        picture = self.object
        context['title'] = picture.get_page_heading()
        context['page_description'] = picture.get_page_description()
        context['similar_pictures'] = get_similar_picture_queryset(picture)
        context['absolute_photo_url'] = (
            f'{settings.PUBLIC_SITE_ORIGIN.rstrip("/")}/'
            f'{picture.photo.url.lstrip("/")}'
        )
        return set_page_metadata(
            context,
            self.request,
            page_title=picture.get_page_title(),
            meta_description=picture.get_meta_description(),
            canonical_path=picture.get_absolute_url(),
            breadcrumbs=(
                ('Главная', reverse('home')),
                ('Каталог', reverse('skinali')),
                (f'Изображение №{picture.name}', None),
            ),
        )


class SkinaliSlug(SkinaliMix):

    def filter_catalog_queryset(self, queryset):
        queryset = queryset.filter(cat=self.get_route_category())
        return self.filter_queryset_by_selected_colors(queryset)


class PictTag(FavoritesContextMixin, ListView):
    template_name = 'pict/tag.html'
    paginate_by = CATALOG_PAGE_SIZE

    def get_tag(self):
        if not hasattr(self, 'tag'):
            self.tag = get_object_or_404(
                TagPict,
                slug=self.kwargs['tag_slug'],
            )
        return self.tag

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(**kwargs)
        tag = self.get_tag()
        result_count = context['paginator'].count
        page_number = context['page_obj'].number
        page_suffix = f' — страница {page_number}' if page_number > 1 else ''

        default_heading = f'Изображения с тегом «{tag.tag}»'
        default_page_title = f'Изображения для скинали: {tag.tag}'
        default_meta_description = (
            f'{format_image_count(result_count)} для скинали '
            f'по теме «{tag.tag}». '
            'Выберите подходящий вариант из каталога ОДИУМ.'
        )
        context['title'] = tag.resolve_seo_value('seo_h1', default_heading)
        context['tag'] = tag
        context['tag_intro'] = tag.intro_text.strip()
        context['result_count'] = result_count
        context['result_summary'] = format_image_count(result_count)
        return set_page_metadata(
            context,
            self.request,
            page_title=(
                f'{tag.resolve_seo_value("seo_title", default_page_title)}'
                f'{page_suffix} | ОДИУМ'
            ),
            meta_description=tag.resolve_seo_value(
                'seo_description',
                default_meta_description,
            ),
            canonical_path=tag.get_absolute_url(),
            page_number=page_number,
            noindex=result_count == 0,
            breadcrumbs=(
                ('Главная', reverse('home')),
                ('Каталог', reverse('skinali')),
                (tag.tag, None),
            ),
        )

    def get_queryset(self):
        return Pict.objects.published().filter(
            tags=self.get_tag(),
        ).prefetch_related(
            'tags',
            'cat',
        )


class FinishedWorkList(FavoritesContextMixin, ListView):
    model = FinishedWork
    template_name = 'pict/finished_works.html'
    context_object_name = 'finished_works'
    paginate_by = 6

    def get_selected_skinali_type(self):
        if not hasattr(self, 'selected_skinali_type'):
            selected_type = self.request.GET.get(
                'skinali_type',
                FinishedWork.SkinaliType.PRINT,
            ).strip() or FinishedWork.SkinaliType.PRINT
            valid_types = {
                value for value, _label in FinishedWork.SkinaliType.choices
            }
            if selected_type not in valid_types:
                raise Http404('Неизвестный тип скинали')
            self.selected_skinali_type = selected_type
        return self.selected_skinali_type

    def get_selected_category(self):
        # Категория готовой работы определяется только через связанное изображение каталога.
        if not hasattr(self, 'selected_category'):
            category_slug = (
                self.request.GET.get('category', '').strip()
                if self.get_selected_skinali_type()
                == FinishedWork.SkinaliType.PRINT
                else ''
            )
            self.selected_category = (
                get_object_or_404(Category, slug=category_slug)
                if category_slug else None
            )
        return self.selected_category

    def get_queryset(self):
        queryset = get_finished_work_gallery_queryset().filter(
            skinali_type=self.get_selected_skinali_type(),
        )
        selected_category = self.get_selected_category()
        if selected_category:
            queryset = queryset.filter(
                catalog_image__cat=selected_category,
            ).distinct()
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_skinali_type = self.get_selected_skinali_type()
        show_categories = (
            selected_skinali_type == FinishedWork.SkinaliType.PRINT
        )
        context['title'] = 'Наши работы'
        context['selected_skinali_type'] = selected_skinali_type
        context['skinali_type_options'] = tuple(
            {
                'value': value,
                'label': label,
                'url': (
                    reverse('finished_works')
                    if value == FinishedWork.SkinaliType.PRINT
                    else (
                        f'{reverse("finished_works")}?'
                        f'{urlencode({"skinali_type": value})}'
                    )
                ),
            }
            for value, label in FinishedWork.SkinaliType.choices
        )
        context['show_finished_work_categories'] = show_categories
        context['categories'] = Category.objects.all() if show_categories else ()
        context['selected_category'] = self.get_selected_category()
        if context['selected_category']:
            context['col_tag'] = (
                f'&category={context["selected_category"].slug}'
            )
        elif not show_categories:
            context['col_tag'] = (
                f'&{urlencode({"skinali_type": selected_skinali_type})}'
            )
        else:
            context['col_tag'] = ''
        page_number = context['page_obj'].number
        is_filtered = (
            context['selected_category'] is not None or not show_categories
        )
        canonical_page = 1 if is_filtered else page_number
        page_suffix = (
            f' — страница {canonical_page}'
            if canonical_page > 1 else ''
        )
        breadcrumbs = [
            ('Главная', reverse('home')),
            (
                'Наши работы',
                reverse('finished_works') if is_filtered else None,
            ),
        ]
        if context['selected_category']:
            breadcrumbs.append((str(context['selected_category']), None))
        elif not show_categories:
            skinali_type_labels = dict(FinishedWork.SkinaliType.choices)
            breadcrumbs.append(
                (skinali_type_labels[selected_skinali_type], None)
            )
        page_title, meta_description = resolve_site_page_metadata(
            SitePage.Code.FINISHED_WORKS,
            default_page_title=(
                f'Фото скинали из стекла — наши работы{page_suffix} | ОДИУМ'
            ),
            default_meta_description=(
                'Фотографии готовых скинали из стекла и примеры '
                'реализованных кухонных проектов ОДИУМ.'
            ),
            page_number=canonical_page,
        )
        return set_page_metadata(
            context,
            self.request,
            page_title=page_title,
            meta_description=meta_description,
            canonical_path=reverse('finished_works'),
            page_number=canonical_page,
            noindex=is_filtered,
            breadcrumbs=breadcrumbs,
        )


def favorites(request):
    favorite_ids = get_favorite_ids(request)
    # Общая с каталогом модальная карточка использует теги и категории.
    pictures_by_id = (
        Pict.objects.published()
        .prefetch_related('tags', 'cat')
        .in_bulk(favorite_ids)
    )
    valid_ids = [pict_id for pict_id in favorite_ids if pict_id in pictures_by_id]

    if valid_ids != favorite_ids:
        request.session[FAVORITES_SESSION_KEY] = valid_ids

    favorite_pictures = [pictures_by_id[pict_id] for pict_id in reversed(valid_ids)]
    context = {
        'title': 'Избранное',
        'favorite_pictures': favorite_pictures,
        'favorite_ids': valid_ids,
        'favorites_count': len(valid_ids),
    }
    set_page_metadata(
        context,
        request,
        page_title='Избранные изображения для скинали | ОДИУМ',
        meta_description='Изображения для скинали, сохранённые в избранном.',
        canonical_path=reverse('favorites'),
        noindex=True,
        breadcrumbs=(
            ('Главная', reverse('home')),
            ('Избранное', None),
        ),
    )
    return render(request, 'pict/favorites.html', context)


@require_POST
def toggle_favorite(request, pict_id):
    get_object_or_404(Pict.objects.published(), pk=pict_id)
    favorite_ids = get_favorite_ids(request)

    if pict_id in favorite_ids:
        favorite_ids.remove(pict_id)
        is_favorite = False
    else:
        favorite_ids.append(pict_id)
        is_favorite = True

    request.session[FAVORITES_SESSION_KEY] = favorite_ids
    return JsonResponse({
        'pict_id': pict_id,
        'is_favorite': is_favorite,
        'favorites_count': len(favorite_ids),
    })


def is_ajax_request(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'


def serialize_form_errors(form):
    return {
        field_name: [error['message'] for error in errors]
        for field_name, errors in form.errors.get_json_data(escape_html=True).items()
    }


def contact_success_response(request):
    if is_ajax_request(request):
        return JsonResponse({
            'ok': True,
            'message': CONTACT_SUCCESS_MESSAGE,
        })

    return render(request, 'pict/contact_form_result.html', {
        'title': 'Заявка отправлена',
        'favorites_count': len(get_favorite_ids(request)),
        'submission_success': True,
        'success_message': CONTACT_SUCCESS_MESSAGE,
        'suppress_callback_dialog': True,
    })


@require_POST
def submit_contact_form(request):
    form_kind = request.POST.get('form_kind', '')
    form_class = CONTACT_FORM_CLASSES.get(form_kind)
    if form_class is None:
        if is_ajax_request(request):
            return JsonResponse({
                'ok': False,
                'errors': {'__all__': ['Не удалось определить тип формы.']},
            }, status=400)
        return HttpResponseBadRequest('Не удалось определить тип формы.')

    form = form_class(request.POST, prefix=form_kind)

    # Для honeypot и подозрительного возраста ответ не отличается от успешного.
    if form.is_suspicious_submission():
        return contact_success_response(request)

    if form.is_valid():
        # Сначала надежно фиксируем заявку; внешняя доставка будет отдельным сервисом.
        with transaction.atomic():
            contact_request = ContactRequest.objects.create(
                request_type=form_kind,
                name=form.cleaned_data['name'],
                phone=form.cleaned_data.get('phone', ''),
                email=form.cleaned_data.get('email', ''),
                question=form.cleaned_data.get('question', ''),
                comment=form.cleaned_data.get('comment', ''),
                catalog_image=getattr(form, 'catalog_image', None),
                image_number=(
                    form.catalog_image.name
                    if getattr(form, 'catalog_image', None)
                    else None
                ),
            )
            ContactRequestDelivery.objects.create(
                contact_request=contact_request,
                channel=ContactRequestDelivery.Channel.TELEGRAM,
            )
        return contact_success_response(request)

    if is_ajax_request(request):
        return JsonResponse({
            'ok': False,
            'errors': serialize_form_errors(form),
        }, status=422)

    return render(request, 'pict/contact_form_result.html', {
        'title': 'Отправить заявку',
        'favorites_count': len(get_favorite_ids(request)),
        'submission_form': form,
        'form_kind': form_kind,
        'suppress_callback_dialog': True,
    }, status=422)


def about(request):
    favorite_ids = get_favorite_ids(request)
    context = {
        'title': 'Связаться с нами',
        'favorites_count': len(favorite_ids),
        'question_form': QuestionContactForm(prefix='question'),
        'email_message_form': EmailCommentContactForm(prefix='email_message'),
    }
    page_title, meta_description = resolve_site_page_metadata(
        SitePage.Code.ABOUT,
        default_page_title='Контакты ОДИУМ — заказать скинали из стекла',
        default_meta_description=(
            'Свяжитесь с ОДИУМ, чтобы заказать скинали из стекла, '
            'задать вопрос или обсудить изображение.'
        ),
    )
    set_page_metadata(
        context,
        request,
        page_title=page_title,
        meta_description=meta_description,
        canonical_path=reverse('about'),
        breadcrumbs=(
            ('Главная', reverse('home')),
            ('Связаться с нами', None),
        ),
    )
    return render(request, 'pict/about.html', context)


def designer(request):
    favorite_ids = get_favorite_ids(request)
    context = {
        'title': 'Услуги дизайнера',
        'favorites_count': len(favorite_ids),
    }
    page_title, meta_description = resolve_site_page_metadata(
        SitePage.Code.DESIGNER,
        default_page_title='Услуги дизайнера для скинали | ОДИУМ',
        default_meta_description=(
            'Подготовка изображения и индивидуальный дизайн '
            'для скинали из стекла от ОДИУМ.'
        ),
    )
    set_page_metadata(
        context,
        request,
        page_title=page_title,
        meta_description=meta_description,
        canonical_path=reverse('designer'),
        breadcrumbs=(
            ('Главная', reverse('home')),
            ('Услуги дизайнера', None),
        ),
    )
    return render(request, 'pict/designer.html', context)


def render_error_page(template_name, *, status, page_title, meta_robots):
    """Рендерит страницу ошибки без context processors и обращений к БД."""
    content = render_to_string(
        template_name,
        {
            'page_title': page_title,
            'meta_robots': meta_robots,
            'site_identity': settings.SITE_IDENTITY,
        },
    )
    return HttpResponse(content, status=status)


def pageNotFound(request, exception):
    return render_error_page(
        'pict/404.html',
        status=404,
        page_title='Страница не найдена | ОДИУМ',
        meta_robots='noindex,follow',
    )


def serverError(request):
    return render_error_page(
        'pict/500.html',
        status=500,
        page_title='Ошибка сервера | ОДИУМ',
        meta_robots='noindex,nofollow',
    )
