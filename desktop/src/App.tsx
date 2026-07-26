import {
  ArchiveRestore,
  ArrowRight,
  BookOpen,
  BriefcaseBusiness,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  FileCheck2,
  FileSearch,
  FolderInput,
  HardDrive,
  Home,
  Inbox,
  Library,
  ListRestart,
  LoaderCircle,
  LockKeyhole,
  Plus,
  RotateCcw,
  Search,
  Settings,
  Sparkles,
  Trash2,
  XCircle,
} from "lucide-react";
import {
  Component,
  lazy,
  Suspense,
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Onboarding } from "./components/Onboarding";
import { core } from "./lib/api";
import type {
  ArticleDetail,
  ArticleSummary,
  CoreStatus,
  EntityId,
  ImportIssue,
  ImportJob,
  Project,
  SearchHit,
  TrashArticle,
  View,
} from "./types";

const PdfReader = lazy(() =>
  import("./components/PdfReader").then((module) => ({ default: module.PdfReader })),
);

export class ReaderErrorBoundary extends Component<
  { children: ReactNode; onClose: () => void },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error) {
    console.error("Research Memory reader failed", error);
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="reader-overlay" role="alert">
          <div className="reader-empty reader-error">
            <CircleAlert />
            <h2>The reader couldn’t open this paper</h2>
            <p>
              Your library and PDF are safe. Close the reader and review the
              paper’s processing status before trying again.
            </p>
            <button className="button primary" onClick={this.props.onClose}>
              Close reader
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

const navigation: { id: View; label: string; icon: typeof Home }[] = [
  { id: "home", label: "Home", icon: Home },
  { id: "library", label: "Library", icon: Library },
  { id: "search", label: "Recall Search", icon: FileSearch },
  { id: "projects", label: "Projects", icon: BriefcaseBusiness },
  { id: "imports", label: "Imports & Jobs", icon: ListRestart },
  { id: "settings", label: "Settings", icon: Settings },
];

function formatType(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function relativeDate(value: string) {
  const delta = Date.now() - new Date(value).getTime();
  const minutes = Math.max(1, Math.round(delta / 60_000));
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function Empty({
  icon: Icon,
  title,
  children,
}: {
  icon: typeof Inbox;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="empty">
      <Icon />
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}

function JobRow({
  job,
  onRefresh,
}: {
  job: ImportJob;
  onRefresh: () => void;
}) {
  const [issues, setIssues] = useState<ImportIssue[] | null>(null);
  const [issuesOpen, setIssuesOpen] = useState(false);
  const icon =
    job.status === "succeeded"
      ? CheckCircle2
      : job.status === "failed"
        ? XCircle
        : job.status === "running"
          ? LoaderCircle
          : Clock3;
  const Icon = icon;
  const progress = job.progress_total
    ? Math.round(job.progress * 100)
    : job.status === "succeeded"
      ? 100
      : 0;
  return (
    <div className={`job-row ${job.status}`}>
      <Icon className={job.status === "running" ? "spin" : ""} />
      <div className="job-main">
        <div><strong>{formatType(job.type)}</strong><span>{job.source}</span></div>
        <small>{formatType(job.stage)} · {relativeDate(job.updated_at)}</small>
        <div className="progress-track"><span style={{ width: `${progress}%` }} /></div>
      </div>
      <div className="job-actions">
        <span className={`status-chip ${job.status}`}>{job.status}</span>
        {job.status === "running" && (
          <button
            className="text-button"
            onClick={() => void core.cancelJob(job.id).then(onRefresh)}
          >
            Cancel
          </button>
        )}
        {job.status === "failed" && job.retryable && (
          <button
            className="text-button"
            onClick={() => void core.retryJob(job.id).then(onRefresh)}
          >
            <RotateCcw size={14} /> Retry
          </button>
        )}
        {job.issue_count > 0 && (
          <button
            className="text-button"
            onClick={() => {
              const nextOpen = !issuesOpen;
              setIssuesOpen(nextOpen);
              if (nextOpen && !issues) {
                void core.jobIssues(job.id).then(setIssues);
              }
            }}
          >
            {issuesOpen ? "Hide" : `Review ${job.issue_count}`}
          </button>
        )}
      </div>
      {job.error_code && <span className="error-code">{job.error_code}</span>}
      {issuesOpen && (
        <div className="job-issues">
          {(issues ?? []).map((issue) => (
            <div key={issue.id}>
              <span>{issue.source_label}</span>
              <code>{formatType(issue.error_code)}</code>
            </div>
          ))}
          {!issues && <small>Loading import issues…</small>}
        </div>
      )}
    </div>
  );
}

function ArticleRow({
  article,
  onOpen,
  selected,
  onSelectedChange,
}: {
  article: ArticleSummary;
  onOpen: () => void;
  selected?: boolean;
  onSelectedChange?: (selected: boolean) => void;
}) {
  if (onSelectedChange) {
    return (
      <div
        className={`article-row article-row-selectable ${selected ? "selected" : ""}`}
        onClick={onOpen}
      >
        <label
          className="article-select"
          onClick={(event) => event.stopPropagation()}
        >
          <input
            type="checkbox"
            checked={Boolean(selected)}
            aria-label={`Select ${article.title}`}
            onChange={(event) => onSelectedChange(event.target.checked)}
          />
        </label>
        <button
          type="button"
          className="article-primary article-primary-button"
          onClick={(event) => {
            event.stopPropagation();
            onOpen();
          }}
        >
          <strong>{article.title}</strong>
          <small>{article.authors || "Unknown author"}</small>
        </button>
        <span>{article.publication_year ?? "—"}</span>
        <span className="type-chip">{formatType(article.source_type)}</span>
        <span className={`extraction ${article.extraction_status}`}>
          {formatType(article.extraction_status)}
        </span>
        <ChevronRight aria-hidden="true" />
      </div>
    );
  }
  return (
    <button className="article-row" onClick={onOpen}>
      <span className="article-icon"><BookOpen /></span>
      <span className="article-primary">
        <strong>{article.title}</strong>
        <small>{article.authors || "Unknown author"}</small>
      </span>
      <span>{article.publication_year ?? "—"}</span>
      <span className="type-chip">{formatType(article.source_type)}</span>
      <span className={`extraction ${article.extraction_status}`}>
        {formatType(article.extraction_status)}
      </span>
      <ChevronRight />
    </button>
  );
}

function HomeView({
  status,
  articles,
  jobs,
  onNavigate,
  onOpen,
  onImport,
}: {
  status: CoreStatus;
  articles: ArticleSummary[];
  jobs: ImportJob[];
  onNavigate: (view: View) => void;
  onOpen: (article: ArticleSummary) => void;
  onImport: () => void;
}) {
  const activeJobs = jobs.filter((job) => job.status === "running" || job.status === "queued");
  return (
    <>
      <section className="welcome">
        <div>
          <span className="eyebrow">Private literature workspace</span>
          <h1>What do you remember?</h1>
          <p>Start with the odd detail, approximate number, method, or phrase that stuck.</p>
        </div>
        <button className="button primary" onClick={onImport}><Plus size={17} /> Add papers</button>
      </section>
      <button className="home-search" onClick={() => onNavigate("search")}>
        <Search />
        <span>Find the paper with the unusually low complication rate…</span>
        <kbd>⌘ K</kbd>
      </button>
      <section className="metric-grid">
        <button onClick={() => onNavigate("library")}>
          <Library /><span><b>{status.documents.toLocaleString()}</b><small>Papers in library</small></span>
        </button>
        <button onClick={() => onNavigate("imports")}>
          <LoaderCircle /><span><b>{activeJobs.length}</b><small>Processing now</small></span>
        </button>
        <button onClick={() => onNavigate("imports")}>
          <CircleAlert /><span><b>{status.review_needed}</b><small>Need review</small></span>
        </button>
        <button onClick={() => onNavigate("settings")}>
          <HardDrive /><span><b>Local</b><small>Storage & privacy</small></span>
        </button>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div><span className="eyebrow">Recently added</span><h2>Continue where you left off</h2></div>
          <button className="text-button" onClick={() => onNavigate("library")}>View library <ArrowRight size={15} /></button>
        </div>
        <div className="article-list">
          {articles.slice(0, 7).map((article) => (
            <ArticleRow key={article.id} article={article} onOpen={() => onOpen(article)} />
          ))}
          {!articles.length && (
            <Empty icon={Inbox} title="Your library is ready">
              Add a folder or connect Zotero to begin building your private research memory.
            </Empty>
          )}
        </div>
      </section>
    </>
  );
}

export function LibraryView({
  onOpen,
  onImport,
}: {
  onOpen: (article: ArticleSummary) => void;
  onImport: () => void;
}) {
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query.trim());
  const [articles, setArticles] = useState<ArticleSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<EntityId>>(() => new Set());
  const [adding, setAdding] = useState(false);
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  const pageSize = 100;

  const load = useCallback(async (offset: number, append: boolean) => {
    setLoading(true);
    try {
      const page = await core.articles(deferred, pageSize, offset);
      setArticles((current) => append ? [...current, ...page.items] : page.items);
      setTotal(page.total);
      setLoadError("");
    } catch (value) {
      setLoadError(value instanceof Error ? value.message : String(value));
    } finally {
      setLoading(false);
    }
  }, [deferred]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(0, false), 150);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    let active = true;
    void core.projects().then((next) => {
      if (!active) return;
      setProjects(next);
      setProjectId((current) =>
        current && next.some((project) => String(project.id) === current)
          ? current
          : "",
      );
    }).catch((value) => {
      if (active) {
        setActionError(value instanceof Error ? value.message : String(value));
      }
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedIds.size) return;
    const clearOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedIds(new Set());
    };
    window.addEventListener("keydown", clearOnEscape);
    return () => window.removeEventListener("keydown", clearOnEscape);
  }, [selectedIds.size]);

  const setArticleSelected = (articleId: EntityId, selected: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (selected) next.add(articleId);
      else next.delete(articleId);
      return next;
    });
    setNotice("");
    setActionError("");
  };

  const setLoadedSelected = (selected: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      for (const article of articles) {
        if (selected) next.add(article.id);
        else next.delete(article.id);
      }
      return next;
    });
    setNotice("");
    setActionError("");
  };

  const addSelectedToProject = async () => {
    if (!projectId || !selectedIds.size) return;
    const selectedProject = projects.find(
      (project) => String(project.id) === projectId,
    );
    if (!selectedProject) return;
    const articleIds = [...selectedIds];
    setAdding(true);
    setActionError("");
    setNotice("");
    try {
      const result = await core.addProjectArticles(selectedProject.id, articleIds);
      const projectName = selectedProject?.name ?? "the project";
      if (result.added) {
        const addedLabel = result.added === 1 ? "paper" : "papers";
        const existingLabel = result.already_present === 1 ? "paper was" : "papers were";
        setNotice(
          `Added ${result.added} ${addedLabel} to ${projectName}.` +
          (result.already_present
            ? ` ${result.already_present} ${existingLabel} already there.`
            : ""),
        );
      } else {
        setNotice(
          result.requested === 1
            ? `The selected paper was already in ${projectName}.`
            : `All ${result.requested} selected papers were already in ${projectName}.`,
        );
      }
      setProjects((current) =>
        current.map((project) =>
          project.id === result.project_id
            ? { ...project, article_count: project.article_count + result.added }
            : project,
        ),
      );
      setSelectedIds(new Set());
    } catch (value) {
      setActionError(value instanceof Error ? value.message : String(value));
    } finally {
      setAdding(false);
    }
  };

  const loadedSelectedCount = articles.reduce(
    (count, article) => count + (selectedIds.has(article.id) ? 1 : 0),
    0,
  );
  const allLoadedSelected =
    articles.length > 0 && loadedSelectedCount === articles.length;

  return (
    <>
      <section className="view-heading">
        <div><span className="eyebrow">Library & inbox</span><h1>Your papers</h1><p>Managed copies stay immutable; notes and annotations live separately.</p></div>
        <button className="button primary" onClick={onImport}><FolderInput size={17} /> Import</button>
      </section>
      <div className="toolbar">
        <label className="field-with-icon"><Search /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter by title or author" /></label>
        <span>{total.toLocaleString()} articles</span>
      </div>
      {loadError && <div className="error-banner" role="alert">{loadError}</div>}
      {actionError && <div className="error-banner" role="alert">{actionError}</div>}
      {notice && <div className="inline-notice library-notice" role="status">{notice}</div>}
      {selectedIds.size > 0 && (
        <div
          className="library-bulk-bar"
          role="region"
          aria-label="Bulk article actions"
        >
          <strong>{selectedIds.size.toLocaleString()} selected</strong>
          <label className="library-project-picker">
            <span>Project</span>
            <select
              value={projectId}
              disabled={!projects.length || adding}
              onChange={(event) => setProjectId(event.target.value)}
            >
              <option value="">
                {projects.length ? "Choose a project…" : "No projects yet"}
              </option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name} ({project.article_count})
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="button primary"
            disabled={!projectId || adding}
            onClick={() => void addSelectedToProject()}
          >
            {adding ? <LoaderCircle className="spin" /> : <BriefcaseBusiness />}
            {adding ? "Adding…" : "Add to project"}
          </button>
          <button
            type="button"
            className="button secondary"
            disabled={adding}
            onClick={() => setSelectedIds(new Set())}
          >
            Clear
          </button>
          {!projects.length && (
            <small>Create a project from the Projects screen first.</small>
          )}
        </div>
      )}
      <section className="panel article-table">
        <div className="article-table-head selectable">
          <label className="article-select">
            <input
              ref={(node) => {
                if (node) {
                  node.indeterminate =
                    loadedSelectedCount > 0 && !allLoadedSelected;
                }
              }}
              type="checkbox"
              checked={allLoadedSelected}
              disabled={!articles.length}
              aria-label="Select all loaded articles"
              onChange={(event) => setLoadedSelected(event.target.checked)}
            />
          </label>
          <span>Paper</span>
          <span>Year</span>
          <span>Type</span>
          <span>Processing</span>
          <span />
        </div>
        {articles.map((article) => (
          <ArticleRow
            key={article.id}
            article={article}
            selected={selectedIds.has(article.id)}
            onSelectedChange={(selected) => setArticleSelected(article.id, selected)}
            onOpen={() => onOpen(article)}
          />
        ))}
        {!articles.length && !loading && (
          <Empty icon={Library} title={query ? "No matching papers" : "No papers yet"}>
            {query ? "Try a broader library filter." : "Import a folder or Zotero collection to begin."}
          </Empty>
        )}
        {articles.length < total && (
          <button
            className="button secondary library-load-more"
            disabled={loading}
            onClick={() => void load(articles.length, true)}
          >
            {loading ? <LoaderCircle className="spin" /> : "Load 100 more"}
          </button>
        )}
      </section>
    </>
  );
}

