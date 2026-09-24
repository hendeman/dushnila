from django.contrib import admin
from django.utils.html import format_html

from .models import Quiz, QuizOption, QuizQuestion


class QuizQuestionInline(admin.TabularInline):
    model = QuizQuestion
    extra = 0
    fields = ['position', 'title', 'kind', 'is_required', 'is_enabled']
    ordering = ['position', 'pk']
    show_change_link = True


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_enabled', 'trigger_link', 'auto_open_enabled', 'updated_at']
    readonly_fields = ['trigger_link', 'updated_at']
    inlines = [QuizQuestionInline]
    fieldsets = (
        ('Публикация', {
            'fields': ('name', 'title', 'is_enabled', 'trigger_key', 'trigger_link', 'page_paths'),
        }),
        ('Кнопка запуска', {
            'fields': ('show_launcher', 'launcher_text', 'launcher_position'),
        }),
        ('Автопоказ', {
            'fields': (
                'auto_open_enabled',
                'auto_open_delay_seconds',
                'repeat_after_days',
                'auto_open_on_mobile',
                'disable_auto_open_after_submit',
                'restart_on_close',
            ),
        }),
        ('Финальная форма', {
            'fields': ('final_title', 'final_text', 'submit_button_text'),
        }),
        ('После отправки', {
            'fields': ('success_title', 'success_text', 'success_extra'),
        }),
        ('Служебное', {
            'fields': ('updated_at',),
        }),
    )

    def has_add_permission(self, request):
        return not Quiz.objects.exists() and super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='Ссылка')
    def trigger_link(self, obj):
        return obj.trigger_hash if obj and obj.pk else 'Будет создана после сохранения'


class QuizOptionInline(admin.TabularInline):
    model = QuizOption
    extra = 0
    fields = [
        'position',
        'title',
        'bundled_image',
        'image',
        'image_preview',
        'is_enabled',
    ]
    readonly_fields = ['image_preview']
    ordering = ['position', 'pk']

    @admin.display(description='Превью')
    def image_preview(self, obj):
        if not obj or not obj.image_url:
            return '—'
        return format_html(
            '<img src="{}" alt="" style="width:80px;height:80px;object-fit:cover;border-radius:6px">',
            obj.image_url,
        )


@admin.register(QuizQuestion)
class QuizQuestionAdmin(admin.ModelAdmin):
    list_display = ['title', 'quiz', 'kind', 'position', 'is_required', 'is_enabled']
    list_filter = ['quiz', 'kind', 'is_required', 'is_enabled']
    list_editable = ['position', 'is_required', 'is_enabled']
    search_fields = ['title', 'description']
    ordering = ['quiz', 'position', 'pk']
    inlines = [QuizOptionInline]
