from html import escape
from django.utils import timezone
from pict.models import ContactRequest


TELEGRAM_REQUEST_ICON_BY_TYPE = {
    ContactRequest.RequestType.CALLBACK: '📌',
    ContactRequest.RequestType.QUESTION: '❔',
    ContactRequest.RequestType.EMAIL_MESSAGE: '✉',
    ContactRequest.RequestType.IMAGE_PURCHASE: '💲',
    ContactRequest.RequestType.QUIZ: '📋',
}


def format_contact_request_message(contact_request):
    created_at = timezone.localtime(contact_request.created_at)
    request_icon = TELEGRAM_REQUEST_ICON_BY_TYPE.get(
        contact_request.request_type,
        '📨',
    )
    request_type = escape(contact_request.get_request_type_display(), quote=False)
    lines = [
        f'{request_icon} <b>Новая заявка №{contact_request.pk}</b>',
        f'— <b><i>{request_type}</i></b> —',
        '',
        f'👤 {escape(contact_request.name, quote=False)}',
    ]
    if contact_request.phone:
        lines.append(f'📞 {escape(contact_request.phone, quote=False)}')
    if contact_request.email:
        lines.append(f'✉ {escape(contact_request.email, quote=False)}')
    if contact_request.question:
        lines.append(f'❔ {escape(contact_request.question, quote=False)}')
    if contact_request.comment:
        lines.append(f'💬 {escape(contact_request.comment, quote=False)}')
    if contact_request.image_number is not None:
        lines.append(f'🖼 №{contact_request.image_number}')
    quiz_submission = getattr(contact_request, 'quiz_submission', None)
    if quiz_submission is not None:
        lines.extend(('', '<b>Ответы квиза:</b>'))
        for number, answer in enumerate(quiz_submission.answers, start=1):
            question = escape(str(answer.get('question', 'Вопрос')), quote=False)
            value = escape(str(answer.get('answer') or 'Не указано'), quote=False)
            lines.append(f'{number}. <b>{question}</b>')
            lines.append(value)
    lines.append(f'🕒 {created_at:%d.%m.%Y %H:%M}')
    return '\n'.join(lines)
