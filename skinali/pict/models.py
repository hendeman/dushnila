from django.db import models
from django.urls import reverse


class Color(models.Model):
    color = models.CharField(max_length=100, verbose_name='Цвет')
    slug_color = models.SlugField(max_length=100, unique=True, db_index=True, verbose_name='Slug')

    def __str__(self):
        return self.color

    class Meta:
        verbose_name = 'Цвет'
        verbose_name_plural = 'Цвета'


class TagPict(models.Model):
    tag = models.CharField(max_length=100, db_index=True, verbose_name='Ключевое слово')
    slug = models.SlugField(max_length=100, db_index=True, unique=True, verbose_name="Slug")

    def __str__(self):
        return self.tag

    def get_absolute_url(self):
        return reverse('tag', kwargs={'tag_slug': self.slug})

    class Meta:
        verbose_name = 'Ключевое слово'
        verbose_name_plural = 'Ключевые слова'


class Category(models.Model):
    cat = models.CharField(max_length=100, verbose_name='Категория')
    slug = models.SlugField(max_length=100, unique=True, db_index=True, verbose_name='Slug')

    def __str__(self):
        return self.cat

    def get_absolute_url(self):
        return reverse('skinali', kwargs={'slug_cat': self.slug})

    class Meta:
        verbose_name = 'Категории'
        verbose_name_plural = 'Категории'


class Pict(models.Model):
    name = models.IntegerField(unique=True, db_index=True, verbose_name='Имя файла')
    # name = models.CharField(max_length=10, unique=True, db_index=True, verbose_name='Имя файла')
    alt = models.CharField(max_length=250, blank=True, verbose_name='Описание')
    photo = models.ImageField(upload_to="photos/", verbose_name='Изображение')
    time_update = models.DateTimeField(auto_now_add=True, verbose_name='Время добавления')
    cat = models.ManyToManyField(Category, verbose_name="Категории")
    tags = models.ManyToManyField(TagPict, blank=True, related_name="tags", verbose_name="Теги")
    color = models.ManyToManyField(Color, verbose_name="Цвет")

    def __str__(self):
        return str(self.name)

    def __add__(self, other):
        return int(Pict.objects.first().name) + other

    class Meta:
        verbose_name = 'Изображения'
        verbose_name_plural = 'Изображения'
        ordering = ['-id']



