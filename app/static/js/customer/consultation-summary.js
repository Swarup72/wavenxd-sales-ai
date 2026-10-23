/**
 * WaveNxD AI Sales Representative - Consultation Summary Panel
 */

import { escapeHtml } from '../ui/formatting.js';

export function renderConsultationSummary(recResult, elements, requirementsOverride) {
  const el = elements || {};

  const matchStatusBadge = el.matchStatusBadge || document.getElementById('matchStatusBadge');
  const matchSummaryText = el.matchSummaryText || document.getElementById('matchSummaryText');
  const reviewWarningPill = el.reviewWarningPill || document.getElementById('reviewWarningPill');
  const knownReqsContainer = el.knownReqsContainer || document.getElementById('knownReqsContainer');
  const missingInfoAccordion = el.missingInfoAccordion || document.getElementById('missingInfoAccordion');
  const missingInfoCount = el.missingInfoCount || document.getElementById('missingInfoCount');
  const missingInfoList = el.missingInfoList || document.getElementById('missingInfoList');
  const compactProductEmpty = el.compactProductEmpty || document.getElementById('compactProductEmpty');
  const compactProductContent = el.compactProductContent || document.getElementById('compactProductContent');
  const compactProdName = el.compactProdName || document.getElementById('compactProdName');
  const compactProdKey = el.compactProdKey || document.getElementById('compactProdKey');
  const compactProdMatchBadge = el.compactProdMatchBadge || document.getElementById('compactProdMatchBadge');
  const compactProdExplanation = el.compactProdExplanation || document.getElementById('compactProdExplanation');

  const result = recResult || {};

  // 1. Active Requirements (structured data from backend)
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

  // 2. Determine Outcome & Candidate Product
  const rawOutcome = (
    result.overall_outcome ||
    result.status ||
    result.match_status ||
    (Array.isArray(result.candidate_evaluations) && result.candidate_evaluations.length > 0 && result.candidate_evaluations.every(c => c.status === 'no_match') ? 'no_match' : '') ||
    'INSUFFICIENT_INFORMATION'
  ).toLowerCase();

  const isConfirmed = rawOutcome === 'match' || rawOutcome === 'confirmed_match';
  const isPotential = rawOutcome.includes('potential') || rawOutcome.includes('partial');

  // Candidate product evaluation
  const prod =
    result.recommended_product ||
    (Array.isArray(result.confirmed_recommendations) && result.confirmed_recommendations[0]) ||
    (Array.isArray(result.potential_matches) && result.potential_matches[0]) ||
    (Array.isArray(result.candidate_evaluations) &&
      result.candidate_evaluations.find(
        (c) => (c.status || '').toLowerCase() === 'match' || (c.status || '').toLowerCase().includes('potential')
      )) ||
    null;

  const isNoMatch =
    rawOutcome.includes('no_match') ||
    rawOutcome.includes('nomatch') ||
    rawOutcome.includes('no-match') ||
    rawOutcome === 'no_compatible_nozzle' ||
    (!prod &&
      Array.isArray(result.unmatched_candidates) &&
      result.unmatched_candidates.length > 0 &&
      (!result.confirmed_recommendations || result.confirmed_recommendations.length === 0) &&
      (!result.potential_matches || result.potential_matches.length === 0) &&
      activeParams.length >= 2 &&
      !rawOutcome.includes('insufficient'));

  // 3. Status Badge & Summary Text
  if (matchStatusBadge) {
    matchStatusBadge.className = 'status-indicator-badge';
    let badgeClass = 'insufficient';
    let label = 'INSUFFICIENT INFORMATION';

    if (isNoMatch) {
      badgeClass = 'nomatch';
      label = 'NO COMPATIBLE NOZZLE';
    } else if (isConfirmed && prod) {
      badgeClass = 'match';
      label = 'CONFIRMED MATCH';
    } else if (isPotential && prod) {
      badgeClass = 'potential';
      label = 'POTENTIAL MATCH';
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

  // 4. Collapsible Missing Information
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

  // 5. Compact Recommended Product Card (Handles insufficient, match, and no_match deterministically)
  if (compactProductEmpty && compactProductContent) {
    if (isNoMatch) {
      // Completed evaluation concluded no compatible nozzle
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
            : "None of your company's authorized catalog products meet the specified application and operational requirements.";
      }
    } else if (prod && (isConfirmed || isPotential)) {
      // Completed evaluation found confirmed or potential match
      compactProductEmpty.style.display = 'none';
      compactProductContent.style.display = 'block';

      if (compactProdName) compactProdName.textContent = prod.product_name;
      if (compactProdKey) compactProdKey.textContent = prod.catalog_key || prod.product_id || 'WaveNxD Series';
      if (compactProdMatchBadge) {
        compactProdMatchBadge.textContent = isConfirmed ? 'CONFIRMED MATCH' : 'POTENTIAL MATCH';
        compactProdMatchBadge.className = `badge-status ${isConfirmed ? 'match' : 'potential'}`;
      }
      if (compactProdExplanation) {
        compactProdExplanation.textContent =
          (prod.reasons && prod.reasons.length > 0)
            ? prod.reasons.join('; ')
            : (result.summary_reasons && result.summary_reasons[0]) || 'Verified against company catalog specifications.';
      }
    } else {
      // Awaiting sufficient technical parameters
      compactProductEmpty.style.display = 'block';
      compactProductEmpty.textContent = 'Awaiting sufficient technical parameters...';
      compactProductContent.style.display = 'none';
    }
  }
}
