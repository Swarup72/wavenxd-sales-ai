/**
 * WaveNxD AI Sales Representative - Customer Application Bootstrap
 * Modular Architecture using native browser ES Modules
 */

import { state } from './core/state.js';
import { checkAuth, login, logout, acceptInvitation } from './core/auth.js';
import { openModal, closeModal } from './ui/modal.js';
import { openDrawer, closeDrawer } from './ui/drawer.js';
import { showToast } from './ui/notifications.js';
import { loadConversations, renderConversationList, createConversation, fetchConversationDetail } from './customer/conversations.js';
import { renderMessages, scrollToBottom, sendTextMessage } from './customer/chat.js';
import { renderConsultationSummary } from './customer/consultation-summary.js?v=20261023c';
import { renderTechnicalDetailsModal } from './customer/recommendations.js?v=20261023c';
import { fetchAssignedProducts, renderCatalogDrawer } from './customer/catalog.js';
import { startRecording, cancelRecording, stopAndSubmitRecording, uploadAndProcessAudio, synthesizeAndPlayAudio } from './customer/voice.js';
import { initCustomerLeadsModals } from './customer/leads.js';

// Global audio playback hook for test suites and templates
window.wavenxdPlayAudio = function (conversationId, messageId, buttonEl) {
  return synthesizeAndPlayAudio(conversationId, messageId, buttonEl);
};

