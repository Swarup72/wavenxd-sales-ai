/**
 * WaveNxD AI Sales Representative - Accessible Modal Dialog Manager
 */

import { saveLastFocus, restoreLastFocus, trapFocus } from './accessibility.js';

const activeModals = new Map();

export function openModal(modalEl, triggerEl = null) {
  if (!modalEl) return;

  saveLastFocus(triggerEl);

  modalEl.style.display = 'flex';
  modalEl.classList.add('active');
  modalEl.setAttribute('aria-hidden', 'false');

  const dialog = modalEl.querySelector('.modal-dialog') || modalEl;
  dialog.setAttribute('role', 'dialog');
  dialog.setAttribute('aria-modal', 'true');

  // Prevent background scrolling while modal is open
  document.body.style.overflow = 'hidden';

  // Setup focus trapping
  const cleanupTrap = trapFocus(dialog);

  // Backdrop click handler
  function handleBackdropClick(e) {
    if (e.target === modalEl) {
      closeModal(modalEl);
    }
  }

  // Escape key handler
  function handleKeydown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      closeModal(modalEl);
    }
  }

  modalEl.addEventListener('click', handleBackdropClick);
  document.addEventListener('keydown', handleKeydown);

  activeModals.set(modalEl, {
    cleanupTrap,
    handleBackdropClick,
    handleKeydown,
  });
}

export function closeModal(modalEl) {
  if (!modalEl) return;

  modalEl.style.display = 'none';
  modalEl.classList.remove('active');
  modalEl.setAttribute('aria-hidden', 'true');

  const listeners = activeModals.get(modalEl);
  if (listeners) {
    if (typeof listeners.cleanupTrap === 'function') listeners.cleanupTrap();
    modalEl.removeEventListener('click', listeners.handleBackdropClick);
    document.removeEventListener('keydown', listeners.handleKeydown);
    activeModals.delete(modalEl);
  }

  // Restore body overflow if no other modals are open
  if (activeModals.size === 0) {
    document.body.style.overflow = '';
  }

  restoreLastFocus();
}

export function initModalCloseButtons() {
  document.querySelectorAll('[data-close-modal]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const modalId = btn.getAttribute('data-close-modal');
      const targetModal = document.getElementById(modalId);
      if (targetModal) closeModal(targetModal);
    });
  });
}
