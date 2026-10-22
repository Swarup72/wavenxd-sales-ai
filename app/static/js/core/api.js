/**
 * WaveNxD AI Sales Representative - Normalized API Client
 */

import { fetchCsrfToken, getCsrfToken, updateCsrfToken } from './csrf.js';

export class ApiError extends Error {
  constructor(status, message, data = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

export async function apiRequest(url, options = {}) {
  let token = getCsrfToken();
  if (!token) {
    token = await fetchCsrfToken();
  }

  const headers = options.headers ? { ...options.headers } : {};
  const method = (options.method || 'GET').toUpperCase();

  // Attach CSRF token on state-changing operations
  if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
    if (token) {
      headers['X-CSRF-Token'] = token;
    }
  }

  options.headers = headers;
  options.credentials = 'same-origin';

  let res;
  try {
    res = await fetch(url, options);
  } catch (err) {
    throw new ApiError(0, `Network communication error: ${err.message}`);
  }

  // Handle potential CSRF invalidation once
  if (res.status === 403 && !options._csrfRetried) {
    const errorBody = await res.clone().text().catch(() => '');
    if (errorBody.toLowerCase().includes('csrf')) {
      const refreshedToken = await fetchCsrfToken();
      if (refreshedToken) {
        options._csrfRetried = true;
        options.headers['X-CSRF-Token'] = refreshedToken;
        return apiRequest(url, options);
      }
    }
  }

  // Check content type to return JSON or raw blob / text
  const contentType = res.headers.get('content-type') || '';
  let responseData = null;

  if (contentType.includes('application/json')) {
    responseData = await res.json().catch(() => null);
  } else if (contentType.includes('text/')) {
    responseData = await res.text().catch(() => null);
  } else {
    // Binary responses (e.g. audio/wav)
    responseData = await res.blob().catch(() => null);
  }

  // Check if response contains a refreshed CSRF token in body
  if (responseData && typeof responseData === 'object' && responseData.csrf_token) {
    updateCsrfToken(responseData.csrf_token);
  }

  if (!res.ok) {
    let detail = `Request failed with HTTP ${res.status}`;
    if (responseData && typeof responseData === 'object' && responseData.detail) {
      detail = typeof responseData.detail === 'string'
        ? responseData.detail
        : JSON.stringify(responseData.detail);
    } else if (typeof responseData === 'string' && responseData.length > 0 && responseData.length < 200) {
      detail = responseData;
    }
    throw new ApiError(res.status, detail, responseData);
  }

  return responseData;
}
