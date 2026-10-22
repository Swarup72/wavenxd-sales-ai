/**
 * WaveNxD Admin - Product Catalog Governance Module
 * Backend: GET/POST /admin/products, PATCH /admin/products/{id}, POST /admin/products/{id}/clear-review
 * ProductAdminResponse: { id, name, catalog_key, category, spray_pattern, feed_configuration,
 *   frequency_khz, droplet_size_um, flow_rate_max_ml_min, viscosity_max_cp, applications,
 *   status, technical_review_required, catalog_notes }
 * Table columns (#productsTable): Product Model | Catalog Identifier | Frequency | Max Flow | Max Viscosity | Status | Tech Review | Actions (8 cols)
 */

import { apiRequest } from '../core/api.js';
import { showToast } from '../ui/notifications.js';
import { escapeHtml } from '../ui/formatting.js';
import { setTableLoading, setTableEmpty, setTableError, errorMessage } from './table-states.js';

const COLS = 8;

export async function loadProducts(tableBodyEl, query = '') {
  setTableLoading(tableBodyEl, COLS, 'Loading products…');
  try {
    const list = await apiRequest('/admin/products');
    renderProducts(list, tableBodyEl, query);
    return list;
  } catch (err) {
    setTableError(tableBodyEl, COLS, errorMessage(err, 'products'), () => loadProducts(tableBodyEl, query));
    return [];
  }
}

export function renderProducts(products, tableBodyEl, query = '') {
  if (!tableBodyEl) return;
  const all = Array.isArray(products) ? products : [];
  const q = query.trim().toLowerCase();
  const filtered = q
    ? all.filter(
        (p) =>
          (p.name || '').toLowerCase().includes(q) ||
          (p.catalog_key || '').toLowerCase().includes(q) ||
          (p.category || '').toLowerCase().includes(q)
      )
    : all;

  if (filtered.length === 0) {
    setTableEmpty(tableBodyEl, COLS, all.length === 0 ? 'No products registered in catalog.' : 'No products match filter.');
    return;
  }

  tableBodyEl.innerHTML = filtered
    .map(
      (p) => `
      <tr>
        <td><strong>${escapeHtml(p.name)}</strong></td>
        <td><code>${escapeHtml(p.catalog_key || '—')}</code></td>
        <td>${p.frequency_khz ? `${p.frequency_khz} kHz` : '—'}</td>
        <td>${p.flow_rate_max_ml_min ? `${p.flow_rate_max_ml_min} ml/min` : '—'}</td>
        <td>${p.viscosity_max_cp ? `${p.viscosity_max_cp} cP` : '—'}</td>
        <td>
          <span class="badge-status ${p.status === 'published' ? 'active' : (p.status === 'draft' ? 'potential' : 'inactive')}">
            ${escapeHtml((p.status || 'draft').toUpperCase())}
          </span>
        </td>
        <td>
          ${
            p.technical_review_required
              ? '<span class="badge-status potential" title="Flagged for engineering review">REVIEW REQ</span>'
              : '<span class="badge-status active">VERIFIED</span>'
          }
        </td>
        <td>
          <div class="table-actions">
            <button type="button" class="btn-table-action" data-action="edit-product" data-id="${escapeHtml(p.id)}">Edit</button>
            ${
              p.technical_review_required
                ? `<button type="button" class="btn-table-action" data-action="clear-review" data-id="${escapeHtml(p.id)}">Clear Review</button>`
                : ''
            }
          </div>
        </td>
      </tr>`
    )
    .join('');
}

export async function clearProductReview(productId, onSuccess) {
  try {
    await apiRequest(`/admin/products/${encodeURIComponent(productId)}/clear-review`, { method: 'POST' });
    showToast('Product review flag cleared and marked published.', 'success');
    if (onSuccess) onSuccess();
  } catch (err) {
    showToast(`Failed to clear review flag: ${err.message}`, 'error');
  }
}

export async function saveProduct(productData, productId, onSuccess) {
  try {
    if (productId) {
      await apiRequest(`/admin/products/${encodeURIComponent(productId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(productData),
      });
      showToast('Product updated successfully.', 'success');
    } else {
      await apiRequest('/admin/products', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(productData),
      });
      showToast('Product created successfully.', 'success');
    }
    if (onSuccess) onSuccess();
  } catch (err) {
    showToast(`Failed to save product: ${err.message}`, 'error');
  }
}
