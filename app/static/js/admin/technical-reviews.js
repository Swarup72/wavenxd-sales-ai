/**
 * WaveNxD Admin - Technical Review Queue Module
 * Backend: GET /admin/technical-review-queue, GET /admin/access-requests,
 *   POST /admin/access-requests/{id}/approve, POST /admin/access-requests/{id}/reject
 */

import { apiRequest } from '../core/api.js';
import { showToast } from '../ui/notifications.js';
import { escapeHtml, formatDate } from '../ui/formatting.js';
import { setTableLoading, setTableEmpty, setTableError, errorMessage } from './table-states.js';

const FLAGGED_COLS = 5;
const REQUEST_COLS = 6;

export async function loadReviewsQueue(accessTableBody, flaggedTableBody, badges = {}) {
  setTableLoading(flaggedTableBody, FLAGGED_COLS, 'Loading flagged products…');
  setTableLoading(accessTableBody, REQUEST_COLS, 'Loading access requests…');

  try {
    const [queueData, requestsData] = await Promise.all([
      apiRequest('/admin/technical-review-queue'),
      apiRequest('/admin/access-requests'),
    ]);

    const flaggedList = (queueData && queueData.flagged_products) ? queueData.flagged_products : [];
    const requestList = Array.isArray(requestsData) ? requestsData : [];

    const pendingRequests = requestList.filter((r) => r.status === 'pending');
    const totalPending = (queueData && typeof queueData.pending_requests_count === 'number')
      ? queueData.pending_requests_count + flaggedList.length
      : pendingRequests.length + flaggedList.length;

    if (badges.navBadge) {
      badges.navBadge.textContent = totalPending;
      badges.navBadge.style.display = totalPending > 0 ? 'inline-block' : 'none';
    }
    if (badges.flaggedBadge) {
      badges.flaggedBadge.textContent = `${flaggedList.length} items`;
    }
    if (badges.requestsBadge) {
      badges.requestsBadge.textContent = `${pendingRequests.length} pending`;
    }

    renderFlaggedProducts(flaggedList, flaggedTableBody);
    renderAccessRequests(requestList, accessTableBody);

    return { flagged: flaggedList, requests: requestList };
  } catch (err) {
    const msg = errorMessage(err, 'review queue');
    setTableError(flaggedTableBody, FLAGGED_COLS, msg, () => loadReviewsQueue(accessTableBody, flaggedTableBody, badges));
    setTableError(accessTableBody, REQUEST_COLS, msg, () => loadReviewsQueue(accessTableBody, flaggedTableBody, badges));
    return { flagged: [], requests: [] };
  }
}

export function renderFlaggedProducts(flagged, tableBodyEl) {
  if (!tableBodyEl) return;
  const list = Array.isArray(flagged) ? flagged : [];
  if (list.length === 0) {
    setTableEmpty(tableBodyEl, FLAGGED_COLS, 'No catalog products currently flagged for technical review.');
    return;
  }

  tableBodyEl.innerHTML = list
    .map(
      (p) => `
      <tr>
        <td><strong>${escapeHtml(p.name)}</strong></td>
        <td><code>${escapeHtml(p.catalog_key || '—')}</code></td>
        <td><span class="badge-status potential">REVIEW REQUIRED</span></td>
        <td>${escapeHtml(p.catalog_notes || p.engineering_notes || '—')}</td>
        <td>
          <button type="button" class="btn-table-action" data-action="clear-review" data-id="${escapeHtml(p.id)}">
            Approve &amp; Clear Flag
          </button>
        </td>
      </tr>`
    )
    .join('');
}

export function renderAccessRequests(requests, tableBodyEl) {
  if (!tableBodyEl) return;
  const list = Array.isArray(requests) ? requests : [];
  if (list.length === 0) {
    setTableEmpty(tableBodyEl, REQUEST_COLS, 'No customer product access requests recorded.');
    return;
  }

  tableBodyEl.innerHTML = list
    .map(
      (r) => `
      <tr>
        <td><strong>${escapeHtml(r.company_name || r.company_id)}</strong></td>
        <td>${escapeHtml(r.product_name || r.product_id)}</td>
        <td>${escapeHtml(r.reason || '—')}</td>
        <td>
          <span class="badge-status ${r.status === 'approved' ? 'active' : (r.status === 'rejected' ? 'inactive' : 'potential')}">
            ${escapeHtml((r.status || 'pending').toUpperCase())}
          </span>
        </td>
        <td>${escapeHtml(formatDate(r.created_at))}</td>
        <td>
          ${
            r.status === 'pending'
              ? `
              <div class="table-actions">
                <button type="button" class="btn-table-action" data-action="approve-request" data-id="${escapeHtml(r.id)}">Approve</button>
                <button type="button" class="btn-table-action danger" data-action="reject-request" data-id="${escapeHtml(r.id)}">Reject</button>
              </div>`
              : `<span class="text-muted">${escapeHtml(r.review_note || 'Completed')}</span>`
          }
        </td>
      </tr>`
    )
    .join('');
}

export async function approveAccessRequest(reqId, onSuccess) {
  try {
    await apiRequest(`/admin/access-requests/${encodeURIComponent(reqId)}/approve`, { method: 'POST' });
    showToast('Access request approved and entitlement granted.', 'success');
    if (onSuccess) onSuccess();
  } catch (err) {
    showToast(`Approval failed: ${err.message}`, 'error');
  }
}

export async function rejectAccessRequest(reqId, onSuccess) {
  try {
    await apiRequest(`/admin/access-requests/${encodeURIComponent(reqId)}/reject`, { method: 'POST' });
    showToast('Access request rejected.', 'info');
    if (onSuccess) onSuccess();
  } catch (err) {
    showToast(`Rejection failed: ${err.message}`, 'error');
  }
}
