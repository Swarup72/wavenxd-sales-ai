/**
 * WaveNxD AI Sales Representative - Consultation Summary Panel
 */

import { escapeHtml } from '../ui/formatting.js';

export function renderConsultationSummary(recResult, elements) {
  if (!elements) return;

  const {
    matchStatusBadge,
    matchSummaryText,
    reviewWarningPill,
    knownReqsContainer,
    missingInfoAccordion,
    missingInfoCount,
    missingInfoList,
    compactProductCard,
    compactProductEmpty,
    compactProductContent,
    compactProdName,
    compactProdKey,
    compactProdMatchBadge,
    compactProdExplanation,
  } = elements;

  const result = recResult || {};
  const status = (result.overall_outcome || 'INSUFFICIENT_INFORMATION').toLowerCase();

  // 1. Status Badge & Summary
  if (matchStatusBadge) {
    matchStatusBadge.className = 'status-indicator-badge';
    let badgeClass = 'insufficient';
    let label = 'INSUFFICIENT INFORMATION';

    if (status.includes('match') && !status.includes('no')) {
      if (status === 'match') {
        badgeClass = 'match';
        label = 'CONFIRMED MATCH';
      } else {
        badgeClass = 'potential';
        label = 'POTENTIAL MATCH';
      }
    } else if (status.includes('no_match') || status.includes('nomatch')) {
      badgeClass = 'nomatch';
      label = 'NO COMPATIBLE NOZZLE';
    }

    matchStatusBadge.classList.add(badgeClass);
    matchStatusBadge.textContent = label;
  }

  if (matchSummaryText) {
    if (result.recommended_product) {
      matchSummaryText.textContent = `Recommended: ${result.recommended_product.product_name}. Verified against company catalog.`;
    } else if (result.clarification_questions && result.clarification_questions.length > 0) {
      matchSummaryText.textContent = 'Clarifications needed to confirm process compatibility.';
    } else if (result.specification_gaps && result.specification_gaps.length > 0) {
      matchSummaryText.textContent = result.specification_gaps[0];
    } else {
      matchSummaryText.textContent = 'Provide flow rate, viscosity, or application for engineering compatibility evaluation.';
    }
  }

  if (reviewWarningPill) {
    reviewWarningPill.style.display = result.requires_technical_review ? 'flex' : 'none';
  }

  // 2. Active Requirements (omit "Not specified" to prevent clutter)
  const reqs = result.extracted_requirements || {};
  const activeParams = [];
  if (reqs.flow_rate_ml_min) activeParams.push({ name: 'Flow', val: `${reqs.flow_rate_ml_min} ml/min` });
  if (reqs.viscosity_cp) activeParams.push({ name: 'Viscosity', val: `${reqs.viscosity_cp} cP` });
  if (reqs.target_droplet_size_um) activeParams.push({ name: 'Droplet', val: `${reqs.target_droplet_size_um} μm` });
  if (reqs.application) activeParams.push({ name: 'App', val: reqs.application });
  if (reqs.spray_pattern) activeParams.push({ name: 'Pattern', val: reqs.spray_pattern });
  if (reqs.feed_configuration) activeParams.push({ name: 'Feed', val: reqs.feed_configuration });

  if (knownReqsContainer) {
    if (activeParams.length === 0) {
      knownReqsContainer.innerHTML = '<span class="empty-param-note">No parameters specified yet</span>';
    } else {
      knownReqsContainer.innerHTML = activeParams
        .map(
          (p) => `<span class="req-pill"><strong>${escapeHtml(p.name)}:</strong> ${escapeHtml(p.val)}</span>`
        )
        .join('');
    }
  }

  // 3. Collapsible Missing Information
  const gaps = result.specification_gaps || [];
  if (missingInfoAccordion && missingInfoCount && missingInfoList) {
    if (gaps.length > 0) {
      missingInfoAccordion.style.display = 'block';
      missingInfoCount.textContent = gaps.length;
      missingInfoList.innerHTML = gaps
        .map((g) => `<li>${escapeHtml(g)}</li>`)
        .join('');
    } else {
      missingInfoAccordion.style.display = 'none';
      missingInfoList.innerHTML = '';
    }
  }

  // 4. Compact Recommended Product
  const prod = result.recommended_product;
  if (compactProductEmpty && compactProductContent) {
    if (prod) {
      compactProductEmpty.style.display = 'none';
      compactProductContent.style.display = 'block';

      if (compactProdName) compactProdName.textContent = prod.product_name;
      if (compactProdKey) compactProdKey.textContent = prod.catalog_key;
      if (compactProdMatchBadge) {
        compactProdMatchBadge.textContent = 'MATCH';
        compactProdMatchBadge.className = 'badge-status match';
      }
      if (compactProdExplanation) {
        compactProdExplanation.textContent = prod.explanation || 'Verified for company requirements.';
      }
    } else {
      compactProductEmpty.style.display = 'block';
      compactProductContent.style.display = 'none';
    }
  }
}