document.addEventListener('DOMContentLoaded', async () => {
  // Initialize leads, quote preview, email draft, and follow-up modals
  initCustomerLeadsModals();
  // --- DOM Elements Cache ---
  const el = {
    // Views
    loginView: document.getElementById('loginView'),
    workspaceView: document.getElementById('workspaceView'),
    appHeader: document.getElementById('appHeader'),
    adminPortalLink: document.getElementById('adminPortalLink'),

    // Login Form
    loginForm: document.getElementById('loginForm'),
    emailInput: document.getElementById('emailInput'),
    passwordInput: document.getElementById('passwordInput'),
    loginErrorAlert: document.getElementById('loginErrorAlert'),
    loginSubmitBtn: document.getElementById('loginSubmitBtn'),

    // Header Profile
    userName: document.getElementById('userName'),
    userCompany: document.getElementById('userCompany'),
    logoutBtn: document.getElementById('logoutBtn'),

    // Sidebar
    newChatBtn: document.getElementById('newChatBtn'),
    searchConversationsInput: document.getElementById('searchConversationsInput'),
    conversationList: document.getElementById('conversationList'),
    catalogDrawerBtn: document.getElementById('catalogDrawerBtn'),

    // Chat
    activeChatTitle: document.getElementById('activeChatTitle'),
    activeLangBadge: document.getElementById('activeLangBadge'),
    messagesContainer: document.getElementById('messagesContainer'),
    messagesList: document.getElementById('messagesList'),
    emptyChatState: document.getElementById('emptyChatState'),
    typingIndicator: document.getElementById('typingIndicator'),
    chatInputArea: document.getElementById('chatInputArea'),
    messageInput: document.getElementById('messageInput'),
    sendBtn: document.getElementById('sendBtn'),
    recordBtn: document.getElementById('recordBtn'),
    audioUploadBtn: document.getElementById('audioUploadBtn'),
    audioFileInput: document.getElementById('audioFileInput'),
    recordingBar: document.getElementById('recordingBar'),
    recordingTimer: document.getElementById('recordingTimer'),
    cancelRecBtn: document.getElementById('cancelRecBtn'),
    stopRecBtn: document.getElementById('stopRecBtn'),

    // Consultation Summary Panel
    summaryPanel: document.getElementById('specPanel') || document.getElementById('summaryPanel'),
    matchStatusBadge: document.getElementById('matchStatusBadge'),
    matchSummaryText: document.getElementById('matchSummaryText'),
    reviewWarningPill: document.getElementById('reviewWarningPill'),
    knownReqsContainer: document.getElementById('knownReqsContainer'),
    missingInfoAccordion: document.getElementById('missingInfoAccordion'),
    missingInfoCount: document.getElementById('missingInfoCount'),
    missingInfoList: document.getElementById('missingInfoList'),
    compactProductCard: document.getElementById('compactProductCard'),
    compactProductEmpty: document.getElementById('compactProductEmpty'),
    compactProductContent: document.getElementById('compactProductContent'),
    compactProdName: document.getElementById('compactProdName'),
    compactProdKey: document.getElementById('compactProdKey'),
    compactProdMatchBadge: document.getElementById('compactProdMatchBadge'),
    compactProdExplanation: document.getElementById('compactProdExplanation'),
    openTechDetailsBtn: document.getElementById('openTechDetailsBtn'),

    // Technical Details Modal
    techDetailsModal: document.getElementById('techDetailsModal'),
    closeTechDetailsBtn: document.getElementById('closeTechDetailsBtn'),
    closeTechDetailsFooterBtn: document.getElementById('closeTechDetailsFooterBtn'),
    modalExtractedParamsGrid: document.getElementById('modalExtractedParamsGrid'),
    modalSpecGapsSection: document.getElementById('modalSpecGapsSection'),
    modalSpecGapsList: document.getElementById('modalSpecGapsList'),
    modalClarificationSection: document.getElementById('modalClarificationSection'),
    modalClarificationList: document.getElementById('modalClarificationList'),
    modalCandidateEvaluationsList: document.getElementById('modalCandidateEvaluationsList'),

    // Catalog Drawer
    catalogDrawer: document.getElementById('catalogDrawer'),
    closeDrawerBtn: document.getElementById('closeDrawerBtn'),
    drawerProductsList: document.getElementById('drawerProductsList'),
  };

  // --- View Switcher ---
  function showLoginView() {
    if (el.workspaceView) el.workspaceView.style.display = 'none';
    if (el.appHeader) el.appHeader.style.display = 'none';
    if (el.loginView) el.loginView.style.display = 'flex';
  }

  function showWorkspaceView() {
    if (el.loginView) el.loginView.style.display = 'none';
    if (el.appHeader) el.appHeader.style.display = 'flex';
    if (el.workspaceView) el.workspaceView.style.display = 'grid';

    // Populate header profile
    if (state.currentUser) {
      if (el.userName) el.userName.textContent = state.currentUser.full_name || state.currentUser.email;
      if (el.userCompany) el.userCompany.textContent = state.currentUser.company_name || 'WaveNxD Authorized Partner';
      if (el.adminPortalLink) {
        el.adminPortalLink.style.display = state.currentUser.role === 'admin' ? 'inline-flex' : 'none';
      }
    }
  }

  // --- Consultation Select Handler ---
  async function selectConversation(convId) {
    if (!convId) return;
    try {
      const detail = await fetchConversationDetail(convId);
      if (el.activeChatTitle) el.activeChatTitle.textContent = detail.title || 'Product Consultation';
      if (el.activeLangBadge) el.activeLangBadge.textContent = (detail.language || 'en').toUpperCase();

      renderMessages(detail.messages, el.messagesList, el.emptyChatState);
      scrollToBottom(el.messagesContainer, false);

      state.currentConversationId = convId;
      state.currentConversationDetail = detail;
      state.lastRecResult = detail.recommendation_result;
      renderConsultationSummary(state.lastRecResult, el, detail.requirements);
      renderTechnicalDetailsModal(state.lastRecResult, el, detail.requirements);

      // Re-render conversation list for active highlighting
      renderConversationList(
        state.conversations,
        el.conversationList,
        el.searchConversationsInput ? el.searchConversationsInput.value : '',
        selectConversation
      );
    } catch (err) {
      showToast(`Error switching consultation: ${err.message}`, 'error');
    }
  }

  // --- App Initialization ---
  async function initApp() {
    const user = await checkAuth();
    if (user) {
      if (user.role === 'admin') {
        window.location.href = '/admin';
        return;
      }
      showWorkspaceView();
      await fetchAssignedProducts();
      const convs = await loadConversations(el.conversationList);
      if (convs && convs.length > 0) {
        await selectConversation(convs[0].id);
      } else {
        // Automatically create initial consultation if list is empty
        const newC = await createConversation('Precision Atomization Consultation');
        await loadConversations(el.conversationList);
        await selectConversation(newC.id);
      }
    } else {
      showLoginView();
    }
  }

  // --- Event Listeners ---

  // 1. Login Form Submission
  if (el.loginForm) {
    el.loginForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = el.emailInput ? el.emailInput.value.trim() : '';
      const password = el.passwordInput ? el.passwordInput.value : '';

      if (el.loginSubmitBtn) {
        el.loginSubmitBtn.disabled = true;
        el.loginSubmitBtn.textContent = 'Signing In...';
      }
      if (el.loginErrorAlert) el.loginErrorAlert.style.display = 'none';

      try {
        const loggedUser = await login(email, password);
        if (loggedUser && loggedUser.role === 'admin') {
          window.location.href = '/admin';
          return;
        }
        await initApp();
      } catch (err) {
        if (el.loginErrorAlert) {
          el.loginErrorAlert.textContent = err.message || 'Invalid credentials or login failure';
          el.loginErrorAlert.style.display = 'block';
        }
      } finally {
        if (el.loginSubmitBtn) {
          el.loginSubmitBtn.disabled = false;
          el.loginSubmitBtn.textContent = 'Sign In to Portal';
        }
      }
    });
  }

  // 2. Demo Buttons
  document.querySelectorAll('.btn-demo').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const email = btn.getAttribute('data-email');
      const pass = btn.getAttribute('data-pass');
      if (el.emailInput) el.emailInput.value = email;
      if (el.passwordInput) el.passwordInput.value = pass;
      if (el.loginForm) {
        el.loginForm.dispatchEvent(new Event('submit', { cancelable: true }));
      }
    });
  });

  // 3. Logout
  if (el.logoutBtn) {
    el.logoutBtn.addEventListener('click', async () => {
      await logout();
      showLoginView();
      showToast('You have been signed out.', 'info');
    });
  }

  // 4. New Chat
  if (el.newChatBtn) {
    el.newChatBtn.addEventListener('click', async () => {
      try {
        const newC = await createConversation('New Atomization Consultation');
        await loadConversations(el.conversationList);
        await selectConversation(newC.id);
        showToast('New consultation created.', 'success');
      } catch (_) {}
    });
  }

  // 5. Search Filter in Sidebar
  if (el.searchConversationsInput) {
    el.searchConversationsInput.addEventListener('input', (e) => {
      renderConversationList(state.conversations, el.conversationList, e.target.value, selectConversation);
    });
  }

  // Helper to reconcile and render message response with consultation summary
  function handleMessageResponse(res) {
    if (!res || !res.assistant_message) return;
    if (!state.currentConversationDetail) state.currentConversationDetail = { messages: [] };
    if (!state.currentConversationDetail.messages) state.currentConversationDetail.messages = [];
    if (res.user_message) state.currentConversationDetail.messages.push(res.user_message);
    state.currentConversationDetail.messages.push(res.assistant_message);

    if (res.updated_requirements) {
      state.currentConversationDetail.requirements = res.updated_requirements;
    }
    if (res.recommendation_result) {
      state.lastRecResult = res.recommendation_result;
    }

    renderMessages(state.currentConversationDetail.messages, el.messagesList, el.emptyChatState);
    scrollToBottom(el.messagesContainer, true);

    renderConsultationSummary(state.lastRecResult, el, state.currentConversationDetail?.requirements);
    renderTechnicalDetailsModal(state.lastRecResult, el, state.currentConversationDetail?.requirements);
  }

  // 6. Send Message
  if (el.sendBtn) {
    el.sendBtn.addEventListener('click', () => {
      if (!state.currentConversationId) {
        showToast('Please select or create a consultation first.', 'warning');
        return;
      }
      const text = el.messageInput ? el.messageInput.value : '';
      sendTextMessage(state.currentConversationId, text, el, async (res) => {
        handleMessageResponse(res);
      });
    });
  }

  // Enter to send in textarea (Shift+Enter for newline)
  if (el.messageInput) {
    el.messageInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (el.sendBtn) el.sendBtn.click();
      }
    });

    // Auto-expanding textarea
    el.messageInput.addEventListener('input', () => {
      el.messageInput.style.height = 'auto';
      el.messageInput.style.height = Math.min(el.messageInput.scrollHeight, 140) + 'px';
    });
  }

  // Suggestion buttons in empty chat
  document.querySelectorAll('.btn-suggestion').forEach((btn) => {
    btn.addEventListener('click', () => {
      if (el.messageInput) {
        el.messageInput.value = btn.textContent.trim();
        el.messageInput.focus();
        if (el.sendBtn) el.sendBtn.click();
      }
    });
  });

  // 7. Voice Controls
  if (el.recordBtn) {
    el.recordBtn.addEventListener('click', () => {
      startRecording(el.recordingTimer, el.recordingBar);
    });
  }

  if (el.cancelRecBtn) {
    el.cancelRecBtn.addEventListener('click', () => {
      cancelRecording(el.recordingBar);
    });
  }

  if (el.stopRecBtn) {
    el.stopRecBtn.addEventListener('click', () => {
      stopAndSubmitRecording(el.recordingBar, (res) => {
        handleMessageResponse(res);
      });
    });
  }

  // Audio file upload
  if (el.audioUploadBtn && el.audioFileInput) {
    el.audioUploadBtn.addEventListener('click', () => el.audioFileInput.click());
    el.audioFileInput.addEventListener('change', (e) => {
      const file = e.target.files && e.target.files[0];
      if (file) {
        uploadAndProcessAudio(file, file.name, (res) => {
          handleMessageResponse(res);
        });
      }
      el.audioFileInput.value = '';
    });
  }

  // 8. Technical Details Modal
  if (el.openTechDetailsBtn && el.techDetailsModal) {
    el.openTechDetailsBtn.addEventListener('click', () => {
      renderTechnicalDetailsModal(state.lastRecResult, el, state.currentConversationDetail?.requirements);
      openModal(el.techDetailsModal, el.openTechDetailsBtn);
    });
  }

  if (el.closeTechDetailsBtn && el.techDetailsModal) {
    el.closeTechDetailsBtn.addEventListener('click', () => closeModal(el.techDetailsModal));
  }

  if (el.closeTechDetailsFooterBtn && el.techDetailsModal) {
    el.closeTechDetailsFooterBtn.addEventListener('click', () => closeModal(el.techDetailsModal));
  }

  // 9. Catalog Drawer
  if (el.catalogDrawerBtn && el.catalogDrawer) {
    el.catalogDrawerBtn.addEventListener('click', async () => {
      renderCatalogDrawer(state.assignedProducts, el.drawerProductsList);
      openDrawer(el.catalogDrawer, el.catalogDrawerBtn);
    });
  }

  if (el.closeDrawerBtn && el.catalogDrawer) {
    el.closeDrawerBtn.addEventListener('click', () => closeDrawer(el.catalogDrawer));
  }

  // 10. Mobile Sidebar & Summary Toggles
  const toggleSidebarBtn = document.getElementById('toggleSidebarBtn');
  const toggleSummaryBtn = document.getElementById('toggleSummaryBtn');
  const sidebar = document.getElementById('sidebar');
  const summaryPanel = el.summaryPanel;

  if (toggleSidebarBtn && sidebar) {
    toggleSidebarBtn.style.display = 'inline-flex';
    toggleSidebarBtn.addEventListener('click', () => {
      sidebar.classList.toggle('mobile-active');
      if (summaryPanel) summaryPanel.classList.remove('mobile-active');
    });
  }

  if (toggleSummaryBtn && summaryPanel) {
    toggleSummaryBtn.style.display = 'inline-flex';
    toggleSummaryBtn.addEventListener('click', () => {
      summaryPanel.classList.toggle('mobile-active');
      if (sidebar) sidebar.classList.remove('mobile-active');
    });
  }

  // 11. Candidate Invitation Activation Form
  const toggleInviteFormBtn = document.getElementById('toggleInviteFormBtn');
  const acceptInviteForm = document.getElementById('acceptInviteForm');
  const cancelInviteFormBtn = document.getElementById('cancelInviteFormBtn');
  const inviteTokenInput = document.getElementById('inviteTokenInput');
  const inviteNameInput = document.getElementById('inviteNameInput');
  const invitePasswordInput = document.getElementById('invitePasswordInput');
  const acceptInviteSubmitBtn = document.getElementById('acceptInviteSubmitBtn');
  const loginSuccessAlert = document.getElementById('loginSuccessAlert');

  if (toggleInviteFormBtn && acceptInviteForm && el.loginForm) {
    toggleInviteFormBtn.addEventListener('click', () => {
      el.loginForm.style.display = 'none';
      toggleInviteFormBtn.style.display = 'none';
      acceptInviteForm.style.display = 'block';
      if (el.loginErrorAlert) el.loginErrorAlert.style.display = 'none';
      if (loginSuccessAlert) loginSuccessAlert.style.display = 'none';
      if (inviteTokenInput) inviteTokenInput.focus();
    });
  }

  if (cancelInviteFormBtn && acceptInviteForm && el.loginForm) {
    cancelInviteFormBtn.addEventListener('click', () => {
      acceptInviteForm.style.display = 'none';
      el.loginForm.style.display = 'block';
      if (toggleInviteFormBtn) toggleInviteFormBtn.style.display = 'inline-block';
      if (el.loginErrorAlert) el.loginErrorAlert.style.display = 'none';
    });
  }

  if (acceptInviteForm) {
    acceptInviteForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const token = inviteTokenInput ? inviteTokenInput.value.trim() : '';
      const name = inviteNameInput ? inviteNameInput.value.trim() : '';
      const password = invitePasswordInput ? invitePasswordInput.value : '';

      if (acceptInviteSubmitBtn) {
        acceptInviteSubmitBtn.disabled = true;
        acceptInviteSubmitBtn.textContent = 'Activating...';
      }
      if (el.loginErrorAlert) el.loginErrorAlert.style.display = 'none';

      try {
        const user = await acceptInvitation(token, password, name);
        if (loginSuccessAlert) {
          loginSuccessAlert.textContent = `Account activated successfully for ${user.email}! Please sign in.`;
          loginSuccessAlert.style.display = 'block';
        }
        acceptInviteForm.reset();
        acceptInviteForm.style.display = 'none';
        el.loginForm.style.display = 'block';
        if (toggleInviteFormBtn) toggleInviteFormBtn.style.display = 'inline-block';
        if (el.emailInput) el.emailInput.value = user.email;
        if (el.passwordInput) el.passwordInput.focus();
        showToast('Account activated! You can now sign in.', 'success');
      } catch (err) {
        if (el.loginErrorAlert) {
          el.loginErrorAlert.textContent = err.message || 'Invitation acceptance failed.';
          el.loginErrorAlert.style.display = 'block';
        }
      } finally {
        if (acceptInviteSubmitBtn) {
          acceptInviteSubmitBtn.disabled = false;
          acceptInviteSubmitBtn.textContent = 'Activate Account & Sign In';
        }
      }
    });
  }

  // Initialize
  await initApp();
});
