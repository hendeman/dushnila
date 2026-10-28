(function () {
	'use strict';

	function getCsrfToken() {
		const input = document.querySelector('[name="csrfmiddlewaretoken"]');
		if (input) {
			return input.value;
		}
		const cookie = document.cookie
			.split('; ')
			.find((item) => item.startsWith('csrftoken='));
		return cookie ? decodeURIComponent(cookie.slice('csrftoken='.length)) : '';
	}

	function showStatus(message, type) {
		let status = document.getElementById('category-order-status');
		if (!status) {
			status = document.createElement('div');
			status.id = 'category-order-status';
			status.setAttribute('role', 'status');
			const results = document.getElementById('changelist-form');
			results.parentNode.insertBefore(status, results);
		}
		status.className = `category-order-status--${type}`;
		status.textContent = message;
	}

	function initializeCategoryOrder() {
		const handles = Array.from(
			document.querySelectorAll('.category-order-handle[data-category-id]')
		);
		if (handles.length < 2) {
			return;
		}

		const rows = handles.map((handle) => handle.closest('tr'));
		const tbody = rows[0].parentNode;
		let saving = false;

		function getOrderedIds() {
			return Array.from(tbody.querySelectorAll('.category-order-handle'))
				.map((handle) => Number(handle.dataset.categoryId));
		}

		function restoreRows(rowOrder) {
			rowOrder.forEach((row) => tbody.appendChild(row));
		}

		async function saveOrder(previousRows) {
			if (saving) {
				return;
			}
			saving = true;
			handles.forEach((handle) => {
				handle.disabled = true;
				handle.draggable = false;
			});
			try {
				const response = await fetch(`${window.location.pathname}reorder/`, {
					method: 'POST',
					headers: {
						'Content-Type': 'application/json',
						'X-CSRFToken': getCsrfToken(),
					},
					body: JSON.stringify({ordered_ids: getOrderedIds()}),
				});
				if (!response.ok) {
					throw new Error('Не удалось сохранить порядок.');
				}
				showStatus('Порядок категорий сохранён.', 'success');
			} catch (error) {
				restoreRows(previousRows);
				showStatus(
					'Порядок не сохранён. Обновите страницу и повторите попытку.',
					'error'
				);
			} finally {
				saving = false;
				handles.forEach((handle) => {
					handle.disabled = false;
					handle.draggable = true;
				});
			}
		}

        window.SkinaliAdminOrder.initialize({
            container: tbody,
            itemSelector: 'tr',
            handleSelector: '.category-order-handle',
            getId: (row) => row.querySelector('.category-order-handle').dataset.categoryId,
            onChange: saveOrder,
            canMove: () => !saving,
        });
	}

	document.addEventListener('DOMContentLoaded', initializeCategoryOrder);
}());
