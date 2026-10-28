(() => {
    'use strict';

    window.SkinaliAdminOrder = {
        initialize({ container, itemSelector, handleSelector, getId, onChange, canMove = () => true }) {
            const items = () => Array.from(container.children).filter((item) => item.matches(itemSelector));
            let dragged = null;
            let previous = [];
            const changed = (before) => {
                const after = items();
                return before.length !== after.length || before.some((item, index) => after[index] !== item);
            };
            const initialized = new WeakSet();
            const refresh = () => {
                const current = items();
                current.forEach((item) => {
                    const handle = item.querySelector(handleSelector);
                    if (!handle) return;
                    handle.disabled = current.length < 2;
                    handle.draggable = current.length > 1;
                    if (initialized.has(handle)) return;
                    initialized.add(handle);
                    handle.addEventListener('dragstart', (event) => {
                        if (!canMove()) {
                            event.preventDefault();
                            return;
                        }
                        dragged = item;
                        previous = items();
                        item.classList.add('admin-order-dragging');
                        event.dataTransfer.effectAllowed = 'move';
                        event.dataTransfer.setData('text/plain', String(getId(item)));
                    });
                    handle.addEventListener('dragend', () => {
                        if (!dragged) return;
                        dragged.classList.remove('admin-order-dragging');
                        dragged = null;
                        if (changed(previous)) onChange(previous);
                    });
                    handle.addEventListener('keydown', (event) => {
                        if (!canMove() || !['ArrowUp', 'ArrowDown'].includes(event.key)) return;
                        const before = items();
                        const index = before.indexOf(item);
                        const sibling = before[index + (event.key === 'ArrowUp' ? -1 : 1)];
                        if (!sibling) return;
                        event.preventDefault();
                        if (event.key === 'ArrowUp') container.insertBefore(item, sibling);
                        else container.insertBefore(sibling, item);
                        handle.focus();
                        onChange(before);
                    });
                });
            };
            refresh();
            container.addEventListener('dragover', (event) => {
                if (!dragged || !canMove()) return;
                const target = event.target.closest(itemSelector);
                if (!target || target === dragged || target.parentNode !== container) return;
                event.preventDefault();
                const bounds = target.getBoundingClientRect();
                container.insertBefore(dragged, event.clientY > bounds.top + bounds.height / 2 ? target.nextElementSibling : target);
            });
            return { refresh };
        },
    };
})();
