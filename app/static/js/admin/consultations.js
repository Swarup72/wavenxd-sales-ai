/**
 * WaveNxD Admin - Support Consultations Inspection Module
 * Backend: GET /admin/support/conversations, GET /admin/support/conversations/{id}
 * AdminConversationResponse: { id, company_id, company_name, user_id, user_email, title, message_count, status, created_at, updated_at }
 * Table columns (#supportConversationsTable): Consultation Title | Company | Customer Email | Messages | Status | Last Active | Actions (7 cols)
 */

import { apiRequest } from '../core/api.js';
import { showToast } from '../ui/notifications.js';
import { escapeHtml, formatDate, formatTime } from '../ui/formatting.js';
import { renderMarkdown } from '../customer/message-renderer.js';
import { setTableLoading, setTableEmpty, setTableError, errorMessage } from './table-states.js';

const COLS = 7;

export async function loadSupportConversations(tableBodyEl, companyFilter = '') {
  setTableLoading(tableBodyEl, COLS, 'Loading consultations…');
  try {
    const url = companyFilter
      ? `/admin/support/conversations?company_id=${encodeURIComponent(companyFilter)}`
      : '/admin/support/conversations';
    const list = await apiRequest(url);
    renderSupportConversations(list, tableBodyEl, companyFilter);
    return list;
  } catch (err) {
    setTableError(tableBodyEl, COLS, errorMessage(err, 'consultations'), () => loadSupportConversations(tableBodyEl, companyFilter));
    return [];
  }
}

export function renderSupportConversations(conversations, tableBodyEl, companyFilter = '') {
  if (!tableBodyEl) return;
  const list = Array.isArray(conversations) ? conversations : [];

  if (list.length === 0) {
    const emptyMsg = companyFilter
      ? 'No consultation sessions found for this company. Select "All Companies" to view all records.'
      : 'No consultation sessions recorded yet.';
    setTableEmpty(tableBodyEl, COLS, emptyMsg);
    return;
  }

  tableBodyEl.innerHTML = list
    .map(
      (c) => `
      <tr>
        <td><strong>${escapeHtml(c.title || 'Technical Consultation')}</strong></td>
        <td>${escapeHtml(c.company_name || '—')}</td>
        <td>${escapeHtml(c.user_email || '—')}</td>
        <td><span class="table-badge count">${c.message_count || 0}</span></td>
        <td>
          <span class="badge-status ${c.status === 'active' ? 'active' : 'inactive'}">
            ${escapeHtml((c.status || 'active').toUpperCase())}
          </span>
        </td>
        <td>${escapeHtml(formatDate(c.updated_at || c.created_at))}</td>
        <td>
          <button type="button" class="btn-table-action" data-action="inspect-conversation" data-id="${escapeHtml(c.id)}">
            Inspect
          </button>
        </td>
      </tr>`
    )
    .join('');
}

export async function inspectConversation(convId, elements) {
  const { titleEl, subtitleEl, messagesListEl } = elements;
  try {
    const detail = await apiRequest(`/admin/support/conversations/${encodeURIComponent(convId)}`);
    if (titleEl) titleEl.textContent = detail.title || 'Consultation History';
    if (subtitleEl) {
      subtitleEl.textContent = `Company: ${detail.company_name || '—'} • User: ${detail.user_email || '—'} • ${
        detail.messages ? detail.messages.length : 0
      } messages`;
    }

    if (messagesListEl) {
      const msgs = detail.messages || [];
      if (msgs.length === 0) {
        messagesListEl.innerHTML = '<div style="color: var(--text-muted); padding: 16px;">No messages in this consultation.</div>';
      } else {
        messagesListEl.innerHTML = msgs
          .map((m) => {
            const isUser = m.role === 'user';
            const roleLabel = isUser ? 'Customer' : 'WaveNxD Technical Sales';
            const timeStr = formatTime(m.created_at);
            const contentHtml = isUser ? `<p>${escapeHtml(m.content)}</p>` : renderMarkdown(m.content);

            return `
            <div class="support-msg-item ${isUser ? 'user' : 'assistant'}">
              <div class="support-msg-meta">
                <strong>${escapeHtml(roleLabel)}</strong>
                <span>${escapeHtml(timeStr)}</span>
              </div>
              <div class="support-msg-content">
                ${contentHtml}
              </div>
            </div>`;
          })
          .join('');
      }
    }
    return detail;
  } catch (err) {
    showToast(`Failed to load consultation: ${err.message}`, 'error');
    throw err;
  }
}
