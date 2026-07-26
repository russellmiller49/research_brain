-- Research Memory synced-library foundation.
--
-- All client-visible records carry an explicit owner_id. Composite foreign
-- keys make it impossible to attach a child record to another user's library,
-- even for server-side code that accidentally bypasses RLS.

create extension if not exists vector with schema extensions;

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

alter default privileges for role postgres in schema public
  revoke select, insert, update, delete on tables from anon, authenticated, service_role;
alter default privileges for role postgres in schema public
  revoke execute on functions from anon, authenticated, service_role;
alter default privileges for role postgres in schema public
  revoke usage, select on sequences from anon, authenticated, service_role;
alter default privileges for role postgres in schema public
  revoke execute on functions from public;

create or replace function private.touch_sync_row()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  new.updated_at = timezone('utc', now());
  new.revision = old.revision + 1;
  return new;
end;
$$;

create table public.libraries (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  name text not null default 'My Research Library'
    check (char_length(name) between 1 and 200),
  sync_mode text not null default 'synced'
    check (sync_mode in ('synced')),
  revision bigint not null default 1 check (revision > 0),
  deleted_at timestamptz,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  unique (owner_id),
  unique (id, owner_id)
);

create table public.articles (
  id uuid primary key default gen_random_uuid(),
  library_id uuid not null,
  owner_id uuid not null,
  title text not null check (char_length(title) between 1 and 1000),
  authors text not null default '' check (char_length(authors) <= 2000),
  journal text not null default '' check (char_length(journal) <= 500),
  publication_year smallint check (publication_year between 1500 and 2200),
  doi text not null default '' check (char_length(doi) <= 500),
  pmid text not null default '' check (char_length(pmid) <= 20),
  abstract text not null default '',
  page_count integer not null default 0 check (page_count >= 0),
  reading_status text not null default 'unread'
    check (reading_status in ('unread', 'reading', 'reference', 'finished')),
  importance smallint not null default 0 check (importance between 0 and 5),
  why_saved text not null default '',
  user_summary text not null default '',
  extraction_status text not null default 'uploaded'
    check (
      extraction_status in (
        'uploaded',
        'queued',
        'processing',
        'indexed',
        'partial',
        'failed',
        'password_required'
      )
    ),
  metadata_status text not null default 'filename'
    check (metadata_status in ('filename', 'local', 'enriched', 'user')),
  source_type text not null default 'journal_article',
  review_state text not null default 'ready',
  revision bigint not null default 1 check (revision > 0),
  deleted_at timestamptz,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  foreign key (library_id, owner_id)
    references public.libraries(id, owner_id) on delete cascade,
  unique (id, library_id, owner_id)
);

create index articles_library_updated_idx
  on public.articles (library_id, updated_at desc)
  where deleted_at is null;
create index articles_owner_title_idx
  on public.articles (owner_id, lower(title))
  where deleted_at is null;
create index articles_doi_idx
  on public.articles (library_id, doi)
  where doi <> '' and deleted_at is null;
create index articles_pmid_idx
  on public.articles (library_id, pmid)
  where pmid <> '' and deleted_at is null;

create table public.article_assets (
  id uuid primary key default gen_random_uuid(),
  article_id uuid not null,
  library_id uuid not null,
  owner_id uuid not null,
  sha256 text not null
    check (sha256 ~ '^[0-9a-f]{64}$'),
  storage_bucket text not null default 'library-pdfs'
    check (storage_bucket = 'library-pdfs'),
  storage_path text not null check (char_length(storage_path) between 1 and 1024),
  file_name text not null check (char_length(file_name) between 1 and 1000),
  size_bytes bigint not null check (size_bytes between 1 and 262144000),
  mime_type text not null default 'application/pdf'
    check (mime_type = 'application/pdf'),
  source_kind text not null default 'upload',
  role text not null default 'article',
  version_label text not null default '',
  availability text not null default 'available'
    check (availability in ('available', 'missing', 'processing', 'failed')),
  is_primary boolean not null default true,
  revision bigint not null default 1 check (revision > 0),
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  foreign key (article_id, library_id, owner_id)
    references public.articles(id, library_id, owner_id) on delete cascade,
  unique (library_id, sha256),
  unique (id, article_id, library_id, owner_id)
);

create index article_assets_article_idx
  on public.article_assets (article_id, is_primary desc, created_at);

