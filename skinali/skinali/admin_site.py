from django.contrib.admin import AdminSite
from django.urls import URLPattern, include, path


class SkinaliAdminSite(AdminSite):
    """Сохраняет старые адреса и показывает число непросмотренных заявок в admin."""

    def get_urls(self):
        from leads.models import ContactRequest, LeadConnection
        from sitecontent.models import Integration, IntegrationRevision

        legacy_urls = []
        for model, old_app in (
            (Integration, 'pict'),
            (IntegrationRevision, 'pict'),
            (ContactRequest, 'pict'),
            (LeadConnection, 'sitecontent'),
        ):
            if not self.is_registered(model):
                continue
            model_admin = self.get_model_admin(model)
            current_prefix = f'{model._meta.app_label}_'
            # Старые ссылки и POST-запросы используют те же защищённые обработчики.
            patterns = [
                URLPattern(
                    pattern.pattern,
                    pattern.callback,
                    pattern.default_args,
                    name=f'{old_app}_{pattern.name.removeprefix(current_prefix)}' if pattern.name else None,
                )
                for pattern in model_admin.urls
            ]
            legacy_urls.append(path(f'{old_app}/{model._meta.model_name}/', include(patterns)))
        return legacy_urls + super().get_urls()

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)
        for app in app_list:
            if app['app_label'] != 'leads':
                continue
            for model in app['models']:
                if model['object_name'] != 'ContactRequest' or not model['admin_url']:
                    continue

                count = getattr(request, '_unviewed_contact_request_count', None)
                if count is None:
                    from leads.models import ContactRequest

                    count = ContactRequest.objects.filter(viewed_at__isnull=True).count()
                    request._unviewed_contact_request_count = count
                if count:
                    model['name'] = f'{model["name"]} ({count})'
                break
        return app_list
