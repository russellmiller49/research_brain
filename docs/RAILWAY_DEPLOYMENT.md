# Railway beta deployment

Research Memory uses Railway for the public web container and a hosted Supabase project
for Auth, Postgres, Storage, Realtime, and Edge Functions. A Railway Postgres service alone
cannot replace those Supabase APIs.

## Repository deployment

The repository root contains:

- `Dockerfile`: reproducible Node build plus a small Caddy runtime;
- `Caddyfile`: SPA fallback, compressed assets, security headers, and `/healthz`;
- `railway.json`: Dockerfile builder, deployment health check, and restart policy.

Connect `russellmiller49/research_brain` to a Railway service on the `main` branch. Set
these service variables before the first deployment:

```dotenv
VITE_SUPABASE_URL=https://<project-ref>.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=<publishable-key>
VITE_MAC_DOWNLOAD_URL=https://github.com/russellmiller49/research_brain/releases
VITE_SOCIAL_AUTH_ENABLED=false
```

The Supabase publishable key is intended for browser clients. Never place a Supabase secret
key, service-role key, database password, OAuth client secret, or connector encryption key
in a `VITE_` variable.

Railway exposes a generated HTTPS domain after deployment. Add that exact origin to:

1. Supabase Auth site URL and redirect allow-list;
2. the `RESEARCH_MEMORY_CLOUD_APP_ORIGINS` Edge Function secret;
3. Google and Microsoft OAuth app origins after those connectors are registered.

The shared Endoreels beta deliberately keeps Supabase social sign-in disabled.
Passwordless email signup tags new accounts with
`app_scope=research_memory`, allowing the shared Auth trigger guard to skip
unrelated Endoreels learner onboarding. Enable social sign-in only after its
new-user routing has an equivalent project-safe scope.

## Supabase backend

For a new hosted project:

1. apply every file in `supabase/migrations/` in timestamp order;
2. verify security and performance advisors;
3. deploy `supabase/functions/cloud-connectors` with custom JWT verification disabled
   because the function validates user POSTs itself and OAuth callbacks use one-time state;
4. set `RESEARCH_MEMORY_CONNECTOR_TOKEN_ENCRYPTION_KEY`, `RESEARCH_MEMORY_CLOUD_APP_ORIGINS`, and
   `RESEARCH_MEMORY_CLOUD_CONNECTOR_CALLBACK_URL` as Edge Function secrets;
5. add Google/Microsoft client IDs and secrets only after provider registration.

When sharing an existing project, the migrations keep internal tables in
`research_memory_private`, grant every Research Memory object explicitly, and
do not modify default privileges for other applications in `public`.

The production connector callback is:

```text
https://<project-ref>.supabase.co/functions/v1/cloud-connectors/callback
```

## macOS download

The web client points its Mac button to `VITE_MAC_DOWNLOAD_URL`. The default is the
repository Releases page. The `Release macOS beta` workflow publishes DMG and updater
assets after Apple signing, notarization, updater, and bundle-identifier secrets are
configured. Do not distribute an unsigned development DMG to beta testers.

## Release checks

Before inviting testers:

- `curl -fsS https://<railway-domain>/healthz`;
- sign in by magic link from a fresh browser profile;
- upload, open, search, annotate, and delete/restore a disposable PDF;
- verify a second device sees the same library;
- confirm one user cannot access another user's rows or signed PDF URL;
- inspect Supabase security/performance advisors and Railway deployment logs;
- confirm the Mac download points to a signed, notarized release.
