/**
 * WaveNxD Admin - Invitations Module
 * Backend: GET /admin/invitations, POST /admin/invitations { email, company_id }
 * InvitationAdminResponse: { id, email, company_id, company_name, status, expires_at, created_at }
 * status ∈ pending | consumed | expired | revoked
 * Table columns (#invitationsTable): Invited Email | Target Company | Status | Expires | Created
 *
 * Delivery: no email provider is integrated. The POST response returns the raw
 * invitation token once; the admin shares it with the invitee manually.
 */

import { apiRequest } from '../core/api.js';
import { showToast } from '../ui/notifications.js';
import { escapeHtml, formatDate } from '../ui/formatting.js';
import { setTableLoading, setTableEmpty, setTableError, errorMessage } from './table-states.js';

const COLS = 5;
const STATUS_CLASS = { pending: 'potential', consumed: 'active', expired: 'inactive', revoked: 'inactive' };

export async function loadInvitations(tableBodyEl) {
  setTableLoading(tableBodyEl, COLS, 'Loading invitations…');
  try {
    const list = await apiRequest('/admin/invitations');
    renderInvitations(list, tableBodyEl);
    return list;
  } catch (err) {
    setTableError(tableBodyEl, COLS, errorMessage(err, 'invitations'), () => loadInvitations(tableBodyEl));
    return [];
  }
}

export function renderInvitations(invitations, tableBodyEl) {
  if (!tableBodyEl) return;
  const list = Array.isArray(invitations) ? invitations : [];
  if (list.length === 0) {
    setTableEmpty(tableBodyEl, COLS, 'No invitations issued yet.');
    return;
  }
  tableBodyEl.innerHTML = list
    .map(
      (inv) => `
      <tr>
        <td><strong>${escapeHtml(inv.email)}</strong></td>
        <td>${escapeHtml(inv.company_name || '—')}</td>
        <td><span class="badge-status ${STATUS_CLASS[inv.status] || 'inactive'}">${escapeHtml(String(inv.status || '').toUpperCase())}</span></td>
        <td>${escapeHtml(formatDate(inv.expires_at))}</td>
        <td>${escapeHtml(formatDate(inv.created_at))}</td>
      </tr>`
    )
    .join('');
}

export async function createAdminInvitation(email, companyId) {
  try {
    const res = await apiRequest('/admin/invitations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.trim().toLowerCase(), company_id: companyId }),
    });
    showToast('Invitation created. Copy the token now — it is shown only once.', 'success');
    return res;
  } catch (err) {
    showToast(`Failed to create invitation: ${err.message}`, 'error');
    throw err;
  }
}
