from django.db.models.signals import m2m_changed, post_save, pre_delete
from django.dispatch import receiver
from django.utils import timezone
from sitecontent.models import SitePage

from .models import Category, Color, FinishedWork, Pict, TagPict


M2M_POST_ACTIONS = {'post_add', 'post_remove', 'post_clear'}


def touch_site_pages(page_codes, *, changed_at, using):
    """Обновляет сохранённые часы публичных постоянных страниц."""
    SitePage.objects.using(using).filter(code__in=page_codes).update(
        updated_at=changed_at,
    )


def touch_all_category_pages(*, changed_at, using):
    """Учитывает общую навигацию категорий, тегов и цветов в каталоге."""
    Category.objects.using(using).update(updated_at=changed_at)


def collect_m2m_change_ids(
    instance,
    action,
    reverse,
    pk_set,
    *,
    forward_manager_name,
    reverse_manager_name,
    state_attribute,
    using,
):
    """Возвращает ID изображений и справочника для прямых и обратных M2M-операций."""
    if action == 'pre_clear':
        if reverse:
            picture_ids = tuple(
                getattr(instance, reverse_manager_name)
                .using(using)
                .values_list('pk', flat=True)
            )
            related_ids = (instance.pk,)
        else:
            picture_ids = (instance.pk,)
            related_ids = tuple(
                getattr(instance, forward_manager_name)
                .using(using)
                .values_list('pk', flat=True)
            )
        setattr(instance, state_attribute, (picture_ids, related_ids))
        return None

    if action not in M2M_POST_ACTIONS:
        return None
    if action == 'post_clear':
        return instance.__dict__.pop(state_attribute, ((), ()))

    changed_ids = tuple(pk_set or ())
    if reverse:
        return changed_ids, (instance.pk,)
    return (instance.pk,), changed_ids


def touch_pictures(picture_ids, *, changed_at, using):
    if not picture_ids:
        return
    Pict.objects.using(using).filter(pk__in=picture_ids).update(
        updated_at=changed_at,
    )


@receiver(post_save, sender=Pict)
def picture_saved(sender, instance, raw, using, **kwargs):
    if raw:
        return
    changed_at = instance.updated_at
    touch_site_pages(
        (SitePage.Code.CATALOG, SitePage.Code.FINISHED_WORKS),
        changed_at=changed_at,
        using=using,
    )
    touch_all_category_pages(changed_at=changed_at, using=using)
    TagPict.objects.using(using).filter(tags=instance.pk).update(
        updated_at=changed_at,
    )


@receiver(pre_delete, sender=Pict)
def picture_deleted(sender, instance, using, **kwargs):
    changed_at = timezone.now()
    touch_site_pages(
        (SitePage.Code.CATALOG, SitePage.Code.FINISHED_WORKS),
        changed_at=changed_at,
        using=using,
    )
    touch_all_category_pages(changed_at=changed_at, using=using)
    TagPict.objects.using(using).filter(tags=instance.pk).update(
        updated_at=changed_at,
    )


@receiver(post_save, sender=FinishedWork)
def finished_work_saved(sender, instance, raw, using, **kwargs):
    if raw:
        return
    touch_site_pages(
        (SitePage.Code.HOME, SitePage.Code.FINISHED_WORKS),
        changed_at=instance.updated_at,
        using=using,
    )


@receiver(pre_delete, sender=FinishedWork)
def finished_work_deleted(sender, instance, using, **kwargs):
    touch_site_pages(
        (SitePage.Code.HOME, SitePage.Code.FINISHED_WORKS),
        changed_at=timezone.now(),
        using=using,
    )


def touch_category_change(*, changed_at, using):
    touch_all_category_pages(changed_at=changed_at, using=using)
    touch_site_pages(
        (SitePage.Code.CATALOG, SitePage.Code.FINISHED_WORKS),
        changed_at=changed_at,
        using=using,
    )


@receiver(post_save, sender=Category)
def category_saved(sender, instance, raw, using, **kwargs):
    if not raw:
        touch_category_change(changed_at=instance.updated_at, using=using)


