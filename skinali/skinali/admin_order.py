import json

from django.db import transaction
from django.http import JsonResponse


def reorder_admin_objects(request, queryset, *, on_reorder=None):
    """Атомарно переставляет записи в видимых слотах поиска или страницы списка."""
    try:
        ordered_ids = json.loads(request.body)['ordered_ids']
        if not isinstance(ordered_ids, list) or not ordered_ids:
            raise ValueError
        if any(type(object_id) is not int or object_id <= 0 for object_id in ordered_ids):
            raise ValueError
    except (KeyError, TypeError, ValueError, RecursionError):
        return JsonResponse({'error': 'Некорректный список записей.'}, status=400)
    if len(ordered_ids) != len(set(ordered_ids)):
        return JsonResponse({'error': 'Запись не может встречаться в порядке дважды.'}, status=400)

    using = queryset.db
    with transaction.atomic(using=using):
        objects = list(queryset.select_for_update().order_by('position', 'pk'))
        current_ids = [obj.pk for obj in objects]
        submitted = set(ordered_ids)
        if not submitted.issubset(current_ids):
            return JsonResponse({'error': 'Список изменился. Обновите страницу.'}, status=409)
        slots = [index for index, object_id in enumerate(current_ids) if object_id in submitted]
        for slot, object_id in zip(slots, ordered_ids):
            current_ids[slot] = object_id

        by_id = {obj.pk: obj for obj in objects}
        changed = []
        for position, object_id in enumerate(current_ids, start=1):
            obj = by_id[object_id]
            if obj.position != position:
                obj.position = position
                changed.append(obj)
        if changed:
            queryset.model.objects.using(using).bulk_update(changed, ['position'])
            if on_reorder:
                on_reorder(changed, using)
    return JsonResponse({'saved': True})
