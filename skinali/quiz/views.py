from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from pict.models import ContactRequest, ContactRequestDelivery

from .forms import QuizContactForm
from .models import Quiz, QuizSubmission


def serialize_form_errors(form):
    return {
        field_name: [error['message'] for error in errors]
        for field_name, errors in form.errors.get_json_data(escape_html=True).items()
    }


def success_response(quiz):
    return JsonResponse({
        'ok': True,
        'title': quiz.success_title,
        'message': quiz.success_text,
        'extra': quiz.success_extra,
    })


@require_POST
def submit_quiz(request, trigger_key):
    quiz = get_object_or_404(
        Quiz.objects.enabled().with_public_content(),
        trigger_key=trigger_key,
    )
    form = QuizContactForm(request.POST, quiz=quiz, prefix='quiz')

    # Подозрительный запрос не получает подсказку о срабатывании антиспама.
    if form.is_suspicious_submission():
        return success_response(quiz)

    if not form.is_valid():
        return JsonResponse({
            'ok': False,
            'errors': serialize_form_errors(form),
        }, status=422)

    with transaction.atomic():
        contact_request = ContactRequest.objects.create(
            request_type=ContactRequest.RequestType.QUIZ,
            name=form.cleaned_data['name'],
            phone=form.cleaned_data['phone'],
        )
        QuizSubmission.objects.create(
            quiz=quiz,
            contact_request=contact_request,
            answers=form.build_answer_snapshot(),
        )
        ContactRequestDelivery.objects.create(
            contact_request=contact_request,
            channel=ContactRequestDelivery.Channel.TELEGRAM,
        )
    return success_response(quiz)
