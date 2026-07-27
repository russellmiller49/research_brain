import {
  createClient,
  type Provider,
  type RealtimeChannel,
  type SupabaseClient,
} from "@supabase/supabase-js";
import { Upload } from "tus-js-client";
import type { ReaderCore } from "../lib/api";
import type {
  Annotation,
  ArticleAsset,
  ArticleDetail,
  ArticleSummary,
  EntityId,
  ImportJob,
  Project,
  TrashArticle,
} from "../types";
import type {
  Database,
  Json,
  Tables,
  TablesInsert,
  TablesUpdate,
} from "./database.types";

const PDF_BUCKET = "library-pdfs";
const MAX_PDF_BYTES = 250 * 1024 * 1024;
const TUS_CHUNK_BYTES = 6 * 1024 * 1024;

type LibraryRow = Tables<"libraries">;
type ArticleRow = Tables<"articles">;
type AssetRow = Tables<"article_assets">;
type AnnotationRow = Tables<"annotations">;
type JobRow = Tables<"jobs">;
type CloudConnectionRow = Tables<"cloud_connections">;
type BackupTargetRow = Tables<"backup_targets">;
type BackupReplicationRow = Tables<"backup_replications">;

export type CloudDriveProvider = "google_drive" | "onedrive";

export interface CloudUser {
  id: string;
  email: string;
}

export interface CloudLibrary {
  id: string;
  ownerId: string;
  name: string;
}

export interface UploadProgress {
  fileName: string;
  bytesSent: number;
  bytesTotal: number;
}

export interface CloudConfiguration {
  supabaseUrl: string;
  publishableKey: string;
}

export interface CloudDashboard {
  articleCount: number;
  unreadCount: number;
  readingCount: number;
  annotationCount: number;
  projectCount: number;
  activeJobCount: number;
  reviewCount: number;
  recentArticles: ArticleSummary[];
}

export interface CloudSearchQuery {
  text: string;
  yearMin?: number;
  yearMax?: number;
  readingStatus?: string;
  projectId?: EntityId;
}

export interface CloudSearchResult extends ArticleSummary {
  matchSource?: "metadata" | "pdf_passage";
  matchSnippet?: string;
  matchPageNumber?: number;
}

export interface CloudDriveConnection {
  id: string;
  provider: CloudDriveProvider;
  status:
    | "pending"
    | "connected"
    | "reauthorization_required"
    | "error"
    | "disconnected";
  accountLabel: string;
  accountEmail: string;
  lastCheckedAt: string | null;
  lastErrorCode: string | null;
}

export interface CloudConnectorStatus {
  serviceAvailable: boolean;
  providers: Record<CloudDriveProvider, boolean>;
}

export interface CloudBackupSettings {
  id: string;
  connectionId: string | null;
  enabled: boolean;
  copyDeviceImports: boolean;
  copyCloudImports: boolean;
  folderName: string;
  folderPath: string;
  queuedCopies: number;
  completedCopies: number;
  failedCopies: number;
  lastErrorCode: string | null;
}

export interface CloudBackupSettingsPatch {
  enabled?: boolean;
  copyDeviceImports?: boolean;
  copyCloudImports?: boolean;
}

export interface PasswordSignUpResult {
  requiresEmailConfirmation: boolean;
}

export interface CloudLibraryService extends ReaderCore {
  currentUser(): Promise<CloudUser | null>;
  onAuthChange(callback: (user: CloudUser | null) => void): () => void;
  signInWithPassword(email: string, password: string): Promise<void>;
  signUpWithPassword(
    email: string,
    password: string,
  ): Promise<PasswordSignUpResult>;
  requestPasswordReset(email: string): Promise<void>;
  updatePassword(password: string): Promise<void>;
  signInWithProvider(provider: "google" | "apple" | "azure"): Promise<void>;
  signOut(): Promise<void>;
  ensurePersonalLibrary(user: CloudUser): Promise<CloudLibrary>;
  updateLibraryName(name: string): Promise<CloudLibrary>;
  dashboard(): Promise<CloudDashboard>;
  listArticles(query?: string): Promise<ArticleSummary[]>;
  searchArticles(query: CloudSearchQuery): Promise<CloudSearchResult[]>;
  driveConnections(): Promise<CloudDriveConnection[]>;
  connectorStatus(): Promise<CloudConnectorStatus>;
  connectDrive(provider: CloudDriveProvider): Promise<void>;
  backupSettings(): Promise<CloudBackupSettings>;
  updateBackupSettings(
    patch: CloudBackupSettingsPatch,
  ): Promise<CloudBackupSettings>;
  article(articleId: EntityId): Promise<ArticleDetail>;
  createProject(name: string, description: string): Promise<Project>;
  projectArticles(projectId: EntityId): Promise<ArticleSummary[]>;
  removeProjectArticle(
    projectId: EntityId,
    articleId: EntityId,
  ): Promise<void>;
  jobs(): Promise<ImportJob[]>;
  trash(): Promise<TrashArticle[]>;
  restoreArticle(articleId: EntityId): Promise<void>;
  uploadPdf(
    file: File,
    onProgress?: (progress: UploadProgress) => void,
  ): Promise<ArticleDetail>;
  subscribeToLibrary(ownerId: string, onChange: () => void): () => void;
}

function requiredCloudConfiguration(): CloudConfiguration {
  const supabaseUrl = import.meta.env.VITE_SUPABASE_URL?.trim();
  const publishableKey =
    import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY?.trim();
  if (!supabaseUrl || !publishableKey) {
    throw new Error(
      "Cloud mode needs VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY.",
    );
  }
  if (
    publishableKey.startsWith("sb_secret_") ||
    publishableKey.includes("service_role")
  ) {
    throw new Error(
      "Use a Supabase publishable key in the client. Secret and service-role keys are server-only.",
    );
  }
  try {
    new URL(supabaseUrl);
  } catch {
    throw new Error("VITE_SUPABASE_URL must be a valid URL.");
  }
  return { supabaseUrl, publishableKey };
}

function toCloudUser(
  user: { id: string; email?: string | null } | null,
): CloudUser | null {
  if (!user) return null;
  return { id: user.id, email: user.email ?? "" };
}

function clearAuthCallbackParameters(url: URL): void {
  for (const parameter of [
    "code",
    "error",
    "error_code",
    "error_description",
  ]) {
    url.searchParams.delete(parameter);
  }
  window.history.replaceState(
    window.history.state,
    document.title,
    `${url.pathname}${url.search}${url.hash.includes("error=") ? "" : url.hash}`,
  );
}

