#!/usr/bin/env node
/**
 * WaveNxD Customer Consultation UI — Browser Smoke & Regression Verification.
 *
 * Verifies in real headless Chrome via CDP:
 *   1. Initial login and empty consultation summary state.
 *   2. Parameter extraction and right-panel summary update (Active Requirements, Missing Info, Recommended Product).
 *   3. Markdown table rendering without raw delimiters or literal <br> fragments.
 *   4. Hypothetical scenario (2 mL/min) preserves primary confirmed flow rate (10 mL/min).
 *   5. Accurate display of NO MATCH when catalog application is not verified.
 *   6. Captures proof screenshot.
 */

import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

const BASE = process.env.WAVENXD_BASE_URL || 'http://127.0.0.1:8000';
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const SHOT_PATH = process.env.WAVENXD_SCREENSHOT_PATH || '/Users/swaruppal/.gemini/antigravity-ide/brain/1d132897-ba6b-43b9-baea-b0795007e03a/consultation_summary_synced.png';

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

async function waitFor(cdp, expression, timeoutMs = 15000, label = expression) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      if (await evaluate(cdp, expression)) return true;
    } catch (_) {}
    await sleep(200);
  }
  throw new Error(`Timed out waiting for: ${label}`);
}

async function main() {
  const failures = [];
  const pass = (msg) => console.log(`  ✓ ${msg}`);
  const fail = (msg) => { console.error(`  ✗ ${msg}`); failures.push(msg); };

  console.log(`Starting headless Chrome against ${BASE}...`);
  const port = 9400 + Math.floor(Math.random() * 500);
  const profile = mkdtempSync(path.join(tmpdir(), 'wavenxd-cust-smoke-'));
  const chrome = spawn(CHROME, [
    '--headless=new',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-gpu',
    '--window-size=1440,900',
    'about:blank',
  ], { stdio: 'ignore' });

  let cdp;
  try {
    let targets = null;
    for (let i = 0; i < 50 && !targets; i++) {
      try {
        targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      } catch (_) {
        await sleep(200);
      }
    }
    const page = targets.find((t) => t.type === 'page');
    if (!page) throw new Error('No page target found');

    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      ws.addEventListener('open', resolve, { once: true });
      ws.addEventListener('error', reject, { once: true });
    });
    cdp = new CDP(ws);

    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

    // Step 1: Navigate to portal
    console.log('\n1. Navigating to Customer Portal');
    await cdp.send('Page.navigate', { url: `${BASE}/` });
    await waitFor(cdp, 'document.readyState === "complete"');
    pass('Page loaded');

    // Step 2: Sign in as Alice (Alpha Pharma)
    console.log('\n2. Signing in as Alice (Alpha Pharma)');
    await waitFor(cdp, `document.querySelector('.btn-demo[data-email="alice@alphapharma.com"]') !== null`, 8000, 'Alice demo button');
    await evaluate(cdp, `document.querySelector('.btn-demo[data-email="alice@alphapharma.com"]').click()`);
    await waitFor(cdp, `document.getElementById('workspaceView') && getComputedStyle(document.getElementById('workspaceView')).display !== 'none'`, 10000, 'workspace view');
    pass('Customer workspace view visible');

    // Step 3: Check initial summary empty state
    console.log('\n3. Checking Initial Consultation Summary Empty State');
    const initReqs = await evaluate(cdp, `document.getElementById('knownReqsContainer').innerText`);
    if (initReqs.includes('No parameters specified yet')) {
      pass(`Active requirements empty state: "${initReqs.trim()}"`);
    } else {
      fail(`Expected empty active requirements, got: "${initReqs}"`);
    }

    const initProduct = await evaluate(cdp, `document.getElementById('compactProductEmpty').innerText`);
    if (initProduct.includes('Awaiting sufficient technical parameters')) {
      pass(`Recommended product empty state: "${initProduct.trim()}"`);
    } else {
      fail(`Expected empty recommended product, got: "${initProduct}"`);
    }

    // Step 4: Send customer requirements message
    console.log('\n4. Sending Structured Customer Requirements');
    const msgText = `Application: pharmaceutical tablet coating
Liquid type: water-based pharmaceutical coating solution
Viscosity: 15 cP
Initial target flow rate: 10 mL/min`;

    await evaluate(cdp, `(() => {
      const input = document.getElementById('messageInput');
      input.value = ${JSON.stringify(msgText)};
      input.dispatchEvent(new Event('input', { bubbles: true }));
      document.getElementById('sendBtn').click();
    })()`);

    // Wait for assistant response to appear (starts with 1 initial greeting, so >= 2)
    await waitFor(
      cdp,
      `document.querySelectorAll('.message-bubble.assistant').length >= 2`,
      25000,
      'assistant response bubble for customer requirements'
    );
    pass('Received AI assistant response');

    // Step 5: Verify Consultation Summary synchronization
    console.log('\n5. Verifying Consultation Summary Synchronization');
    const activeReqsHtml = await evaluate(cdp, `document.getElementById('knownReqsContainer').innerHTML`);
    const activeReqsText = await evaluate(cdp, `document.getElementById('knownReqsContainer').innerText.replace(/\\s+/g, ' ')`);
    console.log(`   Active Requirements: ${activeReqsText}`);

    if (activeReqsText.includes('Flow: 10 ml/min') && activeReqsText.includes('Viscosity: 15 cP') && activeReqsText.includes('App: pharmaceutical tablet coating')) {
      pass('Active Requirements correctly synchronized with structured backend parameters');
    } else {
      fail(`Active Requirements missing expected values: "${activeReqsText}"`);
    }

    // Verify Recommended Product card shows NO MATCH honestly
    const badgeText = await evaluate(cdp, `document.getElementById('compactProdMatchBadge').innerText.replace(/\\s+/g, ' ')`);
    const prodName = await evaluate(cdp, `document.getElementById('compactProdName').innerText.replace(/\\s+/g, ' ')`);
    const prodExplanation = await evaluate(cdp, `document.getElementById('compactProdExplanation').innerText.replace(/\\s+/g, ' ')`);
    console.log(`   Recommended Product Card: [${badgeText}] ${prodName} - ${prodExplanation}`);

    if (badgeText.includes('NO MATCH') && prodName.includes('No Compatible Nozzle')) {
      pass('Recommended Product card correctly displays honest NO MATCH without invented nozzle');
    } else {
      fail(`Expected NO MATCH product card, got badge="${badgeText}", name="${prodName}"`);
    }

    const emptyDisplay = await evaluate(cdp, `getComputedStyle(document.getElementById('compactProductEmpty')).display`);
    const contentDisplay = await evaluate(cdp, `getComputedStyle(document.getElementById('compactProductContent')).display`);
    if (emptyDisplay === 'none' && contentDisplay !== 'none') {
      pass('Recommended Product waiting placeholder is hidden and product content card is visible');
    } else {
      fail(`Expected waiting placeholder hidden and content visible, but emptyDisplay=${emptyDisplay}, contentDisplay=${contentDisplay}`);
    }

    // Verify Missing Information
    const missingCount = await evaluate(cdp, `document.getElementById('missingInfoCount').innerText`);
    console.log(`   Missing info count: ${missingCount}`);
    if (parseInt(missingCount, 10) >= 1) {
      pass(`Missing Information count accurately reflects unprovided specifications (${missingCount})`);
    } else {
      fail(`Missing information count unexpected: "${missingCount}"`);
    }

    // Step 6: Verify message formatting
    console.log('\n6. Verifying Message Formatting');
    const assistantBubbleHtml = await evaluate(cdp, `document.querySelectorAll('.message-bubble.assistant')[1].querySelector('.message-text').innerHTML`);
    if (assistantBubbleHtml.includes('&lt;br&gt;')) {
      fail('Found literal &lt;br&gt; in assistant message!');
    } else {
      pass('No raw <br> tags found as literal text');
    }

    if (assistantBubbleHtml.includes('| Spec | Value |') || assistantBubbleHtml.includes('|---|---|')) {
      fail('Found literal raw Markdown table pipes in assistant message!');
    } else {
      pass('No raw Markdown table delimiter pipes shown as literal text');
    }

    // Step 7: Send hypothetical scenario (2 mL/min)
    console.log('\n7. Sending Hypothetical Test Target (2 mL/min)');
    const hypoText = 'Later hypothetical test target: 2 mL/min. What if we test at 2 mL/min?';
    await evaluate(cdp, `(() => {
      const input = document.getElementById('messageInput');
      input.value = ${JSON.stringify(hypoText)};
      input.dispatchEvent(new Event('input', { bubbles: true }));
      document.getElementById('sendBtn').click();
    })()`);

    await waitFor(
      cdp,
      `document.querySelectorAll('.message-bubble.assistant').length >= 3`,
      25000,
      'third assistant response bubble for hypothetical inquiry'
    );
    pass('Received second AI assistant response for hypothetical inquiry');

    // Verify that primary active requirement flow rate was NOT overwritten
    const postHypoReqsText = await evaluate(cdp, `document.getElementById('knownReqsContainer').innerText.replace(/\\s+/g, ' ')`);
    console.log(`   Active Requirements after hypothetical test: ${postHypoReqsText}`);

    if (postHypoReqsText.includes('Flow: 10 ml/min')) {
      pass('Primary target flow rate (10 ml/min) was NOT overwritten by hypothetical test target (2 ml/min)');
    } else {
      fail(`Primary flow rate was overwritten or corrupted! Current: "${postHypoReqsText}"`);
    }

    // Step 8: Capture browser proof screenshot
    console.log('\n8. Capturing Verification Screenshot');
    const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(SHOT_PATH, Buffer.from(shot.data, 'base64'));
    pass(`Saved verification screenshot to ${SHOT_PATH}`);

  } finally {
    try { await cdp?.send('Browser.close'); } catch (_) {}
    chrome.kill();
    await sleep(300);
    try { rmSync(profile, { recursive: true, force: true }); } catch (_) {}
  }

  console.log(`\n======================================================`);
  if (failures.length === 0) {
    console.log('ALL BROWSER SMOKE CHECKS PASSED SUCCESSFULLY!');
  } else {
    console.error(`FAILED WITH ${failures.length} ISSUES:`);
    failures.forEach((f) => console.error(`  - ${f}`));
    process.exit(1);
  }
}

main().catch((err) => {
  console.error('Fatal test error:', err);
  process.exit(1);
});
