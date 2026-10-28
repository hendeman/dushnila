(() => {
    'use strict';

    const form = document.getElementById('price-calculator');
    if (!form) return;
    const config = JSON.parse(document.getElementById('price-calculator-config').textContent);
    const panels = document.getElementById('price-panels');
    const template = document.getElementById('price-panel-template');
    const addButton = document.getElementById('price-add-panel');
    const shareBlock = form.querySelector('[data-price-share]');
    const shareToggle = shareBlock?.querySelector('[data-share-toggle]');
    const orderButton = document.getElementById('price-order');
    const orderDialog = document.getElementById('calculator-order-dialog');
    const orderUrl = orderDialog?.querySelector('[data-calculation-url]');
    const orderForm = orderDialog?.querySelector('[data-contact-form]');
    const orderSubmit = orderForm?.querySelector('[type="submit"]');
    const orderStatus = orderDialog?.querySelector('[data-order-status]');
    const orderRetry = orderDialog?.querySelector('[data-order-retry]');
    const SHARE_TIMEOUT_MS = 10000;
    let shareRequest = null;
    let orderPreparation = 0;
    let currentInput = null;
    let shareRevision = 0;
    const output = (id) => document.getElementById(`price-${id}`);
    const money = new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 0});
    let nextPanel = 0;
    const grouped = (value) => money.format(BigInt(value));
    const fraction = (value, digits = config.area_decimal_places) => {
        const negative = String(value).startsWith('-');
        const [whole, tail = ''] = String(value).replace(/^-/, '').split('.');
        const formatted = tail.slice(0, digits).padEnd(digits, '0');
        return `${negative ? '−' : ''}${grouped(whole)}${formatted ? `,${formatted}` : ''}`;
    };

    function fitAmount() {
        const amount = output('amount');
        amount.style.removeProperty('--price-amount-font-size');
        const width = amount.querySelector('.price-total__values').getBoundingClientRect().width;
        if (amount.clientWidth > 0 && width > amount.clientWidth) {
            const fontSize = parseFloat(window.getComputedStyle(amount).fontSize);
            amount.style.setProperty('--price-amount-font-size', `${fontSize * amount.clientWidth / width}px`);
        }
    }

    function updateConditionalFields() {
        form.querySelectorAll('[data-service-id]').forEach((row) => {
            const checkbox = row.querySelector('input[type="checkbox"]');
            const details = row.querySelector('.price-service__details');
            if (!checkbox || !details) return;
            details.hidden = !checkbox.checked;
            details.querySelectorAll('input').forEach((input) => { input.disabled = !checkbox.checked; });
        });
        const stairs = output('stairs');
        if (stairs) {
            stairs.hidden = output('lifting').value !== 'stairs';
            stairs.querySelectorAll('input, select').forEach((input) => { input.disabled = stairs.hidden; });
        }
    }

    function update() {
        orderPreparation += 1;
        cancelShareRequest();
        currentInput = null;
        if (orderButton) orderButton.disabled = true;
        if (orderUrl) orderUrl.value = '';
        setOrderState('idle');
        shareRevision += 1;
        if (shareBlock) {
            shareBlock.dataset.shareUrl = '';
            shareToggle.disabled = true;
            shareToggle.title = 'Заполните параметры, чтобы поделиться расчётом';
            shareToggle.setAttribute('aria-expanded', 'false');
            shareBlock.querySelector('[data-share-services]').hidden = true;
        }
        updateConditionalFields();
        form.querySelectorAll('input[type="number"][max]:not(:disabled)').forEach((input) => {
            if (Number(input.value) > Number(input.max)) {
                input.value = input.max;
            }
        });
        form.querySelectorAll('[aria-invalid]').forEach((input) => input.removeAttribute('aria-invalid'));
        try {
            const rows = Array.from(panels.children);
            const filled = rows.filter((row) => Array.from(row.querySelectorAll('input')).some((input) => input.value !== '' || input.validity.badInput));
            const invalid = Array.from(form.querySelectorAll('input, select')).filter((input) => {
                if (input.disabled) return false;
                if (input.closest('.price-panel') && !filled.includes(input.closest('.price-panel'))) return false;
                return !input.checkValidity() || (input.closest('.price-panel') && !input.value);
            });
            invalid.forEach((input) => input.setAttribute('aria-invalid', 'true'));
            if (invalid.length) throw new Error('Заполните выделенные поля. Размеры указываются целыми миллиметрами.');
            const data = {
                panels: filled.map((row) => ({width: row.querySelector('[data-width]').value, height: row.querySelector('[data-height]').value})),
                glass_type: output('glass_type')?.value,
                decoration_type: output('decoration_type')?.value,
                services: config.services.filter((service) => form.elements[`use_service_${service.id}`]?.checked)
                    .map((service) => ({id: service.id, quantity: form.elements[`service_quantity_${service.id}`]?.value || '1'})),
                stairs: output('lifting')?.value === 'stairs' ? {floor: output('floor').value, count: output('stair-count').value} : null,
            };
            const result = globalThis.SkinaliPrice.calculate(config, data);
            currentInput = data;
            if (orderButton) orderButton.disabled = false;
            if (shareToggle) {
                shareToggle.disabled = false;
                shareToggle.title = 'Поделиться расчётом по действующим тарифам';
            }
            output('total').textContent = grouped(result.total);
            output('old-total').textContent = grouped(result.comparison);
            const hasMarketing = Number(config.marketing_discount_percent) > 0 && BigInt(result.comparison) > BigInt(result.total);
            output('comparison').hidden = !hasMarketing;
            output('area').textContent = `Панелей: ${result.panel_count} · Общая площадь: ${fraction(result.area)} м²`;
            output('status').textContent = '';
            output('status').hidden = true;
        } catch (error) {
            output('total').textContent = '—';
            output('status').textContent = error.message;
            output('status').hidden = false;
            output('area').textContent = '';
            output('comparison').hidden = true;
        }
        if (orderDialog?.open) setOrderState('error', 'Параметры расчёта изменились. Повторите действие.');
        fitAmount();
    }

    function renumber() {
        Array.from(panels.children).forEach((row, index) => {
            row.querySelector('[data-panel-title]').textContent = `${index + 1}-я панель`;
            row.querySelector('[data-remove-panel]').setAttribute('aria-label', `Удалить панель ${index + 1}`);
            row.querySelector('[data-remove-panel]').hidden = panels.children.length === 1;
            row.querySelector('[data-width-caption]').textContent = `Ширина панели ${index + 1}, мм`;
            row.querySelector('[data-height-caption]').textContent = `Высота панели ${index + 1}, мм`;
        });
        addButton.disabled = panels.children.length >= config.max_panels;
        output('panel-limit').hidden = !addButton.disabled;
    }

    function addPanel(focus = true) {
        if (panels.children.length >= config.max_panels) return;
        const row = template.content.firstElementChild.cloneNode(true);
        nextPanel += 1;
        for (const dimension of ['width', 'height']) {
            const input = row.querySelector(`[data-${dimension}]`);
            input.id = `price-panel-${nextPanel}-${dimension}`;
            input.name = `panel_${nextPanel}_${dimension}`;
            row.querySelector(`[data-${dimension}-label]`).htmlFor = input.id;
        }
        panels.append(row);
        renumber();
        if (focus) row.querySelector('input').focus();
        return row;
    }

    function cancelShareRequest() {
        const request = shareRequest;
        shareRequest = null;
        request?.cancel(new Error('Параметры расчёта изменились. Повторите действие.'));
    }

    function prepareCalculationShare() {
        if (shareBlock.dataset.shareUrl) return Promise.resolve(shareBlock.dataset.shareUrl);
        if (!currentInput) return Promise.reject(new Error('Сначала заполните параметры расчёта.'));
        if (shareRequest) return shareRequest.promise;
        const revision = shareRevision;
        const body = JSON.stringify(currentInput);
        const controller = new AbortController();
        const request = {};
        const stopped = new Promise((_, reject) => {
            request.cancel = (error) => { reject(error); controller.abort(); };
        });
        const timeout = setTimeout(() => {
            request.cancel(new Error('Ответ не получен вовремя. Попробуйте ещё раз.'));
        }, SHARE_TIMEOUT_MS);
        const response = (async () => {
            let received, result;
            try {
                received = await fetch(shareBlock.dataset.shareEndpoint, {
                    method: 'POST', credentials: 'same-origin', mode: 'same-origin', redirect: 'error',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content,
                    },
                    body, signal: controller.signal,
                });
                result = await received.json();
            } catch (error) {
                throw new Error('Проверьте соединение и попробуйте ещё раз.');
            }
            if (!received.ok || typeof result?.url !== 'string' || !result.url) {
                throw new Error(result?.message || 'Не удалось подготовить расчёт. Попробуйте ещё раз.');
            }
            return result.url;
        })();
        shareRequest = request;
        request.promise = Promise.race([response, stopped]).then((url) => {
            if (controller.signal.aborted || revision !== shareRevision || shareRequest !== request) {
                throw new Error('Параметры расчёта изменились. Повторите действие.');
            }
            shareBlock.dataset.shareUrl = url;
            return url;
        }).finally(() => {
            clearTimeout(timeout);
            if (shareRequest === request) shareRequest = null;
        });
        return request.promise;
    }

    shareBlock?.addEventListener('share:prepare', (event) => {
        event.detail.promises.push(prepareCalculationShare());
    });

    function setOrderState(state, message = '') {
        if (!orderStatus || !orderForm || !orderSubmit) return;
        const labels = {
            loading: ['Подготавливаем расчёт…', 'Вы можете заполнить имя и телефон.'],
            ready: ['Расчёт готов', 'Отправим заявку вместе с вашим расчётом.'],
            error: ['Не удалось подготовить расчёт', message],
        };
        orderStatus.hidden = state === 'idle';
        orderStatus.dataset.state = state;
        orderStatus.setAttribute('role', state === 'error' ? 'alert' : 'status');
        orderStatus.setAttribute('aria-live', state === 'error' ? 'assertive' : 'polite');
        orderStatus.querySelector('[data-order-status-title]').textContent = labels[state]?.[0] || '';
        orderStatus.querySelector('[data-order-status-detail]').textContent = labels[state]?.[1] || '';
        orderStatus.querySelectorAll('[data-order-state-icon]').forEach((icon) => {
            icon.toggleAttribute('hidden', icon.dataset.orderStateIcon !== state);
        });
        orderRetry.hidden = state !== 'error';
        orderRetry.disabled = !currentInput;
        orderForm.dataset.submitBlocked = String(state !== 'ready');
        orderSubmit.disabled = state !== 'ready' || orderForm.getAttribute('aria-busy') === 'true';
    }

    async function prepareOrder() {
        if (!currentInput || !orderDialog?.open || !orderUrl || orderStatus?.dataset.state === 'loading') return;
        const attempt = ++orderPreparation;
        setOrderState('loading');
        try {
            const url = await prepareCalculationShare();
            if (attempt !== orderPreparation || !orderDialog.open) return;
            orderUrl.value = url;
            orderUrl.dispatchEvent(new Event('input', {bubbles: true}));
            setOrderState('ready');
        } catch (error) {
            if (attempt === orderPreparation && orderDialog.open) setOrderState('error', error.message);
        }
    }

    orderButton?.addEventListener('click', () => {
        if (!currentInput || !orderDialog || !orderUrl || orderDialog.open) return;
        orderDialog.showModal();
        orderDialog.querySelector('[data-field-name="name"]').focus();
        return prepareOrder();
    });
    orderRetry?.addEventListener('click', () => prepareOrder());
    orderDialog?.addEventListener('close', () => {
        orderPreparation += 1;
        if (orderUrl) orderUrl.value = '';
        setOrderState('idle');
    });

    function restoreCalculation(input) {
        input.panels.forEach((panel) => {
            const row = addPanel(false);
            row.querySelector('[data-width]').value = panel.width;
            row.querySelector('[data-height]').value = panel.height;
        });
        for (const name of ['glass_type', 'decoration_type']) {
            if (output(name)) output(name).value = input[name];
        }
        input.services.forEach((service) => {
            form.elements[`use_service_${service.id}`].checked = true;
            const quantity = form.elements[`service_quantity_${service.id}`];
            if (quantity) quantity.value = service.quantity;
        });
        if (input.stairs) {
            output('lifting').value = 'stairs';
            output('floor').value = input.stairs.floor;
            output('stair-count').value = input.stairs.count;
        }
    }

    addButton.addEventListener('click', () => { addPanel(); update(); });
    panels.addEventListener('click', (event) => {
        const button = event.target.closest('[data-remove-panel]');
        if (!button || panels.children.length === 1) return;
        const row = button.closest('.price-panel');
        const target = row.nextElementSibling || row.previousElementSibling;
        row.remove();
        renumber();
        target.querySelector('input').focus();
        update();
    });
    form.addEventListener('submit', (event) => { event.preventDefault(); update(); });
    form.addEventListener('input', update);
    form.addEventListener('change', (event) => {
        const input = event.target;
        if (input === output('floor') && !input.disabled && input.value !== ''
            && Number(input.value) < Number(input.min)) {
            input.value = input.min;
        }
        if (input.name?.startsWith('service_quantity_') && input.step === config.quantity_step
            && !input.disabled && input.value !== '' && input.checkValidity()) {
            input.value = Number(input.value).toFixed(config.quantity_decimal_places);
        }
        update();
    });
    window.addEventListener('resize', fitAmount);
    const initialInput = document.getElementById('price-initial-input');
    if (initialInput) restoreCalculation(JSON.parse(initialInput.textContent));
    else {
        addPanel(false);
        addPanel(false);
    }
    form.hidden = false;
    update();
})();
