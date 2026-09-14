from django.apps import AppConfig


class PictConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'pict'
    verbose_name = 'База скинали'

    def ready(self):
        # Регистрация сигналов выполняется после полной загрузки моделей приложений.
        from . import signals  # noqa: F401
