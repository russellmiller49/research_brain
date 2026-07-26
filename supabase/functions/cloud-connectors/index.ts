import {
  createClient,
  type SupabaseClient,
} from "npm:@supabase/supabase-js@2.110.8";

type Provider = "google_drive" | "onedrive";

interface ProviderConfiguration {
  clientId: string;
  clientSecret: string;
  authorizationEndpoint: string;
  tokenEndpoint: string;
  scopes: string[];
}

interface TokenPayload {
  access_token: string;
  refresh_token?: string;
  expires_in?: number;
  expires_at?: number;
  scope?: string;
  token_type?: string;
  [key: string]: unknown;
}

interface OAuthState {
  owner_id: string;
  library_id: string;
  provider: Provider;
  encrypted_pkce_verifier: string;
  return_to: string;
}

interface DriveFolder {
  id: string;
  name: string;
  path: string;
  driveId: string;
}

class ConnectorError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status = 400,
  ) {
    super(message);
  }
}

const encoder = new TextEncoder();
const decoder = new TextDecoder();

function environment(name: string): string {
  const value = Deno.env.get(name)?.trim();
  if (!value) {
    throw new ConnectorError(
      "connector_not_configured",
      "This cloud-drive connector has not been configured by the deployment administrator.",
      503,
    );
  }
  return value;
}

function adminClient(): SupabaseClient {
  return createClient(
    environment("SUPABASE_URL"),
    environment("SUPABASE_SERVICE_ROLE_KEY"),
    {
      auth: {
        autoRefreshToken: false,
        persistSession: false,
      },
      global: {
        headers: {
          "X-Client-Info": "research-memory-cloud-connectors/0.1",
        },
      },
    },
  );
}

function allowedOrigins(): Set<string> {
  const configured = Deno.env.get("RESEARCH_MEMORY_CLOUD_APP_ORIGINS") ??
    [
      "http://127.0.0.1:1420",
      "http://127.0.0.1:1421",
      "http://localhost:1420",
      "http://localhost:1421",
      "https://research-brain-web-production.up.railway.app",
    ].join(",");
  return new Set(
    configured
      .split(",")
      .map((origin) => origin.trim())
      .filter(Boolean),
  );
}

function corsHeaders(request: Request): HeadersInit {
  const origin = request.headers.get("origin") ?? "";
  const allowed = allowedOrigins();
  return {
    ...(allowed.has(origin)
      ? { "Access-Control-Allow-Origin": origin }
      : {}),
    "Access-Control-Allow-Headers":
      "authorization, apikey, content-type, x-client-info",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

function json(
  request: Request,
  value: unknown,
  status = 200,
): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      ...corsHeaders(request),
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

function bytesToBase64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary)
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/g, "");
}

function base64UrlToBytes(value: string): Uint8Array {
  const normalized = value.replaceAll("-", "+").replaceAll("_", "/");
  const padded = normalized.padEnd(
    normalized.length + ((4 - normalized.length % 4) % 4),
    "=",
  );
  const binary = atob(padded);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function randomToken(byteLength = 32): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return bytesToBase64Url(bytes);
}

async function sha256Bytes(value: string): Promise<Uint8Array> {
  return new Uint8Array(
    await crypto.subtle.digest("SHA-256", encoder.encode(value)),
  );
}

async function sha256Hex(value: string): Promise<string> {
  return Array.from(await sha256Bytes(value))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function encryptionKey(): Promise<CryptoKey> {
  const bytes = base64UrlToBytes(
    environment("RESEARCH_MEMORY_CONNECTOR_TOKEN_ENCRYPTION_KEY"),
  );
  if (bytes.byteLength !== 32) {
    throw new ConnectorError(
      "invalid_encryption_key",
      "RESEARCH_MEMORY_CONNECTOR_TOKEN_ENCRYPTION_KEY must decode to exactly 32 bytes.",
      503,
    );
  }
  return crypto.subtle.importKey(
    "raw",
    bytes,
    { name: "AES-GCM" },
    false,
    ["encrypt", "decrypt"],
  );
}

async function encrypt(value: unknown): Promise<string> {
  const iv = new Uint8Array(12);
  crypto.getRandomValues(iv);
  const plaintext = encoder.encode(JSON.stringify(value));
  const ciphertext = new Uint8Array(
    await crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      await encryptionKey(),
      plaintext,
    ),
  );
  return JSON.stringify({
    version: 1,
    iv: bytesToBase64Url(iv),
    ciphertext: bytesToBase64Url(ciphertext),
  });
}

