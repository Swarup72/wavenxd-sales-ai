/**
 * WaveNxD AI Sales Representative - Safe Markdown Message Renderer
 */

import { escapeHtml } from '../ui/formatting.js';

export function renderMarkdown(text) {
  if (!text) return '';

  // 1. First escape all raw HTML to prevent XSS injection
  let safe = escapeHtml(text);

  // 2. Remove JSON requirement code blocks from customer-facing text if present
  safe = safe.replace(/```json[\s\S]*?```/gi, '');
  safe = safe.replace(/```[\s\S]*?```/g, '');

  // 3. Process headings
  safe = safe.replace(/^#### (.*?)$/gm, '<h4>$1</h4>');
  safe = safe.replace(/^### (.*?)$/gm, '<h3>$1</h3>');
  safe = safe.replace(/^## (.*?)$/gm, '<h3>$1</h3>');

  // 4. Bold and Italic
  safe = safe.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  safe = safe.replace(/\*(.*?)\*/g, '<em>$1</em>');

  // 5. Inline Code
  safe = safe.replace(/`([^`]+)`/g, '<code>$1</code>');

  // 6. Split into blocks to process lists vs paragraphs
  const rawBlocks = safe.split(/\n\n+/);
  const formattedBlocks = rawBlocks.map((block) => {
    const trimmed = block.trim();
    if (!trimmed) return '';

    const lines = trimmed.split('\n');

    // Check if block is an unordered list
    if (lines.every((l) => l.trim().startsWith('- ') || l.trim().startsWith('* '))) {
      const items = lines.map((l) => {
        const itemText = l.trim().replace(/^[-*]\s+/, '');
        return `<li>${itemText}</li>`;
      });
      return `<ul>${items.join('')}</ul>`;
    }

    // Check if block is an ordered list
    if (lines.every((l) => /^\d+\.\s+/.test(l.trim()))) {
      const items = lines.map((l) => {
        const itemText = l.trim().replace(/^\d+\.\s+/, '');
        return `<li>${itemText}</li>`;
      });
      return `<ol>${items.join('')}</ol>`;
    }

    // Normal paragraph (convert single newlines to <br>)
    if (trimmed.startsWith('<h3>') || trimmed.startsWith('<h4>')) {
      return trimmed;
    }
    const withBreaks = lines.join('<br>');
    return `<p>${withBreaks}</p>`;
  });

  return formattedBlocks.filter(Boolean).join('');
}
