begin;

create extension if not exists pgtap with schema extensions;

select plan(19);

select ok(
  (
    select bool_and(c.relrowsecurity)
    from pg_catalog.pg_class as c
    join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relname = any (
        array[
          'libraries',
          'articles',
          'article_assets',
          'annotations',
          'projects',
          'project_articles',
          'jobs'
        ]
      )
  ),
  'RLS is enabled on every client-visible synced table'
);

select is(
  (
    select count(*)::integer
    from pg_catalog.pg_policies
    where schemaname = 'public'
      and tablename = 'libraries'
      and roles = array['authenticated']::name[]
  ),
  4,
  'libraries has explicit select, insert, update, and delete policies'
);

select is(
  (
    select count(*)::integer
    from pg_catalog.pg_policies
    where schemaname = 'storage'
      and tablename = 'objects'
      and policyname like 'library_pdfs_%'
      and roles = array['authenticated']::name[]
  ),
  4,
  'the private PDF bucket has four owner-scoped policies'
);

select isnt(
  has_table_privilege('anon', 'public.libraries', 'select'),
  true,
  'anonymous callers do not have table privileges'
);

select ok(
  has_table_privilege('service_role', 'public.articles', 'select'),
  'server-side workers retain explicit access to synced records'
);

insert into auth.users (id, email)
values
  ('11111111-1111-4111-8111-111111111111', 'owner-a@example.test'),
  ('22222222-2222-4222-8222-222222222222', 'owner-b@example.test');

insert into storage.objects (bucket_id, name, owner)
values
  (
    'library-pdfs',
    '11111111-1111-4111-8111-111111111111/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/a.pdf',
    '11111111-1111-4111-8111-111111111111'
  ),
  (
    'library-pdfs',
    '22222222-2222-4222-8222-222222222222/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/b.pdf',
    '22222222-2222-4222-8222-222222222222'
  );

set local role authenticated;
select set_config(
  'request.jwt.claim.sub',
  '11111111-1111-4111-8111-111111111111',
  true
);
select set_config(
  'request.jwt.claims',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated"}',
  true
);

select is(
  auth.uid(),
  '11111111-1111-4111-8111-111111111111'::uuid,
  'the test request is authenticated as owner A'
);

select lives_ok(
  $$
    insert into public.libraries (id, owner_id, name)
    values (
      'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      '11111111-1111-4111-8111-111111111111',
      'Owner A library'
    )
  $$,
  'owner A can create their own library'
);

select lives_ok(
  $$
    insert into public.articles (id, library_id, owner_id, title)
    values (
      'a1111111-1111-4111-8111-111111111111',
      'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      '11111111-1111-4111-8111-111111111111',
      'Owner A paper'
    )
  $$,
  'owner A can create an article in their own library'
);

select lives_ok(
  $$
    insert into storage.objects (bucket_id, name, owner)
    values (
      'library-pdfs',
      '11111111-1111-4111-8111-111111111111/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/client-upload.pdf',
      '11111111-1111-4111-8111-111111111111'
    )
  $$,
  'owner A can create an object below their account and library prefix'
);

select throws_ok(
  $$
    insert into storage.objects (bucket_id, name, owner)
    values (
      'library-pdfs',
      '11111111-1111-4111-8111-111111111111/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/cross-library.pdf',
      '11111111-1111-4111-8111-111111111111'
    )
  $$,
  '42501',
  null,
  'owner A cannot create an object below another library prefix'
);

select throws_ok(
  $$
    insert into public.libraries (id, owner_id, name)
    values (
      'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      '22222222-2222-4222-8222-222222222222',
      'Impersonated library'
    )
  $$,
  '42501',
  null,
  'owner A cannot create records for owner B'
);

select is(
  (select count(*) from storage.objects where bucket_id = 'library-pdfs'),
  2::bigint,
  'owner A sees only PDFs below their own storage prefix'
);

reset role;
set local role authenticated;
select set_config(
  'request.jwt.claim.sub',
  '22222222-2222-4222-8222-222222222222',
  true
);
select set_config(
  'request.jwt.claims',
  '{"sub":"22222222-2222-4222-8222-222222222222","role":"authenticated"}',
  true
);

select lives_ok(
  $$
    insert into public.libraries (id, owner_id, name)
    values (
      'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      '22222222-2222-4222-8222-222222222222',
      'Owner B library'
    )
  $$,
  'owner B can create their own library'
);

select is(
  (select count(*) from public.libraries),
  1::bigint,
  'owner B sees only their own library record'
);

select is(
  (select count(*) from public.articles),
  0::bigint,
  'owner B cannot read owner A articles'
);

select is_empty(
  $$
    update public.articles
    set title = 'Changed by owner B'
    where id = 'a1111111-1111-4111-8111-111111111111'
    returning id
  $$,
  'owner B cannot update owner A articles'
);

select is_empty(
  $$
    delete from public.articles
    where id = 'a1111111-1111-4111-8111-111111111111'
    returning id
  $$,
  'owner B cannot delete owner A articles'
);

select is(
  (select count(*) from storage.objects where bucket_id = 'library-pdfs'),
  1::bigint,
  'owner B sees only PDFs below their own storage prefix'
);

reset role;
select is(
  (
    select count(*)
    from public.articles
    where id = 'a1111111-1111-4111-8111-111111111111'
      and title = 'Owner A paper'
  ),
  1::bigint,
  'owner A article remains unchanged after cross-account attempts'
);

select *
from finish();

rollback;
