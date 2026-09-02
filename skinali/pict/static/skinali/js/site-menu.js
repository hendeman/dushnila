(() => {
  const trigger = document.querySelector('[data-mobile-menu-open]');
  const navigation = document.getElementById('mobile-site-menu');

  if (!trigger || !navigation) {
    return;
  }

  function setExpanded(isExpanded) {
    trigger.setAttribute('aria-expanded', isExpanded ? 'true' : 'false');
    trigger.setAttribute(
      'aria-label',
      isExpanded ? 'Закрыть главное меню' : 'Открыть главное меню'
    );
    navigation.classList.toggle('is-open', isExpanded);
  }

  function isExpanded() {
    return trigger.getAttribute('aria-expanded') === 'true';
  }

  trigger.addEventListener('click', () => {
    setExpanded(!isExpanded());
  });

  navigation.querySelectorAll('a, [data-callback-open]').forEach((control) => {
    control.addEventListener('click', () => setExpanded(false));
  });

  document.addEventListener('click', (event) => {
    if (
      isExpanded() &&
      !navigation.contains(event.target) &&
      !trigger.contains(event.target)
    ) {
      setExpanded(false);
    }
  });

  const mobileViewport = window.matchMedia('(max-width: 900px)');
  if (typeof mobileViewport.addEventListener === 'function') {
    mobileViewport.addEventListener('change', (event) => {
      if (!event.matches) {
        setExpanded(false);
      }
    });
  }
})();
