(() => {
    'use strict';

    const liftingType = document.getElementById('id_lifting_type');
    const stairRows = document.querySelectorAll('[data-stair-field]');
    if (liftingType) {
        const updateStairFields = (fillDefaults = false) => {
            const useStairs = liftingType.value === 'stairs';
            stairRows.forEach((row) => {
                row.hidden = !useStairs;
                row.querySelectorAll('input').forEach((input) => {
                    input.disabled = !useStairs;
                    if (useStairs && fillDefaults && input.value.trim() === '') input.value = input.dataset.initialValue || '1';
                });
            });
        };
        liftingType.addEventListener('change', () => updateStairFields(true));
        updateStairFields();
    }

    document.querySelectorAll('.calculation-service').forEach((service) => {
        const selected = service.querySelector('[data-service-select] input[type="checkbox"]');
        const quantity = service.querySelector('[data-service-quantity]');
        if (!selected || !quantity) return;
        const update = () => {
            quantity.hidden = !selected.checked;
            quantity.querySelectorAll('input').forEach((input) => { input.disabled = !selected.checked; });
        };
        selected.addEventListener('change', update);
        update();
    });

    const table = document.getElementById('calculation-panels');
    const template = document.getElementById('empty-calculation-panel');
    if (!table || !template) return;

    const total = document.getElementById(`id_${table.dataset.prefix}-TOTAL_FORMS`);
    if (!total) return;
    const limit = Number(table.dataset.limit);
    const body = table.tBodies[0];

    const expandLastPanel = (event) => {
        const selectedRow = event.target.closest('tr');
        if (!selectedRow || selectedRow !== body.lastElementChild) return;
        if (event.type === 'focusin' && !event.target.matches('input[type="number"]')) return;
        if (selectedRow.querySelector('input[name$="-DELETE"]').checked) return;
        const index = Number(total.value);
        if (!Number.isInteger(index) || index < 0 || index >= limit) return;
        const rowTemplate = document.createElement('template');
        rowTemplate.innerHTML = template.innerHTML.replaceAll('__prefix__', String(index));
        const row = rowTemplate.content.querySelector('tr');
        row.querySelector('.panel-number').textContent = String(index + 1);
        body.append(row);
        total.value = String(index + 1);
    };
    body.addEventListener('click', expandLastPanel);
    body.addEventListener('focusin', expandLastPanel);
})();
