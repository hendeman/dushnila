(() => {
    'use strict';

    const initialize = () => {
        const name = document.getElementById('id_name');
        const visibleLabel = document.getElementById('id_visibility_label');
        const priceLabel = document.getElementById('id_price_label');
        if (name && visibleLabel && priceLabel) {
            const refreshLabels = () => {
                [[visibleLabel, 'id_is_visible', 'Показывать услугу'], [priceLabel, 'id_price_per_unit', 'Цена за одну единицу']].forEach(([input, target, fallback]) => {
                    const label = document.querySelector(`label[for="${target}"]`);
                    const text = input.value.trim() || fallback;
                    if (label) label.textContent = text.endsWith(':') ? text : `${text}:`;
                });
            };
            const defaults = [[visibleLabel, (value) => value ? `Показать: ${value}` : ''], [priceLabel, (value) => value]];
            defaults.forEach(([input, label]) => {
                let automatic = input.value === '' || input.value === label(name.value);
                input.addEventListener('input', () => { automatic = input.value === ''; refreshLabels(); });
                name.addEventListener('input', () => { if (automatic) input.value = label(name.value); refreshLabels(); });
            });
            refreshLabels();
        }
        const paid = document.getElementById('id_has_price');
        const price = document.getElementById('id_price_per_unit');
        const fixed = document.getElementById('id_fixed_price');
        const area = document.getElementById('id_use_panel_area');
        const whole = document.getElementById('id_whole_quantity');
        const maximum = document.getElementById('id_max_quantity');
        if (paid && price) {
            const update = () => {
                price.closest('.form-row').hidden = !paid.checked;
                price.disabled = !paid.checked;
                if (fixed) fixed.closest('.form-row').hidden = !paid.checked;
                const hideQuantity = !paid.checked || Boolean(fixed?.checked);
                const quantitySection = document.getElementById('id_quantity_label')?.closest('fieldset');
                if (quantitySection) quantitySection.hidden = hideQuantity;
                ['quantity_label', 'unit', 'use_panel_area', 'whole_quantity'].forEach((name) => {
                    const input = document.getElementById(`id_${name}`);
                    if (!input) return;
                    input.disabled = hideQuantity;
                });
                if (maximum) {
                    const hideMaximum = hideQuantity || Boolean(area?.checked);
                    maximum.closest('.form-row').hidden = hideMaximum;
                    maximum.disabled = hideMaximum;
                    maximum.min = whole?.checked ? '1' : maximum.dataset.quantityStep;
                    maximum.step = whole?.checked ? '1' : maximum.dataset.quantityStep;
                    if (whole?.checked && !hideMaximum) {
                        maximum.value = maximum.value.replace(/^([+-]?\d+)[.,]0+$/, '$1');
                    } else if (!hideMaximum) {
                        const digits = maximum.dataset.quantityStep.split('.')[1].length;
                        const pattern = new RegExp(`^[+-]?\\d+(?:[.,]\\d{1,${digits}})?$`);
                        if (pattern.test(maximum.value)) {
                            maximum.value = Number(maximum.value.replace(',', '.')).toFixed(digits);
                        }
                    }
                }
            };
            paid.addEventListener('change', update);
            if (fixed) fixed.addEventListener('change', update);
            if (area) area.addEventListener('change', update);
            if (whole) whole.addEventListener('change', update);
            if (maximum) maximum.addEventListener('change', update);
            update();
        }
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
    else initialize();
})();