function SearchView({
  onOpen,
}: {
  onOpen: (articleId: EntityId, hit: SearchHit) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [yearMin, setYearMin] = useState("");
  const [yearMax, setYearMax] = useState("");
  const [sourceType, setSourceType] = useState("");
  const [projectId, setProjectId] = useState("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [searchError, setSearchError] = useState("");
  useEffect(() => {
    void core.projects().then(setProjects).catch(() => setProjects([]));
  }, []);
  const examples = [
    "The study with about 200 patients where technical success was high but diagnostic yield was lower",
    "Paper I saved because the benign follow-up definition was unusual",
    "Prospective study that excluded patients without a bronchus sign",
  ];
  const runSearch = async (text = query) => {
    if (!text.trim()) return;
    setQuery(text);
    setSearching(true);
    try {
      setResults(await core.search({
        text,
        limit: 20,
        year_min: yearMin ? Number(yearMin) : undefined,
        year_max: yearMax ? Number(yearMax) : undefined,
        source_type: sourceType || undefined,
        project_id: projects.find((project) => String(project.id) === projectId)?.id,
      }));
      setSearched(true);
      setSearchError("");
    } catch (value) {
      setSearchError(value instanceof Error ? value.message : String(value));
    } finally {
      setSearching(false);
    }
  };
  return (
    <>
      <section className="search-hero">
        <span className="eyebrow">Approximate recall</span>
        <h1>Find the paper you half remember</h1>
        <p>Describe a number, method, relationship, author, or your own reason for saving it.</p>
        <form onSubmit={(event) => { event.preventDefault(); void runSearch(); }}>
          <Search />
          <textarea
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="The paper where navigation success was around 94% but strict diagnostic yield was closer to 70%…"
          />
          <button className="button primary" disabled={searching}>
            {searching ? <LoaderCircle className="spin" /> : "Search"}
          </button>
        </form>
        <div className="search-filters" aria-label="Search filters">
          <label>
            From year
            <input
              value={yearMin}
              inputMode="numeric"
              maxLength={4}
              onChange={(event) => setYearMin(event.target.value.replace(/\D/g, ""))}
              placeholder="Any"
            />
          </label>
          <label>
            To year
            <input
              value={yearMax}
              inputMode="numeric"
              maxLength={4}
              onChange={(event) => setYearMax(event.target.value.replace(/\D/g, ""))}
              placeholder="Any"
            />
          </label>
          <label>
            Article type
            <select value={sourceType} onChange={(event) => setSourceType(event.target.value)}>
              <option value="">All types</option>
              <option value="journal_article">Journal article</option>
              <option value="randomized_trial">Randomized trial</option>
              <option value="prospective_cohort">Prospective cohort</option>
              <option value="retrospective_study">Retrospective study</option>
              <option value="systematic_review">Systematic review</option>
              <option value="guideline">Guideline</option>
              <option value="review">Review</option>
              <option value="case_report">Case report</option>
            </select>
          </label>
          <label>
            Project
            <select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
              <option value="">All projects</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>{project.name}</option>
              ))}
            </select>
          </label>
        </div>
        {!searched && (
          <div className="query-examples">
            {examples.map((example) => (
              <button key={example} onClick={() => void runSearch(example)}>{example}</button>
            ))}
          </div>
        )}
      </section>
      {searchError && <div className="error-banner" role="alert">{searchError}</div>}
      {searched && (
        <section className="results">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Evidence-backed ranking</span>
              <h2>
                {results.length === 0
                  ? "No strong matches"
                  : `${results.length} strong ${results.length === 1 ? "match" : "matches"}`}
              </h2>
            </div>
            <small>Every excerpt is stored on its cited page.</small>
          </div>
          {results.map((result) => (
            <article className="result-card" key={`${result.article_id}-${result.passage_id}`}>
              <span className="result-rank">{result.rank}</span>
              <div className="result-body">
                <div className="result-meta"><span>{formatType(result.source_type)}</span>{result.publication_year && <span>{result.publication_year}</span>}{result.page_number && <span>Page {result.page_number}</span>}</div>
                <button className="result-title" onClick={() => onOpen(result.article_id, result)}>{result.title}</button>
                <p className="authors">{result.authors}{result.journal && ` · ${result.journal}`}</p>
                <blockquote>{result.snippet}</blockquote>
                <div className="reason-row">{result.match_reasons.map((reason) => <span key={reason.code}>{reason.label}</span>)}</div>
                {result.why_saved && <div className="saved-context"><b>Your context</b>{result.why_saved}</div>}
              </div>
              <button className="button secondary" onClick={() => onOpen(result.article_id, result)}>Open passage <ArrowRight size={15} /></button>
            </article>
          ))}
          {!results.length && (
            <Empty icon={Search} title="No strong match yet">
              Try the terminology likely used by the authors, remove a detail, or search a smaller fragment.
            </Empty>
          )}
        </section>
      )}
    </>
  );
}

