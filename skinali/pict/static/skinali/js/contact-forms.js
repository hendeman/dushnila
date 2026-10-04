(() => {
  const callbackDialog = document.getElementById('callback-dialog');
  const purchaseDialog = document.getElementById('image-purchase-dialog');
  const purchaseForm = purchaseDialog?.querySelector('[data-contact-form]');
  const purchaseNumber = purchaseDialog?.querySelector('[data-image-purchase-number]');
  const purchasePictInput = purchaseForm?.querySelector('[data-image-purchase-pict]');
  const contactToast = document.querySelector('[data-contact-success-toast]');
  const contactMessage = contactToast?.querySelector('[data-contact-success-message]');
  const CONTACT_TOAST_DURATION_MS = 3000;
  const CONTACT_TOAST_MESSAGES = {
    warning: 'Проверьте выделенные поля',
    error: 'Проверьте интернет-соединение'
  };
  let contactToastTimer = null;
  let contactToastTransitionTimer = null;

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

  function hideContactToast() {
    if (!contactToast || contactToast.hidden) {
      return;
    }

    window.clearTimeout(contactToastTimer);
    window.clearTimeout(contactToastTransitionTimer);
    contactToast.classList.remove('is-visible');
    contactToastTransitionTimer = window.setTimeout(() => {
      if (!contactToast.classList.contains('is-visible')) {
        contactToast.hidden = true;
      }
    }, 180);
  }

  function showContactToast(message, kind = 'success', form = null) {
    if (!contactToast || !contactMessage) {
      return;
    }

    window.clearTimeout(contactToastTimer);
    window.clearTimeout(contactToastTransitionTimer);

    const dialog = form?.closest('dialog');
    const toastHost = dialog?.open ? dialog : document.body;
    if (contactToast.parentElement !== toastHost) {
      toastHost.append(contactToast);
    }

    const messageLines = String(message || '').split(/\r?\n/).filter(Boolean);
    contactMessage.replaceChildren(...messageLines.map((line) => {
      const span = document.createElement('span');
      span.textContent = line;
      return span;
    }));

    contactToast.style.setProperty('--contact-toast-duration', `${CONTACT_TOAST_DURATION_MS}ms`);
    contactToast.classList.remove('is-visible', 'contact-toast--warning', 'contact-toast--error');
    if (kind !== 'success') {
      contactToast.classList.add(`contact-toast--${kind}`);
    }
    contactToast.hidden = false;
    void contactToast.offsetWidth;
    contactToast.classList.add('is-visible');

    contactToastTimer = window.setTimeout(hideContactToast, CONTACT_TOAST_DURATION_MS);
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

  contactToast?.querySelector('[data-contact-toast-close]')?.addEventListener('click', hideContactToast);

  document.querySelectorAll('.contact-dialog').forEach((dialog) => {
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) {
        dialog.close();
      }
    });
  });

  document.querySelectorAll('[data-contact-form]').forEach((form) => {
    let validationToastQueued = false;
    form.addEventListener('invalid', (event) => {
      const fieldName = event.target.dataset.fieldName;
      if (!fieldName) {
        return;
      }
      event.preventDefault();
      showFieldErrors(form, fieldName, [event.target.validationMessage]);
      if (!validationToastQueued) {
        validationToastQueued = true;
        showContactToast(CONTACT_TOAST_MESSAGES.warning, 'warning', form);
        window.setTimeout(() => { validationToastQueued = false; }, 0);
      }
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

        if (!response.ok || !result.ok) {
          Object.entries(result.errors || {}).forEach(([fieldName, messages]) => {
            showFieldErrors(form, fieldName, messages);
          });
          const kind = response.status === 422 ? 'warning' : 'error';
          showContactToast(CONTACT_TOAST_MESSAGES[kind], kind, form);
          return;
        }

        form.reset();
        clearAllErrors(form);

        const parentDialog = form.closest('dialog');
        if (parentDialog?.open) {
          parentDialog.close();
        }
        showContactToast(result.message, 'success', form);
      } catch (error) {
        showFieldErrors(form, '__all__', [CONTACT_TOAST_MESSAGES.error]);
        showContactToast(CONTACT_TOAST_MESSAGES.error, 'error', form);
      } finally {
        submitButton.disabled = false;
        form.removeAttribute('aria-busy');
      }
    });
  });
})();
