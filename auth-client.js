/* CONTEXTO — Cliente de Auth compartido (Fase 2)
   ================================================
   Único punto donde se construye el AuthClient de @supabase/auth-js
   (vendoreada, ver la excepción al "sin SDK" en CLAUDE.md). Lo importan
   cuenta.js (página de cuenta) y favoritos.js (botones de guardar en
   portada/hemeroteca/páginas de artículo) — así la configuración de sesión
   (storageKey, PKCE) vive en un solo lugar y todas las páginas comparten
   la misma sesión. */

import { AuthClient } from './assets/vendor/auth-js-2.110.7.mjs';

// anon key pública a propósito (igual que en app.js/blog.js) — RLS manda.
export const SUPABASE_URL = 'https://lgprhvetnkucpttgpwxi.supabase.co';
export const SUPABASE_ANON_KEY = 'sb_publishable_adwmkWFs98Pr13WW9rJ28Q_tLA5HH6j';

export const auth = new AuthClient({
  url: `${SUPABASE_URL}/auth/v1`,
  headers: { apikey: SUPABASE_ANON_KEY },
  storageKey: 'contexto-auth',
  flowType: 'pkce',
  autoRefreshToken: true,
  persistSession: true,
  detectSessionInUrl: true,
});

// Cabeceras para hablar con PostgREST como el usuario logueado (REST puro,
// RLS decide) — `session` es el objeto que regresa auth.getSession().
export function restHeaders(session) {
  return {
    'apikey': SUPABASE_ANON_KEY,
    'Authorization': `Bearer ${session.access_token}`,
    'Content-Type': 'application/json',
  };
}
