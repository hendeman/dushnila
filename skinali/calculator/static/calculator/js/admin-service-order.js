(() => {
    'use strict';

    const initialize = () => {
        const container = document.querySelector('[data-service-order-items]');
        if (!container) return;
        const cards = () => Array.from(container.querySelectorAll('[data-service-card]'));
        const position = (card) => card.querySelector('input[name$="-position"]');
        const ordered = cards().sort((first, second) => Number(position(first).value) - Number(position(second).value));
        ordered.forEach((card) => container.appendChild(card));
        window.SkinaliAdminOrder.initialize({
            container,
            itemSelector: '[data-service-card]',
            handleSelector: '[data-service-order-handle]',
            getId: (card) => card.dataset.serviceId,
            onChange: () => {
                cards().forEach((card, index) => { position(card).value = String(index + 1); });
                document.getElementById('service-order-status').textContent = 'Порядок изменён. Нажмите «Сохранить».';
            },
        });
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
    else initialize();
})();
