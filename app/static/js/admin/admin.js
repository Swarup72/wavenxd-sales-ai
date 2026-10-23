/**
 * WaveNxD Admin Control Center - Orchestrator & Tab Manager
 */

import { apiRequest } from '../core/api.js';
import { checkAuth, logout } from '../core/auth.js';
import { showToast } from '../ui/notifications.js';
import { openModal, closeModal } from '../ui/modal.js';
import { escapeHtml } from '../ui/formatting.js';

import { loadCompanies, renderCompanies, toggleCompanyStatus, saveCompany } from './companies.js';
import { loadUsers, renderUsers, toggleUserStatus, resetUserPassword } from './users.js';
import { loadInvitations, renderInvitations, createAdminInvitation } from './invitations.js';
import { loadProducts, renderProducts, clearProductReview, saveProduct } from './products.js';
import { loadAssignments, renderAssignments, revokeAssignment, grantAssignment } from './assignments.js';
import { loadReviewsQueue, approveAccessRequest, rejectAccessRequest } from './technical-reviews.js';
import { loadSupportConversations, inspectConversation } from './consultations.js';
import { loadProviderStatus } from './provider-health.js';
import { loadAuditLogs } from './audit-log.js';
import { loadLeads, openLeadDetailModal, updateLeadStatus } from './leads.js?v=20261023c';

// Cache of loaded admin entities
const adminData = {
  companies: [],
  users: [],
  products: [],
  invitations: [],
};

let appInitialized = false;

// Global modal closer for inline onclick handlers in admin.html
window.adminCloseModal = function (modalId) {
  const modal = document.getElementById(modalId);
  if (modal) closeModal(modal);
};

