-- CONTEXTO — Fase 1: cuentas de usuario (magic link + perfil)
-- =============================================================
-- Se corre UNA vez en el SQL Editor de Supabase. Queda commiteado aquí como
-- registro reproducible de la estructura, igual que las tablas de envíos
-- (jur_submissions / resena_submissions) quedaron documentadas en CLAUDE.md.
--
-- Principios de seguridad de esta fase (no negociables):
--   * Nada de service_role: todo se resuelve con anon key + RLS + el JWT del
--     usuario logueado.
--   * El user_id de cada fila lo pone el servidor (auth.uid() vía trigger o
--     WITH CHECK), nunca el body que mande el cliente.
--   * Estos datos viven SOLO en Supabase — jamás se vuelcan a un JSON
--     estático del repo.

-- ---------------------------------------------------------------
-- Tabla de perfiles: exactamente una fila por usuario registrado.
-- La crea el trigger handle_new_user() al registrarse; el cliente solo
-- puede leerla y actualizar su preferencia de boletín.
-- ---------------------------------------------------------------
create table if not exists public.profiles (
  user_id    uuid primary key references auth.users (id) on delete cascade,
  newsletter boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

-- SELECT: cada quien ve solo su propia fila. Sin política para anon:
-- una petición sin sesión no ve nada.
create policy "profiles_select_own" on public.profiles
  for select to authenticated
  using (user_id = (select auth.uid()));

-- UPDATE: solo la fila propia, y el WITH CHECK impide "regalar" la fila
-- reasignando user_id a otra cuenta.
create policy "profiles_update_own" on public.profiles
  for update to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

-- INSERT de respaldo por si el trigger no corrió (no debería pasar):
-- solo puede insertarse la fila propia.
create policy "profiles_insert_own" on public.profiles
  for insert to authenticated
  with check (user_id = (select auth.uid()));

-- Sin política de DELETE: el perfil solo desaparece por CASCADE cuando se
-- borra la cuenta completa (delete_own_account, abajo).

-- updated_at automático en cada UPDATE.
create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists profiles_touch_updated_at on public.profiles;
create trigger profiles_touch_updated_at
  before update on public.profiles
  for each row execute function public.touch_updated_at();

-- ---------------------------------------------------------------
-- Trigger de alta: al crearse un usuario en auth.users, nace su perfil.
-- SECURITY DEFINER porque el rol del usuario nuevo no tiene (ni debe
-- tener) permiso de escribir perfiles arbitrarios — el user_id sale de
-- new.id del propio registro de auth, nunca del cliente.
-- ---------------------------------------------------------------
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = ''
as $$
begin
  insert into public.profiles (user_id) values (new.id)
  on conflict (user_id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------
-- Borrado de cuenta self-service (LFPDPPP: derecho de cancelación).
-- SECURITY DEFINER: el privilegio de borrar en auth.users vive en esta
-- función de la base, no en ninguna key — el frontend la invoca vía
-- /rest/v1/rpc/delete_own_account con el JWT del usuario y solo puede
-- borrar SU propia cuenta (auth.uid()). El ON DELETE CASCADE arrastra el
-- perfil y, en fases futuras, favoritos y votos.
-- ---------------------------------------------------------------
create or replace function public.delete_own_account()
returns void
language plpgsql
security definer set search_path = ''
as $$
begin
  if auth.uid() is null then
    raise exception 'Se requiere sesión para borrar la cuenta';
  end if;
  delete from auth.users where id = auth.uid();
end;
$$;

-- Solo usuarios logueados pueden ejecutarla; anon ni la ve.
revoke all on function public.delete_own_account() from public, anon;
grant execute on function public.delete_own_account() to authenticated;
