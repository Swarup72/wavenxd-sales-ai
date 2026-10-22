import { escapeHtml, formatParamValue } from '../ui/formatting.js';
import { apiRequest } from '../core/api.js';
import { showToast } from '../ui/notifications.js';

// Global handler for requesting engineering access/review on candidate products
window.customerRequestAccess = async (productId, productName, btnEl) => {
  if (!productId) return;
  if (btnEl) {
    btnEl.disabled = true;
    btnEl.textContent = 'Submitting Request…';
  }
  try {
    const res = await apiRequest('/customer/access-requests', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        product_id: productId,
        reason: `Customer requested technical review / catalog expansion for ${productName || 'product'}`,
      }),
    });
    showToast(`Access request submitted successfully (Status: ${res.status.toUpperCase()}). Our engineering team will review it.`, 'success');
    if (btnEl) {
      btnEl.textContent = `Review Requested (${res.status.toUpperCase()})`;
      btnEl.classList.remove('btn-secondary');
      btnEl.classList.add('badge-status', 'pending');
    }
  } catch (err) {
    showToast(`Failed to submit access request: ${err.message}`, 'error');
    if (btnEl) {
      btnEl.disabled = false;
      btnEl.textContent = 'Request Engineering Review';
    }
  }
};

export function renderTechnicalDetailsModal(recResult, elements) {
  if (!elements) return;

  const {
    modalExtractedParamsGrid,
    modalSpecGapsSection,
    modalSpecGapsList,
    modalClarificationSection,
    modalClarificationList,
    modalCandidateEvaluationsList,
  } = elements;

  const result = recResult || {};
  const status = (result.overall_outcome || 'insufficient_information').toLowerCase();

  // 1. Process Parameters Grid
  const reqs = result.extracted_requirements || {};
  if (modalExtractedParamsGrid) {
    const params = [
      { label: 'Application Process', val: reqs.application, unit: '' },
      { label: 'Flow Rate', val: reqs.flow_rate_ml_min, unit: 'ml/min' },
      { label: 'Fluid Viscosity', val: reqs.viscosity_cp, unit: 'cP' },
      { label: 'Target Droplet Size', val: reqs.target_droplet_size_um, unit: 'μm' },
      { label: 'Spray Pattern', val: reqs.spray_pattern, unit: '' },
      { label: 'Feed Configuration', val: reqs.feed_configuration, unit: '' },
    ];

    modalExtractedParamsGrid.innerHTML = params
      .map(
        (p) => `
        <div class="tech-spec-item">
          <div class="label">${escapeHtml(p.label)}</div>
          <div class="value">${escapeHtml(formatParamValue(p.val, p.unit))}</div>
        </div>
      `
      )
      .join('');
  }

  // 2. Specification Limitations & Boundary Gaps
  const gaps = result.specification_gaps || [];
  if (modalSpecGapsSection && modalSpecGapsList) {
    if (gaps.length > 0) {
      modalSpecGapsSection.style.display = 'block';
      modalSpecGapsList.innerHTML = gaps
        .map((gap) => `<li>${escapeHtml(gap)}</li>`)
        .join('');
    } else {
      modalSpecGapsSection.style.display = 'none';
      modalSpecGapsList.innerHTML = '';
    }
  }

  // 3. Unresolved Technical Clarifications
  const clarifications = result.clarification_questions || [];
  if (modalClarificationSection && modalClarificationList) {
    if (clarifications.length > 0) {
      modalClarificationSection.style.display = 'block';
      modalClarificationList.innerHTML = clarifications
        .map((q) => `<li>${escapeHtml(q)}</li>`)
        .join('');
    } else {
      modalClarificationSection.style.display = 'none';
      modalClarificationList.innerHTML = '';
    }
  }

  // 4. Evaluated Candidate Nozzles
  const candidates = result.candidate_evaluations || [];
  if (modalCandidateEvaluationsList) {
    if (candidates.length === 0) {
      modalCandidateEvaluationsList.innerHTML = `
        <div class="card-empty-note" style="padding: 14px; background: var(--bg-surface-secondary); border: 1px solid var(--border-color); border-radius: var(--radius-sm); color: var(--text-secondary); font-size: 0.8125rem; line-height: 1.5;">
          <strong>No Authorized Products in Scope:</strong> Your company's currently authorized catalog does not include nozzle configurations for this inquiry. Contact sales administration to request catalog expansion.
        </div>
      `;
    } else {
      modalCandidateEvaluationsList.innerHTML = candidates
        .map((c) => {
          const outcome = (c.status || c.outcome || 'INSUFFICIENT_INFORMATION').toLowerCase();
          const isMatch = outcome === 'match';
          const badgeClass = outcome.includes('match') && !outcome.includes('no')
            ? (isMatch ? 'match' : 'potential')
            : (outcome.includes('insufficient') ? 'insufficient' : 'nomatch');

          const badgeLabel = outcome.replace(/_/g, ' ').toUpperCase();
          const specs = c.specifications || {};
          const gapsList = Array.isArray(c.limitations_and_gaps) ? c.limitations_and_gaps : [];
          const reasonsList = Array.isArray(c.reasons) ? c.reasons : [];
          const pid = c.product_id || c.id || '';

          return `
          <div class="modal-candidate-card ${isMatch ? 'is-match' : ''}">
            <div class="modal-candidate-header">
              <div class="modal-candidate-title">
                <span class="candidate-name">${escapeHtml(c.product_name || c.catalog_key)}</span>
                <span class="candidate-key">${escapeHtml(c.catalog_key || '')}</span>
              </div>
              <span class="status-indicator-badge ${badgeClass}">${escapeHtml(badgeLabel)}</span>
            </div>
            ${c.notes ? `<p class="candidate-notes">${escapeHtml(c.notes)}</p>` : ''}
            ${c.ranking_explanation ? `<p class="candidate-notes" style="color: var(--text-secondary);">${escapeHtml(c.ranking_explanation)}</p>` : ''}
            <div class="candidate-spec-grid">
              ${specs.frequency_khz ? `<div><strong>Freq:</strong> ${specs.frequency_khz} kHz</div>` : ''}
              ${specs.flow_rate_min_ml_min !== undefined ? `<div><strong>Flow:</strong> ${specs.flow_rate_min_ml_min}-${specs.flow_rate_max_ml_min} ml/min</div>` : ''}
              ${specs.viscosity_max_cp !== undefined ? `<div><strong>Max Visc:</strong> ${specs.viscosity_max_cp} cP</div>` : ''}
              ${specs.spray_pattern ? `<div><strong>Pattern:</strong> ${escapeHtml(specs.spray_pattern)}</div>` : ''}
            </div>
            ${
              gapsList.length > 0
                ? `<div style="margin-top: 8px; font-size: 0.75rem; color: var(--color-warning);">
                     <strong>Engineering Scope Limitations:</strong>
                     <ul style="margin: 2px 0 0 16px; padding: 0;">
                       ${gapsList.map((g) => `<li>${escapeHtml(g)}</li>`).join('')}
                     </ul>
                   </div>`
                : ''
            }
            ${
              reasonsList.length > 0 && !isMatch
                ? `<div style="margin-top: 6px; font-size: 0.75rem; color: var(--text-muted);">
                     ${reasonsList.map((r) => `<div>• ${escapeHtml(r)}</div>`).join('')}
                   </div>`
                : ''
            }
            ${
              !isMatch && pid
                ? `<div style="margin-top: 10px; display: flex; justify-content: flex-end;">
                     <button type="button" class="btn-secondary" style="font-size: 0.75rem; padding: 4px 10px;"
                       onclick="window.customerRequestAccess('${escapeHtml(pid)}', '${escapeHtml(c.product_name || c.catalog_key || '')}', this)">
                       Request Engineering Review
                     </button>
                   </div>`
                : ''
            }
          </div>
        `;
        })
        .join('');
    }
  }
}

