#!/usr/bin/env node
/**
 * WaveNxD Admin Portal — real-browser smoke/regression test.
 *
 * Drives a locally installed Google Chrome (headless) through the Chrome
 * DevTools Protocol using only Node built-ins (fetch + WebSocket, Node >= 22).
 * No npm packages, no Playwright download, no bundler.
 *
 * What it verifies against a RUNNING server:
 *   1. Admin can sign in through the real login form (CSRF + cookies).
 *   2. /admin renders the admin shell.
 *   3. Every sidebar tab shows exactly one visible pane, the correct one,
 *      with a heading, and every table body ends in a non-loading state
 *      (data rows, an empty-state row, or an error-state row).
 *   4. Switching tabs repeatedly and reloading keeps working.
 *   5. One click on a tab issues each data request exactly once
 *      (guards against duplicated event listeners).
 *   6. A modal opens and closes with Escape.
 *   7. No uncaught JS exceptions / console errors / failed requests.
 *
 * Usage:
 *   WAVENXD_ADMIN_PASSWORD='<dev admin password>' node tests/browser/admin_portal_smoke.mjs
 * Optional env:
 *   WAVENXD_BASE_URL (default http://127.0.0.1:8000)
 *   WAVENXD_ADMIN_EMAIL (default admin@wavenxd.com)
 *   CHROME_PATH (default macOS Google Chrome location)
 *   WAVENXD_SCREENSHOT_DIR (if set, a PNG is saved per tab)
 *   WAVENXD_VIEWPORTS (default "1440x900,1024x768,390x844")
 */

import { spawn } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

const BASE = process.env.WAVENXD_BASE_URL || 'http://127.0.0.1:8000';
const EMAIL = process.env.WAVENXD_ADMIN_EMAIL || 'admin@wavenxd.com';
const PASSWORD = process.env.WAVENXD_ADMIN_PASSWORD;
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const SHOT_DIR = process.env.WAVENXD_SCREENSHOT_DIR || '';
const VIEWPORTS = (process.env.WAVENXD_VIEWPORTS || '1440x900,1024x768,390x844')
  .split(',')
  .map((v) => v.trim().split('x').map(Number));

const TABS = [
  'overview', 'companies', 'users', 'products', 'assignments',
  'reviews', 'support', 'leads', 'providers', 'audit', 'settings',
];
// Data endpoints each tab is expected to call exactly once per click.
const TAB_REQUESTS = {
  overview: ['/admin/overview'],
  companies: ['/admin/companies'],
  users: ['/admin/users', '/admin/invitations'],
  products: ['/admin/products'],
  assignments: ['/admin/assignments'],
  reviews: ['/admin/technical-review-queue', '/admin/access-requests'],
  support: ['/admin/support/conversations'],
  leads: ['/admin/leads'],
  providers: ['/admin/provider-status'],
  audit: ['/admin/audit-logs'],
  settings: [],
};

if (!PASSWORD) {
  console.error('Set WAVENXD_ADMIN_PASSWORD to the development admin password.');
  process.exit(2);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class CDP {
  constructor(ws) {
    this.ws = ws;
    this.seq = 0;
    this.pending = new Map();
    this.listeners = [];
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(typeof ev.data === 'string' ? ev.data : ev.data.toString());
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(`${msg.error.message}`));
        else resolve(msg.result);
      } else if (msg.method) {
        for (const fn of this.listeners) fn(msg);
      }
    });
  }
  send(method, params = {}) {
    const id = ++this.seq;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }
  on(fn) { this.listeners.push(fn); }
}

async function evaluate(cdp, expression) {
  const res = await cdp.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (res.exceptionDetails) {
    throw new Error(`Evaluation failed: ${res.exceptionDetails.text} ${res.exceptionDetails.exception?.description || ''}`);
  }
  return res.result.value;
}

async function waitFor(cdp, expression, timeoutMs = 8000, label = expression) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      if (await evaluate(cdp, expression)) return true;
    } catch (_) { /* page may be navigating */ }
    await sleep(100);
  }
  throw new Error(`Timed out waiting for: ${label}`);
}

async function navigate(cdp, url) {
  await cdp.send('Page.navigate', { url });
  await waitFor(cdp, 'document.readyState === "complete"', 10000, `load ${url}`);
}

