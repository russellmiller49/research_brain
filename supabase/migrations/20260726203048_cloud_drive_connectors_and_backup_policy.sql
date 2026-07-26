-- Direct drive connectors and an independent app-backup policy.
--
-- A source cloud file is deliberately not treated as the backup copy. Every
-- imported PDF first receives an immutable managed-library asset. If the
-- user's backup target is enabled, a separate replication is queued according
-- to the source policy, including Google Drive and OneDrive imports when
-- copy_cloud_imports is enabled.

create table public.cloud_connections (
  id uuid primary key default gen_random_uuid(),
  library_id uuid not null,
  owner_id uuid not null,
  provider text not null
    check (provider in ('google_drive', 'onedrive')),
  status text not null default 'pending'
    check (
      status in (
        'pending',
        'connected',
        'reauthorization_required',
        'error',
        'disconnected'
      )
    ),
  account_label text not null default ''
    check (char_length(account_label) <= 500),
  account_email text not null default ''
    check (char_length(account_email) <= 500),
  scopes text[] not null default array[]::text[],
  last_checked_at timestamptz,
  last_error_code text,
  revision bigint not null default 1 check (revision > 0),
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  foreign key (library_id, owner_id)
    references public.libraries(id, owner_id) on delete cascade,
  unique (library_id, provider),
  unique (id, library_id, owner_id)
);

create index cloud_connections_library_idx
  on public.cloud_connections (library_id, provider);

create table public.backup_targets (
  id uuid primary key default gen_random_uuid(),
  library_id uuid not null,
  owner_id uuid not null,
  connection_id uuid,
  enabled boolean not null default false,
  copy_device_imports boolean not null default true,
  copy_cloud_imports boolean not null default true,
  remote_drive_id text not null default ''
    check (char_length(remote_drive_id) <= 2048),
  remote_folder_id text not null default ''
    check (char_length(remote_folder_id) <= 2048),
  remote_folder_name text not null default 'Research Memory Backup'
    check (char_length(remote_folder_name) between 1 and 500),
  remote_folder_path text not null default 'Research Memory Backup'
    check (char_length(remote_folder_path) between 1 and 2048),
  naming_strategy text not null default 'preserve_source_name'
    check (naming_strategy in ('preserve_source_name')),
  conflict_strategy text not null default 'versioned_copy'
    check (conflict_strategy in ('versioned_copy', 'skip_same_hash')),
  last_verified_at timestamptz,
  last_error_code text,
  revision bigint not null default 1 check (revision > 0),
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  foreign key (library_id, owner_id)
    references public.libraries(id, owner_id) on delete cascade,
  foreign key (connection_id, library_id, owner_id)
    references public.cloud_connections(id, library_id, owner_id),
  unique (library_id),
  unique (id, library_id, owner_id)
);

alter table public.article_assets
  add column source_connection_id uuid,
  add column source_remote_file_id text
    check (
      source_remote_file_id is null
      or char_length(source_remote_file_id) between 1 and 2048
    ),
  add column source_remote_parent_id text
    check (
      source_remote_parent_id is null
      or char_length(source_remote_parent_id) between 1 and 2048
    ),
  add column source_remote_path text
    check (
      source_remote_path is null
      or char_length(source_remote_path) between 1 and 4096
    ),
  add column source_remote_revision text
    check (
      source_remote_revision is null
      or char_length(source_remote_revision) between 1 and 2048
    ),
  add foreign key (source_connection_id, library_id, owner_id)
    references public.cloud_connections(id, library_id, owner_id);

create index article_assets_source_connection_idx
  on public.article_assets (source_connection_id, source_remote_file_id)
  where source_connection_id is not null;

