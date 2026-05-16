// v0 search: substring match over the flat posts.json index.
// v1 will swap this out for jieba-pre-tokenized MiniSearch.

const MAX_RESULTS = 50;
let INDEX = null;

async function loadIndex() {
  if (INDEX) return INDEX;
  const r = await fetch('./posts.json', { cache: 'no-cache' });
  INDEX = await r.json();
  return INDEX;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function highlight(text, terms) {
  let out = escapeHtml(text || '');
  for (const t of terms) {
    if (!t) continue;
    const re = new RegExp(t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    out = out.replace(re, m => `<mark>${m}</mark>`);
  }
  return out;
}

function matches(post, terms) {
  const hay = (
    (post.title || '') + '\n' +
    (post.body || '') + '\n' +
    (post.ocr_text || '') + '\n' +
    (post.tags || []).join(' ') + '\n' +
    (post.author || '')
  ).toLowerCase();
  return terms.every(t => hay.includes(t));
}

function render(results, terms) {
  const ul = document.getElementById('results');
  if (!results.length) {
    ul.innerHTML = terms.length
      ? '<li class="empty">没有匹配的笔记。可以打开小红书再搜一次。</li>'
      : '';
    return;
  }
  ul.innerHTML = results.map(p => `
    <li>
      <h2><a href="./p/${encodeURIComponent(p.id)}.html">${highlight(p.title || '(无标题)', terms)}</a></h2>
      ${p.body_excerpt ? `<p class="excerpt">${highlight(p.body_excerpt, terms)}</p>` : ''}
      <p class="byline">
        ${p.author ? escapeHtml(p.author) + ' · ' : ''}${p.published_at || p.fetched_at || ''}
      </p>
    </li>
  `).join('');
}

let searchTimer = null;
async function doSearch() {
  const raw = document.getElementById('q').value.trim();
  const terms = raw.toLowerCase().split(/\s+/).filter(Boolean);
  history.replaceState(null, '', raw ? `?q=${encodeURIComponent(raw)}` : location.pathname);
  if (!terms.length) { render([], terms); return; }
  const idx = await loadIndex();
  const hits = [];
  for (const p of idx.posts) {
    if (matches(p, terms)) {
      hits.push(p);
      if (hits.length >= MAX_RESULTS) break;
    }
  }
  render(hits, terms);
}

document.getElementById('q').addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(doSearch, 80);
});

const initial = new URLSearchParams(location.search).get('q');
if (initial) {
  document.getElementById('q').value = initial;
  doSearch();
}
