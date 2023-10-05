from django.core.paginator import Paginator
from django.db.models import Count
from django.http import HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.views.generic import ListView

from .models import *

# menu = ["Каталог скинали", "Услуги дизайнера", "Связаться с нами", "Главная страница"]
menu = [{'title': "Главная страница", 'url_name': 'home'},
        {'title': "Каталог скинали", 'url_name': 'skinali'},
        {'title': "Услуги дизайнера", 'url_name': 'designer'},
        {'title': "Связаться с нами", 'url_name': 'about'}]


class PictHome(ListView):
    # model = Pict
    template_name = 'pict/index.html'
    paginate_by = 6

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(**kwargs)
        get_find = self.request.GET.get('product-number')
        if len(context['object_list']) == 0 and get_find:
            context['list_pict'] = 0
        context['title'] = 'Главная страница'
        context['menu'] = menu
        context['col_tag'] = f"&product-number={get_find}" if get_find else ""
        if context['col_tag']:
            context['get_find'] = self.request.GET.get('product-number')
        return context

    def get_queryset(self):
        if self.request.GET.get('product-number'):
            search_elem = self.request.GET.get('product-number')
            if search_elem.isdigit():
                return Pict.objects.filter(name=search_elem)
            else:
                if len(search_elem) >= 3:
                    request_cap = search_elem.lower()[:-1]
                    return Pict.objects.filter(tags__tag__contains=request_cap)
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

class SkinaliMix(ListView):
    template_name = 'pict/skinali.html'
    paginate_by = 6

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(**kwargs)
        get_color = self.request.GET.get('color')
        context['title'] = 'Каталог скинали'
        context['cat_name'] = Category.objects.get(slug=self.kwargs['slug_cat']) if self.kwargs else 'Каталог скинали'
        # context['slug_cat'] = self.kwargs['slug_cat']
        context['menu'] = menu
        context['col'] = get_color if get_color else ""
        context['col_tag'] = f"&color={get_color}" if get_color else ""
        context['color_list'] = Color.objects.all()
        context['list_cat'] = Category.objects.all()
        context['list_tag'] = TagPict.objects.annotate(total=Count("tags")).filter(total__gte=3).order_by("-total")
        try:
            context['col_ru'] = Color.objects.get(slug_color=context['col'])
        except:
            context['col_ru'] = ""
        return context


class SkinaliAll(SkinaliMix):

    def get_queryset(self):
        if self.request.GET.get('color'):
            return Pict.objects.filter(color__slug_color=self.request.GET.get('color'))
        else:
            return Pict.objects.all()

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
        if self.request.GET.get('color'):
            return Pict.objects.filter(color__slug_color=self.request.GET.get('color'), cat__slug=self.kwargs['slug_cat'])
        else:
            return Pict.objects.filter(cat__slug=self.kwargs['slug_cat'])


class PictTag(ListView):
    template_name = 'pict/tag.html'
    paginate_by = 6

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = TagPict.objects.get(slug=self.kwargs['tag_slug'])
        context['menu'] = menu
        return context

    def get_queryset(self):
        return Pict.objects.filter(tags__slug=self.kwargs['tag_slug'])

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
    return render(request, 'pict/about.html', {'menu': menu, 'title': 'Связаться с нами'})


def designer(request):
    # context = {
    #     'menu': menu,
    #     'title': 'Услуги дизайнера'
    # }
    return render(request, 'pict/designer.html', {'menu': menu, 'title': 'Услуги дизайнера'})


def pageNotFound(request, exception):
    return HttpResponseNotFound('<h1>Ops...Страница не найдена</h1>')

def cat(request, catid):
    return HttpResponse(f'<h1>Страница найдена {catid}</h1>')