create table public.backup_replications (
  id uuid primary key default gen_random_uuid(),
  target_id uuid not null,
  asset_id uuid not null,
  article_id uuid not null,
  library_id uuid not null,
  owner_id uuid not null,
  source_kind text not null,
  source_sha256 text not null
    check (source_sha256 ~ '^[0-9a-f]{64}$'),
  status text not null default 'queued'
    check (
      status in (
        'queued',
        'running',
        'succeeded',
        'failed',
        'canceled',
        'skipped'
      )
    ),
  provider_file_id text not null default ''
    check (char_length(provider_file_id) <= 2048),
  provider_path text not null default ''
    check (char_length(provider_path) <= 4096),
  attempt_count integer not null default 0 check (attempt_count >= 0),
  retryable boolean not null default true,
  error_code text,
  error_message text not null default '',
  started_at timestamptz,
  finished_at timestamptz,
  revision bigint not null default 1 check (revision > 0),
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  foreign key (target_id, library_id, owner_id)
    references public.backup_targets(id, library_id, owner_id) on delete cascade,
  foreign key (asset_id, article_id, library_id, owner_id)
    references public.article_assets(id, article_id, library_id, owner_id)
      on delete cascade,
  unique (asset_id, target_id)
);

create index backup_replications_queue_idx
  on public.backup_replications (status, created_at)
  where status in ('queued', 'failed');
create index backup_replications_library_idx
  on public.backup_replications (library_id, updated_at desc);

create table research_memory_private.cloud_connection_secrets (
  connection_id uuid primary key,
  library_id uuid not null,
  owner_id uuid not null,
  encrypted_token_payload text not null,
  token_expires_at timestamptz,
  token_version integer not null default 1 check (token_version > 0),
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  foreign key (connection_id, library_id, owner_id)
    references public.cloud_connections(id, library_id, owner_id)
      on delete cascade
);

create table research_memory_private.cloud_oauth_states (
  state_hash text primary key
    check (state_hash ~ '^[0-9a-f]{64}$'),
  owner_id uuid not null references auth.users(id) on delete cascade,
  library_id uuid not null,
  provider text not null
    check (provider in ('google_drive', 'onedrive')),
  encrypted_pkce_verifier text not null,
  return_to text not null check (char_length(return_to) <= 4096),
  expires_at timestamptz not null,
  created_at timestamptz not null default timezone('utc', now()),
  foreign key (library_id, owner_id)
    references public.libraries(id, owner_id) on delete cascade
);

create index cloud_oauth_states_expiry_idx
  on research_memory_private.cloud_oauth_states (expires_at);

create trigger cloud_connections_touch_sync_row
before update on public.cloud_connections
for each row execute function research_memory_private.touch_sync_row();
create trigger backup_targets_touch_sync_row
before update on public.backup_targets
for each row execute function research_memory_private.touch_sync_row();
create trigger backup_replications_touch_sync_row
before update on public.backup_replications
for each row execute function research_memory_private.touch_sync_row();

alter table public.cloud_connections enable row level security;
alter table public.backup_targets enable row level security;
alter table public.backup_replications enable row level security;
alter table research_memory_private.cloud_connection_secrets enable row level security;
alter table research_memory_private.cloud_oauth_states enable row level security;

create policy cloud_connections_select_own
on public.cloud_connections for select
to authenticated
using ((select auth.uid()) = owner_id);

create policy backup_targets_select_own
on public.backup_targets for select
to authenticated
using ((select auth.uid()) = owner_id);
create policy backup_targets_insert_own
on public.backup_targets for insert
to authenticated
with check ((select auth.uid()) = owner_id);
create policy backup_targets_update_own
on public.backup_targets for update
to authenticated
using ((select auth.uid()) = owner_id)
with check ((select auth.uid()) = owner_id);

create policy backup_replications_select_own
on public.backup_replications for select
to authenticated
using ((select auth.uid()) = owner_id);

revoke all on table public.cloud_connections from anon, authenticated;
revoke all on table public.backup_targets from anon, authenticated;
revoke all on table public.backup_replications from anon, authenticated;

grant select on table public.cloud_connections to authenticated;
grant select, insert, update on table public.backup_targets to authenticated;
grant select on table public.backup_replications to authenticated;

grant select, insert, update, delete
  on table public.cloud_connections to service_role;
