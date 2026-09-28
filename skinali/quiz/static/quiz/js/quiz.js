(() => {
  const dialog = document.querySelector('[data-site-quiz]');
  if (!dialog) {
    return;
  }

  const form = dialog.querySelector('[data-quiz-form]');
  const questionSteps = Array.from(dialog.querySelectorAll('[data-quiz-step]'));
  const contactStep = dialog.querySelector('[data-quiz-contact-step]');
  const successStep = dialog.querySelector('[data-quiz-success-step]');
  const navigation = dialog.querySelector('[data-quiz-navigation]');
  const backButton = dialog.querySelector('[data-quiz-back]');
  const nextButton = dialog.querySelector('[data-quiz-next]');
  const submitButton = dialog.querySelector('[data-quiz-submit]');
  const progressValue = dialog.querySelector('[data-quiz-progress-value]');
  const progressBar = dialog.querySelector('[data-quiz-progress-bar]');
  const carouselControllers = [];
  const reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  const triggerHash = dialog.dataset.triggerHash;
  const storagePrefix = `odium-quiz:${triggerHash}:`;
  const shownStorageKey = `${storagePrefix}shown-at`;
  const submittedStorageKey = `${storagePrefix}submitted`;
  const answerAutoAdvanceDelay = 3000;
  let currentQuestionIndex = 0;
  let autoOpenTimer = null;
  let answerAutoAdvanceTimer = null;
  let openedOnThisPage = false;

  function readStorage(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (error) {
      return null;
    }
  }

  function writeStorage(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (error) {
      // Квиз остаётся рабочим в приватном режиме и при запрете localStorage.
    }
  }

  function cancelAnswerAutoAdvance() {
    window.clearTimeout(answerAutoAdvanceTimer);
    answerAutoAdvanceTimer = null;
  }

  function scheduleAnswerAutoAdvance(field) {
    cancelAnswerAutoAdvance();
    const step = field.closest('[data-quiz-step]');
    if (!step) {
      return;
    }
    answerAutoAdvanceTimer = window.setTimeout(() => {
      answerAutoAdvanceTimer = null;
      if (
        dialog.open
        && field.checked
        && questionSteps[currentQuestionIndex] === step
      ) {
        nextButton.click();
      }
    }, answerAutoAdvanceDelay);
  }

  function getErrorBox(fieldName) {
    return Array.from(dialog.querySelectorAll('[data-quiz-errors]')).find(
      (box) => box.dataset.quizErrors === fieldName
    );
  }

  function clearFieldError(fieldName) {
    const errorBox = getErrorBox(fieldName);
    if (errorBox) {
      errorBox.replaceChildren();
      errorBox.hidden = true;
    }
    form.querySelectorAll('[data-field-name]').forEach((field) => {
      if (field.dataset.fieldName === fieldName) {
        field.removeAttribute('aria-invalid');
      }
    });
  }

  function clearAllErrors() {
    dialog.querySelectorAll('[data-quiz-errors]').forEach((box) => {
      box.replaceChildren();
      box.hidden = true;
    });
    form.querySelectorAll('[aria-invalid="true"]').forEach((field) => {
      field.removeAttribute('aria-invalid');
    });
  }

  function showFieldErrors(fieldName, messages) {
    const errorBox = getErrorBox(fieldName);
    if (!errorBox) {
      return;
    }
    errorBox.replaceChildren(...messages.map((message) => {
      const paragraph = document.createElement('p');
      paragraph.textContent = message;
      return paragraph;
    }));
    errorBox.hidden = false;
    form.querySelectorAll('[data-field-name]').forEach((field) => {
      if (field.dataset.fieldName === fieldName) {
        field.setAttribute('aria-invalid', 'true');
      }
    });
  }

  function focusStepHeading(step) {
    const heading = step?.querySelector('h2');
    if (heading) {
      window.requestAnimationFrame(() => heading.focus({ preventScroll: true }));
    }
  }

  function setupImageCarousel(carousel) {
    const track = carousel.querySelector('[data-quiz-carousel-track]');
    const previousButton = carousel.querySelector('[data-quiz-carousel-previous]');
    const nextButton = carousel.querySelector('[data-quiz-carousel-next]');
    const progress = carousel.querySelector('[data-quiz-carousel-progress]');
    if (!track || !previousButton || !nextButton || !progress) {
      return;
    }

    let updateFrame = null;
    let dragPointerId = null;
    let dragStartX = 0;
    let dragStartScrollLeft = 0;
    let dragged = false;
    let suppressClick = false;
    let resizeObserver = null;

    function update() {
      updateFrame = null;
      const maxScrollLeft = Math.max(0, track.scrollWidth - track.clientWidth);
      const scrollLeft = Math.max(0, Math.min(track.scrollLeft, maxScrollLeft));
      const hasOverflow = maxScrollLeft > 2;
      const visibleProgress = track.scrollWidth > 0
        ? Math.min(1, (scrollLeft + track.clientWidth) / track.scrollWidth)
        : 1;

      progress.style.transform = `scaleX(${visibleProgress})`;
      previousButton.hidden = !hasOverflow;
      nextButton.hidden = !hasOverflow;
      previousButton.disabled = !hasOverflow || scrollLeft <= 2;
      nextButton.disabled = !hasOverflow || scrollLeft >= maxScrollLeft - 2;
    }

    function requestUpdate() {
      if (updateFrame !== null) {
        return;
      }
      updateFrame = window.requestAnimationFrame(update);
    }

    function getScrollStep() {
      const cards = track.querySelectorAll('.site-quiz-image-option');
      if (cards.length > 1) {
        return Math.max(1, cards[1].offsetLeft - cards[0].offsetLeft);
      }
      return Math.max(1, Math.round(track.clientWidth * .85));
    }

    function scrollByCard(direction) {
      track.scrollBy({
        left: direction * getScrollStep(),
        behavior: reducedMotionQuery.matches ? 'auto' : 'smooth'
      });
    }

    function finishDrag(event) {
      if (dragPointerId !== event.pointerId) {
        return;
      }
      if (dragged) {
        suppressClick = true;
        window.setTimeout(() => {
          suppressClick = false;
        }, 0);
      }
      if (track.hasPointerCapture(event.pointerId)) {
        track.releasePointerCapture(event.pointerId);
      }
      dragPointerId = null;
      track.classList.remove('is-dragging');
      requestUpdate();
    }

    previousButton.addEventListener('click', () => scrollByCard(-1));
    nextButton.addEventListener('click', () => scrollByCard(1));
    track.addEventListener('scroll', requestUpdate, { passive: true });
    track.addEventListener('dragstart', (event) => event.preventDefault());
    track.addEventListener('click', (event) => {
      if (!suppressClick) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
    }, true);
    track.addEventListener('pointerdown', (event) => {
      if (event.pointerType !== 'mouse' || event.button !== 0) {
        return;
      }
      dragPointerId = event.pointerId;
      dragStartX = event.clientX;
      dragStartScrollLeft = track.scrollLeft;
      dragged = false;
    });
    track.addEventListener('pointermove', (event) => {
      if (dragPointerId !== event.pointerId) {
        return;
      }
      const distance = event.clientX - dragStartX;
      if (!dragged && Math.abs(distance) < 5) {
        return;
      }
      if (!dragged) {
        dragged = true;
        track.classList.add('is-dragging');
        track.setPointerCapture(event.pointerId);
      }
      event.preventDefault();
      track.scrollLeft = dragStartScrollLeft - distance;
    });
    track.addEventListener('pointerleave', () => {
      if (!dragged) {
        dragPointerId = null;
      }
    });
    track.addEventListener('pointerup', finishDrag);
    track.addEventListener('pointercancel', finishDrag);

    if ('ResizeObserver' in window) {
      resizeObserver = new window.ResizeObserver(requestUpdate);
      resizeObserver.observe(track);
    } else {
      window.addEventListener('resize', requestUpdate);
    }

    carouselControllers.push({ carousel, track, update, resizeObserver });
    update();
  }

  function refreshImageCarousels(scope = dialog) {
    carouselControllers.forEach((controller) => {
      if (scope === dialog || scope.contains(controller.carousel)) {
        controller.update();
      }
    });
  }

  function resetImageCarousels() {
    carouselControllers.forEach((controller) => {
      controller.track.scrollLeft = 0;
      controller.update();
    });
  }

  function hideAllSteps() {
    questionSteps.forEach((step) => {
      step.hidden = true;
    });
    contactStep.hidden = true;
    successStep.hidden = true;
  }

  function updateProgress() {
    const percent = questionSteps.length
      ? Math.round((currentQuestionIndex / questionSteps.length) * 100)
      : 100;
    progressValue.textContent = `${percent}%`;
    progressBar.style.width = `${percent}%`;
    backButton.disabled = currentQuestionIndex === 0;
  }

  function showQuestion(index, { focus = true } = {}) {
    cancelAnswerAutoAdvance();
    currentQuestionIndex = Math.max(0, Math.min(index, questionSteps.length - 1));
    hideAllSteps();
    const step = questionSteps[currentQuestionIndex];
    if (step) {
      step.hidden = false;
    }
    navigation.hidden = false;
    updateProgress();
    window.requestAnimationFrame(() => refreshImageCarousels(step));
    if (focus) {
      focusStepHeading(step);
    }
  }

  function showContactStep() {
    cancelAnswerAutoAdvance();
    hideAllSteps();
    contactStep.hidden = false;
    navigation.hidden = true;
    focusStepHeading(contactStep);
  }

  function showSuccessStep(result) {
    cancelAnswerAutoAdvance();
    hideAllSteps();
    navigation.hidden = true;
    const title = successStep.querySelector('[data-quiz-success-title]');
    const message = successStep.querySelector('[data-quiz-success-message]');
    const extra = successStep.querySelector('[data-quiz-success-extra]');
    title.textContent = result.title || title.textContent;
    message.textContent = result.message || message.textContent;
    extra.textContent = result.extra || '';
    extra.hidden = !result.extra;
    successStep.hidden = false;
    focusStepHeading(successStep);
  }

  function validateQuestionStep(step) {
    const fieldName = step.dataset.quizField;
    const fields = Array.from(step.querySelectorAll('[data-quiz-answer]'));
    clearFieldError(fieldName);
    if (!fields.length) {
      return true;
    }

    const firstField = fields[0];
    let isValid = true;
    let message = '';
    if (firstField.type === 'radio') {
      const selected = fields.some((field) => field.checked);
      isValid = !firstField.required || selected;
      message = 'Выберите один из вариантов.';
    } else {
      isValid = firstField.checkValidity();
      message = firstField.validationMessage || 'Проверьте ответ.';
    }
    if (!isValid) {
      showFieldErrors(fieldName, [message]);
      firstField.focus({ preventScroll: true });
    }
    return isValid;
  }

  function resetQuiz() {
    form.reset();
    clearAllErrors();
    submitButton.disabled = false;
    submitButton.textContent = submitButton.dataset.defaultLabel;
    form.removeAttribute('aria-busy');
    resetImageCarousels();
    showQuestion(0, { focus: false });
  }

  function rememberOpen() {
    openedOnThisPage = true;
    writeStorage(shownStorageKey, String(Date.now()));
  }

  function openQuiz() {
    window.clearTimeout(autoOpenTimer);
    if (dialog.open || document.querySelector('dialog[open]')) {
      return false;
    }
    if (dialog.dataset.restartOnClose === '1') {
      resetQuiz();
    }
    dialog.showModal();
    document.body.classList.add('site-quiz-is-open');
    rememberOpen();
    window.requestAnimationFrame(() => {
      refreshImageCarousels(questionSteps[currentQuestionIndex]);
    });
    focusStepHeading(questionSteps[currentQuestionIndex]);
    return true;
  }

  function closeQuiz() {
    if (dialog.open) {
      dialog.close();
    }
  }

  function isMobileViewport() {
    return window.matchMedia('(max-width: 700px)').matches;
  }

  function autoOpenIsAllowed() {
    if (openedOnThisPage || dialog.dataset.autoOpen !== '1') {
      return false;
    }
    if (isMobileViewport() && dialog.dataset.autoOpenMobile !== '1') {
      return false;
    }
    if (
      dialog.dataset.disableAfterSubmit === '1'
      && readStorage(submittedStorageKey) === '1'
    ) {
      return false;
    }

    const repeatDays = Number(dialog.dataset.repeatDays || 0);
    const shownAt = Number(readStorage(shownStorageKey) || 0);
    if (repeatDays > 0 && shownAt > 0) {
      return Date.now() - shownAt >= repeatDays * 24 * 60 * 60 * 1000;
    }
    return true;
  }

  function tryAutoOpen() {
    if (!autoOpenIsAllowed()) {
      return;
    }
    if (!openQuiz()) {
      autoOpenTimer = window.setTimeout(tryAutoOpen, 1000);
    }
  }

  function scheduleAutoOpen() {
    if (!autoOpenIsAllowed()) {
      return;
    }
    const delay = Math.max(1, Number(dialog.dataset.autoOpenDelay || 10));
    autoOpenTimer = window.setTimeout(tryAutoOpen, delay * 1000);
  }

  document.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-quiz-open], a[href^="#popup:"]');
    if (!trigger) {
      return;
    }
    const href = trigger.getAttribute('href');
    if (!trigger.hasAttribute('data-quiz-open') && href !== triggerHash) {
      return;
    }
    event.preventDefault();
    openQuiz();
  });

  dialog.querySelectorAll('[data-quiz-close]').forEach((button) => {
    button.addEventListener('click', closeQuiz);
  });

  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) {
      closeQuiz();
    }
  });

  dialog.addEventListener('close', () => {
    cancelAnswerAutoAdvance();
    document.body.classList.remove('site-quiz-is-open');
    if (dialog.dataset.restartOnClose === '1') {
      resetQuiz();
    }
  });

  form.querySelectorAll('[data-field-name]').forEach((field) => {
    ['input', 'change'].forEach((eventName) => {
      field.addEventListener(eventName, () => clearFieldError(field.dataset.fieldName));
    });
  });

  form.querySelectorAll([
    '.site-quiz-image-option > input[data-quiz-answer]',
    '.site-quiz-choice-option > input[data-quiz-answer]'
  ].join(', ')).forEach((field) => {
    field.addEventListener('change', () => {
      if (field.checked) {
        scheduleAnswerAutoAdvance(field);
      }
    });
  });

  backButton.addEventListener('click', () => {
    if (currentQuestionIndex > 0) {
      showQuestion(currentQuestionIndex - 1);
    }
  });

  nextButton.addEventListener('click', () => {
    const currentStep = questionSteps[currentQuestionIndex];
    if (!validateQuestionStep(currentStep)) {
      return;
    }
    if (currentQuestionIndex >= questionSteps.length - 1) {
      showContactStep();
    } else {
      showQuestion(currentQuestionIndex + 1);
    }
  });

  form.addEventListener('invalid', (event) => {
    const fieldName = event.target.dataset.fieldName;
    if (!fieldName) {
      return;
    }
    event.preventDefault();
    showFieldErrors(fieldName, [event.target.validationMessage]);
  }, true);

  function showFirstServerError(fieldNames) {
    for (const fieldName of fieldNames) {
      const questionStep = questionSteps.find(
        (step) => step.dataset.quizField === fieldName
      );
      if (questionStep) {
        showQuestion(questionSteps.indexOf(questionStep));
        return;
      }
    }
    showContactStep();
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    clearAllErrors();

    if (!form.checkValidity()) {
      return;
    }

    submitButton.disabled = true;
    submitButton.textContent = 'Отправляем…';
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
        const errors = result.errors || {};
        Object.entries(errors).forEach(([fieldName, messages]) => {
          showFieldErrors(fieldName, messages);
        });
        showFirstServerError(Object.keys(errors));
        return;
      }

      if (dialog.dataset.disableAfterSubmit === '1') {
        writeStorage(submittedStorageKey, '1');
      }
      showSuccessStep(result);
    } catch (error) {
      showFieldErrors('__all__', [
        'Не удалось отправить форму. Проверьте соединение и попробуйте ещё раз.'
      ]);
      showContactStep();
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = submitButton.dataset.defaultLabel;
      form.removeAttribute('aria-busy');
    }
  });

  window.addEventListener('hashchange', () => {
    if (window.location.hash === triggerHash) {
      openQuiz();
    }
  });

  dialog.querySelectorAll('[data-quiz-carousel]').forEach(setupImageCarousel);
  resetQuiz();
  if (window.location.hash === triggerHash) {
    openQuiz();
  } else {
    scheduleAutoOpen();
  }
})();
