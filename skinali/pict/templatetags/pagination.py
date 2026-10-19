from django import template


register = template.Library()


@register.simple_tag
def pagination_items(page_obj):
    """Номера страниц и переходы в середину пропущенных диапазонов."""
    current = page_obj.number
    last = page_obj.paginator.num_pages

    if current <= 3:
        nearby = range(1, min(3, last) + 1)
    elif current >= last - 2:
        nearby = range(max(1, last - 2), last + 1)
    else:
        nearby = (current - 1, current)

    numbers = sorted({1, last, *nearby})
    items = []
    previous = None
    for number in numbers:
        if previous is not None:
            gap = number - previous
            if gap == 2:
                items.append({'number': previous + 1, 'is_gap': False})
            elif gap > 2:
                items.append({'number': (previous + number) // 2, 'is_gap': True})
        items.append({'number': number, 'is_gap': False})
        previous = number
    return items