grant select, insert, update, delete
  on table public.backup_targets to service_role;
grant select, insert, update, delete
  on table public.backup_replications to service_role;
grant select, insert, update, delete
  on table research_memory_private.cloud_connection_secrets to service_role;
grant select, insert, update, delete
  on table research_memory_private.cloud_oauth_states to service_role;

create or replace function public.queue_library_backups(
  p_asset_id uuid default null
)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  caller_id uuid := auth.uid();
  queued_count integer;
begin
  if caller_id is null then
    raise exception 'Authentication is required'
      using errcode = '42501';
  end if;

  insert into public.backup_replications (
    target_id,
    asset_id,
    article_id,
    library_id,
    owner_id,
    source_kind,
    source_sha256
  )
  select
    target.id,
    asset.id,
    asset.article_id,
    asset.library_id,
    asset.owner_id,
    asset.source_kind,
    asset.sha256
  from public.article_assets as asset
  join public.backup_targets as target
    on target.library_id = asset.library_id
   and target.owner_id = asset.owner_id
  where asset.owner_id = caller_id
    and (p_asset_id is null or asset.id = p_asset_id)
    and asset.availability = 'available'
    and target.enabled
    and target.connection_id is not null
    and target.remote_folder_id <> ''
    and (
      (
        lower(asset.source_kind) in (
          'google_drive',
          'onedrive',
          'cloud_drive'
        )
        and target.copy_cloud_imports
      )
      or
      (
        lower(asset.source_kind) not in (
          'google_drive',
          'onedrive',
          'cloud_drive'
        )
        and target.copy_device_imports
      )
    )
  on conflict (asset_id, target_id) do nothing;

  get diagnostics queued_count = row_count;
  return queued_count;
end;
$$;

revoke all on function public.queue_library_backups(uuid)
  from public, anon;
grant execute on function public.queue_library_backups(uuid)
  to authenticated, service_role;