async function decrypt<T>(envelope: string): Promise<T> {
  const parsed = JSON.parse(envelope) as {
    version: number;
    iv: string;
    ciphertext: string;
  };
  if (
    parsed.version !== 1 ||
    typeof parsed.iv !== "string" ||
    typeof parsed.ciphertext !== "string"
  ) {
    throw new ConnectorError(
      "invalid_token_envelope",
      "The encrypted connector credential has an unsupported format.",
      500,
    );
  }
  const plaintext = await crypto.subtle.decrypt(
    {
      name: "AES-GCM",
      iv: base64UrlToBytes(parsed.iv),
    },
    await encryptionKey(),
    base64UrlToBytes(parsed.ciphertext),
  );
  return JSON.parse(decoder.decode(plaintext)) as T;
}

function providerConfiguration(provider: Provider): ProviderConfiguration {
  if (provider === "google_drive") {
    return {
      clientId: environment("RESEARCH_MEMORY_GOOGLE_DRIVE_CLIENT_ID"),
      clientSecret: environment("RESEARCH_MEMORY_GOOGLE_DRIVE_CLIENT_SECRET"),
      authorizationEndpoint: "https://accounts.google.com/o/oauth2/v2/auth",
      tokenEndpoint: "https://oauth2.googleapis.com/token",
      scopes: [
        "openid",
        "email",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.file",
      ],
    };
  }
  const tenant = Deno.env.get("RESEARCH_MEMORY_MICROSOFT_DRIVE_TENANT")?.trim() || "common";
  if (!/^[A-Za-z0-9.-]+$/.test(tenant)) {
    throw new ConnectorError(
      "invalid_microsoft_tenant",
      "RESEARCH_MEMORY_MICROSOFT_DRIVE_TENANT contains unsupported characters.",
      503,
    );
  }
  return {
    clientId: environment("RESEARCH_MEMORY_MICROSOFT_DRIVE_CLIENT_ID"),
    clientSecret: environment("RESEARCH_MEMORY_MICROSOFT_DRIVE_CLIENT_SECRET"),
    authorizationEndpoint:
      `https://login.microsoftonline.com/${tenant}/oauth2/v2.0/authorize`,
    tokenEndpoint:
      `https://login.microsoftonline.com/${tenant}/oauth2/v2.0/token`,
    scopes: [
      "openid",
      "profile",
      "email",
      "offline_access",
      "Files.ReadWrite",
    ],
  };
}

function validEncryptionEnvironment(): boolean {
  const value = Deno.env.get("RESEARCH_MEMORY_CONNECTOR_TOKEN_ENCRYPTION_KEY")?.trim();
  if (!value) return false;
  try {
    return base64UrlToBytes(value).byteLength === 32;
  } catch {
    return false;
  }
}

function providerEnvironmentConfigured(provider: Provider): boolean {
  const variables = provider === "google_drive"
    ? ["RESEARCH_MEMORY_GOOGLE_DRIVE_CLIENT_ID", "RESEARCH_MEMORY_GOOGLE_DRIVE_CLIENT_SECRET"]
    : ["RESEARCH_MEMORY_MICROSOFT_DRIVE_CLIENT_ID", "RESEARCH_MEMORY_MICROSOFT_DRIVE_CLIENT_SECRET"];
  return validEncryptionEnvironment() &&
    variables.every((name) => Boolean(Deno.env.get(name)?.trim()));
}

function callbackUrl(): string {
  return Deno.env.get("RESEARCH_MEMORY_CLOUD_CONNECTOR_CALLBACK_URL")?.trim() ||
    `${environment("SUPABASE_URL")}/functions/v1/cloud-connectors/callback`;
}

