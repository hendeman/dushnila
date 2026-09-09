from .forms import CallbackContactForm, ImagePurchaseContactForm


def contact_forms(request):
    """Добавляет общие модальные формы во все публичные шаблоны с base.html."""
    return {
        'callback_form': CallbackContactForm(prefix='callback'),
        'image_purchase_form': ImagePurchaseContactForm(prefix='image_purchase'),
    }
