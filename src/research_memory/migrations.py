from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


def _execute_script(connection: sqlite3.Connection, script: str) -> None:
    """Execute a SQL script without sqlite3.executescript's implicit COMMIT."""
    statement = ""
    for line in script.splitlines():
        statement += f"{line}\n"
        if sqlite3.complete_statement(statement):
            sql = statement.strip()
            if sql:
                connection.execute(sql)
            statement = ""
    if statement.strip():
        raise sqlite3.OperationalError("Incomplete SQL statement in migration")


BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL DEFAULT '',
    authors TEXT NOT NULL DEFAULT '',
    journal TEXT NOT NULL DEFAULT '',
    publication_year INTEGER,
    doi TEXT NOT NULL DEFAULT '',
    pmid TEXT NOT NULL DEFAULT '',
    abstract TEXT NOT NULL DEFAULT '',
    page_count INTEGER NOT NULL DEFAULT 0,
    reading_status TEXT NOT NULL DEFAULT 'unread',
    importance INTEGER NOT NULL DEFAULT 0 CHECK (importance BETWEEN 0 AND 5),
    why_saved TEXT NOT NULL DEFAULT '',
    user_summary TEXT NOT NULL DEFAULT '',
    extraction_status TEXT NOT NULL DEFAULT 'indexed',
    metadata_status TEXT NOT NULL DEFAULT 'local',
    source_type TEXT NOT NULL DEFAULT 'journal_article',
    keywords_json TEXT NOT NULL DEFAULT '[]',
    study_card_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_documents_title ON documents(normalized_title);
CREATE INDEX IF NOT EXISTS idx_documents_doi ON documents(doi);
CREATE INDEX IF NOT EXISTS idx_documents_pmid ON documents(pmid);
CREATE INDEX IF NOT EXISTS idx_documents_year ON documents(publication_year);
CREATE INDEX IF NOT EXISTS idx_documents_created ON documents(created_at DESC);

CREATE TABLE IF NOT EXISTS document_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    sha256 TEXT NOT NULL UNIQUE,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    is_primary INTEGER NOT NULL DEFAULT 0,
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_document_files_document ON document_files(document_id);

