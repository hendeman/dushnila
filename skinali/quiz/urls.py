from django.urls import path

from .views import submit_quiz


app_name = 'quiz'

urlpatterns = [
    path('<slug:trigger_key>/submit/', submit_quiz, name='submit'),
]
