// Mirror of rednote_kb/index/tokenize.py. Both sides MUST match or recall breaks.
// Rule: lowercase; CJK ideographs (U+4E00–U+9FFF + Ext-A U+3400–U+4DBF) → one
// token per char; [a-z0-9_] runs → one word token; everything else is a boundary.

const MAX_RESULTS = 50;
const FIELD_WEIGHTS = { title: 10, tag: 5, author: 3, body: 1 };

function isCJK(cp) {
  return (cp >= 0x4E00 && cp <= 0x9FFF) || (cp >= 0x3400 && cp <= 0x4DBF);
}
function isWord(cp) {
  return (cp >= 0x30 && cp <= 0x39) ||  // 0-9
         (cp >= 0x61 && cp <= 0x7A) ||  // a-z
         cp === 0x5F;                   // _
}

function tokenize(s) {
  if (!s) return [];
  const out = [];
  let buf = '';
  const lo = s.toLowerCase();
  for (let i = 0; i < lo.length; i++) {
    const cp = lo.charCodeAt(i);
    if (isCJK(cp)) {
      if (buf) { out.push(buf); buf = ''; }
      out.push(lo[i]);
    } else if (isWord(cp)) {
      buf += lo[i];
    } else {
      if (buf) { out.push(buf); buf = ''; }
    }
  }
  if (buf) out.push(buf);
  return out;
}

function tokenizeUnique(s) {
  const seen = new Set(), out = [];
  for (const t of tokenize(s)) if (!seen.has(t)) { seen.add(t); out.push(t); }
  return out;
}

let INDEX = null;
async function loadIndex() {
  if (INDEX) return INDEX;
  const r = await fetch('./posts.json', { cache: 'no-cache' });
  if (!r.ok) throw new Error('posts.json HTTP ' + r.status);
  INDEX = await r.json();
  if (INDEX.v !== 2) {
    console.warn('posts.json schema v' + INDEX.v + ' — expected 2; reload required');
  }
  return INDEX;
}

function intersectSorted(a, b) {
  const out = [];
  let i = 0, j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { out.push(a[i]); i++; j++; }
    else if (a[i] <  b[j]) i++;
    else j++;
  }
  return out;
}

function search(index, query) {
  const qTokens = tokenizeUnique(query);
  if (!qTokens.length) return { hits: [], terms: [] };

  // Inverted-index intersection across query tokens.
  let candidates = null;
  for (const t of qTokens) {
    const postings = index.tok[t];
    if (!postings || !postings.length) return { hits: [], terms: qTokens };
    candidates = candidates ? intersectSorted(candidates, postings) : postings.slice();
    if (!candidates.length) return { hits: [], terms: qTokens };
  }

  // Field-weighted scoring on the survivors.
  const scored = [];
  for (const idx of candidates) {
    const p = index.posts[idx];
    let score = 0;
    for (const t of qTokens) {
      for (const field of Object.keys(FIELD_WEIGHTS)) {
        if (p._t[field] && p._t[field].includes(t)) score += FIELD_WEIGHTS[field];
      }
    }
    scored.push({ p, score });
  }

  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    const ad = a.p.published_at || a.p.fetched_at || '';
    const bd = b.p.published_at || b.p.fetched_at || '';
    return bd.localeCompare(ad);
  });

  return { hits: scored.slice(0, MAX_RESULTS).map(s => s.p), terms: qTokens };
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function highlight(text, terms) {
  if (!text) return '';
  let out = escapeHtml(text);
  // Sort by length desc so longer Latin words get highlighted before single chars.
  const sorted = [...terms].sort((a, b) => b.length - a.length);
  for (const t of sorted) {
    if (!t) continue;
    const re = new RegExp(t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    out = out.replace(re, m => `<mark>${m}</mark>`);
  }
  return out;
}

function render(result) {
  const ul = document.getElementById('results');
  const { hits, terms } = result;
  if (!hits.length) {
    ul.innerHTML = terms.length
      ? '<li class="empty">没有匹配的笔记。可以打开小红书再搜一次。</li>'
      : '';
    return;
  }
  ul.innerHTML = hits.map(p => `
    <li>
      <h2><a href="./p/${encodeURIComponent(p.id)}.html">${highlight(p.title || '(无标题)', terms)}</a></h2>
      ${p.body_excerpt ? `<p class="excerpt">${highlight(p.body_excerpt, terms)}</p>` : ''}
      <p class="byline">
        ${p.author ? escapeHtml(p.author) + ' · ' : ''}${escapeHtml(p.published_at || p.fetched_at || '')}
      </p>
    </li>
  `).join('');
}

let searchTimer = null;
async function doSearch() {
  const raw = document.getElementById('q').value.trim();
  history.replaceState(null, '', raw ? `?q=${encodeURIComponent(raw)}` : location.pathname);
  if (!raw) { render({ hits: [], terms: [] }); return; }
  try {
    const idx = await loadIndex();
    render(search(idx, raw));
  } catch (e) {
    document.getElementById('results').innerHTML =
      `<li class="empty">加载索引出错：${escapeHtml(e.message)}</li>`;
  }
}

const qEl = document.getElementById('q');
qEl.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(doSearch, 60);
});

const initial = new URLSearchParams(location.search).get('q');
if (initial) { qEl.value = initial; doSearch(); }

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('./sw.js').catch(() => { /* offline-only mode optional */ });
  });
}

window.__rednoteKB = { tokenize, tokenizeUnique, search, loadIndex };  // for tests