create table public.annotations (
  id uuid primary key default gen_random_uuid(),
  article_id uuid not null,
  asset_id uuid not null,
  library_id uuid not null,
  owner_id uuid not null,
  page_number integer not null check (page_number > 0),
  annotation_type text not null
    check (annotation_type in ('highlight', 'comment', 'bookmark')),
  color text not null default '#F4C95D'
    check (color ~ '^#[0-9A-Fa-f]{6}$'),
  quad_points jsonb not null default '[]'::jsonb
    check (jsonb_typeof(quad_points) = 'array'),
  selected_text text not null default '',
  context_hash text not null default '',
  comment text not null default '',
  revision bigint not null default 1 check (revision > 0),
  deleted_at timestamptz,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  foreign key (article_id, library_id, owner_id)
    references public.articles(id, library_id, owner_id) on delete cascade,
  foreign key (asset_id, article_id, library_id, owner_id)
    references public.article_assets(id, article_id, library_id, owner_id) on delete cascade
);

create index annotations_article_page_idx
  on public.annotations (article_id, page_number, created_at)
  where deleted_at is null;

create table public.projects (
  id uuid primary key default gen_random_uuid(),
  library_id uuid not null,
  owner_id uuid not null,
  name text not null check (char_length(name) between 1 and 500),
  description text not null default '',
  project_type text not null default 'collection',
  central_question text not null default '',
  revision bigint not null default 1 check (revision > 0),
  deleted_at timestamptz,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  foreign key (library_id, owner_id)
    references public.libraries(id, owner_id) on delete cascade,
  unique (id, library_id, owner_id)
);

create index projects_library_updated_idx
  on public.projects (library_id, updated_at desc)
  where deleted_at is null;

create table public.project_articles (
  project_id uuid not null,
  article_id uuid not null,
  library_id uuid not null,
  owner_id uuid not null,
  status text not null default 'candidate',
  added_at timestamptz not null default timezone('utc', now()),
  primary key (project_id, article_id),
  foreign key (project_id, library_id, owner_id)
    references public.projects(id, library_id, owner_id) on delete cascade,
  foreign key (article_id, library_id, owner_id)
    references public.articles(id, library_id, owner_id) on delete cascade
);

create index project_articles_article_idx
  on public.project_articles (article_id, project_id);

create table public.jobs (
  id uuid primary key default gen_random_uuid(),
  library_id uuid not null,
  owner_id uuid not null,
  type text not null default 'import',
  source text not null default '',
  stage text not null default 'queued',
  status text not null default 'queued'
    check (status in ('queued', 'running', 'paused', 'succeeded', 'failed', 'canceled')),
  progress_current bigint not null default 0 check (progress_current >= 0),
  progress_total bigint not null default 0 check (progress_total >= 0),
  retryable boolean not null default false,
  error_code text,
  issue_count integer not null default 0 check (issue_count >= 0),
  input jsonb not null default '{}'::jsonb,
  output jsonb not null default '{}'::jsonb,
  revision bigint not null default 1 check (revision > 0),
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  finished_at timestamptz,
  foreign key (library_id, owner_id)
    references public.libraries(id, owner_id) on delete cascade
);

create index jobs_library_updated_idx
  on public.jobs (library_id, updated_at desc);

create table private.article_pages (
  article_id uuid not null,
  asset_id uuid not null,
  library_id uuid not null,
  owner_id uuid not null,
  page_number integer not null check (page_number > 0),
  width double precision not null default 0 check (width >= 0),
  height double precision not null default 0 check (height >= 0),
  text text not null default '',
  layout jsonb not null default '[]'::jsonb,
  extraction_method text not null default 'pdfium',
  created_at timestamptz not null default timezone('utc', now()),
  primary key (asset_id, page_number),
  foreign key (asset_id, article_id, library_id, owner_id)
    references public.article_assets(id, article_id, library_id, owner_id) on delete cascade
);

create table private.article_chunks (
  id uuid primary key default gen_random_uuid(),
  article_id uuid not null,
  asset_id uuid not null,
  library_id uuid not null,
  owner_id uuid not null,
  page_number integer not null check (page_number > 0),
  chunk_index integer not null check (chunk_index >= 0),
  text text not null,
  bounding_boxes jsonb not null default '[]'::jsonb,
  search_vector tsvector generated always as (to_tsvector('english', text)) stored,
  embedding extensions.vector(384),
  embedding_model text not null default '',
  index_version text not null default '',
  created_at timestamptz not null default timezone('utc', now()),
  foreign key (asset_id, article_id, library_id, owner_id)
    references public.article_assets(id, article_id, library_id, owner_id) on delete cascade,
  unique (asset_id, page_number, chunk_index)
);