function parseProvider(value: unknown): Provider {
  if (value === "google_drive" || value === "onedrive") return value;
  throw new ConnectorError(
    "unsupported_provider",
    "Choose Google Drive or OneDrive.",
  );
}

function safeReturnTo(value: unknown): URL {
  if (typeof value !== "string" || value.length > 4096) {
    throw new ConnectorError(
      "invalid_return_url",
      "The app return URL is invalid.",
    );
  }
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new ConnectorError(
      "invalid_return_url",
      "The app return URL is invalid.",
    );
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    !allowedOrigins().has(url.origin) ||
    url.username ||
    url.password
  ) {
    throw new ConnectorError(
      "return_url_not_allowed",
      "The app return URL is not in RESEARCH_MEMORY_CLOUD_APP_ORIGINS.",
    );
  }
  return url;
}

async function authenticatedContext(
  request: Request,
  admin: SupabaseClient,
): Promise<{ userId: string; libraryId: string }> {
  const authorization = request.headers.get("authorization") ?? "";
  const token = authorization.match(/^Bearer\s+(.+)$/i)?.[1];
  if (!token) {
    throw new ConnectorError(
      "authentication_required",
      "Sign in before connecting a cloud drive.",
      401,
    );
  }
  const userResponse = await admin.auth.getUser(token);
  if (userResponse.error || !userResponse.data.user) {
    throw new ConnectorError(
      "invalid_session",
      "Your session expired. Sign in and try again.",
      401,
    );
  }
  const userId = userResponse.data.user.id;
  const libraryResponse = await admin
    .from("libraries")
    .select("id")
    .eq("owner_id", userId)
    .is("deleted_at", null)
    .single();
  if (libraryResponse.error) {
    throw new ConnectorError(
      "library_not_found",
      "Create your synced library before connecting a drive.",
      404,
    );
  }
  return { userId, libraryId: libraryResponse.data.id };
}

async function authorize(
  request: Request,
  body: Record<string, unknown>,
): Promise<Response> {
  const admin = adminClient();
  const provider = parseProvider(body.provider);
  const returnTo = safeReturnTo(body.returnTo);
  const { userId, libraryId } = await authenticatedContext(request, admin);
  const configuration = providerConfiguration(provider);
  await encryptionKey();
  const state = randomToken();
  const verifier = randomToken(48);
  const challenge = bytesToBase64Url(await sha256Bytes(verifier));
  const stateResponse = await admin.rpc("create_cloud_oauth_state", {
    p_state_hash: await sha256Hex(state),
    p_owner_id: userId,
    p_library_id: libraryId,
    p_provider: provider,
    p_encrypted_pkce_verifier: await encrypt(verifier),
    p_return_to: returnTo.toString(),
    p_expires_at: new Date(Date.now() + 10 * 60_000).toISOString(),
  });
  if (stateResponse.error) {
    throw new ConnectorError(
      "oauth_state_failed",
      "Could not start the secure cloud-drive connection.",
      500,
    );
  }

  const authorizationUrl = new URL(configuration.authorizationEndpoint);
  authorizationUrl.searchParams.set("client_id", configuration.clientId);
  authorizationUrl.searchParams.set("redirect_uri", callbackUrl());
  authorizationUrl.searchParams.set("response_type", "code");
  authorizationUrl.searchParams.set("scope", configuration.scopes.join(" "));
  authorizationUrl.searchParams.set("state", state);
  authorizationUrl.searchParams.set("code_challenge", challenge);
  authorizationUrl.searchParams.set("code_challenge_method", "S256");
  if (provider === "google_drive") {
    authorizationUrl.searchParams.set("access_type", "offline");
    authorizationUrl.searchParams.set("include_granted_scopes", "true");
    authorizationUrl.searchParams.set("prompt", "consent");
  } else {
    authorizationUrl.searchParams.set("response_mode", "query");
  }
  return json(request, { authorizationUrl: authorizationUrl.toString() });
}

async function connectorStatus(request: Request): Promise<Response> {
  const admin = adminClient();
  await authenticatedContext(request, admin);
  return json(request, {
    serviceAvailable: true,
    providers: {
      google_drive: providerEnvironmentConfigured("google_drive"),
      onedrive: providerEnvironmentConfigured("onedrive"),
    },
  });
}

