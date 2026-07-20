/* CONTEXTO — Mi cuenta (Fase 1: magic link + perfil)
   ====================================================
   Única excepción al "sin SDK" del proyecto: Auth usa la librería oficial
   @supabase/auth-js (vendoreada en assets/vendor/, versión pinneada) porque
   manejar JWT/refresh/PKCE a mano es donde nacen los bugs de seguridad
   reales. Todo lo demás (perfil hoy; favoritos/likes en fases futuras)
   sigue siendo REST puro contra PostgREST, con la anon key pública + el JWT
   del usuario — la protección real es RLS del lado del servidor. */

// el AuthClient y las cabeceras REST viven en auth-client.js desde la
// Fase 2 — mismo cliente y misma sesión que favoritos.js
import { auth, SUPABASE_URL, restHeaders } from './auth-client.js';

(function () {
  'use strict';

  // Site key de Cloudflare Turnstile (pública, como toda site key).
  const TURNSTILE_SITE_KEY = '0x4AAAAAAD5YgHCOLMGTJT2r';

  const $ = (sel) => document.querySelector(sel);
  const loading = $('#accountLoading');
  const loginSection = $('#loginSection');
  const sentSection = $('#sentSection');
  const profileSection = $('#profileSection');

  let turnstileWidgetId = null;
  let turnstileToken = null;

  function showStatus(el, msg, ok) {
    el.textContent = msg;
    el.hidden = false;
    el.classList.toggle('is-ok', !!ok);
    el.classList.toggle('is-error', !ok);
  }

  function show(section) {
    loading.hidden = true;
    for (const el of [loginSection, sentSection, profileSection]) {
      el.hidden = el !== section;
    }
  }

  // ---------- Turnstile ----------

  function mountTurnstile() {
    const box = $('#turnstileBox');
    if (!box || turnstileWidgetId !== null) return;
    if (TURNSTILE_SITE_KEY.startsWith('PENDIENTE')) {
      // aún sin widget creado en Cloudflare: se envía sin token y el
      // servidor decide (con CAPTCHA activo en Supabase, rechazará).
      console.warn('Turnstile sin configurar: falta la site key.');
      return;
    }
    let tries = 0;
    const timer = setInterval(() => {
      tries += 1;
      if (window.turnstile) {
        clearInterval(timer);
        turnstileWidgetId = window.turnstile.render(box, {
          sitekey: TURNSTILE_SITE_KEY,
          theme: document.documentElement.dataset.theme === 'light' ? 'light' : 'dark',
          callback: (token) => { turnstileToken = token; },
          'expired-callback': () => { turnstileToken = null; },
        });
      } else if (tries > 50) {
        clearInterval(timer);
        showStatus($('#loginStatus'),
          'No cargó la verificación anti-bots. Recarga la página o revisa tu bloqueador.', false);
      }
    }, 100);
  }

  function resetTurnstile() {
    turnstileToken = null;
    if (turnstileWidgetId !== null && window.turnstile) {
      window.turnstile.reset(turnstileWidgetId);
    }
  }

  // ---------- entrar con enlace mágico ----------

  function initLogin() {
    const form = $('#loginForm');
    const status = $('#loginStatus');
    const submitBtn = $('#loginSubmit');

    form.addEventListener('submit', async (e) => {
      e.preventDefault();

      // honeypot: ver la misma explicación en blog.js
      const honeypot = form.querySelector('[name="website"]');
      if (honeypot && honeypot.value) {
        form.reset();
        showStatus(status, 'Listo — revisa tu correo.', true);
        return;
      }

      const email = $('#loginEmail').value.trim();
      if (!email || !email.includes('@')) {
        showStatus(status, 'Escribe un correo válido.', false);
        return;
      }

      submitBtn.disabled = true;
      submitBtn.textContent = 'Enviando…';
      try {
        const { error } = await auth.signInWithOtp({
          email,
          options: {
            emailRedirectTo: window.location.origin + window.location.pathname,
            captchaToken: turnstileToken || undefined,
          },
        });
        if (error) throw error;
        $('#sentEmail').textContent = email;
        show(sentSection);
        status.hidden = true;
      } catch (err) {
        const msg = /captcha/i.test(String(err && err.message))
          ? 'La verificación anti-bots no pasó. Complétala e intenta de nuevo.'
          : 'No se pudo enviar el enlace. Espera un momento e intenta de nuevo.';
        showStatus(status, msg, false);
      } finally {
        resetTurnstile();
        submitBtn.disabled = false;
        submitBtn.textContent = '✉ Mandarme el enlace';
      }
    });

    $('#sentRetry').addEventListener('click', () => {
      show(loginSection);
      mountTurnstile();
    });
  }

  // ---------- perfil (REST puro, RLS decide) ----------

  async function loadProfile(session) {
    $('#profileEmail').textContent = session.user.email || '';
    const check = $('#newsletterCheck');
    check.disabled = true;
    try {
      const resp = await fetch(
        `${SUPABASE_URL}/rest/v1/profiles?select=newsletter&user_id=eq.${session.user.id}`,
        { headers: restHeaders(session) }
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const rows = await resp.json();
      check.checked = !!(rows[0] && rows[0].newsletter);
    } catch (err) {
      console.warn('No se pudo leer el perfil', err);
    } finally {
      check.disabled = false;
    }
  }

  function initPrefs() {
    const check = $('#newsletterCheck');
    const status = $('#prefStatus');
    check.addEventListener('change', async () => {
      const session = (await auth.getSession()).data.session;
      if (!session) return;
      const wanted = check.checked;
      check.disabled = true;
      try {
        const resp = await fetch(
          `${SUPABASE_URL}/rest/v1/profiles?user_id=eq.${session.user.id}`,
          {
            method: 'PATCH',
            headers: { ...restHeaders(session), 'Prefer': 'return=minimal' },
            body: JSON.stringify({ newsletter: wanted }),
          }
        );
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        showStatus(status, 'Preferencia guardada.', true);
      } catch (err) {
        check.checked = !wanted;
        showStatus(status, 'No se pudo guardar. Intenta de nuevo.', false);
      } finally {
        check.disabled = false;
      }
    });
  }

  // ---------- mis favoritos (Fase 2; REST puro, RLS decide) ----------

  async function articleIndex() {
    // id → {title, category} desde los JSON públicos del sitio; la
    // hemeroteca cubre notas que ya salieron de la portada. Si un JSON
    // falla, se sigue con lo que haya — el favorito se lista igual con
    // título de respaldo.
    const map = new Map();
    for (const src of ['hemeroteca.json', 'articles.json']) {
      try {
        const data = await fetch(src, { cache: 'no-store' }).then(r => r.json());
        for (const a of (data.articles || [])) {
          if (a.id) map.set(a.id, a);
        }
      } catch (err) {
        console.warn(`No se pudo leer ${src}`, err);
      }
    }
    return map;
  }

  async function loadFavorites(session) {
    const status = $('#favsStatus');
    const list = $('#favList');
    status.hidden = false;
    status.textContent = 'Cargando tus notas guardadas…';
    list.innerHTML = '';
    try {
      const resp = await fetch(
        `${SUPABASE_URL}/rest/v1/favoritos?select=article_id,created_at&order=created_at.desc`,
        { headers: restHeaders(session) }
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const favs = await resp.json();
      if (!favs.length) {
        status.textContent = 'Aún no guardas ninguna nota. Usa el botón "Guardar" en las tarjetas de la portada, en la hemeroteca o en la página de cualquier nota.';
        return;
      }
      const index = await articleIndex();
      status.hidden = true;
      for (const f of favs) {
        const a = index.get(f.article_id);
        const li = document.createElement('li');
        li.className = 'fav-item';
        const link = document.createElement('a');
        link.href = `articulo/${encodeURIComponent(f.article_id)}.html`;
        link.textContent = a ? a.title : `Nota archivada (${f.article_id})`;
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'account-secondary fav-remove';
        btn.dataset.unfav = f.article_id;
        btn.textContent = 'Quitar';
        li.append(link, btn);
        list.appendChild(li);
      }
    } catch (err) {
      console.warn('No se pudieron cargar los favoritos', err);
      status.textContent = 'No se pudieron cargar tus favoritos. Recarga la página para reintentar.';
    }
  }

  function initFavorites() {
    $('#favList').addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-unfav]');
      if (!btn) return;
      const session = (await auth.getSession()).data.session;
      if (!session) return;
      btn.disabled = true;
      try {
        const resp = await fetch(
          `${SUPABASE_URL}/rest/v1/favoritos?article_id=eq.${encodeURIComponent(btn.dataset.unfav)}`,
          { method: 'DELETE', headers: restHeaders(session) }
        );
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        btn.closest('li').remove();
        if (!$('#favList').children.length) {
          const status = $('#favsStatus');
          status.hidden = false;
          status.textContent = 'Aún no guardas ninguna nota. Usa el botón "Guardar" en las tarjetas de la portada, en la hemeroteca o en la página de cualquier nota.';
        }
      } catch (err) {
        console.warn('No se pudo quitar el favorito', err);
        btn.disabled = false;
      }
    });
  }

  // ---------- cerrar sesión y borrar cuenta ----------

  function initSessionActions() {
    $('#logoutBtn').addEventListener('click', async () => {
      await auth.signOut();
      show(loginSection);
      mountTurnstile();
    });

    const confirmBox = $('#deleteConfirmBox');
    $('#deleteAskBtn').addEventListener('click', () => { confirmBox.hidden = false; });
    $('#deleteCancelBtn').addEventListener('click', () => { confirmBox.hidden = true; });

    $('#deleteConfirmBtn').addEventListener('click', async () => {
      const status = $('#deleteStatus');
      const session = (await auth.getSession()).data.session;
      if (!session) return;
      const btn = $('#deleteConfirmBtn');
      btn.disabled = true;
      try {
        const resp = await fetch(`${SUPABASE_URL}/rest/v1/rpc/delete_own_account`, {
          method: 'POST',
          headers: restHeaders(session),
          body: '{}',
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        // la cuenta ya no existe en el servidor; limpiar la sesión local
        await auth.signOut({ scope: 'local' }).catch(() => {});
        confirmBox.hidden = true;
        show(loginSection);
        mountTurnstile();
        showStatus($('#loginStatus'), 'Tu cuenta y sus datos quedaron borrados. Gracias por habernos leído.', true);
      } catch (err) {
        showStatus(status, 'No se pudo borrar la cuenta. Intenta de nuevo en unos minutos.', false);
        btn.disabled = false;
      }
    });
  }

  // ---------- arranque ----------

  async function render(session) {
    if (session) {
      show(profileSection);
      await loadProfile(session);
      await loadFavorites(session);
    } else {
      show(loginSection);
      mountTurnstile();
    }
  }

  async function main() {
    initLogin();
    initPrefs();
    initFavorites();
    initSessionActions();

    // getSession espera a que auth-js procese el ?code= del enlace mágico
    // (PKCE) si venimos de dar clic en el correo.
    const { data: { session } } = await auth.getSession();

    // limpiar el ?code= de la URL después del intercambio
    if (window.location.search.includes('code=')) {
      window.history.replaceState({}, '', window.location.pathname);
    }

    await render(session);

    auth.onAuthStateChange((event, newSession) => {
      if (event === 'SIGNED_IN') render(newSession);
      if (event === 'SIGNED_OUT') render(null);
    });
  }

  main();
})();
