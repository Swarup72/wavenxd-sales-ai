/**
 * WaveNxD AI Sales Representative - Safe Markdown Message Renderer
 */

import { escapeHtml } from '../ui/formatting.js';

function parseTableRow(line) {
  let cleaned = line.trim();
  if (cleaned.startsWith('|')) cleaned = cleaned.slice(1);
  if (cleaned.endsWith('|')) cleaned = cleaned.slice(0, -1);
  return cleaned.split('|').map((c) => c.trim());
}

function isTableBlock(lines) {
  if (lines.length < 2) return false;
  const headerLine = lines[0].trim();
  const delimLine = lines[1].trim();
  if (!headerLine.includes('|') || !delimLine.includes('|')) return false;
  return /^\|?(\s*:?-+:?\s*\|?)+$/.test(delimLine);
}

function renderTable(lines) {
  if (lines.length < 2) return '';
  const headers = parseTableRow(lines[0]);
  const rows = lines.slice(2).filter((l) => l.trim().length > 0 && l.includes('|'));

  const headerHtml = `<thead><tr>${headers
    .map((h) => `<th>${h}</th>`)
    .join('')}</tr></thead>`;

  const bodyHtml = `<tbody>${rows
    .map((r) => {
      const cells = parseTableRow(r);
      return `<tr>${cells.map((c) => `<td>${c}</td>`).join('')}</tr>`;
    })
    .join('')}</tbody>`;

  return `<div class="table-container"><table class="markdown-table">${headerHtml}${bodyHtml}</table></div>`;
}

function renderLines(lines) {
  const parts = [];
  let currentUl = [];
  let currentOl = [];
  let currentP = [];

  function flushP() {
    if (currentP.length > 0) {
      parts.push(`<p>${currentP.join('<br>')}</p>`);
      currentP = [];
    }
  }

  function flushUl() {
    if (currentUl.length > 0) {
      parts.push(`<ul>${currentUl.map((li) => `<li>${li}</li>`).join('')}</ul>`);
      currentUl = [];
    }
  }

  function flushOl() {
    if (currentOl.length > 0) {
      parts.push(`<ol>${currentOl.map((li) => `<li>${li}</li>`).join('')}</ol>`);
      currentOl = [];
    }
  }

  for (const rawLine of lines) {
    const trimmed = rawLine.trim();
    if (!trimmed) {
      flushP();
      flushUl();
      flushOl();
      continue;
    }

    if (trimmed.startsWith('<h3>') || trimmed.startsWith('<h4>')) {
      flushP();
      flushUl();
      flushOl();
      parts.push(trimmed);
      continue;
    }

    if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
      flushP();
      flushOl();
      currentUl.push(trimmed.replace(/^[-*]\s+/, ''));
      continue;
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      flushP();
      flushUl();
      currentOl.push(trimmed.replace(/^\d+\.\s+/, ''));
      continue;
    }

    flushUl();
    flushOl();
    currentP.push(trimmed);
  }

  flushP();
  flushUl();
  flushOl();

  return parts.join('');
}

export function renderMarkdown(text) {
  if (!text) return '';

  // 1. Normalize linebreaks and raw <br> tags before HTML escaping to avoid literal &lt;br&gt;
  const normalized = String(text).replace(/<br\s*\/?>/gi, '\n');

  // 2. Escape all HTML to prevent XSS injection
  let safe = escapeHtml(normalized);

  // 3. Remove JSON requirement code blocks from customer-facing text if present
  safe = safe.replace(/```json[\s\S]*?```/gi, '');
  safe = safe.replace(/```[\s\S]*?```/g, '');

  // 4. Process headings
  safe = safe.replace(/^#### (.*?)$/gm, '<h4>$1</h4>');
  safe = safe.replace(/^### (.*?)$/gm, '<h3>$1</h3>');
  safe = safe.replace(/^## (.*?)$/gm, '<h3>$1</h3>');

  // 5. Bold and Italic
  safe = safe.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  safe = safe.replace(/\*(.*?)\*/g, '<em>$1</em>');

  // 6. Inline Code
  safe = safe.replace(/`([^`]+)`/g, '<code>$1</code>');

  // 7. Split into blocks separated by two or more newlines
  const rawBlocks = safe.split(/\n\n+/);
  const formattedBlocks = rawBlocks.map((block) => {
    const trimmed = block.trim();
    if (!trimmed) return '';

    const lines = trimmed.split('\n');

    // Check if entire block is a markdown table
    if (isTableBlock(lines)) {
      return renderTable(lines);
    }

    return renderLines(lines);
  });

  return formattedBlocks.filter(Boolean).join('');
}
