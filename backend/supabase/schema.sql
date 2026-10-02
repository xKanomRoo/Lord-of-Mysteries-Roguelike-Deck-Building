-- Player-owned cloud backup only. This is not an authoritative game economy.
-- Run once in your own Supabase project's SQL Editor as the project owner.
begin;

create table public.cloud_saves (
    user_id uuid primary key references auth.users(id) on delete cascade,
    schema_version integer not null default 1 check (schema_version = 1),
    revision integer not null default 1 check (revision between 1 and 2147483647),
    payload jsonb not null check (
        jsonb_typeof(payload) = 'object'
        and octet_length(payload::text) <= 131072
    ),
    updated_at timestamptz not null default now()
);

create function public.guard_cloud_save_revision()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if tg_op = 'INSERT' then
        if new.revision <> 1 then
            raise exception 'initial cloud save revision must be 1';
        end if;
    else
        if new.user_id <> old.user_id or new.schema_version <> old.schema_version then
            raise exception 'cloud save owner and schema cannot change';
        end if;
        if old.revision = 2147483647 or new.revision <> old.revision + 1 then
            raise exception 'cloud save revision must increase by one';
        end if;
    end if;
    new.updated_at := now();
    return new;
end;
$$;

create trigger cloud_saves_revision_guard
before insert or update on public.cloud_saves
for each row execute function public.guard_cloud_save_revision();

alter table public.cloud_saves enable row level security;

create policy cloud_saves_read_own on public.cloud_saves
for select to authenticated
using ((select auth.uid()) = user_id);

create policy cloud_saves_insert_own on public.cloud_saves
for insert to authenticated
with check ((select auth.uid()) = user_id and revision = 1);

create policy cloud_saves_update_own on public.cloud_saves
for update to authenticated
using ((select auth.uid()) = user_id)
with check ((select auth.uid()) = user_id);

-- No public access, deletes, client timestamps or client-controlled ownership.
revoke all on public.cloud_saves from anon, authenticated;
grant select on public.cloud_saves to authenticated;
grant insert (user_id, schema_version, revision, payload)
    on public.cloud_saves to authenticated;
grant update (revision, payload) on public.cloud_saves to authenticated;
revoke all on function public.guard_cloud_save_revision() from public, anon, authenticated;

commit;
