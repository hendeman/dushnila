from django.urls import path
from .views import *

urlpatterns = [
    path('', PictHome.as_view(), name='home'),
    path('about/', about, name='about'),
    path('skinali/', SkinaliAll.as_view(), name='skinali'),
    path('skinali/<slug:slug_cat>/', SkinaliSlug.as_view(), name='skinali'),
    path('designer', designer, name='designer'),
    path('cats/<int:catid>/', cat, name='cat'),
    path('tag/<slug:tag_slug>/', PictTag.as_view(), name='tag')
]