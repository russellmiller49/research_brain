export type View =
  | "home"
  | "library"
  | "search"
  | "projects"
  | "imports"
  | "settings";

export type EntityId = number | string;

export interface BoundingBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  coordinate_space: "pdf_points";
}

export interface MatchReason {
  code: string;
  label: string;
}

export interface SearchHit {
  rank: number;
  article_id: EntityId;
  asset_id: EntityId | null;
  title: string;
  authors: string;
  journal: string;
  publication_year: number | null;
  source_type: string;
  page_number: number | null;
  passage_id: EntityId | null;
  snippet: string;
  bounding_boxes: BoundingBox[];
  match_reasons: MatchReason[];
  why_saved: string;
}

export interface ArticleSummary {
  id: EntityId;
  title: string;
  authors: string;
  journal: string;
  publication_year: number | null;
  source_type: string;
  reading_status: string;
  importance: number;
  page_count: number;
  why_saved: string;
  extraction_status: string;
  review_state: string;
}

export interface ArticlePage {
  items: ArticleSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface TrashArticle {
  id: EntityId;
  title: string;
  deleted_at: string;
  purge_after: string;
}

export interface ArticleAsset {
  id: EntityId;
  article_id: EntityId;
  sha256: string;
  file_name: string;
  role: string;
  version_label: string;
  source_kind: string;
  availability: string;
  is_primary: boolean;
  size_bytes: number;
}

export interface Annotation {
  id: string;
  article_id: EntityId;
  asset_id: EntityId;
  page_number: number;
  annotation_type: "highlight" | "comment" | "bookmark";
  color: string;
  quad_points: number[];
  selected_text: string;
  context_hash: string;
  comment: string;
  created_at: string;
  updated_at: string;
}

export interface ArticleDetail extends ArticleSummary {
  doi: string;
  pmid: string;
  abstract: string;
  user_summary: string;
  metadata_conflicts: Array<Record<string, unknown>>;
  assets: ArticleAsset[];
  annotations: Annotation[];
}

export interface ImportJob {
  id: string;
  type: string;
  source: string;
  stage: string;
  status: "queued" | "running" | "paused" | "succeeded" | "failed" | "canceled";
  progress_current: number;
  progress_total: number;
  progress: number;
  retryable: boolean;
  error_code: string | null;
  issue_count: number;
  created_at: string;
  updated_at: string;
}

export interface ImportIssue {
  id: number;
  job_id: string;
  source_label: string;
  error_code: string;
  retryable: boolean;
  created_at: string;
}

export interface CoreStatus {
  status: "ok";
  version: string;
  schema_version: number;
  documents: number;
  review_needed: number;
  jobs_running: number;
  embedding_backend: string;
  embedding_warning: string | null;
  ocr_available: boolean;
  network_metadata_enabled: boolean;
  diagnostics_enabled: boolean;
}

export interface Project {
  id: EntityId;
  name: string;
  description: string;
  project_type: string;
  central_question: string;
  created_at: string;
  updated_at: string;
  article_count: number;
}

export interface ProjectArticlesBulkResult {
  project_id: EntityId;
  requested: number;
  added: number;
  already_present: number;
}

export interface SearchQuery {
  text: string;
  year_min?: number;
  year_max?: number;
  source_type?: string;
  reading_status?: string;
  project_id?: EntityId;
  document_ids?: EntityId[];
  limit?: number;
}
