class DeliveryConfigurationError(Exception):
    """Безопасное сообщение о некорректной конфигурации подключения."""


class DeliveryError(Exception):
    """Безопасная ошибка сервиса и условия повторной попытки."""

    def __init__(self, message, *, retryable, retry_after=None):
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after
