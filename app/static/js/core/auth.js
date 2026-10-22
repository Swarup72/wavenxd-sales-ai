/**
 * WaveNxD AI Sales Representative - Authentication Service
 */

import { CONFIG } from './config.js';
import { apiRequest } from './api.js';
import { state, resetSessionState } from './state.js';
import { updateCsrfToken } from './csrf.js';

export async function checkAuth() {
  try {
    const data = await apiRequest(CONFIG.ENDPOINTS.ME);
    if (data && data.id) {
      state.currentUser = data;
      return state.currentUser;
    }
  } catch (err) {
    // 401 or network error means unauthenticated
    state.currentUser = null;
  }
  return null;
}

export async function login(email, password) {
  const payload = {
    email: email.trim().toLowerCase(),
    password: password,
  };

  const data = await apiRequest(CONFIG.ENDPOINTS.LOGIN, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (data && data.user) {
    state.currentUser = data.user;
    if (data.csrf_token) {
      updateCsrfToken(data.csrf_token);
    }
    return data.user;
  }
  throw new Error('Invalid response structure from login endpoint');
}

export async function logout() {
  try {
    await apiRequest(CONFIG.ENDPOINTS.LOGOUT, { method: 'POST' });
  } catch (err) {
    console.warn('Logout API request returned an error, proceeding with client cleanup:', err);
  } finally {
    resetSessionState();
  }
}

export async function acceptInvitation(token, password, fullName = '') {
  const payload = {
    token: token.trim(),
    password: password,
    full_name: fullName.trim() || undefined,
  };

  const data = await apiRequest(CONFIG.ENDPOINTS.ACCEPT_INVITATION, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  return data;
}
