import time
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.core import signing
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from pict.admin import ContactRequestAdmin
from pict.forms import CONTACT_FORM_TOKEN_SALT, PhoneContactForm
from pict.models import ContactRequest, ContactRequestDelivery
from pict.services.contact_delivery import format_contact_request_message

from .admin import QuizAdmin
from .context_processors import _load_public_quiz
from .forms import QuizContactForm
from .models import Quiz, QuizOption, QuizQuestion, QuizSubmission


class SeededQuizTests(TestCase):
    def test_migration_seeds_complete_leadforms_content_and_settings(self):
        quiz = Quiz.objects.get(trigger_key='skinali-quiz')
        questions = list(quiz.questions.prefetch_related('options'))

        self.assertTrue(quiz.is_enabled)
        self.assertEqual(quiz.trigger_hash, '#popup:skinali-quiz')
        self.assertEqual(quiz.auto_open_delay_seconds, 10)
        self.assertEqual(quiz.repeat_after_days, 3)
        self.assertTrue(quiz.restart_on_close)
        self.assertEqual(len(questions), 6)
        self.assertEqual(sum(question.options.count() for question in questions), 23)
        self.assertEqual(questions[0].title, 'Какая планировка у Вашей кухни:')
        self.assertEqual(questions[2].kind, QuizQuestion.Kind.TEXT)
        self.assertFalse(questions[2].is_required)
        self.assertFalse(questions[5].is_required)
        self.assertEqual(
            questions[5].options.order_by('position').first().title,
            'Часы под цвет скинали',
        )

    def test_all_bundled_images_exist_in_static_source(self):
        image_paths = QuizOption.objects.exclude(bundled_image='').values_list(
            'bundled_image',
            flat=True,
        )
        self.assertEqual(len(image_paths), 13)
        for image_path in image_paths:
            with self.subTest(image_path=image_path):
                self.assertTrue(
                    Path(settings.BASE_DIR, 'quiz/static', image_path).is_file()
                )


class QuizModelTests(TestCase):
    def setUp(self):
        self.quiz = Quiz.objects.get(trigger_key='skinali-quiz')

    def test_page_paths_are_normalized_and_matched_exactly(self):
        self.quiz.page_paths = ' /about/\n/about/\n/skinali/ '
        self.quiz.full_clean()

        self.assertEqual(self.quiz.page_paths, '/about/\n/skinali/')
        self.assertTrue(self.quiz.matches_path('/about/'))
        self.assertFalse(self.quiz.matches_path('/about'))

    def test_page_paths_reject_domains_parameters_fragments_and_masks(self):
        for path in (
            'https://example.com/',
            '//example.com/',
            '/about/?q=1',
            '/about/#contacts',
            '/skinali/*',
            '/bad path',
        ):
            with self.subTest(path=path):
                self.quiz.page_paths = path
                with self.assertRaises(ValidationError):
                    self.quiz.full_clean()

    def test_admin_allows_only_one_quiz_and_protects_it_from_deletion(self):
        quiz_admin = QuizAdmin(Quiz, AdminSite())

        self.assertFalse(quiz_admin.has_add_permission(None))
        self.assertFalse(quiz_admin.has_delete_permission(None, self.quiz))


