/**
 * WaveNxD Admin - Companies Management Module
 * Backend: GET/POST /admin/companies, PATCH /admin/companies/{id}
 * CompanyResponse: { id, name, is_active, contact_email, notes }
 * Table columns (admin.html #companiesTable): Name | Contact Email | Status | Notes | Actions
 */

import { apiRequest } from '../core/api.js';
import { showToast } from '../ui/notifications.js';
import { escapeHtml } from '../ui/formatting.js';
import { setTableLoading, setTableEmpty, setTableError, errorMessage } from './table-states.js';

const COLS = 5;

export async function loadCompanies(tableBodyEl, query = '') {
  setTableLoading(tableBodyEl, COLS, 'Loading companies…');
  try {
    const list = await apiRequest('/admin/companies');
    renderCompanies(list, tableBodyEl, query);
    return list;
  } catch (err) {
    setTableError(tableBodyEl, COLS, errorMessage(err, 'companies'), () => loadCompanies(tableBodyEl, query));
    return [];
  }
}

export function renderCompanies(companies, tableBodyEl, query = '') {
  if (!tableBodyEl) return;
  const all = Array.isArray(companies) ? companies : [];
  const q = query.trim().toLowerCase();
  const filtered = q
    ? all.filter((c) => `${c.name} ${c.contact_email || ''}`.toLowerCase().includes(q))
    : all;

  if (filtered.length === 0) {
    setTableEmpty(tableBodyEl, COLS, all.length === 0 ? 'No companies registered yet.' : 'No companies match the filter.');
    return;
  }

  tableBodyEl.innerHTML = filtered
    .map(
      (c) => `
      <tr>
        <td><strong>${escapeHtml(c.name)}</strong></td>
        <td>${escapeHtml(c.contact_email || '—')}</td>
        <td><span class="badge-status ${c.is_active ? 'active' : 'inactive'}">${c.is_active ? 'Active' : 'Disabled'}</span></td>
        <td>${escapeHtml(c.notes || '—')}</td>
        <td>
          <div class="table-actions">
            <button type="button" class="btn-table-action" data-action="edit-company" data-id="${escapeHtml(c.id)}">Edit</button>
            <button type="button" class="btn-table-action ${c.is_active ? 'danger' : ''}" data-action="toggle-company"
              data-id="${escapeHtml(c.id)}" data-active="${c.is_active ? 'false' : 'true'}">${c.is_active ? 'Disable' : 'Enable'}</button>
          </div>
        </td>
      </tr>`
    )
    .join('');
}

export async function toggleCompanyStatus(companyId, newActive, onSuccess) {
  try {
    await apiRequest(`/admin/companies/${encodeURIComponent(companyId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: newActive }),
    });
    showToast(`Company ${newActive ? 'enabled' : 'disabled'}.`, 'success');
    if (onSuccess) onSuccess();
  } catch (err) {
    showToast(`Failed to update company: ${err.message}`, 'error');
  }
}

export async function saveCompany(companyData, companyId, onSuccess) {
  try {
    await apiRequest(companyId ? `/admin/companies/${encodeURIComponent(companyId)}` : '/admin/companies', {
      method: companyId ? 'PATCH' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(companyData),
    });
    showToast(companyId ? 'Company updated.' : 'Company created.', 'success');
    if (onSuccess) onSuccess();
  } catch (err) {
    showToast(`Failed to save company: ${err.message}`, 'error');
  }
}
