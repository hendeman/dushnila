(() => {
    'use strict';

    const initialize = () => {
        document.querySelectorAll('.stair-lifting-rules').forEach((widget) => {
            const count = widget.querySelector('[data-rule-count]');
            const add = widget.querySelector('[data-add-rule]');
            const remove = widget.querySelector('[data-remove-rule]');
            const minimum = Number(widget.dataset.min);
            const maximum = Number(widget.dataset.max);
            const update = () => {
                const visible = Number(count.value);
                widget.querySelectorAll('[data-rule-column]').forEach((cell) => {
                    cell.hidden = Number(cell.dataset.ruleColumn) > visible;
                    cell.querySelectorAll('input').forEach((input) => {
                        input.disabled = cell.hidden;
                        input.required = !cell.hidden;
                    });
                });
                add.disabled = visible >= maximum;
                remove.disabled = visible <= minimum;
            };
            add.addEventListener('click', () => {
                if (Number(count.value) >= maximum) return;
                count.value = String(Number(count.value) + 1);
                update();
                widget.querySelector(`td[data-rule-column="${count.value}"] input`).focus();
            });
            remove.addEventListener('click', () => {
                if (Number(count.value) <= minimum) return;
                count.value = String(Number(count.value) - 1);
                update();
            });
            update();
        });
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
    else initialize();
})();