class QuizRenderingTests(TestCase):
    def setUp(self):
        self.quiz = Quiz.objects.get(trigger_key='skinali-quiz')

    def test_public_page_contains_native_dialog_launcher_and_all_questions(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="site-quiz-dialog"')
        self.assertContains(response, 'data-trigger-hash="#popup:skinali-quiz"')
        self.assertContains(response, 'data-auto-open-delay="10"')
        self.assertContains(response, 'data-repeat-days="3"')
        self.assertContains(response, '/static/quiz/css/quiz.css')
        self.assertContains(response, '/static/quiz/js/quiz.js')
        self.assertContains(response, 'Какая планировка у Вашей кухни:')
        self.assertContains(response, 'Укажите ваш город')
        self.assertContains(response, 'Выберите Ваш подарок!')
        self.assertContains(response, '/static/quiz/images/answers/layout-straight.jpg')
        self.assertNotContains(response, 'обработку персональных данных')
        self.assertNotContains(response, 'leadforms.ru')

    def test_disabled_or_path_scoped_quiz_is_not_rendered_outside_scope(self):
        self.quiz.page_paths = '/about/'
        self.quiz.save(update_fields=['page_paths'])

        self.assertNotContains(self.client.get(reverse('home')), 'data-site-quiz')
        self.assertContains(self.client.get(reverse('about')), 'data-site-quiz')

        self.quiz.is_enabled = False
        self.quiz.save(update_fields=['is_enabled'])
        self.assertNotContains(self.client.get(reverse('about')), 'data-site-quiz')

    def test_context_loader_uses_three_queries_for_full_quiz(self):
        request = RequestFactory().get('/')

        with self.assertNumQueries(3):
            context = _load_public_quiz(request)

        self.assertEqual(context['quiz'], self.quiz)
        self.assertEqual(len(context['form'].question_fields), 6)


class QuizSubmissionTests(TestCase):
    def setUp(self):
        self.quiz = Quiz.objects.enabled().with_public_content().get(
            trigger_key='skinali-quiz'
        )

    @staticmethod
    def create_token(age_seconds=3):
        return signing.dumps(
            {'issued_at': time.time() - age_seconds},
            salt=CONTACT_FORM_TOKEN_SALT,
            compress=True,
        )

    def valid_data(self, **overrides):
        data = {
            'quiz-name': 'Анна-Мария',
            'quiz-phone': '+375 (29) 123-45-67',
            'quiz-website': '',
            'quiz-form_token': self.create_token(),
        }
        for question in self.quiz.get_public_questions():
            if question.kind == QuizQuestion.Kind.TEXT:
                data[f'quiz-{question.field_name}'] = 'Жодино'
            else:
                data[f'quiz-{question.field_name}'] = str(
                    question.get_public_options()[0].pk
                )
        data.update(overrides)
        return data

    def test_quiz_form_reuses_phone_contact_validation(self):
        self.assertTrue(issubclass(QuizContactForm, PhoneContactForm))
        form = QuizContactForm(quiz=self.quiz, prefix='quiz')

        self.assertEqual(form.form_kind, ContactRequest.RequestType.QUIZ)
        self.assertEqual(len(form.question_fields), 6)
        self.assertEqual(form.fields['name'].label, 'Имя')
        self.assertEqual(form.fields['phone'].label, 'Телефон')

    def test_valid_post_creates_quiz_request_snapshot_and_delivery(self):
        response = self.client.post(
            reverse('quiz:submit', args=[self.quiz.trigger_key]),
            self.valid_data(),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        contact_request = ContactRequest.objects.get()
        self.assertEqual(contact_request.request_type, ContactRequest.RequestType.QUIZ)
        self.assertEqual(contact_request.name, 'Анна-Мария')
        self.assertEqual(contact_request.phone, '+375 (29) 123-45-67')
        submission = QuizSubmission.objects.get(contact_request=contact_request)
        self.assertEqual(len(submission.answers), 6)
        self.assertEqual(submission.answers[0]['question'], 'Какая планировка у Вашей кухни:')
        self.assertEqual(submission.answers[0]['answer'], 'прямая')
        self.assertEqual(submission.answers[2]['answer'], 'Жодино')
        delivery = contact_request.deliveries.get()
        self.assertEqual(delivery.channel, ContactRequestDelivery.Channel.TELEGRAM)
        self.assertEqual(delivery.status, ContactRequestDelivery.Status.PENDING)

    def test_optional_city_and_gift_may_be_skipped_but_remain_in_snapshot(self):
        city, gift = self.quiz.get_public_questions()[2], self.quiz.get_public_questions()[5]
        data = self.valid_data()
        data.pop(f'quiz-{city.field_name}')
        data.pop(f'quiz-{gift.field_name}')

        response = self.client.post(
            reverse('quiz:submit', args=[self.quiz.trigger_key]),
            data,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        answers = QuizSubmission.objects.get().answers
        self.assertEqual(answers[2]['answer'], '')
        self.assertEqual(answers[5]['answer'], '')

    def test_required_missing_and_tampered_answers_are_rejected(self):
        first_question = self.quiz.get_public_questions()[0]
        missing_data = self.valid_data()
        missing_data.pop(f'quiz-{first_question.field_name}')
        missing_response = self.client.post(
            reverse('quiz:submit', args=[self.quiz.trigger_key]),
            missing_data,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        tampered_response = self.client.post(
            reverse('quiz:submit', args=[self.quiz.trigger_key]),
            self.valid_data(**{f'quiz-{first_question.field_name}': '999999'}),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(missing_response.status_code, 422)
        self.assertIn(first_question.field_name, missing_response.json()['errors'])
        self.assertEqual(tampered_response.status_code, 422)
        self.assertIn(first_question.field_name, tampered_response.json()['errors'])
        self.assertFalse(ContactRequest.objects.exists())

    def test_honeypot_and_too_fast_token_return_success_without_saving(self):
        honeypot_response = self.client.post(
            reverse('quiz:submit', args=[self.quiz.trigger_key]),
            self.valid_data(**{'quiz-website': 'https://spam.example'}),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        fast_response = self.client.post(
            reverse('quiz:submit', args=[self.quiz.trigger_key]),
            self.valid_data(**{'quiz-form_token': self.create_token(age_seconds=0)}),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertTrue(honeypot_response.json()['ok'])
        self.assertTrue(fast_response.json()['ok'])
        self.assertFalse(ContactRequest.objects.exists())

    def test_disabled_quiz_cannot_accept_submission(self):
        self.quiz.is_enabled = False
        self.quiz.save(update_fields=['is_enabled'])

        response = self.client.post(
            reverse('quiz:submit', args=[self.quiz.trigger_key]),
            self.valid_data(),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(ContactRequest.objects.exists())

    def test_request_and_delivery_are_atomic_with_answer_snapshot(self):
        with patch('quiz.views.QuizSubmission.objects.create', side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse('quiz:submit', args=[self.quiz.trigger_key]),
                    self.valid_data(),
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest',
                )

        self.assertFalse(ContactRequest.objects.exists())
        self.assertFalse(ContactRequestDelivery.objects.exists())

    def test_telegram_and_admin_show_escaped_quiz_answers(self):
        contact_request = ContactRequest.objects.create(
            request_type=ContactRequest.RequestType.QUIZ,
            name='Иван',
            phone='+375 29 111-22-33',
        )
        QuizSubmission.objects.create(
            quiz=self.quiz,
            contact_request=contact_request,
            answers=[{
                'question': 'Город <район>',
                'answer': 'Жодино & рядом',
            }],
        )

        message = format_contact_request_message(contact_request)
        request_admin = ContactRequestAdmin(ContactRequest, AdminSite())
        admin_answers = str(request_admin.get_quiz_answers(contact_request))

        self.assertTrue(message.startswith('📋 <b>Новая заявка №'))
        self.assertIn('— <b><i>Квиз</i></b> —', message)
        self.assertIn('<b>Город &lt;район&gt;</b>', message)
        self.assertIn('Жодино &amp; рядом', message)
        self.assertIn('Город &lt;район&gt;', admin_answers)
        self.assertIn('Жодино &amp; рядом', admin_answers)
        self.assertEqual(
            request_admin.get_fields(None, contact_request),
            [
                'request_type',
                'name',
                'phone',
                'get_quiz_answers',
                'get_delivery_status',
                'created_at',
            ],
        )
