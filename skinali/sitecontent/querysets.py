from django.db import models


class PublicationQuerySet(models.QuerySet):
    """Единая выборка контента, разрешённого к показу на публичном сайте."""

    def published(self):
        return self.filter(is_published=True)
