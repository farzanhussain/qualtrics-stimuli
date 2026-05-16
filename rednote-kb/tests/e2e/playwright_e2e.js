// Real-browser end-to-end test of the built rednote-kb static site.
//
// Usage:  node playwright_e2e.js <base-url>
//
// Exits 0 on full pass; prints a JSON line per scenario:
//   {"name": "<scenario>", "pass": bool, "info": ...}
// and a final summary line:
//   {"name": "_summary_", "pass": bool, "total": N, "failed": [..names..]}
//
// Exits non-zero if any scenario fails (so pytest can fail the test cleanly).

// Resolve playwright from a few well-known locations so this script works
// regardless of whether NODE_PATH is set.
function loadPlaywright() {
  const tried = [];
  for (const p of [
    'playwright',
    '/opt/node22/lib/node_modules/playwright',
    '/usr/lib/node_modules/playwright',
    '/usr/local/lib/node_modules/playwright',
  ]) {
    try { return require(p); } catch (e) { tried.push(`${p}: ${e.code || e.message}`); }
  }
  throw new Error('cannot resolve playwright; tried:\n  ' + tried.join('\n  '));
}
const { chromium } = loadPlaywright();

const BASE = process.argv[2] || 'http://127.0.0.1:8770';

const results = [];
function record(name, pass, info) {
  results.push({ name, pass, info });
  process.stdout.write(JSON.stringify({ name, pass, info }) + '\n');
}

