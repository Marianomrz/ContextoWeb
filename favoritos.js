/* CONTEXTO — Favoritos (Fase 2)
   ===============================
   Botones de guardar/quitar nota, vinculados al usuario logueado. Lo cargan
   index.html, hemeroteca.html y las páginas generadas de articulo/ (ver
   build_pages.py). Los renderers solo pintan botones con `data-fav="<id>"`;
   este módulo les pone estado y comportamiento.

   Todo es REST puro contra PostgREST (tabla `favoritos`, RLS solo-lo-propio,
   user_id lo pone el servidor con DEFAULT auth.uid()) — auth-js solo aporta
   la sesión. Sin sesión, el clic lleva a cuenta.html.

   Los renderers dinámicos (app.js, hemeroteca.js) avisan tras cada render
   con `document.dispatchEvent(new CustomEvent('contexto:fav-rendered'))`
   para que los botones nuevos reciban su estado. */

import { auth, SUPABASE_URL, restHeaders } from './auth-client.js';

// rutas absolutas al sitio calculadas desde la URL de ESTE módulo (que vive
// en la raíz) — así el mismo archivo funciona cargado desde /articulo/.
const CUENTA_URL = new URL('cuenta.html', import.meta.url).href;

let session = null;
let favSet = new Set();

function favButtons() {
  return document.querySelectorAll('[data-fav]');
}

function decorate() {
  favButtons().forEach((btn) => {
    const saved = favSet.has(btn.dataset.fav);
    btn.classList.toggle('is-saved', saved);
    btn.setAttribute('aria-pressed', saved ? 'true' : 'false');
    btn.title = session
      ? (saved ? 'Quitar de mis favoritos' : 'Guardar en mis favoritos')
      : 'Inicia sesión para guardar favoritos';
    const label = btn.querySelector('.fav-label');
    if (label) label.textContent = saved ? 'Guardada' : 'Guardar';
  });
}

async function loadFavs() {
  if (!session) { favSet = new Set(); return; }
  try {
    const resp = await fetch(`${SUPABASE_URL}/rest/v1/favoritos?select=article_id`, {
      headers: restHeaders(session),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    favSet = new Set((await resp.json()).map((r) => r.article_id));
  } catch (err) {
    console.warn('No se pudieron cargar los favoritos', err);
    favSet = new Set();
  }
}

async function toggle(btn) {
  const id = btn.dataset.fav;
  const wasSaved = favSet.has(id);
  // optimista: pintar ya, revertir si el servidor dice que no
  if (wasSaved) favSet.delete(id); else favSet.add(id);
  decorate();
  try {
    const resp = wasSaved
      ? await fetch(`${SUPABASE_URL}/rest/v1/favoritos?article_id=eq.${encodeURIComponent(id)}`, {
          method: 'DELETE',
          headers: restHeaders(session),
        })
      : await fetch(`${SUPABASE_URL}/rest/v1/favoritos?on_conflict=user_id,article_id`, {
          method: 'POST',
          headers: { ...restHeaders(session), 'Prefer': 'resolution=ignore-duplicates,return=minimal' },
          // user_id NO va en el body: lo pone el DEFAULT auth.uid() del servidor
          body: JSON.stringify({ article_id: id }),
        });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  } catch (err) {
    console.warn('No se pudo actualizar el favorito', err);
    if (wasSaved) favSet.add(id); else favSet.delete(id);
    decorate();
  }
}

document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-fav]');
  if (!btn) return;
  e.preventDefault();
  if (!session) { window.location.href = CUENTA_URL; return; }
  toggle(btn);
});

document.addEventListener('contexto:fav-rendered', decorate);

async function init() {
  session = (await auth.getSession()).data.session;
  await loadFavs();
  decorate();
  auth.onAuthStateChange(async (_event, newSession) => {
    session = newSession;
    await loadFavs();
    decorate();
  });
}

init();

// por si algún script clásico quiere forzar un repintado
window.contextoFav = { refresh: decorate };
