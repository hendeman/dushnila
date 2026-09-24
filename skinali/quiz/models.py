from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Prefetch
from django.templatetags.static import static

from pict.page_paths import matches_public_page_path, normalize_public_page_paths


TRIGGER_KEY_VALIDATOR = RegexValidator(
    regex=r'^[a-z0-9_-]+$',
    message='Используйте строчные латинские буквы, цифры, дефис и подчёркивание.',
)

BUNDLED_IMAGE_CHOICES = (
    ('', 'Без исходного изображения'),
    ('quiz/images/answers/layout-straight.jpg', 'Планировка: прямая'),
    ('quiz/images/answers/layout-corner.jpg', 'Планировка: угловая'),
    ('quiz/images/answers/layout-u-shaped.jpg', 'Планировка: П-образная'),
    ('quiz/images/answers/layout-island.jpg', 'Планировка: кухня с островом'),
    ('quiz/images/answers/layout-two-row.jpg', 'Планировка: двухрядная'),
    ('quiz/images/answers/layout-other.jpg', 'Планировка: другая'),
    ('quiz/images/answers/skinali-photo-print.jpg', 'Вид: с фотопечатью'),
    ('quiz/images/answers/skinali-solid.jpg', 'Вид: однотонное'),
    ('quiz/images/answers/skinali-transparent.jpg', 'Вид: прозрачное'),
    ('quiz/images/answers/gift-clock.jpg', 'Подарок: часы'),
    ('quiz/images/answers/gift-hood-glass.jpg', 'Подарок: стекло под вытяжкой'),
    ('quiz/images/answers/gift-discount.jpg', 'Подарок: скидка'),
    ('quiz/images/answers/gift-shelves.jpg', 'Подарок: полки'),
)


class QuizQuerySet(models.QuerySet):
    def enabled(self):
        return self.filter(is_enabled=True)

    def with_public_content(self):
        options = QuizOption.objects.filter(is_enabled=True).order_by('position', 'pk')
        questions = (
            QuizQuestion.objects
            .filter(is_enabled=True)
            .order_by('position', 'pk')
            .prefetch_related(Prefetch('options', queryset=options, to_attr='public_options'))
        )
        return self.prefetch_related(
            Prefetch('questions', queryset=questions, to_attr='public_questions')
        )


class Quiz(models.Model):
    """Настройки единственного публичного квиза и его способа показа."""

    name = models.CharField('Название в admin', max_length=200)
    title = models.CharField('Заголовок квиза', max_length=300)
    is_enabled = models.BooleanField('Включён', default=False, db_index=True)
    trigger_key = models.CharField(
        'Ключ ссылки',
        max_length=80,
        unique=True,
        validators=[TRIGGER_KEY_VALIDATOR],
        help_text='Ссылка для открытия будет иметь вид #popup:ключ.',
    )
    page_paths = models.TextField(
        'Страницы',
        blank=True,
        help_text=(
            'Пусто — все публичные страницы. Или точные локальные пути, '
            'по одному на строку, например /about/ и /skinali/.'
        ),
    )
    show_launcher = models.BooleanField('Показывать кнопку запуска', default=True)
    launcher_text = models.CharField('Текст кнопки запуска', max_length=80, default='Пройти тест')
    launcher_position = models.CharField(
        'Сторона кнопки запуска',
        max_length=10,
        choices=(('left', 'Слева'), ('right', 'Справа')),
        default='left',
    )
    auto_open_enabled = models.BooleanField('Включить автопоказ', default=True)
    auto_open_delay_seconds = models.PositiveSmallIntegerField(
        'Задержка автопоказа, секунд',
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(3600)],
    )
    repeat_after_days = models.PositiveSmallIntegerField(
        'Повторный автопоказ через, дней',
        default=3,
        validators=[MinValueValidator(0), MaxValueValidator(3650)],
        help_text='0 — разрешать автопоказ при каждой новой загрузке страницы.',
    )
    auto_open_on_mobile = models.BooleanField('Автопоказ на мобильных', default=True)
    disable_auto_open_after_submit = models.BooleanField(
        'Не показывать автоматически после заявки',
        default=True,
    )
    restart_on_close = models.BooleanField(
        'Начинать заново после закрытия',
        default=True,
    )
    final_title = models.CharField('Заголовок формы', max_length=200)
    final_text = models.TextField('Текст перед формой')
    submit_button_text = models.CharField('Текст кнопки отправки', max_length=160)
    success_title = models.CharField('Заголовок после отправки', max_length=160)
    success_text = models.TextField('Сообщение после отправки')
    success_extra = models.TextField('Дополнительный текст после отправки', blank=True)
    updated_at = models.DateTimeField('Изменён', auto_now=True)

    objects = QuizQuerySet.as_manager()

    class Meta:
        verbose_name = 'Квиз'
        verbose_name_plural = 'Квиз'
        ordering = ['pk']

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        try:
            self.page_paths = normalize_public_page_paths(self.page_paths)
        except ValidationError as error:
            raise ValidationError({'page_paths': error.messages}) from error

    def matches_path(self, path):
        return matches_public_page_path(self.page_paths, path)

    @property
    def trigger_hash(self):
        return f'#popup:{self.trigger_key}'

    def get_public_questions(self):
        if hasattr(self, 'public_questions'):
            return self.public_questions
        return list(
            self.questions.filter(is_enabled=True)
            .order_by('position', 'pk')
            .prefetch_related(
                Prefetch(
                    'options',
                    queryset=QuizOption.objects.filter(is_enabled=True).order_by('position', 'pk'),
                    to_attr='public_options',
                )
            )
        )


