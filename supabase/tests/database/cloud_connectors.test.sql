begin;

create extension if not exists pgtap with schema extensions;

select plan(17);

select ok(
  (
    select bool_and(c.relrowsecurity)
    from pg_catalog.pg_class as c
    join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relname = any (
        array[
          'cloud_connections',
          'backup_targets',
          'backup_replications'
        ]
      )
  ),
  'RLS is enabled on every connector and backup table'
);

select ok(
  has_table_privilege(
    'authenticated',
    'public.cloud_connections',
    'select'
  ),
  'authenticated users can read their connection status'
);

select isnt(
  has_table_privilege(
    'authenticated',
    'public.cloud_connections',
    'insert'
  ),
  true,
  'authenticated users cannot forge provider connections'
);

select isnt(
  has_table_privilege(
    'anon',
    'public.backup_targets',
    'select'
  ),
  true,
  'anonymous callers cannot inspect backup configuration'
);

select isnt(
  has_table_privilege(
    'authenticated',
    'private.cloud_connection_secrets',
    'select'
  ),
  true,
  'encrypted provider credentials are not readable by clients'
);

select ok(
  has_table_privilege(
    'service_role',
    'private.cloud_connection_secrets',
    'select'
  ),
  'the connector service can read encrypted provider credentials'
);

select isnt(
  has_function_privilege(
    'authenticated',
    'public.read_cloud_connection_secret(uuid)',
    'execute'
  ),
  true,
  'client sessions cannot call the credential reader'
);

select ok(
  has_function_privilege(
    'authenticated',
    'public.queue_library_backups(uuid)',
    'execute'
  ),
  'client sessions can invoke the owner-checked backup queue'
);

insert into auth.users (id, email)
values
  ('33333333-3333-4333-8333-333333333333', 'backup-a@example.test'),
  ('44444444-4444-4444-8444-444444444444', 'backup-b@example.test');

insert into public.libraries (id, owner_id, name)
values
  (
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    '33333333-3333-4333-8333-333333333333',
    'Backup owner A'
  ),
  (
    'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
    '44444444-4444-4444-8444-444444444444',
    'Backup owner B'
  );

insert into public.articles (id, library_id, owner_id, title)
values
  (
    'c1111111-1111-4111-8111-111111111111',
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    '33333333-3333-4333-8333-333333333333',
    'Device paper'
  ),
  (
    'c2222222-2222-4222-8222-222222222222',
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    '33333333-3333-4333-8333-333333333333',
    'Google Drive paper'
  ),
  (
    'd1111111-1111-4111-8111-111111111111',
    'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
    '44444444-4444-4444-8444-444444444444',
    'Other owner paper'
  );

insert into public.cloud_connections (
  id,
  library_id,
  owner_id,
  provider,
  status
)
values
  (
    'c3333333-3333-4333-8333-333333333333',
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    '33333333-3333-4333-8333-333333333333',
    'google_drive',
    'connected'
  );

insert into public.backup_targets (
  id,
  library_id,
  owner_id,
  connection_id,
  enabled,
  copy_device_imports,
  copy_cloud_imports,
  remote_folder_id
)
values
  (
    'c4444444-4444-4444-8444-444444444444',
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    '33333333-3333-4333-8333-333333333333',
    'c3333333-3333-4333-8333-333333333333',
    true,
    true,
    false,
    'google-backup-folder'
  );

insert into public.article_assets (
  id,
  article_id,
  library_id,
  owner_id,
  sha256,
  storage_path,
  file_name,
  size_bytes,
  source_kind
)
values
  (
    'c5555555-5555-4555-8555-555555555555',
    'c1111111-1111-4111-8111-111111111111',
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    '33333333-3333-4333-8333-333333333333',
    repeat('a', 64),
    'owner-a/device.pdf',
    'device.pdf',
    100,
    'device_upload'
  ),
  (
    'c6666666-6666-4666-8666-666666666666',
    'c2222222-2222-4222-8222-222222222222',
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    '33333333-3333-4333-8333-333333333333',
    repeat('b', 64),
    'owner-a/google.pdf',
    'google.pdf',
    100,
    'google_drive'
  ),
  (
    'd5555555-5555-4555-8555-555555555555',
    'd1111111-1111-4111-8111-111111111111',
    'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
    '44444444-4444-4444-8444-444444444444',
    repeat('c', 64),
    'owner-b/other.pdf',
    'other.pdf',
    100,
    'device_upload'
  );

insert into private.article_chunks (
  article_id,
  asset_id,
  library_id,
  owner_id,
  page_number,
  chunk_index,
  text
)
values (
  'c2222222-2222-4222-8222-222222222222',
  'c6666666-6666-4666-8666-666666666666',
  'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
  '33333333-3333-4333-8333-333333333333',
  7,
  0,
  'Bronchoscopic staging combines nodal sampling with airway inspection.'
);

set local role authenticated;
select set_config(
  'request.jwt.claim.sub',
  '33333333-3333-4333-8333-333333333333',
  true
);
select set_config(
  'request.jwt.claims',
  '{"sub":"33333333-3333-4333-8333-333333333333","role":"authenticated"}',
  true
);

select is(
  public.queue_library_backups(null),
  1,
  'device imports queue while cloud-origin backup is disabled'
);

select is(
  (
    select count(*)
    from public.backup_replications
    where source_kind = 'device_upload'
  ),
  1::bigint,
  'the first replication belongs to the device import'
);

update public.backup_targets
set copy_cloud_imports = true
where id = 'c4444444-4444-4444-8444-444444444444';

select is(
  public.queue_library_backups(null),
  1,
  'enabling cloud-origin backup queues the Google Drive import separately'
);

select is(
  (
    select count(*)
    from public.backup_replications
    where source_kind = 'google_drive'
      and target_id = 'c4444444-4444-4444-8444-444444444444'
  ),
  1::bigint,
  'a cloud source can be copied into the app backup on the same provider'
);

select is(
  public.queue_library_backups(null),
  0,
  'backup queueing is idempotent for an asset and target'
);

select is(
  (
    select count(*)
    from public.search_library_chunks(
      'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
      'bronchoscopic staging',
      10
    )
  ),
  1::bigint,
  'owner A can search indexed passages in their library'
);

reset role;
set local role authenticated;
select set_config(
  'request.jwt.claim.sub',
  '44444444-4444-4444-8444-444444444444',
  true
);
select set_config(
  'request.jwt.claims',
  '{"sub":"44444444-4444-4444-8444-444444444444","role":"authenticated"}',
  true
);

select is(
  public.queue_library_backups(
    'c5555555-5555-4555-8555-555555555555'
  ),
  0,
  'owner B cannot queue owner A assets'
);

select is(
  (select count(*) from public.backup_replications),
  0::bigint,
  'owner B cannot see owner A backup records'
);

select is(
  (
    select count(*)
    from public.search_library_chunks(
      'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
      'bronchoscopic staging',
      10
    )
  ),
  0::bigint,
  'owner B cannot search owner A indexed passages'
);

select *
from finish();

rollback;