export async function initAdminApp() {
  if (appInitialized) return;
  appInitialized = true;
  const el = {
    adminShell: document.getElementById('adminShell'),
    accessDeniedView: document.getElementById('accessDeniedView'),
    adminUserEmail: document.getElementById('adminUserEmail'),
    adminLogoutBtn: document.getElementById('adminLogoutBtn'),
    deniedSignOutBtn: document.getElementById('deniedSignOutBtn'),

    // Nav & Panes
    navItems: document.querySelectorAll('.admin-nav .nav-item'),
    tabPanes: document.querySelectorAll('.admin-main .tab-pane'),
    reviewBadgeCount: document.getElementById('reviewBadgeCount'),

    // Overview Stats
    statCompanies: document.getElementById('statCompanies'),
    statCompaniesSub: document.getElementById('statCompaniesSub'),
    statUsers: document.getElementById('statUsers'),
    statUsersSub: document.getElementById('statUsersSub'),
    statProducts: document.getElementById('statProducts'),
    statProductsSub: document.getElementById('statProductsSub'),
    statAssignments: document.getElementById('statAssignments'),
    statReviewQueue: document.getElementById('statReviewQueue'),
    statReviewQueueSub: document.getElementById('statReviewQueueSub'),
    statProvider: document.getElementById('statProvider'),
    refreshOverviewBtn: document.getElementById('refreshOverviewBtn'),

    // Companies
    companiesTableBody: document.getElementById('companiesTableBody'),
    searchCompaniesInput: document.getElementById('searchCompaniesInput'),
    openCreateCompanyBtn: document.getElementById('openCreateCompanyBtn'),
    companyModal: document.getElementById('companyModal'),
    companyModalTitle: document.getElementById('companyModalTitle'),
    companyForm: document.getElementById('companyForm'),
    companyEditId: document.getElementById('companyEditId'),
    companyNameInput: document.getElementById('companyNameInput'),
    companyEmailInput: document.getElementById('companyEmailInput'),
    companyNotesInput: document.getElementById('companyNotesInput'),
    companyStatusGroup: document.getElementById('companyStatusGroup'),
    companyActiveCheckbox: document.getElementById('companyActiveCheckbox'),

    // Users & Invitations
    searchUsersInput: document.getElementById('searchUsersInput'),
    usersTableBody: document.getElementById('usersTableBody'),
    invitationsTableBody: document.getElementById('invitationsTableBody'),
    subnavUsersListBtn: document.getElementById('subnavUsersListBtn'),
    subnavInvitationsListBtn: document.getElementById('subnavInvitationsListBtn'),
    usersSubPane: document.getElementById('usersSubPane'),
    invitationsSubPane: document.getElementById('invitationsSubPane'),
    openCreateInviteBtn: document.getElementById('openCreateInviteBtn'),
    inviteModal: document.getElementById('inviteModal'),
    inviteForm: document.getElementById('inviteForm'),
    inviteEmailInput: document.getElementById('inviteEmailInput'),
    inviteCompanySelect: document.getElementById('inviteCompanySelect'),
    inviteResultBox: document.getElementById('inviteResultBox'),
    inviteTokenDisplay: document.getElementById('inviteTokenDisplay'),
    resetPasswordModal: document.getElementById('resetPasswordModal'),
    resetPasswordForm: document.getElementById('resetPasswordForm'),
    resetPasswordUserId: document.getElementById('resetPasswordUserId'),
    resetPasswordUserEmail: document.getElementById('resetPasswordUserEmail'),
    newPasswordInput: document.getElementById('newPasswordInput'),

    // Products
    searchProductsInput: document.getElementById('searchProductsInput'),
    productsTableBody: document.getElementById('productsTableBody'),
    openCreateProductBtn: document.getElementById('openCreateProductBtn'),
    productModal: document.getElementById('productModal'),
    productModalTitle: document.getElementById('productModalTitle'),
    productForm: document.getElementById('productForm'),
    productEditId: document.getElementById('productEditId'),
    prodNameInput: document.getElementById('prodNameInput'),
    prodCatalogKeyInput: document.getElementById('prodCatalogKeyInput'),
    prodFreqInput: document.getElementById('prodFreqInput'),
    prodDropletInput: document.getElementById('prodDropletInput'),
    prodCategoryInput: document.getElementById('prodCategoryInput'),
    prodFlowMaxInput: document.getElementById('prodFlowMaxInput'),
    prodViscosityMaxInput: document.getElementById('prodViscosityMaxInput'),
    prodSprayPatternInput: document.getElementById('prodSprayPatternInput'),
    prodFeedConfigInput: document.getElementById('prodFeedConfigInput'),
    prodAppsInput: document.getElementById('prodAppsInput'),
    prodStatusSelect: document.getElementById('prodStatusSelect'),
    prodTechReviewCheckbox: document.getElementById('prodTechReviewCheckbox'),
    prodNotesInput: document.getElementById('prodNotesInput'),

    // Assignments
    assignmentsTableBody: document.getElementById('assignmentsTableBody'),
    assignmentCompanyFilter: document.getElementById('assignmentCompanyFilter'),
    openAssignModalBtn: document.getElementById('openAssignModalBtn'),
    assignmentModal: document.getElementById('assignmentModal'),
    assignmentForm: document.getElementById('assignmentForm'),
    assignCompanySelect: document.getElementById('assignCompanySelect'),
    assignProductSelect: document.getElementById('assignProductSelect'),

    // Reviews
    flaggedProdsTableBody: document.getElementById('flaggedProdsTableBody'),
    accessRequestsTableBody: document.getElementById('accessRequestsTableBody'),
    flaggedProdsCountBadge: document.getElementById('flaggedProdsCountBadge'),
    pendingRequestsCountBadge: document.getElementById('pendingRequestsCountBadge'),
    refreshReviewsBtn: document.getElementById('refreshReviewsBtn'),

    // Support Consultations
    supportConversationsTableBody: document.getElementById('supportConversationsTableBody'),
    supportCompanyFilter: document.getElementById('supportCompanyFilter'),
    refreshSupportBtn: document.getElementById('refreshSupportBtn'),
    supportModal: document.getElementById('supportModal'),
    supportModalTitle: document.getElementById('supportModalTitle'),
    supportModalSubtitle: document.getElementById('supportModalSubtitle'),
    supportMessagesList: document.getElementById('supportMessagesList'),

    // Provider Health
    paneProviders: document.getElementById('pane-providers'),
    refreshProviderStatusBtn: document.getElementById('refreshProviderStatusBtn'),

    // Audit Log
    auditTableBody: document.getElementById('auditTableBody'),
    auditActionFilter: document.getElementById('auditActionFilter'),
    refreshAuditBtn: document.getElementById('refreshAuditBtn'),

    // Leads & Inquiries
    leadsTableBody: document.getElementById('leadsTableBody'),
    leadCompanyFilter: document.getElementById('leadCompanyFilter'),
    leadStageFilter: document.getElementById('leadStageFilter'),
    refreshLeadsBtn: document.getElementById('refreshLeadsBtn'),
    exportLeadsCsvBtn: document.getElementById('exportLeadsCsvBtn'),
    adminLeadModal: document.getElementById('adminLeadModal'),
    adminLeadForm: document.getElementById('adminLeadForm'),
    saveAdminLeadBtn: document.getElementById('saveAdminLeadBtn'),
  };

  // --- Auth Verification ---
  const user = await checkAuth();
  if (!user || user.role !== 'admin') {
    if (el.adminShell) el.adminShell.style.display = 'none';
    if (el.accessDeniedView) el.accessDeniedView.style.display = 'flex';
    return;
  }

  if (el.adminShell) el.adminShell.style.display = 'flex';
  if (el.accessDeniedView) el.accessDeniedView.style.display = 'none';
  if (el.adminUserEmail) el.adminUserEmail.textContent = user.email;

  // --- Logout ---
  const handleLogout = async () => {
    await logout();
    window.location.href = '/login';
  };
  if (el.adminLogoutBtn) el.adminLogoutBtn.addEventListener('click', handleLogout);
  if (el.deniedSignOutBtn) el.deniedSignOutBtn.addEventListener('click', handleLogout);

  // --- Overview Loader ---
  async function loadOverview() {
    try {
      const stats = await apiRequest('/admin/overview');
      if (el.statCompanies) el.statCompanies.textContent = stats.total_companies ?? 0;
      if (el.statCompaniesSub) el.statCompaniesSub.textContent = `${stats.active_companies ?? 0} active companies`;
      if (el.statUsers) el.statUsers.textContent = stats.total_users ?? 0;
      if (el.statUsersSub) el.statUsersSub.textContent = `${stats.active_users ?? 0} active users`;
      if (el.statProducts) el.statProducts.textContent = stats.total_products ?? 0;
      if (el.statProductsSub) el.statProductsSub.textContent = `${stats.published_products ?? 0} published in catalog`;
      if (el.statAssignments) el.statAssignments.textContent = stats.active_assignments ?? 0;
      if (el.statReviewQueue) el.statReviewQueue.textContent = (stats.review_required_products ?? 0) + (stats.pending_access_requests ?? 0);
      if (el.statReviewQueueSub) {
        el.statReviewQueueSub.textContent = `${stats.review_required_products ?? 0} flagged nozzles, ${stats.pending_access_requests ?? 0} requests`;
      }
      if (el.statProvider) el.statProvider.textContent = (stats.primary_provider || 'Groq').toUpperCase();

      if (el.reviewBadgeCount) {
        const total = (stats.review_required_products ?? 0) + (stats.pending_access_requests ?? 0);
        el.reviewBadgeCount.textContent = total;
        el.reviewBadgeCount.style.display = total > 0 ? 'inline-block' : 'none';
      }
    } catch (err) {
      showToast(`Failed to load overview metrics: ${err.message}`, 'error');
    }
  }

  // Format company label human-readably with verified contact email / domain
  function formatCompanyLabel(c) {
    let name = c.name || 'Unnamed Company';
    // Clean trailing test hex ObjectIds from test suites for human presentation
    name = name.replace(/\s+[0-9a-f]{24}$/i, '');
    const email = c.contact_email ? ` (${c.contact_email})` : '';
    const status = c.is_active === false ? ' [Inactive]' : '';
    return `${name}${email}${status}`;
  }

  // --- Populate company dropdown filters across tabs ---
  async function ensureCompaniesList() {
    if (adminData.companies.length === 0) {
      adminData.companies = await apiRequest('/admin/companies').catch(() => []);
    }
    const comps = adminData.companies;
    const makeFilterOptions = (defaultLabel) =>
      `<option value="">${escapeHtml(defaultLabel)}</option>` +
      comps.map((c) => `<option value="${escapeHtml(c.id)}">${escapeHtml(formatCompanyLabel(c))}</option>`).join('');

    const activeComps = comps.filter((c) => c.is_active !== false);
    const inactiveComps = comps.filter((c) => c.is_active === false);

    const makeSelectOptions = () => {
      let html = '<option value="">Select Target Company…</option>';
      if (activeComps.length > 0) {
        html += `<optgroup label="Active Client Accounts">` +
          activeComps.map((c) => `<option value="${escapeHtml(c.id)}">${escapeHtml(formatCompanyLabel(c))}</option>`).join('') +
          `</optgroup>`;
      }
      if (inactiveComps.length > 0) {
        html += `<optgroup label="Inactive / Test Records">` +
          inactiveComps.map((c) => `<option value="${escapeHtml(c.id)}">${escapeHtml(formatCompanyLabel(c))}</option>`).join('') +
          `</optgroup>`;
      }
      return html;
    };

    if (el.assignmentCompanyFilter && el.assignmentCompanyFilter.options.length <= 1) {
      el.assignmentCompanyFilter.innerHTML = makeFilterOptions('All Companies');
    }
    if (el.supportCompanyFilter && el.supportCompanyFilter.options.length <= 1) {
      el.supportCompanyFilter.innerHTML = makeFilterOptions('All Companies');
    }
    if (el.leadCompanyFilter && el.leadCompanyFilter.options.length <= 1) {
      el.leadCompanyFilter.innerHTML = makeFilterOptions('All Companies');
    }
    if (el.inviteCompanySelect && el.inviteCompanySelect.options.length <= 1) {
      el.inviteCompanySelect.innerHTML = makeSelectOptions();
    }
    if (el.assignCompanySelect && el.assignCompanySelect.options.length <= 1) {
      el.assignCompanySelect.innerHTML = makeSelectOptions();
    }
  }

  // --- Tab Navigation Switcher ---
  // In admin.html, panes are identified by `id="pane-${targetTabId}"`!
  function switchTab(targetTabId) {
    const canonicalTab = targetTabId === 'consultations' ? 'support' : targetTabId;

    el.navItems.forEach((btn) => {
      const bTab = btn.getAttribute('data-tab');
      btn.classList.toggle('active', bTab === canonicalTab || (bTab === 'support' && targetTabId === 'consultations'));
    });

    el.tabPanes.forEach((pane) => {
      pane.classList.toggle('active', pane.id === `pane-${canonicalTab}`);
    });

    switch (canonicalTab) {
      case 'overview':
        loadOverview();
        break;
      case 'companies':
        loadCompanies(el.companiesTableBody).then((list) => {
          adminData.companies = list;
          ensureCompaniesList();
        });
        break;
      case 'users':
        loadUsers(el.usersTableBody).then((list) => { adminData.users = list; });
        loadInvitations(el.invitationsTableBody).then((list) => { adminData.invitations = list; });
        break;
      case 'products':
        loadProducts(el.productsTableBody).then((list) => { adminData.products = list; });
        break;
      case 'assignments':
        ensureCompaniesList();
        loadAssignments(el.assignmentsTableBody, el.assignmentCompanyFilter ? el.assignmentCompanyFilter.value : '');
        break;
      case 'reviews':
        loadReviewsQueue(el.accessRequestsTableBody, el.flaggedProdsTableBody, {
          navBadge: el.reviewBadgeCount,
          flaggedBadge: el.flaggedProdsCountBadge,
          requestsBadge: el.pendingRequestsCountBadge,
        });
        break;
      case 'support':
        ensureCompaniesList();
        loadSupportConversations(el.supportConversationsTableBody, el.supportCompanyFilter ? el.supportCompanyFilter.value : '');
        break;
      case 'leads':
        ensureCompaniesList();
        loadLeads(el.leadsTableBody, el.leadCompanyFilter ? el.leadCompanyFilter.value : '', el.leadStageFilter ? el.leadStageFilter.value : '');
        break;
      case 'providers':
        loadProviderStatus(el.paneProviders);
        break;
      case 'audit':
        loadAuditLogs(el.auditTableBody, el.auditActionFilter ? el.auditActionFilter.value : '');
        break;
      case 'settings':
        // Static policy presentation; verified active
        break;
    }
  }

  // Expose global tab switcher for action tiles on Overview
  window.adminSwitchTab = switchTab;

  el.navItems.forEach((btn) => {
    btn.addEventListener('click', () => {
      const tab = btn.getAttribute('data-tab');
      if (tab) switchTab(tab);
    });
  });

  // --- Overview Refresh ---
  if (el.refreshOverviewBtn) {
    el.refreshOverviewBtn.addEventListener('click', loadOverview);
  }

  // --- Subnav: Users vs Invitations ---
  if (el.subnavUsersListBtn && el.subnavInvitationsListBtn) {
    el.subnavUsersListBtn.addEventListener('click', () => {
      el.subnavUsersListBtn.classList.add('active');
      el.subnavInvitationsListBtn.classList.remove('active');
      if (el.usersSubPane) el.usersSubPane.style.display = 'block';
      if (el.invitationsSubPane) el.invitationsSubPane.style.display = 'none';
      loadUsers(el.usersTableBody).then((list) => { adminData.users = list; });
    });
    el.subnavInvitationsListBtn.addEventListener('click', () => {
      el.subnavInvitationsListBtn.classList.add('active');
      el.subnavUsersListBtn.classList.remove('active');
      if (el.usersSubPane) el.usersSubPane.style.display = 'none';
      if (el.invitationsSubPane) el.invitationsSubPane.style.display = 'block';
      loadInvitations(el.invitationsTableBody).then((list) => { adminData.invitations = list; });
    });
  }

  // --- Search & Filter Inputs ---
  if (el.searchCompaniesInput) {
    el.searchCompaniesInput.addEventListener('input', (e) => {
      renderCompanies(adminData.companies, el.companiesTableBody, e.target.value);
    });
  }
  if (el.searchUsersInput) {
    el.searchUsersInput.addEventListener('input', (e) => {
      renderUsers(adminData.users, el.usersTableBody, e.target.value);
    });
  }
  if (el.searchProductsInput) {
    el.searchProductsInput.addEventListener('input', (e) => {
      renderProducts(adminData.products, el.productsTableBody, e.target.value);
    });
  }
  if (el.assignmentCompanyFilter) {
    el.assignmentCompanyFilter.addEventListener('change', (e) => {
      loadAssignments(el.assignmentsTableBody, e.target.value);
    });
  }
  if (el.supportCompanyFilter) {
    el.supportCompanyFilter.addEventListener('change', (e) => {
      loadSupportConversations(el.supportConversationsTableBody, e.target.value);
    });
  }
  if (el.refreshSupportBtn) {
    el.refreshSupportBtn.addEventListener('click', () => {
      loadSupportConversations(el.supportConversationsTableBody, el.supportCompanyFilter ? el.supportCompanyFilter.value : '');
    });
  }
  if (el.refreshReviewsBtn) {
    el.refreshReviewsBtn.addEventListener('click', () => {
      loadReviewsQueue(el.accessRequestsTableBody, el.flaggedProdsTableBody, {
        navBadge: el.reviewBadgeCount,
        flaggedBadge: el.flaggedProdsCountBadge,
        requestsBadge: el.pendingRequestsCountBadge,
      });
    });
  }
  if (el.refreshProviderStatusBtn) {
    el.refreshProviderStatusBtn.addEventListener('click', () => {
      loadProviderStatus(el.paneProviders);
    });
  }
  if (el.auditActionFilter) {
    el.auditActionFilter.addEventListener('change', (e) => {
      loadAuditLogs(el.auditTableBody, e.target.value);
    });
  }
  if (el.refreshAuditBtn) {
    el.refreshAuditBtn.addEventListener('click', () => {
      loadAuditLogs(el.auditTableBody, el.auditActionFilter ? el.auditActionFilter.value : '');
    });
  }

  // --- Company Modal Handlers ---
  window.adminOpenEditCompany = (id) => {
    const comp = adminData.companies.find((c) => c.id === id);
    if (!comp) return;
    if (el.companyEditId) el.companyEditId.value = comp.id;
    if (el.companyModalTitle) el.companyModalTitle.textContent = 'Edit Company';
    if (el.companyNameInput) el.companyNameInput.value = comp.name;
    if (el.companyEmailInput) el.companyEmailInput.value = comp.contact_email || '';
    if (el.companyNotesInput) el.companyNotesInput.value = comp.notes || '';
    if (el.companyStatusGroup) el.companyStatusGroup.style.display = 'block';
    if (el.companyActiveCheckbox) el.companyActiveCheckbox.checked = comp.is_active;
    openModal(el.companyModal);
  };

  window.adminToggleCompanyStatus = (id, newActive) => {
    toggleCompanyStatus(id, newActive, () => {
      loadCompanies(el.companiesTableBody).then((list) => { adminData.companies = list; });
    });
  };

  if (el.openCreateCompanyBtn) {
    el.openCreateCompanyBtn.addEventListener('click', () => {
      if (el.companyForm) el.companyForm.reset();
      if (el.companyEditId) el.companyEditId.value = '';
      if (el.companyModalTitle) el.companyModalTitle.textContent = 'Register New Client Company';
      if (el.companyStatusGroup) el.companyStatusGroup.style.display = 'none';
      openModal(el.companyModal, el.openCreateCompanyBtn);
    });
  }

  if (el.companyForm) {
    el.companyForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const id = el.companyEditId ? el.companyEditId.value : '';
      const payload = {
        name: el.companyNameInput ? el.companyNameInput.value.trim() : '',
        contact_email: el.companyEmailInput && el.companyEmailInput.value.trim() ? el.companyEmailInput.value.trim() : null,
        notes: el.companyNotesInput ? el.companyNotesInput.value.trim() : null,
      };
      if (id && el.companyActiveCheckbox) {
        payload.is_active = el.companyActiveCheckbox.checked;
      }
      const btn = el.companyForm.querySelector('button[type="submit"]');
      const originalText = btn ? btn.textContent : 'Save Company';
      if (btn) {
        btn.disabled = true;
        btn.textContent = id ? 'Updating…' : 'Saving…';
      }
      try {
        await saveCompany(payload, id, () => {
          closeModal(el.companyModal);
          loadCompanies(el.companiesTableBody).then((list) => { adminData.companies = list; });
        });
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = originalText;
        }
      }
    });
  }

  // --- User Reset Password & Status ---
  window.adminOpenResetPassword = (userId, email) => {
    if (el.resetPasswordUserId) el.resetPasswordUserId.value = userId;
    if (el.resetPasswordUserEmail) el.resetPasswordUserEmail.textContent = email;
    if (el.newPasswordInput) el.newPasswordInput.value = '';
    openModal(el.resetPasswordModal);
  };

  window.adminToggleUserStatus = (id, newActive) => {
    toggleUserStatus(id, newActive, () => {
      loadUsers(el.usersTableBody).then((list) => { adminData.users = list; });
    });
  };

  if (el.resetPasswordForm) {
    el.resetPasswordForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const userId = el.resetPasswordUserId ? el.resetPasswordUserId.value : '';
      const newPass = el.newPasswordInput ? el.newPasswordInput.value : '';
      const btn = el.resetPasswordForm.querySelector('button[type="submit"]');
      const originalText = btn ? btn.textContent : 'Set New Password';
      if (btn) {
        btn.disabled = true;
        btn.textContent = 'Resetting…';
      }
      try {
        await resetUserPassword(userId, newPass, () => {
          closeModal(el.resetPasswordModal);
        });
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = originalText;
        }
      }
    });
  }

  // --- Invitation Modal Handlers ---
  if (el.openCreateInviteBtn) {
    el.openCreateInviteBtn.addEventListener('click', async () => {
      if (el.inviteForm) el.inviteForm.reset();
      if (el.inviteResultBox) el.inviteResultBox.style.display = 'none';
      await ensureCompaniesList();
      openModal(el.inviteModal, el.openCreateInviteBtn);
    });
  }

  if (el.inviteForm) {
    el.inviteForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = el.inviteEmailInput ? el.inviteEmailInput.value.trim() : '';
      const companyId = el.inviteCompanySelect ? el.inviteCompanySelect.value : '';
      if (!email || !companyId) return;

      const btn = el.inviteForm.querySelector('button[type="submit"]');
      const originalText = btn ? btn.textContent : 'Generate Invitation';
      if (btn) {
        btn.disabled = true;
        btn.textContent = 'Generating…';
      }
      try {
        const res = await createAdminInvitation(email, companyId);
        if (el.inviteResultBox && el.inviteTokenDisplay) {
          el.inviteTokenDisplay.textContent = res.invitation_token || res.token || 'Created';
          el.inviteResultBox.style.display = 'block';
        }
        loadInvitations(el.invitationsTableBody).then((list) => { adminData.invitations = list; });
      } catch (_) {
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = originalText;
        }
      }
    });
  }

  // --- Product Modal Handlers ---
  window.adminOpenEditProduct = (id) => {
    const prod = adminData.products.find((p) => p.id === id);
    if (!prod) return;
    if (el.productEditId) el.productEditId.value = prod.id;
    if (el.productModalTitle) el.productModalTitle.textContent = 'Edit Catalog Nozzle Model';
    if (el.prodNameInput) el.prodNameInput.value = prod.name;
    if (el.prodCatalogKeyInput) el.prodCatalogKeyInput.value = prod.catalog_key || '';
    if (el.prodCategoryInput) el.prodCategoryInput.value = prod.category || '';
    if (el.prodFreqInput) el.prodFreqInput.value = prod.frequency_khz ?? '';
    if (el.prodDropletInput) el.prodDropletInput.value = prod.droplet_size_um ?? '';
    if (el.prodFlowMaxInput) el.prodFlowMaxInput.value = prod.flow_rate_max_ml_min ?? '';
    if (el.prodViscosityMaxInput) el.prodViscosityMaxInput.value = prod.viscosity_max_cp ?? '';
    if (el.prodSprayPatternInput) el.prodSprayPatternInput.value = prod.spray_pattern || '';
    if (el.prodFeedConfigInput) el.prodFeedConfigInput.value = prod.feed_configuration || '';
    if (el.prodAppsInput) el.prodAppsInput.value = Array.isArray(prod.applications) ? prod.applications.join(', ') : '';
    if (el.prodStatusSelect) el.prodStatusSelect.value = prod.status || 'published';
    if (el.prodTechReviewCheckbox) el.prodTechReviewCheckbox.checked = !!prod.technical_review_required;
    if (el.prodNotesInput) el.prodNotesInput.value = prod.catalog_notes || '';

    openModal(el.productModal);
  };

  window.adminClearReview = (productId) => {
    clearProductReview(productId, () => {
      loadProducts(el.productsTableBody).then((list) => { adminData.products = list; });
      loadReviewsQueue(el.accessRequestsTableBody, el.flaggedProdsTableBody, {
        navBadge: el.reviewBadgeCount,
        flaggedBadge: el.flaggedProdsCountBadge,
        requestsBadge: el.pendingRequestsCountBadge,
      });
    });
  };

  if (el.openCreateProductBtn) {
    el.openCreateProductBtn.addEventListener('click', () => {
      if (el.productForm) el.productForm.reset();
      if (el.productEditId) el.productEditId.value = '';
      if (el.productModalTitle) el.productModalTitle.textContent = 'Add Catalog Nozzle Model';
      openModal(el.productModal, el.openCreateProductBtn);
    });
  }

  if (el.productForm) {
    el.productForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const id = el.productEditId ? el.productEditId.value : '';
      const apps = (el.prodAppsInput ? el.prodAppsInput.value : '')
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);

      const payload = {
        name: el.prodNameInput ? el.prodNameInput.value.trim() : '',
        catalog_key: el.prodCatalogKeyInput && el.prodCatalogKeyInput.value.trim() ? el.prodCatalogKeyInput.value.trim().toLowerCase() : null,
        category: el.prodCategoryInput && el.prodCategoryInput.value.trim() ? el.prodCategoryInput.value.trim() : null,
        frequency_khz: el.prodFreqInput && el.prodFreqInput.value ? parseFloat(el.prodFreqInput.value) : null,
        droplet_size_um: el.prodDropletInput && el.prodDropletInput.value ? parseFloat(el.prodDropletInput.value) : null,
        flow_rate_max_ml_min: el.prodFlowMaxInput && el.prodFlowMaxInput.value ? parseFloat(el.prodFlowMaxInput.value) : null,
        viscosity_max_cp: el.prodViscosityMaxInput && el.prodViscosityMaxInput.value ? parseFloat(el.prodViscosityMaxInput.value) : null,
        spray_pattern: el.prodSprayPatternInput && el.prodSprayPatternInput.value.trim() ? el.prodSprayPatternInput.value.trim() : null,
        feed_configuration: el.prodFeedConfigInput && el.prodFeedConfigInput.value.trim() ? el.prodFeedConfigInput.value.trim() : null,
        applications: apps,
        status: el.prodStatusSelect ? el.prodStatusSelect.value : 'published',
        technical_review_required: el.prodTechReviewCheckbox ? el.prodTechReviewCheckbox.checked : false,
        catalog_notes: el.prodNotesInput && el.prodNotesInput.value.trim() ? el.prodNotesInput.value.trim() : null,
      };

      const btn = el.productForm.querySelector('button[type="submit"]');
      const originalText = btn ? btn.textContent : 'Save Product';
      if (btn) {
        btn.disabled = true;
        btn.textContent = id ? 'Updating…' : 'Saving…';
      }
      try {
        await saveProduct(payload, id, () => {
          closeModal(el.productModal);
          loadProducts(el.productsTableBody).then((list) => { adminData.products = list; });
        });
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = originalText;
        }
      }
    });
  }

  // --- Assignment Modal Handlers ---
  window.adminRevokeAssignment = (companyId, productId) => {
    revokeAssignment(companyId, productId, () => {
      loadAssignments(el.assignmentsTableBody, el.assignmentCompanyFilter ? el.assignmentCompanyFilter.value : '');
    });
  };

  if (el.openAssignModalBtn) {
    el.openAssignModalBtn.addEventListener('click', async () => {
      await ensureCompaniesList();
      if (adminData.products.length === 0) {
        adminData.products = await apiRequest('/admin/products').catch(() => []);
      }
      if (el.assignProductSelect) {
        const publishedProds = adminData.products.filter((p) => p.status === 'published' || !p.status);
        const prods = publishedProds.length > 0 ? publishedProds : adminData.products;
        el.assignProductSelect.innerHTML = prods
          .map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)} (${escapeHtml(p.catalog_key || 'standard')})</option>`)
          .join('');
      }
      openModal(el.assignmentModal, el.openAssignModalBtn);
    });
  }

  if (el.assignmentForm) {
    el.assignmentForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const compId = el.assignCompanySelect ? el.assignCompanySelect.value : '';
      const prodId = el.assignProductSelect ? el.assignProductSelect.value : '';
      if (!compId || !prodId) return;

      const btn = el.assignmentForm.querySelector('button[type="submit"]');
      const originalText = btn ? btn.textContent : 'Grant Entitlement';
      if (btn) {
        btn.disabled = true;
        btn.textContent = 'Granting Entitlement…';
      }
      try {
        await grantAssignment(compId, prodId, () => {
          closeModal(el.assignmentModal);
          loadAssignments(el.assignmentsTableBody, el.assignmentCompanyFilter ? el.assignmentCompanyFilter.value : '');
        });
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = originalText;
        }
      }
    });
  }


  // --- Technical Review Actions ---
  window.adminApproveAccessRequest = (reqId) => {
    approveAccessRequest(reqId, () => {
      loadReviewsQueue(el.accessRequestsTableBody, el.flaggedProdsTableBody, {
        navBadge: el.reviewBadgeCount,
        flaggedBadge: el.flaggedProdsCountBadge,
        requestsBadge: el.pendingRequestsCountBadge,
      });
    });
  };

  window.adminRejectAccessRequest = (reqId) => {
    rejectAccessRequest(reqId, () => {
      loadReviewsQueue(el.accessRequestsTableBody, el.flaggedProdsTableBody, {
        navBadge: el.reviewBadgeCount,
        flaggedBadge: el.flaggedProdsCountBadge,
        requestsBadge: el.pendingRequestsCountBadge,
      });
    });
  };

  // --- Support Conversation Inspection ---
  window.adminInspectConversation = (convId) => {
    inspectConversation(convId, {
      titleEl: el.supportModalTitle,
      subtitleEl: el.supportModalSubtitle,
      messagesListEl: el.supportMessagesList,
    }).then(() => {
      openModal(el.supportModal);
    });
  };

  // --- Click Event Delegation on Table Action Buttons ---
  // Guarantees all data-action buttons trigger their respective handlers reliably
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-action]');
    if (!btn) return;
    const action = btn.getAttribute('data-action');
    const id = btn.getAttribute('data-id');

    switch (action) {
      case 'edit-company':
        window.adminOpenEditCompany(id);
        break;
      case 'toggle-company':
        window.adminToggleCompanyStatus(id, btn.getAttribute('data-active') === 'true');
        break;
      case 'reset-password':
        window.adminOpenResetPassword(id, btn.getAttribute('data-email'));
        break;
      case 'toggle-user':
        window.adminToggleUserStatus(id, btn.getAttribute('data-active') === 'true');
        break;
      case 'edit-product':
        window.adminOpenEditProduct(id);
        break;
      case 'clear-review':
        window.adminClearReview(id);
        break;
      case 'revoke-assignment':
        window.adminRevokeAssignment(btn.getAttribute('data-company-id'), btn.getAttribute('data-product-id'));
        break;
      case 'approve-request':
        window.adminApproveAccessRequest(id);
        break;
      case 'reject-request':
        window.adminRejectAccessRequest(id);
        break;
      case 'inspect-conversation':
        window.adminInspectConversation(id);
        break;
    }
  });

  // --- Leads & Inquiries Event Listeners ---
  if (el.leadCompanyFilter) {
    el.leadCompanyFilter.addEventListener('change', () => {
      loadLeads(el.leadsTableBody, el.leadCompanyFilter.value, el.leadStageFilter ? el.leadStageFilter.value : '');
    });
  }
  if (el.leadStageFilter) {
    el.leadStageFilter.addEventListener('change', () => {
      loadLeads(el.leadsTableBody, el.leadCompanyFilter ? el.leadCompanyFilter.value : '', el.leadStageFilter.value);
    });
  }
  if (el.refreshLeadsBtn) {
    el.refreshLeadsBtn.addEventListener('click', () => {
      loadLeads(el.leadsTableBody, el.leadCompanyFilter ? el.leadCompanyFilter.value : '', el.leadStageFilter ? el.leadStageFilter.value : '');
    });
  }
  if (el.exportLeadsCsvBtn) {
    el.exportLeadsCsvBtn.addEventListener('click', () => {
      const company = el.leadCompanyFilter ? el.leadCompanyFilter.value : '';
      const stage = el.leadStageFilter ? el.leadStageFilter.value : '';
      const params = new URLSearchParams();
      if (company) params.append('company_id', company);
      if (stage) params.append('stage', stage);
      const q = params.toString() ? `?${params.toString()}` : '';
      window.location.href = `/admin/leads/export/csv${q}`;
    });
  }
  if (el.adminLeadForm) {
    el.adminLeadForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const leadId = document.getElementById('adminLeadId')?.value;
      const stage = document.getElementById('adminLeadStageSelect')?.value;
      const notes = document.getElementById('adminLeadInternalNotes')?.value;
      if (!leadId) return;

      if (el.saveAdminLeadBtn) {
        el.saveAdminLeadBtn.disabled = true;
        el.saveAdminLeadBtn.textContent = 'Updating...';
      }
      try {
        await updateLeadStatus(leadId, stage, notes);
        showToast('Lead status updated successfully.', 'success');
        closeModal(el.adminLeadModal);
        loadLeads(el.leadsTableBody, el.leadCompanyFilter ? el.leadCompanyFilter.value : '', el.leadStageFilter ? el.leadStageFilter.value : '');
      } catch (err) {
        showToast(`Failed to update lead: ${err.message}`, 'error');
      } finally {
        if (el.saveAdminLeadBtn) {
          el.saveAdminLeadBtn.disabled = false;
          el.saveAdminLeadBtn.textContent = 'Update Lead Status';
        }
      }
    });
  }

  // Load Overview by default
  await loadOverview();
}

// Ensure automatic boot whether loaded directly or via entry point
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initAdminApp);
} else {
  initAdminApp();
}
