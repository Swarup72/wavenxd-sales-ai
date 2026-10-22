/**
 * WaveNxD AI Sales Representative - Application Configuration
 */

export const CONFIG = {
  APP_NAME: 'WaveNxD AI Sales Representative',
  ENDPOINTS: {
    CSRF: '/auth/csrf',
    LOGIN: '/auth/login',
    LOGOUT: '/auth/logout',
    ME: '/auth/me',
    ACCEPT_INVITATION: '/auth/invitations/accept',
    CONVERSATIONS: '/customer/conversations',
    PRODUCTS: '/customer/products',
    ADMIN_OVERVIEW: '/admin/overview',
    ADMIN_COMPANIES: '/admin/companies',
    ADMIN_USERS: '/admin/users',
    ADMIN_INVITATIONS: '/admin/invitations',
    ADMIN_PRODUCTS: '/admin/products',
    ADMIN_ASSIGNMENTS: '/admin/assignments',
    ADMIN_REVIEW_QUEUE: '/admin/technical-review-queue',
    ADMIN_ACCESS_REQUESTS: '/admin/access-requests',
    ADMIN_SUPPORT: '/admin/support/conversations',
    ADMIN_PROVIDER_STATUS: '/admin/provider-status',
    ADMIN_AUDIT_LOGS: '/admin/audit-logs',
  },
  COOKIES: {
    CSRF: 'wavenxd_csrf',
    SESSION: 'wavenxd_session',
  },
  AUDIO: {
    MAX_FILE_SIZE_BYTES: 15 * 1024 * 1024, // 15MB
    SUPPORTED_MIME_TYPES: ['audio/wav', 'audio/mp3', 'audio/mpeg', 'audio/m4a', 'audio/webm', 'audio/ogg'],
  },
};
