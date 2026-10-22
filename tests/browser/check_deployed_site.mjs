import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

const URL_TO_CHECK = process.argv[2] || 'https://wavenxd-sales-ai.onrender.com/';
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const port = 9400 + Math.floor(Math.random() * 500);
const profile = mkdtempSync(path.join(tmpdir(), 'wavenxd-check-'));

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
        if (msg.error) reject(new Error(msg.error.message));
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

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

try {
  let targets = null;
  for (let i = 0; i < 50 && !targets; i++) {
    try { targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); } catch (_) { await sleep(200); }
  }
  const page = targets.find((t) => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.addEventListener('open', r); ws.addEventListener('error', j); });
  const cdp = new CDP(ws);

  const networkResponses = [];
  const consoleMessages = [];

  cdp.on((m) => {
    if (m.method === 'Network.responseReceived') {
      const { status, url, mimeType } = m.params.response;
      networkResponses.push({ status, url, mimeType });
    }
    if (m.method === 'Runtime.consoleAPICalled') {
      consoleMessages.push(m.params.args.map((a) => a.value ?? a.description).join(' '));
    }
    if (m.method === 'Log.entryAdded') {
      consoleMessages.push(`[${m.params.entry.level}] ${m.params.entry.text} ${m.params.entry.url || ''}`);
    }
  });

  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Log.enable');
  await cdp.send('Network.enable');

  console.log(`Navigating to ${URL_TO_CHECK}...`);
  await cdp.send('Page.navigate', { url: URL_TO_CHECK });
  await sleep(4000);

  const styles = await cdp.send('Runtime.evaluate', {
    expression: `
      (() => {
        const body = document.body;
        const icon = document.querySelector('.login-brand-icon');
        const iconSvg = icon ? icon.querySelector('svg') : null;
        const card = document.querySelector('.login-card');
        return {
          bodyFont: window.getComputedStyle(body).fontFamily,
          bodyBg: window.getComputedStyle(body).backgroundColor,
          iconBg: icon ? window.getComputedStyle(icon).background : 'none',
          iconBoxShadow: icon ? window.getComputedStyle(icon).boxShadow : 'none',
          iconSvgStroke: iconSvg ? window.getComputedStyle(iconSvg).stroke : 'none',
          cardBg: card ? window.getComputedStyle(card).backgroundColor : 'none',
          cardBoxShadow: card ? window.getComputedStyle(card).boxShadow : 'none',
        };
      })()
    `,
    returnByValue: true,
  });

  console.log('\n--- NETWORK RESPONSES ---');
  for (const r of networkResponses) {
    console.log(`${r.status} [${r.mimeType}] ${r.url}`);
  }

  console.log('\n--- CONSOLE MESSAGES ---');
  for (const cm of consoleMessages) {
    console.log(cm);
  }

  console.log('\n--- COMPUTED STYLES ---');
  console.log(JSON.stringify(styles.result.value, null, 2));

  const screenshotRes = await cdp.send('Page.captureScreenshot', { format: 'png' });
  const screenshotPath = '/Users/swaruppal/.gemini/antigravity-ide/brain/1d132897-ba6b-43b9-baea-b0795007e03a/deployed_login_page.png';
  import('node:fs').then(({ writeFileSync }) => {
    writeFileSync(screenshotPath, Buffer.from(screenshotRes.data, 'base64'));
    console.log(`\nScreenshot saved: ${screenshotPath}`);
  });
  await sleep(500);

  ws.close();
} catch (err) {
  console.error('Check failed:', err);
} finally {
  chrome.kill();
  try { rmSync(profile, { recursive: true, force: true }); } catch (_) {}
}
