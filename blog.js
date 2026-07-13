/* ==========================================================================
   CONTEXTO — blog.js (Revista Jurídica)
   Carga blog.json y lista los artículos publicados. Independiente de
   app.js porque las páginas estáticas no cargan ese script.
   ========================================================================== */

(function () {
  'use strict';

  // Supabase: URL y anon key SÍ pueden vivir literal en el JS — a
  // diferencia del correo de contacto (que se ofuscaba para que bots no lo
  // cosechen), el anon key está diseñado para ser público; la protección
  // real es RLS del lado del servidor (la tabla solo acepta INSERT desde
  // "anon", nunca SELECT/UPDATE — ver el SQL en el plan de este cambio).
  // Reemplaza estos dos valores por los de tu proyecto de Supabase.
  const SUPABASE_URL = 'https://lgprhvetnkucpttgpwxi.supabase.co';
  const SUPABASE_ANON_KEY = 'sb_publishable_adwmkWFs98Pr13WW9rJ28Q_tLA5HH6j';

  // respetar el tema elegido en la portada
  const saved = localStorage.getItem('contexto-theme');
  if (saved === 'dark' || saved === 'light') {
    document.documentElement.dataset.theme = saved;
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

  function fecha(iso) {
    const d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleDateString('es-MX', {
      day: 'numeric', month: 'long', year: 'numeric',
    });
  }

  function render(entries) {
    const list = document.getElementById('jurList');
    if (!entries.length) {
      list.innerHTML = '<p class="feed-empty">Aún no hay artículos publicados. ' +
        'Los primeros textos están en dictamen editorial.</p>';
      return;
    }
    list.innerHTML = entries.map(a => `
      <a class="jur-card" href="revista/${esc(a.id)}.html">
        <div class="jur-card-meta">
          <span>${esc(a.author)}</span>
          <span>·</span>
          <time datetime="${esc(a.published_at || '')}">${esc(fecha(a.published_at))}</time>
          <span>·</span>
          <span>${parseInt(a.minutos_lectura, 10) || 1} min</span>
        </div>
        <h3>${esc(a.title)}</h3>
        <p>${esc(a.summary)}</p>
        <div class="focus-chip-row">
          ${(a.areas || []).map(t => `<span class="focus-chip">${esc(t)}</span>`).join('')}
        </div>
      </a>`).join('');
  }

  fetch('blog.json', { cache: 'no-store' })
    .then(r => r.ok ? r.json() : { articles: [] })
    .then(data => render(Array.isArray(data.articles) ? data.articles : []))
    .catch(() => render([]));

  // envío del artículo: inserta directo en Supabase (jur_submissions,
  // status='pending'); agent/juridica.py lo recoge de ahí en el siguiente
  // ciclo de moderación. Antes esto abría un mailto: y alguien copiaba el
  // texto a mano — ver CLAUDE.md para el porqué del cambio.
  const form = document.getElementById('jurForm');
  if (form) {
    const status = document.getElementById('jurFormStatus');
    const submitBtn = document.getElementById('jurSubmit');

    function showStatus(msg, ok) {
      status.textContent = msg;
      status.hidden = false;
      status.classList.toggle('is-ok', ok);
      status.classList.toggle('is-error', !ok);
    }

    form.addEventListener('submit', async (e) => {
      e.preventDefault();

      // honeypot: un humano nunca llena este campo (está oculto por CSS);
      // si trae contenido, es un bot — se descarta en silencio, sin llamar
      // a Supabase, pero mostrando el mismo mensaje de éxito para no
      // revelarle al bot que fue detectado
      const honeypot = form.querySelector('[name="website"]');
      if (honeypot && honeypot.value) {
        form.reset();
        showStatus('Gracias — tu artículo quedó en dictamen editorial.', true);
        return;
      }

      const titulo = form.querySelector('#jurTitulo').value.trim();
      const autor = form.querySelector('#jurAutor').value.trim();
      const cuerpo = form.querySelector('#jurCuerpo').value.trim();
      if (!titulo || !autor || !cuerpo) {
        showStatus('Falta el título, tu nombre o el texto del artículo.', false);
        return;
      }

      submitBtn.disabled = true;
      submitBtn.textContent = 'Enviando…';
      try {
        const resp = await fetch(`${SUPABASE_URL}/rest/v1/jur_submissions`, {
          method: 'POST',
          headers: {
            'apikey': SUPABASE_ANON_KEY,
            'Authorization': `Bearer ${SUPABASE_ANON_KEY}`,
            'Content-Type': 'application/json',
            'Prefer': 'return=minimal',
          },
          body: JSON.stringify({ titulo, autor, body_md: cuerpo }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        form.reset();
        showStatus('¡Gracias! Tu artículo quedó en dictamen editorial — recibirás el veredicto aquí mismo cuando esté listo.', true);
      } catch (err) {
        showStatus('No se pudo enviar tu artículo. Inténtalo de nuevo en unos minutos.', false);
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = '✉ Enviar mi artículo';
      }
    });
  }
})();