function requireStringId(value: EntityId, label: string): string {
  if (typeof value !== "string" || !value) {
    throw new Error(`${label} is not a synced-library identifier.`);
  }
  return value;
}

function articleSummary(row: ArticleRow): ArticleSummary {
  return {
    id: row.id,
    title: row.title,
    authors: row.authors,
    journal: row.journal,
    publication_year: row.publication_year,
    source_type: row.source_type,
    reading_status: row.reading_status,
    importance: row.importance,
    page_count: row.page_count,
    why_saved: row.why_saved,
    extraction_status: row.extraction_status,
    review_state: row.review_state,
  };
}

function importJob(row: JobRow): ImportJob {
  const statuses: ImportJob["status"][] = [
    "queued",
    "running",
    "paused",
    "succeeded",
    "failed",
    "canceled",
  ];
  const status = statuses.includes(row.status as ImportJob["status"])
    ? (row.status as ImportJob["status"])
    : "failed";
  const progress =
    row.progress_total > 0
      ? Math.min(1, row.progress_current / row.progress_total)
      : status === "succeeded"
        ? 1
        : 0;
  return {
    id: row.id,
    type: row.type,
    source: row.source,
    stage: row.stage,
    status,
    progress_current: row.progress_current,
    progress_total: row.progress_total,
    progress,
    retryable: row.retryable,
    error_code: row.error_code,
    issue_count: row.issue_count,
    created_at: row.created_at,
    updated_at: row.updated_at,
  };
}

function cloudDriveConnection(
  row: CloudConnectionRow,
): CloudDriveConnection {
  return {
    id: row.id,
    provider: row.provider as CloudDriveProvider,
    status: row.status as CloudDriveConnection["status"],
    accountLabel: row.account_label,
    accountEmail: row.account_email,
    lastCheckedAt: row.last_checked_at,
    lastErrorCode: row.last_error_code,
  };
}

function replicationCounts(rows: BackupReplicationRow[]) {
  return rows.reduce(
    (counts, row) => {
      if (row.status === "succeeded" || row.status === "skipped") {
        counts.completedCopies += 1;
      } else if (row.status === "failed") {
        counts.failedCopies += 1;
      } else if (row.status === "queued" || row.status === "running") {
        counts.queuedCopies += 1;
      }
      return counts;
    },
    { queuedCopies: 0, completedCopies: 0, failedCopies: 0 },
  );
}

function cloudBackupSettings(
  row: BackupTargetRow,
  replications: BackupReplicationRow[],
): CloudBackupSettings {
  return {
    id: row.id,
    connectionId: row.connection_id,
    enabled: row.enabled,
    copyDeviceImports: row.copy_device_imports,
    copyCloudImports: row.copy_cloud_imports,
    folderName: row.remote_folder_name,
    folderPath: row.remote_folder_path,
    lastErrorCode: row.last_error_code,
    ...replicationCounts(replications),
  };
}

function articleAsset(row: AssetRow): ArticleAsset {
  return {
    id: row.id,
    article_id: row.article_id,
    sha256: row.sha256,
    file_name: row.file_name,
    role: row.role,
    version_label: row.version_label,
    source_kind: row.source_kind,
    availability: row.availability,
    is_primary: row.is_primary,
    size_bytes: row.size_bytes,
  };
}

function stripHeadlineMarkup(value: string): string {
  return value.replaceAll(/<\/?b>/gi, "").replaceAll(/\s+/g, " ").trim();
}

function numericArray(value: Json): number[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is number => typeof item === "number");
}

function annotation(row: AnnotationRow): Annotation {
  return {
    id: row.id,
    article_id: row.article_id,
    asset_id: row.asset_id,
    page_number: row.page_number,
    annotation_type: row.annotation_type as Annotation["annotation_type"],
    color: row.color,
    quad_points: numericArray(row.quad_points),
    selected_text: row.selected_text,
    context_hash: row.context_hash,
    comment: row.comment,
    created_at: row.created_at,
    updated_at: row.updated_at,
  };
}

function titleFromFileName(fileName: string): string {
  const title = fileName
    .replace(/\.pdf$/i, "")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return title || "Untitled paper";
}