function ImportsView({
  jobs,
  onRefresh,
  onFolder,
  onFiles,
  onError,
}: {
  jobs: ImportJob[];
  onRefresh: () => void;
  onFolder: () => void;
  onFiles: () => void;
  onError: (message: string) => void;
}) {
  return (
    <>
      <section className="view-heading">
        <div><span className="eyebrow">Durable background work</span><h1>Imports & jobs</h1><p>Every stage can resume after interruption without duplicate records or partial files.</p></div>
        <div className="heading-actions">
          <button className="button secondary" onClick={onFiles}><FileCheck2 size={17} /> Choose PDFs</button>
          <button className="button primary" onClick={onFolder}><FolderInput size={17} /> Choose folder</button>
        </div>
      </section>
      <section className="import-source-grid">
        <button onClick={onFolder}><FolderInput /><span><b>Folder import</b><small>Recursive managed-copy import with change watching.</small></span><ChevronRight /></button>
        <button onClick={() => void core.importZotero().then(onRefresh).catch((value) => onError(value instanceof Error ? value.message : String(value)))}><Library /><span><b>Zotero local API</b><small>Read-only, offline, and idempotent.</small></span><ChevronRight /></button>
      </section>
      <section className="panel">
        <div className="panel-heading"><div><span className="eyebrow">Queue</span><h2>Processing history</h2></div><button className="text-button" onClick={onRefresh}><RotateCcw size={14} /> Refresh</button></div>
        <div className="job-list">
          {jobs.map((job) => <JobRow key={job.id} job={job} onRefresh={onRefresh} />)}
          {!jobs.length && <Empty icon={Clock3} title="No jobs yet">Imports, OCR, model installation, and reindexing will appear here.</Empty>}
        </div>
      </section>
    </>
  );
}

