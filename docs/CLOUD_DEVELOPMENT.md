# Synced Web and Mobile-Web Development

The first cross-device vertical slice is implemented alongside the existing
local-only desktop app. Cloud mode uses the same React/PDF.js reader with a
Supabase-backed client; the normal desktop build continues to use the Tauri
sidecar.

## What works

- passwordless email sign-in;
- Apple, Google, and Microsoft sign-in entry points (after provider setup);
- one private library created for each authenticated account;
- responsive desktop navigation and phone bottom navigation;
- a synced dashboard with recent papers and library activity;
- metadata, abstract, personal-summary, and saved-context recall search;
- ranked full-text results from indexed PDF passages, with page snippets;
- project creation, project membership, and project-filtered search;
- import/job history, editable library settings, and 30-day trash recovery;
- PDF import from the browser or operating-system file picker;
- resumable 6 MiB-chunk uploads for PDFs up to 250 MB;
- SHA-256 deduplication within a library;
- private immutable PDF storage and short-lived signed reader URLs;
- synced bibliographic metadata, personal context, bookmarks, highlights, and
  comments;
- realtime library refresh after changes from another open client;
- Google Drive and OneDrive OAuth/PKCE connection entry points with encrypted,
  server-only token storage;
- a dedicated `Research Memory Backup` folder target and independent settings
  for device imports and cloud-drive imports;
- idempotent backup replication queue records, including a second copy when
  the source itself was Google Drive or OneDrive;
- account-scoped projects and project membership from the projects workspace
  or reader;
- Markdown, RIS, BibTeX, and XFDF exports.

On iOS and iPadOS, the system Files picker can expose iCloud Drive, Google
Drive, OneDrive, and other installed document providers. iCloud does not offer
the same general-purpose server drive API as Google Drive or Microsoft Graph,
so it remains a Files-picker source. Direct Google Drive and OneDrive account
authorization is now wired; the remote file browser and the background worker
that drains queued backup replications remain the next connector slice.

## Local setup

Requirements:

- Docker running;
- the repository's supported Node.js version;
- dependencies installed in `desktop/`.

Start the local account, database, realtime, and storage services from the
repository root:

```bash
npx --yes supabase@2.109.1 start
```

Read the local client values:

```bash
npx --yes supabase@2.109.1 status --output env
```

Copy `desktop/.env.cloud.example` to `desktop/.env.cloud.local`, then set:

```dotenv
VITE_SUPABASE_URL=http://127.0.0.1:54321
VITE_SUPABASE_PUBLISHABLE_KEY=<PUBLISHABLE_KEY from supabase status>
```

Only a publishable key belongs in this file. Never put a Supabase secret key
or service-role token in a Vite variable.

Run the responsive web app:

```bash
cd desktop
npm install
npm run dev:web
```

`dev:web` starts both Vite and the local cloud-connector Edge Function. To run
them in separate terminals instead, use `npm run dev:web-only` and
`npm run dev:connectors`. The default URL is `http://127.0.0.1:1420`. Local
magic-link emails appear in Mailpit at `http://127.0.0.1:54324`.

## Google Drive and OneDrive connector setup

Connector credentials and refresh tokens never belong in the Vite
environment. Copy `supabase/functions/.env.example` to an ignored local file,
configure one or both providers, and generate a unique 32-byte encryption key:

```bash
cp supabase/functions/.env.example supabase/functions/.env.local
openssl rand -base64 32 | tr '+/' '-_' | tr -d '='
```

Paste the generated value into `CONNECTOR_TOKEN_ENCRYPTION_KEY`. The local
connector can run without provider credentials so the app can report its setup
state, but an account cannot be attached until that provider's OAuth client ID
and secret are present.

Register this exact local callback with each provider:

```text
http://127.0.0.1:54321/functions/v1/cloud-connectors/callback
```

If Vite is already running with `npm run dev:web-only`, serve the function in a
second terminal:

```bash
cd desktop
npm run dev:connectors
```

For hosted environments, place the same values in Supabase Edge Function
secrets, use the hosted function callback URL, and list the deployed web
origins in `CLOUD_APP_ORIGINS`. Google authorization requests read-only Drive
access for selecting existing PDFs plus app-file access for the backup folder.
Microsoft requests delegated `Files.ReadWrite` and `offline_access`.

The app always creates its own managed-library copy first. Its backup policy is
then evaluated independently:

- `copy_device_imports` covers device and system Files-picker sources;
- `copy_cloud_imports` covers Google Drive and OneDrive sources;
- `(asset_id, target_id)` uniqueness prevents duplicate backup jobs;
- enabling backup queues eligible PDFs already in the library as well as new
  imports.

The original desktop workflow is unchanged:

```bash
cd desktop
npm run dev
```

## Verification

Resetting the local database is destructive to local Supabase test data. It
does not affect the existing SQLite desktop library or any hosted project.

```bash
npx --yes supabase@2.109.1 db reset --local --no-seed
npx --yes supabase@2.109.1 test db --local

cd desktop
npm test -- --run
npm run build
npm run build:web
```

The database suite verifies:

- row-level security on all exposed synced tables;
- explicit authenticated policies and anonymous denial;
- cross-account read, update, and delete isolation;
- owner-and-library-scoped storage prefixes;
- private-bucket configuration;
- explicit server-worker access without exposing privileged credentials to the
  client.
- cloud-source backup policy behavior and idempotent replication queueing;
- client denial for encrypted OAuth credentials and service-only RPCs;
- cross-account isolation for backup status and indexed PDF passage search.

## Dedicated hosted environment

Do not link these migrations to an unrelated Supabase project. For a hosted
test or production environment:

1. Create a dedicated Research Memory Supabase project.
2. Link this repository to that project.
3. review the generated migration and run it through the normal migration
   workflow;
4. configure the production site URL and allowed auth callbacks;
5. configure only the OAuth providers the deployment is ready to support;
6. set the hosted URL and publishable key in the web deployment environment;
7. run the database isolation suite against a disposable staging project
   before production.

The browser client talks directly to the RLS-protected Data API and Storage.
Provider authorization is brokered by the connector function, which encrypts
OAuth material before it enters private tables. PDF extraction, OCR, metadata
enrichment, populating the full-text index, embeddings, remote-drive imports,
and draining backup replication jobs remain background-worker
responsibilities; this slice does not claim those workers are running.

## Remaining product milestones

- explicit opt-in migration of an existing local desktop library;
- direct Google Drive and OneDrive file browsing and import download;
- resumable background upload of queued app-backup copies and retry controls;
- cloud PDF/OCR/metadata/search workers;
- conflict-aware offline queues and downloaded-PDF caches;
- native iOS and Android packaging, secure credential storage, and deep-link
  callbacks;
- flattened annotated-PDF export in cloud mode;
- production hosting, monitoring, quotas, deletion workflows, and recovery
  drills.
