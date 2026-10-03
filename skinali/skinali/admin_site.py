from django.contrib.admin import AdminSite


class SkinaliAdminSite(AdminSite):
    """Добавляет число непросмотренных заявок в список моделей admin."""

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)
        for app in app_list:
            if app['app_label'] != 'pict':
                continue
            for model in app['models']:
                if model['object_name'] != 'ContactRequest' or not model['admin_url']:
                    continue

                count = getattr(request, '_unviewed_contact_request_count', None)
                if count is None:
                    from pict.models import ContactRequest

                    count = ContactRequest.objects.filter(viewed_at__isnull=True).count()
                    request._unviewed_contact_request_count = count
                if count:
                    model['name'] = f'{model["name"]} ({count})'
                break
        return app_list
