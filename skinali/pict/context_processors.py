from urllib.parse import urljoin

from django.conf import settings
from django.templatetags.static import static

from .forms import CallbackContactForm, ImagePurchaseContactForm


def site_identity(request):
    """Передаёт шаблонам единые публичные реквизиты и абсолютные URL."""
    identity = settings.SITE_IDENTITY
    site_url = f'{settings.PUBLIC_SITE_ORIGIN.rstrip("/")}/'
    return {
        'site_identity': {
            **identity,
            'url': site_url,
            'website_id': f'{site_url}#website',
            'organization_id': f'{site_url}#organization',
            'logo_url': urljoin(site_url, static(identity['logo_static_path'])),
        },
    }


def contact_forms(request):
    """Добавляет общие модальные формы во все публичные шаблоны с base.html."""
    return {
        'callback_form': CallbackContactForm(prefix='callback'),
        'image_purchase_form': ImagePurchaseContactForm(prefix='image_purchase'),
    }
