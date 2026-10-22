/**
 * WaveNxD AI Sales Representative - Consultation Management
 */

import { CONFIG } from '../core/config.js';
import { apiRequest } from '../core/api.js';
import { state } from '../core/state.js';
import { escapeHtml, formatDate } from '../ui/formatting.js';
import { showToast } from '../ui/notifications.js';

export async function loadConversations(containerEl) {
  try {
    const list = await apiRequest(CONFIG.ENDPOINTS.CONVERSATIONS);
    state.conversations = Array.isArray(list) ? list : [];
    renderConversationList(state.conversations, containerEl);
    return state.conversations;
  } catch (err) {
    console.warn('Failed to load conversations:', err);
    state.conversations = [];
    renderConversationList([], containerEl);
    return [];
  }
}

export function renderConversationList(conversations, containerEl, filterQuery = '', onSelect = null) {
  if (!containerEl) return;

  const query = (filterQuery || '').trim().toLowerCase();
  const filtered = query
    ? conversations.filter((c) => (c.title || '').toLowerCase().includes(query))
    : conversations;

  if (filtered.length === 0) {
    containerEl.innerHTML = `
      <div style="padding: 16px 8px; text-align: center; color: var(--text-muted); font-size: 0.75rem;">
        ${query ? 'No matching consultations' : 'No consultations yet. Click "+ New Consultation" to begin.'}
      </div>
    `;
    return;
  }

  containerEl.innerHTML = filtered
    .map((c) => {
      const isActive = c.id === state.currentConversationId;
      const count = c.message_count !== undefined ? c.message_count : '';
      const timeStr = formatDate(c.updated_at || c.created_at);

      return `
      <div class="conversation-item ${isActive ? 'active' : ''}" data-conv-id="${c.id}" role="button" tabindex="0">
        <div class="conv-top">
          <span class="conv-title" title="${escapeHtml(c.title)}">${escapeHtml(c.title || 'Product Consultation')}</span>
          ${count !== '' ? `<span class="conv-count">${count}</span>` : ''}
        </div>
        <div class="conv-time">${escapeHtml(timeStr)}</div>
      </div>
    `;
    })
    .join('');

  // Attach click & enter listeners
  containerEl.querySelectorAll('.conversation-item').forEach((item) => {
    const convId = item.getAttribute('data-conv-id');
    const selectHandler = () => {
      if (onSelect && typeof onSelect === 'function') {
        onSelect(convId);
      }
    };
    item.addEventListener('click', selectHandler);
    item.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        selectHandler();
      }
    });
  });
}

export async function createConversation(title = 'Product Consultation') {
  try {
    const newConv = await apiRequest(CONFIG.ENDPOINTS.CONVERSATIONS, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    });
    return newConv;
  } catch (err) {
    showToast(`Failed to create consultation: ${err.message}`, 'error');
    throw err;
  }
}

export async function fetchConversationDetail(conversationId) {
  try {
    const detail = await apiRequest(`${CONFIG.ENDPOINTS.CONVERSATIONS}/${conversationId}`);
    state.currentConversationId = detail.id;
    state.currentConversationDetail = detail;
    return detail;
  } catch (err) {
    showToast(`Failed to load consultation detail: ${err.message}`, 'error');
    throw err;
  }
}
