/* ==========================================================================
   CONTEXTO — metodologia.js
   Lee qc_log.json en la RAÍZ del repo (bitácora acotada a las últimas 200
   entradas) — copia pública de agent/qc_log.json, publicada ahí porque
   .vercelignore excluye toda la carpeta agent/ del despliegue (a propósito,
   ver .vercelignore) y esta página necesita poder leerla desde el
   navegador. La copia la genera el paso "Publicar cambios" de
   agente.yml/moderacion.yml (agregado 16 jul 2026 tras detectar que la
   página siempre mostraba "sin veredictos" en producción).
   Puro cliente, sin llamada nueva a ningún backend — el archivo ya es
   público (se sirve como cualquier otro archivo estático del repo, igual
   que articles.json/blog.json).
   Independiente de app.js, mismo criterio que hemeroteca.js/compass.js.
   Agregada 16 jul 2026 (transparencia del pipeline de control de calidad).
   ========================================================================== */

(function () {
  'use strict';

  const saved = localStorage.getItem('contexto-theme');
  if (saved === 'dark' || saved === 'light') {
    document.documentElement.dataset.theme = saved;
  }

  const KIND_LABELS = {
    noticia: 'Noticias', literatura: 'Literatura',
    juridica: 'Revista jurídica', resena: 'Reseñas de lectores',
  };
  const CATEGORY_LABELS = {
    politica: 'Política', economia: 'Economía', tecnologia: 'Tecnología',
    sociedad: 'Sociedad', internacional: 'Internacional', deportes: 'Deportes',
  };

  function esc(str) {
    const d = document.createElement('div');
    d.textContent = String(str == null ? '' : str);
    return d.innerHTML;
  }

  function prettyCriterion(key) {
    return key.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
  }

  function barRow(label, aprobados, rechazados) {
    const total = aprobados + rechazados;
    const pct = total ? Math.round((aprobados / total) * 100) : 0;
    return `
      <div class="method-row">
        <div class="method-row-label">
          <span>${esc(label)}</span>
          <span class="method-row-count">${aprobados} de ${total} (${pct}%)</span>
        </div>
        <div class="method-bar-track">
          <div class="method-bar-fill" style="width:${pct}%"></div>
        </div>
      </div>`;
  }

  function criterionRow(label, avg) {
    const pct = Math.max(0, Math.min(100, (avg / 10) * 100));
    return `
      <div class="method-row method-row-sm">
        <div class="method-row-label">
          <span>${esc(label)}</span>
          <span class="method-row-count">${avg.toFixed(1)}/10</span>
        </div>
        <div class="method-bar-track method-bar-track-sm">
          <div class="method-bar-fill" style="width:${pct}%"></div>
        </div>
      </div>`;
  }

  function render(verdicts) {
    const root = document.getElementById('methodologyRoot');
    if (!verdicts.length) {
      root.innerHTML = '<p class="feed-empty">Todavía no hay veredictos registrados.</p>';
      return;
    }

    const byKind = {};
    for (const v of verdicts) {
      const k = v.kind || '?';
      byKind[k] = byKind[k] || { aprobados: 0, rechazados: 0, scores: {} };
      byKind[k][v.approved ? 'aprobados' : 'rechazados']++;
      const scores = v.scores || {};
      for (const [crit, val] of Object.entries(scores)) {
        if (typeof val !== 'number') continue;
        byKind[k].scores[crit] = byKind[k].scores[crit] || [];
        byKind[k].scores[crit].push(val);
      }
    }

    const catCounts = {};
    for (const v of verdicts) {
      if (v.kind !== 'noticia' || !v.category) continue;
      catCounts[v.category] = catCounts[v.category] || { aprobados: 0, rechazados: 0 };
      catCounts[v.category][v.approved ? 'aprobados' : 'rechazados']++;
    }

    const totalAprobados = verdicts.filter(v => v.approved).length;
    const totalPct = Math.round((totalAprobados / verdicts.length) * 100);

    let html = `
      <p class="method-summary">De las últimas <strong>${verdicts.length}</strong> evaluaciones
      registradas por el control de calidad, <strong>${totalAprobados}</strong> se aprobaron
      (${totalPct}%). Cada tipo de contenido usa su propia rúbrica de 5 criterios — ver
      <a href="fuentes.html">Panel de fuentes</a> y el
      <a href="https://github.com/Marianomrz/ContextoWeb/blob/main/README.md#control-de-calidad-el-segundo-agente" target="_blank" rel="noopener noreferrer">detalle en el README</a>.</p>
      <div class="method-section">
        <h2 class="method-section-title">Por tipo de contenido</h2>
        ${Object.entries(byKind).map(([k, c]) =>
          barRow(KIND_LABELS[k] || k, c.aprobados, c.rechazados)).join('')}
      </div>`;

    if (Object.keys(catCounts).length) {
      html += `
      <div class="method-section">
        <h2 class="method-section-title">Noticias por categoría</h2>
        ${Object.entries(catCounts)
          .sort((a, b) => (b[1].aprobados + b[1].rechazados) - (a[1].aprobados + a[1].rechazados))
          .map(([cat, c]) => barRow(CATEGORY_LABELS[cat] || cat, c.aprobados, c.rechazados)).join('')}
      </div>`;
    }

    html += `<div class="method-section">
      <h2 class="method-section-title">Promedio por criterio de la rúbrica</h2>`;
    for (const [k, c] of Object.entries(byKind)) {
      const critEntries = Object.entries(c.scores);
      if (!critEntries.length) continue;
      html += `<h3 class="method-subtitle">${esc(KIND_LABELS[k] || k)}</h3>`;
      html += critEntries.map(([crit, vals]) => {
        const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
        return criterionRow(prettyCriterion(crit), avg);
      }).join('');
    }
    html += `</div>`;

    root.innerHTML = html;
  }

  fetch('qc_log.json', { cache: 'no-store' })
    .then(r => r.ok ? r.json() : { verdicts: [] })
    .then(data => render(Array.isArray(data.verdicts) ? data.verdicts : []))
    .catch(() => render([]));
})();