create index article_chunks_fts_idx
  on private.article_chunks using gin (search_vector);
create index article_chunks_owner_idx
  on private.article_chunks (owner_id, article_id);
create index article_chunks_embedding_idx
  on private.article_chunks
  using hnsw (embedding vector_cosine_ops)
  where embedding is not null;

create trigger libraries_touch_sync_row
before update on public.libraries
for each row execute function private.touch_sync_row();
create trigger articles_touch_sync_row
before update on public.articles
for each row execute function private.touch_sync_row();
create trigger article_assets_touch_sync_row
before update on public.article_assets
for each row execute function private.touch_sync_row();
create trigger annotations_touch_sync_row
before update on public.annotations
for each row execute function private.touch_sync_row();
create trigger projects_touch_sync_row
before update on public.projects
for each row execute function private.touch_sync_row();
create trigger jobs_touch_sync_row
before update on public.jobs
for each row execute function private.touch_sync_row();

alter table public.libraries enable row level security;
alter table public.articles enable row level security;
alter table public.article_assets enable row level security;
alter table public.annotations enable row level security;
alter table public.projects enable row level security;
alter table public.project_articles enable row level security;
alter table public.jobs enable row level security;
alter table private.article_pages enable row level security;
alter table private.article_chunks enable row level security;

create policy libraries_select_own
on public.libraries for select
to authenticated
using ((select auth.uid()) = owner_id);
create policy libraries_insert_own
on public.libraries for insert
to authenticated
with check ((select auth.uid()) = owner_id);
create policy libraries_update_own
on public.libraries for update
to authenticated
using ((select auth.uid()) = owner_id)
with check ((select auth.uid()) = owner_id);
create policy libraries_delete_own
on public.libraries for delete
to authenticated
using ((select auth.uid()) = owner_id);

create policy articles_select_own
on public.articles for select
to authenticated
using ((select auth.uid()) = owner_id);
create policy articles_insert_own
on public.articles for insert
to authenticated
with check ((select auth.uid()) = owner_id);
create policy articles_update_own
on public.articles for update
to authenticated
using ((select auth.uid()) = owner_id)
with check ((select auth.uid()) = owner_id);
create policy articles_delete_own
on public.articles for delete
to authenticated
using ((select auth.uid()) = owner_id);

create policy article_assets_select_own
on public.article_assets for select
to authenticated
using ((select auth.uid()) = owner_id);
create policy article_assets_insert_own
on public.article_assets for insert
to authenticated
with check ((select auth.uid()) = owner_id);
create policy article_assets_update_own
on public.article_assets for update
to authenticated
using ((select auth.uid()) = owner_id)
with check ((select auth.uid()) = owner_id);
create policy article_assets_delete_own
on public.article_assets for delete
to authenticated
using ((select auth.uid()) = owner_id);

create policy annotations_select_own
on public.annotations for select
to authenticated
using ((select auth.uid()) = owner_id);
create policy annotations_insert_own
on public.annotations for insert
to authenticated
with check ((select auth.uid()) = owner_id);
create policy annotations_update_own
on public.annotations for update
to authenticated
using ((select auth.uid()) = owner_id)
with check ((select auth.uid()) = owner_id);
create policy annotations_delete_own
on public.annotations for delete
to authenticated
using ((select auth.uid()) = owner_id);

create policy projects_select_own
on public.projects for select
to authenticated
using ((select auth.uid()) = owner_id);
create policy projects_insert_own
on public.projects for insert
to authenticated
with check ((select auth.uid()) = owner_id);
create policy projects_update_own
on public.projects for update
to authenticated
using ((select auth.uid()) = owner_id)
with check ((select auth.uid()) = owner_id);
create policy projects_delete_own
on public.projects for delete
to authenticated
using ((select auth.uid()) = owner_id);

