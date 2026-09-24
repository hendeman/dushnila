from django.db import migrations
from django.db.models import Q


QUIZ_TRIGGER_KEY = 'skinali-quiz'


QUESTIONS = (
    {
        'title': 'Какая планировка у Вашей кухни:',
        'description': (
            'Изготавливаем скинали и фартуки из стекла по индивидуальному проекту '
            'любых размеров и комплектации, от бюджетного до премиум класса.'
        ),
        'kind': 'image',
        'is_required': True,
        'position': 0,
        'options': (
            ('прямая', 'quiz/images/answers/layout-straight.jpg'),
            ('угловая', 'quiz/images/answers/layout-corner.jpg'),
            ('П-образная', 'quiz/images/answers/layout-u-shaped.jpg'),
            ('кухня с островом', 'quiz/images/answers/layout-island.jpg'),
            ('двухрядная', 'quiz/images/answers/layout-two-row.jpg'),
            ('другая', 'quiz/images/answers/layout-other.jpg'),
        ),
    },
    {
        'title': 'Какой вид скинали Вы хотите?',
        'description': (
            'На панели из стекла можно нанести любое изображение из нашего каталога '
            '(более 12 000 вариантов), фотобанка или Вашу личную фотографию '
            'в подходящем качестве.'
        ),
        'kind': 'image',
        'is_required': True,
        'position': 1,
        'options': (
            ('с фотопечатью', 'quiz/images/answers/skinali-photo-print.jpg'),
            ('однотонное', 'quiz/images/answers/skinali-solid.jpg'),
            ('прозрачное', 'quiz/images/answers/skinali-transparent.jpg'),
        ),
    },
    {
        'title': 'Укажите ваш город',
        'description': '',
        'kind': 'text',
        'placeholder': 'Ваш город',
        'is_required': False,
        'position': 2,
        'options': (),
    },
    {
        'title': 'Укажите длину Вашей кухни в метрах:',
        'description': (
            'Стоимость скинали напрямую зависит от ее общей длины, поэтому чем точнее '
            'вы ее укажете, тем точнее будет результат теста.'
        ),
        'kind': 'choice',
        'is_required': True,
        'position': 3,
        'options': (
            ('Меньше 2,5 метров', ''),
            ('От 2,5 до 3 метров', ''),
            ('От 3,0 до 3,5 метров', ''),
            ('От 3,5 до 4 метров', ''),
            ('Более 4 метров', ''),
            ('не знаю', ''),
        ),
    },
    {
        'title': 'Когда планируете устанавливать скинали?',
        'description': (
            'Выберите примерный период, чтобы мы понимали и учитывали наши складские '
            'ресурсы. Чем меньше период, тем точнее будет расчет.'
        ),
        'kind': 'choice',
        'is_required': True,
        'position': 4,
        'options': (
            ('1-2 недели', ''),
            ('3-4 недели', ''),
            ('1-2 месяца', ''),
            ('Не знаю', ''),
        ),
    },
    {
        'title': 'Выберите Ваш подарок!',
        'description': 'Пройдите тест до конца и получите гарантированный подарок!',
        'kind': 'image',
        'is_required': False,
        'position': 5,
        'options': (
            ('Часы под цвет скинали', 'quiz/images/answers/gift-clock.jpg'),
            ('Стекло под вытяжкой', 'quiz/images/answers/gift-hood-glass.jpg'),
            ('Скидка 5% на заказ', 'quiz/images/answers/gift-discount.jpg'),
            ('Полки из стекла', 'quiz/images/answers/gift-shelves.jpg'),
        ),
    },
)


def seed_quiz(apps, schema_editor):
    Quiz = apps.get_model('quiz', 'Quiz')
    QuizQuestion = apps.get_model('quiz', 'QuizQuestion')
    QuizOption = apps.get_model('quiz', 'QuizOption')
    Integration = apps.get_model('pict', 'Integration')
    IntegrationRevision = apps.get_model('pict', 'IntegrationRevision')

    quiz, quiz_created = Quiz.objects.get_or_create(
        trigger_key=QUIZ_TRIGGER_KEY,
        defaults={
            'name': 'Квиз «Расчёт стоимости скинали»',
            'title': (
                'Ответьте на 5 простых вопросов и узнайте стоимость скинали из стекла '
                'для Вашей кухни, а также получите подарок!'
            ),
            'is_enabled': True,
            'page_paths': '',
            'show_launcher': True,
            'launcher_text': 'Пройти тест',
            'launcher_position': 'left',
            'auto_open_enabled': True,
            'auto_open_delay_seconds': 10,
            'repeat_after_days': 3,
            'auto_open_on_mobile': True,
            'disable_auto_open_after_submit': True,
            'restart_on_close': True,
            'final_title': 'Последний шаг!',
            'final_text': (
                'Ваш расчет готов! Введите номер телефона, мы вышлем на него стоимость '
                'Вашей будущей скинали для кухни'
            ),
            'submit_button_text': 'Получить результат. Забронировать скидку',
            'success_title': 'Спасибо!',
            'success_text': 'В ближайшее время с Вами свяжется наш менеджер',
            'success_extra': (
                'Скидка либо подарок будут забронированы за Вашим номером телефона '
                'и действительны в течение 60 дней'
            ),
        },
    )

    if quiz_created:
        for question_data in QUESTIONS:
            options = question_data['options']
            question = QuizQuestion.objects.create(
                quiz=quiz,
                title=question_data['title'],
                description=question_data['description'],
                kind=question_data['kind'],
                placeholder=question_data.get('placeholder', ''),
                is_required=question_data['is_required'],
                is_enabled=True,
                position=question_data['position'],
            )
            QuizOption.objects.bulk_create([
                QuizOption(
                    question=question,
                    title=title,
                    bundled_image=image,
                    is_enabled=True,
                    position=position,
                )
                for position, (title, image) in enumerate(options)
            ])

    # Два виджета одновременно конкурировали бы за автопоказ, поэтому прежнюю
    # интеграцию только выключаем и сохраняем её код вместе с историей.
    old_integrations = Integration.objects.filter(is_enabled=True).filter(
        Q(head_html__icontains='leadforms')
        | Q(body_start_html__icontains='leadforms')
        | Q(body_end_html__icontains='leadforms')
    ).filter(
        Q(head_html__contains='2327')
        | Q(body_start_html__contains='2327')
        | Q(body_end_html__contains='2327')
    )
    snapshot_fields = (
        'name', 'description', 'is_enabled', 'position', 'page_paths',
        'head_html', 'body_start_html', 'body_end_html',
    )
    for integration in old_integrations:
        integration.is_enabled = False
        integration.save(update_fields=['is_enabled', 'updated_at'])
        IntegrationRevision.objects.create(
            integration=integration,
            author=None,
            note='Отключена после переноса квиза в проект',
            snapshot={
                field: getattr(integration, field)
                for field in snapshot_fields
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_quiz, migrations.RunPython.noop),
    ]
