from django.urls import path

from .views import price, share_calculation


urlpatterns = [
    path('price/', price, name='price'),
    path('price/share/', share_calculation, name='price_share'),
]