create or replace function public.search_library_chunks(
  p_library_id uuid,
  p_query text,
  p_limit integer default 40
)
returns table (
  article_id uuid,
  page_number integer,
  snippet text,
  match_rank real
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  caller_id uuid := auth.uid();
  parsed_query tsquery;
begin
  if caller_id is null then
    raise exception 'Authentication is required'
      using errcode = '42501';
  end if;
  if trim(coalesce(p_query, '')) = '' then
    return;
  end if;

  parsed_query := websearch_to_tsquery(
    'english',
    left(trim(p_query), 500)
  );

  return query
  select
    chunk.article_id,
    chunk.page_number,
    ts_headline(
      'english',
      chunk.text,
      parsed_query,
      'MaxWords=35, MinWords=12, MaxFragments=2'
    ),
    ts_rank_cd(chunk.search_vector, parsed_query)::real
  from research_memory_private.article_chunks as chunk
  join public.articles as article
    on article.id = chunk.article_id
   and article.library_id = chunk.library_id
   and article.owner_id = chunk.owner_id
  where chunk.owner_id = caller_id
    and chunk.library_id = p_library_id
    and article.deleted_at is null
    and chunk.search_vector @@ parsed_query
  order by
    ts_rank_cd(chunk.search_vector, parsed_query) desc,
    chunk.article_id,
    chunk.page_number
  limit least(greatest(coalesce(p_limit, 40), 1), 100);
end;
$$;

revoke all on function public.search_library_chunks(uuid, text, integer)
  from public, anon;
grant execute
  on function public.search_library_chunks(uuid, text, integer)
  to authenticated, service_role;

create or replace function public.create_cloud_oauth_state(
  p_state_hash text,
  p_owner_id uuid,
  p_library_id uuid,
  p_provider text,
  p_encrypted_pkce_verifier text,
  p_return_to text,
  p_expires_at timestamptz
)
returns void
language sql
security definer
set search_path = ''
as $$
  insert into research_memory_private.cloud_oauth_states (
    state_hash,
    owner_id,
    library_id,
    provider,
    encrypted_pkce_verifier,
    return_to,
    expires_at
  )
  values (
    p_state_hash,
    p_owner_id,
    p_library_id,
    p_provider,
    p_encrypted_pkce_verifier,
    p_return_to,
    p_expires_at
  );
$$;

create or replace function public.consume_cloud_oauth_state(
  p_state_hash text
)
returns table (
  owner_id uuid,
  library_id uuid,
  provider text,
  encrypted_pkce_verifier text,
  return_to text
)
language sql
security definer
set search_path = ''
as $$
  delete from research_memory_private.cloud_oauth_states
  where state_hash = p_state_hash
    and expires_at > timezone('utc', now())
  returning
    cloud_oauth_states.owner_id,
    cloud_oauth_states.library_id,
    cloud_oauth_states.provider,
    cloud_oauth_states.encrypted_pkce_verifier,
    cloud_oauth_states.return_to;
$$;

create or replace function public.upsert_cloud_connection_secret(
  p_connection_id uuid,
  p_library_id uuid,
  p_owner_id uuid,
  p_encrypted_token_payload text,
  p_token_expires_at timestamptz
)
returns void
language sql
security definer
set search_path = ''
as $$
  insert into research_memory_private.cloud_connection_secrets (
    connection_id,
    library_id,
    owner_id,
    encrypted_token_payload,
    token_expires_at
  )
  values (
    p_connection_id,
    p_library_id,
    p_owner_id,
    p_encrypted_token_payload,
    p_token_expires_at
  )
  on conflict (connection_id) do update
  set
    encrypted_token_payload = excluded.encrypted_token_payload,
    token_expires_at = excluded.token_expires_at,
    token_version = cloud_connection_secrets.token_version + 1,
    updated_at = timezone('utc', now());
$$;

create or replace function public.read_cloud_connection_secret(
  p_connection_id uuid
)
returns table (
  library_id uuid,
  owner_id uuid,
  encrypted_token_payload text,
  token_expires_at timestamptz,
  token_version integer
)
language sql
stable
security definer
set search_path = ''
as $$
  select
    secret.library_id,
    secret.owner_id,
    secret.encrypted_token_payload,
    secret.token_expires_at,
    secret.token_version
  from research_memory_private.cloud_connection_secrets as secret
  where secret.connection_id = p_connection_id;
$$;

revoke all
  on function public.create_cloud_oauth_state(
    text,
    uuid,
    uuid,
    text,
    text,
    text,
    timestamptz
  )
  from public, anon, authenticated;
revoke all
  on function public.consume_cloud_oauth_state(text)
  from public, anon, authenticated;
revoke all
  on function public.upsert_cloud_connection_secret(
    uuid,
    uuid,
    uuid,
    text,
    timestamptz
  )
  from public, anon, authenticated;
revoke all
  on function public.read_cloud_connection_secret(uuid)
  from public, anon, authenticated;

grant execute
  on function public.create_cloud_oauth_state(
    text,
    uuid,
    uuid,
    text,
    text,
    text,
    timestamptz
  )
  to service_role;
grant execute
  on function public.consume_cloud_oauth_state(text)
  to service_role;
grant execute
  on function public.upsert_cloud_connection_secret(
    uuid,
    uuid,
    uuid,
    text,
    timestamptz
  )
  to service_role;
grant execute
  on function public.read_cloud_connection_secret(uuid)
  to service_role;

do $$
declare
  synced_table text;
begin
  if exists (
    select 1
    from pg_catalog.pg_publication
    where pubname = 'supabase_realtime'
  ) then
    foreach synced_table in array array[
      'cloud_connections',
      'backup_targets',
      'backup_replications'
    ]
    loop
      if not exists (
        select 1
        from pg_catalog.pg_publication_tables
        where pubname = 'supabase_realtime'
          and schemaname = 'public'
          and tablename = synced_table
      ) then
        execute format(
          'alter publication supabase_realtime add table public.%I',
          synced_table
        );
      end if;
    end loop;
  end if;
end;
$$;
