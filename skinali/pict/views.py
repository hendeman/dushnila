from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotFound, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from .forms import (
    CallbackContactForm,
    EmailCommentContactForm,
    ImagePurchaseContactForm,
    QuestionContactForm,
)
from .models import *

# menu = ["Каталог скинали", "Услуги дизайнера", "Связаться с нами", "Главная страница"]
menu = [{'title': "Главная страница", 'url_name': 'home'},
        {'title': "Каталог скинали", 'url_name': 'skinali'},
        {'title': "Наши работы", 'url_name': 'finished_works'},
        {'title': "Услуги дизайнера", 'url_name': 'designer'},
        {'title': "Связаться с нами", 'url_name': 'about'}]


FAVORITES_SESSION_KEY = 'favorite_pict_ids'
CONTACT_SUCCESS_MESSAGE = 'Спасибо! Мы получили заявку и скоро свяжемся с вами'
IMAGE_PURCHASE_SUCCESS_MESSAGE = 'Спасибо! Заявка на покупку изображения принята'
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


class PictHome(FavoritesContextMixin, ListView):
    # model = Pict
    template_name = 'pict/index.html'
    paginate_by = 6

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(**kwargs)
        get_find = self.request.GET.get('product-number')
        if len(context['object_list']) == 0 and get_find:
            context['list_pict'] = 0
        context['title'] = 'Результаты поиска' if get_find else 'Главная страница'
        context['menu'] = menu
        context['col_tag'] = f"&product-number={get_find}" if get_find else ""
        if context['col_tag']:
            context['get_find'] = self.request.GET.get('product-number')
        else:
            context['recent_finished_works'] = get_finished_work_gallery_queryset()[:3]
        return context

    def get_queryset(self):
        if self.request.GET.get('product-number'):
            search_elem = self.request.GET.get('product-number')
            if search_elem.isdigit():
                return Pict.objects.published().filter(name=search_elem)
            else:
                if len(search_elem) >= 3:
                    request_cap = search_elem.lower()[:-1]
                    return Pict.objects.published().filter(tags__tag__contains=request_cap)
                # Короткий текстовый запрос показывает обычную пустую выдачу.
                return Pict.objects.none()
        else:
            return ""


# def index(request):
#     if request.GET.get('product-number'):
#         search_elem = request.GET.get('product-number')
#         if search_elem.isdigit():
#             list_cat = Pict.objects.filter(name=search_elem)
#         else:
#             if len(search_elem) >= 3:
#                 request_cap = search_elem.capitalize()[:-1]
#                 list_cat = Pict.objects.filter(title__startswith=request_cap)
#             else:
#                 list_cat = ""
#         list_cat = 0 if len(list_cat) == 0 else list_cat
#         return render(request, 'pict/index.html', {'menu': menu, 'title': 'Главная страница', 'list_cat': list_cat})
#     return render(request, 'pict/index.html', {'menu': menu, 'title': 'Главная страница'})

class SkinaliMix(FavoritesContextMixin, ListView):
    template_name = 'pict/skinali.html'
    paginate_by = 6

    @staticmethod
    def get_catalog_queryset():
        # Данные модальной карточки загружаются заранее и не создают N+1 запросов.
        return Pict.objects.published().prefetch_related('tags', 'cat')

    def get_popular_tags(self):
        category_slug = self.kwargs.get('slug_cat')
        publication_filter = Q(tags__is_published=True)
        if category_slug:
            publication_filter &= Q(tags__cat__slug=category_slug)

        return TagPict.objects.annotate(
            total=Count('tags', filter=publication_filter, distinct=True)
        ).filter(total__gt=0).order_by('-total', 'tag')[:10]

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(**kwargs)
        get_color = self.request.GET.get('color')
        selected_category = (
            Category.objects.get(slug=self.kwargs['slug_cat'])
            if self.kwargs else None
        )
        context['title'] = 'Каталог скинали'
        context['cat_name'] = selected_category or 'Каталог скинали'
        context['selected_category'] = selected_category
        # context['slug_cat'] = self.kwargs['slug_cat']
        context['menu'] = menu
        context['col'] = get_color if get_color else ""
        context['col_tag'] = f"&color={get_color}" if get_color else ""
        context['color_list'] = Color.objects.all()
        context['list_cat'] = Category.objects.all()
        context['list_tag'] = self.get_popular_tags()
        try:
            context['col_ru'] = Color.objects.get(slug_color=context['col'])
        except:
            context['col_ru'] = ""
        return context


