/**
 * WaveNxD AI Sales Representative - CSRF Security Manager
 */

import { CONFIG } from './config.js';
import { state } from './state.js';

export function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length >= 2) return parts.pop().split(';').shift();
  return null;
}

export async function fetchCsrfToken() {
  try {
    const res = await fetch(CONFIG.ENDPOINTS.CSRF, { credentials: 'same-origin' });
    if (res.ok) {
      const data = await res.json();
      if (data && data.csrf_token) {
        state.csrfToken = data.csrf_token;
        return state.csrfToken;
      }
    }
  } catch (err) {
    console.warn('Failed to fetch CSRF token from endpoint, checking cookie:', err);
  }

  // Fallback to cookie
  const cookieToken = getCookie(CONFIG.COOKIES.CSRF);
  if (cookieToken) {
    state.csrfToken = cookieToken;
  }
  return state.csrfToken;
}

export function updateCsrfToken(newToken) {
  if (newToken && typeof newToken === 'string') {
    state.csrfToken = newToken;
  }
}

export function getCsrfToken() {
  return state.csrfToken || getCookie(CONFIG.COOKIES.CSRF);
}
