import re

from django import forms

from .models import MAX_STAIR_INCLUDED_FLOOR, MAX_STAIR_PANELS, MIN_STAIR_PANELS, QUANTITY_DECIMAL_PLACES, QUANTITY_STEP, StairLiftingRule


class QuantityLimitWidget(forms.NumberInput):
    """Показывает целое количество без дроби, дробное — с двумя знаками."""

    def format_value(self, value):
        value = super().format_value(value)
        if str(self.attrs.get('step')) == '1' and value:
            return re.sub(r'^([+-]?\d+)[.,]0+$', r'\1', value)
        if str(self.attrs.get('step')) == str(QUANTITY_STEP) and value:
            if re.fullmatch(rf'[+-]?\d+(?:[.,]\d{{1,{QUANTITY_DECIMAL_PLACES}}})?', value):
                whole, _, tail = value.replace(',', '.').partition('.')
                return f'{whole}.{tail.ljust(QUANTITY_DECIMAL_PLACES, "0")}'
        return value


class StairLiftingRulesWidget(forms.Widget):
    """Таблица с последовательными столбцами для 1–6 панелей."""

    template_name = 'calculator/widgets/stair_lifting_rules.html'

    def value_from_datadict(self, data, files, name):
        return {
            'count': data.get(f'{name}_count', ''),
            'rules': {
                count: tuple(data.get(f'{name}_{field}_{count}', '') for field in ('included_floor', 'multiplier'))
                for count in range(1, MAX_STAIR_PANELS + 1)
            },
        }

    def id_for_label(self, id_):
        return f'{id_}_included_floor_1' if id_ else ''

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        if isinstance(value, dict) and 'count' in value:
            rules = value['rules']
            try:
                count = int(value['count'])
            except (TypeError, ValueError):
                count = MIN_STAIR_PANELS
        else:
            rules = value or {}
            count = len(rules)
        count = min(MAX_STAIR_PANELS, max(MIN_STAIR_PANELS, count))
        widget = context['widget']
        widget.update(count=count, min_count=MIN_STAIR_PANELS, max_count=MAX_STAIR_PANELS)
        widget['columns'] = [(number, number > count) for number in range(1, MAX_STAIR_PANELS + 1)]
        rows = []
        for index, field_name in enumerate(('included_floor', 'multiplier')):
            field = StairLiftingRule._meta.get_field(field_name)
            cells = []
            for number, hidden in widget['columns']:
                cell_attrs = {
                    **widget['attrs'], 'id': f'{widget["attrs"].get("id", name)}_{field_name}_{number}',
                    'min': 0, 'step': 1 if index == 0 else '0.01',
                    'aria-label': f'{field.verbose_name}: панелей {number}',
                    'disabled': hidden, 'required': not hidden,
                }
                if index == 0:
                    cell_attrs['max'] = MAX_STAIR_INCLUDED_FLOOR
                input_widget = field.formfield().widget
                cells.append((hidden, input_widget.get_context(
                    f'{name}_{field_name}_{number}', rules.get(number, ('', ''))[index], cell_attrs,
                )['widget']))
            rows.append((str(field.verbose_name), cells))
        widget['rule_rows'] = rows
        return context

    class Media:
        css = {'all': ('calculator/css/admin-stair-lifting-rules.css',)}
        js = ('calculator/js/admin-stair-lifting-rules.js',)
