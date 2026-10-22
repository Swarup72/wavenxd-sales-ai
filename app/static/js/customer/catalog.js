/**
 * WaveNxD AI Sales Representative - Company Authorized Product Catalog
 */

import { CONFIG } from '../core/config.js';
import { apiRequest } from '../core/api.js';
import { state } from '../core/state.js';
import { escapeHtml } from '../ui/formatting.js';

export async function fetchAssignedProducts() {
  try {
    const products = await apiRequest(CONFIG.ENDPOINTS.PRODUCTS);
    state.assignedProducts = Array.isArray(products) ? products : [];
    return state.assignedProducts;
  } catch (err) {
    console.warn('Failed to load authorized products:', err);
    state.assignedProducts = [];
    return [];
  }
}

export function renderCatalogDrawer(products, containerEl) {
  if (!containerEl) return;

  if (!products || products.length === 0) {
    containerEl.innerHTML = `
      <div style="padding: 24px; text-align: center; color: var(--text-muted);">
        No authorized products are currently assigned to your company entitlement. Please contact WaveNxD sales administration.
      </div>
    `;
    return;
  }

  containerEl.innerHTML = products
    .map((p) => {
      const specs = p.specifications || {};
      return `
      <div class="drawer-prod-card">
        <div class="drawer-prod-header">
          <div>
            <div class="drawer-prod-name">${escapeHtml(p.name)}</div>
            <span class="drawer-prod-key">${escapeHtml(p.catalog_key)}</span>
          </div>
          <span class="badge-status active">Authorized</span>
        </div>
        ${p.description ? `<p class="drawer-prod-desc">${escapeHtml(p.description)}</p>` : ''}
        <div class="drawer-prod-specs">
          ${specs.frequency_khz ? `<div class="prod-spec-row"><span class="prod-spec-label">Frequency:</span><span class="prod-spec-val">${specs.frequency_khz} kHz</span></div>` : ''}
          ${specs.flow_rate_min_ml_min !== undefined ? `<div class="prod-spec-row"><span class="prod-spec-label">Flow Range:</span><span class="prod-spec-val">${specs.flow_rate_min_ml_min} - ${specs.flow_rate_max_ml_min} ml/min</span></div>` : ''}
          ${specs.viscosity_max_cp !== undefined ? `<div class="prod-spec-row"><span class="prod-spec-label">Max Viscosity:</span><span class="prod-spec-val">${specs.viscosity_max_cp} cP</span></div>` : ''}
          ${specs.spray_pattern ? `<div class="prod-spec-row"><span class="prod-spec-label">Spray Pattern:</span><span class="prod-spec-val">${escapeHtml(specs.spray_pattern)}</span></div>` : ''}
        </div>
      </div>
    `;
    })
    .join('');
}