@receiver(pre_delete, sender=Category)
def category_deleted(sender, instance, using, **kwargs):
    touch_category_change(changed_at=timezone.now(), using=using)


def touch_tag_change(*, changed_at, using):
    touch_all_category_pages(changed_at=changed_at, using=using)
    touch_site_pages(
        (SitePage.Code.CATALOG,),
        changed_at=changed_at,
        using=using,
    )


@receiver(post_save, sender=TagPict)
def tag_saved(sender, instance, raw, using, **kwargs):
    if not raw:
        touch_tag_change(changed_at=instance.updated_at, using=using)


@receiver(pre_delete, sender=TagPict)
def tag_deleted(sender, instance, using, **kwargs):
    touch_tag_change(changed_at=timezone.now(), using=using)


@receiver(post_save, sender=Color)
@receiver(pre_delete, sender=Color)
def color_changed(sender, instance, using, **kwargs):
    if kwargs.get('raw'):
        return
    changed_at = timezone.now()
    picture_ids = tuple(
        instance.pict_set.using(using).values_list('pk', flat=True)
    )
    touch_pictures(picture_ids, changed_at=changed_at, using=using)
    touch_all_category_pages(changed_at=changed_at, using=using)
    touch_site_pages(
        (SitePage.Code.CATALOG,),
        changed_at=changed_at,
        using=using,
    )


@receiver(m2m_changed, sender=Pict.cat.through)
def picture_categories_changed(
    sender,
    instance,
    action,
    reverse,
    pk_set,
    using,
    **kwargs,
):
    changed_ids = collect_m2m_change_ids(
        instance,
        action,
        reverse,
        pk_set,
        forward_manager_name='cat',
        reverse_manager_name='pict_set',
        state_attribute='_sitemap_category_clear_ids',
        using=using,
    )
    if changed_ids is None:
        return
    picture_ids, _category_ids = changed_ids
    changed_at = timezone.now()
    touch_pictures(picture_ids, changed_at=changed_at, using=using)
    touch_all_category_pages(changed_at=changed_at, using=using)
    touch_site_pages(
        (SitePage.Code.CATALOG, SitePage.Code.FINISHED_WORKS),
        changed_at=changed_at,
        using=using,
    )


@receiver(m2m_changed, sender=Pict.tags.through)
def picture_tags_changed(
    sender,
    instance,
    action,
    reverse,
    pk_set,
    using,
    **kwargs,
):
    changed_ids = collect_m2m_change_ids(
        instance,
        action,
        reverse,
        pk_set,
        forward_manager_name='tags',
        reverse_manager_name='tags',
        state_attribute='_sitemap_tag_clear_ids',
        using=using,
    )
    if changed_ids is None:
        return
    picture_ids, tag_ids = changed_ids
    changed_at = timezone.now()
    touch_pictures(picture_ids, changed_at=changed_at, using=using)
    TagPict.objects.using(using).filter(pk__in=tag_ids).update(
        updated_at=changed_at,
    )
    touch_all_category_pages(changed_at=changed_at, using=using)
    touch_site_pages(
        (SitePage.Code.CATALOG,),
        changed_at=changed_at,
        using=using,
    )


@receiver(m2m_changed, sender=Pict.color.through)
def picture_colors_changed(
    sender,
    instance,
    action,
    reverse,
    pk_set,
    using,
    **kwargs,
):
    changed_ids = collect_m2m_change_ids(
        instance,
        action,
        reverse,
        pk_set,
        forward_manager_name='color',
        reverse_manager_name='pict_set',
        state_attribute='_sitemap_color_clear_ids',
        using=using,
    )
    if changed_ids is None:
        return
    picture_ids, _color_ids = changed_ids
    changed_at = timezone.now()
    touch_pictures(picture_ids, changed_at=changed_at, using=using)
    touch_all_category_pages(changed_at=changed_at, using=using)
    touch_site_pages(
        (SitePage.Code.CATALOG,),
        changed_at=changed_at,
        using=using,
    )
