/**
 * WaveNxD AI Sales Representative - Chat & Messaging Logic
 */

import { CONFIG } from '../core/config.js';
import { apiRequest } from '../core/api.js';
import { state } from '../core/state.js';
import { renderMarkdown } from './message-renderer.js';
import { escapeHtml, formatTime } from '../ui/formatting.js';
import { showToast } from '../ui/notifications.js';

export function renderMessages(messages, messagesListEl, emptyStateEl) {
  if (!messagesListEl) return;

  const msgArray = Array.isArray(messages) ? messages : [];

  if (emptyStateEl) {
    emptyStateEl.style.display = msgArray.length === 0 ? 'block' : 'none';
  }

  messagesListEl.innerHTML = msgArray
    .map((m) => {
      const isUser = m.role === 'user';
      const roleLabel = isUser ? 'Customer' : 'WaveNxD Technical Sales';
      const timeStr = formatTime(m.created_at);

      const contentHtml = isUser
        ? `<p>${escapeHtml(m.content)}</p>`
        : renderMarkdown(m.content);

      const ttsButtonHtml = !isUser
        ? `
        <div class="message-actions">
          <button class="btn-speak" data-conv-id="${state.currentConversationId}" data-msg-id="${m.id}" title="Synthesize speech with Gemini TTS">
            <span>🔊 Listen</span>
          </button>
        </div>
      `
        : '';

      return `
      <div class="message-bubble ${isUser ? 'user' : 'assistant'}" data-msg-id="${m.id}">
        <div class="message-header">
          <span class="message-role">${escapeHtml(roleLabel)}</span>
          ${timeStr ? `<span class="message-time">${escapeHtml(timeStr)}</span>` : ''}
        </div>
        <div class="message-text">
          ${contentHtml}
        </div>
        ${ttsButtonHtml}
      </div>
    `;
    })
    .join('');

  // Attach speech listeners to TTS buttons
  messagesListEl.querySelectorAll('.btn-speak').forEach((btn) => {
    btn.addEventListener('click', () => {
      const convId = btn.getAttribute('data-conv-id');
      const msgId = btn.getAttribute('data-msg-id');
      if (window.wavenxdPlayAudio) {
        window.wavenxdPlayAudio(convId, msgId, btn);
      }
    });
  });
}

export function scrollToBottom(containerEl, smooth = true) {
  if (!containerEl) return;
  requestAnimationFrame(() => {
    containerEl.scrollTo({
      top: containerEl.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto',
    });
  });
}

export async function sendTextMessage(conversationId, text, elements, onComplete) {
  const content = (text || '').trim();
  if (!content) return;

  const { messageInput, sendBtn, typingIndicator, messagesContainer } = elements;

  if (sendBtn) sendBtn.disabled = true;
  if (messageInput) messageInput.disabled = true;
  if (typingIndicator) typingIndicator.style.display = 'flex';
  scrollToBottom(messagesContainer, true);

  try {
    const res = await apiRequest(`${CONFIG.ENDPOINTS.CONVERSATIONS}/${conversationId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });

    if (onComplete && typeof onComplete === 'function') {
      onComplete(res);
    }
  } catch (err) {
    showToast(`Failed to send message: ${err.message}`, 'error');
  } finally {
    if (sendBtn) sendBtn.disabled = false;
    if (messageInput) {
      messageInput.disabled = false;
      messageInput.value = '';
      messageInput.style.height = 'auto';
      messageInput.focus();
    }
    if (typingIndicator) typingIndicator.style.display = 'none';
    scrollToBottom(messagesContainer, true);
  }
}
