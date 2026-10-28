(() => {
    'use strict';

    const showStatus = (container, message, error = false) => {
        let status = container.querySelector('[data-price-order-status]');
        if (!status) {
            status = document.createElement('p');
            status.dataset.priceOrderStatus = '';
            status.setAttribute('role', 'status');
            container.prepend(status);
        }
        status.className = `price-table-order-status${error ? ' price-table-order-status--error' : ''}`;
        status.textContent = message;
    };

    const initializeList = () => {
        const handles = [...document.querySelectorAll('[data-price-table-id]')];
        if (handles.length < 2) return;
        const container = handles[0].closest('tbody');
        const form = document.getElementById('changelist-form');
        let saving = false;
        window.SkinaliAdminOrder.initialize({
            container,
            itemSelector: 'tr',
            handleSelector: '[data-price-table-id]',
            getId: (row) => row.querySelector('[data-price-table-id]').dataset.priceTableId,
            canMove: () => !saving,
            onChange: async (previous) => {
                saving = true;
                handles.forEach((handle) => { handle.disabled = true; handle.draggable = false; });
                try {
                    const response = await fetch(handles[0].dataset.reorderUrl, {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': form.querySelector('[name="csrfmiddlewaretoken"]').value,
                        },
                        body: JSON.stringify({ordered_ids: [...container.querySelectorAll('[data-price-table-id]')]
                            .map((handle) => Number(handle.dataset.priceTableId))}),
                    });
                    if (!response.ok || !(await response.json()).saved) throw new Error();
                    showStatus(form.parentNode, 'Порядок таблиц сохранён.');
                } catch {
                    previous.forEach((row) => container.appendChild(row));
                    showStatus(form.parentNode, 'Порядок не сохранён. Обновите страницу и повторите попытку.', true);
                } finally {
                    saving = false;
                    handles.forEach((handle) => { handle.disabled = false; handle.draggable = true; });
                }
            },
        });
    };

    const initializeRows = () => {
        const group = document.getElementById('rows-group');
        if (!group) return;
        const container = group.querySelector('tbody');
        const selector = 'tr.form-row:not(.empty-form)';
        const rows = () => [...container.children].filter((row) => row.matches(selector));
        const position = (row) => row.querySelector('input[name$="-position"]');
        const isEmpty = (row) => !row.querySelector('input[name$="-id"]').value
            && ![...row.querySelectorAll('textarea')].some((field) => field.value.trim());
        const emptyTemplate = container.querySelector('.empty-form');
        rows().sort((first, second) => Number(isEmpty(first)) - Number(isEmpty(second))
            || Number(position(first).value) - Number(position(second).value))
            .forEach((row) => container.insertBefore(row, emptyTemplate));
        const updatePositions = () => rows().forEach((row, index) => { position(row).value = String(index + 1); });
        const prepareSubmit = () => {
            updatePositions();
            // Django перенумеровывает формы после удаления новой строки. Для POST
            // сохранённые объекты должны оставаться в начальных INITIAL_FORMS.
            const hasId = (row) => Boolean(row.querySelector('input[name$="-id"]').value);
            const forms = rows();
            [...forms.filter(hasId), ...forms.filter((row) => !hasId(row))].forEach((row, index) => {
                for (const element of [row, ...row.querySelectorAll('*')]) {
                    for (const attribute of ['name', 'id', 'for', 'aria-describedby', 'aria-labelledby']) {
                        const value = element.getAttribute(attribute);
                        if (value) element.setAttribute(attribute, value.replace(/rows-\d+(?=-|$)/g, `rows-${index}`));
                    }
                }
            });
        };
        const controller = window.SkinaliAdminOrder.initialize({
            container,
            itemSelector: selector,
            handleSelector: '[data-price-row-order]',
            getId: (row) => row.id,
            onChange: () => {
                updatePositions();
                showStatus(group, 'Порядок строк изменён. Нажмите «Сохранить».');
            },
        });
        for (const name of ['formset:added', 'formset:removed']) {
            document.addEventListener(name, (event) => {
                if (event.detail.formsetName !== 'rows') return;
                updatePositions();
                controller.refresh();
            });
        }
        group.closest('form').addEventListener('submit', prepareSubmit);
    };

    const initialize = () => { initializeList(); initializeRows(); };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
    else initialize();
})();
