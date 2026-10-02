-- Local PostgreSQL fixture only. NEVER run this in a live Supabase project.
-- psql -X -v ON_ERROR_STOP=1 -f backend/supabase/test_local.sql test_database
-- This creates mock auth roles/users, then rolls back the complete fixture.
\set ON_ERROR_STOP on
begin;
create role anon nologin;
create role authenticated nologin;
create schema auth;
create table auth.users (id uuid primary key);
create function auth.uid() returns uuid language sql stable as
    'select nullif(current_setting(''request.jwt.claim.sub'', true), '''')::uuid';
grant usage on schema auth to anon, authenticated;
grant execute on function auth.uid() to anon, authenticated;
insert into auth.users values
    ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'),
    ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');

-- Strip only transaction wrappers when replaying the production schema here.
-- psql includes the file exactly; its nested BEGIN/COMMIT would commit fixtures.
-- The runner supplies a schema-without-wrappers file via this variable.
\i :schema_fixture_path

create function pg_temp.check_fixture(value boolean, label text)
returns void language plpgsql as $$
begin
    if value is distinct from true then
        raise exception 'fixture failed: %', label;
    end if;
    raise notice 'PASS: %', label;
end;
$$;

set role anon;
do $$
begin
    begin
        perform * from public.cloud_saves;
        raise exception 'anonymous read unexpectedly allowed';
    exception when insufficient_privilege then
        raise notice 'PASS: anonymous cannot read';
    end;
    begin
        insert into public.cloud_saves(user_id, payload)
        values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', '{}'::jsonb);
        raise exception 'anonymous insert unexpectedly allowed';
    exception when insufficient_privilege then
        raise notice 'PASS: anonymous cannot insert';
    end;
end;
$$;

reset role;
set role authenticated;
select set_config('request.jwt.claim.sub', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', false);
insert into public.cloud_saves(user_id, schema_version, revision, payload)
values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 1, 1, '{"fixture":"A"}'::jsonb);
select pg_temp.check_fixture((select count(*) = 1 from public.cloud_saves), 'owner reads own backup');
select pg_temp.check_fixture((select revision = 1 from public.cloud_saves), 'initial revision is one');

select set_config('request.jwt.claim.sub', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', false);
select pg_temp.check_fixture((select count(*) = 0 from public.cloud_saves), 'other account cannot read owner backup');
do $$
declare affected integer;
begin
    begin
        insert into public.cloud_saves(user_id, schema_version, revision, payload)
        values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 1, 1, '{}'::jsonb);
        raise exception 'forged owner unexpectedly allowed';
    exception when insufficient_privilege then
        raise notice 'PASS: forged owner insert denied';
    end;
    update public.cloud_saves set revision = 2, payload = '{"fixture":"forged"}'::jsonb
    where user_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' and revision = 1;
    get diagnostics affected = row_count;
    perform pg_temp.check_fixture(affected = 0, 'other account cannot modify owner backup');
end;
$$;
insert into public.cloud_saves(user_id, payload)
values ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', '{"fixture":"B"}'::jsonb);
select pg_temp.check_fixture((select count(*) = 1 from public.cloud_saves), 'second account reads only its own backup');

select set_config('request.jwt.claim.sub', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', false);
do $$
declare affected integer;
begin
    update public.cloud_saves set revision = 2, payload = '{"fixture":"A2"}'::jsonb
    where user_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' and revision = 1;
    get diagnostics affected = row_count;
    perform pg_temp.check_fixture(affected = 1, 'matching expected revision updates once');
    update public.cloud_saves set revision = 2, payload = '{"fixture":"stale"}'::jsonb
    where user_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' and revision = 1;
    get diagnostics affected = row_count;
    perform pg_temp.check_fixture(affected = 0, 'stale revision update changes nothing');
    perform pg_temp.check_fixture((select payload->>'fixture' = 'A2' from public.cloud_saves), 'stale writer preserves new backup');
    begin
        update public.cloud_saves set revision = 7;
        raise exception 'skipped revision unexpectedly allowed';
    exception when raise_exception then
        if sqlerrm = 'skipped revision unexpectedly allowed' then raise; end if;
        perform pg_temp.check_fixture(sqlerrm = 'cloud save revision must increase by one', 'revision trigger rejects skipped revision');
    end;
    begin
        update public.cloud_saves set user_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
        raise exception 'owner update unexpectedly allowed';
    exception when insufficient_privilege then
        raise notice 'PASS: owner column update denied';
    end;
    begin
        update public.cloud_saves set updated_at = '2000-01-01';
        raise exception 'timestamp update unexpectedly allowed';
    exception when insufficient_privilege then
        raise notice 'PASS: client timestamp update denied';
    end;
    begin
        delete from public.cloud_saves;
        raise exception 'delete unexpectedly allowed';
    exception when insufficient_privilege then
        raise notice 'PASS: client delete denied';
    end;
    begin
        update public.cloud_saves set revision = 3, payload = jsonb_build_object('huge', repeat('x', 131073));
        raise exception 'oversized payload unexpectedly allowed';
    exception when check_violation then
        raise notice 'PASS: oversized server payload denied';
    end;
    begin
        update public.cloud_saves set revision = 3, payload = '[]'::jsonb;
        raise exception 'array payload unexpectedly allowed';
    exception when check_violation then
        raise notice 'PASS: non-object server payload denied';
    end;
end;
$$;
select pg_temp.check_fixture((select revision = 2 from public.cloud_saves), 'failed writes preserve revision');
reset role;
rollback;
