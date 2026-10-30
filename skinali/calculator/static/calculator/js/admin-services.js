(() => {
    'use strict';

    const initialize = () => {
        const name = document.getElementById('id_name');
        const priceLabel = document.getElementById('id_price_label');
        if (name && priceLabel) {
            const refreshPriceLabel = () => {
                const label = document.querySelector('label[for="id_price_per_unit"]');
                const text = priceLabel.value.trim() || 'Цена за одну единицу';
                if (label) label.textContent = text.endsWith(':') ? text : `${text}:`;
            };
            let automatic = priceLabel.value === '' || priceLabel.value === name.value;
            priceLabel.addEventListener('input', () => { automatic = priceLabel.value === ''; refreshPriceLabel(); });
            name.addEventListener('input', () => {
                if (automatic) priceLabel.value = name.value;
                refreshPriceLabel();
            });
            refreshPriceLabel();
        }
        const paid = document.getElementById('id_has_price');
        const types = document.querySelectorAll('input[name="calculation_type"]');
        const discount = document.getElementById('id_discount_percent');
        const price = document.getElementById('id_price_per_unit');
        const fixed = document.getElementById('id_fixed_price');
        const area = document.getElementById('id_use_panel_area');
        const whole = document.getElementById('id_whole_quantity');
        const maximum = document.getElementById('id_max_quantity');
        if (paid && price) {
            const update = () => {
                const isDiscount = Array.from(types).find(input => input.checked)?.value === 'order_discount';
                paid.closest('fieldset').hidden = isDiscount;
                paid.disabled = isDiscount;
                if (discount) {
                    discount.closest('.form-row').hidden = !isDiscount;
                    discount.disabled = !isDiscount;
                }
                if (priceLabel) {
                    priceLabel.closest('.form-row').hidden = !paid.checked;
                    priceLabel.disabled = isDiscount;
                }
                price.closest('.form-row').hidden = !paid.checked;
                price.disabled = isDiscount || !paid.checked;
                if (fixed) {
                    fixed.closest('.form-row').hidden = !paid.checked;
                    fixed.disabled = isDiscount;
                }
                const hideQuantity = isDiscount || !paid.checked || Boolean(fixed?.checked);
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
            types.forEach(input => input.addEventListener('change', update));
            if (fixed) fixed.addEventListener('change', update);
            if (area) area.addEventListener('change', update);
            if (whole) whole.addEventListener('change', update);
            if (maximum) maximum.addEventListener('change', update);
            update();
        }
        if (document.getElementById('calculator-service-editor-script')?.dataset.focusName === 'true') {
            name?.focus({preventScroll: true});
        }
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
    else initialize();
})();
