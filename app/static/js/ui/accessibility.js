/**
 * WaveNxD AI Sales Representative - Accessibility & Focus Management
 */

const FOCUSABLE_SELECTOR = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

let lastFocusedElement = null;

export function saveLastFocus(element) {
  lastFocusedElement = element || document.activeElement;
}

export function restoreLastFocus() {
  if (lastFocusedElement && typeof lastFocusedElement.focus === 'function') {
    try {
      lastFocusedElement.focus();
    } catch (_) {}
  }
  lastFocusedElement = null;
}

export function trapFocus(containerEl) {
  if (!containerEl) return () => {};

  const focusableEls = containerEl.querySelectorAll(FOCUSABLE_SELECTOR);
  if (!focusableEls || focusableEls.length === 0) return () => {};

  const firstEl = focusableEls[0];
  const lastEl = focusableEls[focusableEls.length - 1];

  firstEl.focus();

  function keydownHandler(e) {
    if (e.key === 'Tab') {
      if (e.shiftKey) {
        if (document.activeElement === firstEl) {
          e.preventDefault();
          lastEl.focus();
        }
      } else {
        if (document.activeElement === lastEl) {
          e.preventDefault();
          firstEl.focus();
        }
      }
    }
  }

  containerEl.addEventListener('keydown', keydownHandler);

  return function cleanup() {
    containerEl.removeEventListener('keydown', keydownHandler);
  };
}