function ProjectsView({
  onOpen,
}: {
  onOpen: (article: ArticleSummary) => void;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState<Project | null>(null);
  const [projectArticles, setProjectArticles] = useState<ArticleSummary[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const loadProjects = useCallback(async () => {
    try {
      const next = await core.projects();
      setProjects(next);
      setSelected((current) =>
        current ? next.find((project) => project.id === current.id) ?? null : next[0] ?? null,
      );
      setError("");
    } catch (value) {
      setError(value instanceof Error ? value.message : String(value));
    }
  }, []);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    if (!selected) {
      setProjectArticles([]);
      return;
    }
    void core.projectArticles(selected.id).then(setProjectArticles).catch((value) => {
      setError(value instanceof Error ? value.message : String(value));
    });
  }, [selected]);

  const create = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const project = await core.createProject(name.trim(), description.trim());
      setName("");
      setDescription("");
      setShowCreate(false);
      await loadProjects();
      setSelected(project);
    } catch (value) {
      setError(value instanceof Error ? value.message : String(value));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <section className="view-heading">
        <div>
          <span className="eyebrow">Focused collections</span>
          <h1>Projects</h1>
          <p>Organize papers for manuscripts, reviews, teaching, grants, and journal club.</p>
        </div>
        <button className="button primary" onClick={() => setShowCreate((value) => !value)}>
          <Plus size={17} /> New project
        </button>
      </section>
      {error && <div className="error-banner" role="alert">{error}</div>}
      {showCreate && (
        <form
          className="panel project-create"
          onSubmit={(event) => {
            event.preventDefault();
            void create();
          }}
        >
          <label>
            Project name
            <input
              autoFocus
              value={name}
              maxLength={500}
              onChange={(event) => setName(event.target.value)}
              placeholder="Diagnostic bronchoscopy review"
            />
          </label>
          <label>
            Description
            <input
              value={description}
              maxLength={50_000}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Optional context"
            />
          </label>
          <button className="button primary" disabled={!name.trim() || busy}>
            {busy ? "Creating…" : "Create"}
          </button>
        </form>
      )}
      {!projects.length && !showCreate ? (
        <Empty icon={BriefcaseBusiness} title="No projects yet">
          Create a collection, then add papers from their context panel.
        </Empty>
      ) : (
        <div className="project-workspace">
          <aside className="panel project-list" aria-label="Projects">
            {projects.map((project) => (
              <button
                key={project.id}
                className={selected?.id === project.id ? "active" : ""}
                onClick={() => setSelected(project)}
              >
                <span><b>{project.name}</b><small>{project.description || "Collection"}</small></span>
                <span>{project.article_count}</span>
              </button>
            ))}
          </aside>
          <section className="panel article-table">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">Collection</span>
                <h2>{selected?.name ?? "Select a project"}</h2>
              </div>
              <small>{projectArticles.length} papers</small>
            </div>
            {projectArticles.map((article) => (
              <ArticleRow key={article.id} article={article} onOpen={() => onOpen(article)} />
            ))}
            {selected && !projectArticles.length && (
              <Empty icon={BookOpen} title="This project is empty">
                Open a paper and add it from the reader context panel.
              </Empty>
            )}
          </section>
        </div>
      )}
    </>
  );
}