CREATE TABLE IF NOT EXISTS document_pages (
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(document_id, page_number)
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    embedding BLOB,
    embedding_dim INTEGER NOT NULL DEFAULT 0,
    embedding_backend TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_id, page_number, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_page ON document_chunks(document_id, page_number);

CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(
    text,
    document_id UNINDEXED,
    page_number UNINDEXED,
    chunk_id UNINDEXED,
    tokenize = 'porter unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    note_type TEXT NOT NULL DEFAULT 'note',
    body TEXT NOT NULL,
    page_number INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_notes_document ON notes(document_id, created_at DESC);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    project_type TEXT NOT NULL DEFAULT 'collection',
    central_question TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS project_documents (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'candidate',
    exclusion_reason TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(project_id, document_id)
);
CREATE INDEX IF NOT EXISTS idx_project_documents_document ON project_documents(document_id);

CREATE TABLE IF NOT EXISTS watched_folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_path TEXT NOT NULL UNIQUE,
    recursive INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_scanned_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS saved_searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    query TEXT NOT NULL,
    filters_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _add_column(
    connection: sqlite3.Connection,
    table: str,
    definition: str,
) -> None:
    name = definition.split(maxsplit=1)[0]
    if name not in _columns(connection, table):
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _migration_001(connection: sqlite3.Connection) -> None:
    _execute_script(connection, BASE_SCHEMA)


def _migration_002(connection: sqlite3.Connection) -> None:
    for definition in (
        "deleted_at TEXT",
        "review_state TEXT NOT NULL DEFAULT 'ready'",
        "metadata_conflicts_json TEXT NOT NULL DEFAULT '[]'",
        "external_source TEXT NOT NULL DEFAULT ''",
        "external_key TEXT NOT NULL DEFAULT ''",
        "external_version INTEGER NOT NULL DEFAULT 0",
    ):
        _add_column(connection, "documents", definition)

    for definition in (
        "object_path TEXT NOT NULL DEFAULT ''",
        "original_path TEXT NOT NULL DEFAULT ''",
        "source_kind TEXT NOT NULL DEFAULT 'legacy'",
        "role TEXT NOT NULL DEFAULT 'article'",
        "version_label TEXT NOT NULL DEFAULT ''",
        "availability TEXT NOT NULL DEFAULT 'available'",
        "mime_type TEXT NOT NULL DEFAULT 'application/pdf'",
    ):
        _add_column(connection, "document_files", definition)

    for definition in (
        "width REAL NOT NULL DEFAULT 0",
        "height REAL NOT NULL DEFAULT 0",
        "extraction_method TEXT NOT NULL DEFAULT 'legacy'",
        "extraction_confidence REAL NOT NULL DEFAULT 0",
        "layout_json TEXT NOT NULL DEFAULT '[]'",
    ):
        _add_column(connection, "document_pages", definition)

    for definition in (
        "file_id INTEGER REFERENCES document_files(id) ON DELETE CASCADE",
        "bounding_boxes_json TEXT NOT NULL DEFAULT '[]'",
        "index_version TEXT NOT NULL DEFAULT ''",
        "embedding_model TEXT NOT NULL DEFAULT ''",
    ):
        _add_column(connection, "document_chunks", definition)

    _execute_script(
        connection,
        """
        CREATE INDEX IF NOT EXISTS idx_documents_deleted ON documents(deleted_at);
        CREATE INDEX IF NOT EXISTS idx_documents_external
            ON documents(external_source, external_key);
        CREATE INDEX IF NOT EXISTS idx_files_object_path ON document_files(object_path);

        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            stage TEXT NOT NULL DEFAULT 'queued',
            status TEXT NOT NULL DEFAULT 'queued',
            progress_current INTEGER NOT NULL DEFAULT 0,
            progress_total INTEGER NOT NULL DEFAULT 0,
            input_json TEXT NOT NULL DEFAULT '{}',
            checkpoint_json TEXT NOT NULL DEFAULT '{}',
            output_json TEXT NOT NULL DEFAULT '{}',
            error_code TEXT,
            error_message TEXT,
            retryable INTEGER NOT NULL DEFAULT 0,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            attempt INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at TEXT,
            finished_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_status
            ON jobs(status, created_at);

        CREATE TABLE IF NOT EXISTS metadata_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            field_name TEXT NOT NULL,
            prior_value_json TEXT NOT NULL,
            new_value_json TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'user',
            reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS index_state (
            name TEXT PRIMARY KEY,
            version TEXT NOT NULL,
            item_count INTEGER NOT NULL DEFAULT 0,
            max_item_id INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """,
    )

    connection.execute(
        """
        UPDATE document_files
        SET object_path = CASE WHEN object_path = '' THEN file_path ELSE object_path END,
            original_path = CASE WHEN original_path = '' THEN file_path ELSE original_path END
        """
    )
    # v0.1 derived claims and flat-text indexes are intentionally invalidated.
    # Bibliographic records, notes, projects, and file relationships remain intact.
    connection.execute(
        """
        UPDATE documents
        SET keywords_json = '[]', study_card_json = '{}',
            extraction_status = CASE
                WHEN EXISTS (
                    SELECT 1 FROM document_files f WHERE f.document_id = documents.id
                ) THEN 'reindex_required'
                ELSE extraction_status
            END
        """
    )
    connection.execute("DELETE FROM document_chunks_fts")
    connection.execute("DELETE FROM document_chunks")
    connection.execute("DELETE FROM document_pages")


def _migration_003(connection: sqlite3.Connection) -> None:
    _execute_script(
        connection,
        """
        CREATE TABLE IF NOT EXISTS annotations (
            id TEXT PRIMARY KEY,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            file_id INTEGER NOT NULL REFERENCES document_files(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL,
            annotation_type TEXT NOT NULL,
            color TEXT NOT NULL DEFAULT '#F4C95D',
            quad_points_json TEXT NOT NULL DEFAULT '[]',
            selected_text TEXT NOT NULL DEFAULT '',
            context_hash TEXT NOT NULL DEFAULT '',
            comment TEXT NOT NULL DEFAULT '',
            external_source TEXT NOT NULL DEFAULT '',
            external_key TEXT NOT NULL DEFAULT '',
            deleted_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_annotations_document
            ON annotations(document_id, page_number, created_at);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_annotations_external
            ON annotations(external_source, external_key)
            WHERE external_source != '' AND external_key != '';

        CREATE TABLE IF NOT EXISTS import_sources (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            uri TEXT NOT NULL DEFAULT '',
            config_json TEXT NOT NULL DEFAULT '{}',
            last_cursor TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS external_items (
            source_id TEXT NOT NULL REFERENCES import_sources(id) ON DELETE CASCADE,
            external_key TEXT NOT NULL,
            external_version INTEGER NOT NULL DEFAULT 0,
            document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
            payload_hash TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(source_id, external_key)
        );

        CREATE TABLE IF NOT EXISTS asset_access_tokens (
            token_hash TEXT PRIMARY KEY,
            file_id INTEGER NOT NULL REFERENCES document_files(id) ON DELETE CASCADE,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_asset_tokens_expires
            ON asset_access_tokens(expires_at);
        """,
    )


def _migration_004(connection: sqlite3.Connection) -> None:
    for definition in (
        "external_source TEXT NOT NULL DEFAULT ''",
        "external_key TEXT NOT NULL DEFAULT ''",
        "external_version INTEGER NOT NULL DEFAULT 0",
    ):
        _add_column(connection, "document_files", definition)
    _execute_script(
        connection,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_files_external
            ON document_files(external_source, external_key)
            WHERE external_source != '' AND external_key != '';

        CREATE TABLE IF NOT EXISTS external_collections (
            source_id TEXT NOT NULL REFERENCES import_sources(id) ON DELETE CASCADE,
            external_key TEXT NOT NULL,
            name TEXT NOT NULL,
            parent_key TEXT NOT NULL DEFAULT '',
            external_version INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(source_id, external_key)
        );

        CREATE TABLE IF NOT EXISTS external_item_collections (
            source_id TEXT NOT NULL REFERENCES import_sources(id) ON DELETE CASCADE,
            item_key TEXT NOT NULL,
            collection_key TEXT NOT NULL,
            PRIMARY KEY(source_id, item_key, collection_key)
        );

        CREATE TABLE IF NOT EXISTS external_annotations (
            source_id TEXT NOT NULL REFERENCES import_sources(id) ON DELETE CASCADE,
            external_key TEXT NOT NULL,
            parent_attachment_key TEXT NOT NULL DEFAULT '',
            document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
            external_version INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(source_id, external_key)
        );
        """,
    )


def _migration_005(connection: sqlite3.Connection) -> None:
    _execute_script(
        connection,
        """
        CREATE TABLE IF NOT EXISTS review_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            prior_state TEXT NOT NULL,
            resolution TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_review_decisions_document
            ON review_decisions(document_id, created_at DESC);
        """,
    )


def _migration_006(connection: sqlite3.Connection) -> None:
    _execute_script(
        connection,
        """
        CREATE TABLE IF NOT EXISTS job_issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            source_label TEXT NOT NULL,
            error_code TEXT NOT NULL,
            retryable INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(job_id, source_label, error_code)
        );
        CREATE INDEX IF NOT EXISTS idx_job_issues_job
            ON job_issues(job_id, id);
        """,
    )


def _migration_007(connection: sqlite3.Connection) -> None:
    _execute_script(
        connection,
        """
        CREATE TABLE IF NOT EXISTS external_attachments (
            source_id TEXT NOT NULL REFERENCES import_sources(id) ON DELETE CASCADE,
            external_key TEXT NOT NULL,
            parent_item_key TEXT NOT NULL DEFAULT '',
            document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
            file_id INTEGER REFERENCES document_files(id) ON DELETE SET NULL,
            external_version INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(source_id, external_key)
        );
        CREATE INDEX IF NOT EXISTS idx_external_attachments_document
            ON external_attachments(document_id);
        CREATE INDEX IF NOT EXISTS idx_external_attachments_parent
            ON external_attachments(source_id, parent_item_key);

        INSERT OR IGNORE INTO external_attachments(
            source_id, external_key, document_id, file_id, external_version
        )
        SELECT s.id, f.external_key, f.document_id, f.id, f.external_version
        FROM document_files f
        JOIN import_sources s ON s.kind = 'zotero'
        WHERE f.external_source = 'zotero' AND f.external_key != '';
        """,
    )


def _migration_008(connection: sqlite3.Connection) -> None:
    _execute_script(
        connection,
        """
        CREATE TABLE taxonomy_catalog_versions (
            version TEXT PRIMARY KEY,
            source_date TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            installed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE taxonomy_nodes (
            id TEXT PRIMARY KEY,
            node_type TEXT NOT NULL CHECK (
                node_type IN (
                    'certifying_board', 'specialty', 'subspecialty',
                    'focused_practice', 'research_interest', 'clinical_domain',
                    'disease_family', 'disease', 'phenotype',
                    'clinical_activity', 'procedure', 'diagnostic_test',
                    'device_category', 'population', 'care_setting',
                    'methodology', 'evidence_field', 'work_product',
                    'personal_intent', 'state_dimension'
                )
            ),
            canonical_name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            source_system TEXT NOT NULL DEFAULT 'research_memory',
            source_code TEXT NOT NULL DEFAULT '',
            source_version TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            catalog_version TEXT NOT NULL
                REFERENCES taxonomy_catalog_versions(version),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX idx_taxonomy_nodes_type_name
            ON taxonomy_nodes(node_type, canonical_name);

        CREATE TABLE taxonomy_synonyms (
            node_id TEXT NOT NULL REFERENCES taxonomy_nodes(id) ON DELETE CASCADE,
            synonym TEXT NOT NULL,
            normalized_synonym TEXT NOT NULL,
            language_code TEXT NOT NULL DEFAULT 'en',
            source TEXT NOT NULL DEFAULT 'research_memory',
            PRIMARY KEY (node_id, normalized_synonym, language_code)
        );
        CREATE INDEX idx_taxonomy_synonyms_normalized
            ON taxonomy_synonyms(normalized_synonym);

        CREATE TABLE taxonomy_edges (
            parent_node_id TEXT NOT NULL
                REFERENCES taxonomy_nodes(id) ON DELETE CASCADE,
            child_node_id TEXT NOT NULL
                REFERENCES taxonomy_nodes(id) ON DELETE CASCADE,
            edge_type TEXT NOT NULL CHECK (
                edge_type IN (
                    'is_a', 'part_of', 'offered_by', 'has_subspecialty',
                    'inherits', 'relevant_to', 'commonly_managed_by',
                    'commonly_researched_in', 'has_state_archetype',
                    'diagnosed_by', 'treated_by', 'overlaps_with',
                    'display_under'
                )
            ),
            source TEXT NOT NULL DEFAULT 'research_memory',
            confidence REAL NOT NULL DEFAULT 1.0
                CHECK (confidence BETWEEN 0 AND 1),
            sort_order INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (parent_node_id, child_node_id, edge_type)
        );
        CREATE INDEX idx_taxonomy_edges_child_type
            ON taxonomy_edges(child_node_id, edge_type);

        CREATE TABLE specialty_packs (
            pack_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            pack_type TEXT NOT NULL,
            selection_node_id TEXT NOT NULL REFERENCES taxonomy_nodes(id),
            version TEXT NOT NULL,
            curation_status TEXT NOT NULL DEFAULT 'starter',
            manifest_json TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
        );

        CREATE TABLE specialty_pack_memberships (
            pack_id TEXT NOT NULL
                REFERENCES specialty_packs(pack_id) ON DELETE CASCADE,
            node_id TEXT NOT NULL REFERENCES taxonomy_nodes(id),
            membership_role TEXT NOT NULL,
            display_parent_node_id TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            config_json TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (
                pack_id, node_id, membership_role, display_parent_node_id
            )
        );
        CREATE INDEX idx_specialty_pack_memberships_node_role
            ON specialty_pack_memberships(node_id, membership_role);
        CREATE UNIQUE INDEX idx_specialty_pack_memberships_null_parent
            ON specialty_pack_memberships(pack_id, node_id, membership_role)
            WHERE display_parent_node_id IS NULL;

        CREATE TABLE research_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            role_type TEXT NOT NULL DEFAULT 'physician_researcher',
            automation_mode TEXT NOT NULL DEFAULT 'balanced'
                CHECK (automation_mode IN ('conservative', 'balanced', 'aggressive')),
            hierarchy_depth TEXT NOT NULL DEFAULT 'balanced'
                CHECK (hierarchy_depth IN ('broad', 'balanced', 'detailed')),
            questionnaire_version TEXT NOT NULL,
            raw_answers_json TEXT NOT NULL DEFAULT '{}',
            catalog_version TEXT NOT NULL
                REFERENCES taxonomy_catalog_versions(version),
            onboarding_completed INTEGER NOT NULL DEFAULT 0
                CHECK (onboarding_completed IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE research_profile_selections (
            profile_id INTEGER NOT NULL
                REFERENCES research_profile(id) ON DELETE CASCADE,
            node_id TEXT NOT NULL REFERENCES taxonomy_nodes(id),
            relationship_type TEXT NOT NULL CHECK (
                relationship_type IN (
                    'primary_specialty', 'secondary_specialty', 'subspecialty',
                    'focused_practice', 'research_interest',
                    'disease_interest', 'clinical_activity',
                    'population_interest', 'work_product', 'evidence_priority'
                )
            ),
            priority_weight REAL NOT NULL DEFAULT 0.5
                CHECK (priority_weight BETWEEN 0 AND 1),
            visibility TEXT NOT NULL DEFAULT 'normal',
            source TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (profile_id, node_id, relationship_type)
        );
        CREATE INDEX idx_research_profile_selections_node_relationship
            ON research_profile_selections(node_id, relationship_type);

        CREATE TABLE research_profile_preferences (
            profile_id INTEGER NOT NULL
                REFERENCES research_profile(id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (profile_id, key)
        );

        CREATE TABLE user_navigation_overrides (
            id TEXT PRIMARY KEY,
            profile_id INTEGER NOT NULL
                REFERENCES research_profile(id) ON DELETE CASCADE,
            node_id TEXT NOT NULL REFERENCES taxonomy_nodes(id),
            action TEXT NOT NULL CHECK (action IN ('pin', 'hide', 'move', 'alias')),
            display_parent_node_id TEXT,
            display_alias TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (profile_id, node_id, action, display_parent_node_id)
        );
        CREATE UNIQUE INDEX idx_navigation_overrides_null_parent
            ON user_navigation_overrides(profile_id, node_id, action)
            WHERE display_parent_node_id IS NULL;

        CREATE TABLE article_taxonomy_assignments (
            id TEXT PRIMARY KEY,
            document_id INTEGER NOT NULL
                REFERENCES documents(id) ON DELETE CASCADE,
            node_id TEXT NOT NULL REFERENCES taxonomy_nodes(id),
            node_name_snapshot TEXT NOT NULL,
            node_type TEXT NOT NULL,
            role TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0
                CHECK (confidence BETWEEN 0 AND 1),
            source TEXT NOT NULL CHECK (
                source IN (
                    'user', 'import_metadata', 'deterministic_rule',
                    'classifier', 'external_import'
                )
            ),
            verification_status TEXT NOT NULL CHECK (
                verification_status IN (
                    'suggested', 'auto_applied', 'accepted',
                    'rejected', 'human_verified'
                )
            ),
            state_json TEXT NOT NULL DEFAULT '{}',
            classifier_version TEXT NOT NULL DEFAULT '',
            input_fingerprint TEXT NOT NULL DEFAULT '',
            locked_by_user INTEGER NOT NULL DEFAULT 0
                CHECK (locked_by_user IN (0, 1)),
            display_priority INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (document_id, node_id, role)
        );
        CREATE INDEX idx_article_taxonomy_document_status
            ON article_taxonomy_assignments(document_id, verification_status);
        CREATE INDEX idx_article_taxonomy_node_status_document
            ON article_taxonomy_assignments(
                node_id, verification_status, document_id
            );
        CREATE INDEX idx_article_taxonomy_role_status
            ON article_taxonomy_assignments(role, verification_status);

        CREATE TABLE article_taxonomy_evidence (
            id TEXT PRIMARY KEY,
            assignment_id TEXT NOT NULL
                REFERENCES article_taxonomy_assignments(id) ON DELETE CASCADE,
            file_id INTEGER REFERENCES document_files(id) ON DELETE CASCADE,
            page_number INTEGER CHECK (page_number IS NULL OR page_number > 0),
            chunk_id INTEGER REFERENCES document_chunks(id) ON DELETE SET NULL,
            supporting_text TEXT NOT NULL DEFAULT ''
                CHECK (length(supporting_text) <= 2000),
            bounding_boxes_json TEXT NOT NULL DEFAULT '[]',
            section_type TEXT NOT NULL DEFAULT 'unknown',
            evidence_kind TEXT NOT NULL,
            score REAL NOT NULL DEFAULT 0 CHECK (score BETWEEN 0 AND 1),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX idx_article_taxonomy_evidence_assignment_page
            ON article_taxonomy_evidence(assignment_id, page_number);

        CREATE TABLE taxonomy_decision_history (
            id TEXT PRIMARY KEY,
            assignment_id TEXT
                REFERENCES article_taxonomy_assignments(id) ON DELETE SET NULL,
            document_id INTEGER NOT NULL
                REFERENCES documents(id) ON DELETE CASCADE,
            node_id TEXT NOT NULL,
            action TEXT NOT NULL,
            prior_value_json TEXT NOT NULL DEFAULT '{}',
            new_value_json TEXT NOT NULL DEFAULT '{}',
            reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX idx_taxonomy_decision_history_document_created
            ON taxonomy_decision_history(document_id, created_at DESC);
        """,
    )


MIGRATIONS = (
    Migration(1, "legacy-baseline", _migration_001),
    Migration(2, "managed-assets-and-jobs", _migration_002),
    Migration(3, "annotations-and-external-imports", _migration_003),
    Migration(4, "external-source-relationships", _migration_004),
    Migration(5, "review-decisions", _migration_005),
    Migration(6, "job-issues", _migration_006),
    Migration(7, "zotero-attachment-relationships", _migration_007),
    Migration(8, "taxonomy-catalog-and-local-persistence", _migration_008),
)
CURRENT_SCHEMA_VERSION = MIGRATIONS[-1].version


class MigrationRunner:
    def __init__(self, database_path: Path, backup_dir: Path | None = None):
        self.database_path = database_path
        self.backup_dir = backup_dir or database_path.parent / "backups"

    def run(self, connection: sqlite3.Connection) -> list[int]:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()
        applied = {
            int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")
        }
        pending = [migration for migration in MIGRATIONS if migration.version not in applied]
        if not pending:
            return []

        self._snapshot(connection, max(applied, default=0), pending[-1].version)
        completed: list[int] = []
        for migration in pending:
            try:
                connection.execute("BEGIN IMMEDIATE")
                migration.apply(connection)
                connection.execute(
                    "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                    (migration.version, migration.name),
                )
                connection.execute(f"PRAGMA user_version = {migration.version}")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            completed.append(migration.version)
        return completed

    def _snapshot(self, connection: sqlite3.Connection, start: int, target: int) -> None:
        if not self.database_path.exists() or self.database_path.stat().st_size == 0:
            return
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        destination = self.backup_dir / f"pre-migration-v{start}-to-v{target}-{stamp}.sqlite3"
        with contextlib.closing(sqlite3.connect(destination)) as backup:
            connection.backup(backup)
