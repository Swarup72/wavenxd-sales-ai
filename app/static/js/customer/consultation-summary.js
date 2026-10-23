/**
 * WaveNxD AI Sales Representative - Consultation Summary Panel
 */

import { escapeHtml } from '../ui/formatting.js';

export function renderConsultationSummary(recResult, elements, requirementsOverride) {
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
  const isNoMatch = status.includes('no_match') || status.includes('nomatch');
  const isConfirmed = status === 'match' || status === 'confirmed_match';
  const isPotential = status.includes('potential');

  // Candidate product evaluation
  const prod =
    result.recommended_product ||
    (Array.isArray(result.confirmed_recommendations) && result.confirmed_recommendations[0]) ||
    (Array.isArray(result.potential_matches) && result.potential_matches[0]) ||
    null;

  // 1. Status Badge & Summary
  if (matchStatusBadge) {
    matchStatusBadge.className = 'status-indicator-badge';
    let badgeClass = 'insufficient';
    let label = 'INSUFFICIENT INFORMATION';

    if (isConfirmed) {
      badgeClass = 'match';
      label = 'CONFIRMED MATCH';
    } else if (isPotential) {
      badgeClass = 'potential';
      label = 'POTENTIAL MATCH';
    } else if (isNoMatch) {
      badgeClass = 'nomatch';
      label = 'NO COMPATIBLE NOZZLE';
    }

    matchStatusBadge.classList.add(badgeClass);
    matchStatusBadge.textContent = label;
  }

  if (matchSummaryText) {
    if (isNoMatch) {
      matchSummaryText.textContent =
        (result.summary_reasons && result.summary_reasons[0]) ||
        'Catalog products do not establish verified compatibility with specified process application.';
    } else if (isConfirmed && prod) {
      matchSummaryText.textContent = `Recommended: ${prod.product_name}. Verified against company catalog.`;
    } else if (isPotential && prod) {
      matchSummaryText.textContent = `Potential candidate: ${prod.product_name}. Technical clarification required.`;
    } else if (result.clarification_questions && result.clarification_questions.length > 0) {
      matchSummaryText.textContent = 'Clarifications needed to confirm process compatibility.';
    } else if (result.specification_gaps && result.specification_gaps.length > 0) {
      matchSummaryText.textContent = result.specification_gaps[0];
    } else {
      matchSummaryText.textContent = 'Provide flow rate, viscosity, or application for engineering compatibility evaluation.';
    }
  }

  if (reviewWarningPill) {
    const needsReview = Boolean(result.technical_review_required || result.requires_technical_review);
    reviewWarningPill.style.display = needsReview ? 'flex' : 'none';
  }

  // 2. Active Requirements (structured data from backend)
  const reqs = requirementsOverride || result.requirements || result.extracted_requirements || {};
  const activeParams = [];
  if (reqs.flow_rate_ml_min !== undefined && reqs.flow_rate_ml_min !== null) {
    activeParams.push({ name: 'Flow', val: `${reqs.flow_rate_ml_min} ml/min` });
  }
  if (reqs.viscosity_cp !== undefined && reqs.viscosity_cp !== null) {
    activeParams.push({ name: 'Viscosity', val: `${reqs.viscosity_cp} cP` });
  }
  const dropletVal =
    reqs.droplet_size_um !== undefined && reqs.droplet_size_um !== null
      ? reqs.droplet_size_um
      : reqs.target_droplet_size_um;
  if (dropletVal !== undefined && dropletVal !== null) {
    activeParams.push({ name: 'Droplet', val: `${dropletVal} μm` });
  }
  if (reqs.application) activeParams.push({ name: 'App', val: reqs.application });
  if (reqs.fluid_description) activeParams.push({ name: 'Liquid', val: reqs.fluid_description });
  if (reqs.spray_pattern) activeParams.push({ name: 'Pattern', val: reqs.spray_pattern });
  if (reqs.feed_configuration) activeParams.push({ name: 'Feed', val: reqs.feed_configuration });
  if (reqs.industry) activeParams.push({ name: 'Industry', val: reqs.industry });

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
  const gaps = [];
  if (Array.isArray(result.specification_gaps)) {
    gaps.push(...result.specification_gaps);
  }
  if (Array.isArray(result.clarification_questions)) {
    for (const q of result.clarification_questions) {
      if (!gaps.includes(q)) gaps.push(q);
    }
  }

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
  if (compactProductEmpty && compactProductContent) {
    if (isNoMatch) {
      compactProductEmpty.style.display = 'none';
      compactProductContent.style.display = 'block';

      if (compactProdName) compactProdName.textContent = 'No Compatible Nozzle';
      if (compactProdKey) compactProdKey.textContent = 'Catalog Compatibility Evaluation';
      if (compactProdMatchBadge) {
        compactProdMatchBadge.textContent = 'NO MATCH';
        compactProdMatchBadge.className = 'badge-status nomatch';
      }
      if (compactProdExplanation) {
        compactProdExplanation.textContent =
          (result.summary_reasons && result.summary_reasons.length > 0)
            ? result.summary_reasons.join('; ')
            : 'None of your company\'s authorized catalog products meet the documented application requirements.';
      }
    } else if (prod && (isConfirmed || isPotential)) {
      compactProductEmpty.style.display = 'none';
      compactProductContent.style.display = 'block';

      if (compactProdName) compactProdName.textContent = prod.product_name;
      if (compactProdKey) compactProdKey.textContent = prod.catalog_key || prod.product_id;
      if (compactProdMatchBadge) {
        compactProdMatchBadge.textContent = isConfirmed ? 'CONFIRMED MATCH' : 'POTENTIAL MATCH';
        compactProdMatchBadge.className = `badge-status ${isConfirmed ? 'match' : 'potential'}`;
      }
      if (compactProdExplanation) {
        compactProdExplanation.textContent =
          (prod.reasons && prod.reasons.length > 0)
            ? prod.reasons.join('; ')
            : (result.summary_reasons && result.summary_reasons[0]) || 'Verified against company catalog.';
      }
    } else {
      compactProductEmpty.style.display = 'block';
      compactProductEmpty.textContent = 'Awaiting sufficient technical parameters...';
      compactProductContent.style.display = 'none';
    }
  }
}
