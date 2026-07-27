use std::collections::HashMap;
use std::fs::OpenOptions;
use std::io::Write;
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use notify::{EventKind, RecommendedWatcher, RecursiveMode, Watcher};
use reqwest::{Client, Method};
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use tauri::{AppHandle, Manager, RunEvent, State};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_updater::UpdaterExt;
use uuid::Uuid;

struct CoreState {
    base_url: String,
    token: String,
    data_dir: PathBuf,
    client: Client,
    child: Mutex<Option<CommandChild>>,
    watchers: Mutex<Vec<RecommendedWatcher>>,
    watcher_controls: Mutex<HashMap<PathBuf, Arc<AtomicBool>>>,
}

#[derive(Debug, Serialize, Deserialize)]
struct CoreStatus {
    status: String,
    version: String,
    schema_version: i64,
    documents: i64,
    review_needed: i64,
    jobs_running: i64,
    embedding_backend: String,
    embedding_warning: Option<String>,
    ocr_available: bool,
    network_metadata_enabled: bool,
    diagnostics_enabled: bool,
    taxonomy_profile_enabled: bool,
    taxonomy_suggestions_enabled: bool,
    taxonomy_auto_apply_enabled: bool,
    taxonomy_disease_state_extraction_enabled: bool,
}

#[derive(Debug, Serialize, Deserialize)]
struct TaxonomyNodeSummary {
    id: String,
    node_type: String,
    canonical_name: String,
    status: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct ExternalMapping {
    vocabulary: String,
    code: String,
    display_name: String,
    version: String,
    provenance: String,
    status: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct TaxonomyNode {
    id: String,
    node_type: String,
    canonical_name: String,
    status: String,
    description: String,
    source_system: String,
    source_code: String,
    source_version: String,
    external_mappings: Vec<ExternalMapping>,
    metadata: Value,
}

#[derive(Debug, Serialize, Deserialize)]
struct TaxonomyCatalogPage {
    items: Vec<TaxonomyNodeSummary>,
    total: i64,
    limit: i64,
    offset: i64,
    catalog_version: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct SpecialtyPackSummary {
    pack_id: String,
    display_name: String,
    pack_type: String,
    version: String,
    selection_node_id: String,
    curation_status: String,
    inherits: Vec<String>,
    membership_count: i64,
    state_archetypes: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize)]
struct PersonalizedTaxonomyNode {
    canonical_node_id: String,
    display_instance_id: String,
    parent_display_instance_id: Option<String>,
    display_name: String,
    node_type: String,
    weight: f64,
    depth: i64,
    visible: bool,
    pinned: bool,
    children: Vec<PersonalizedTaxonomyNode>,
}

#[derive(Debug, Serialize, Deserialize)]
struct PersonalizedTaxonomyTree {
    catalog_version: String,
    profile_revision: String,
    warnings: Vec<String>,
    roots: Vec<PersonalizedTaxonomyNode>,
    total_canonical_nodes: i64,
}

#[derive(Debug, Serialize, Deserialize)]
struct ArticleSummary {
    id: i64,
    title: String,
    authors: String,
    journal: String,
    publication_year: Option<i64>,
    source_type: String,
    reading_status: String,
    importance: i64,
    page_count: i64,
    why_saved: String,
    extraction_status: String,
    review_state: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct ArticlePage {
    items: Vec<ArticleSummary>,
    total: i64,
    limit: i64,
    offset: i64,
}

#[derive(Debug, Serialize, Deserialize)]
struct TrashArticle {
    id: i64,
    title: String,
    deleted_at: String,
    purge_after: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct ArticleAsset {
    id: i64,
    article_id: i64,
    sha256: String,
    file_name: String,
    role: String,
    version_label: String,
    source_kind: String,
    availability: String,
    is_primary: bool,
    size_bytes: i64,
}

#[derive(Debug, Serialize, Deserialize)]
struct Annotation {
    id: String,
    article_id: i64,
    asset_id: i64,
    page_number: i64,
    annotation_type: String,
    color: String,
    quad_points: Vec<f64>,
    selected_text: String,
    context_hash: String,
    comment: String,
    created_at: String,
    updated_at: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct ArticleDetail {
    id: i64,
    title: String,
    authors: String,
    journal: String,
    publication_year: Option<i64>,
    source_type: String,
    reading_status: String,
    importance: i64,
    page_count: i64,
    why_saved: String,
    extraction_status: String,
    review_state: String,
    doi: String,
    pmid: String,
    r#abstract: String,
    user_summary: String,
    metadata_conflicts: Vec<Value>,
    assets: Vec<ArticleAsset>,
    annotations: Vec<Annotation>,
}

#[derive(Debug, Serialize, Deserialize)]
struct SearchQuery {
    text: String,
    year_min: Option<i64>,
    year_max: Option<i64>,
    source_type: Option<String>,
    reading_status: Option<String>,
    project_id: Option<i64>,
    document_ids: Option<Vec<i64>>,
    limit: Option<i64>,
}

#[derive(Debug, Serialize, Deserialize)]
struct BoundingBox {
    x0: f64,
    y0: f64,
    x1: f64,
    y1: f64,
    coordinate_space: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct MatchReason {
    code: String,
    label: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct SearchHit {
    rank: i64,
    article_id: i64,
    asset_id: Option<i64>,
    title: String,
    authors: String,
    journal: String,
    publication_year: Option<i64>,
    source_type: String,
    page_number: Option<i64>,
    passage_id: Option<i64>,
    snippet: String,
    bounding_boxes: Vec<BoundingBox>,
    match_reasons: Vec<MatchReason>,
    why_saved: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct ImportJob {
    id: String,
    #[serde(rename = "type")]
    job_type: String,
    source: String,
    stage: String,
    status: String,
    progress_current: i64,
    progress_total: i64,
    progress: f64,
    retryable: bool,
    error_code: Option<String>,
    issue_count: i64,
    created_at: String,
    updated_at: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct ImportIssue {
    id: i64,
    job_id: String,
    source_label: String,
    error_code: String,
    retryable: bool,
    created_at: String,
}

#[derive(Debug, Deserialize)]
struct WatchRecord {
    folder_path: PathBuf,
    recursive: bool,
    #[serde(default)]
    active_job_id: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
struct Project {
    id: i64,
    name: String,
    description: String,
    project_type: String,
    central_question: String,
    created_at: String,
    updated_at: String,
    article_count: i64,
}

#[derive(Debug, Serialize, Deserialize)]
struct ProjectArticlesBulkResult {
    project_id: i64,
    requested: i64,
    added: i64,
    already_present: i64,
}

#[derive(Debug, Serialize, Deserialize)]
struct PrivacySettings {
    enable_network_metadata: bool,
    diagnostics_enabled: bool,
}

#[derive(Debug, Serialize, Deserialize)]
struct UpdateCheck {
    available: bool,
    version: Option<String>,
}

async fn api<T: DeserializeOwned>(
    state: &CoreState,
    method: Method,
    path: &str,
    body: Option<Value>,
) -> Result<T, String> {
    let url = format!("{}{}", state.base_url, path);
    let mut request = state
        .client
        .request(method, url)
        .header("X-Research-Memory-Token", &state.token);
    if let Some(payload) = body {
        request = request.json(&payload);
    }
    let response = request.send().await.map_err(|error| {
        format!(
            "The private research core is not responding ({})",
            error.status().map_or("connection", |_| "http")
        )
    })?;
    let status = response.status();
    if !status.is_success() {
        let error: Value = response.json().await.unwrap_or_else(|_| json!({}));
        let message = error
            .get("detail")
            .and_then(Value::as_str)
            .unwrap_or("The private core rejected this command");
        return Err(format!("{message} [{status}]"));
    }
    response
        .json::<T>()
        .await
        .map_err(|_| "The private core returned an invalid typed response".to_string())
}

#[tauri::command]
async fn core_status(state: State<'_, CoreState>) -> Result<CoreStatus, String> {
    api(&state, Method::GET, "/api/v1/status", None).await
}

#[tauri::command]
async fn taxonomy_catalog(
    state: State<'_, CoreState>,
    query: String,
    node_type: Option<String>,
    parent: Option<String>,
    limit: i64,
    offset: i64,
) -> Result<TaxonomyCatalogPage, String> {
    let mut path = format!(
        "/api/v1/taxonomy/catalog?query={}&limit={limit}&offset={offset}",
        urlencoding::encode(&query)
    );
    if let Some(node_type) = node_type {
        path.push_str("&node_type=");
        path.push_str(&urlencoding::encode(&node_type));
    }
    if let Some(parent) = parent {
        path.push_str("&parent=");
        path.push_str(&urlencoding::encode(&parent));
    }
    api(&state, Method::GET, &path, None).await
}

#[tauri::command]
async fn taxonomy_node(
    state: State<'_, CoreState>,
    node_id: String,
) -> Result<TaxonomyNode, String> {
    let node_id = validated_taxonomy_id(&node_id)?;
    api(
        &state,
        Method::GET,
        &format!("/api/v1/taxonomy/nodes/{node_id}"),
        None,
    )
    .await
}

#[tauri::command]
async fn taxonomy_packs(
    state: State<'_, CoreState>,
    pack_type: Option<String>,
) -> Result<Vec<SpecialtyPackSummary>, String> {
    let path = pack_type.map_or_else(
        || "/api/v1/taxonomy/packs".to_string(),
        |value| {
            format!(
                "/api/v1/taxonomy/packs?pack_type={}",
                urlencoding::encode(&value)
            )
        },
    );
    api(&state, Method::GET, &path, None).await
}

#[tauri::command]
async fn taxonomy_tree(state: State<'_, CoreState>) -> Result<PersonalizedTaxonomyTree, String> {
    api(&state, Method::GET, "/api/v1/taxonomy/tree", None).await
}

#[tauri::command]
async fn list_articles(
    state: State<'_, CoreState>,
    query: String,
    limit: i64,
    offset: i64,
) -> Result<ArticlePage, String> {
    let encoded = urlencoding::encode(&query);
    api(
        &state,
        Method::GET,
        &format!("/api/v1/articles/page?query={encoded}&limit={limit}&offset={offset}"),
        None,
    )
    .await
}

#[tauri::command]
async fn get_article(
    state: State<'_, CoreState>,
    article_id: i64,
) -> Result<ArticleDetail, String> {
    api(
        &state,
        Method::GET,
        &format!("/api/v1/articles/{article_id}"),
        None,
    )
    .await
}

#[tauri::command]
async fn list_trash(state: State<'_, CoreState>) -> Result<Vec<TrashArticle>, String> {
    api(&state, Method::GET, "/api/v1/trash", None).await
}

#[tauri::command]
async fn trash_article(
    state: State<'_, CoreState>,
    article_id: i64,
    title: String,
) -> Result<bool, String> {
    let confirmed = rfd::AsyncMessageDialog::new()
        .set_level(rfd::MessageLevel::Warning)
        .set_title("Move paper to Trash?")
        .set_description(format!(
            "“{title}” will leave your library and can be restored for 30 days. The original source file will not be changed."
        ))
        .set_buttons(rfd::MessageButtons::YesNo)
        .show()
        .await;
    if confirmed != rfd::MessageDialogResult::Yes {
        return Ok(false);
    }
    let url = format!("{}/api/v1/articles/{article_id}", state.base_url);
    let response = state
        .client
        .delete(url)
        .header("X-Research-Memory-Token", &state.token)
        .send()
        .await
        .map_err(|_| "The paper could not be moved to Trash".to_string())?;
    if response.status().is_success() {
        Ok(true)
    } else {
        Err("The paper could not be moved to Trash".to_string())
    }
}

#[tauri::command]
async fn restore_article(state: State<'_, CoreState>, article_id: i64) -> Result<(), String> {
    let url = format!("{}/api/v1/trash/{article_id}/restore", state.base_url);
    let response = state
        .client
        .post(url)
        .header("X-Research-Memory-Token", &state.token)
        .send()
        .await
        .map_err(|_| "The paper could not be restored".to_string())?;
    if response.status().is_success() {
        Ok(())
    } else {
        Err("The paper could not be restored".to_string())
    }
}

#[tauri::command]
async fn update_article(
    state: State<'_, CoreState>,
    article_id: i64,
    value: Value,
) -> Result<ArticleDetail, String> {
    api(
        &state,
        Method::PATCH,
        &format!("/api/v1/articles/{article_id}"),
        Some(value),
    )
    .await
}

#[tauri::command]
async fn resolve_article_review(
    state: State<'_, CoreState>,
    article_id: i64,
    resolution: String,
) -> Result<ArticleDetail, String> {
    api(
        &state,
        Method::POST,
        &format!("/api/v1/articles/{article_id}/review"),
        Some(json!({"resolution": resolution})),
    )
    .await
}

#[tauri::command]
async fn unlock_article(
    state: State<'_, CoreState>,
    article_id: i64,
    password: String,
) -> Result<ImportJob, String> {
    api(
        &state,
        Method::POST,
        &format!("/api/v1/articles/{article_id}/unlock"),
        Some(json!({"password": password})),
    )
    .await
}

#[tauri::command]
async fn recall_search(
    state: State<'_, CoreState>,
    query: SearchQuery,
) -> Result<Vec<SearchHit>, String> {
    api(
        &state,
        Method::POST,
        "/api/v1/search",
        Some(serde_json::to_value(query).map_err(|error| error.to_string())?),
    )
    .await
}

async fn start_import(
    state: &CoreState,
    path: PathBuf,
    source_kind: &str,
) -> Result<ImportJob, String> {
    api(
        state,
        Method::POST,
        "/api/v1/imports",
        Some(json!({
            "path": path,
            "recursive": source_kind == "folder",
            "watch": source_kind == "folder",
            "source_kind": source_kind
        })),
    )
    .await
}

#[tauri::command]
async fn choose_import_folder(state: State<'_, CoreState>) -> Result<Option<ImportJob>, String> {
    let selected = rfd::AsyncFileDialog::new()
        .set_title("Choose a folder of research PDFs")
        .pick_folder()
        .await;
    match selected {
        Some(folder) => {
            let path = folder.path().to_path_buf();
            let job = start_import(&state, path.clone(), "folder").await?;
            let watcher_enabled = attach_watcher(&state, path.clone(), true, false)?;
            enable_watcher_after_folder_imports(&state, path, watcher_enabled);
            Ok(Some(job))
        }
        None => Ok(None),
    }
}

#[tauri::command]
async fn choose_import_files(state: State<'_, CoreState>) -> Result<Vec<ImportJob>, String> {
    let selected = rfd::AsyncFileDialog::new()
        .set_title("Choose research PDFs")
        .add_filter("PDF documents", &["pdf"])
        .pick_files()
        .await;
    let mut jobs = Vec::new();
    if let Some(files) = selected {
        for file in files {
            jobs.push(start_import(&state, file.path().to_path_buf(), "file").await?);
        }
    }
    Ok(jobs)
}

#[tauri::command]
async fn import_zotero(state: State<'_, CoreState>) -> Result<ImportJob, String> {
    api(
        &state,
        Method::POST,
        "/api/v1/imports/zotero",
        Some(json!({"base_url": "http://127.0.0.1:23119/api"})),
    )
    .await
}

#[tauri::command]
async fn list_jobs(state: State<'_, CoreState>) -> Result<Vec<ImportJob>, String> {
    api(&state, Method::GET, "/api/v1/jobs?limit=500", None).await
}

#[tauri::command]
async fn list_job_issues(
    state: State<'_, CoreState>,
    job_id: String,
) -> Result<Vec<ImportIssue>, String> {
    let job_id = validated_uuid(&job_id, "job")?;
    api(
        &state,
        Method::GET,
        &format!("/api/v1/jobs/{job_id}/issues"),
        None,
    )
    .await
}

#[tauri::command]
async fn cancel_job(state: State<'_, CoreState>, job_id: String) -> Result<(), String> {
    let job_id = validated_uuid(&job_id, "job")?;
    let _: Value = api(
        &state,
        Method::POST,
        &format!("/api/v1/jobs/{job_id}/cancel"),
        None,
    )
    .await?;
    Ok(())
}

#[tauri::command]
async fn retry_job(state: State<'_, CoreState>, job_id: String) -> Result<ImportJob, String> {
    let job_id = validated_uuid(&job_id, "job")?;
    api(
        &state,
        Method::POST,
        &format!("/api/v1/jobs/{job_id}/retry"),
        None,
    )
    .await
}

#[tauri::command]
async fn asset_url(state: State<'_, CoreState>, asset_id: i64) -> Result<String, String> {
    let access: Value = api(
        &state,
        Method::POST,
        &format!("/api/v1/assets/{asset_id}/access"),
        None,
    )
    .await?;
    let path = access
        .get("url")
        .and_then(Value::as_str)
        .ok_or_else(|| "The core did not issue an asset capability".to_string())?;
    Ok(format!("{}{}", state.base_url, path))
}

#[tauri::command]
async fn create_annotation(
    state: State<'_, CoreState>,
    article_id: i64,
    value: Value,
) -> Result<Annotation, String> {
    api(
        &state,
        Method::POST,
        &format!("/api/v1/articles/{article_id}/annotations"),
        Some(value),
    )
    .await
}

#[tauri::command]
async fn delete_annotation(
    state: State<'_, CoreState>,
    article_id: i64,
    annotation_id: String,
) -> Result<(), String> {
    let annotation_id = validated_uuid(&annotation_id, "annotation")?;
    let url = format!(
        "{}/api/v1/articles/{article_id}/annotations/{annotation_id}",
        state.base_url
    );
    let response = state
        .client
        .delete(url)
        .header("X-Research-Memory-Token", &state.token)
        .send()
        .await
        .map_err(|_| "The annotation could not be deleted".to_string())?;
    if response.status().is_success() {
        Ok(())
    } else {
        Err("The annotation could not be deleted".to_string())
    }
}

fn validated_uuid(value: &str, label: &str) -> Result<String, String> {
    Uuid::parse_str(value)
        .map(|parsed| parsed.to_string())
        .map_err(|_| format!("Invalid {label} identifier"))
}

fn validated_taxonomy_id(value: &str) -> Result<String, String> {
    let Some((prefix, identifier)) = value.split_once('.') else {
        return Err("Invalid taxonomy identifier".to_string());
    };
    let valid_segment = |segment: &str| {
        !segment.is_empty()
            && segment.chars().all(|character| {
                character.is_ascii_lowercase() || character.is_ascii_digit() || character == '_'
            })
    };
    if value.len() <= 200 && valid_segment(prefix) && valid_segment(identifier) {
        Ok(value.to_string())
    } else {
        Err("Invalid taxonomy identifier".to_string())
    }
}

#[tauri::command]
async fn install_model(state: State<'_, CoreState>) -> Result<ImportJob, String> {
    api(
        &state,
        Method::POST,
        "/api/v1/models/install",
        Some(json!({"consent_to_download": true})),
    )
    .await
}

#[tauri::command]
async fn create_backup(
    state: State<'_, CoreState>,
    passphrase: String,
) -> Result<Option<String>, String> {
    let selected = rfd::AsyncFileDialog::new()
        .set_title("Create encrypted Research Memory backup")
        .set_file_name("Research Memory Backup.rmbak")
        .add_filter("Research Memory backup", &["rmbak"])
        .save_file()
        .await;
    let Some(file) = selected else {
        return Ok(None);
    };
    ensure_external_destination(file.path(), &state.data_dir)?;
    let result: Value = api(
        &state,
        Method::POST,
        "/api/v1/backups",
        Some(json!({"destination": file.path(), "passphrase": passphrase})),
    )
    .await?;
    Ok(result
        .get("file_name")
        .and_then(Value::as_str)
        .map(str::to_string))
}

#[tauri::command]
async fn restore_backup(
    state: State<'_, CoreState>,
    passphrase: String,
) -> Result<Option<Value>, String> {
    let selected = rfd::AsyncFileDialog::new()
        .set_title("Restore a Research Memory backup")
        .add_filter("Research Memory backup", &["rmbak"])
        .pick_file()
        .await;
    let Some(file) = selected else {
        return Ok(None);
    };
    let confirmed = rfd::AsyncMessageDialog::new()
        .set_level(rfd::MessageLevel::Warning)
        .set_title("Replace this library from backup?")
        .set_description(
            "Research Memory will validate the encrypted backup, replace the current library, and restart its private core. This cannot be undone unless you have another backup.",
        )
        .set_buttons(rfd::MessageButtons::YesNo)
        .show()
        .await;
    if confirmed != rfd::MessageDialogResult::Yes {
        return Ok(None);
    }
    let result = api(
        &state,
        Method::POST,
        "/api/v1/backups/restore",
        Some(json!({"source": file.path(), "passphrase": passphrase})),
    )
    .await?;
    Ok(Some(result))
}

#[tauri::command]
async fn list_projects(state: State<'_, CoreState>) -> Result<Vec<Project>, String> {
    api(&state, Method::GET, "/api/v1/projects", None).await
}

#[tauri::command]
async fn create_project(
    state: State<'_, CoreState>,
    name: String,
    description: String,
) -> Result<Project, String> {
    api(
        &state,
        Method::POST,
        "/api/v1/projects",
        Some(json!({
            "name": name,
            "description": description,
            "project_type": "collection"
        })),
    )
    .await
}

#[tauri::command]
async fn list_project_articles(
    state: State<'_, CoreState>,
    project_id: i64,
) -> Result<Vec<ArticleSummary>, String> {
    api(
        &state,
        Method::GET,
        &format!("/api/v1/projects/{project_id}/articles"),
        None,
    )
    .await
}

#[tauri::command]
async fn add_project_article(
    state: State<'_, CoreState>,
    project_id: i64,
    article_id: i64,
) -> Result<(), String> {
    let url = format!(
        "{}/api/v1/projects/{project_id}/articles/{article_id}",
        state.base_url
    );
    let response = state
        .client
        .put(url)
        .header("X-Research-Memory-Token", &state.token)
        .json(&json!({"status": "candidate"}))
        .send()
        .await
        .map_err(|_| "The paper could not be added to the project".to_string())?;
    if response.status().is_success() {
        Ok(())
    } else {
        Err("The paper could not be added to the project".to_string())
    }
}

#[tauri::command]
async fn add_project_articles(
    state: State<'_, CoreState>,
    project_id: i64,
    article_ids: Vec<i64>,
) -> Result<ProjectArticlesBulkResult, String> {
    api(
        &state,
        Method::POST,
        &format!("/api/v1/projects/{project_id}/articles/bulk"),
        Some(json!({"article_ids": article_ids})),
    )
    .await
}

#[tauri::command]
async fn update_privacy(
    state: State<'_, CoreState>,
    enable_network_metadata: bool,
    diagnostics_enabled: bool,
) -> Result<PrivacySettings, String> {
    api(
        &state,
        Method::PATCH,
        "/api/v1/settings/privacy",
        Some(json!({
            "enable_network_metadata": enable_network_metadata,
            "diagnostics_enabled": diagnostics_enabled
        })),
    )
    .await
}

#[tauri::command]
async fn create_support_bundle(state: State<'_, CoreState>) -> Result<Option<String>, String> {
    let selected = rfd::AsyncFileDialog::new()
        .set_title("Save redacted Research Memory support bundle")
        .set_file_name("Research Memory Support.zip")
        .add_filter("ZIP archive", &["zip"])
        .save_file()
        .await;
    let Some(file) = selected else {
        return Ok(None);
    };
    ensure_external_destination(file.path(), &state.data_dir)?;
    let result: Value = api(
        &state,
        Method::POST,
        "/api/v1/support-bundles",
        Some(json!({"destination": file.path()})),
    )
    .await?;
    Ok(result
        .get("file_name")
        .and_then(Value::as_str)
        .map(str::to_string))
}

#[tauri::command]
async fn export_article(
    state: State<'_, CoreState>,
    article_id: i64,
    asset_id: i64,
    export_type: String,
    suggested_name: String,
) -> Result<Option<String>, String> {
    let (endpoint, extension, filter_name) = match export_type.as_str() {
        "markdown" => ("annotations.md", "md", "Markdown"),
        "ris" => ("citation.ris", "ris", "RIS citation"),
        "bibtex" => ("citation.bib", "bib", "BibTeX citation"),
        "xfdf" => ("annotations.xfdf", "xfdf", "XFDF annotations"),
        "annotated_pdf" => ("annotated.pdf", "pdf", "PDF document"),
        _ => return Err("Unsupported export type".to_string()),
    };
    let selected = rfd::AsyncFileDialog::new()
        .set_title("Export article")
        .set_file_name(&suggested_name)
        .add_filter(filter_name, &[extension])
        .save_file()
        .await;
    let Some(file) = selected else {
        return Ok(None);
    };
    ensure_external_destination(file.path(), &state.data_dir)?;
    let asset_query = matches!(export_type.as_str(), "markdown" | "xfdf" | "annotated_pdf")
        .then(|| format!("?asset_id={asset_id}"))
        .unwrap_or_default();
    let url = format!(
        "{}/api/v1/articles/{article_id}/exports/{endpoint}{asset_query}",
        state.base_url
    );
    let response = state
        .client
        .get(url)
        .header("X-Research-Memory-Token", &state.token)
        .send()
        .await
        .map_err(|_| "The export could not be generated".to_string())?;
    if !response.status().is_success() {
        return Err("The export could not be generated".to_string());
    }
    let bytes = response
        .bytes()
        .await
        .map_err(|_| "The export could not be read".to_string())?;
    write_atomic(file.path(), &bytes)?;
    Ok(file
        .path()
        .file_name()
        .and_then(|name| name.to_str())
        .map(str::to_string))
}

#[tauri::command]
async fn check_for_updates(app: AppHandle) -> Result<UpdateCheck, String> {
    let updater = app.updater().map_err(|error| error.to_string())?;
    match updater.check().await.map_err(|error| error.to_string())? {
        Some(update) => Ok(UpdateCheck {
            available: true,
            version: Some(update.version),
        }),
        None => Ok(UpdateCheck {
            available: false,
            version: None,
        }),
    }
}

#[tauri::command]
async fn install_update(app: AppHandle) -> Result<String, String> {
    let updater = app.updater().map_err(|error| error.to_string())?;
    let Some(update) = updater.check().await.map_err(|error| error.to_string())? else {
        return Ok("Research Memory is already up to date.".to_string());
    };
    update
        .download_and_install(|_, _| {}, || {})
        .await
        .map_err(|error| error.to_string())?;
    app.restart()
}

fn available_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|error| error.to_string())?;
    listener
        .local_addr()
        .map(|address| address.port())
        .map_err(|error| error.to_string())
}

fn ensure_external_destination(destination: &Path, data_dir: &Path) -> Result<(), String> {
    let parent = destination
        .parent()
        .ok_or_else(|| "Choose a destination folder outside the app library".to_string())?;
    let canonical_parent = parent
        .canonicalize()
        .map_err(|_| "The destination folder is unavailable".to_string())?;
    let canonical_data = data_dir
        .canonicalize()
        .map_err(|_| "The app library is unavailable".to_string())?;
    if canonical_parent == canonical_data || canonical_parent.starts_with(&canonical_data) {
        return Err("Choose a destination outside the managed Research Memory library".to_string());
    }
    if destination.exists()
        && let Ok(canonical_destination) = destination.canonicalize()
        && (canonical_destination == canonical_data
            || canonical_destination.starts_with(&canonical_data))
    {
        return Err("Choose a destination outside the managed Research Memory library".to_string());
    }
    Ok(())
}

fn write_atomic(destination: &Path, bytes: &[u8]) -> Result<(), String> {
    let parent = destination
        .parent()
        .ok_or_else(|| "The export destination is invalid".to_string())?;
    let file_name = destination
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("research-memory-export");
    let temporary = parent.join(format!(".{file_name}.{}.tmp", Uuid::new_v4().simple()));
    let result = (|| -> std::io::Result<()> {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        std::fs::rename(&temporary, destination)
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result.map_err(|_| "The export could not be saved".to_string())
}

fn is_pdf_path(path: &Path) -> bool {
    path.extension()
        .and_then(|value| value.to_str())
        .is_some_and(|value| value.eq_ignore_ascii_case("pdf"))
}

async fn wait_for_stable_pdf(path: &Path) -> bool {
    let mut previous = None;
    let mut stable_intervals = 0;
    for _ in 0..20 {
        let current = std::fs::metadata(path).ok().and_then(|metadata| {
            metadata
                .is_file()
                .then(|| (metadata.len(), metadata.modified().ok()))
        });
        match current {
            Some(value) if value.0 > 0 && Some(value) == previous => {
                stable_intervals += 1;
                if stable_intervals >= 2 {
                    return true;
                }
            }
            Some(value) => {
                previous = Some(value);
                stable_intervals = 0;
            }
            None => {
                previous = None;
                stable_intervals = 0;
            }
        }
        tokio::time::sleep(Duration::from_millis(750)).await;
    }
    false
}

fn enable_watcher_after_folder_imports(
    state: &CoreState,
    path: PathBuf,
    watcher_enabled: Arc<AtomicBool>,
) {
    let base_url = state.base_url.clone();
    let token = state.token.clone();
    let client = state.client.clone();
    tauri::async_runtime::spawn(async move {
        loop {
            let response = client
                .get(format!("{base_url}/api/v1/watches/internal"))
                .header("X-Research-Memory-Token", &token)
                .send()
                .await;
            if let Ok(response) = response
                && response.status().is_success()
                && let Ok(records) = response.json::<Vec<WatchRecord>>().await
                && records
                    .iter()
                    .find(|record| record.folder_path == path)
                    .is_none_or(|record| record.active_job_id.is_none())
            {
                watcher_enabled.store(true, Ordering::Release);
                return;
            }
            tokio::time::sleep(Duration::from_millis(500)).await;
        }
    });
}

fn attach_watcher(
    state: &CoreState,
    path: PathBuf,
    recursive: bool,
    initially_enabled: bool,
) -> Result<Arc<AtomicBool>, String> {
    let watcher_enabled = {
        let mut paths = state
            .watcher_controls
            .lock()
            .map_err(|_| "Folder watch state is unavailable".to_string())?;
        if let Some(existing) = paths.get(&path) {
            existing.store(initially_enabled, Ordering::Release);
            return Ok(Arc::clone(existing));
        }
        let enabled = Arc::new(AtomicBool::new(initially_enabled));
        paths.insert(path.clone(), Arc::clone(&enabled));
        enabled
    };
    let base_url = state.base_url.clone();
    let token = state.token.clone();
    let client = state.client.clone();
    let recent = Arc::new(Mutex::new(HashMap::<PathBuf, Instant>::new()));
    let recent_events = Arc::clone(&recent);
    let event_watcher_enabled = Arc::clone(&watcher_enabled);
    let mut watcher = notify::recommended_watcher(move |result: notify::Result<notify::Event>| {
        if !event_watcher_enabled.load(Ordering::Acquire) {
            return;
        }
        let Ok(event) = result else {
            return;
        };
        if !matches!(event.kind, EventKind::Create(_) | EventKind::Modify(_)) {
            return;
        }
        for event_path in event.paths {
            if !is_pdf_path(&event_path) {
                continue;
            }
            let should_enqueue = recent_events
                .lock()
                .map(|mut values| {
                    let now = Instant::now();
                    values.retain(|_, seen| now.duration_since(*seen) < Duration::from_secs(10));
                    if values.contains_key(&event_path) {
                        false
                    } else {
                        values.insert(event_path.clone(), now);
                        true
                    }
                })
                .unwrap_or(false);
            if !should_enqueue {
                continue;
            }
            let event_client = client.clone();
            let event_token = token.clone();
            let endpoint = format!("{base_url}/api/v1/imports");
            tauri::async_runtime::spawn(async move {
                if !wait_for_stable_pdf(&event_path).await {
                    return;
                }
                let _ = event_client
                    .post(endpoint)
                    .header("X-Research-Memory-Token", event_token)
                    .json(&json!({
                        "path": event_path,
                        "recursive": false,
                        "watch": false,
                        "source_kind": "file"
                    }))
                    .send()
                    .await;
            });
        }
    })
    .map_err(|error| error.to_string())?;
    watcher
        .watch(
            &path,
            if recursive {
                RecursiveMode::Recursive
            } else {
                RecursiveMode::NonRecursive
            },
        )
        .map_err(|error| error.to_string())?;
    state
        .watchers
        .lock()
        .map_err(|_| "Folder watch state is unavailable".to_string())?
        .push(watcher);
    Ok(watcher_enabled)
}

pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|app| {
            let port = available_port()?;
            let token = format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple());
            let data_dir = app.path().app_data_dir()?;
            std::fs::create_dir_all(&data_dir)?;
            let bundled_tesseract = std::env::current_exe()
                .ok()
                .and_then(|path| path.parent().map(|parent| parent.join("tesseract")))
                .filter(|path| path.is_file())
                .unwrap_or_else(|| PathBuf::from("tesseract"));
            let mut sidecar = app
                .shell()
                .sidecar("research-memory-core")?
                .env("RESEARCH_MEMORY_IPC_TOKEN", &token)
                .env("RESEARCH_MEMORY_TESSERACT_PATH", &bundled_tesseract);
            if let Ok(resources) = app.path().resource_dir() {
                let tessdata = resources.join("resources/tessdata");
                if tessdata.is_dir() {
                    sidecar = sidecar.env("TESSDATA_PREFIX", &tessdata);
                }
                let models = resources.join("resources/models");
                if models
                    .join("models--qdrant--bge-small-en-v1.5-onnx-q")
                    .is_dir()
                {
                    sidecar = sidecar.env("RESEARCH_MEMORY_MODEL_DIR", &models);
                }
            }
            let sidecar = sidecar.args([
                "--desktop",
                "--no-browser",
                "--host",
                "127.0.0.1",
                "--port",
                &port.to_string(),
                "--data-dir",
                &data_dir.to_string_lossy(),
            ]);
            let (mut events, child) = sidecar.spawn()?;
            tauri::async_runtime::spawn(async move {
                while let Some(event) = events.recv().await {
                    match event {
                        CommandEvent::Stderr(bytes) => {
                            let line = String::from_utf8_lossy(&bytes);
                            if !line.contains("ipc-token") {
                                eprint!("{line}");
                            }
                        }
                        CommandEvent::Terminated(status) => {
                            eprintln!("Research core exited: {:?}", status.code);
                        }
                        _ => {}
                    }
                }
            });
            app.manage(CoreState {
                base_url: format!("http://127.0.0.1:{port}"),
                token,
                data_dir,
                client: Client::builder()
                    .timeout(Duration::from_secs(300))
                    .build()?,
                child: Mutex::new(Some(child)),
                watchers: Mutex::new(Vec::new()),
                watcher_controls: Mutex::new(HashMap::new()),
            });
            let app_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                for _ in 0..60 {
                    let state = app_handle.state::<CoreState>();
                    match api::<Vec<WatchRecord>>(
                        &state,
                        Method::GET,
                        "/api/v1/watches/internal",
                        None,
                    )
                    .await
                    {
                        Ok(records) => {
                            for record in records {
                                let folder_path = record.folder_path;
                                let has_active_import = record.active_job_id.is_some();
                                let watcher_enabled = attach_watcher(
                                    &state,
                                    folder_path.clone(),
                                    record.recursive,
                                    !has_active_import,
                                );
                                if let (Ok(watcher_enabled), true) =
                                    (watcher_enabled, has_active_import)
                                {
                                    enable_watcher_after_folder_imports(
                                        &state,
                                        folder_path,
                                        watcher_enabled,
                                    );
                                }
                            }
                            break;
                        }
                        Err(_) => tokio::time::sleep(Duration::from_millis(250)).await,
                    }
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            core_status,
            taxonomy_catalog,
            taxonomy_node,
            taxonomy_packs,
            taxonomy_tree,
            list_articles,
            get_article,
            list_trash,
            trash_article,
            restore_article,
            update_article,
            resolve_article_review,
            unlock_article,
            recall_search,
            choose_import_folder,
            choose_import_files,
            import_zotero,
            list_jobs,
            list_job_issues,
            cancel_job,
            retry_job,
            asset_url,
            create_annotation,
            delete_annotation,
            install_model,
            create_backup,
            restore_backup,
            list_projects,
            create_project,
            list_project_articles,
            add_project_article,
            add_project_articles,
            update_privacy,
            create_support_bundle,
            export_article,
            check_for_updates,
            install_update,
        ]);

    let app = builder
        .build(tauri::generate_context!())
        .expect("failed to build Research Memory");
    app.run(|handle, event| {
        if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. })
            && let Some(state) = handle.try_state::<CoreState>()
            && let Ok(mut child) = state.child.lock()
            && let Some(process) = child.take()
        {
            let _ = process.kill();
        }
    });
}

#[cfg(test)]
mod tests {
    use super::{
        ArticleDetail, PersonalizedTaxonomyTree, SpecialtyPackSummary, TaxonomyCatalogPage,
        TaxonomyNode, available_port, ensure_external_destination, is_pdf_path,
        validated_taxonomy_id, validated_uuid, write_atomic,
    };
    use std::path::Path;

    #[test]
    fn validates_identifiers_before_using_them_in_api_paths() {
        let value = "8ba076a7-49bc-4244-84cf-5f60164f2ba2";
        assert_eq!(validated_uuid(value, "job").expect("valid UUID"), value);
        assert!(validated_uuid("../assets/1", "job").is_err());
        assert_eq!(
            validated_taxonomy_id("disease.pulmonary_hypertension").expect("valid taxonomy ID"),
            "disease.pulmonary_hypertension"
        );
        assert!(validated_taxonomy_id("../taxonomy/catalog").is_err());
    }

    #[test]
    fn folder_watches_accept_only_pdf_extensions() {
        assert!(is_pdf_path(Path::new("/tmp/paper.PDF")));
        assert!(!is_pdf_path(Path::new("/tmp/paper.pdf.tmp")));
        assert!(!is_pdf_path(Path::new("/tmp/paper")));
    }

    #[test]
    fn loopback_port_selection_returns_a_bindable_port() {
        assert!(available_port().expect("available loopback port") > 0);
    }

    #[test]
    fn article_contract_preserves_reader_review_state() {
        let article: ArticleDetail = serde_json::from_value(serde_json::json!({
            "id": 1,
            "title": "Reader contract",
            "authors": "",
            "journal": "",
            "publication_year": null,
            "source_type": "journal_article",
            "reading_status": "unread",
            "importance": 0,
            "page_count": 1,
            "why_saved": "",
            "extraction_status": "indexed",
            "review_state": "ready",
            "doi": "",
            "pmid": "",
            "abstract": "",
            "user_summary": "",
            "metadata_conflicts": [],
            "assets": [],
            "annotations": []
        }))
        .expect("valid article detail");
        let renderer_value = serde_json::to_value(article).expect("serialize article detail");
        assert_eq!(renderer_value["review_state"], "ready");
    }

    #[test]
    fn taxonomy_contracts_round_trip_without_untyped_bridge_values() {
        let page: TaxonomyCatalogPage = serde_json::from_value(serde_json::json!({
            "items": [{
                "id": "disease.copd",
                "node_type": "disease",
                "canonical_name": "Chronic obstructive pulmonary disease",
                "status": "active"
            }],
            "total": 1,
            "limit": 100,
            "offset": 0,
            "catalog_version": "taxonomy-v1"
        }))
        .expect("valid taxonomy page");
        let node: TaxonomyNode = serde_json::from_value(serde_json::json!({
            "id": "disease.copd",
            "node_type": "disease",
            "canonical_name": "Chronic obstructive pulmonary disease",
            "status": "active",
            "description": "",
            "source_system": "research_memory",
            "source_code": "",
            "source_version": "taxonomy-v1",
            "external_mappings": [],
            "metadata": {"curation_status": "starter"}
        }))
        .expect("valid taxonomy node");
        let pack: SpecialtyPackSummary = serde_json::from_value(serde_json::json!({
            "pack_id": "pack.subspecialty.pulmonary_disease",
            "display_name": "Pulmonary Disease",
            "pack_type": "subspecialty",
            "version": "1.0.0",
            "selection_node_id": "subspecialty.pulmonary_disease",
            "curation_status": "curated",
            "inherits": ["pack.specialty.internal_medicine"],
            "membership_count": 11,
            "state_archetypes": ["state_archetype.pulmonary"]
        }))
        .expect("valid pack summary");
        let tree: PersonalizedTaxonomyTree = serde_json::from_value(serde_json::json!({
            "catalog_version": "taxonomy-v1",
            "profile_revision": "revision",
            "warnings": [],
            "roots": [{
                "canonical_node_id": "subspecialty.pulmonary_disease",
                "display_instance_id": "display.123",
                "parent_display_instance_id": null,
                "display_name": "Pulmonary Disease",
                "node_type": "subspecialty",
                "weight": 0.95,
                "depth": 0,
                "visible": true,
                "pinned": false,
                "children": []
            }],
            "total_canonical_nodes": 1
        }))
        .expect("valid personalized tree");
        assert_eq!(
            serde_json::to_value(page).expect("serialize page")["catalog_version"],
            "taxonomy-v1"
        );
        assert_eq!(
            serde_json::to_value(node).expect("serialize node")["id"],
            "disease.copd"
        );
        assert_eq!(
            serde_json::to_value(pack).expect("serialize pack")["membership_count"],
            11
        );
        assert_eq!(
            serde_json::to_value(tree).expect("serialize tree")["roots"][0]["canonical_node_id"],
            "subspecialty.pulmonary_disease"
        );
    }

    #[test]
    fn development_updater_configuration_is_explicitly_disabled() {
        let config: serde_json::Value =
            serde_json::from_str(include_str!("../tauri.conf.json")).expect("valid Tauri config");
        let updater = &config["plugins"]["updater"];
        assert_eq!(updater["pubkey"], "");
        assert_eq!(updater["endpoints"], serde_json::json!([]));
        assert_eq!(updater["dangerousInsecureTransportProtocol"], false);
    }

    #[test]
    fn custom_title_bar_can_start_native_window_dragging() {
        let capability: serde_json::Value =
            serde_json::from_str(include_str!("../capabilities/default.json"))
                .expect("valid default capability");
        let permissions = capability["permissions"]
            .as_array()
            .expect("capability permissions");
        assert!(
            permissions
                .iter()
                .any(|permission| permission == "core:window:allow-start-dragging")
        );
    }

    #[test]
    fn exports_are_atomic_and_cannot_target_managed_storage() {
        let root = std::env::temp_dir().join(format!(
            "research-memory-rust-test-{}",
            uuid::Uuid::new_v4().simple()
        ));
        let managed = root.join("managed");
        let outside = root.join("exports");
        std::fs::create_dir_all(&managed).expect("managed test directory");
        std::fs::create_dir_all(&outside).expect("export test directory");
        assert!(ensure_external_destination(&managed.join("paper.pdf"), &managed).is_err());
        let destination = outside.join("paper.pdf");
        ensure_external_destination(&destination, &managed).expect("external destination");
        let managed_file = managed.join("immutable.pdf");
        std::fs::write(&managed_file, b"immutable").expect("managed test file");
        let unsafe_link = outside.join("unsafe.pdf");
        std::os::unix::fs::symlink(&managed_file, &unsafe_link).expect("test symlink");
        assert!(ensure_external_destination(&unsafe_link, &managed).is_err());
        write_atomic(&destination, b"first").expect("initial atomic export");
        write_atomic(&destination, b"second").expect("replacement atomic export");
        assert_eq!(
            std::fs::read(&destination).expect("read exported bytes"),
            b"second"
        );
        std::fs::remove_dir_all(&root).expect("remove test directory");
    }
}
