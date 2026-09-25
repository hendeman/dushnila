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
		let draggedRow = null;
		let orderBeforeDrag = [];
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

		handles.forEach((handle) => {
			handle.addEventListener('dragstart', (event) => {
				draggedRow = handle.closest('tr');
				orderBeforeDrag = Array.from(tbody.children);
				draggedRow.classList.add('category-order-dragging');
				event.dataTransfer.effectAllowed = 'move';
				event.dataTransfer.setData('text/plain', handle.dataset.categoryId);
			});

			handle.addEventListener('dragend', () => {
				if (!draggedRow) {
					return;
				}
				draggedRow.classList.remove('category-order-dragging');
				const changed = orderBeforeDrag.some(
					(row, index) => tbody.children[index] !== row
				);
				if (changed) {
					saveOrder(orderBeforeDrag);
				}
				draggedRow = null;
			});

			handle.addEventListener('keydown', (event) => {
				if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') {
					return;
				}
				const row = handle.closest('tr');
				const previousRows = Array.from(tbody.children);
				const sibling = event.key === 'ArrowUp'
					? row.previousElementSibling
					: row.nextElementSibling;
				if (!sibling || !sibling.querySelector('.category-order-handle')) {
					return;
				}
				event.preventDefault();
				if (event.key === 'ArrowUp') {
					tbody.insertBefore(row, sibling);
				} else {
					tbody.insertBefore(sibling, row);
				}
				handle.focus();
				saveOrder(previousRows);
			});
		});

		tbody.addEventListener('dragover', (event) => {
			if (!draggedRow) {
				return;
			}
			const targetRow = event.target.closest('tr');
			if (
				!targetRow
				|| targetRow === draggedRow
				|| !targetRow.querySelector('.category-order-handle')
			) {
				return;
			}
			event.preventDefault();
			const bounds = targetRow.getBoundingClientRect();
			const insertAfter = event.clientY > bounds.top + bounds.height / 2;
			tbody.insertBefore(
				draggedRow,
				insertAfter ? targetRow.nextElementSibling : targetRow
			);
		});
	}

	document.addEventListener('DOMContentLoaded', initializeCategoryOrder);
}());
