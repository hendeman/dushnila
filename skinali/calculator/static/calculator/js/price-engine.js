(() => {
    'use strict';

    // Денежные вычисления идут в десятичной арифметике, без ошибок Number.
    const SCALE = 10n ** 50n;
    const decimal = (value) => {
        const text = String(value);
        if (!/^\d+(?:\.\d{1,50})?$/.test(text)) throw new Error('Укажите корректное число.');
        const [whole, fraction = ''] = text.split('.');
        return BigInt(whole) * SCALE + BigInt(fraction.padEnd(50, '0'));
    };
    const multiply = (left, right) => left * right / SCALE;
    const integer = (value, maximum, minimum = 1) => {
        if (!/^\d{1,9}$/.test(String(value)) || BigInt(value) < BigInt(minimum) || BigInt(value) > BigInt(maximum)) {
            throw new Error(`Укажите целое число от ${minimum} до ${maximum}.`);
        }
        return BigInt(value);
    };
    const text = (value) => {
        const sign = value < 0n ? '-' : '';
        const absolute = value < 0n ? -value : value;
        const fraction = (absolute % SCALE).toString().padStart(50, '0').replace(/0+$/, '');
        return `${sign}${absolute / SCALE}${fraction ? `.${fraction}` : ''}`;
    };
    const ceil = (numerator, denominator) => (numerator + denominator - 1n) / denominator;

    function weightedArea(area, percent, threshold) {
        if (percent === 0n || area <= threshold) return area;
        const ratio = SCALE - percent / 100n;
        let remaining = area / SCALE;
        let power = ratio;
        let sum = SCALE;
        let resultPower = SCALE;
        let resultSum = 0n;
        // Геометрическая сумма за O(log S), включая очень большие площади.
        while (remaining > 0n) {
            if (remaining % 2n) {
                resultSum += multiply(resultPower, sum);
                resultPower = multiply(resultPower, power);
            }
            sum += multiply(power, sum);
            power = multiply(power, power);
            remaining /= 2n;
        }
        return resultSum + multiply(area % SCALE, resultPower);
    }

    function calculate(config, input) {
        if (!Array.isArray(input.panels) || !input.panels.length) {
            throw new Error('Укажите размеры хотя бы одной панели.');
        }
        if (input.panels.length > config.max_panels) {
            throw new Error(`Можно рассчитать не более ${config.max_panels} панелей.`);
        }
        const rawArea = input.panels.reduce((sum, panel) => sum + (
            integer(panel.width, config.max_panel_dimension_mm) * integer(panel.height, config.max_panel_dimension_mm) * SCALE / 1000000n
        ), 0n);
        const areaStep = SCALE / (10n ** BigInt(config.area_decimal_places));
        const area = (rawArea + areaStep / 2n) / areaStep * areaStep;
        const lines = [];
        const add = (label, amount, included = false) => lines.push({label, amount, included});
        let materialPrice = 0n;
        for (const [field, label] of [['glass_type', 'Стекло'], ['decoration_type', 'Декорирование']]) {
            const group = config[field];
            const id = group.visible ? input[field] : group.default;
            const option = group.options.find((item) => String(item.id) === String(id));
            if (!option) throw new Error(`Выберите вариант: ${label.toLowerCase()}.`);
            const price = decimal(option.price);
            materialPrice += price;
            add(`${label}: ${option.name}`, multiply(area, price));
        }
        const weighted = weightedArea(area, decimal(config.area_discount_percent), decimal(config.area_discount_threshold));
        const discount = multiply(area - weighted, materialPrice);
        if (discount > 0n) add('Скидка на стекло и декорирование', -discount);
        if (config.stairs) {
            if (input.stairs) {
                const floor = integer(input.stairs.floor, config.max_stair_floor, config.min_stair_floor);
                const count = integer(input.stairs.count, config.stairs.rules.length);
                const rule = config.stairs.rules.find((item) => BigInt(item.count) === count);
                if (!rule) throw new Error('Выберите количество панелей для подъёма.');
                const extra = floor > BigInt(rule.floor) ? floor - BigInt(rule.floor) : 0n;
                add('Подъём по лестнице', decimal(config.stairs.base)
                    + extra * multiply(decimal(config.stairs.per_floor), decimal(rule.multiplier)));
            } else add('Стандартный подъём', 0n, true);
        }
        const selected = new Map((input.services || []).map((service) => [String(service.id), service.quantity]));
        for (const service of config.services) {
            if (!service.has_price) {
                add(service.name, 0n, true);
            } else if (selected.has(String(service.id))) {
                let quantity = SCALE;
                if (!service.fixed_price) {
                    if (service.use_panel_area) quantity = area;
                    else if (service.whole_quantity) quantity = integer(selected.get(String(service.id)), config.max_integer) * SCALE;
                    else {
                        const raw = String(selected.get(String(service.id)));
                        const pattern = new RegExp(`^\\d{1,9}(?:\\.\\d{1,${config.quantity_decimal_places}})?$`);
                        if (!pattern.test(raw)) throw new Error(`Проверьте количество: ${service.name}.`);
                        quantity = decimal(raw);
                        if (quantity <= 0n || quantity > decimal(config.max_quantity)) {
                            throw new Error(`Укажите количество больше нуля: ${service.name}.`);
                        }
                    }
                }
                if (!service.fixed_price && !service.use_panel_area && quantity > decimal(service.max_quantity)) {
                    throw new Error(`Укажите количество не больше ${service.max_quantity}: ${service.name}.`);
                }
                add(service.name, multiply(quantity, decimal(service.price)));
            }
        }
        const subtotal = lines.reduce((sum, line) => sum + line.amount, 0n);
        const total = ceil(subtotal, SCALE);
        const marketing = decimal(config.marketing_discount_percent);
        const comparison = ceil(total * 100n * SCALE, 100n * SCALE - marketing);
        return {
            area: text(area), subtotal: text(subtotal), total: String(total), comparison: String(comparison),
            materials_discount: text(discount), panel_count: input.panels.length,
            lines: lines.map((line) => ({...line, amount: text(line.amount)})),
        };
    }

    globalThis.SkinaliPrice = Object.freeze({calculate});
})();
