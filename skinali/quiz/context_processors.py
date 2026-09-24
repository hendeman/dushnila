from django.utils.functional import SimpleLazyObject

from .forms import QuizContactForm
from .models import Quiz


def _load_public_quiz(request):
    resolver_match = getattr(request, 'resolver_match', None)
    if resolver_match and resolver_match.namespace in {'admin', 'djdt'}:
        return None

    quiz = Quiz.objects.enabled().with_public_content().first()
    if quiz is None or not quiz.matches_path(request.path_info):
        return None
    return {
        'quiz': quiz,
        'form': QuizContactForm(quiz=quiz, prefix='quiz'),
    }


def public_quiz(request):
    """Лениво добавляет квиз: admin и шаблоны без обращения к значению не делают SQL."""
    return {
        'site_quiz': SimpleLazyObject(lambda: _load_public_quiz(request)),
    }