async function sha256(file: File): Promise<string> {
  const bytes = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function resumableUploadEndpoint(supabaseUrl: string): string {
  const url = new URL(supabaseUrl);
  if (url.hostname.endsWith(".supabase.co")) {
    const projectRef = url.hostname.split(".")[0];
    if (projectRef) {
      return `${url.protocol}//${projectRef}.storage.supabase.co/storage/v1/upload/resumable`;
    }
  }
  return `${url.origin}/storage/v1/upload/resumable`;
}

function triggerDownload(contents: BlobPart, type: string, fileName: string) {
  const url = URL.createObjectURL(new Blob([contents], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function escapeXml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function escapeRis(value: string): string {
  return value.replaceAll(/\r?\n/g, " ");
}

interface ConnectorFailure {
  code: string;
  message: string;
}

const unavailableConnectorMessage =
  "The cloud-drive connector is stopped in this local build. Start it with “npm run dev:connectors”, then try again.";

function connectorProviderLabel(provider: CloudDriveProvider): string {
  return provider === "google_drive" ? "Google Drive" : "OneDrive";
}

function isUnavailableConnectorFailure(failure: ConnectorFailure): boolean {
  const text = `${failure.code} ${failure.message}`.toLocaleLowerCase();
  return [
    "name resolution failed",
    "failed to send a request",
    "failed to fetch",
    "fetch failed",
    "connection refused",
    "networkerror",
  ].some((fragment) => text.includes(fragment));
}

async function connectorFailure(value: unknown): Promise<ConnectorFailure> {
  const error = value as {
    context?: unknown;
    message?: unknown;
    name?: unknown;
  };
  let code = typeof error.name === "string" ? error.name : "";
  let message = typeof error.message === "string" ? error.message : "";
  if (error.context instanceof Response) {
    try {
      const payload = await error.context.clone().json() as {
        error?: unknown;
        message?: unknown;
      };
      if (typeof payload.error === "string") code = payload.error;
      if (typeof payload.message === "string") message = payload.message;
    } catch {
      // Network-level Functions errors do not always have a JSON response.
    }
  }
  return { code, message };
}

function connectorFailureMessage(
  provider: CloudDriveProvider,
  failure: ConnectorFailure,
): string {
  if (isUnavailableConnectorFailure(failure)) {
    return unavailableConnectorMessage;
  }
  if (failure.code === "connector_not_configured") {
    return `${connectorProviderLabel(provider)} needs OAuth setup in this local build. Add its client ID and secret to supabase/functions/.env.local, then restart the connector.`;
  }
  return failure.message ||
    "The cloud-drive connector could not complete this request.";
}

export class SupabaseCloudLibraryService implements CloudLibraryService {
  private readonly supabase: SupabaseClient<Database>;
  private authInitialization: Promise<CloudUser | null> | undefined;
  private cachedContext:
    | { user: CloudUser; library: CloudLibrary }
    | undefined;

  constructor(private readonly configuration: CloudConfiguration) {
    this.supabase = createClient<Database>(
      configuration.supabaseUrl,
      configuration.publishableKey,
      {
        auth: {
          flowType: "pkce",
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: false,
        },
        global: {
          headers: {
            "X-Client-Info": "research-memory-web/0.2",
          },
        },
      },
    );
  }

  async currentUser(): Promise<CloudUser | null> {
    this.authInitialization ??= this.initializeAuth();
    return this.authInitialization;
  }

  private async initializeAuth(): Promise<CloudUser | null> {
    const callbackUrl = new URL(window.location.href);
    const code = callbackUrl.searchParams.get("code");
    const callbackError =
      callbackUrl.searchParams.get("error_description") ??
      callbackUrl.searchParams.get("error");
    if (code) {
      const exchanged = await this.supabase.auth.exchangeCodeForSession(code);
      if (!exchanged.error) {
        clearAuthCallbackParameters(callbackUrl);
        return toCloudUser(exchanged.data.user);
      }

      // A previous client instance may already have exchanged the callback
      // during a hot reload. Accept that session only after the auth server
      // confirms the user still exists.
      const validated = await this.supabase.auth.getUser();
      if (!validated.error && validated.data.user) {
        clearAuthCallbackParameters(callbackUrl);
        return toCloudUser(validated.data.user);
      }
      await this.supabase.auth.signOut({ scope: "local" });
      clearAuthCallbackParameters(callbackUrl);
      throw new Error(exchanged.error.message);
    }

    if (
      callbackUrl.searchParams.has("error") ||
      callbackUrl.hash.includes("error=")
    ) {
      clearAuthCallbackParameters(callbackUrl);
    }

    // getUser verifies the cached token with the auth server. This prevents a
    // deleted local-development account from being used to create library rows.
    const { data, error } = await this.supabase.auth.getUser();
    if (error) {
      await this.supabase.auth.signOut({ scope: "local" });
      if (callbackError) throw new Error(callbackError);
      return null;
    }
    return toCloudUser(data.user);
  }

  onAuthChange(callback: (user: CloudUser | null) => void): () => void {
    const { data } = this.supabase.auth.onAuthStateChange((event, session) => {
      if (event === "INITIAL_SESSION") return;
      this.cachedContext = undefined;
      const user = toCloudUser(session?.user ?? null);
      this.authInitialization = Promise.resolve(user);
      callback(user);
    });
    return () => data.subscription.unsubscribe();
  }

  async signInWithPassword(email: string, password: string): Promise<void> {
    const { error } = await this.supabase.auth.signInWithPassword({
      email,
      password,
    });
    if (error) throw new Error(error.message);
  }

  async signUpWithPassword(
    email: string,
    password: string,
  ): Promise<PasswordSignUpResult> {
    const redirectTo = new URL(
      import.meta.env.BASE_URL || "/",
      window.location.origin,
    ).toString();
    const { data, error } = await this.supabase.auth.signUp({
      email,
      password,
      options: {
        emailRedirectTo: redirectTo,
        data: { app_scope: "research_memory" },
      },
    });
    if (error) throw new Error(error.message);
    return { requiresEmailConfirmation: data.session == null };
  }

  async requestPasswordReset(email: string): Promise<void> {
    const redirectTo = new URL(
      "/reset-password",
      window.location.origin,
    ).toString();
    const { error } = await this.supabase.auth.resetPasswordForEmail(email, {
      redirectTo,
    });
    if (error) throw new Error(error.message);
  }

  async updatePassword(password: string): Promise<void> {
    const { error } = await this.supabase.auth.updateUser({ password });
    if (error) throw new Error(error.message);
  }

  async signInWithProvider(
    provider: "google" | "apple" | "azure",
  ): Promise<void> {
    const redirectTo = new URL(
      import.meta.env.BASE_URL || "/",
      window.location.origin,
    ).toString();
    const options =
      provider === "azure"
        ? { redirectTo, scopes: "email openid profile" }
        : { redirectTo };
    const { error } = await this.supabase.auth.signInWithOAuth({
      provider: provider as Provider,
      options,
    });
    if (error) throw new Error(error.message);
  }

  async signOut(): Promise<void> {
    const { error } = await this.supabase.auth.signOut();
    if (error) throw new Error(error.message);
    this.cachedContext = undefined;
    this.authInitialization = Promise.resolve(null);
  }

  async ensurePersonalLibrary(user: CloudUser): Promise<CloudLibrary> {
    if (this.cachedContext?.user.id === user.id) {
      return this.cachedContext.library;
    }
    const existing = await this.supabase
      .from("libraries")
      .select("*")
      .eq("owner_id", user.id)
      .is("deleted_at", null)
      .maybeSingle();
    if (existing.error) throw new Error(existing.error.message);
    let row: LibraryRow | null = existing.data;
    if (!row) {
      const created = await this.supabase
        .from("libraries")
        .insert({ owner_id: user.id, name: "My Research Library" })
        .select("*")
        .single();
      if (created.error?.code === "23505") {
        const raced = await this.supabase
          .from("libraries")
          .select("*")
          .eq("owner_id", user.id)
          .is("deleted_at", null)
          .single();
        if (raced.error) throw new Error(raced.error.message);
        row = raced.data;
      } else if (created.error) {
        throw new Error(created.error.message);
      } else {
        row = created.data;
      }
    }
    const library = {
      id: row.id,
      ownerId: row.owner_id,
      name: row.name,
    };
    this.cachedContext = { user, library };
    return library;
  }

  async updateLibraryName(name: string): Promise<CloudLibrary> {
    const nextName = name.trim();
    if (!nextName) throw new Error("Library name cannot be empty.");
    const { user, library } = await this.context();
    const response = await this.supabase
      .from("libraries")
      .update({ name: nextName.slice(0, 500) })
      .eq("id", library.id)
      .select("*")
      .single();
    if (response.error) throw new Error(response.error.message);
    const updated = {
      id: response.data.id,
      ownerId: response.data.owner_id,
      name: response.data.name,
    };
    this.cachedContext = { user, library: updated };
    return updated;
  }

  private async context(): Promise<{
    user: CloudUser;
    library: CloudLibrary;
  }> {
    const user = await this.currentUser();
    if (!user) throw new Error("Your session has expired. Sign in again.");
    const library = await this.ensurePersonalLibrary(user);
    return { user, library };
  }

  async listArticles(query = ""): Promise<ArticleSummary[]> {
    return this.searchArticles({ text: query });
  }

  async searchArticles(
    query: CloudSearchQuery,
  ): Promise<CloudSearchResult[]> {
    const { library } = await this.context();
    let projectArticleIds: Set<string> | undefined;
    if (query.projectId != null) {
      const projectId = requireStringId(query.projectId, "Project");
      const memberships = await this.supabase
        .from("project_articles")
        .select("article_id")
        .eq("library_id", library.id)
        .eq("project_id", projectId);
      if (memberships.error) throw new Error(memberships.error.message);
      projectArticleIds = new Set(
        memberships.data.map((membership) => membership.article_id),
      );
      if (!projectArticleIds.size) return [];
    }

    let request = this.supabase
      .from("articles")
      .select("*")
      .eq("library_id", library.id)
      .is("deleted_at", null)
      .order("updated_at", { ascending: false })
      .limit(500);
    if (query.yearMin != null) {
      request = request.gte("publication_year", query.yearMin);
    }
    if (query.yearMax != null) {
      request = request.lte("publication_year", query.yearMax);
    }
    if (query.readingStatus) {
      request = request.eq("reading_status", query.readingStatus);
    }
    const needle = query.text.trim().toLocaleLowerCase();
    const [response, passageResponse] = await Promise.all([
      request,
      needle
        ? this.supabase.rpc("search_library_chunks", {
            p_library_id: library.id,
            p_query: query.text.trim(),
            p_limit: 100,
          })
        : Promise.resolve({ data: [], error: null }),
    ]);
    if (response.error) throw new Error(response.error.message);
    if (passageResponse.error) {
      throw new Error(passageResponse.error.message);
    }
    const passageHits = new Map<
      string,
      {
        pageNumber: number;
        rank: number;
        snippet: string;
      }
    >();
    for (const hit of passageResponse.data ?? []) {
      const previous = passageHits.get(hit.article_id);
      if (!previous || hit.match_rank > previous.rank) {
        passageHits.set(hit.article_id, {
          pageNumber: hit.page_number,
          rank: hit.match_rank,
          snippet: stripHeadlineMarkup(hit.snippet),
        });
      }
    }
    const matchingProjectRows = projectArticleIds
      ? response.data.filter((row) => projectArticleIds.has(row.id))
      : response.data;
    const rows = needle
      ? matchingProjectRows.filter((row) =>
          [
            row.title,
            row.authors,
            row.journal,
            row.doi,
            row.pmid,
            row.abstract,
            row.user_summary,
            row.why_saved,
          ].some(
            (value) => value.toLocaleLowerCase().includes(needle),
          ) || passageHits.has(row.id),
        )
      : matchingProjectRows;
    return rows
      .map((row): CloudSearchResult => {
        const passage = passageHits.get(row.id);
        return {
          ...articleSummary(row),
          matchSource: passage ? "pdf_passage" : needle ? "metadata" : undefined,
          matchSnippet: passage?.snippet,
          matchPageNumber: passage?.pageNumber,
        };
      })
      .sort((left, right) => {
        const leftRank = passageHits.get(String(left.id))?.rank ?? 0;
        const rightRank = passageHits.get(String(right.id))?.rank ?? 0;
        return rightRank - leftRank;
      });
  }

  async driveConnections(): Promise<CloudDriveConnection[]> {
    const { library } = await this.context();
    const response = await this.supabase
      .from("cloud_connections")
      .select("*")
      .eq("library_id", library.id)
      .order("provider", { ascending: true });
    if (response.error) throw new Error(response.error.message);
    return response.data.map(cloudDriveConnection);
  }

  async connectorStatus(): Promise<CloudConnectorStatus> {
    await this.context();
    const response = await this.supabase.functions.invoke(
      "cloud-connectors",
      { body: { action: "status" } },
    );
    if (response.error) {
      const failure = await connectorFailure(response.error);
      if (isUnavailableConnectorFailure(failure)) {
        return {
          serviceAvailable: false,
          providers: { google_drive: false, onedrive: false },
        };
      }
      throw new Error(
        failure.message ||
          "The cloud-drive connector status could not be checked.",
      );
    }
    const payload = response.data as {
      serviceAvailable?: unknown;
      providers?: Partial<Record<CloudDriveProvider, unknown>>;
    } | null;
    return {
      serviceAvailable: payload?.serviceAvailable === true,
      providers: {
        google_drive: payload?.providers?.google_drive === true,
        onedrive: payload?.providers?.onedrive === true,
      },
    };
  }

  async connectDrive(provider: CloudDriveProvider): Promise<void> {
    await this.context();
    const returnUrl = new URL(window.location.href);
    for (const parameter of ["connector", "connector_error"]) {
      returnUrl.searchParams.delete(parameter);
    }
    const response = await this.supabase.functions.invoke(
      "cloud-connectors",
      {
        body: {
          action: "authorize",
          provider,
          returnTo: returnUrl.toString(),
        },
      },
    );
    if (response.error) {
      throw new Error(
        connectorFailureMessage(
          provider,
          await connectorFailure(response.error),
        ),
      );
    }
    const payload = response.data as {
      authorizationUrl?: string;
      error?: string;
      message?: string;
    } | null;
    if (!payload?.authorizationUrl) {
      throw new Error(
        payload?.message ??
          payload?.error ??
          "The cloud-drive provider has not been configured yet.",
      );
    }
    window.location.assign(payload.authorizationUrl);
  }

  private async ensureBackupTarget(): Promise<BackupTargetRow> {
    const { user, library } = await this.context();
    const existing = await this.supabase
      .from("backup_targets")
      .select("*")
      .eq("library_id", library.id)
      .maybeSingle();
    if (existing.error) throw new Error(existing.error.message);
    if (existing.data) return existing.data;

    const created = await this.supabase
      .from("backup_targets")
      .insert({
        library_id: library.id,
        owner_id: user.id,
      })
      .select("*")
      .single();
    if (created.error?.code === "23505") {
      const raced = await this.supabase
        .from("backup_targets")
        .select("*")
        .eq("library_id", library.id)
        .single();
      if (raced.error) throw new Error(raced.error.message);
      return raced.data;
    }
    if (created.error) throw new Error(created.error.message);
    return created.data;
  }

  async backupSettings(): Promise<CloudBackupSettings> {
    const target = await this.ensureBackupTarget();
    const replications = await this.supabase
      .from("backup_replications")
      .select("*")
      .eq("target_id", target.id)
      .order("updated_at", { ascending: false })
      .limit(1_000);
    if (replications.error) throw new Error(replications.error.message);
    return cloudBackupSettings(target, replications.data);
  }

  async updateBackupSettings(
    patch: CloudBackupSettingsPatch,
  ): Promise<CloudBackupSettings> {
    const target = await this.ensureBackupTarget();
    const update: TablesUpdate<"backup_targets"> = {};
    if (patch.enabled != null) update.enabled = patch.enabled;
    if (patch.copyDeviceImports != null) {
      update.copy_device_imports = patch.copyDeviceImports;
    }
    if (patch.copyCloudImports != null) {
      update.copy_cloud_imports = patch.copyCloudImports;
    }
    if (!Object.keys(update).length) return this.backupSettings();

    const response = await this.supabase
      .from("backup_targets")
      .update(update)
      .eq("id", target.id);
    if (response.error) throw new Error(response.error.message);

    const queueResponse = await this.supabase.rpc(
      "queue_library_backups",
      {},
    );
    if (queueResponse.error) {
      throw new Error(queueResponse.error.message);
    }
    return this.backupSettings();
  }

  async dashboard(): Promise<CloudDashboard> {
    const { library } = await this.context();
    const [
      articlesResponse,
      unreadResponse,
      readingResponse,
      reviewResponse,
      annotationsResponse,
      projectsResponse,
      jobsResponse,
    ] = await Promise.all([
      this.supabase
        .from("articles")
        .select("*", { count: "exact" })
        .eq("library_id", library.id)
        .is("deleted_at", null)
        .order("updated_at", { ascending: false })
        .limit(6),
      this.supabase
        .from("articles")
        .select("id", { count: "exact", head: true })
        .eq("library_id", library.id)
        .eq("reading_status", "unread")
        .is("deleted_at", null),
      this.supabase
        .from("articles")
        .select("id", { count: "exact", head: true })
        .eq("library_id", library.id)
        .eq("reading_status", "reading")
        .is("deleted_at", null),
      this.supabase
        .from("articles")
        .select("id", { count: "exact", head: true })
        .eq("library_id", library.id)
        .neq("review_state", "ready")
        .is("deleted_at", null),
      this.supabase
        .from("annotations")
        .select("id", { count: "exact", head: true })
        .eq("library_id", library.id)
        .is("deleted_at", null),
      this.supabase
        .from("projects")
        .select("id", { count: "exact", head: true })
        .eq("library_id", library.id)
        .is("deleted_at", null),
      this.supabase
        .from("jobs")
        .select("id", { count: "exact", head: true })
        .eq("library_id", library.id)
        .in("status", ["queued", "running"]),
    ]);
    if (articlesResponse.error) {
      throw new Error(articlesResponse.error.message);
    }
    if (unreadResponse.error) throw new Error(unreadResponse.error.message);
    if (readingResponse.error) throw new Error(readingResponse.error.message);
    if (reviewResponse.error) throw new Error(reviewResponse.error.message);
    if (annotationsResponse.error) {
      throw new Error(annotationsResponse.error.message);
    }
    if (projectsResponse.error) {
      throw new Error(projectsResponse.error.message);
    }
    if (jobsResponse.error) throw new Error(jobsResponse.error.message);

    return {
      articleCount: articlesResponse.count ?? 0,
      unreadCount: unreadResponse.count ?? 0,
      readingCount: readingResponse.count ?? 0,
      annotationCount: annotationsResponse.count ?? 0,
      projectCount: projectsResponse.count ?? 0,
      activeJobCount: jobsResponse.count ?? 0,
      reviewCount: reviewResponse.count ?? 0,
      recentArticles: articlesResponse.data.map(articleSummary),
    };
  }

  async article(articleId: EntityId): Promise<ArticleDetail> {
    const id = requireStringId(articleId, "Article");
    const articleResponse = await this.supabase
      .from("articles")
      .select("*")
      .eq("id", id)
      .is("deleted_at", null)
      .single();
    if (articleResponse.error) throw new Error(articleResponse.error.message);
    const [assetsResponse, annotationsResponse] = await Promise.all([
      this.supabase
        .from("article_assets")
        .select("*")
        .eq("article_id", id)
        .order("is_primary", { ascending: false })
        .order("created_at", { ascending: true }),
      this.supabase
        .from("annotations")
        .select("*")
        .eq("article_id", id)
        .is("deleted_at", null)
        .order("created_at", { ascending: true }),
    ]);
    if (assetsResponse.error) throw new Error(assetsResponse.error.message);
    if (annotationsResponse.error) {
      throw new Error(annotationsResponse.error.message);
    }
    return {
      ...articleSummary(articleResponse.data),
      doi: articleResponse.data.doi,
      pmid: articleResponse.data.pmid,
      abstract: articleResponse.data.abstract,
      user_summary: articleResponse.data.user_summary,
      metadata_conflicts: [],
      assets: assetsResponse.data.map(articleAsset),
      annotations: annotationsResponse.data.map(annotation),
    };
  }

  private async findByDigest(
    libraryId: string,
    digest: string,
  ): Promise<ArticleDetail | null> {
    const response = await this.supabase
      .from("article_assets")
      .select("article_id")
      .eq("library_id", libraryId)
      .eq("sha256", digest)
      .maybeSingle();
    if (response.error) throw new Error(response.error.message);
    return response.data ? this.article(response.data.article_id) : null;
  }

  private async resumableUpload(
    file: File,
    storagePath: string,
    onProgress?: (progress: UploadProgress) => void,
  ): Promise<void> {
    const { data, error } = await this.supabase.auth.getSession();
    if (error) throw new Error(error.message);
    if (!data.session) throw new Error("Your session has expired. Sign in again.");
    await new Promise<void>((resolve, reject) => {
      const upload = new Upload(file, {
        endpoint: resumableUploadEndpoint(this.configuration.supabaseUrl),
        retryDelays: [0, 1_000, 3_000, 5_000, 10_000],
        headers: {
          authorization: `Bearer ${data.session.access_token}`,
          apikey: this.configuration.publishableKey,
        },
        uploadDataDuringCreation: true,
        removeFingerprintOnSuccess: true,
        chunkSize: TUS_CHUNK_BYTES,
        metadata: {
          bucketName: PDF_BUCKET,
          objectName: storagePath,
          contentType: "application/pdf",
          cacheControl: "3600",
        },
        onProgress: (bytesSent, bytesTotal) => {
          onProgress?.({ fileName: file.name, bytesSent, bytesTotal });
        },
        onError: (uploadError) => reject(uploadError),
        onSuccess: () => resolve(),
      });
      void upload.findPreviousUploads().then((previous) => {
        const resumable = previous.find(
          (item) =>
            item.metadata.bucketName === PDF_BUCKET &&
            item.metadata.objectName === storagePath,
        );
        if (resumable) upload.resumeFromPreviousUpload(resumable);
        upload.start();
      }).catch(reject);
    });
  }

  async uploadPdf(
    file: File,
    onProgress?: (progress: UploadProgress) => void,
  ): Promise<ArticleDetail> {
    if (
      file.type !== "application/pdf" &&
      !file.name.toLocaleLowerCase().endsWith(".pdf")
    ) {
      throw new Error(`${file.name} is not a PDF.`);
    }
    if (!file.size) throw new Error(`${file.name} is empty.`);
    if (file.size > MAX_PDF_BYTES) {
      throw new Error(`${file.name} exceeds the 250 MB upload limit.`);
    }
    const { user, library } = await this.context();
    const digest = await sha256(file);
    const existing = await this.findByDigest(library.id, digest);
    if (existing) return existing;

    const jobResponse = await this.supabase
      .from("jobs")
      .insert({
        library_id: library.id,
        owner_id: user.id,
        type: "import",
        source: file.name,
        stage: "uploading",
        status: "running",
        progress_total: file.size,
        input: { source_kind: "device_upload" },
      })
      .select("*")
      .single();
    if (jobResponse.error) throw new Error(jobResponse.error.message);
    const job = jobResponse.data;

    const articleInsert: TablesInsert<"articles"> = {
      library_id: library.id,
      owner_id: user.id,
      title: titleFromFileName(file.name),
      extraction_status: "uploaded",
      metadata_status: "filename",
      source_type: "journal_article",
    };
    const articleResponse = await this.supabase
      .from("articles")
      .insert(articleInsert)
      .select("*")
      .single();
    if (articleResponse.error) {
      await this.failJob(job.id, articleResponse.error.message);
      throw new Error(articleResponse.error.message);
    }

    const storagePath = `${user.id}/${library.id}/${digest}.pdf`;
    const assetInsert: TablesInsert<"article_assets"> = {
      article_id: articleResponse.data.id,
      library_id: library.id,
      owner_id: user.id,
      sha256: digest,
      storage_path: storagePath,
      file_name: file.name.slice(0, 1_000),
      size_bytes: file.size,
      mime_type: "application/pdf",
      source_kind: "device_upload",
      version_label: "Synced original",
      availability: "processing",
      is_primary: true,
    };
    const assetResponse = await this.supabase
      .from("article_assets")
      .insert(assetInsert)
      .select("*")
      .single();
    if (assetResponse.error?.code === "23505") {
      await this.supabase
        .from("articles")
        .delete()
        .eq("id", articleResponse.data.id);
      await this.succeedJob(job.id, { duplicate: true });
      const raced = await this.findByDigest(library.id, digest);
      if (raced) return raced;
      throw new Error("This PDF was imported by another device. Refresh the library.");
    }
    if (assetResponse.error) {
      await this.supabase
        .from("articles")
        .delete()
        .eq("id", articleResponse.data.id);
      await this.failJob(job.id, assetResponse.error.message);
      throw new Error(assetResponse.error.message);
    }

    try {
      await this.resumableUpload(file, storagePath, onProgress);
      const [assetUpdate, articleUpdate] = await Promise.all([
        this.supabase
          .from("article_assets")
          .update({ availability: "available" })
          .eq("id", assetResponse.data.id),
        this.supabase
          .from("articles")
          .update({ extraction_status: "queued" })
          .eq("id", articleResponse.data.id),
      ]);
      if (assetUpdate.error) throw new Error(assetUpdate.error.message);
      if (articleUpdate.error) throw new Error(articleUpdate.error.message);
      const backupQueue = await this.supabase.rpc("queue_library_backups", {
        p_asset_id: assetResponse.data.id,
      });
      await this.succeedJob(job.id, {
        article_id: articleResponse.data.id,
        asset_id: assetResponse.data.id,
        sha256: digest,
        backup_copies_queued: backupQueue.error
          ? 0
          : backupQueue.data,
        backup_queue_warning: backupQueue.error?.message ?? null,
      });
      return await this.article(articleResponse.data.id);
    } catch (value) {
      const message = value instanceof Error ? value.message : String(value);
      await Promise.all([
        this.supabase
          .from("article_assets")
          .update({ availability: "failed" })
          .eq("id", assetResponse.data.id),
        this.supabase
          .from("articles")
          .update({ extraction_status: "failed" })
          .eq("id", articleResponse.data.id),
        this.failJob(job.id, message),
      ]);
      throw new Error(`Could not upload ${file.name}: ${message}`);
    }
  }

  private async succeedJob(id: string, output: Json): Promise<void> {
    await this.supabase
      .from("jobs")
      .update({
        stage: "uploaded",
        status: "succeeded",
        progress_current: 1,
        progress_total: 1,
        output,
        finished_at: new Date().toISOString(),
      })
      .eq("id", id);
  }

  private async failJob(id: string, message: string): Promise<void> {
    await this.supabase
      .from("jobs")
      .update({
        stage: "upload_failed",
        status: "failed",
        retryable: true,
        error_code: "upload_failed",
        output: { message },
        finished_at: new Date().toISOString(),
      })
      .eq("id", id);
  }

  subscribeToLibrary(ownerId: string, onChange: () => void): () => void {
    let timer = 0;
    const notify = () => {
      this.cachedContext = undefined;
      window.clearTimeout(timer);
      timer = window.setTimeout(onChange, 75);
    };
    let channel: RealtimeChannel = this.supabase.channel(
      `library:${ownerId}:${crypto.randomUUID()}`,
    );
    for (const table of [
      "libraries",
      "articles",
      "article_assets",
      "annotations",
      "projects",
      "project_articles",
      "jobs",
      "cloud_connections",
      "backup_targets",
      "backup_replications",
    ] as const) {
      channel = channel.on(
        "postgres_changes",
        {
          event: "*",
          schema: "public",
          table,
          filter: `owner_id=eq.${ownerId}`,
        },
        notify,
      );
    }
    void channel.subscribe();
    return () => {
      window.clearTimeout(timer);
      void this.supabase.removeChannel(channel);
    };
  }

  async assetUrl(assetId: EntityId): Promise<string> {
    const id = requireStringId(assetId, "Asset");
    const assetResponse = await this.supabase
      .from("article_assets")
      .select("storage_bucket, storage_path")
      .eq("id", id)
      .single();
    if (assetResponse.error) throw new Error(assetResponse.error.message);
    const signed = await this.supabase.storage
      .from(assetResponse.data.storage_bucket)
      .createSignedUrl(assetResponse.data.storage_path, 15 * 60);
    if (signed.error) throw new Error(signed.error.message);
    return signed.data.signedUrl;
  }

  async createAnnotation(
    articleId: EntityId,
    value: Omit<
      Annotation,
      "id" | "article_id" | "created_at" | "updated_at"
    >,
  ): Promise<Annotation> {
    const id = requireStringId(articleId, "Article");
    const assetId = requireStringId(value.asset_id, "Asset");
    const { user, library } = await this.context();
    const response = await this.supabase
      .from("annotations")
      .insert({
        article_id: id,
        asset_id: assetId,
        library_id: library.id,
        owner_id: user.id,
        page_number: value.page_number,
        annotation_type: value.annotation_type,
        color: value.color,
        quad_points: value.quad_points,
        selected_text: value.selected_text,
        context_hash: value.context_hash,
        comment: value.comment,
      })
      .select("*")
      .single();
    if (response.error) throw new Error(response.error.message);
    return annotation(response.data);
  }

  async deleteAnnotation(
    articleId: EntityId,
    annotationId: string,
  ): Promise<void> {
    const id = requireStringId(articleId, "Article");
    const response = await this.supabase
      .from("annotations")
      .update({ deleted_at: new Date().toISOString() })
      .eq("id", annotationId)
      .eq("article_id", id);
    if (response.error) throw new Error(response.error.message);
  }

  async updateArticle(
    articleId: EntityId,
    value: Record<string, unknown>,
  ): Promise<ArticleDetail> {
    const id = requireStringId(articleId, "Article");
    const update: TablesUpdate<"articles"> = {};
    if (typeof value.title === "string" && value.title.trim()) {
      update.title = value.title.trim().slice(0, 1_000);
    }
    if (typeof value.authors === "string") {
      update.authors = value.authors.trim().slice(0, 2_000);
    }
    if (typeof value.journal === "string") {
      update.journal = value.journal.trim().slice(0, 500);
    }
    if (
      value.publication_year === null ||
      (typeof value.publication_year === "number" &&
        value.publication_year >= 1500 &&
        value.publication_year <= 2200)
    ) {
      update.publication_year = value.publication_year;
    }
    if (typeof value.doi === "string") {
      update.doi = value.doi.trim().slice(0, 500);
    }
    if (typeof value.pmid === "string") {
      update.pmid = value.pmid.trim().slice(0, 20);
    }
    if (typeof value.why_saved === "string") {
      update.why_saved = value.why_saved.slice(0, 50_000);
    }
    if (typeof value.user_summary === "string") {
      update.user_summary = value.user_summary.slice(0, 100_000);
    }
    if (
      typeof value.reading_status === "string" &&
      ["unread", "reading", "reference", "finished"].includes(
        value.reading_status,
      )
    ) {
      update.reading_status = value.reading_status;
    }
    if (
      typeof value.importance === "number" &&
      Number.isInteger(value.importance) &&
      value.importance >= 0 &&
      value.importance <= 5
    ) {
      update.importance = value.importance;
    }
    if (
      ["title", "authors", "journal", "publication_year", "doi", "pmid"].some(
        (field) => field in value,
      )
    ) {
      update.metadata_status = "user";
    }
    if (!Object.keys(update).length) return this.article(id);
    const response = await this.supabase
      .from("articles")
      .update(update)
      .eq("id", id);
    if (response.error) throw new Error(response.error.message);
    return this.article(id);
  }

  async resolveArticleReview(
    articleId: EntityId,
    _resolution: "accept_as_separate_article" | "keep_as_single_article",
  ): Promise<ArticleDetail> {
    const id = requireStringId(articleId, "Article");
    const response = await this.supabase
      .from("articles")
      .update({ review_state: "ready" })
      .eq("id", id);
    if (response.error) throw new Error(response.error.message);
    return this.article(id);
  }

  async unlockArticle(
    _articleId: EntityId,
    _password: string,
  ): Promise<ImportJob> {
    throw new Error(
      "Password-protected PDF processing is not enabled in cloud mode yet.",
    );
  }

  async projects(): Promise<Project[]> {
    const { library } = await this.context();
    const [projectsResponse, membershipResponse] = await Promise.all([
      this.supabase
        .from("projects")
        .select("*")
        .eq("library_id", library.id)
        .is("deleted_at", null)
        .order("updated_at", { ascending: false }),
      this.supabase
        .from("project_articles")
        .select("project_id")
        .eq("library_id", library.id),
    ]);
    if (projectsResponse.error) throw new Error(projectsResponse.error.message);
    if (membershipResponse.error) {
      throw new Error(membershipResponse.error.message);
    }
    const counts = new Map<string, number>();
    for (const membership of membershipResponse.data) {
      counts.set(
        membership.project_id,
        (counts.get(membership.project_id) ?? 0) + 1,
      );
    }
    return projectsResponse.data.map((row) => ({
      id: row.id,
      name: row.name,
      description: row.description,
      project_type: row.project_type,
      central_question: row.central_question,
      created_at: row.created_at,
      updated_at: row.updated_at,
      article_count: counts.get(row.id) ?? 0,
    }));
  }

  async createProject(
    name: string,
    description: string,
  ): Promise<Project> {
    const nextName = name.trim();
    if (!nextName) throw new Error("Project name cannot be empty.");
    const { user, library } = await this.context();
    const response = await this.supabase
      .from("projects")
      .insert({
        library_id: library.id,
        owner_id: user.id,
        name: nextName.slice(0, 500),
        description: description.trim().slice(0, 50_000),
      })
      .select("*")
      .single();
    if (response.error) throw new Error(response.error.message);
    return {
      id: response.data.id,
      name: response.data.name,
      description: response.data.description,
      project_type: response.data.project_type,
      central_question: response.data.central_question,
      created_at: response.data.created_at,
      updated_at: response.data.updated_at,
      article_count: 0,
    };
  }

  async projectArticles(projectId: EntityId): Promise<ArticleSummary[]> {
    const id = requireStringId(projectId, "Project");
    const { library } = await this.context();
    const memberships = await this.supabase
      .from("project_articles")
      .select("article_id")
      .eq("library_id", library.id)
      .eq("project_id", id);
    if (memberships.error) throw new Error(memberships.error.message);
    const articleIds = memberships.data.map((row) => row.article_id);
    if (!articleIds.length) return [];
    const response = await this.supabase
      .from("articles")
      .select("*")
      .eq("library_id", library.id)
      .in("id", articleIds)
      .is("deleted_at", null)
      .order("updated_at", { ascending: false });
    if (response.error) throw new Error(response.error.message);
    return response.data.map(articleSummary);
  }

  async addProjectArticle(
    projectId: EntityId,
    articleId: EntityId,
  ): Promise<void> {
    const project = requireStringId(projectId, "Project");
    const article = requireStringId(articleId, "Article");
    const { user, library } = await this.context();
    const response = await this.supabase
      .from("project_articles")
      .upsert(
        {
          project_id: project,
          article_id: article,
          library_id: library.id,
          owner_id: user.id,
        },
        { onConflict: "project_id,article_id", ignoreDuplicates: true },
    );
    if (response.error) throw new Error(response.error.message);
  }

  async removeProjectArticle(
    projectId: EntityId,
    articleId: EntityId,
  ): Promise<void> {
    const project = requireStringId(projectId, "Project");
    const article = requireStringId(articleId, "Article");
    const response = await this.supabase
      .from("project_articles")
      .delete()
      .eq("project_id", project)
      .eq("article_id", article);
    if (response.error) throw new Error(response.error.message);
  }

  async jobs(): Promise<ImportJob[]> {
    const { library } = await this.context();
    const response = await this.supabase
      .from("jobs")
      .select("*")
      .eq("library_id", library.id)
      .order("created_at", { ascending: false })
      .limit(200);
    if (response.error) throw new Error(response.error.message);
    return response.data.map(importJob);
  }

  async trash(): Promise<TrashArticle[]> {
    const { library } = await this.context();
    const response = await this.supabase
      .from("articles")
      .select("id, title, deleted_at")
      .eq("library_id", library.id)
      .not("deleted_at", "is", null)
      .order("deleted_at", { ascending: false });
    if (response.error) throw new Error(response.error.message);
    return response.data.flatMap((row) => {
      if (!row.deleted_at) return [];
      const purgeAfter = new Date(row.deleted_at);
      purgeAfter.setUTCDate(purgeAfter.getUTCDate() + 30);
      return [{
        id: row.id,
        title: row.title,
        deleted_at: row.deleted_at,
        purge_after: purgeAfter.toISOString(),
      }];
    });
  }

  async restoreArticle(articleId: EntityId): Promise<void> {
    const id = requireStringId(articleId, "Article");
    const response = await this.supabase
      .from("articles")
      .update({ deleted_at: null })
      .eq("id", id);
    if (response.error) throw new Error(response.error.message);
  }

  async trashArticle(
    articleId: EntityId,
    _title: string,
  ): Promise<boolean> {
    const id = requireStringId(articleId, "Article");
    const response = await this.supabase
      .from("articles")
      .update({ deleted_at: new Date().toISOString() })
      .eq("id", id)
      .select("id")
      .maybeSingle();
    if (response.error) throw new Error(response.error.message);
    return Boolean(response.data);
  }

  async exportArticle(
    articleId: EntityId,
    _assetId: EntityId,
    exportType: "markdown" | "ris" | "bibtex" | "xfdf" | "annotated_pdf",
    suggestedName: string,
  ): Promise<string | null> {
    if (exportType === "annotated_pdf") {
      throw new Error(
        "Flattened annotation export is not available in cloud mode yet. The original PDF can still be downloaded from the reader toolbar.",
      );
    }
    const value = await this.article(articleId);
    if (exportType === "markdown") {
      const body = [
        `# ${value.title}`,
        "",
        value.authors ? `**Authors:** ${value.authors}` : null,
        value.journal ? `**Journal:** ${value.journal}` : null,
        value.doi ? `**DOI:** ${value.doi}` : null,
        "",
        value.user_summary,
        "",
        "## Annotations",
        ...value.annotations.map(
          (item) =>
            `- Page ${item.page_number}: ${item.comment || item.selected_text || "Bookmark"}`,
        ),
      ]
        .filter((line): line is string => line !== null)
        .join("\n");
      triggerDownload(body, "text/markdown;charset=utf-8", suggestedName);
    } else if (exportType === "ris") {
      const body = [
        "TY  - JOUR",
        `TI  - ${escapeRis(value.title)}`,
        value.authors && `AU  - ${escapeRis(value.authors)}`,
        value.journal && `JO  - ${escapeRis(value.journal)}`,
        value.publication_year && `PY  - ${value.publication_year}`,
        value.doi && `DO  - ${escapeRis(value.doi)}`,
        "ER  -",
      ]
        .filter(Boolean)
        .join("\n");
      triggerDownload(body, "application/x-research-info-systems", suggestedName);
    } else if (exportType === "bibtex") {
      const key = `research_memory_${String(value.id).slice(0, 8)}`;
      const fields = [
        `  title = {${value.title.replaceAll(/[{}]/g, "")}}`,
        value.authors &&
          `  author = {${value.authors.replaceAll(/[{}]/g, "")}}`,
        value.journal &&
          `  journal = {${value.journal.replaceAll(/[{}]/g, "")}}`,
        value.publication_year && `  year = {${value.publication_year}}`,
        value.doi && `  doi = {${value.doi.replaceAll(/[{}]/g, "")}}`,
      ].filter(Boolean);
      triggerDownload(
        `@article{${key},\n${fields.join(",\n")}\n}\n`,
        "application/x-bibtex",
        suggestedName,
      );
    } else {
      const contents = value.annotations
        .map(
          (item) =>
            `<text page="${item.page_number - 1}" color="${escapeXml(item.color)}" subject="${escapeXml(item.annotation_type)}"><contents>${escapeXml(item.comment || item.selected_text)}</contents></text>`,
        )
        .join("");
      triggerDownload(
        `<?xml version="1.0" encoding="UTF-8"?><xfdf xmlns="http://ns.adobe.com/xfdf/"><annots>${contents}</annots></xfdf>`,
        "application/vnd.adobe.xfdf",
        suggestedName,
      );
    }
    return suggestedName;
  }
}

let defaultCloudLibraryService: CloudLibraryService | undefined;

export function createCloudLibraryService(): CloudLibraryService {
  defaultCloudLibraryService ??= new SupabaseCloudLibraryService(
    requiredCloudConfiguration(),
  );
  return defaultCloudLibraryService;
}