async function providerFetch(
  url: string,
  accessToken: string,
  init: RequestInit = {},
): Promise<Response> {
  return fetch(url, {
    ...init,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
}

async function responseJson<T>(
  response: Response,
  code: string,
  message: string,
): Promise<T> {
  if (!response.ok) {
    const providerBody = await response.text();
    console.error(code, response.status, providerBody.slice(0, 1_000));
    throw new ConnectorError(code, message, 502);
  }
  return await response.json() as T;
}

async function accountIdentity(
  provider: Provider,
  accessToken: string,
): Promise<{ label: string; email: string }> {
  if (provider === "google_drive") {
    const response = await providerFetch(
      "https://openidconnect.googleapis.com/v1/userinfo",
      accessToken,
    );
    const profile = await responseJson<{
      name?: string;
      email?: string;
    }>(
      response,
      "google_profile_failed",
      "Google connected, but the account profile could not be read.",
    );
    return {
      label: profile.name ?? profile.email ?? "Google Drive",
      email: profile.email ?? "",
    };
  }
  const response = await providerFetch(
    "https://graph.microsoft.com/v1.0/me" +
      "?$select=displayName,mail,userPrincipalName",
    accessToken,
  );
  const profile = await responseJson<{
    displayName?: string;
    mail?: string;
    userPrincipalName?: string;
  }>(
    response,
    "microsoft_profile_failed",
    "Microsoft connected, but the account profile could not be read.",
  );
  return {
    label: profile.displayName ?? profile.userPrincipalName ?? "OneDrive",
    email: profile.mail ?? profile.userPrincipalName ?? "",
  };
}

function escapedGoogleQueryValue(value: string): string {
  return value.replaceAll("\\", "\\\\").replaceAll("'", "\\'");
}

async function ensureBackupFolder(
  provider: Provider,
  accessToken: string,
): Promise<DriveFolder> {
  const folderName = "Research Memory Backup";
  if (provider === "google_drive") {
    const query = [
      `name = '${escapedGoogleQueryValue(folderName)}'`,
      "mimeType = 'application/vnd.google-apps.folder'",
      "'root' in parents",
      "trashed = false",
    ].join(" and ");
    const listUrl = new URL("https://www.googleapis.com/drive/v3/files");
    listUrl.searchParams.set("q", query);
    listUrl.searchParams.set("fields", "files(id,name)");
    listUrl.searchParams.set("pageSize", "1");
    const listResponse = await providerFetch(listUrl.toString(), accessToken);
    const existing = await responseJson<{
      files?: Array<{ id: string; name: string }>;
    }>(
      listResponse,
      "google_folder_lookup_failed",
      "Could not check the Google Drive backup folder.",
    );
    const folder = existing.files?.[0];
    if (folder) {
      return {
        id: folder.id,
        name: folder.name,
        path: folder.name,
        driveId: "",
      };
    }
    const createResponse = await providerFetch(
      "https://www.googleapis.com/drive/v3/files?fields=id,name",
      accessToken,
      {
        method: "POST",
        body: JSON.stringify({
          name: folderName,
          mimeType: "application/vnd.google-apps.folder",
          parents: ["root"],
        }),
      },
    );
    const created = await responseJson<{ id: string; name: string }>(
      createResponse,
      "google_folder_create_failed",
      "Could not create the Google Drive backup folder.",
    );
    return {
      id: created.id,
      name: created.name,
      path: created.name,
      driveId: "",
    };
  }

  const lookupResponse = await providerFetch(
    `https://graph.microsoft.com/v1.0/me/drive/root:/${encodeURIComponent(folderName)}`,
    accessToken,
  );
  if (lookupResponse.ok) {
    const existing = await lookupResponse.json() as {
      id: string;
      name: string;
      parentReference?: { driveId?: string };
    };
    return {
      id: existing.id,
      name: existing.name,
      path: existing.name,
      driveId: existing.parentReference?.driveId ?? "",
    };
  }
  if (lookupResponse.status !== 404) {
    await responseJson(
      lookupResponse,
      "microsoft_folder_lookup_failed",
      "Could not check the OneDrive backup folder.",
    );
  }
  const createResponse = await providerFetch(
    "https://graph.microsoft.com/v1.0/me/drive/root/children",
    accessToken,
    {
      method: "POST",
      body: JSON.stringify({
        name: folderName,
        folder: {},
        "@microsoft.graph.conflictBehavior": "fail",
      }),
    },
  );
  const created = await responseJson<{
    id: string;
    name: string;
    parentReference?: { driveId?: string };
  }>(
    createResponse,
    "microsoft_folder_create_failed",
    "Could not create the OneDrive backup folder.",
  );
  return {
    id: created.id,
    name: created.name,
    path: created.name,
    driveId: created.parentReference?.driveId ?? "",
  };
}

async function tokenExchange(
  provider: Provider,
  code: string,
  verifier: string,
): Promise<TokenPayload> {
  const configuration = providerConfiguration(provider);
  const parameters = new URLSearchParams({
    client_id: configuration.clientId,
    client_secret: configuration.clientSecret,
    code,
    code_verifier: verifier,
    redirect_uri: callbackUrl(),
    grant_type: "authorization_code",
  });
  if (provider === "onedrive") {
    parameters.set("scope", configuration.scopes.join(" "));
  }
  const response = await fetch(configuration.tokenEndpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: parameters,
  });
  const token = await responseJson<TokenPayload>(
    response,
    "token_exchange_failed",
    "The cloud provider did not accept the authorization response.",
  );
  if (!token.access_token) {
    throw new ConnectorError(
      "missing_access_token",
      "The cloud provider did not return an access token.",
      502,
    );
  }
  token.expires_at = Math.floor(Date.now() / 1_000) +
    Number(token.expires_in ?? 3_600);
  return token;
}

async function consumeState(
  admin: SupabaseClient,
  state: string,
): Promise<OAuthState> {
  const response = await admin.rpc("consume_cloud_oauth_state", {
    p_state_hash: await sha256Hex(state),
  });
  const row = response.data?.[0] as OAuthState | undefined;
  if (response.error || !row) {
    throw new ConnectorError(
      "invalid_oauth_state",
      "This cloud-drive connection expired or was already used.",
      400,
    );
  }
  return row;
}

function redirectWith(
  returnTo: string,
  parameter: "connector" | "connector_error",
  value: string,
): Response {
  const url = safeReturnTo(returnTo);
  url.searchParams.set(parameter, value);
  return Response.redirect(url.toString(), 302);
}

async function callback(request: Request): Promise<Response> {
  const admin = adminClient();
  const callbackRequest = new URL(request.url);
  const stateValue = callbackRequest.searchParams.get("state");
  if (!stateValue) {
    throw new ConnectorError(
      "missing_oauth_state",
      "The cloud provider returned no OAuth state.",
    );
  }
  const state = await consumeState(admin, stateValue);
  const providerError = callbackRequest.searchParams.get("error");
  if (providerError) {
    return redirectWith(
      state.return_to,
      "connector_error",
      providerError.slice(0, 100),
    );
  }
  const code = callbackRequest.searchParams.get("code");
  if (!code) {
    return redirectWith(
      state.return_to,
      "connector_error",
      "missing_authorization_code",
    );
  }

  try {
    const verifier = await decrypt<string>(state.encrypted_pkce_verifier);
    const token = await tokenExchange(state.provider, code, verifier);
    const identity = await accountIdentity(
      state.provider,
      token.access_token,
    );
    const configuration = providerConfiguration(state.provider);
    const existingConnection = await admin
      .from("cloud_connections")
      .select("id")
      .eq("library_id", state.library_id)
      .eq("provider", state.provider)
      .maybeSingle();
    if (existingConnection.error) {
      throw new ConnectorError(
        "connection_lookup_failed",
        "Could not save the cloud-drive connection.",
        500,
      );
    }

    if (!token.refresh_token && existingConnection.data?.id) {
      const previousSecret = await admin.rpc(
        "read_cloud_connection_secret",
        { p_connection_id: existingConnection.data.id },
      );
      const previousEnvelope = previousSecret.data?.[0]
        ?.encrypted_token_payload;
      if (previousEnvelope) {
        const previous = await decrypt<TokenPayload>(previousEnvelope);
        token.refresh_token = previous.refresh_token;
      }
    }

    const connectionResponse = await admin
      .from("cloud_connections")
      .upsert(
        {
          ...(existingConnection.data?.id
            ? { id: existingConnection.data.id }
            : {}),
          library_id: state.library_id,
          owner_id: state.owner_id,
          provider: state.provider,
          status: "connected",
          account_label: identity.label,
          account_email: identity.email,
          scopes: token.scope?.split(/\s+/).filter(Boolean) ??
            configuration.scopes,
          last_checked_at: new Date().toISOString(),
          last_error_code: null,
        },
        { onConflict: "library_id,provider" },
      )
      .select("id")
      .single();
    if (connectionResponse.error) {
      throw new ConnectorError(
        "connection_save_failed",
        "Could not save the cloud-drive connection.",
        500,
      );
    }
    const connectionId = connectionResponse.data.id;
    const secretResponse = await admin.rpc(
      "upsert_cloud_connection_secret",
      {
        p_connection_id: connectionId,
        p_library_id: state.library_id,
        p_owner_id: state.owner_id,
        p_encrypted_token_payload: await encrypt(token),
        p_token_expires_at: new Date(
          Number(token.expires_at) * 1_000,
        ).toISOString(),
      },
    );
    if (secretResponse.error) {
      throw new ConnectorError(
        "credential_save_failed",
        "Could not store the encrypted cloud-drive credential.",
        500,
      );
    }

    try {
      const folder = await ensureBackupFolder(
        state.provider,
        token.access_token,
      );
      const targetResponse = await admin
        .from("backup_targets")
        .upsert(
          {
            library_id: state.library_id,
            owner_id: state.owner_id,
            connection_id: connectionId,
            remote_drive_id: folder.driveId,
            remote_folder_id: folder.id,
            remote_folder_name: folder.name,
            remote_folder_path: folder.path,
            last_verified_at: new Date().toISOString(),
            last_error_code: null,
          },
          { onConflict: "library_id" },
        );
      if (targetResponse.error) throw targetResponse.error;
    } catch (folderError) {
      console.error("backup_folder_setup_failed", folderError);
      await admin
        .from("backup_targets")
        .upsert(
          {
            library_id: state.library_id,
            owner_id: state.owner_id,
            connection_id: connectionId,
            enabled: false,
            last_error_code: "backup_folder_setup_failed",
          },
          { onConflict: "library_id" },
        );
    }
    return redirectWith(state.return_to, "connector", state.provider);
  } catch (error) {
    const code = error instanceof ConnectorError
      ? error.code
      : "connector_callback_failed";
    console.error(code, error);
    return redirectWith(state.return_to, "connector_error", code);
  }
}

async function handler(request: Request): Promise<Response> {
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders(request) });
  }
  const path = new URL(request.url).pathname.replace(/\/+$/, "");
  if (request.method === "GET" && path.endsWith("/callback")) {
    return callback(request);
  }
  if (request.method !== "POST") {
    return json(
      request,
      { error: "method_not_allowed", message: "Use POST for this action." },
      405,
    );
  }
  const body = await request.json() as Record<string, unknown>;
  if (body.action === "status") return connectorStatus(request);
  if (body.action === "authorize") return authorize(request, body);
  return json(
    request,
    {
      error: "unsupported_action",
      message: "This connector action is not available.",
    },
    400,
  );
}

Deno.serve(async (request) => {
  try {
    return await handler(request);
  } catch (error) {
    const connectorError = error instanceof ConnectorError
      ? error
      : new ConnectorError(
        "connector_internal_error",
        "The cloud-drive connector could not complete this request.",
        500,
      );
    if (connectorError.status >= 500) {
      console.error(connectorError.code, error);
    }
    return json(
      request,
      {
        error: connectorError.code,
        message: connectorError.message,
      },
      connectorError.status,
    );
  }
});
