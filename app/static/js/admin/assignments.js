/**
 * WaveNxD Admin - Company Product Entitlements Module
 * Backend: GET /admin/assignments, POST /admin/companies/{cid}/products/{pid}, DELETE /admin/companies/{cid}/products/{pid}
 * AssignmentDetailResponse: { id, company_id, company_name, product_id, product_name, product_catalog_key, is_active, assigned_by_user_id, created_at }
 * Table columns (#assignmentsTable): Company Name | Assigned Product | Catalog Key | Entitlement Status | Granted Date | Revoke (6 cols)
 */

import { apiRequest } from '../core/api.js';
import { showToast } from '../ui/notifications.js';
import { escapeHtml, formatDate } from '../ui/formatting.js';
import { setTableLoading, setTableEmpty, setTableError, errorMessage } from './table-states.js';

const COLS = 6;

export async function loadAssignments(tableBodyEl, companyFilter = '') {
  setTableLoading(tableBodyEl, COLS, 'Loading product assignments…');
  try {
    const url = companyFilter
      ? `/admin/assignments?company_id=${encodeURIComponent(companyFilter)}`
      : '/admin/assignments';
    const list = await apiRequest(url);
    renderAssignments(list, tableBodyEl, companyFilter);
    return list;
  } catch (err) {
    setTableError(tableBodyEl, COLS, errorMessage(err, 'assignments'), () => loadAssignments(tableBodyEl, companyFilter));
    return [];
  }
}

export function renderAssignments(assignments, tableBodyEl, companyFilter = '') {
  if (!tableBodyEl) return;
  const list = Array.isArray(assignments) ? assignments : [];

  if (list.length === 0) {
    const emptyMsg = companyFilter
      ? 'No product entitlements granted for this company. Select "All Companies" to view all records.'
      : 'No company product entitlements granted yet.';
    setTableEmpty(tableBodyEl, COLS, emptyMsg);
    return;
  }

  tableBodyEl.innerHTML = list
    .map(
      (a) => `
      <tr>
        <td><strong>${escapeHtml(a.company_name)}</strong></td>
        <td>${escapeHtml(a.product_name)}</td>
        <td><code>${escapeHtml(a.product_catalog_key || '—')}</code></td>
        <td>
          <span class="badge-status ${a.is_active ? 'active' : 'inactive'}">
            ${a.is_active ? 'ACTIVE' : 'DEACTIVATED'}
          </span>
        </td>
        <td>${escapeHtml(formatDate(a.created_at))}</td>
        <td>
          ${
            a.is_active
              ? `<button type="button" class="btn-table-action danger" data-action="revoke-assignment"
                   data-company-id="${escapeHtml(a.company_id)}" data-product-id="${escapeHtml(a.product_id)}">
                   Revoke
                 </button>`
              : '<span class="text-muted">—</span>'
          }
        </td>
      </tr>`
    )
    .join('');
}

export async function revokeAssignment(companyId, productId, onSuccess) {
  try {
    await apiRequest(`/admin/companies/${encodeURIComponent(companyId)}/products/${encodeURIComponent(productId)}`, {
      method: 'DELETE',
    });
    showToast('Product assignment revoked.', 'success');
    if (onSuccess) onSuccess();
  } catch (err) {
    showToast(`Failed to revoke assignment: ${err.message}`, 'error');
  }
}

export async function grantAssignment(companyId, productId, onSuccess) {
  try {
    await apiRequest(`/admin/companies/${encodeURIComponent(companyId)}/products/${encodeURIComponent(productId)}`, {
      method: 'POST',
    });
    showToast('Product entitlement granted successfully.', 'success');
    if (onSuccess) onSuccess();
  } catch (err) {
    showToast(`Failed to grant entitlement: ${err.message}`, 'error');
  }
}
