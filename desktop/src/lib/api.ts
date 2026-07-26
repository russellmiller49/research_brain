import { invoke as tauriInvoke } from "@tauri-apps/api/core";
import type {
  Annotation,
  ArticleDetail,
  ArticlePage,
  ArticleSummary,
  CoreStatus,
  EntityId,
  ImportIssue,
  ImportJob,
  Project,
  ProjectArticlesBulkResult,
  SearchHit,
  SearchQuery,
  TrashArticle,
} from "../types";
import { invokeBrowserTest } from "./browser-test-core";

const browserTest =
  import.meta.env.DEV &&
  new URLSearchParams(window.location.search).get("browser-test") === "1";

function invoke<T>(
  command: string,
  args?: Record<string, unknown>,
): Promise<T> {
  return browserTest
    ? invokeBrowserTest<T>(command, args)
    : tauriInvoke<T>(command, args);
}

export const core = {
  status: () => invoke<CoreStatus>("core_status"),
  articles: (query = "", limit = 100, offset = 0) =>
    invoke<ArticlePage>("list_articles", { query, limit, offset }),
  article: (articleId: EntityId) =>
    invoke<ArticleDetail>("get_article", { articleId }),
  trash: () => invoke<TrashArticle[]>("list_trash"),
  trashArticle: (articleId: EntityId, title: string) =>
    invoke<boolean>("trash_article", { articleId, title }),
  restoreArticle: (articleId: EntityId) =>
    invoke<void>("restore_article", { articleId }),
  updateArticle: (articleId: EntityId, value: Record<string, unknown>) =>
    invoke<ArticleDetail>("update_article", { articleId, value }),
  resolveArticleReview: (
    articleId: EntityId,
    resolution: "accept_as_separate_article" | "keep_as_single_article",
  ) =>
    invoke<ArticleDetail>("resolve_article_review", { articleId, resolution }),
  unlockArticle: (articleId: EntityId, password: string) =>
    invoke<ImportJob>("unlock_article", { articleId, password }),
  search: (query: SearchQuery) => invoke<SearchHit[]>("recall_search", { query }),
  chooseImportFolder: () => invoke<ImportJob | null>("choose_import_folder"),
  chooseImportFiles: () => invoke<ImportJob[]>("choose_import_files"),
  importZotero: () => invoke<ImportJob>("import_zotero"),
  jobs: () => invoke<ImportJob[]>("list_jobs"),
  jobIssues: (jobId: string) =>
    invoke<ImportIssue[]>("list_job_issues", { jobId }),
  cancelJob: (jobId: string) => invoke<void>("cancel_job", { jobId }),
  retryJob: (jobId: string) => invoke<ImportJob>("retry_job", { jobId }),
  assetUrl: (assetId: EntityId) => invoke<string>("asset_url", { assetId }),
  createAnnotation: (
    articleId: EntityId,
    value: Omit<Annotation, "id" | "article_id" | "created_at" | "updated_at">,
  ) => invoke<Annotation>("create_annotation", { articleId, value }),
  deleteAnnotation: (articleId: EntityId, annotationId: string) =>
    invoke<void>("delete_annotation", { articleId, annotationId }),
  installModel: () => invoke<ImportJob>("install_model"),
  chooseBackupDestination: (passphrase: string) =>
    invoke<string | null>("create_backup", { passphrase }),
  chooseBackupRestore: (passphrase: string) =>
    invoke<Record<string, number> | null>("restore_backup", { passphrase }),
  projects: () => invoke<Project[]>("list_projects"),
  createProject: (name: string, description: string) =>
    invoke<Project>("create_project", { name, description }),
  projectArticles: (projectId: EntityId) =>
    invoke<ArticleSummary[]>("list_project_articles", { projectId }),
  addProjectArticle: (projectId: EntityId, articleId: EntityId) =>
    invoke<void>("add_project_article", { projectId, articleId }),
  addProjectArticles: (projectId: EntityId, articleIds: EntityId[]) =>
    invoke<ProjectArticlesBulkResult>("add_project_articles", {
      projectId,
      articleIds,
    }),
  updatePrivacy: (
    enableNetworkMetadata: boolean,
    diagnosticsEnabled: boolean,
  ) =>
    invoke<{
      enable_network_metadata: boolean;
      diagnostics_enabled: boolean;
    }>("update_privacy", {
      enableNetworkMetadata,
      diagnosticsEnabled,
    }),
  createSupportBundle: () =>
    invoke<string | null>("create_support_bundle"),
  exportArticle: (
    articleId: EntityId,
    assetId: EntityId,
    exportType: "markdown" | "ris" | "bibtex" | "xfdf" | "annotated_pdf",
    suggestedName: string,
  ) =>
    invoke<string | null>("export_article", {
      articleId,
      assetId,
      exportType,
      suggestedName,
    }),
  checkForUpdates: () =>
    invoke<{ available: boolean; version: string | null }>("check_for_updates"),
  installUpdate: () => invoke<string>("install_update"),
};

export type ReaderCore = Pick<
  typeof core,
  | "assetUrl"
  | "unlockArticle"
  | "projects"
  | "createAnnotation"
  | "exportArticle"
  | "resolveArticleReview"
  | "deleteAnnotation"
  | "updateArticle"
  | "addProjectArticle"
  | "trashArticle"
>;
