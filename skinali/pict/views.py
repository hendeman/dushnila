from urllib.parse import urlencode

from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotFound, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import ListView, TemplateView

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

# menu = ["Каталог скинали", "Услуги дизайнера", "Связаться с нами", "Главная страница"]
menu = [{'title': "Главная страница", 'url_name': 'home'},
        {'title': "Каталог скинали", 'url_name': 'skinali'},
        {'title': "Наши работы", 'url_name': 'finished_works'},
        {'title': "Услуги дизайнера", 'url_name': 'designer'},
        {'title': "Связаться с нами", 'url_name': 'about'}]


FAVORITES_SESSION_KEY = 'favorite_pict_ids'
CONTACT_SUCCESS_MESSAGE = 'Спасибо! Мы получили заявку и скоро свяжемся с вами'
IMAGE_PURCHASE_SUCCESS_MESSAGE = 'Спасибо! Заявка на покупку изображения принята'
CATALOG_PAGE_SIZE = 30
CONTACT_FORM_CLASSES = {
    CallbackContactForm.form_kind: CallbackContactForm,
    QuestionContactForm.form_kind: QuestionContactForm,
    EmailCommentContactForm.form_kind: EmailCommentContactForm,
    ImagePurchaseContactForm.form_kind: ImagePurchaseContactForm,
}


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
        context['menu'] = menu
        context['recent_finished_works'] = get_finished_work_gallery_queryset()[:3]
        return context


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
        route_category = self.get_route_category()
        publication_filter = Q(tags__is_published=True)
        if route_category:
            publication_filter &= Q(tags__cat=route_category)

        return TagPict.objects.annotate(
            total=Count('tags', filter=publication_filter, distinct=True)
        ).filter(total__gt=0).order_by('-total', 'tag')[:10]

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(**kwargs)
        is_search = self.is_search_requested()
        search_form = self.get_search_form()
        search_is_valid = is_search and search_form.is_valid()
        get_color = None if is_search else self.request.GET.get('color')
        route_category = self.get_route_category()
        selected_category = None if is_search else route_category
        context['title'] = 'Результаты поиска' if is_search else 'Каталог скинали'
        context['cat_name'] = selected_category or 'Каталог скинали'
        context['selected_category'] = selected_category
        context['menu'] = menu
        context['search_form'] = search_form
        context['is_search'] = is_search
        context['search_is_valid'] = search_is_valid
        context['col'] = get_color if get_color else ""
        context['color_list'] = Color.objects.none() if is_search else Color.objects.all()
        context['list_cat'] = Category.objects.none() if is_search else Category.objects.all()
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
            context['col_tag'] = f"&color={get_color}" if get_color else ""
            context['search_result_count'] = 0
            context['search_terms'] = ()

        context['col_ru'] = (
            Color.objects.filter(slug_color=context['col']).first()
            if context['col'] else ''
        )
        return context

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
        if self.request.GET.get('color'):
            return queryset.filter(color__slug_color=self.request.GET.get('color'))
        return queryset


class SkinaliSlug(SkinaliMix):

    def filter_catalog_queryset(self, queryset):
        if self.request.GET.get('color'):
            return queryset.filter(
                color__slug_color=self.request.GET.get('color'),
                cat=self.get_route_category(),
            )
        return queryset.filter(cat=self.get_route_category())


class PictTag(FavoritesContextMixin, ListView):
    template_name = 'pict/tag.html'
    paginate_by = CATALOG_PAGE_SIZE

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = TagPict.objects.get(slug=self.kwargs['tag_slug'])
        context['menu'] = menu
        return context

    def get_queryset(self):
        return Pict.objects.published().filter(
            tags__slug=self.kwargs['tag_slug'],
        )


class FinishedWorkList(FavoritesContextMixin, ListView):
    model = FinishedWork
    template_name = 'pict/finished_works.html'
    context_object_name = 'finished_works'
    paginate_by = 6

    def get_selected_category(self):
        # Категория готовой работы определяется только через связанное изображение каталога.
        if not hasattr(self, 'selected_category'):
            category_slug = self.request.GET.get('category', '').strip()
            self.selected_category = (
                get_object_or_404(Category, slug=category_slug)
                if category_slug else None
            )
        return self.selected_category

    def get_queryset(self):
        queryset = get_finished_work_gallery_queryset()
        selected_category = self.get_selected_category()
        if selected_category:
            queryset = queryset.filter(
                catalog_image__cat=selected_category,
            ).distinct()
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Наши работы'
        context['menu'] = menu
        context['categories'] = Category.objects.all()
        context['selected_category'] = self.get_selected_category()
        context['col_tag'] = (
            f'&category={context["selected_category"].slug}'
            if context['selected_category'] else ''
        )
        return context


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
    return render(request, 'pict/favorites.html', {
        'menu': menu,
        'title': 'Избранное',
        'favorite_pictures': favorite_pictures,
        'favorite_ids': valid_ids,
        'favorites_count': len(valid_ids),
    })


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


def contact_success_response(request, *, form_kind=''):
    success_message = (
        IMAGE_PURCHASE_SUCCESS_MESSAGE
        if form_kind == ContactRequest.RequestType.IMAGE_PURCHASE
        else CONTACT_SUCCESS_MESSAGE
    )
    if is_ajax_request(request):
        return JsonResponse({
            'ok': True,
            'message': success_message,
        })

    return render(request, 'pict/contact_form_result.html', {
        'menu': menu,
        'title': 'Заявка отправлена',
        'favorites_count': len(get_favorite_ids(request)),
        'submission_success': True,
        'success_message': success_message,
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
        return contact_success_response(request, form_kind=form_kind)

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
        return contact_success_response(request, form_kind=form_kind)

    if is_ajax_request(request):
        return JsonResponse({
            'ok': False,
            'errors': serialize_form_errors(form),
        }, status=422)

    return render(request, 'pict/contact_form_result.html', {
        'menu': menu,
        'title': 'Отправить заявку',
        'favorites_count': len(get_favorite_ids(request)),
        'submission_form': form,
        'form_kind': form_kind,
        'suppress_callback_dialog': True,
    }, status=422)


def about(request):
    # context = {
    #     'menu': menu,
    #     'title': 'Связаться с нами'
    # }
    favorite_ids = get_favorite_ids(request)
    return render(request, 'pict/about.html', {
        'menu': menu,
        'title': 'Связаться с нами',
        'favorites_count': len(favorite_ids),
        'question_form': QuestionContactForm(prefix='question'),
        'email_message_form': EmailCommentContactForm(prefix='email_message'),
    })


def designer(request):
    # context = {
    #     'menu': menu,
    #     'title': 'Услуги дизайнера'
    # }
    favorite_ids = get_favorite_ids(request)
    return render(request, 'pict/designer.html', {
        'menu': menu,
        'title': 'Услуги дизайнера',
        'favorites_count': len(favorite_ids),
    })


def pageNotFound(request, exception):
    return HttpResponseNotFound('<h1>Ops...Страница не найдена</h1>')

def cat(request, catid):
    return HttpResponse(f'<h1>Страница найдена {catid}</h1>')