create policy project_articles_select_own
on public.project_articles for select
to authenticated
using ((select auth.uid()) = owner_id);
create policy project_articles_insert_own
on public.project_articles for insert
to authenticated
with check ((select auth.uid()) = owner_id);
create policy project_articles_update_own
on public.project_articles for update
to authenticated
using ((select auth.uid()) = owner_id)
with check ((select auth.uid()) = owner_id);
create policy project_articles_delete_own
on public.project_articles for delete
to authenticated
using ((select auth.uid()) = owner_id);

create policy jobs_select_own
on public.jobs for select
to authenticated
using ((select auth.uid()) = owner_id);
create policy jobs_insert_own
on public.jobs for insert
to authenticated
with check ((select auth.uid()) = owner_id);
create policy jobs_update_own
on public.jobs for update
to authenticated
using ((select auth.uid()) = owner_id)
with check ((select auth.uid()) = owner_id);
create policy jobs_delete_own
on public.jobs for delete
to authenticated
using ((select auth.uid()) = owner_id);

revoke all on table public.libraries from anon;
revoke all on table public.articles from anon;
revoke all on table public.article_assets from anon;
revoke all on table public.annotations from anon;
revoke all on table public.projects from anon;
revoke all on table public.project_articles from anon;
revoke all on table public.jobs from anon;

grant select, insert, update, delete on table public.libraries to authenticated;
grant select, insert, update, delete on table public.articles to authenticated;
grant select, insert, update, delete on table public.article_assets to authenticated;
grant select, insert, update, delete on table public.annotations to authenticated;
grant select, insert, update, delete on table public.projects to authenticated;
grant select, insert, update, delete on table public.project_articles to authenticated;
grant select, insert, update, delete on table public.jobs to authenticated;

grant usage on schema private to service_role;
grant select, insert, update, delete on table public.libraries to service_role;
grant select, insert, update, delete on table public.articles to service_role;
grant select, insert, update, delete on table public.article_assets to service_role;
grant select, insert, update, delete on table public.annotations to service_role;
grant select, insert, update, delete on table public.projects to service_role;
grant select, insert, update, delete on table public.project_articles to service_role;
grant select, insert, update, delete on table public.jobs to service_role;
grant select, insert, update, delete on table private.article_pages to service_role;
grant select, insert, update, delete on table private.article_chunks to service_role;

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
      'libraries',
      'articles',
      'article_assets',
      'annotations',
      'projects',
      'project_articles',
      'jobs'
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

insert into storage.buckets (
  id,
  name,
  public,
  file_size_limit,
  allowed_mime_types
)
values (
  'library-pdfs',
  'library-pdfs',
  false,
  262144000,
  array['application/pdf']
)
on conflict (id) do update
set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

create policy library_pdfs_select_own
on storage.objects for select
to authenticated
using (
  bucket_id = 'library-pdfs'
  and (storage.foldername(name))[1] = (select auth.uid())::text
  and exists (
    select 1
    from public.libraries
    where owner_id = (select auth.uid())
      and id::text = (storage.foldername(storage.objects.name))[2]
      and deleted_at is null
  )
);

create policy library_pdfs_insert_own
on storage.objects for insert
to authenticated
with check (
  bucket_id = 'library-pdfs'
  and (storage.foldername(name))[1] = (select auth.uid())::text
  and exists (
    select 1
    from public.libraries
    where owner_id = (select auth.uid())
      and id::text = (storage.foldername(storage.objects.name))[2]
      and deleted_at is null
  )
);

create policy library_pdfs_update_own
on storage.objects for update
to authenticated
using (
  bucket_id = 'library-pdfs'
  and (storage.foldername(name))[1] = (select auth.uid())::text
  and exists (
    select 1
    from public.libraries
    where owner_id = (select auth.uid())
      and id::text = (storage.foldername(storage.objects.name))[2]
      and deleted_at is null
  )
)
with check (
  bucket_id = 'library-pdfs'
  and (storage.foldername(name))[1] = (select auth.uid())::text
  and exists (
    select 1
    from public.libraries
    where owner_id = (select auth.uid())
      and id::text = (storage.foldername(storage.objects.name))[2]
      and deleted_at is null
  )
);

create policy library_pdfs_delete_own
on storage.objects for delete
to authenticated
using (
  bucket_id = 'library-pdfs'
  and (storage.foldername(name))[1] = (select auth.uid())::text
  and exists (
    select 1
    from public.libraries
    where owner_id = (select auth.uid())
      and id::text = (storage.foldername(storage.objects.name))[2]
      and deleted_at is null
  )
);
