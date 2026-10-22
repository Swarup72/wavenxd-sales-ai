/**
 * WaveNxD Admin - Audit Log Inspection Module
 * Backend: GET /admin/audit-logs?limit=100&action=...
 * Audit log entry: { id, admin_email, action, target_type, target_id, details, created_at }
 * Table columns (#auditTable): Timestamp | Admin User | Action | Target Type | Target ID | Details (6 cols)
 */

import { apiRequest } from '../core/api.js';
import { escapeHtml, formatDate } from '../ui/formatting.js';
import { setTableLoading, setTableEmpty, setTableError, errorMessage } from './table-states.js';

const COLS = 6;

export async function loadAuditLogs(tableBodyEl, actionFilter = '') {
  setTableLoading(tableBodyEl, COLS, 'Loading audit logs…');
  try {
    const url = actionFilter
      ? `/admin/audit-logs?action=${encodeURIComponent(actionFilter)}`
      : '/admin/audit-logs';
    const list = await apiRequest(url);
    renderAuditLogs(list, tableBodyEl);
    return list;
  } catch (err) {
    setTableError(tableBodyEl, COLS, errorMessage(err, 'audit logs'), () => loadAuditLogs(tableBodyEl, actionFilter));
    return [];
  }
}

export function renderAuditLogs(logs, tableBodyEl) {
  if (!tableBodyEl) return;
  const list = Array.isArray(logs) ? logs : [];

  if (list.length === 0) {
    setTableEmpty(tableBodyEl, COLS, 'No audit log entries recorded yet.');
    return;
  }

  tableBodyEl.innerHTML = list
    .map(
      (log) => `
      <tr>
        <td>${escapeHtml(formatDate(log.created_at))}</td>
        <td>${escapeHtml(log.admin_email || 'System')}</td>
        <td><code>${escapeHtml(log.action || '—')}</code></td>
        <td><span class="table-badge role">${escapeHtml(log.target_type || '—')}</span></td>
        <td><code>${escapeHtml(log.target_id || '—')}</code></td>
        <td>${escapeHtml(log.details || '—')}</td>
      </tr>`
    )
    .join('');
}
