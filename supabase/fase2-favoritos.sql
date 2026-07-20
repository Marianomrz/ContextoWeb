-- CONTEXTO — Fase 2: favoritos por usuario
-- ==========================================
-- Se corre UNA vez en el SQL Editor de Supabase, después de
-- fase1-cuentas.sql. Mismos principios que la fase 1: anon key + RLS + JWT
-- del usuario (nada de service_role), user_id siempre del lado del
-- servidor, datos solo en Supabase (jamás volcados a un JSON del repo).

-- Una fila por (usuario, nota guardada). article_id es el `id` de
-- articles.json / hemeroteca.json (hex corto, ver contrato en CLAUDE.md);
-- el CHECK evita basura arbitraria sin acoplarse al formato exacto.
create table if not exists public.favoritos (
  user_id    uuid not null default auth.uid()
             references auth.users (id) on delete cascade,
  article_id text not null
             check (char_length(article_id) between 1 and 64),
  created_at timestamptz not null default now(),
  primary key (user_id, article_id)
);

alter table public.favoritos enable row level security;

-- Cada quien ve, guarda y quita SOLO sus propias filas. Sin política para
-- anon: una petición sin sesión no ve ni toca nada. Sin UPDATE: un
-- favorito solo existe o no existe.
create policy "favoritos_select_own" on public.favoritos
  for select to authenticated
  using (user_id = (select auth.uid()));

create policy "favoritos_insert_own" on public.favoritos
  for insert to authenticated
  with check (user_id = (select auth.uid()));

create policy "favoritos_delete_own" on public.favoritos
  for delete to authenticated
  using (user_id = (select auth.uid()));

-- El DELETE CASCADE desde auth.users ya cubre el borrado de cuenta de la
-- fase 1: borrar la cuenta arrastra sus favoritos, sin tocar
-- delete_own_account().
