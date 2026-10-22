/**
 * WaveNxD Admin - Shared table/pane state rendering (loading, empty, error).
 *
 * Every admin loader uses these so a pending, empty, or failed request never
 * leaves a blank table. States carry data-state attributes so they can be
 * asserted by the browser regression test.
 */

import { escapeHtml } from '../ui/formatting.js';

function stateRow(tbody, colspan, state, html) {
  if (!tbody) return null;
  tbody.innerHTML = `<tr data-state="${state}"><td colspan="${colspan}" class="empty-table-cell">${html}</td></tr>`;
  return tbody.firstElementChild;
}

export function setTableLoading(tbody, colspan, label = 'Loading…') {
  stateRow(tbody, colspan, 'loading', escapeHtml(label));
}

export function setTableEmpty(tbody, colspan, message) {
  stateRow(tbody, colspan, 'empty', escapeHtml(message));
}

export function setTableError(tbody, colspan, message, onRetry) {
  const row = stateRow(
    tbody,
    colspan,
    'error',
    `<span class="text-error">${escapeHtml(message)}</span>
     ${onRetry ? '<button type="button" class="btn-table-action" data-retry>Retry</button>' : ''}`
  );
  const btn = row && row.querySelector('[data-retry]');
  if (btn && onRetry) btn.addEventListener('click', onRetry, { once: true });
}

/** Error banner for panes without a table (e.g. Provider Health). */
export function setPaneError(container, message, onRetry) {
  if (!container) return;
  clearPaneError(container);
  const box = document.createElement('div');
  box.className = 'alert-banner error';
  box.setAttribute('data-state', 'error');
  box.setAttribute('role', 'alert');
  box.textContent = message + ' ';
  if (onRetry) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn-table-action';
    btn.textContent = 'Retry';
    btn.addEventListener('click', onRetry, { once: true });
    box.appendChild(btn);
  }
  container.prepend(box);
}

export function clearPaneError(container) {
  if (!container) return;
  container.querySelectorAll(':scope > [data-state="error"]').forEach((n) => n.remove());
}

export function errorMessage(err, what) {
  const status = err && err.status ? ` (HTTP ${err.status})` : '';
  return `Could not load ${what}${status}: ${err && err.message ? err.message : 'unknown error'}`;
}