// Inspect the currently visible admin pane and return a structured snapshot.
const SNAPSHOT_JS = `(() => {
  const visible = (el) => !!el && el.offsetParent !== null && el.getBoundingClientRect().height > 0;
  const panes = [...document.querySelectorAll('.admin-main .tab-pane')];
  const shown = panes.filter(visible);
  const pane = shown[0] || null;
  const activeNav = [...document.querySelectorAll('.nav-item.active')].map((b) => b.dataset.tab);
  const tbodies = pane ? [...pane.querySelectorAll('tbody')].filter((tb) => visible(tb.closest('table'))) : [];
  return {
    visiblePaneIds: shown.map((p) => p.id),
    activeNav,
    heading: pane ? (pane.querySelector('h1')?.textContent || '').trim() : '',
    textLength: pane ? pane.innerText.trim().length : 0,
    paneHeight: pane ? Math.round(pane.getBoundingClientRect().height) : 0,
    tbodies: tbodies.map((tb) => ({
      id: tb.id,
      rows: tb.rows.length,
      loading: !!tb.querySelector('[data-state="loading"]'),
      empty: !!tb.querySelector('[data-state="empty"]'),
      error: !!tb.querySelector('[data-state="error"]'),
      firstRow: (tb.rows[0]?.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 90),
    })),
    paneError: pane ? !!pane.querySelector('[data-state="error"]') : false,
    horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
})()`;

