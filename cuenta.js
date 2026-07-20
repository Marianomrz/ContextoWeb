/* CONTEXTO — Mi cuenta (Fase 1: magic link + perfil)
   ====================================================
   Única excepción al "sin SDK" del proyecto: Auth usa la librería oficial
   @supabase/auth-js (vendoreada en assets/vendor/, versión pinneada) porque
   manejar JWT/refresh/PKCE a mano es donde nacen los bugs de seguridad
   reales. Todo lo demás (perfil hoy; favoritos/likes en fases futuras)
   sigue siendo REST puro contra PostgREST, con la anon key pública + el JWT
   del usuario — la protección real es RLS del lado del servidor. */

import { AuthClient } from './assets/vendor/auth-js-2.110.7.mjs';

(function () {
  'use strict';

  const SUPABASE_URL = 'https://lgprhvetnkucpttgpwxi.supabase.co';
  // anon key pública a propósito (igual que en app.js/blog.js) — RLS manda.
  const SUPABASE_ANON_KEY = 'sb_publishable_adwmkWFs98Pr13WW9rJ28Q_tLA5HH6j';
  // Site key de Cloudflare Turnstile (pública, como toda site key).
  const TURNSTILE_SITE_KEY = '0x4AAAAAAD5YgHCOLMGTJT2r';

  const auth = new AuthClient({
    url: `${SUPABASE_URL}/auth/v1`,
    headers: { apikey: SUPABASE_ANON_KEY },
    storageKey: 'contexto-auth',
    flowType: 'pkce',
    autoRefreshToken: true,
    persistSession: true,
    detectSessionInUrl: true,
  });

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

  function restHeaders(session) {
    // REST puro contra PostgREST: anon key + JWT del usuario. RLS decide.
    return {
      'apikey': SUPABASE_ANON_KEY,
      'Authorization': `Bearer ${session.access_token}`,
      'Content-Type': 'application/json',
    };
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
    } else {
      show(loginSection);
      mountTurnstile();
    }
  }

  async function main() {
    initLogin();
    initPrefs();
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
