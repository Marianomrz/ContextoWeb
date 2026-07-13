/* ==========================================================================
   CONTEXTO — app.js
   Carga artículos desde articles.json, renderiza tarjetas con espectro
   editorial, enfoque y contexto. Maneja filtros por categoría y nav móvil.
   ========================================================================== */

(function () {
  'use strict';

  // Supabase: URL y anon key SÍ pueden vivir literal en el JS — a
  // diferencia del correo de contacto (que se ofuscaba para que bots no lo
  // cosechen), el anon key está diseñado para ser público; la protección
  // real es RLS del lado del servidor (la tabla solo acepta INSERT desde
  // "anon", nunca SELECT/UPDATE). Mismos valores que en blog.js — si
  // cambias el proyecto de Supabase, actualiza los dos archivos.
  const SUPABASE_URL = 'https://lgprhvetnkucpttgpwxi.supabase.co';
  const SUPABASE_ANON_KEY = 'sb_publishable_adwmkWFs98Pr13WW9rJ28Q_tLA5HH6j';

  // marca que hay JS activo: los estados iniciales de los efectos de scroll
  // (elementos ocultos antes de revelarse) solo aplican bajo .js — sin
  // JavaScript todo el contenido es visible desde el primer render
  document.documentElement.classList.add('js');

  // ---------- utilidades ----------

  const $ = (sel, ctx = document) => ctx.querySelector(sel);
  const $$ = (sel, ctx = document) => Array.from(ctx.querySelectorAll(sel));

  const CATEGORY_LABELS = {
    politica: 'Política',
    economia: 'Economía',
    tecnologia: 'Tecnología',
    sociedad: 'Sociedad',
    internacional: 'Internacional',
    deportes: 'Deportes',
    literatura: 'Literatura',
  };

  // score de sesgo: -100 (izquierda) … 0 (centro) … +100 (derecha)
  function spectrumPercent(score) {
    const clamped = Math.max(-100, Math.min(100, Number(score) || 0));
    return ((clamped + 100) / 2).toFixed(1); // 0–100 %
  }

  function spectrumVerdict(score) {
    const s = Number(score) || 0;
    if (s <= -60) return { text: 'Marcadamente a la izquierda', cls: 'v-left' };
    if (s <= -25) return { text: 'Inclinada a la izquierda', cls: 'v-left' };
    if (s < 25)   return { text: 'Cerca del centro', cls: 'v-center' };
    if (s < 60)   return { text: 'Inclinada a la derecha', cls: 'v-right' };
    return { text: 'Marcadamente a la derecha', cls: 'v-right' };
  }

  function timeAgo(isoDate) {
    const then = new Date(isoDate);
    if (isNaN(then)) return '';
    const mins = Math.round((Date.now() - then.getTime()) / 60000);
    if (mins < 1) return 'ahora mismo';
    if (mins < 60) return `hace ${mins} min`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `hace ${hrs} h`;
    const days = Math.round(hrs / 24);
    if (days === 1) return 'ayer';
    if (days < 7) return `hace ${days} días`;
    return then.toLocaleDateString('es-MX', { day: 'numeric', month: 'short' });
  }

  function esc(str) {
    // escapa también comillas (revisión de seguridad 10 jul 2026): el truco
    // textContent->innerHTML solo codifica & < > — pero esc() se usa dentro
    // de atributos (href="...", datetime="..."), donde una comilla doble en
    // el dato rompería el atributo e inyectaría atributos arbitrarios.
    const d = document.createElement('div');
    d.textContent = String(str == null ? '' : str);
    return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // ---------- coberturas relacionadas (similitud de títulos) ----------

  const STOPWORDS = new Set([
    'para', 'como', 'sobre', 'entre', 'desde', 'hasta', 'contra', 'durante',
    'ante', 'tras', 'este', 'esta', 'estos', 'estas', 'aquel', 'aquella',
    'que', 'los', 'las', 'del', 'por', 'con', 'una', 'uno', 'unos', 'unas',
    'mas', 'pero', 'sus', 'ser', 'son', 'fue', 'han', 'hay', 'sin', 'segun',
    'nueva', 'nuevo', 'tres', 'anos', 'dias', 'tiene', 'sera', 'esto',
  ]);

  function titleTokens(title) {
    return new Set(
      String(title || '')
        .toLowerCase()
        .normalize('NFD').replace(/[̀-ͯ]/g, '')
        .replace(/[^a-z0-9ñ ]/g, ' ')
        .split(/\s+/)
        .filter(w => w.length > 3 && !STOPWORDS.has(w))
    );
  }

  function findRelated(article, all) {
    const base = titleTokens(article.title);
    if (!base.size) return [];
    return all
      .filter(b => b.id !== article.id)
      .map(b => ({ b, n: [...titleTokens(b.title)].filter(w => base.has(w)).length }))
      .filter(x => x.n >= 2)
      .sort((x, y) => y.n - x.n)
      .slice(0, 3)
      .map(x => x.b);
  }

  // ---------- reacciones personales (honestas: nunca inventan un conteo
  // global — solo recuerdan tu propia marca, mismo criterio de privacidad
  // y "sin servidor" que la dieta informativa) ----------

  const REACTIONS_KEY = 'contexto-reacciones';

  function loadReactions() {
    try { return JSON.parse(localStorage.getItem(REACTIONS_KEY)) || {}; }
    catch (_) { return {}; }
  }
  function saveReactions(state) {
    localStorage.setItem(REACTIONS_KEY, JSON.stringify(state));
  }

  function reactionsHTML(articleId) {
    if (!articleId) return '';
    return `
      <div class="article-reactions" data-article-id="${esc(articleId)}">
        <button type="button" class="reaction-btn" data-reaction="util">Me sirvió</button>
        <button type="button" class="reaction-btn" data-reaction="ya-sabia">Ya sabía esto</button>
      </div>`;
  }

  // vuelve a pintar el estado guardado sobre el DOM recién renderizado —
  // hay que llamarla después de cada renderFeed(), no solo una vez
  function applyReactionState() {
    const state = loadReactions();
    $$('.article-reactions').forEach(row => {
      const saved = state[row.dataset.articleId] || {};
      $$('.reaction-btn', row).forEach(btn => {
        btn.classList.toggle('is-picked', !!saved[btn.dataset.reaction]);
      });
    });
  }

  function initReactions() {
    $('#feed').addEventListener('click', (e) => {
      const btn = e.target.closest('.reaction-btn');
      if (!btn) return;
      const row = btn.closest('.article-reactions');
      const id = row.dataset.articleId;
      const state = loadReactions();
      state[id] = state[id] || {};
      state[id][btn.dataset.reaction] = !state[id][btn.dataset.reaction];
      saveReactions(state);
      btn.classList.toggle('is-picked', state[id][btn.dataset.reaction]);
    });
  }

  function relatedHTML(article, all) {
    const rel = findRelated(article, all);
    if (!rel.length) return '';
    const items = rel.map(r => `
      <a class="related-item" href="articulo/${esc(r.id)}.html">
        <span class="related-dot rd-${sideOf(r.bias_score)}" aria-hidden="true"></span>
        <span class="related-title">${esc(r.title)}</span>
        <small>· ${esc(r.source_name || 'fuente externa')}</small>
      </a>`).join('');
    return `
      <div class="related-block">
        <h3 class="analysis-col-title">Otras miradas a este tema</h3>
        <div class="related-list">${items}</div>
      </div>`;
  }

  // ---------- dieta informativa (medidor de burbuja, solo local) ----------

  const DIET_KEY = 'contexto-dieta';

  function sideOf(score) {
    const s = Number(score) || 0;
    return s <= -25 ? 'left' : s >= 25 ? 'right' : 'center';
  }

  function loadDiet() {
    try {
      return JSON.parse(localStorage.getItem(DIET_KEY)) ||
        { left: 0, center: 0, right: 0, dismissedAt: 0 };
    } catch (_) {
      return { left: 0, center: 0, right: 0, dismissedAt: 0 };
    }
  }

  function trackReading(card) {
    if (!card || card.dataset.counted || card.dataset.free === '1') return;
    card.dataset.counted = '1';
    const diet = loadDiet();
    diet[sideOf(card.dataset.bias)]++;
    localStorage.setItem(DIET_KEY, JSON.stringify(diet));
    maybeShowDietNudge(diet);
  }

  function maybeShowDietNudge(diet) {
    const total = diet.left + diet.center + diet.right;
    if (total < 5) return;
    if (Date.now() - (diet.dismissedAt || 0) < 7 * 24 * 3600 * 1000) return;
    if (document.querySelector('.diet-toast')) return;
    const labels = { left: 'la izquierda', right: 'la derecha' };
    for (const side of ['left', 'right']) {
      const share = diet[side] / total;
      if (share >= 0.7) {
        showDietToast(labels[side], Math.round(share * 100));
        return;
      }
    }
  }

  function showDietToast(sideText, pct) {
    const toast = document.createElement('div');
    toast.className = 'diet-toast';
    toast.setAttribute('role', 'status');
    toast.innerHTML = `
      <p><strong>Tu dieta informativa.</strong> El ${pct}% de tus últimas lecturas
      viene de coberturas inclinadas a ${esc(sideText)}. Ninguna mirada es completa
      sola — asomarte al otro lado ayuda a triangular.</p>
      <button class="diet-toast-btn" type="button">Entendido</button>`;
    document.body.appendChild(toast);
    toast.querySelector('button').addEventListener('click', () => {
      localStorage.setItem(DIET_KEY, JSON.stringify(
        { left: 0, center: 0, right: 0, dismissedAt: Date.now() }
      ));
      toast.remove();
    });
  }

  // ---------- render de una tarjeta ----------

  // tarjeta mínima para la columna lateral (secundarias 1-3): funciona como
  // un botón que lleva directo a la página completa de la nota — el
  // espectro, el análisis y las reacciones siguen existiendo, solo que ahí
  // (articulo/<id>.html), no repetidos en la portada
  function renderSideItem(a) {
    const catLabel = CATEGORY_LABELS[a.category] || a.category || 'General';
    return `
      <a class="side-item" data-category="${esc(a.category || '')}" href="articulo/${esc(a.id)}.html">
        <span class="side-item-art" aria-hidden="true"></span>
        <span class="side-item-body">
          <span class="side-item-kicker">${esc(catLabel)}</span>
          <span class="side-item-title">${esc(a.title)}</span>
        </span>
      </a>`;
  }

  // compact=true (grid parejo, índice 4+): tarjeta más chica — mismo
  // espectro y reacciones, pero sin el párrafo de razonamiento ni el
  // análisis desplegable (foco/contexto/relacionadas viven en la página
  // completa de la nota, no hace falta duplicarlos en cada tarjeta chica)
  function renderArticle(a, idx, compact) {
    const isFreePiece = a.editorial_pick === true;
    const isFeatured = idx === 0;
    const pct = spectrumPercent(a.bias_score);
    const verdict = spectrumVerdict(a.bias_score);
    const catLabel = CATEGORY_LABELS[a.category] || a.category || 'General';
    const score = Math.max(-100, Math.min(100, Number(a.bias_score) || 0));
    const scoreLabel = score > 0 ? `+${score}` : String(score);

    const chips = (a.focus_tags || [])
      .map(t => `<span class="focus-chip">${esc(t)}</span>`)
      .join('');

    const contextItems = (a.context || [])
      .map(c => `<li><strong>${esc(c.label)}:</strong> ${esc(c.text)}</li>`)
      .join('');

    const sourceLink = a.source_url
      ? `<a class="article-foot-btn" href="${esc(a.source_url)}" target="_blank" rel="noopener noreferrer">
           <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M14 4h6v6M20 4l-9 9M9 5H5a1 1 0 0 0-1 1v13a1 1 0 0 0 1 1h13a1 1 0 0 0 1-1v-4"/></svg>
           Leer nota original en ${esc(a.source_name || 'la fuente')}</a>`
      : '';

    // tarjetas compactas (grid parejo, índice 4+): solo encabezado + una
    // línea de contexto + pie con reacciones y fuente — el espectro, el
    // análisis y el trasfondo siguen existiendo tal cual, solo que viven en
    // la página completa de la nota (articulo/<id>.html, ver build_pages.py)
    // en vez de repetirse en cada tarjeta chica del feed. Toda la parte de
    // arriba (arte + encabezado + dek) es un solo enlace — el "botón
    // inteligente" que pidió el usuario — para no competir con el título
    // como único punto de entrada.
    const articleTop = compact ? `
      <a class="article-top article-top-link" href="articulo/${esc(a.id)}.html">
        <div class="article-art" aria-hidden="true"></div>
        <div class="article-head">
          <div class="article-meta-row">
            <span class="category-tag">${isFreePiece ? 'Mano libre · selección del día' : esc(catLabel)}</span>
          </div>
          <h2 class="article-title">${esc(a.title)}</h2>
          <p class="article-dek${isFreePiece ? ' is-quote' : ''}">${esc(a.summary)}</p>
        </div>
      </a>` : `
      <div class="article-top">
      <div class="article-art" aria-hidden="true">${isFeatured ? `<div class="sticky-note" aria-hidden="true">no te la<br>pierdas ↴</div>` : ''}</div>
      <div class="article-head">
        <div class="article-meta-row">
          <span class="category-tag">${esc(catLabel)}</span>
          <time datetime="${esc(a.published_at || '')}">${esc(timeAgo(a.published_at))}</time>
          <span class="source-name">· vía ${esc(a.source_name || 'fuente externa')}</span>
        </div>
        <h2 class="article-title">${a.id
          ? `<a href="articulo/${esc(a.id)}.html">${esc(a.title)}</a>`
          : esc(a.title)}</h2>
        <p class="article-dek">${esc(a.summary)}</p>
      </div>
      </div>`;

    const body = compact ? `
      <div class="article-foot compact-foot">
        ${reactionsHTML(a.id)}
        <span class="source-name-plain">${isFreePiece ? 'Redacción del agente' : esc(a.source_name || 'Fuente externa')}</span>
      </div>` : `
      ${isFreePiece ? `
      <div class="spectrum-block free-piece-block">
        <div class="spectrum-label-row">
          <span class="spectrum-label">Pieza de mano libre</span>
          <span class="free-piece-badge">Selección del día · redacción del agente</span>
        </div>
        <p class="spectrum-why">Esta pieza no analiza la cobertura de un medio: es una recomendación o ensayo breve escrito directamente por nuestro agente editorial. Aquí no hay espectro que medir — hay un punto de vista, y lo asumimos como propio.</p>
      </div>` : `
      <div class="spectrum-block">
        <div class="spectrum-label-row">
          <span class="spectrum-label">Espectro editorial de esta cobertura</span>
          <span class="spectrum-verdict ${verdict.cls}">${verdict.text}</span>
        </div>
        <div class="spectrum-track-wrap">
          <div class="spectrum-track" role="img"
               aria-label="Posición de la cobertura en el espectro: ${verdict.text} (${scoreLabel} de -100 a +100)">
            <div class="spectrum-marker" data-target="${pct}" data-score="${scoreLabel}"></div>
          </div>
          <div class="spectrum-ticks" aria-hidden="true">
            <span>Izquierda</span><span>Centro</span><span>Derecha</span>
          </div>
        </div>
        ${a.bias_reason ? `<p class="spectrum-why">${esc(a.bias_reason)}</p>` : ''}
      </div>`}

      ${reactionsHTML(a.id)}

      <button class="analysis-toggle" aria-expanded="${isFeatured}">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>
        <span class="analysis-toggle-label">${isFeatured ? 'Ocultar análisis' : 'Análisis y contexto'}</span>
      </button>

      <div class="analysis-wrap${isFeatured ? ' is-open' : ''}">
      <div class="analysis-wrap-inner">
      <div class="article-analysis">
        <div class="analysis-col">
          <h3 class="analysis-col-title">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.5"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22"/></svg>
            ${isFreePiece ? 'Por qué lo elegimos hoy' : 'Con qué foco se cuenta'}
          </h3>
          <p>${esc(a.focus_analysis || '')}</p>
          ${chips ? `<div class="focus-chip-row">${chips}</div>` : ''}
        </div>
        <div class="analysis-col">
          <h3 class="analysis-col-title">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M4 19V5a1 1 0 0 1 1-1h6v16H5a1 1 0 0 1-1-1zM11 4h8a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-8"/></svg>
            ${isFreePiece ? 'Para llegar más lejos' : 'Contexto y trasfondo'}
          </h3>
          <ul class="context-list">${contextItems}</ul>
        </div>
      </div>
      ${relatedHTML(a, ARTICLES)}
      </div>
      </div>

      <div class="article-foot">
        ${sourceLink}
        <span class="confidence-note">
          <span class="agent-avatar" aria-hidden="true"></span>${isFreePiece ? 'Redacción propia del agente' : `Análisis editorial · confianza ${esc(a.confidence || 'media')}`}
        </span>
      </div>`;

    return `
    <article class="article-card${isFeatured ? ' is-featured' : ''}${compact ? ' is-compact' : ''}"
             data-category="${esc(a.category || '')}"
             data-bias="${score}" data-free="${isFreePiece ? 1 : 0}"
             style="--stagger:${Math.min(idx || 0, 8)}">
      ${articleTop}
      ${body}
    </article>`;
  }

  // ---------- estado y filtros ----------

  let ARTICLES = [];
  let currentCategory = 'todas';
  let currentQuery = '';

  function matchesQuery(a, q) {
    if (!q) return true;
    const haystack = [
      a.title, a.summary, a.source_name, a.focus_analysis,
      ...(a.focus_tags || []),
    ].filter(Boolean).join(' ').toLowerCase();
    return haystack.includes(q);
  }

  // se llama al cambiar de sección (nav) — conserva la búsqueda activa
  function applyFilter(filter) {
    currentCategory = filter;
    renderFeed();
  }

  function renderFeed() {
    const feed = $('#feed');
    const empty = $('#feedEmpty');
    const q = currentQuery.trim().toLowerCase();

    let list = currentCategory === 'todas'
      ? ARTICLES
      : ARTICLES.filter(a => a.category === currentCategory);
    list = list.filter(a => matchesQuery(a, q));

    // ordenar de más reciente a más antigua
    list.sort((x, y) => new Date(y.published_at) - new Date(x.published_at));

    // jerarquía real de portada (no solo una tarjeta destacada suelta en un
    // grid parejo): destacada + hasta 3 secundarias en columna lateral
    // compacta, y el resto en grid — misma agrupación que el mockup v3
    // aprobado. Los índices que recibe renderArticle() no cambian (0, 1..3,
    // 4+), así que is-featured/is-secondary siguen funcionando igual.
    const hero = list[0];
    const secondaries = list.slice(1, 4);
    const rest = list.slice(4);
    let html = '';
    if (hero) {
      const heroHTML = renderArticle(hero, 0);
      html += secondaries.length
        ? `<div class="feed-front">
             ${heroHTML}
             <div class="feed-side">${secondaries.map(renderSideItem).join('')}</div>
           </div>`
        : heroHTML;
    }
    if (rest.length) {
      html += `<div class="feed-grid">${rest.map((a, i) => renderArticle(a, i + 4, true)).join('')}</div>`;
    }
    feed.innerHTML = html;
    empty.hidden = list.length > 0;
    empty.textContent = q
      ? `No hay notas que coincidan con «${currentQuery.trim()}». Prueba otra palabra.`
      : 'No hay notas en esta sección todavía. Prueba con otra categoría.';
    animateSpectrums();
    applyReactionState();

    const count = $('#searchCount');
    if (count) {
      if (q) {
        count.hidden = false;
        count.textContent = `${list.length} resultado${list.length === 1 ? '' : 's'}`;
      } else {
        count.hidden = true;
      }
    }
  }

  // búsqueda instantánea: filtra sin llamadas a red, respeta la categoría activa
  function initSearch() {
    const input = $('#searchInput');
    const clearBtn = $('#searchClear');
    const hint = $('#searchHint');
    if (!input) return;

    const updateHint = () => {
      if (!hint) return;
      hint.hidden = document.activeElement === input || input.value.length > 0;
    };

    input.addEventListener('input', () => {
      currentQuery = input.value;
      clearBtn.hidden = currentQuery.length === 0;
      updateHint();
      renderFeed();
    });
    input.addEventListener('focus', updateHint);
    input.addEventListener('blur', updateHint);
    clearBtn.addEventListener('click', () => {
      input.value = '';
      currentQuery = '';
      clearBtn.hidden = true;
      updateHint();
      renderFeed();
      input.focus();
    });

    // atajo "/" para saltar directo al buscador (como GitHub, Linear, etc.)
    document.addEventListener('keydown', (e) => {
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
      const tag = document.activeElement && document.activeElement.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || document.activeElement?.isContentEditable) return;
      e.preventDefault();
      input.focus();
    });
  }

  // calcula el offset en px para centrar el marcador en un punto 0-100 de su
  // pista (ya resta la mitad del propio ancho) — la aritmética vive en JS
  // porque mezclar % con variables numéricas en calc() para translateX() es
  // frágil entre motores; lecturas agrupadas antes que escrituras, para no
  // forzar un reflow por marcador
  function markerOffsetPx(trackW, markerW, pct) {
    return (trackW * pct / 100) - (markerW / 2);
  }

  function measureSpectrumTracks() {
    const markers = $$('.spectrum-marker[data-target]');
    const rects = markers.map(m => ({
      trackW: m.parentElement.getBoundingClientRect().width,
      markerW: m.getBoundingClientRect().width,
    }));
    markers.forEach((m, i) => {
      m.style.setProperty('--marker-x', `${markerOffsetPx(rects[i].trackW, rects[i].markerW, 50)}px`);
    });
    return markers.map((m, i) => ({ m, ...rects[i] }));
  }

  // los marcadores nacen en el centro y viajan a su posición real
  // (setTimeout en vez de rAF: no depende del pipeline de render) — animar
  // por "transform" en vez de "left" evita relayout en cada tecla de la
  // búsqueda, que re-renderiza las tarjetas en cada keystroke
  function animateSpectrums() {
    const measured = measureSpectrumTracks();
    setTimeout(() => {
      measured.forEach(({ m, trackW, markerW }) => {
        const pct = Number(m.dataset.target);
        m.style.setProperty('--marker-x', `${markerOffsetPx(trackW, markerW, pct)}px`);
      });
    }, 60);
  }

  // plegar/desplegar análisis (delegado: las tarjetas se re-renderizan);
  // abrir el análisis o salir a la fuente cuenta para la dieta informativa
  function initAnalysisToggles() {
    $('#feed').addEventListener('click', (e) => {
      const foot = e.target.closest('.article-foot-btn');
      if (foot) {
        trackReading(foot.closest('.article-card'));
        return; // dejar que el enlace navegue
      }
      const btn = e.target.closest('.analysis-toggle');
      if (!btn) return;
      const wrap = btn.nextElementSibling;
      const open = wrap.classList.toggle('is-open');
      btn.setAttribute('aria-expanded', String(open));
      btn.querySelector('.analysis-toggle-label').textContent =
        open ? 'Ocultar análisis' : 'Análisis y contexto';
      if (open) trackReading(btn.closest('.article-card'));
    });
  }

  // ---------- skeleton de carga ----------

  function skeletonHTML(n) {
    let out = '';
    for (let i = 0; i < n; i++) {
      out += `
      <div class="skeleton-card${i === 0 ? ' is-featured' : ''}" aria-hidden="true">
        <div class="sk-band"></div>
        <div class="sk-body">
          <div class="sk-line sk-tag"></div>
          <div class="sk-line sk-title"></div>
          <div class="sk-line"></div>
          <div class="sk-line sk-short"></div>
        </div>
      </div>`;
    }
    return `<div class="feed-grid">${out}</div>`;
  }

  // tema: oscuro es el default del portal; claro es la variante elegida
  function initTheme() {
    const saved = localStorage.getItem('contexto-theme');
    if (saved === 'dark' || saved === 'light') {
      document.documentElement.dataset.theme = saved;
    }
    const toggle = $('#themeToggle');
    if (!toggle) return;
    toggle.addEventListener('click', () => {
      const root = document.documentElement;
      const isDark = root.dataset.theme !== 'light';
      root.dataset.theme = isDark ? 'light' : 'dark';
      localStorage.setItem('contexto-theme', root.dataset.theme);
    });
  }

  function initNav() {
    $$('.nav-pill[data-filter]').forEach(btn => {
      btn.addEventListener('click', () => {
        $$('.nav-pill').forEach(b => b.classList.remove('is-active'));
        btn.classList.add('is-active');
        applyFilter(btn.dataset.filter);
        // cerrar menú móvil tras elegir
        $('#mainNav').classList.remove('is-open');
        $('#navToggle').setAttribute('aria-expanded', 'false');
      });
    });

    const toggle = $('#navToggle');
    toggle.addEventListener('click', () => {
      const nav = $('#mainNav');
      const open = nav.classList.toggle('is-open');
      toggle.setAttribute('aria-expanded', String(open));
    });
  }

  function initDate() {
    const texto = new Date().toLocaleDateString('es-MX', {
      weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
    });
    const el = $('#fecha-hoy');
    if (el) el.textContent = texto;
    const elPortada = $('#fecha-portada');
    if (elPortada) elPortada.textContent = texto;
  }

  // ---------- termómetro del día ----------

  function renderThermometer(all) {
    const el = $('#thermometer');
    if (!el) return;
    const newsOnly = all.filter(a => !a.editorial_pick && a.bias_score != null);
    if (!newsOnly.length) { el.innerHTML = ''; return; }

    const today = new Date().toISOString().slice(0, 10);
    let pool = newsOnly.filter(a => String(a.published_at || '').slice(0, 10) === today);
    let scope = 'de hoy';
    if (pool.length < 2) { pool = newsOnly.slice(0, 12); scope = 'más recientes'; }

    const scores = pool.map(a => Math.max(-100, Math.min(100, Number(a.bias_score) || 0)));
    const avg = scores.reduce((s, x) => s + x, 0) / scores.length;
    const variance = scores.reduce((s, x) => s + (x - avg) ** 2, 0) / scores.length;
    const spread = Math.sqrt(variance);
    const spreadText = spread >= 45
      ? 'con bastante dispersión: hubo coberturas marcadamente a la izquierda y a la derecha'
      : spread >= 20
      ? 'con dispersión moderada entre las distintas coberturas'
      : 'con coberturas bastante parejas entre sí';

    const pct = spectrumPercent(avg);
    const verdict = spectrumVerdict(avg);

    el.innerHTML = `
      <div class="thermo-card">
        <div class="thermo-head">
          <span class="thermo-eyebrow">Termómetro editorial · notas ${scope}</span>
          <span class="spectrum-verdict ${verdict.cls}">${esc(verdict.text)}</span>
        </div>
        <div class="spectrum-track-wrap">
          <div class="spectrum-track" role="img" aria-label="Promedio de la cobertura: ${esc(verdict.text)}">
            <div class="spectrum-marker" data-target="${pct}"></div>
          </div>
          <div class="spectrum-ticks" aria-hidden="true">
            <span>Izquierda</span><span>Centro</span><span>Derecha</span>
          </div>
        </div>
        <p class="thermo-note">Promedio de ${scores.length} nota${scores.length === 1 ? '' : 's'} analizada${scores.length === 1 ? '' : 's'}, ${spreadText}.</p>
      </div>`;
    // el posicionamiento del marcador lo hace animateSpectrums() (llamada
    // por applyFilter() justo después de renderThermometer() en
    // loadArticles()) — ese mismo código ya centra correctamente cualquier
    // .spectrum-marker[data-target] del documento vía --marker-x. Este
    // termómetro tenía ADEMÁS su propio bloque que fijaba "left" a mano con
    // el porcentaje crudo (sin restar la mitad del ancho del marcador): las
    // dos posiciones se sumaban (left + transform) y la perilla terminaba
    // fuera de la pista. Se quitó ese bloque duplicado — un solo sistema de
    // posicionamiento para todos los marcadores del sitio.
  }

  // ---------- mini-brújula arrastrable (teaser de brujula.html) ----------

  function initMiniCompass() {
    const slider = $('#miniSlider');
    const dot = $('#miniSliderDot');
    const go = $('#miniCompassGo');
    if (!slider || !dot) return;
    let dragging = false;

    function setDot(clientX) {
      const rect = slider.getBoundingClientRect();
      let pct = ((clientX - rect.left) / rect.width) * 100;
      pct = Math.max(0, Math.min(100, pct));
      dot.style.left = `${pct}%`;
      slider.setAttribute('aria-valuenow', Math.round(pct));
      if (go) {
        const texto = pct < 35 ? 'Te ubicas a la izquierda'
          : pct > 65 ? 'Te ubicas a la derecha'
          : 'Te ubicas cerca del centro';
        go.textContent = `${texto} — hacer el quiz completo →`;
      }
    }

    slider.addEventListener('pointerdown', (e) => {
      dragging = true;
      slider.setPointerCapture(e.pointerId);
      setDot(e.clientX);
    });
    slider.addEventListener('pointermove', (e) => { if (dragging) setDot(e.clientX); });
    slider.addEventListener('pointerup', () => { dragging = false; });
    slider.addEventListener('keydown', (e) => {
      const rect = slider.getBoundingClientRect();
      const current = parseFloat(dot.style.left) || 50;
      if (e.key === 'ArrowLeft') setDot(rect.left + rect.width * Math.max(0, current - 5) / 100);
      if (e.key === 'ArrowRight') setDot(rect.left + rect.width * Math.min(100, current + 5) / 100);
    });
  }

  // ---------- carrusel "para seguir leyendo" ----------
  // Descubrimiento cruzado de categorías: siempre el resto más reciente del
  // portal completo, sin importar el filtro activo en el feed principal.

  function renderCarousel(all) {
    const section = $('#carouselSection');
    const track = $('#carousel');
    if (!section || !track) return;
    const sorted = all
      .filter(a => !a.editorial_pick)
      .slice()
      .sort((x, y) => new Date(y.published_at) - new Date(x.published_at));
    // se salta las primeras 4 (destacada + secundarias, ya visibles arriba)
    const picks = sorted.slice(4, 10);
    if (!picks.length) { section.hidden = true; return; }
    section.hidden = false;
    track.innerHTML = picks.map(a => `
      <a class="mini-card" data-category="${esc(a.category || '')}" href="articulo/${esc(a.id)}.html">
        <span class="mini-card-kicker">${esc(CATEGORY_LABELS[a.category] || a.category || 'General')}</span>
        <span class="mini-card-title">${esc(a.title)}</span>
      </a>`).join('');
  }

  // ---------- reseñas reales ("Correo del lector") ----------
  // Se cargan desde testimonios.json, publicado por agent/resenas.py tras
  // pasar por moderación (fail-closed). Sin reseñas todavía, se muestra un
  // estado vacío honesto en vez de testimonios de ejemplo.

  function renderLetters(testimonios) {
    const grid = $('#lettersGrid');
    const sub = $('#lettersSub');
    if (!grid) return;
    if (!testimonios.length) {
      grid.innerHTML = `<p class="feed-empty">Todavía no hay reseñas publicadas — sé quien deje la primera.</p>`;
      if (sub) sub.textContent = 'Cuando alguien escriba, este espacio será suyo.';
      return;
    }
    if (sub) sub.textContent = 'Reseñas reales de lectores, revisadas por el consejo editorial antes de publicarse.';
    grid.innerHTML = testimonios.map(t => `
      <figure class="letter">
        <blockquote>${esc(t.texto)}</blockquote>
        <figcaption>— ${esc(t.nombre)}${t.ocupacion ? ` · ${esc(t.ocupacion)}` : ''}</figcaption>
      </figure>`).join('');
  }

  async function loadLetters() {
    try {
      const res = await fetch('testimonios.json', { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderLetters(Array.isArray(data.testimonios) ? data.testimonios : []);
    } catch (err) {
      console.warn('No se pudo cargar testimonios.json', err);
      renderLetters([]);
    }
  }

  // envío de la reseña: inserta directo en Supabase (resena_submissions,
  // status='pending'); agent/resenas.py lo recoge de ahí en el siguiente
  // ciclo de moderación. Antes esto abría un mailto: y alguien copiaba el
  // texto a mano — mismo cambio que blog.js hizo para la Revista Jurídica.
  function initReviewSubmit() {
    const form = $('#reviewForm');
    if (!form) return;
    const status = $('#reviewFormStatus');
    const submitBtn = $('#reviewSubmit');

    function showStatus(msg, ok) {
      status.textContent = msg;
      status.hidden = false;
      status.classList.toggle('is-ok', ok);
      status.classList.toggle('is-error', !ok);
    }

    form.addEventListener('submit', async (e) => {
      e.preventDefault();

      // honeypot: ver la misma explicación en blog.js
      const honeypot = form.querySelector('[name="website"]');
      if (honeypot && honeypot.value) {
        form.reset();
        showStatus('Gracias — tu reseña quedó en dictamen editorial.', true);
        return;
      }

      const nombre = form.querySelector('#reviewNombre').value.trim();
      const ocupacion = form.querySelector('#reviewOcupacion').value.trim();
      const texto = form.querySelector('#reviewTexto').value.trim();
      if (!nombre || !texto) {
        showStatus('Falta tu nombre o el texto de la reseña.', false);
        return;
      }

      submitBtn.disabled = true;
      submitBtn.textContent = 'Enviando…';
      try {
        const resp = await fetch(`${SUPABASE_URL}/rest/v1/resena_submissions`, {
          method: 'POST',
          headers: {
            'apikey': SUPABASE_ANON_KEY,
            'Authorization': `Bearer ${SUPABASE_ANON_KEY}`,
            'Content-Type': 'application/json',
            'Prefer': 'return=minimal',
          },
          body: JSON.stringify({ nombre, ocupacion, texto }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        form.reset();
        showStatus('¡Gracias! Tu reseña quedó en dictamen editorial — si se aprueba, la verás en esta misma sección.', true);
      } catch (err) {
        showStatus('No se pudo enviar tu reseña. Inténtalo de nuevo en unos minutos.', false);
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = '✉ Dejar mi reseña';
      }
    });
  }

  // ---------- carga de datos ----------

  async function loadArticles() {
    $('#feed').innerHTML = skeletonHTML(4);
    try {
      const res = await fetch('articles.json', { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      ARTICLES = Array.isArray(data.articles) ? data.articles : [];
    } catch (err) {
      console.warn('No se pudo cargar articles.json, usando datos embebidos.', err);
      ARTICLES = window.__FALLBACK_ARTICLES__ || [];
    }
    renderThermometer(ARTICLES);
    renderCarousel(ARTICLES);
    applyFilter('todas');
  }

  // ---------- efectos de scroll (hero, revelados, metodología anclada) ----------

  function initScrollFX() {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    // revelado de secciones al entrar en pantalla
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('in-view');
          io.unobserve(entry.target);
        }
      });
    }, { rootMargin: '0px 0px -10% 0px' });
    $$('.reveal').forEach((el) => io.observe(el));

    // la secuencia de la metodología solo corre en escritorio
    const howTrack = $('#howScroll');
    const isDesktop = window.matchMedia('(min-width: 861px)').matches;
    if (howTrack && isDesktop) {
      $('.how-grid', howTrack).classList.add('how-seq');
    }

    // ---- título de portada: viaja y se encoge hasta el masthead ----
    // Un solo elemento (#coverBrand, no un clon) que se mueve de su lugar
    // centrado en la portada hasta el hueco de .masthead-title, midiendo
    // ambas posiciones reales en vez de suponer coordenadas fijas — así se
    // adapta solo a cualquier tamaño de pantalla (ver mismo criterio ya
    // probado en el demo de propuesta, julio 2026).
    const coverBrand = $('#coverBrand');
    const coverBrandSpacer = $('.cover-brand-spacer');
    const mastheadTitle = $('.masthead-title');
    let brandStart = null;
    let brandTarget = null;

    function measureBrandTravel() {
      if (!coverBrand || !mastheadTitle) return;
      // en celular la mecánica fija está desactivada (ver fixedCoverSupported
      // más abajo y el CSS @media max-width:640px) — no hace falta medir nada
      if (!fixedCoverSupported()) return;
      // #coverBrand ya es position:fixed en este punto (la clase .js se
      // aplica antes de que corra este script), así que medir su propio
      // getBoundingClientRect() da su posición fixed actual, no su lugar
      // "de reposo" en la portada. Antes esto se resolvía pasándolo a
      // position:static un instante y midiéndolo ahí — pero .cover-brand
      // -spacer (el div invisible que existe justo para reservarle el
      // hueco) seguía ocupando su propio espacio en el flujo mientras
      // tanto, así que el #coverBrand "estático" se medía DESPUÉS del
      // spacer, no encima de él: quedaba ~76px más abajo de lo real y
      // terminaba encimado con el eslogan. El spacer ya tiene exactamente
      // el tamaño/tipografía/margen de #coverBrand — hay que medir a ÉL
      // directamente, no reconstruir su posición con un truco aparte.
      const s = coverBrandSpacer
        ? coverBrandSpacer.getBoundingClientRect()
        : coverBrand.getBoundingClientRect();
      const cs = getComputedStyle(coverBrand);
      brandStart = { top: s.top, left: s.left, fontSize: parseFloat(cs.fontSize) };

      const m = mastheadTitle.getBoundingClientRect();
      const mcs = getComputedStyle(mastheadTitle);
      const docTop = m.top + window.scrollY;
      brandTarget = {
        top: docTop - window.innerHeight, // dónde caería si scrollY === coverH
        left: m.left,
        fontSize: parseFloat(mcs.fontSize),
      };
    }

    function lerp(a, b, p) { return a + (b - a) * p; }
    function clamp01(x) { return Math.min(1, Math.max(0, x)); }

    // scroll: cortina de portada, glow del hero y secuencia de pasos.
    // Corre directo en cada evento (el navegador ya los alinea a los frames
    // y el trabajo es barato); sin rAF para no depender del pipeline de render.
    const root = document.documentElement;
    const cover = $('#portada');
    // la portada fija + título viajero dependen de que window.innerHeight
    // sea estable durante el scroll — en celular no lo es: Safari/Chrome
    // móvil oculta y muestra la barra de direcciones EN PLENO gesto de
    // scroll, cambiando el alto visible a medio cálculo. Eso desincroniza
    // scrollY/coverH y se traducía en pantalla trabada (la portada se
    // queda fija tapando todo) o un hueco en blanco al volver a subir.
    // En vez de perseguir ese blanco móvil, la mecánica fija se desactiva
    // en viewports angostos (CSS: ver @media max-width:640px cerca de
    // .js .cover) y aquí solo dejamos de tocar top/left/font-size — el
    // mismo respaldo que ya existe para prefers-reduced-motion.
    const fixedCoverSupported = () => window.matchMedia('(min-width: 641px)').matches;
    function onScroll() {
      // la portada se desvanece mientras la edición la cubre
      const coverH = cover ? window.innerHeight : 0;
      let cp = 0;
      if (cover) {
        cp = clamp01(window.scrollY / coverH);
        root.style.setProperty('--cover-p', cp.toFixed(3));
        cover.classList.toggle('is-passed', cp > 0.98);
      }

      if (fixedCoverSupported() && coverBrand && mastheadTitle && brandStart && brandTarget) {
        const ep = 1 - Math.pow(1 - cp, 2); // easing de salida, menos mecánico
        coverBrand.style.top = lerp(brandStart.top, brandTarget.top, ep) + 'px';
        coverBrand.style.left = lerp(brandStart.left, brandTarget.left, ep) + 'px';
        coverBrand.style.fontSize = lerp(brandStart.fontSize, brandTarget.fontSize, ep) + 'px';

        // crossfade continuo (85%→95% del recorrido, con margen antes del
        // 98% donde .is-passed oculta la portada): la suma de las dos
        // opacidades siempre da 1, nunca hay un instante sin el título.
        const crossP = clamp01((cp - 0.85) / 0.10);
        coverBrand.style.opacity = String(1 - crossP);
        mastheadTitle.style.opacity = String(crossP);
      }

      // el glow del masthead arranca cuando la edición ya es visible
      const p = clamp01((window.scrollY - coverH) / 320);
      root.style.setProperty('--hero-p', p.toFixed(3));

      if (howTrack && isDesktop) {
        const rect = howTrack.getBoundingClientRect();
        const total = rect.height - window.innerHeight;
        const prog = total > 0 ? clamp01(-rect.top / total) : 1;
        $$('.how-card', howTrack).forEach((card, i) => {
          card.classList.toggle('is-lit', prog >= (i + 0.35) / 3);
        });
      }
    }
    measureBrandTravel();
    document.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', () => { measureBrandTravel(); onScroll(); });
    onScroll();

    // al volver a esta página (botón atrás desde una nota, restaurada desde
    // bfcache o no) el navegador repone tu posición de scroll, pero no
    // siempre dispara un evento "scroll" a tiempo — sin eso, .cover (fijo,
    // opaco, cubre toda la pantalla) nunca recibe la clase que lo oculta
    // y se queda tapando el feed: la página se siente "trabada" en la
    // portada aunque el contenido real ya esté ahí debajo. "pageshow"
    // corre siempre (carga nueva o restaurada desde bfcache) después de
    // que el navegador ya repuso el scroll, así que forzamos un recálculo.
    window.addEventListener('pageshow', () => { measureBrandTravel(); onScroll(); });
  }

  // spotlight: las superficies de vidrio responden a la posición del cursor;
  // la destacada además recibe una leve inclinación 3D (toque táctil)
  function initSpotlight() {
    if (window.matchMedia('(hover: none)').matches) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    let raf = null;
    document.addEventListener('pointermove', (e) => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = null;
        const card = e.target.closest && e.target.closest('.article-card, .how-card');
        if (!card) return;
        const rect = card.getBoundingClientRect();
        card.style.setProperty('--mx', `${e.clientX - rect.left}px`);
        card.style.setProperty('--my', `${e.clientY - rect.top}px`);

        if (card.classList.contains('is-featured')) {
          // incluye el mismo translateY(-4px) que ya aplica .article-card:hover
          // por CSS — el estilo inline lo pisaría si no lo repetimos aquí
          const px = (e.clientX - rect.left) / rect.width - 0.5;
          const py = (e.clientY - rect.top) / rect.height - 0.5;
          card.style.transform = `perspective(1200px) rotateY(${px * 2.2}deg) rotateX(${-py * 2.2}deg) translateY(-4px)`;
        }
      });
    }, { passive: true });

    document.addEventListener('pointerleave', (e) => {
      const card = e.target.closest && e.target.closest('.article-card.is-featured');
      if (card) card.style.transform = '';
    }, { passive: true, capture: true });
  }

  document.addEventListener('DOMContentLoaded', () => {
    initDate();
    initNav();
    initTheme();
    initAnalysisToggles();
    initReactions();
    initMiniCompass();
    initScrollFX();
    initSpotlight();
    initSearch();
    initReviewSubmit();
    loadArticles();
    loadLetters();
  });
})();
