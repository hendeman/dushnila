from django.shortcuts import redirect
from django.urls import reverse


class SuperuserAdminMixin:
    """Редактирование системных настроек доступно активному суперпользователю."""

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)


class SingletonAdminMixin(SuperuserAdminMixin):
    """Общий переход в единственную системную карточку и запрет её удаления."""

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        if self.has_view_permission(request):
            instance = self.model.objects.only('pk').first()
            if instance:
                opts = self.model._meta
                return redirect(reverse(
                    f'{self.admin_site.name}:{opts.app_label}_{opts.model_name}_change',
                    args=[instance.pk],
                ))
        return super().changelist_view(request, extra_context=extra_context)
