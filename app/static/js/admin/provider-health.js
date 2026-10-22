/**
 * WaveNxD Admin - Provider Health & Diagnostics Module
 * Backend: GET /admin/provider-status
 * Schema: { primary_llm, primary_model, fallback_llm, fallback_enabled, stt_provider, stt_model, tts_provider, tts_model, environment, budget_mode }
 */

import { apiRequest } from '../core/api.js';
import { showToast } from '../ui/notifications.js';
import { setPaneError, clearPaneError, errorMessage } from './table-states.js';

export async function loadProviderStatus(containerEl) {
  if (containerEl) clearPaneError(containerEl);
  try {
    const data = await apiRequest('/admin/provider-status');
    renderProviderStatus(data);
    return data;
  } catch (err) {
    if (containerEl) {
      setPaneError(containerEl, errorMessage(err, 'provider status'), () => loadProviderStatus(containerEl));
    }
    showToast(`Failed to load provider health: ${err.message}`, 'error');
    return null;
  }
}

export function renderProviderStatus(data) {
  if (!data) return;

  const setTxt = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val !== null && val !== undefined ? val : '—';
  };

  setTxt('primaryLlmProvider', data.primary_llm ? data.primary_llm.toUpperCase() : 'GROQ');
  setTxt('primaryLlmModel', data.primary_model || '—');
  const primStatus = document.getElementById('primaryLlmStatus');
  if (primStatus) {
    primStatus.textContent = data.primary_model ? 'CONFIGURED' : 'UNAVAILABLE';
    primStatus.className = `status-pill ${data.primary_model ? 'active' : 'inactive'}`;
  }

  setTxt('secondaryLlmProvider', data.fallback_llm ? data.fallback_llm.toUpperCase() : 'NONE');
  setTxt('secondaryLlmModel', data.fallback_llm ? (data.primary_model.includes('gemini') ? 'groq-fallback' : 'gemini-3.8-flash') : 'Disabled');
  setTxt('fallbackEnabledVal', data.fallback_enabled ? 'Enabled (At most once)' : 'Disabled');
  const secStatus = document.getElementById('secondaryLlmStatus');
  if (secStatus) {
    secStatus.textContent = data.fallback_enabled ? 'STANDBY' : 'OFF';
    secStatus.className = `status-pill ${data.fallback_enabled ? 'active' : 'inactive'}`;
  }

  setTxt('sttModelName', data.stt_model || 'whisper-large-v3');
  setTxt('ttsModelName', data.tts_model || 'gemini-3.8-flash-lite-tts');
}
