from django import template

from pict.models import Integration


register = template.Library()


@register.simple_tag(takes_context=True)
def site_integrations(context):
    """Один запрос на страницу; код подключается только из публичного базового шаблона."""
    request = context.get('request')
    if request is None:
        return []
    match = request.resolver_match
    if match and any(namespace in ('admin', 'djdt') for namespace in match.namespaces):
        return []
    return [
        integration for integration in Integration.objects.filter(is_enabled=True)
        if integration.matches_path(request.path_info)
    ]
