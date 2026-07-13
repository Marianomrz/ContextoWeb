/* ==========================================================================
   CONTEXTO — hemeroteca.js
   Carga articles.json y agrupa todas las notas por día de publicación,
   más reciente primero. Independiente de app.js (páginas estáticas no
   cargan ese script). Puro cliente, sin llamadas adicionales.
   ========================================================================== */

(function () {
  'use strict';

  const saved = localStorage.getItem('contexto-theme');
  if (saved === 'dark' || saved === 'light') {
    document.documentElement.dataset.theme = saved;
  }

  const CATEGORY_LABELS = {
    politica: 'Política',
    economia: 'Economía',
    tecnologia: 'Tecnología',
    sociedad: 'Sociedad',
    internacional: 'Internacional',
    deportes: 'Deportes',
    literatura: 'Literatura',
  };

  function esc(str) {
    // escapa también comillas (revisión de seguridad 10 jul 2026): el truco
    // textContent->innerHTML solo codifica & < > — pero esc() se usa dentro
    // de atributos (href="...", datetime="..."), donde una comilla doble en
    // el dato rompería el atributo e inyectaría atributos arbitrarios.
    const d = document.createElement('div');
    d.textContent = String(str == null ? '' : str);
    return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function dayKey(iso) {
    const d = new Date(iso);
    return isNaN(d) ? 'sin-fecha' : d.toISOString().slice(0, 10);
  }

  function dayLabel(key) {
    if (key === 'sin-fecha') return 'Sin fecha';
    // mediodía UTC evita que el huso horario local recorra la fecha al día anterior
    const d = new Date(key + 'T12:00:00Z');
    return d.toLocaleDateString('es-MX', {
      weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
    });
  }

  function timeLabel(iso) {
    const d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit' });
  }

  function groupByDay(articles) {
    const groups = new Map();
    for (const a of articles) {
      const key = dayKey(a.published_at);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(a);
    }
    return [...groups.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  }

  function render(articles) {
    const list = document.getElementById('hemerotecaList');
    if (!articles.length) {
      list.innerHTML = '<p class="feed-empty">Todavía no hay notas en el archivo.</p>';
      return;
    }
    const days = groupByDay(articles);
    list.innerHTML = days.map(([key, entries]) => {
      entries.sort((x, y) => new Date(y.published_at) - new Date(x.published_at));
      const items = entries.map(a => `
        <li>
          <a href="articulo/${esc(a.id)}.html" data-category="${esc(a.category || '')}">
            <span class="category-tag hemero-tag">${esc(CATEGORY_LABELS[a.category] || a.category || 'General')}</span>
            <span class="hemero-title">${esc(a.title)}</span>
            <time class="hemero-time" datetime="${esc(a.published_at || '')}">${esc(timeLabel(a.published_at))}</time>
          </a>
        </li>`).join('');
      return `
        <div class="hemero-day">
          <h2 class="hemero-date">${esc(dayLabel(key))} <span class="hemero-count">· ${entries.length} nota${entries.length === 1 ? '' : 's'}</span></h2>
          <ul class="hemero-entries">${items}</ul>
        </div>`;
    }).join('');
  }

  fetch('articles.json', { cache: 'no-store' })
    .then(r => r.ok ? r.json() : { articles: [] })
    .then(data => render(Array.isArray(data.articles) ? data.articles : []))
    .catch(() => render([]));
})();
