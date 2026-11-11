import django.core.validators
import django.db.models.deletion
import django.utils.timezone
import uuid
from django.db import migrations, models



PREVIOUS_APP_LABELS = (
    ('contactrequest', 'pict'),
    ('contactrequestdelivery', 'pict'),
    ('leadconnection', 'sitecontent'),
)


def move_content_types(apps, schema_editor, *, backwards=False):
    content_types = apps.get_model('contenttypes', 'ContentType')
    # Существующие права и журнал admin ссылаются на эти же идентификаторы.
    for model, previous_app in PREVIOUS_APP_LABELS:
        source, destination = ('leads', previous_app) if backwards else (previous_app, 'leads')
        content_types.objects.using(schema_editor.connection.alias).filter(
            app_label=source, model=model,
        ).update(app_label=destination)


def restore_content_types(apps, schema_editor):
    move_content_types(apps, schema_editor, backwards=True)


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
        ('pict', '0040_remove_integration_state'),
        ('sitecontent', '0017_move_integrations'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='LeadConnection',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('name', models.CharField(max_length=100, verbose_name='Название')),
                        ('provider', models.CharField(choices=[('telegram', 'Telegram'), ('email', 'Email')], max_length=20, verbose_name='Сервис')),
                        ('is_enabled', models.BooleanField(default=False, verbose_name='Включено')),
                        ('all_request_types', models.BooleanField(default=True, verbose_name='Все типы заявок')),
                        ('request_types', models.JSONField(blank=True, default=list, verbose_name='Типы заявок')),
                        ('recipients', models.JSONField(blank=True, default=list, verbose_name='Получатели')),
                        ('use_environment', models.BooleanField(default=False, verbose_name='Использовать настройки Telegram из окружения')),
                        ('telegram_token_encrypted', models.TextField(blank=True, editable=False)),
                        ('proxy_url_encrypted', models.TextField(blank=True, editable=False)),
                        ('smtp_host', models.CharField(blank=True, max_length=253, verbose_name='SMTP-сервер')),
                        ('smtp_port', models.PositiveIntegerField(default=587, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(65535)], verbose_name='Порт')),
                        ('smtp_security', models.CharField(choices=[('starttls', 'STARTTLS'), ('ssl', 'SSL/TLS')], default='starttls', max_length=20, verbose_name='Защита соединения')),
                        ('smtp_username', models.CharField(blank=True, max_length=254, verbose_name='Логин SMTP')),
                        ('smtp_password_encrypted', models.TextField(blank=True, editable=False)),
                        ('from_email', models.EmailField(blank=True, max_length=254, verbose_name='Адрес отправителя')),
                        ('from_name', models.CharField(blank=True, max_length=100, verbose_name='Имя отправителя')),
                        ('connect_timeout', models.PositiveSmallIntegerField(default=3, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(30)], verbose_name='Тайм-аут соединения, сек.')),
                        ('read_timeout', models.PositiveSmallIntegerField(default=5, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(30)], verbose_name='Тайм-аут ответа, сек.')),
                        ('configuration_error', models.TextField(blank=True, editable=False, verbose_name='Ошибка настройки')),
                        ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создано')),
                        ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Изменено')),
                    ],
                    options={
                        'verbose_name': 'Подключение',
                        'verbose_name_plural': 'Обработка заявок',
                        'db_table': 'sitecontent_leadconnection',
                        'ordering': ['name', 'pk'],
                    },
                ),
                migrations.CreateModel(
                    name='ContactRequest',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('request_type', models.CharField(choices=[('callback', 'Обратный звонок'), ('question', 'Вопрос'), ('email_message', 'Сообщение по email'), ('image_purchase', 'Покупка изображения'), ('quiz', 'Квиз'), ('calculator_order', 'Заказ из калькулятора')], max_length=20, verbose_name='Тип заявки')),
                        ('name', models.CharField(max_length=20, verbose_name='Имя')),
                        ('phone', models.CharField(blank=True, max_length=20, verbose_name='Телефон')),
                        ('calculation_url', models.CharField(blank=True, default='', editable=False, max_length=8192, verbose_name='Ссылка на расчёт')),
                        ('email', models.EmailField(blank=True, default='', max_length=254, verbose_name='Email')),
                        ('question', models.CharField(blank=True, max_length=250, verbose_name='Вопрос')),
                        ('comment', models.CharField(blank=True, default='', max_length=250, verbose_name='Комментарий')),
                        ('image_number', models.PositiveIntegerField(blank=True, null=True, verbose_name='Номер изображения на момент заявки')),
                        ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Время создания')),
                        ('viewed_at', models.DateTimeField(blank=True, editable=False, null=True, verbose_name='Время просмотра')),
                        ('catalog_image', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='purchase_requests', to='pict.pict', verbose_name='Изображение каталога')),
                    ],
                    options={
                        'verbose_name': 'Заявка',
                        'verbose_name_plural': 'Заявки',
                        'db_table': 'pict_contactrequest',
                        'ordering': ['-created_at', '-id'],
                    },
                ),
                migrations.CreateModel(
                    name='ContactRequestDelivery',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('recipient', models.CharField(blank=True, max_length=254, verbose_name='Получатель')),
                        ('test_batch_id', models.UUIDField(blank=True, editable=False, null=True, verbose_name='Группа тестовой отправки')),
                        ('message_key', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                        ('channel', models.CharField(choices=[('telegram', 'Telegram'), ('email', 'Email')], max_length=20, verbose_name='Канал')),
                        ('status', models.CharField(choices=[('pending', 'Ожидает отправки'), ('processing', 'Отправляется'), ('retry', 'Ожидает повтора'), ('sent', 'Отправлено'), ('failed', 'Ошибка отправки')], db_index=True, default='pending', max_length=20, verbose_name='Статус')),
                        ('attempts', models.PositiveSmallIntegerField(default=0, verbose_name='Попытки')),
                        ('next_attempt_at', models.DateTimeField(blank=True, db_index=True, default=django.utils.timezone.now, null=True, verbose_name='Следующая попытка')),
                        ('processing_started_at', models.DateTimeField(blank=True, null=True, verbose_name='Начало обработки')),
                        ('sent_at', models.DateTimeField(blank=True, null=True, verbose_name='Время отправки')),
                        ('external_message_id', models.CharField(blank=True, default='', max_length=255, verbose_name='ID внешнего сообщения')),
                        ('last_error', models.TextField(blank=True, verbose_name='Последняя ошибка')),
                        ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Время создания')),
                        ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Время изменения')),
                        ('contact_request', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='deliveries', to='leads.contactrequest', verbose_name='Заявка')),
                        ('connection', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='deliveries', to='leads.leadconnection', verbose_name='Подключение')),
                    ],
                    options={
                        'verbose_name': 'Доставка заявки',
                        'verbose_name_plural': 'Доставки заявок',
                        'db_table': 'pict_contactrequestdelivery',
                        'ordering': ['-created_at', '-id'],
                        'indexes': [models.Index(fields=['connection', 'status', 'next_attempt_at'], name='pict_connection_due_idx')],
                        'constraints': [models.UniqueConstraint(fields=('contact_request', 'connection', 'recipient'), name='unique_request_connection_target'), models.CheckConstraint(condition=models.Q(models.Q(('contact_request__isnull', False), ('test_batch_id__isnull', True)), models.Q(('contact_request__isnull', True), ('test_batch_id__isnull', False)), _connector='OR'), name='delivery_request_or_test')],
                    },
                ),
            ],
        ),
        migrations.RunPython(move_content_types, restore_content_types),
    ]