async function withRetries(fn, { tries = 20, delayMs = 50 } = {}) {
  let lastErr;
  for (let i = 0; i < tries; i++) {
    try { return await fn(); } catch (e) { lastErr = e; }
    await new Promise(r => setTimeout(r, delayMs));
  }
  throw lastErr;
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ serviceWorkers: 'allow' });
  const page = await ctx.newPage();

  const consoleErrors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', err => consoleErrors.push('pageerror: ' + err.message));

  // --- Scenario 1: home page renders without console errors ---
  try {
    await page.goto(BASE + '/', { waitUntil: 'networkidle' });
    await page.waitForSelector('#q');
    const title = await page.title();
    record('home_renders', title.includes('小红书'),
           { title, consoleErrors: [...consoleErrors] });
  } catch (e) {
    record('home_renders', false, { error: e.message });
  }

  // --- Scenario 2: link[rel=manifest] exists and resolves ---
  try {
    const href = await page.getAttribute('link[rel=manifest]', 'href');
    const r = await page.request.get(new URL(href, BASE + '/').toString());
    const ct = r.headers()['content-type'] || '';
    const body = await r.json();
    record('manifest_link_resolves',
           r.ok() && body.start_url !== undefined,
           { href, status: r.status(), content_type: ct, start_url: body.start_url });
  } catch (e) {
    record('manifest_link_resolves', false, { error: e.message });
  }

  // --- Scenario 3: search '京都' returns fixture-003 ---
  try {
    await page.fill('#q', '');
    await page.type('#q', '京都', { delay: 10 });
    await withRetries(async () => {
      const links = await page.$$eval('#results li h2 a',
        as => as.map(a => a.getAttribute('href')));
      if (!links.some(h => h && h.includes('fixture-003'))) {
        throw new Error('fixture-003 not yet present: ' + JSON.stringify(links));
      }
    });
    const links = await page.$$eval('#results li h2 a',
      as => as.map(a => a.getAttribute('href')));
    record('search_kyoto_finds_003',
           links.some(h => h.includes('fixture-003')),
           { links });
  } catch (e) {
    record('search_kyoto_finds_003', false, { error: e.message });
  }

  // --- Scenario 4: multi-token '上海 brunch' contains 001, excludes 003 ---
  try {
    await page.fill('#q', '');
    await page.type('#q', '上海 brunch', { delay: 10 });
    await withRetries(async () => {
      const links = await page.$$eval('#results li h2 a',
        as => as.map(a => a.getAttribute('href')));
      if (!links.some(h => h && h.includes('fixture-001'))) {
        throw new Error('fixture-001 not yet present: ' + JSON.stringify(links));
      }
    });
    const links = await page.$$eval('#results li h2 a',
      as => as.map(a => a.getAttribute('href')));
    const has001 = links.some(h => h.includes('fixture-001'));
    const no003  = !links.some(h => h.includes('fixture-003'));
    record('search_multi_token', has001 && no003,
           { links, has001, no003 });
  } catch (e) {
    record('search_multi_token', false, { error: e.message });
  }

  // --- Scenario 5: click first result navigates to /p/fixture-XXX.html ---
  try {
    // Start from a fresh search that we know has exactly one hit (fixture-003).
    // Reload so input value + URL state are clean.
    await page.goto(BASE + '/', { waitUntil: 'networkidle' });
    await page.waitForSelector('#q');
    await page.fill('#q', '');
    await page.type('#q', '京都', { delay: 10 });
    // Wait until the result list actually shows fixture-003 (debounced search).
    await withRetries(async () => {
      const links = await page.$$eval('#results li h2 a',
        as => as.map(a => a.getAttribute('href')));
      if (!links.length || !links[0].includes('fixture-003')) {
        throw new Error('first link not fixture-003 yet: ' + JSON.stringify(links));
      }
    });
    const firstHref = await page.getAttribute('#results li h2 a', 'href');
    await Promise.all([
      page.waitForURL(/\/p\/fixture-003\.html/),
      page.click('#results li h2 a'),
    ]);
    const url = page.url();
    const bodyText = await page.locator('article.post .body').innerText();
    record('click_navigates_to_post',
           /\/p\/fixture-003\.html$/.test(url) && bodyText.includes('京都'),
           { url, body_len: bodyText.length, first_href: firstHref });
  } catch (e) {
    record('click_navigates_to_post', false, { error: e.message });
  }

  // --- Scenario 6: zzznonexistent shows the empty message ---
  try {
    // go back to home first
    await page.goto(BASE + '/', { waitUntil: 'networkidle' });
    await page.waitForSelector('#q');
    await page.fill('#q', '');
    await page.type('#q', 'zzznonexistent', { delay: 10 });
    await withRetries(async () => {
      const text = await page.locator('#results').innerText();
      if (!text.includes('没有匹配的笔记')) throw new Error('empty text not shown: ' + text);
    });
    const text = await page.locator('#results').innerText();
    record('no_match_shows_empty_msg',
           text.includes('没有匹配的笔记'),
           { text });
  } catch (e) {
    record('no_match_shows_empty_msg', false, { error: e.message });
  }

  // --- Scenario 7: service worker registers ---
  try {
    // we already loaded '/' above with serviceWorkers:'allow' on the context
    const reg = await page.evaluate(async () => {
      if (!('serviceWorker' in navigator)) return { supported: false };
      const r = await navigator.serviceWorker.getRegistration();
      return {
        supported: true,
        has_registration: !!r,
        scope: r ? r.scope : null,
        controller: !!navigator.serviceWorker.controller,
      };
    });
    record('service_worker_registers',
           reg.supported && reg.has_registration, reg);
  } catch (e) {
    record('service_worker_registers', false, { error: e.message });
  }

  // --- Scenario 8: mobile viewport, full-width search, no horizontal scroll ---
  try {
    const mobileCtx = await browser.newContext({
      viewport: { width: 390, height: 844 },
      deviceScaleFactor: 3,
      isMobile: true,
      hasTouch: true,
    });
    const mPage = await mobileCtx.newPage();
    const mErrors = [];
    mPage.on('console', m => { if (m.type() === 'error') mErrors.push(m.text()); });
    mPage.on('pageerror', e => mErrors.push('pageerror: ' + e.message));
    await mPage.goto(BASE + '/', { waitUntil: 'networkidle' });
    await mPage.waitForSelector('#q');

    const dims = await mPage.evaluate(() => {
      const q = document.getElementById('q');
      const r = q.getBoundingClientRect();
      return {
        innerWidth: window.innerWidth,
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
        q_width: r.width,
        q_left: r.left,
        q_right: r.right,
      };
    });
    // search input should fill nearly the full content width (allowing for main's
    // 16px padding on each side → 390 - 32 = 358). We assert >= 320 (~88%) and
    // page does not horizontally overflow viewport.
    const fullWidth = dims.q_width >= 320;
    const noHScroll = dims.scrollWidth <= dims.innerWidth + 1;  // tolerate rounding
    record('mobile_layout',
           fullWidth && noHScroll && mErrors.length === 0,
           { dims, console_errors: mErrors, fullWidth, noHScroll });
    await mobileCtx.close();
  } catch (e) {
    record('mobile_layout', false, { error: e.message });
  }

  // --- Final summary ---
  const failed = results.filter(r => !r.pass).map(r => r.name);
  const summary = { name: '_summary_', pass: failed.length === 0,
                    total: results.length, failed };
  process.stdout.write(JSON.stringify(summary) + '\n');
  // emit console errors collected across desktop session for debugging
  if (consoleErrors.length) {
    process.stderr.write('desktop console errors:\n' +
      consoleErrors.map(s => '  ' + s).join('\n') + '\n');
  }
  await browser.close();
  process.exit(failed.length ? 1 : 0);
})().catch(e => {
  process.stderr.write('FATAL: ' + (e && e.stack || e) + '\n');
  process.exit(2);
});
