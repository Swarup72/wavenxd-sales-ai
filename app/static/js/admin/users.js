/**
 * WaveNxD Admin - Users Governance Module
 * Backend: GET /admin/users, PATCH /admin/users/{id}, POST /admin/users/{id}/reset-password { password }
 * UserAdminResponse: { id, email, full_name, role, company_id, company_name, is_active, must_change_password, created_at, updated_at }
 * Table columns (#usersTable): User | Role | Assigned Company | Account Status | Created | Security Actions
 */

import { apiRequest } from '../core/api.js';
import { showToast } from '../ui/notifications.js';
import { escapeHtml, formatDate } from '../ui/formatting.js';
import { setTableLoading, setTableEmpty, setTableError, errorMessage } from './table-states.js';

const COLS = 6;

export async function loadUsers(tableBodyEl, query = '') {
  setTableLoading(tableBodyEl, COLS, 'Loading users…');
  try {
    const list = await apiRequest('/admin/users');
    renderUsers(list, tableBodyEl, query);
    return list;
  } catch (err) {
    setTableError(tableBodyEl, COLS, errorMessage(err, 'users'), () => loadUsers(tableBodyEl, query));
    return [];
  }
}

export function renderUsers(users, tableBodyEl, query = '') {
  if (!tableBodyEl) return;
  const all = Array.isArray(users) ? users : [];
  const q = query.trim().toLowerCase();
  const filtered = q
    ? all.filter((u) => `${u.email} ${u.full_name || ''} ${u.company_name || ''}`.toLowerCase().includes(q))
    : all;

  if (filtered.length === 0) {
    setTableEmpty(tableBodyEl, COLS, all.length === 0 ? 'No user accounts exist yet.' : 'No users match the filter.');
    return;
  }

  tableBodyEl.innerHTML = filtered
    .map(
      (u) => `
      <tr>
        <td><strong>${escapeHtml(u.full_name || '—')}</strong><br><span class="text-muted">${escapeHtml(u.email)}</span></td>
        <td><span class="table-badge role ${escapeHtml(u.role)}">${escapeHtml(u.role)}</span></td>
        <td>${escapeHtml(u.company_name || (u.role === 'admin' ? 'WaveNxD (internal)' : '—'))}</td>
        <td>
          <span class="badge-status ${u.is_active ? 'active' : 'inactive'}">${u.is_active ? 'Active' : 'Disabled'}</span>
          ${u.must_change_password ? '<span class="badge-status potential">Must change password</span>' : ''}
        </td>
        <td>${escapeHtml(formatDate(u.created_at))}</td>
        <td>
          <div class="table-actions">
            <button type="button" class="btn-table-action" data-action="reset-password"
              data-id="${escapeHtml(u.id)}" data-email="${escapeHtml(u.email)}">Reset password</button>
            <button type="button" class="btn-table-action ${u.is_active ? 'danger' : ''}" data-action="toggle-user"
              data-id="${escapeHtml(u.id)}" data-active="${u.is_active ? 'false' : 'true'}">${u.is_active ? 'Disable' : 'Enable'}</button>
          </div>
        </td>
      </tr>`
    )
    .join('');
}

export async function toggleUserStatus(userId, newActive, onSuccess) {
  try {
    await apiRequest(`/admin/users/${encodeURIComponent(userId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: newActive }),
    });
    showToast(`User ${newActive ? 'enabled' : 'disabled'}.`, 'success');
    if (onSuccess) onSuccess();
  } catch (err) {
    showToast(`Failed to update user: ${err.message}`, 'error');
  }
}

export async function resetUserPassword(userId, newPassword, onSuccess) {
  try {
    // Backend schema AdminResetPasswordRequest expects the field "password".
    await apiRequest(`/admin/users/${encodeURIComponent(userId)}/reset-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: newPassword }),
    });
    showToast('Password reset successfully.', 'success');
    if (onSuccess) onSuccess();
  } catch (err) {
    showToast(`Password reset failed: ${err.message}`, 'error');
  }
}
