from django import forms

from pict.forms import PhoneContactForm
from pict.models import ContactRequest

from .models import QuizQuestion


class QuizContactForm(PhoneContactForm):
    """Контактные данные и серверно проверенные ответы текущей версии квиза."""

    form_kind = ContactRequest.RequestType.QUIZ

    def __init__(self, *args, quiz, **kwargs):
        self.quiz = quiz
        self.question_fields = []
        super().__init__(*args, **kwargs)
        self.fields['name'].label = 'Имя'
        self.fields['phone'].label = 'Телефон'

        for question in quiz.get_public_questions():
            field_name = question.field_name
            options = question.get_public_options()
            common_attrs = {
                'data-quiz-answer': True,
                'data-field-name': field_name,
            }
            if question.kind == QuizQuestion.Kind.TEXT:
                field = forms.CharField(
                    label=question.title,
                    required=question.is_required,
                    max_length=200,
                    strip=True,
                    error_messages={
                        'required': 'Введите ответ.',
                        'max_length': 'Ответ должен содержать не более 200 символов.',
                    },
                    widget=forms.TextInput(attrs={
                        **common_attrs,
                        'maxlength': 200,
                        'placeholder': question.placeholder,
                        'autocomplete': 'address-level2',
                    }),
                )
            else:
                field = forms.ChoiceField(
                    label=question.title,
                    required=question.is_required,
                    choices=[(str(option.pk), option.title) for option in options],
                    error_messages={
                        'required': 'Выберите один из вариантов.',
                        'invalid_choice': (
                            'Выбранный вариант больше не доступен. Обновите страницу.'
                        ),
                    },
                    widget=forms.RadioSelect(attrs=common_attrs),
                )
            self.fields[field_name] = field
            self.question_fields.append({
                'question': question,
                'field': self[field_name],
                'options': options,
            })

    def build_answer_snapshot(self):
        """Возвращает текстовый снимок, независимый от будущего редактирования."""
        answers = []
        for entry in self.question_fields:
            question = entry['question']
            field_name = question.field_name
            raw_value = self.cleaned_data.get(field_name, '')
            option_id = None
            if question.kind == QuizQuestion.Kind.TEXT:
                answer = raw_value or ''
            else:
                option_by_id = {
                    str(option.pk): option
                    for option in entry['options']
                }
                selected_option = option_by_id.get(str(raw_value)) if raw_value else None
                answer = selected_option.title if selected_option else ''
                option_id = selected_option.pk if selected_option else None
            answers.append({
                'question_id': question.pk,
                'question': question.title,
                'kind': question.kind,
                'option_id': option_id,
                'answer': answer,
            })
        return answers