function SettingsView({
  status,
  onRefresh,
}: {
  status: CoreStatus;
  onRefresh: () => Promise<void>;
}) {
  const [passphrase, setPassphrase] = useState("");
  const [notice, setNotice] = useState("");
  const [updating, setUpdating] = useState(false);
  const [updateVersion, setUpdateVersion] = useState<string | null>(null);
  const [trash, setTrash] = useState<TrashArticle[]>([]);
  const showActionError = useCallback((value: unknown) => {
    setNotice(`Could not complete the action: ${value instanceof Error ? value.message : String(value)}`);
  }, []);
  const updatePrivacy = async (
    networkMetadata: boolean,
    diagnostics: boolean,
  ) => {
    setUpdating(true);
    try {
      await core.updatePrivacy(networkMetadata, diagnostics);
      await onRefresh();
      setNotice("Privacy settings updated.");
    } catch (value) {
      showActionError(value);
    } finally {
      setUpdating(false);
    }
  };
  const runBackup = async (operation: "create" | "restore") => {
    setUpdating(true);
    setNotice("");
    try {
      if (operation === "create") {
        const name = await core.chooseBackupDestination(passphrase);
        if (name) setNotice(`Created ${name}`);
      } else {
        const result = await core.chooseBackupRestore(passphrase);
        if (result) setNotice(`Restored ${result.documents ?? 0} articles.`);
      }
    } catch (value) {
      showActionError(value);
    } finally {
      setPassphrase("");
      setUpdating(false);
    }
  };
  const refreshTrash = useCallback(async () => {
    try {
      setTrash(await core.trash());
    } catch (value) {
      showActionError(value);
    }
  }, [showActionError]);
  useEffect(() => {
    void refreshTrash();
  }, [refreshTrash]);
  return (
    <>
      <section className="view-heading">
        <div><span className="eyebrow">Local control</span><h1>Settings</h1><p>Network access and diagnostics remain off unless you explicitly enable them.</p></div>
      </section>
      {notice && <div className="inline-notice">{notice}</div>}
      <section className="settings-grid">
        <div className="panel setting-card">
          <div className="setting-title"><Sparkles /><div><h2>Recall Search model</h2><p>{status.embedding_backend}</p></div></div>
          {status.embedding_warning && <div className="warning-box">{status.embedding_warning}</div>}
          <button
            className="button secondary"
            disabled={status.embedding_backend.startsWith("fastembed:")}
            onClick={() => void core.installModel().then(() => setNotice("Pinned model install queued.")).catch(showActionError)}
          >
            {status.embedding_backend.startsWith("fastembed:")
              ? "Pinned model verified"
              : "Install pinned local model"}
          </button>
        </div>
        <div className="panel setting-card">
          <div className="setting-title"><ArchiveRestore /><div><h2>Encrypted backups</h2><p>Portable database, immutable PDFs, annotations, and collections.</p></div></div>
          <label>Backup passphrase<input type="password" autoComplete="new-password" value={passphrase} onChange={(event) => setPassphrase(event.target.value)} placeholder="At least 12 characters" /></label>
          <div className="button-row">
            <button className="button primary" disabled={passphrase.length < 12 || updating} onClick={() => void runBackup("create")}>Create backup</button>
            <button className="button secondary" disabled={passphrase.length < 12 || updating} onClick={() => void runBackup("restore")}>Restore…</button>
          </div>
        </div>
        <div className="panel setting-card">
          <div className="setting-title"><LockKeyhole /><div><h2>Privacy</h2><p>Content never leaves this Mac in the core beta.</p></div></div>
          <label className="setting-toggle">
            <span><b>Online identifier metadata</b><small>Crossref/PubMed identifiers only; never PDF text</small></span>
            <input
              type="checkbox"
              checked={status.network_metadata_enabled}
              disabled={updating}
              onChange={(event) => void updatePrivacy(
                event.target.checked,
                status.diagnostics_enabled,
              )}
            />
          </label>
          <label className="setting-toggle">
            <span><b>Anonymous diagnostics</b><small>Excludes content, paths, filenames, notes, and queries</small></span>
            <input
              type="checkbox"
              checked={status.diagnostics_enabled}
              disabled={updating}
              onChange={(event) => void updatePrivacy(
                status.network_metadata_enabled,
                event.target.checked,
              )}
            />
          </label>
          <button
            className="button secondary"
            onClick={() => void core.createSupportBundle().then((name) => {
              if (name) setNotice(`Created ${name}`);
            }).catch(showActionError)}
          >
            <FileCheck2 size={16} /> Create redacted support bundle
          </button>
        </div>
        <div className="panel setting-card">
          <div className="setting-title"><HardDrive /><div><h2>Runtime</h2><p>Core {status.version} · schema {status.schema_version}</p></div></div>
          <dl><div><dt>OCR</dt><dd>{status.ocr_available ? "Tesseract available" : "Unavailable"}</dd></div><div><dt>Storage</dt><dd>Content-addressed managed copies</dd></div><div><dt>Trash</dt><dd>30-day recovery</dd></div></dl>
          {updateVersion ? (
            <button className="button primary" disabled={updating} onClick={() => { setUpdating(true); void core.installUpdate().catch(showActionError).finally(() => setUpdating(false)); }}>
              {updating ? "Installing…" : `Install ${updateVersion}`}
            </button>
          ) : (
            <button className="button secondary" disabled={updating} onClick={() => {
              setUpdating(true);
              void core.checkForUpdates()
                .then((result) => {
                  setUpdateVersion(result.version);
                  setNotice(result.available && result.version
                    ? `Version ${result.version} is available.`
                    : "Research Memory is up to date.");
                })
                .catch(showActionError)
                .finally(() => setUpdating(false));
            }}>{updating ? "Checking…" : "Check for updates"}</button>
          )}
        </div>
        <div className="panel setting-card trash-card">
          <div className="setting-title"><Trash2 /><div><h2>Trash</h2><p>Recover papers for 30 days. Source files are never deleted.</p></div></div>
          <div className="trash-list">
            {trash.map((article) => (
              <div className="trash-row" key={article.id}>
                <span>
                  <b>{article.title}</b>
                  <small>Purges {new Date(article.purge_after).toLocaleDateString()}</small>
                </span>
                <button
                  className="button secondary"
                  disabled={updating}
                  onClick={() => {
                    setUpdating(true);
                    void core.restoreArticle(article.id)
                      .then(async () => {
                        await Promise.all([refreshTrash(), onRefresh()]);
                        setNotice(`Restored “${article.title}”.`);
                      })
                      .catch(showActionError)
                      .finally(() => setUpdating(false));
                  }}
                >
                  Restore
                </button>
              </div>
            ))}
            {!trash.length && <p className="muted">Trash is empty.</p>}
          </div>
        </div>
      </section>
    </>
  );
}

