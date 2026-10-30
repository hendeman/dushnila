(() => {
    'use strict';

    const initialize = () => {
        const modes = document.querySelectorAll('input[name="material_discount_mode"]');
        if (!modes.length) return;
        const tables = document.querySelectorAll('[data-discount-mode]');
        const errors = document.querySelectorAll('[data-discount-errors]');
        const update = () => {
            const selected = Array.from(modes).find(input => input.checked)?.value;
            tables.forEach(table => { table.hidden = table.dataset.discountMode !== selected; });
            errors.forEach(note => { note.hidden = note.dataset.discountErrors === selected; });
        };
        modes.forEach(input => input.addEventListener('change', update));
        update();
    };

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
    else initialize();
})();
