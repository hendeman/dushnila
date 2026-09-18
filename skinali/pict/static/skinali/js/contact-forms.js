(() => {
  const callbackDialog = document.getElementById('callback-dialog');
  const purchaseDialog = document.getElementById('image-purchase-dialog');
  const purchaseForm = purchaseDialog?.querySelector('[data-contact-form]');
  const purchaseNumber = purchaseDialog?.querySelector('[data-image-purchase-number]');
  const purchasePictInput = purchaseForm?.querySelector('[data-image-purchase-pict]');
  const successToast = document.querySelector('[data-contact-success-toast]');
  const successMessage = successToast?.querySelector('[data-contact-success-message]');
  let successToastTimer = null;
  let successToastTransitionTimer = null;

  function openDialog(dialog) {
    if (!dialog || dialog.open) {
      return;
    }
    dialog.showModal();
  }

  function closeDialog(button) {
    const dialog = button.closest('dialog');
    if (dialog?.open) {
      dialog.close();
    }
  }

  function showSuccessToast(message) {
    if (!successToast || !successMessage) {
      return;
    }

    window.clearTimeout(successToastTimer);
    window.clearTimeout(successToastTransitionTimer);

    const messageLines = String(message || '').split(/\r?\n/).filter(Boolean);
    successMessage.replaceChildren(...messageLines.map((line) => {
      const span = document.createElement('span');
      span.textContent = line;
      return span;
    }));

    successToast.hidden = false;
    window.requestAnimationFrame(() => {
      successToast.classList.add('is-visible');
    });

    successToastTimer = window.setTimeout(() => {
      successToast.classList.remove('is-visible');
      successToastTransitionTimer = window.setTimeout(() => {
        if (!successToast.classList.contains('is-visible')) {
          successToast.hidden = true;
        }
      }, 180);
    }, 2000);
  }

  function getErrorBox(form, fieldName) {
    return form.querySelector(`[data-form-errors="${fieldName}"]`);
  }

  function clearFieldErrors(form, fieldName) {
    const errorBox = getErrorBox(form, fieldName);
    if (errorBox) {
      errorBox.replaceChildren();
      errorBox.hidden = true;
    }

    const field = form.querySelector(`[data-field-name="${fieldName}"]`);
    if (field) {
      field.removeAttribute('aria-invalid');
    }
  }

  function clearAllErrors(form) {
    form.querySelectorAll('[data-form-errors]').forEach((errorBox) => {
      errorBox.replaceChildren();
      errorBox.hidden = true;
    });
    form.querySelectorAll('[aria-invalid="true"]').forEach((field) => {
      field.removeAttribute('aria-invalid');
    });
  }

  function showFieldErrors(form, fieldName, messages) {
    const errorBox = getErrorBox(form, fieldName);
    if (!errorBox) {
      return;
    }

    errorBox.replaceChildren();
    messages.forEach((message) => {
      const paragraph = document.createElement('p');
      paragraph.textContent = message;
      errorBox.appendChild(paragraph);
    });
    errorBox.hidden = false;

    const field = form.querySelector(`[data-field-name="${fieldName}"]`);
    if (field) {
      field.setAttribute('aria-invalid', 'true');
    }
  }

  // Делегирование также обслуживает кнопки из динамических подписей Fancybox.
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-callback-open]');
    if (!button || !callbackDialog) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    openDialog(callbackDialog);
  });

  // Кнопки находятся в шаблонах подписей Fancybox и появляются в DOM динамически.
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-image-purchase-open]');
    if (!button || !purchaseDialog || !purchasePictInput) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    purchasePictInput.value = button.dataset.pictId || '';
    if (purchaseNumber) {
      purchaseNumber.textContent = button.dataset.imageNumber || '—';
    }
    clearFieldErrors(purchaseForm, 'pict_id');
    openDialog(purchaseDialog);
  });

  document.querySelectorAll('[data-contact-dialog-close]').forEach((button) => {
    button.addEventListener('click', () => closeDialog(button));
  });

  document.querySelectorAll('.contact-dialog').forEach((dialog) => {
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) {
        dialog.close();
      }
    });
  });

  document.querySelectorAll('[data-contact-form]').forEach((form) => {
    form.addEventListener('invalid', (event) => {
      const fieldName = event.target.dataset.fieldName;
      if (!fieldName) {
        return;
      }
      event.preventDefault();
      showFieldErrors(form, fieldName, [event.target.validationMessage]);
    }, true);

    form.querySelectorAll('[data-field-name]').forEach((field) => {
      field.addEventListener('input', () => {
        clearFieldErrors(form, field.dataset.fieldName);
      });
    });

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      clearAllErrors(form);

      const submitButton = form.querySelector('[type="submit"]');
      submitButton.disabled = true;
      form.setAttribute('aria-busy', 'true');

      try {
        const response = await fetch(form.action, {
          method: 'POST',
          body: new FormData(form),
          credentials: 'same-origin',
          headers: {
            'X-Requested-With': 'XMLHttpRequest'
          }
        });
        const result = await response.json();

        if (!result.ok) {
          Object.entries(result.errors || {}).forEach(([fieldName, messages]) => {
            showFieldErrors(form, fieldName, messages);
          });
          return;
        }

        form.reset();
        clearAllErrors(form);

        const parentDialog = form.closest('dialog');
        if (parentDialog?.open) {
          parentDialog.close();
        }
        showSuccessToast(result.message);
      } catch (error) {
        showFieldErrors(form, '__all__', [
          'Не удалось отправить форму. Проверьте соединение и попробуйте ещё раз.'
        ]);
      } finally {
        submitButton.disabled = false;
        form.removeAttribute('aria-busy');
      }
    });
  });
})();
