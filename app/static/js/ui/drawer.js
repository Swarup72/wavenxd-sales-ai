/**
 * WaveNxD AI Sales Representative - Accessible Drawer Manager
 */

import { saveLastFocus, restoreLastFocus, trapFocus } from './accessibility.js';

const activeDrawers = new Map();

export function openDrawer(drawerEl, triggerEl = null) {
  if (!drawerEl) return;

  saveLastFocus(triggerEl);

  drawerEl.style.display = 'flex';
  drawerEl.classList.add('active');
  drawerEl.setAttribute('aria-hidden', 'false');

  const content = drawerEl.querySelector('.drawer-content') || drawerEl;
  content.setAttribute('role', 'region');
  content.setAttribute('aria-label', 'Side Drawer Panel');

  const cleanupTrap = trapFocus(content);

  function handleBackdropClick(e) {
    if (e.target === drawerEl) {
      closeDrawer(drawerEl);
    }
  }

  function handleKeydown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      closeDrawer(drawerEl);
    }
  }

  drawerEl.addEventListener('click', handleBackdropClick);
  document.addEventListener('keydown', handleKeydown);

  activeDrawers.set(drawerEl, {
    cleanupTrap,
    handleBackdropClick,
    handleKeydown,
  });
}

export function closeDrawer(drawerEl) {
  if (!drawerEl) return;

  drawerEl.style.display = 'none';
  drawerEl.classList.remove('active');
  drawerEl.setAttribute('aria-hidden', 'true');

  const listeners = activeDrawers.get(drawerEl);
  if (listeners) {
    if (typeof listeners.cleanupTrap === 'function') listeners.cleanupTrap();
    drawerEl.removeEventListener('click', listeners.handleBackdropClick);
    document.removeEventListener('keydown', listeners.handleKeydown);
    activeDrawers.delete(drawerEl);
  }

  restoreLastFocus();
}
