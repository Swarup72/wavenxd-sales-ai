/**
 * WaveNxD Admin - Leads & Commercial Inquiries Management Module
 * Backend: GET /admin/leads, GET /admin/leads/{id}, PATCH /admin/leads/{id}, GET /admin/leads/export/csv
 * Table columns (#leadsTable): Created | Customer Name | Company | Contact Email | Application | Equipment | Stage | Actions (8 cols)
 */

import { apiRequest } from '../core/api.js';
import { showToast } from '../ui/notifications.js';
import { openModal, closeModal } from '../ui/modal.js';
import { escapeHtml, formatDate } from '../ui/formatting.js';
import { setTableLoading, setTableEmpty, setTableError, errorMessage } from './table-states.js';

const COLS = 8;

export async function loadLeads(tableBodyEl, companyFilter = '', stageFilter = '') {
  setTableLoading(tableBodyEl, COLS, 'Loading leads and inquiries…');
  try {
    const params = new URLSearchParams();
    if (companyFilter) params.append('company_id', companyFilter);
    if (stageFilter) params.append('stage', stageFilter);

    const query = params.toString() ? `?${params.toString()}` : '';
    const list = await apiRequest(`/admin/leads${query}`);
    renderLeads(list, tableBodyEl, companyFilter, stageFilter);
    return list;
  } catch (err) {
    setTableError(tableBodyEl, COLS, errorMessage(err, 'leads'), () => loadLeads(tableBodyEl, companyFilter, stageFilter));
    return [];
  }
}

export function renderLeads(leads, tableBodyEl, companyFilter = '', stageFilter = '') {
  if (!tableBodyEl) return;
  const list = Array.isArray(leads) ? leads : [];

  if (list.length === 0) {
    let msg = 'No customer leads or inquiries recorded yet.';
    if (companyFilter || stageFilter) {
      msg = 'No leads match the selected company or stage filters.';
    }
    setTableEmpty(tableBodyEl, COLS, msg);
    return;
  }

  const stageBadgeClass = (st) => {
    switch (st) {
      case 'new': return 'style="background: #E0F2FE; color: #0369A1;"';
      case 'qualified': return 'style="background: #DCFCE7; color: #15803D;"';
      case 'quote_draft': return 'style="background: #FEF3C7; color: #B45309;"';
      case 'follow_up_requested': return 'style="background: #F3E8FF; color: #7E22CE;"';
      case 'closed': return 'style="background: #F1F5F9; color: #475569;"';
      default: return '';
    }
  };

  tableBodyEl.innerHTML = list
    .map(
      (lead) => `
      <tr>
        <td>${escapeHtml(formatDate(lead.created_at))}</td>
        <td><strong>${escapeHtml(lead.customer_name)}</strong></td>
        <td>${escapeHtml(lead.company_name || '—')}</td>
        <td>${escapeHtml(lead.email)}</td>
        <td>${escapeHtml(lead.application || '—')}</td>
        <td>
          <span style="font-size: 0.8rem; color: #0284C7; font-weight: 500;">
            ${escapeHtml((lead.recommended_product_ids || []).join(', ') || 'Evaluating')}
          </span>
        </td>
        <td>
          <span class="badge-status" ${stageBadgeClass(lead.stage)}>
            ${escapeHtml((lead.stage || 'new').toUpperCase())}
          </span>
        </td>
        <td>
          <button type="button" class="btn-table-action" data-action="inspect-lead" data-id="${escapeHtml(lead.id)}">
            Inspect / Edit
          </button>
        </td>
      </tr>
    `
    )
    .join('');

  tableBodyEl.querySelectorAll('[data-action="inspect-lead"]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.getAttribute('data-id');
      if (id) openLeadDetailModal(id);
    });
  });
}

export async function openLeadDetailModal(leadId) {
  const modal = document.getElementById('adminLeadModal');
  if (!modal) return;

  try {
    const lead = await apiRequest(`/admin/leads/${leadId}`);

    document.getElementById('adminLeadId').value = lead.id;
    document.getElementById('adminLeadCustName').textContent = lead.customer_name || '—';
    document.getElementById('adminLeadCompanyName').textContent = lead.company_name || '—';
    document.getElementById('adminLeadEmail').textContent = lead.email || '—';
    document.getElementById('adminLeadPhone').textContent = lead.phone || '—';
    document.getElementById('adminLeadIndustry').textContent = lead.industry || '—';

    document.getElementById('adminLeadConvId').textContent = lead.conversation_id || '—';
    document.getElementById('adminLeadSource').textContent = lead.lead_source || '—';
    document.getElementById('adminLeadFollowUpDt').textContent = lead.preferred_follow_up_at ? formatDate(lead.preferred_follow_up_at) : (lead.follow_up_datetime ? formatDate(lead.follow_up_datetime) : 'None');
    document.getElementById('adminLeadFollowUpStatus').textContent = (lead.follow_up_status || (lead.preferred_follow_up_at ? 'scheduled' : 'none')).toUpperCase();

    document.getElementById('adminLeadApp').textContent = lead.application || '—';
    document.getElementById('adminLeadMaterial').textContent = lead.coating_material || lead.fluid_description || '—';
    document.getElementById('adminLeadFlow').textContent = lead.flow_rate_ml_min ? `${lead.flow_rate_ml_min} ml/min` : (lead.flow_rate || '—');
    document.getElementById('adminLeadVisc').textContent = lead.viscosity_cp ? `${lead.viscosity_cp} cP` : (lead.viscosity || '—');
    document.getElementById('adminLeadDroplet').textContent = lead.droplet_size_um ? `${lead.droplet_size_um} µm` : (lead.droplet_size || '—');
    document.getElementById('adminLeadCustNotes').textContent = lead.notes || lead.technical_notes || 'None';

    document.getElementById('adminLeadProds').textContent = (lead.recommended_product_ids || []).join(', ') || 'None';
    document.getElementById('adminLeadRecSummary').textContent = lead.recommendation_summary || 'No summary available';

    document.getElementById('adminLeadStageSelect').value = lead.stage || 'new';
    document.getElementById('adminLeadInternalNotes').value = lead.internal_notes || '';

    openModal(modal);
  } catch (err) {
    showToast(`Failed to load lead details: ${err.message}`, 'error');
  }
}

export async function updateLeadStatus(leadId, stage, notes) {
  return await apiRequest(`/admin/leads/${leadId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stage, notes, internal_notes: notes }),
  });
}
