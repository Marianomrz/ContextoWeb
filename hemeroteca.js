/* ==========================================================================
   CONTEXTO — hemeroteca.js
   Carga hemeroteca.json (índice PERMANENTE que alimenta agent.py en cada
   ciclo, nunca se recorta) y agrupa todas las notas por día de
   publicación, más reciente primero. Independiente de app.js (páginas
   estáticas no cargan ese script). Puro cliente, sin llamadas adicionales.

   Antes de la corrección del 14 jul 2026, este script leía articles.json
   directo — pero ese archivo lo trunca agent.py a las MAX_ARTICLES_KEPT
   notas vivas de la portada, así que la "hemeroteca" en realidad nunca
   fue un archivo: cualquier nota más vieja que esa ventana desaparecía
   también de aquí. hemeroteca.json es un índice ligero aparte
   (id/title/category/published_at) que sí se conserva para siempre.
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

  // Todo el sitio agrupa/muestra fechas en hora de Ciudad de México, sin
  // importar la zona del lector ni la del servidor que generó el dato
  // (agregado 14 jul 2026 — antes dayKey() usaba toISOString(), que es
  // SIEMPRE UTC: una nota publicada, por decir, a las 19:00 hora CDMX ya
  // caía del lado UTC del día siguiente y aparecía agrupada bajo la fecha
  // equivocada — el bug real detrás de "aparece miércoles siendo aún
  // martes"). mxDateKey usa el locale en-CA solo como truco: ese locale
  // formatea como AAAA-MM-DD, que es justo lo que necesitamos, ya
  // convertido al huso de Ciudad de México por el motor de Intl.
  function mxDateKey(d) {
    return new Intl.DateTimeFormat('en-CA', {
      timeZone: 'America/Mexico_City', year: 'numeric', month: '2-digit', day: '2-digit',
    }).format(d);
  }

  function dayKey(iso) {
    const d = new Date(iso);
    return isNaN(d) ? 'sin-fecha' : mxDateKey(d);
  }

  function dayLabel(key) {
    if (key === 'sin-fecha') return 'Sin fecha';
    // mediodía UTC evita que el huso horario local recorra la fecha al día
    // anterior al construir el Date; timeZone explícito en el format de
    // abajo asegura que el nombre del día/mes también salga en hora CDMX.
    const d = new Date(key + 'T12:00:00Z');
    return d.toLocaleDateString('es-MX', {
      weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
      timeZone: 'America/Mexico_City',
    });
  }

  function timeLabel(iso) {
    const d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleTimeString('es-MX', {
      hour: '2-digit', minute: '2-digit', timeZone: 'America/Mexico_City',
    });
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
          <button type="button" class="fav-btn hemero-fav" data-fav="${esc(a.id)}" aria-pressed="false">
            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M6 3h12a1 1 0 0 1 1 1v17l-7-4-7 4V4a1 1 0 0 1 1-1z"/></svg>
            <span class="fav-label">Guardar</span>
          </button>
        </li>`).join('');
      return `
        <div class="hemero-day">
          <h2 class="hemero-date">${esc(dayLabel(key))} <span class="hemero-count">· ${entries.length} nota${entries.length === 1 ? '' : 's'}</span></h2>
          <ul class="hemero-entries">${items}</ul>
        </div>`;
    }).join('');
    // avisa a favoritos.js que hay botones data-fav nuevos que decorar
    document.dispatchEvent(new CustomEvent('contexto:fav-rendered'));
  }

  fetch('hemeroteca.json', { cache: 'no-store' })
    .then(r => r.ok ? r.json() : { articles: [] })
    .then(data => render(Array.isArray(data.articles) ? data.articles : []))
    .catch(() => render([]));
})();