async function main() {
  const failures = [];
  const fail = (msg) => { failures.push(msg); console.log(`  FAIL ${msg}`); };
  const pass = (msg) => console.log(`  ok   ${msg}`);

  const port = 9300 + Math.floor(Math.random() * 500);
  const profile = mkdtempSync(path.join(tmpdir(), 'wavenxd-chrome-'));
  if (SHOT_DIR) mkdirSync(SHOT_DIR, { recursive: true });

  const chrome = spawn(CHROME, [
    '--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
    '--no-first-run', '--no-default-browser-check', '--disable-gpu', '--window-size=1440,900',
    'about:blank',
  ], { stdio: 'ignore' });

  let cdp;
  try {
    let targets = null;
    for (let i = 0; i < 50 && !targets; i++) {
      try { targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); } catch (_) { await sleep(200); }
    }
    const page = targets.find((t) => t.type === 'page');
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((r, j) => { ws.addEventListener('open', r); ws.addEventListener('error', j); });
    cdp = new CDP(ws);

    const consoleErrors = [];
    const httpErrors = [];
    const requests = [];
    cdp.on((m) => {
      if (m.method === 'Runtime.exceptionThrown') {
        consoleErrors.push(`exception: ${m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text}`);
      } else if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
        consoleErrors.push(`console.error: ${m.params.args.map((a) => a.value ?? a.description).join(' ')}`);
      } else if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') {
        const full = `${m.params.entry.text} ${m.params.entry.url || ''}`;
        if (!full.includes('/auth/me')) {
          consoleErrors.push(`log: ${full}`);
        }
      } else if (m.method === 'Network.requestWillBeSent') {
        requests.push(new URL(m.params.request.url).pathname);
      } else if (m.method === 'Network.responseReceived') {
        const { status, url, mimeType } = m.params.response;
        const p = new URL(url).pathname;
        if (status >= 400 && p !== '/auth/me') httpErrors.push(`${status} ${p}`);
        if (p.startsWith('/static/js/') && !mimeType.includes('javascript')) httpErrors.push(`bad MIME ${mimeType} for ${p}`);
      } else if (m.method === 'Network.loadingFailed' && !m.params.canceled) {
        httpErrors.push(`loadingFailed ${m.params.errorText}`);
      }
    });
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Log.enable');
    await cdp.send('Network.enable');

    // ---- Sign in through the real login form ----
    console.log('Sign-in');
    await navigate(cdp, `${BASE}/login`);
    await waitFor(cdp, '!!document.getElementById("loginForm")');
    await evaluate(cdp, `(() => {
      document.getElementById('emailInput').value = ${JSON.stringify(EMAIL)};
      document.getElementById('passwordInput').value = ${JSON.stringify(PASSWORD)};
      document.getElementById('loginForm').requestSubmit();
    })()`);
    await waitFor(cdp, `fetch('/auth/me', {credentials: 'same-origin'}).then(r => r.ok ? r.json() : null).then(u => !!u && u.role === 'admin')`, 10000, 'admin session');
    pass('admin signed in via login form');

    for (const [w, h] of VIEWPORTS) {
      console.log(`\nViewport ${w}x${h}`);
      await cdp.send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: w < 768 });

      for (const round of ['initial', 'repeat', 'after-reload']) {
        if (round === 'initial' || round === 'after-reload') {
          await navigate(cdp, `${BASE}/admin`);
          await waitFor(cdp, `getComputedStyle(document.getElementById('adminShell')).display !== 'none'`, 10000, 'admin shell visible');
        }
        console.log(` round: ${round}`);
        for (const tab of TABS) {
          const before = requests.length;
          await evaluate(cdp, `document.querySelector('.nav-item[data-tab="${tab}"]').click()`);
          // Wait until the target pane is the only visible one and no table is still loading.
          try {
            await waitFor(cdp, `(() => { const s = ${SNAPSHOT_JS};
              return s.visiblePaneIds.length === 1 && s.visiblePaneIds[0] === 'pane-${tab}'
                && s.tbodies.every((t) => t.rows > 0 && !t.loading); })()`, 8000, `pane-${tab} settled`);
          } catch (e) { /* captured by snapshot assertions below */ }
          await sleep(150);
          const snap = await evaluate(cdp, SNAPSHOT_JS);
          const label = `[${w}x${h} ${round}] ${tab}`;

          const problems = [];
          if (snap.visiblePaneIds.length !== 1 || snap.visiblePaneIds[0] !== `pane-${tab}`) problems.push(`visible panes=${JSON.stringify(snap.visiblePaneIds)}`);
          if (!snap.activeNav.includes(tab) || snap.activeNav.length !== 1) problems.push(`active nav=${JSON.stringify(snap.activeNav)}`);
          if (!snap.heading) problems.push('no heading');
          if (snap.textLength < 40) problems.push(`pane text too short (${snap.textLength})`);
          for (const t of snap.tbodies) {
            if (t.rows === 0) problems.push(`#${t.id} has 0 rows (blank)`);
            if (t.loading) problems.push(`#${t.id} stuck loading`);
            if (t.error) problems.push(`#${t.id} shows error state: ${t.firstRow}`);
          }
          if (snap.paneError) problems.push('pane shows an error state');
          if (snap.horizontalOverflow) problems.push('page-level horizontal overflow');

          if (round === 'repeat') {
            const sent = requests.slice(before);
            for (const ep of TAB_REQUESTS[tab]) {
              const n = sent.filter((p) => p === ep).length;
              if (n !== 1) problems.push(`${ep} requested ${n}x on one click (expected 1)`);
            }
          }

          if (problems.length) fail(`${label}: ${problems.join('; ')}`);
          else pass(`${label}: "${snap.heading}" ${snap.tbodies.map((t) => `#${t.id}=${t.rows}${t.empty ? '(empty-state)' : ''}`).join(' ')}`);

          if (SHOT_DIR && round === 'initial') {
            const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
            writeFileSync(path.join(SHOT_DIR, `admin_${w}x${h}_${tab}.png`), Buffer.from(shot.data, 'base64'));
          }
        }
      }
    }

    // ---- Modal open / Escape close ----
    console.log('\nModal behaviour');
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
    await evaluate(cdp, `document.querySelector('.nav-item[data-tab="companies"]').click()`);
    await sleep(500);
    await evaluate(cdp, `document.getElementById('openCreateCompanyBtn').click()`);
    const modalOpen = await evaluate(cdp, `getComputedStyle(document.getElementById('companyModal')).display !== 'none'`);
    modalOpen ? pass('company modal opens') : fail('company modal did not open');
    await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
    await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
    await sleep(200);
    const modalClosed = await evaluate(cdp, `getComputedStyle(document.getElementById('companyModal')).display === 'none'`);
    modalClosed ? pass('company modal closes with Escape') : fail('company modal did not close with Escape');

    // ---- Console / network ----
    console.log('\nConsole & network');
    const uniqConsole = [...new Set(consoleErrors)];
    const uniqHttp = [...new Set(httpErrors)];
    uniqConsole.length ? uniqConsole.forEach((e) => fail(`console: ${e}`)) : pass('no console errors or uncaught exceptions');
    uniqHttp.length ? uniqHttp.forEach((e) => fail(`network: ${e}`)) : pass('no failed requests (excluding expected pre-login /auth/me 401)');
  } finally {
    try { await cdp?.send('Browser.close'); } catch (_) {}
    chrome.kill();
    await sleep(300);
    try { rmSync(profile, { recursive: true, force: true }); } catch (_) {}
  }

  console.log(`\n${failures.length === 0 ? 'PASSED' : `FAILED (${failures.length} problems)`}`);
  process.exit(failures.length === 0 ? 0 : 1);
}

main().catch((err) => { console.error(err); process.exit(1); });
