/**
 * WaveNxD AI Sales Representative - Customer Leads, Quotation, Email Draft & Follow-Up
 */

import { state } from '../core/state.js';
import { apiRequest } from '../core/api.js';
import { openModal, closeModal } from '../ui/modal.js';
import { showToast } from '../ui/notifications.js';
import { escapeHtml } from '../ui/formatting.js';

export function initCustomerLeadsModals() {
  const el = {
    // Open Buttons
    openLeadModalBtn: document.getElementById('openLeadModalBtn'),
    openQuoteModalBtn: document.getElementById('openQuoteModalBtn'),
    openFollowUpModalBtn: document.getElementById('openFollowUpModalBtn'),

    // Lead Modal
    leadModal: document.getElementById('leadModal'),
    closeLeadModalBtn: document.getElementById('closeLeadModalBtn'),
    leadForm: document.getElementById('leadForm'),
    leadCustomerName: document.getElementById('leadCustomerName'),
    leadCompanyName: document.getElementById('leadCompanyName'),
    leadEmail: document.getElementById('leadEmail'),
    leadPhone: document.getElementById('leadPhone'),
    leadIndustry: document.getElementById('leadIndustry'),
    leadApplication: document.getElementById('leadApplication'),
    leadMaterial: document.getElementById('leadMaterial'),
    leadFlowRate: document.getElementById('leadFlowRate'),
    leadViscosity: document.getElementById('leadViscosity'),
    leadDropletSize: document.getElementById('leadDropletSize'),
    leadNotes: document.getElementById('leadNotes'),
    leadRecommendedProducts: document.getElementById('leadRecommendedProducts'),
    saveLeadSubmitBtn: document.getElementById('saveLeadSubmitBtn'),

    // Quote Modal
    quoteModal: document.getElementById('quoteModal'),
    closeQuoteModalBtn: document.getElementById('closeQuoteModalBtn'),
    quotePreviewContainer: document.getElementById('quotePreviewContainer'),
    printQuoteBtn: document.getElementById('printQuoteBtn'),
    downloadQuoteHtmlBtn: document.getElementById('downloadQuoteHtmlBtn'),
    quoteToEmailDraftBtn: document.getElementById('quoteToEmailDraftBtn'),

    // Email Draft Modal
    emailDraftModal: document.getElementById('emailDraftModal'),
    closeEmailDraftModalBtn: document.getElementById('closeEmailDraftModalBtn'),
    emailDraftTo: document.getElementById('emailDraftTo'),
    emailDraftSubject: document.getElementById('emailDraftSubject'),
    emailDraftBody: document.getElementById('emailDraftBody'),
    emailDraftStatusBadge: document.getElementById('emailDraftStatusBadge'),
    downloadEmlBtn: document.getElementById('downloadEmlBtn'),
    simulateEmailBtn: document.getElementById('simulateEmailBtn'),
    simulationResultBox: document.getElementById('simulationResultBox'),

    // Follow-Up Modal
    followUpModal: document.getElementById('followUpModal'),
    closeFollowUpModalBtn: document.getElementById('closeFollowUpModalBtn'),
    followUpForm: document.getElementById('followUpForm'),
    followUpDatetime: document.getElementById('followUpDatetime'),
    followUpTimezone: document.getElementById('followUpTimezone'),
    followUpDuration: document.getElementById('followUpDuration'),
    followUpNotes: document.getElementById('followUpNotes'),
    saveFollowUpSubmitBtn: document.getElementById('saveFollowUpSubmitBtn'),
    followUpSuccessBox: document.getElementById('followUpSuccessBox'),
    downloadIcsBtn: document.getElementById('downloadIcsBtn'),
    googleCalendarBtn: document.getElementById('googleCalendarBtn'),
  };

  // Helper: prefill lead form from current user and conversation state
  function prefillLeadForm() {
    if (!state.currentConversationId) {
      showToast('Please open or start a consultation first.', 'warning');
      return false;
    }
    const user = state.currentUser;
    if (user) {
      if (el.leadCustomerName) el.leadCustomerName.value = user.full_name || '';
      if (el.leadCompanyName) el.leadCompanyName.value = user.company_name || '';
      if (el.leadEmail) el.leadEmail.value = user.email || '';
    }

    const detail = state.currentConversationDetail;
    const reqs = (detail && detail.requirements) ? detail.requirements : {};

    if (el.leadApplication) el.leadApplication.value = reqs.application || '';
    if (el.leadMaterial) el.leadMaterial.value = reqs.coating_material || '';
    if (el.leadFlowRate) {
      el.leadFlowRate.value = reqs.flow_rate_ml_min ? `${reqs.flow_rate_ml_min} ml/min` : '';
    }
    if (el.leadViscosity) {
      el.leadViscosity.value = reqs.viscosity_cp ? `${reqs.viscosity_cp} cP` : '';
    }
    if (el.leadDropletSize) {
      el.leadDropletSize.value = reqs.target_droplet_size_um ? `${reqs.target_droplet_size_um} µm` : '';
    }

    // Recommended products
    const rec = (detail && detail.last_recommendation) ? detail.last_recommendation : null;
    if (rec && rec.recommended_product_ids && rec.recommended_product_ids.length > 0) {
      if (el.leadRecommendedProducts) {
        el.leadRecommendedProducts.textContent = rec.recommended_product_ids.join(', ');
      }
    } else {
      if (el.leadRecommendedProducts) {
        el.leadRecommendedProducts.textContent = 'Engineering evaluation in progress';
      }
    }

    return true;
  }

  // 1. OPEN LEAD MODAL
  if (el.openLeadModalBtn) {
    el.openLeadModalBtn.addEventListener('click', async () => {
      if (!prefillLeadForm()) return;

      // Try checking if a lead already exists for this conversation
      try {
        const existing = await apiRequest(`/customer/leads/conversation/${state.currentConversationId}`);
        if (existing) {
          if (existing.customer_name && el.leadCustomerName) el.leadCustomerName.value = existing.customer_name;
          if (existing.company_name && el.leadCompanyName) el.leadCompanyName.value = existing.company_name;
          if (existing.email && el.leadEmail) el.leadEmail.value = existing.email;
          if (existing.phone && el.leadPhone) el.leadPhone.value = existing.phone;
          if (existing.industry && el.leadIndustry) el.leadIndustry.value = existing.industry;
          if (existing.notes && el.leadNotes) el.leadNotes.value = existing.notes;
        }
      } catch (_) {}

      openModal(el.leadModal);
    });
  }

  if (el.closeLeadModalBtn) {
    el.closeLeadModalBtn.addEventListener('click', () => closeModal(el.leadModal));
  }

  // SAVE LEAD
  if (el.leadForm) {
    el.leadForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!state.currentConversationId) return;

      const payload = {
        conversation_id: state.currentConversationId,
        customer_name: (el.leadCustomerName?.value || '').trim(),
        company_name: (el.leadCompanyName?.value || '').trim() || undefined,
        email: (el.leadEmail?.value || '').trim(),
        phone: (el.leadPhone?.value || '').trim() || undefined,
        industry: (el.leadIndustry?.value || '').trim() || undefined,
        application: (el.leadApplication?.value || '').trim() || undefined,
        coating_material: (el.leadMaterial?.value || '').trim() || undefined,
        flow_rate: (el.leadFlowRate?.value || '').trim() || undefined,
        viscosity: (el.leadViscosity?.value || '').trim() || undefined,
        droplet_size: (el.leadDropletSize?.value || '').trim() || undefined,
        technical_notes: (el.leadNotes?.value || '').trim() || undefined,
      };

      if (!payload.customer_name || !payload.email) {
        showToast('Please provide your name and contact email.', 'warning');
        return;
      }

      if (el.saveLeadSubmitBtn) {
        el.saveLeadSubmitBtn.disabled = true;
        el.saveLeadSubmitBtn.textContent = 'Saving Inquiry...';
      }

      try {
        const res = await apiRequest('/customer/leads', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        showToast('Inquiry saved successfully! WaveNxD engineering has logged your requirements.', 'success');
        closeModal(el.leadModal);
      } catch (err) {
        showToast(`Failed to save lead: ${err.message}`, 'error');
      } finally {
        if (el.saveLeadSubmitBtn) {
          el.saveLeadSubmitBtn.disabled = false;
          el.saveLeadSubmitBtn.textContent = 'Save Formal Inquiry';
        }
      }
    });
  }

  // 2. OPEN QUOTE PREVIEW
  if (el.openQuoteModalBtn) {
    el.openQuoteModalBtn.addEventListener('click', async () => {
      if (!state.currentConversationId) {
        showToast('Please open or start a consultation first.', 'warning');
        return;
      }
      openModal(el.quoteModal);
      if (el.quotePreviewContainer) {
        el.quotePreviewContainer.innerHTML = '<div style="text-align: center; padding: 30px; color: var(--text-muted);">Generating quotation preview from authorized catalog...</div>';
      }

      try {
        const quote = await apiRequest(`/customer/conversations/${state.currentConversationId}/quote-preview`);
        renderQuotePreview(quote);
      } catch (err) {
        if (el.quotePreviewContainer) {
          el.quotePreviewContainer.innerHTML = `<div style="text-align: center; padding: 30px; color: var(--text-danger);">Failed to generate quotation: ${escapeHtml(err.message)}</div>`;
        }
      }
    });
  }

  if (el.closeQuoteModalBtn) {
    el.closeQuoteModalBtn.addEventListener('click', () => closeModal(el.quoteModal));
  }

  function renderQuotePreview(quote) {
    if (!el.quotePreviewContainer) return;

    let reviewHtml = '';
    if (quote.technical_review_required) {
      reviewHtml = `
        <div style="background: rgba(245, 158, 11, 0.1); border: 1px solid #F59E0B; border-radius: 6px; padding: 12px; margin-bottom: 16px; color: #B45309;">
          <strong>⚠️ Engineering Technical Review Required:</strong> ${escapeHtml(quote.review_notes || 'Requires engineering signoff prior to commercial dispatch.')}
        </div>
      `;
    }

    let prodsHtml = '';
    if (quote.products && quote.products.length > 0) {
      prodsHtml = quote.products.map((p) => `
        <div style="border: 1px solid var(--border-color); border-radius: 6px; padding: 12px; margin-bottom: 12px; background: var(--surface-bg);">
          <div style="display: flex; justify-content: space-between; align-items: baseline;">
            <h4 style="margin: 0; color: var(--text-primary); font-size: 1rem;">${escapeHtml(p.product_name)} <span style="font-size: 0.8rem; color: var(--text-muted); font-weight: normal;">(${escapeHtml(p.catalog_key)})</span></h4>
            <span style="font-weight: 600; color: #0284C7; font-size: 0.85rem;">${escapeHtml(p.pricing)}</span>
          </div>
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px; margin-top: 10px; font-size: 0.8rem;">
            <div><strong>Frequency:</strong> ${p.frequency_khz ? p.frequency_khz + ' kHz' : 'N/A'}</div>
            <div><strong>Droplet Size:</strong> ${escapeHtml(p.droplet_size || 'N/A')}</div>
            <div><strong>Max Flow Rate:</strong> ${p.max_flow_rate_ml_min ? p.max_flow_rate_ml_min + ' ml/min' : 'N/A'}</div>
            <div><strong>Max Viscosity:</strong> ${p.max_viscosity_cp ? p.max_viscosity_cp + ' cP' : 'N/A'}</div>
          </div>
          ${p.match_reasons && p.match_reasons.length > 0 ? `
            <div style="margin-top: 8px; font-size: 0.8rem; color: #16A34A;">
              <strong>Match Reasons:</strong> ${p.match_reasons.map((r) => escapeHtml(r)).join('; ')}
            </div>
          ` : ''}
        </div>
      `).join('');
    } else {
      prodsHtml = `<div style="padding: 16px; color: var(--text-muted); font-style: italic;">No specific nozzle currently recommended. Consultation requires additional process parameters.</div>`;
    }

    const reqs = quote.requirements || {};

    el.quotePreviewContainer.innerHTML = `
      <div style="padding: 8px; font-family: inherit;">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid var(--border-color); padding-bottom: 12px; margin-bottom: 16px;">
          <div>
            <h3 style="margin: 0; font-size: 1.2rem; color: var(--text-primary);">${escapeHtml(quote.heading || 'WaveNxD AI Sales Representative')}</h3>
            <div style="color: #64748B; font-weight: 600; font-size: 0.85rem; margin-top: 4px;">${escapeHtml(quote.subheading || 'Quotation Draft — Subject to Commercial Confirmation')}</div>
          </div>
          <div style="text-align: right; font-size: 0.8rem; color: var(--text-muted);">
            <div><strong>Quote Ref:</strong> ${escapeHtml(quote.quote_reference || 'N/A')}</div>
            <div><strong>Date:</strong> ${escapeHtml(quote.date_generated || '')}</div>
          </div>
        </div>

        ${reviewHtml}

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; font-size: 0.85rem; background: var(--surface-bg); padding: 12px; border-radius: 6px;">
          <div>
            <strong style="display: block; margin-bottom: 4px; color: var(--text-muted); font-size: 0.75rem; text-transform: uppercase;">Customer Profile:</strong>
            <div><strong>Name:</strong> ${escapeHtml(quote.customer_name || 'Valued Customer')}</div>
            <div><strong>Company:</strong> ${escapeHtml(quote.company_name || 'WaveNxD Partner')}</div>
            <div><strong>Email:</strong> ${escapeHtml(quote.contact_email || 'On file')}</div>
          </div>
          <div>
            <strong style="display: block; margin-bottom: 4px; color: var(--text-muted); font-size: 0.75rem; text-transform: uppercase;">Process Specifications:</strong>
            <div><strong>Application:</strong> ${escapeHtml(reqs.application || 'Unspecified')}</div>
            <div><strong>Fluid:</strong> ${escapeHtml(reqs.coating_material || 'Unspecified')}</div>
            <div><strong>Flow Rate:</strong> ${reqs.flow_rate_ml_min ? reqs.flow_rate_ml_min + ' ml/min' : 'Unspecified'}</div>
            <div><strong>Viscosity:</strong> ${reqs.viscosity_cp ? reqs.viscosity_cp + ' cP' : 'Unspecified'}</div>
          </div>
        </div>

        <h4 style="margin: 16px 0 8px 0; font-size: 0.95rem; color: var(--text-primary);">Evaluated Ultrasonic Nozzle Equipment</h4>
        ${prodsHtml}

        <div style="background: rgba(14, 165, 233, 0.08); border-left: 4px solid #0EA5E9; padding: 10px 14px; border-radius: 4px; margin-top: 16px; font-size: 0.8rem; color: var(--text-primary);">
          <strong>Commercial Terms Notice:</strong> ${escapeHtml(quote.commercial_status || 'Price on Application — Final pricing and commercial terms require confirmation by WaveNxD.')}
        </div>
      </div>
    `;
  }

  // Print Quote
  if (el.printQuoteBtn) {
    el.printQuoteBtn.addEventListener('click', () => {
      if (!state.currentConversationId) return;
      window.open(`/customer/conversations/${state.currentConversationId}/quote-preview/download`, '_blank');
    });
  }

  // Download Quote HTML
  if (el.downloadQuoteHtmlBtn) {
    el.downloadQuoteHtmlBtn.addEventListener('click', () => {
      if (!state.currentConversationId) return;
      const a = document.createElement('a');
      a.href = `/customer/conversations/${state.currentConversationId}/quote-preview/download`;
      a.download = `wavenxd_quote_${state.currentConversationId.substring(0, 8)}.html`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    });
  }

  // Navigate from Quote to Email Draft
  if (el.quoteToEmailDraftBtn) {
    el.quoteToEmailDraftBtn.addEventListener('click', () => {
      closeModal(el.quoteModal);
      openEmailDraftModal();
    });
  }

  // 3. EMAIL DRAFT MODAL
  async function openEmailDraftModal() {
    if (!state.currentConversationId) {
      showToast('Please open or start a consultation first.', 'warning');
      return;
    }
    openModal(el.emailDraftModal);
    if (el.simulationResultBox) el.simulationResultBox.style.display = 'none';

    try {
      const draft = await apiRequest(`/customer/conversations/${state.currentConversationId}/email-draft`);
      if (el.emailDraftTo) el.emailDraftTo.textContent = draft.recipient_email || 'Not specified';
      if (el.emailDraftSubject) el.emailDraftSubject.textContent = draft.subject || 'WaveNxD Technical Quotation';
      if (el.emailDraftBody) el.emailDraftBody.textContent = draft.body || '';
      if (el.emailDraftStatusBadge) {
        el.emailDraftStatusBadge.textContent = (draft.status || 'PREVIEW').toUpperCase();
      }
    } catch (err) {
      showToast(`Failed to load email draft: ${err.message}`, 'error');
    }
  }

  if (el.closeEmailDraftModalBtn) {
    el.closeEmailDraftModalBtn.addEventListener('click', () => closeModal(el.emailDraftModal));
  }

  // Download .eml
  if (el.downloadEmlBtn) {
    el.downloadEmlBtn.addEventListener('click', () => {
      if (!state.currentConversationId) return;
      const a = document.createElement('a');
      a.href = `/customer/conversations/${state.currentConversationId}/email-draft/download`;
      a.download = `wavenxd_quotation_${state.currentConversationId.substring(0, 8)}.eml`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      showToast('Downloaded RFC 822 .eml draft file.', 'info');
    });
  }

  // Simulate Email Delivery
  if (el.simulateEmailBtn) {
    el.simulateEmailBtn.addEventListener('click', async () => {
      if (!state.currentConversationId) return;
      try {
        const res = await apiRequest(`/customer/conversations/${state.currentConversationId}/email-simulate`, {
          method: 'POST',
        });
        if (el.simulationResultBox) {
          el.simulationResultBox.style.display = 'block';
          el.simulationResultBox.innerHTML = `
            <div style="font-weight: 600; color: #16A34A; margin-bottom: 4px;">Status: SIMULATED (Success)</div>
            <div style="font-size: 0.8rem; color: var(--text-muted);">${escapeHtml(res.note)}</div>
          `;
        }
        showToast('Simulated dispatch test successful (no live email was sent).', 'success');
      } catch (err) {
        showToast(`Simulation failed: ${err.message}`, 'error');
      }
    });
  }

  // 4. FOLLOW-UP SCHEDULING
  if (el.openFollowUpModalBtn) {
    el.openFollowUpModalBtn.addEventListener('click', () => {
      if (!state.currentConversationId) {
        showToast('Please open or start a consultation first.', 'warning');
        return;
      }
      openModal(el.followUpModal);
      if (el.followUpSuccessBox) el.followUpSuccessBox.style.display = 'none';

      // Auto-populate local timezone
      try {
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        if (el.followUpTimezone) el.followUpTimezone.value = tz || 'Asia/Kolkata';
      } catch (_) {
        if (el.followUpTimezone) el.followUpTimezone.value = 'Asia/Kolkata';
      }

      // Default datetime to tomorrow at 10:00 AM local
      if (el.followUpDatetime && !el.followUpDatetime.value) {
        const tomorrow = new Date();
        tomorrow.setDate(tomorrow.getDate() + 1);
        tomorrow.setHours(10, 0, 0, 0);
        const isoLocal = new Date(tomorrow.getTime() - (tomorrow.getTimezoneOffset() * 60000)).toISOString().slice(0, 16);
        el.followUpDatetime.value = isoLocal;
      }
    });
  }

  if (el.closeFollowUpModalBtn) {
    el.closeFollowUpModalBtn.addEventListener('click', () => closeModal(el.followUpModal));
  }

  if (el.followUpForm) {
    el.followUpForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!state.currentConversationId) return;

      const dtVal = el.followUpDatetime?.value;
      if (!dtVal) {
        showToast('Please specify a date and time for the follow-up.', 'warning');
        return;
      }

      // Convert local date time to ISO string
      const isoDt = new Date(dtVal).toISOString();
      const payload = {
        proposed_datetime: isoDt,
        timezone: el.followUpTimezone?.value || 'Asia/Kolkata',
        duration_minutes: parseInt(el.followUpDuration?.value || '30', 10),
        notes: (el.followUpNotes?.value || '').trim() || undefined,
      };

      if (el.saveFollowUpSubmitBtn) {
        el.saveFollowUpSubmitBtn.disabled = true;
        el.saveFollowUpSubmitBtn.textContent = 'Generating Invitation...';
      }

      try {
        const res = await apiRequest(`/customer/conversations/${state.currentConversationId}/follow-up`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        if (el.followUpSuccessBox) {
          el.followUpSuccessBox.style.display = 'block';
        }

        // Setup .ics download button
        if (el.downloadIcsBtn) {
          el.downloadIcsBtn.onclick = () => {
            const a = document.createElement('a');
            a.href = `/customer/conversations/${state.currentConversationId}/follow-up/calendar.ics`;
            a.download = `wavenxd_consultation_${state.currentConversationId.substring(0, 8)}.ics`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
          };
        }

        // Setup Google Calendar button
        if (el.googleCalendarBtn && res.google_calendar_url) {
          el.googleCalendarBtn.onclick = () => {
            window.open(res.google_calendar_url, '_blank');
          };
          el.googleCalendarBtn.style.display = 'inline-flex';
        } else if (el.googleCalendarBtn) {
          el.googleCalendarBtn.style.display = 'none';
        }

        showToast('Follow-up invitation prepared. Download the calendar file to import into your calendar.', 'success');
      } catch (err) {
        showToast(`Failed to schedule follow-up: ${err.message}`, 'error');
      } finally {
        if (el.saveFollowUpSubmitBtn) {
          el.saveFollowUpSubmitBtn.disabled = false;
          el.saveFollowUpSubmitBtn.textContent = 'Prepare Follow-Up Invitation';
        }
      }
    });
  }
}
