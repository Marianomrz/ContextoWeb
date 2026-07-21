-- CONTEXTO — Fase 2b: secciones preferidas del boletín
-- ======================================================
-- Se corre UNA vez en el SQL Editor, después de fase1-cuentas.sql.
-- Solo CAPTURA la preferencia — el job que arme y mande el correo no
-- existe todavía (bloqueado hasta decidir proveedor de email).
--
-- Semántica del arreglo (opt-out, no opt-in):
--   * '{}' (default) = TODAS las categorías — quien nunca toca el filtro
--     no se queda sin nada.
--   * ['politica','deportes'] = solo esas secciones.
--
-- REGLA DE ORO (para la lógica futura de envío, dejada escrita desde hoy):
--   este arreglo NUNCA dispara un envío por sí solo. Cualquier job de
--   newsletter debe revisar SIEMPRE newsletter = true JUNTO con el
--   arreglo — el arreglo filtra el contenido de quien YA se suscribió,
--   jamás decide a quién se le manda. Nota para ese futuro job: leerá las
--   preferencias de todos los suscritos con la service_role key del lado
--   del servidor (igual que juridica.py/resenas.py) — eso es el uso
--   correcto de esa key, no una excepción a evitar.

alter table public.profiles
  add column if not exists newsletter_categorias text[] not null default '{}';

-- El CHECK no confía en el frontend: solo admite los 7 valores válidos y
-- máximo 7 entradas. DEBE COINCIDIR con VALID_CATEGORIES en
-- agent/agent.py — son dos fuentes de verdad sincronizadas A MANO; si el
-- agente gana o pierde una categoría, hay que soltar y recrear este
-- constraint en el mismo cambio.
alter table public.profiles
  drop constraint if exists profiles_newsletter_categorias_check;
alter table public.profiles
  add constraint profiles_newsletter_categorias_check check (
    cardinality(newsletter_categorias) <= 7
    and newsletter_categorias <@ array[
      'politica', 'economia', 'tecnologia', 'sociedad',
      'internacional', 'deportes', 'literatura'
    ]::text[]
  );

-- RLS: nada nuevo que hacer — las políticas de profiles (fase 1) son por
-- fila, así que la columna nueva queda cubierta: cada quien lee y escribe
-- solo su propio filtro, esté o no visible en la UI.
