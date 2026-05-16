# E2E test report — rednote-kb static site

## Tooling
- **Real browser** via Playwright (Node) + Chromium headless.
- Playwright pre-installed at `/opt/node22/lib/node_modules/playwright`; Chromium pre-installed at `/opt/pw-browsers/chromium-1194/chrome-linux/chrome` (env `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`). No download required.
- pytest wrapper: `tests/e2e/test_e2e_browser.py` builds the fixture site in a tmp dir, serves it on a free port via `ThreadingHTTPServer`, then runs `tests/e2e/playwright_e2e.js` against it. Skips cleanly with `pytest.skip(...)` if `node`, the playwright module, or a Chromium binary is missing — verified by re-running with `PLAYWRIGHT_BROWSERS_PATH=/nonexistent` (got `1 skipped`).
- JSDOM fallback was not needed.

## Scenarios

| # | Scenario | Result |
|---|---|---|
| 1 | Home `/` renders, title `小红书 KB · 搜索`, **0 console errors** | PASS |
| 2 | `link[rel=manifest]` resolves (`200 application/manifest+json`, `start_url=./index.html`) | PASS |
| 3 | Search `京都` → results contain `fixture-003` | PASS (`./p/fixture-003.html`) |
| 4 | Search `上海 brunch` → contains `fixture-001`, excludes `fixture-003` | PASS |
| 5 | Click first result → navigates to `/p/fixture-003.html`, body contains `京都` | PASS |
| 6 | Search `zzznonexistent` → renders `没有匹配的笔记。可以打开小红书再搜一次。` | PASS |
| 7 | Service worker registers (`getRegistration()` returns a `ServiceWorkerRegistration`; `controller` set after second load) | PASS |
| 8 | Mobile viewport 390×844: search input is 358px wide (= 390 − 16×2 padding), `scrollWidth == innerWidth == 390` (no horizontal scroll), 0 console errors | PASS |

`pytest -q` before changes: **19 passed**. After: **20 passed** (the new e2e test added; no regressions).

## Bugs found and fixed

None in the product. The single bug was in my first version of the e2e harness: scenario 5 typed `京都` after scenario 4 had left the input on `上海 brunch`, but didn't wait through the 60 ms debounce in `search.js`, so it read the previous result list and "navigated" to `fixture-001` while still asserting "looks like a `/p/fixture-XXX.html` URL" (the wide assertion let the bug pass). Fix in `tests/e2e/playwright_e2e.js`: reload `/`, then poll until `#results li h2 a[0]` href contains `fixture-003`, then click and assert the URL specifically matches `/p/fixture-003.html` and the body contains `京都`. No source code in `search.js`, `build.py`, templates, or CSS needed changing.

## Only verifiable on a real phone
- Actual PWA install flow ("Add to Home Screen" sheet on iOS Safari / Android Chrome) and the standalone-mode chrome behaviour driven by `manifest.webmanifest`'s `display: standalone`.
- iOS `apple-mobile-web-app-*` meta + `apple-touch-icon` rendering on the home screen.
- Real `prefers-color-scheme: dark` switching when she toggles iOS dark mode.
- Real-network offline behaviour: airplane mode → revisit cached post page, confirm SW serves `staleWhileRevalidate` from `DATA_CACHE`.
- iOS Safari quirks around `enterkeyhint="search"`, `viewport-fit=cover`, and `env(safe-area-inset-bottom)` on a notched phone.
- Touch target ergonomics — the desktop test only measures geometry, not thumb reach.