class QuizQuestion(models.Model):
    class Kind(models.TextChoices):
        IMAGE = 'image', 'Один вариант с изображениями'
        CHOICE = 'choice', 'Один вариант списком'
        TEXT = 'text', 'Текстовый ответ'

    quiz = models.ForeignKey(
        Quiz,
        on_delete=models.CASCADE,
        related_name='questions',
        verbose_name='Квиз',
    )
    title = models.CharField('Вопрос', max_length=250)
    description = models.TextField('Пояснение', blank=True)
    kind = models.CharField('Тип вопроса', max_length=20, choices=Kind.choices)
    placeholder = models.CharField('Подсказка в поле', max_length=160, blank=True)
    is_required = models.BooleanField('Обязательный', default=True)
    is_enabled = models.BooleanField('Показывать', default=True)
    position = models.PositiveIntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Вопрос квиза'
        verbose_name_plural = 'Вопросы квиза'
        ordering = ['position', 'pk']

    def __str__(self):
        return self.title

    @property
    def field_name(self):
        return f'question_{self.pk}'

    def get_public_options(self):
        if hasattr(self, 'public_options'):
            return self.public_options
        return list(self.options.filter(is_enabled=True).order_by('position', 'pk'))


class QuizOption(models.Model):
    question = models.ForeignKey(
        QuizQuestion,
        on_delete=models.CASCADE,
        related_name='options',
        verbose_name='Вопрос',
    )
    title = models.CharField('Вариант ответа', max_length=200)
    bundled_image = models.CharField(
        'Исходное изображение',
        max_length=200,
        blank=True,
        choices=BUNDLED_IMAGE_CHOICES,
        help_text='Загруженное изображение имеет приоритет над исходным.',
    )
    image = models.ImageField(
        'Загруженное изображение',
        upload_to='quiz/options/',
        blank=True,
    )
    is_enabled = models.BooleanField('Показывать', default=True)
    position = models.PositiveIntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Вариант ответа'
        verbose_name_plural = 'Варианты ответов'
        ordering = ['position', 'pk']

    def __str__(self):
        return self.title

    @property
    def image_url(self):
        if self.image:
            try:
                return self.image.url
            except ValueError:
                pass
        return static(self.bundled_image) if self.bundled_image else ''


class QuizSubmission(models.Model):
    """Неизменяемый снимок ответов, связанный с общей контактной заявкой."""

    quiz = models.ForeignKey(
        Quiz,
        on_delete=models.PROTECT,
        related_name='submissions',
        verbose_name='Квиз',
    )
    contact_request = models.OneToOneField(
        'pict.ContactRequest',
        on_delete=models.CASCADE,
        related_name='quiz_submission',
        verbose_name='Заявка',
    )
    answers = models.JSONField('Снимок ответов', default=list)
    created_at = models.DateTimeField('Время создания', auto_now_add=True)

    class Meta:
        verbose_name = 'Ответ на квиз'
        verbose_name_plural = 'Ответы на квиз'
        ordering = ['-created_at', '-pk']

    def __str__(self):
        return f'{self.quiz} — заявка №{self.contact_request_id}'