class SkinaliAll(SkinaliMix):

    def get_queryset(self):
        queryset = self.get_catalog_queryset()
        if self.request.GET.get('color'):
            return queryset.filter(color__slug_color=self.request.GET.get('color'))
        else:
            return queryset

# def skinaliall(request):
#
#     list_cat = Category.objects.all()
#     col = col_tag = col_ru = ""
#     cat_name = "Каталог скинали"
#     if request.GET.get('color'):
#         col = request.GET.get('color')
#         col_tag = f"&color={request.GET.get('color')}"
#         try:
#             col_ru = Color.objects.get(slug_color=col)
#             list_pict = Pict.objects.filter(color__slug_color=col)
#         except:
#             list_pict = Pict.objects.all()
#     else:
#         list_pict = Pict.objects.all()
#
#     color_list = Color.objects.all()
#     paginator = Paginator(list_pict, 6)
#
#     page_number = request.GET.get('page')
#     page_obj = paginator.get_page(page_number)
#     return render(request, 'pict/skinali.html', {'page_obj': page_obj,
#                                                  'list_pict': list_pict,
#                                                  'menu': menu,
#                                                  'title': 'Каталог скинали',
#                                                  'list_cat': list_cat,
#                                                  'color_list': color_list,
#                                                  'col_tag': col_tag,
#                                                  'col': col,
#                                                  'col_ru': col_ru,
#                                                  'cat_name': cat_name})


class SkinaliSlug(SkinaliMix):

    def get_queryset(self):
        queryset = self.get_catalog_queryset()
        if self.request.GET.get('color'):
            return queryset.filter(color__slug_color=self.request.GET.get('color'), cat__slug=self.kwargs['slug_cat'])
        else:
            return queryset.filter(cat__slug=self.kwargs['slug_cat'])


class PictTag(FavoritesContextMixin, ListView):
    template_name = 'pict/tag.html'
    paginate_by = 6

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = TagPict.objects.get(slug=self.kwargs['tag_slug'])
        context['menu'] = menu
        return context

    def get_queryset(self):
        return Pict.objects.published().filter(tags__slug=self.kwargs['tag_slug'])


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

# def skinali(request, slug_cat):
#     cat_name = Category.objects.get(slug=slug_cat)
#     # list_pict = cat_name.pict_set.all()
#     col = col_tag = col_ru = ""
#     if request.GET.get('color'):
#         col_tag = f"&color={request.GET.get('color')}"
#         col = request.GET.get('color')
#         try:
#             col_ru = Color.objects.get(slug_color=col)
#             list_pict = Pict.objects.filter(color__slug_color=col, cat__slug=slug_cat)
#         except:
#             list_pict = Pict.objects.filter(cat__slug=slug_cat)
#     else:
#         list_pict = Pict.objects.filter(cat__slug=slug_cat)
#
#     color_list = Color.objects.all()
#
#     list_cat = Category.objects.all()
#     paginator = Paginator(list_pict, 6)
#
#     page_number = request.GET.get('page')
#     page_obj = paginator.get_page(page_number)
#     return render(request, 'pict/skinali.html', {'page_obj': page_obj,
#                                                  'list_pict': list_pict,
#                                                  'menu': menu,
#                                                  'title': 'Каталог скинали',
#                                                  'list_cat': list_cat,
#                                                  'cat_name': cat_name,
#                                                  'color_list': color_list,
#                                                  'col_tag': col_tag,
#                                                  'col': col,
#                                                  'col_ru': col_ru})


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