export function App() {
  const [view, setView] = useState<View>("home");
  const [status, setStatus] = useState<CoreStatus | null>(null);
  const [articles, setArticles] = useState<ArticleSummary[]>([]);
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [reader, setReader] = useState<{ article: ArticleDetail; hit?: SearchHit } | null>(null);
  const [error, setError] = useState("");
  const [onboarded, setOnboarded] = useState(
    () => localStorage.getItem("research-memory:onboarded") === "true",
  );

  const refresh = useCallback(async () => {
    try {
      const [nextStatus, nextArticles, nextJobs] = await Promise.all([
        core.status(),
        core.articles("", 20, 0),
        core.jobs(),
      ]);
      setStatus(nextStatus);
      setArticles(nextArticles.items);
      setJobs(nextJobs);
      setError("");
    } catch (value) {
      setError(value instanceof Error ? value.message : String(value));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (status) return;
    const timer = window.setInterval(() => void refresh(), 750);
    return () => window.clearInterval(timer);
  }, [refresh, status]);

  useEffect(() => {
    if (!jobs.some((job) => job.status === "running" || job.status === "queued")) return;
    const timer = window.setInterval(() => void refresh(), 2_000);
    return () => window.clearInterval(timer);
  }, [jobs, refresh]);

  useEffect(() => {
    const onShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k" && !reader) {
        event.preventDefault();
        setView("search");
      }
    };
    window.addEventListener("keydown", onShortcut);
    return () => window.removeEventListener("keydown", onShortcut);
  }, [reader]);

  const openArticle = async (article: ArticleSummary | EntityId, hit?: SearchHit) => {
    const id = typeof article === "object" ? article.id : article;
    try {
      setReader({ article: await core.article(id), hit });
    } catch (value) {
      setError(value instanceof Error ? value.message : String(value));
    }
  };
  const importFolder = () => {
    void core.chooseImportFolder().then((job) => {
      if (job) {
        setView("imports");
        void refresh();
      }
    }).catch((value) => setError(value instanceof Error ? value.message : String(value)));
  };
  const importFiles = () => {
    void core.chooseImportFiles().then((created) => {
      if (created.length) {
        setView("imports");
        void refresh();
      }
    }).catch((value) => setError(value instanceof Error ? value.message : String(value)));
  };

  const content = useMemo(() => {
    if (!status) return null;
    if (view === "home") return <HomeView status={status} articles={articles} jobs={jobs} onNavigate={setView} onOpen={(article) => void openArticle(article)} onImport={importFolder} />;
    if (view === "library") return <LibraryView onOpen={(article) => void openArticle(article)} onImport={importFolder} />;
    if (view === "search") return <SearchView onOpen={(id, hit) => void openArticle(id, hit)} />;
    if (view === "projects") return <ProjectsView onOpen={(article) => void openArticle(article)} />;
    if (view === "imports") return <ImportsView jobs={jobs} onRefresh={() => void refresh()} onFolder={importFolder} onFiles={importFiles} onError={setError} />;
    return <SettingsView status={status} onRefresh={refresh} />;
  }, [articles, jobs, refresh, status, view]);

  if (!status) {
    return <div className="boot"><span className="brand-glyph">RM</span><LoaderCircle className="spin" /><p>{error || "Starting the private research core…"}</p></div>;
  }
  if (!onboarded) {
    return <Onboarding status={status} onComplete={() => { localStorage.setItem("research-memory:onboarded", "true"); setOnboarded(true); void refresh(); }} />;
  }
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="traffic-space" data-tauri-drag-region />
        <button className="brand" onClick={() => setView("home")}><span className="brand-glyph">RM</span><span><b>Research Memory</b><small>Private literature recall</small></span></button>
        <nav aria-label="Primary">
          {navigation.map((item) => {
            const Icon = item.icon;
            return <button key={item.id} className={view === item.id ? "active" : ""} onClick={() => setView(item.id)}><Icon /><span>{item.label}</span>{item.id === "imports" && status.jobs_running > 0 && <b className="nav-count">{status.jobs_running}</b>}</button>;
          })}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-status"><span /><div><b>On this Mac</b><small>{status.embedding_backend.startsWith("fastembed") ? "Semantic model ready" : "Lexical fallback"}</small></div></div>
          <p><LockKeyhole size={13} /> No paper text leaves this device</p>
        </div>
      </aside>
      <div className="app-main">
        <header className="topbar" data-tauri-drag-region>
          <button className="global-search" onClick={() => setView("search")}><Search /><span>Recall a paper…</span><kbd>⌘ K</kbd></button>
          <div className="topbar-drag-space" data-tauri-drag-region aria-hidden="true" />
          <button className="button primary" onClick={importFolder}><Plus size={17} /> Add papers</button>
        </header>
        <main className="content">
          {error && <div className="error-banner"><CircleAlert />{error}<button className="icon-button" onClick={() => setError("")} aria-label="Dismiss error"><XCircle /></button></div>}
          {content}
        </main>
      </div>
      {reader && (
        <ReaderErrorBoundary
          key={reader.article.id}
          onClose={() => setReader(null)}
        >
          <Suspense fallback={<div className="reader-overlay"><div className="boot"><LoaderCircle className="spin" /><p>Opening reader…</p></div></div>}>
            <PdfReader
              article={reader.article}
              initialHit={reader.hit}
              onClose={() => setReader(null)}
              onArticleChanged={(article) => setReader((current) => current ? { ...current, article } : null)}
              onTrashed={() => {
                setReader(null);
                void refresh();
              }}
            />
          </Suspense>
        </ReaderErrorBoundary>
      )}
    </div>
  );
}
