from django.urls import path

from .views import ArticleDetail, ArticleList


urlpatterns = [
    path('polezno-znat/', ArticleList.as_view(), name='article_list'),
    path('polezno-znat/<slug:slug>/', ArticleDetail.as_view(), name='article_detail'),
]
