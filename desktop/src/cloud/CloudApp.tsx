import {
  ArchiveRestore,
  ArrowRight,
  BookOpen,
  BriefcaseBusiness,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  Cloud,
  Database,
  Download,
  FileSearch,
  FileText,
  FileUp,
  FolderInput,
  HardDrive,
  Home,
  Inbox,
  KeyRound,
  Library,
  ListRestart,
  LoaderCircle,
  LogOut,
  Mail,
  Plus,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  Smartphone,
  Trash2,
  UserPlus,
  X,
  XCircle,
} from "lucide-react";
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import type {
  ArticleDetail,
  ArticleSummary,
  EntityId,
  ImportJob,
  Project,
  TrashArticle,
  View,
} from "../types";
import {
  createCloudLibraryService,
  type CloudBackupSettings,
  type CloudConnectorStatus,
  type CloudDashboard,
  type CloudDriveConnection,
  type CloudDriveProvider,
  type CloudLibrary,
  type CloudLibraryService,
  type CloudSearchQuery,
  type CloudSearchResult,
  type CloudUser,
  type UploadProgress,
} from "./service";

const PdfReader = lazy(() =>
  import("../components/PdfReader").then((module) => ({
    default: module.PdfReader,
  })),
);

const macDownloadUrl =
  import.meta.env.VITE_MAC_DOWNLOAD_URL?.trim() ||
  "https://github.com/russellmiller49/research_brain/releases";
const socialAuthEnabled =
  import.meta.env.VITE_SOCIAL_AUTH_ENABLED?.trim().toLowerCase() === "true";

interface CloudAppProps {
  service?: CloudLibraryService;
}

const navigation: Array<{
  id: View;
  label: string;
  shortLabel: string;
  icon: typeof Home;
}> = [
  { id: "home", label: "Home", shortLabel: "Home", icon: Home },
  { id: "library", label: "Library", shortLabel: "Library", icon: Library },
  {
    id: "search",
    label: "Recall search",
    shortLabel: "Search",
    icon: FileSearch,
  },
  {
    id: "projects",
    label: "Projects",
    shortLabel: "Projects",
    icon: BriefcaseBusiness,
  },
  {
    id: "imports",
    label: "Imports & jobs",
    shortLabel: "Imports",
    icon: ListRestart,
  },
  {
    id: "settings",
    label: "Settings",
    shortLabel: "Settings",
    icon: Settings,
  },
];

const emptyDashboard: CloudDashboard = {
  articleCount: 0,
  unreadCount: 0,
  readingCount: 0,
  annotationCount: 0,
  projectCount: 0,
  activeJobCount: 0,
  reviewCount: 0,
  recentArticles: [],
};

function readableError(value: unknown): string {
  return value instanceof Error ? value.message : String(value);
}

function CloudAuthIntro() {
  return (
    <section className="cloud-auth-intro">
      <div className="cloud-brand">
        <span className="brand-glyph"><BookOpen /></span>
        <span>
          <b>Research Memory</b>
          <small>One library, every device</small>
        </span>
      </div>
      <div>
        <span className="eyebrow">Synced research workspace</span>
        <h1>Your papers should travel with you.</h1>
        <p>
          Sign in on the web, desktop, or mobile. Your managed PDFs,
          bibliographic details, highlights, projects, and notes stay
          attached to your account.
        </p>
        <div className="cloud-auth-download">
          <a
            className="button secondary"
            href={macDownloadUrl}
            target="_blank"
            rel="noreferrer"
          >
            <Download /> Download for Mac
          </a>
          <small>Apple silicon · macOS 13 or newer</small>
        </div>
      </div>
      <div className="cloud-auth-benefits">
        <span><Cloud /><b>Private cloud library</b></span>
        <span><Smartphone /><b>Responsive reader</b></span>
        <span><ShieldCheck /><b>Account-isolated data</b></span>
      </div>
    </section>
  );
}

type AuthMode = "sign-in" | "sign-up" | "forgot-password";

function formatLabel(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function providerLabel(provider: CloudDriveProvider): string {
  return provider === "google_drive" ? "Google Drive" : "OneDrive";
}

function connectorAvailabilityLabel(
  status: CloudConnectorStatus | null,
  provider: CloudDriveProvider,
  readyLabel: string,
): string {
  if (!status) return "Checking connector…";
  if (!status.serviceAvailable) return "Connector service is stopped";
  if (!status.providers[provider]) return "OAuth setup required";
  return readyLabel;
}

function relativeDate(value: string): string {
  const milliseconds = Date.now() - new Date(value).getTime();
  const minutes = Math.max(1, Math.round(milliseconds / 60_000));
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

function AuthScreen({
  service,
  initialError = "",
}: {
  service: CloudLibraryService;
  initialError?: string;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirmation, setPasswordConfirmation] = useState("");
  const [mode, setMode] = useState<AuthMode>("sign-in");
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState("");
  const [error, setError] = useState(initialError);

  const switchMode = (nextMode: AuthMode) => {
    setMode(nextMode);
    setPassword("");
    setPasswordConfirmation("");
    setSuccess("");
    setError("");
  };

  const submitCredentials = async (event: FormEvent) => {
    event.preventDefault();
    const normalizedEmail = email.trim();
    if (!normalizedEmail) return;
    if (mode !== "forgot-password" && password.length < 8) {
      setError("Use at least 8 characters for your password.");
      return;
    }
    if (mode === "sign-up" && password !== passwordConfirmation) {
      setError("The passwords do not match.");
      return;
    }

    setBusy(true);
    setError("");
    setSuccess("");
    try {
      if (mode === "sign-in") {
        await service.signInWithPassword(normalizedEmail, password);
        setSuccess("Signed in. Opening your library…");
      } else if (mode === "sign-up") {
        const result = await service.signUpWithPassword(
          normalizedEmail,
          password,
        );
        setSuccess(
          result.requiresEmailConfirmation
            ? "Check your email to confirm the account, then sign in with your password."
            : "Account created. Opening your library…",
        );
      } else {
        await service.requestPasswordReset(normalizedEmail);
        setSuccess(
          "Check your email for a password-reset link. It will return you here to choose a new password.",
        );
      }
    } catch (value) {
      setError(readableError(value));
    } finally {
      setBusy(false);
    }
  };

  const signInWith = async (provider: "google" | "apple" | "azure") => {
    setBusy(true);
    setError("");
    try {
      await service.signInWithProvider(provider);
    } catch (value) {
      setError(readableError(value));
      setBusy(false);
    }
  };

  const heading =
    mode === "sign-in"
      ? "Sign in to your library"
      : mode === "sign-up"
        ? "Create your account"
        : "Reset your password";
  const description =
    mode === "sign-in"
      ? "Your email address is your username on every device."
      : mode === "sign-up"
        ? "Create one private account for your web, mobile, and desktop library."
        : "Enter your account email and we’ll send a secure reset link.";

  return (
    <main className="cloud-auth">
      <CloudAuthIntro />

      <section className="cloud-auth-card" aria-labelledby="cloud-sign-in">
        <span className="eyebrow">Welcome</span>
        <h2 id="cloud-sign-in">{heading}</h2>
        <p className="muted">{description}</p>
        <form onSubmit={(event) => void submitCredentials(event)}>
          <label>
            Email address
            <input
              autoComplete="email"
              inputMode="email"
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
            />
          </label>
          {mode !== "forgot-password" && (
            <label>
              Password
              <input
                autoComplete={
                  mode === "sign-up" ? "new-password" : "current-password"
                }
                type="password"
                required
                minLength={8}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="At least 8 characters"
              />
            </label>
          )}
          {mode === "sign-up" && (
            <label>
              Confirm password
              <input
                autoComplete="new-password"
                type="password"
                required
                minLength={8}
                value={passwordConfirmation}
                onChange={(event) =>
                  setPasswordConfirmation(event.target.value)}
                placeholder="Enter it again"
              />
            </label>
          )}
          <button className="button primary" disabled={busy}>
            {busy
              ? <LoaderCircle className="spin" />
              : mode === "sign-up"
                ? <UserPlus />
                : mode === "forgot-password"
                  ? <Mail />
                  : <KeyRound />}
            {mode === "sign-in"
              ? "Sign in"
              : mode === "sign-up"
                ? "Create account"
                : "Send password reset"}
          </button>
        </form>
        {success && (
          <div className="cloud-auth-success" role="status">
            <Check />
            <span>
              <b>{mode === "sign-in" ? "Welcome back" : "Request received"}</b>
              <small>{success}</small>
            </span>
          </div>
        )}
        <div className="cloud-auth-actions">
          {mode === "sign-in" && (
            <>
              <button
                type="button"
                onClick={() => switchMode("forgot-password")}
              >
                Forgot password?
              </button>
              <span />
              <button type="button" onClick={() => switchMode("sign-up")}>
                Create an account
              </button>
            </>
          )}
          {mode !== "sign-in" && (
            <button type="button" onClick={() => switchMode("sign-in")}>
              Back to sign in
            </button>
          )}
        </div>
        {socialAuthEnabled && mode === "sign-in" && (
          <>
            <div className="cloud-auth-divider">
              <span>or continue with</span>
            </div>
            <div className="cloud-provider-grid">
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => void signInWith("google")}
              >
                Google
              </button>
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => void signInWith("apple")}
              >
                Apple
              </button>
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => void signInWith("azure")}
              >
                Microsoft
              </button>
            </div>
          </>
        )}
        {error && <div className="error-banner" role="alert">{error}</div>}
        <small className="cloud-auth-footnote">
          PDFs are private by default and served through short-lived signed
          links. Your account can access only its own database rows and storage
          folder.
        </small>
      </section>
    </main>
  );
}

function PasswordResetScreen({
  service,
  onComplete,
}: {
  service: CloudLibraryService;
  onComplete: () => void;
}) {
  const [password, setPassword] = useState("");
  const [passwordConfirmation, setPasswordConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [updated, setUpdated] = useState(false);
  const [error, setError] = useState("");

  const updatePassword = async (event: FormEvent) => {
    event.preventDefault();
    if (password.length < 8) {
      setError("Use at least 8 characters for your password.");
      return;
    }
    if (password !== passwordConfirmation) {
      setError("The passwords do not match.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await service.updatePassword(password);
      setUpdated(true);
      setPassword("");
      setPasswordConfirmation("");
    } catch (value) {
      setError(readableError(value));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="cloud-auth">
      <CloudAuthIntro />
      <section className="cloud-auth-card" aria-labelledby="reset-password">
        <span className="eyebrow">Account recovery</span>
        <h2 id="reset-password">Choose a new password</h2>
        <p className="muted">
          Set a password for this account, then use it on every device.
        </p>
        {updated ? (
          <>
            <div className="cloud-auth-success" role="status">
              <Check />
              <span>
                <b>Password updated</b>
                <small>Your new password is ready to use.</small>
              </span>
            </div>
            <button
              className="button primary cloud-auth-continue"
              onClick={onComplete}
            >
              Continue to your library <ArrowRight />
            </button>
          </>
        ) : (
          <form onSubmit={(event) => void updatePassword(event)}>
            <label>
              New password
              <input
                autoComplete="new-password"
                type="password"
                required
                minLength={8}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="At least 8 characters"
              />
            </label>
            <label>
              Confirm new password
              <input
                autoComplete="new-password"
                type="password"
                required
                minLength={8}
                value={passwordConfirmation}
                onChange={(event) =>
                  setPasswordConfirmation(event.target.value)}
                placeholder="Enter it again"
              />
            </label>
            <button className="button primary" disabled={busy}>
              {busy ? <LoaderCircle className="spin" /> : <KeyRound />}
              Update password
            </button>
          </form>
        )}
        {error && <div className="error-banner" role="alert">{error}</div>}
        <small className="cloud-auth-footnote">
          Research Memory never receives or stores your password. Supabase Auth
          verifies it securely.
        </small>
      </section>
    </main>
  );
}

function ConfigurationScreen({ message }: { message: string }) {
  return (
    <main className="cloud-configuration">
      <section className="cloud-auth-card">
        <span className="brand-glyph"><Database /></span>
        <span className="eyebrow">Cloud configuration needed</span>
        <h1>Connect the web app to Supabase</h1>
        <p>{message}</p>
        <p className="muted">
          Copy <code>.env.cloud.example</code> to{" "}
          <code>.env.cloud.local</code>, add the local or hosted publishable
          values, then run <code>npm run dev:web</code>.
        </p>
      </section>
    </main>
  );
}

function EmptyState({
  icon: Icon,
  title,
  children,
}: {
  icon: typeof Inbox;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="cloud-empty">
      <span className="brand-glyph"><Icon /></span>
      <h2>{title}</h2>
      <p>{children}</p>
    </div>
  );
}

function ArticleCard({
  article,
  onOpen,
  action,
}: {
  article: ArticleSummary;
  onOpen: () => void;
  action?: ReactNode;
}) {
  return (
    <article className="cloud-article-card">
      <button className="cloud-article-open" onClick={onOpen}>
        <span className="cloud-file-icon"><FileText /></span>
        <span>
          <b>{article.title}</b>
          <small>
            {article.authors || "Unknown author"}
            {article.journal ? ` · ${article.journal}` : ""}
          </small>
        </span>
      </button>
      <div className="cloud-article-meta">
        <span>{article.publication_year ?? "Year —"}</span>
        <span className="cloud-reading-chip">
          {formatLabel(article.reading_status)}
        </span>
        <span className={`cloud-sync-chip ${article.extraction_status}`}>
          <Cloud />
          {article.extraction_status === "queued"
            ? "Synced"
            : formatLabel(article.extraction_status)}
        </span>
        {action}
      </div>
    </article>
  );
}

function ViewHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <section className="cloud-view-heading">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </section>
  );
}

function HomeView({
  library,
  dashboard,
  onNavigate,
  onOpen,
  onImport,
}: {
  library: CloudLibrary;
  dashboard: CloudDashboard;
  onNavigate: (view: View) => void;
  onOpen: (id: EntityId) => void;
  onImport: () => void;
}) {
  return (
    <>
      <section className="cloud-home-hero">
        <div>
          <span className="eyebrow">Your synced research workspace</span>
          <h1>{library.name}</h1>
          <p>
            Pick up a paper, find a half-remembered detail, or organize the
            evidence for your next project.
          </p>
        </div>
        <button className="button primary" onClick={onImport}>
          <FileUp /> Add papers
        </button>
      </section>

      <button
        className="cloud-recall-prompt"
        onClick={() => onNavigate("search")}
      >
        <Search />
        <span>
          <b>What do you remember?</b>
          <small>
            Search a title, author, abstract phrase, summary, or your reason
            for saving it.
          </small>
        </span>
        <ArrowRight />
      </button>

      <section className="cloud-metric-grid" aria-label="Library overview">
        <button onClick={() => onNavigate("library")}>
          <Library />
          <span>
            <b>{dashboard.articleCount.toLocaleString()}</b>
            <small>Papers</small>
          </span>
        </button>
        <button onClick={() => onNavigate("library")}>
          <BookOpen />
          <span>
            <b>{dashboard.readingCount}</b>
            <small>Reading now</small>
          </span>
        </button>
        <button onClick={() => onNavigate("projects")}>
          <BriefcaseBusiness />
          <span>
            <b>{dashboard.projectCount}</b>
            <small>Projects</small>
          </span>
        </button>
        <button onClick={() => onNavigate("imports")}>
          <ListRestart />
          <span>
            <b>{dashboard.activeJobCount}</b>
            <small>Processing</small>
          </span>
        </button>
        <button onClick={() => onNavigate("library")}>
          <FileText />
          <span>
            <b>{dashboard.annotationCount}</b>
            <small>Annotations</small>
          </span>
        </button>
        <button onClick={() => onNavigate("imports")}>
          <CircleAlert />
          <span>
            <b>{dashboard.reviewCount}</b>
            <small>Need review</small>
          </span>
        </button>
      </section>

      <section className="cloud-library-panel">
        <div className="cloud-list-heading">
          <div>
            <span className="eyebrow">Recently updated</span>
            <h2>Continue where you left off</h2>
          </div>
          <button
            className="text-button"
            onClick={() => onNavigate("library")}
          >
            View library <ArrowRight />
          </button>
        </div>
        <div className="cloud-article-list">
          {dashboard.recentArticles.map((article) => (
            <ArticleCard
              key={article.id}
              article={article}
              onOpen={() => onOpen(article.id)}
            />
          ))}
        </div>
        {!dashboard.recentArticles.length && (
          <EmptyState icon={Inbox} title="Your library is ready">
            Import a PDF from this device or a cloud-drive file picker to
            make it available everywhere you sign in.
          </EmptyState>
        )}
      </section>
    </>
  );
}

function LibraryView({
  library,
  articles,
  loading,
  onOpen,
  onImport,
  onRefresh,
}: {
  library: CloudLibrary;
  articles: ArticleSummary[];
  loading: boolean;
  onOpen: (id: EntityId) => void;
  onImport: () => void;
  onRefresh: () => void;
}) {
  const [query, setQuery] = useState("");
  const [readingStatus, setReadingStatus] = useState("");
  const needle = query.trim().toLocaleLowerCase();
  const filtered = useMemo(
    () =>
      articles.filter((article) => {
        if (readingStatus && article.reading_status !== readingStatus) {
          return false;
        }
        if (!needle) return true;
        return [
          article.title,
          article.authors,
          article.journal,
          String(article.publication_year ?? ""),
        ].some((value) => value.toLocaleLowerCase().includes(needle));
      }),
    [articles, needle, readingStatus],
  );

  return (
    <>
      <ViewHeading
        eyebrow="Available on every signed-in device"
        title={library.name}
        description="Browse your managed PDFs and reading state. Notes, highlights, metadata, and project membership sync separately from the immutable original."
        action={
          <button className="button primary" onClick={onImport}>
            <FileUp /> Import PDFs
          </button>
        }
      />

      <section className="cloud-source-strip" aria-label="PDF sources">
        <div>
          <span className="cloud-source-icon active"><HardDrive /></span>
          <span><b>This device</b><small>Upload now</small></span>
        </div>
        <div>
          <span className="cloud-source-icon active"><Cloud /></span>
          <span><b>iCloud Drive</b><small>Use the Files picker</small></span>
        </div>
        <div>
          <span className="cloud-source-icon"><Cloud /></span>
          <span><b>Google Drive</b><small>Connect in Imports</small></span>
        </div>
        <div>
          <span className="cloud-source-icon"><Cloud /></span>
          <span><b>OneDrive</b><small>Connect in Imports</small></span>
        </div>
      </section>

      <section className="cloud-toolbar">
        <label className="cloud-search">
          <Search />
          <span className="sr-only">Filter library</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter title, author, journal, or year"
          />
        </label>
        <label className="cloud-filter">
          <span className="sr-only">Reading status</span>
          <select
            value={readingStatus}
            onChange={(event) => setReadingStatus(event.target.value)}
          >
            <option value="">All reading states</option>
            <option value="unread">Unread</option>
            <option value="reading">Reading</option>
            <option value="reference">Reference</option>
            <option value="finished">Finished</option>
          </select>
        </label>
        <button
          className="icon-button"
          aria-label="Refresh library"
          disabled={loading}
          onClick={onRefresh}
        >
          <RefreshCw className={loading ? "spin" : ""} />
        </button>
      </section>

      <section className="cloud-library-panel" aria-busy={loading}>
        <div className="cloud-list-heading">
          <div>
            <span className="eyebrow">Library</span>
            <h2>{needle || readingStatus ? "Filtered papers" : "All papers"}</h2>
          </div>
          <small>
            {filtered.length} of {articles.length}{" "}
            {articles.length === 1 ? "paper" : "papers"}
          </small>
        </div>
        <div className="cloud-article-list">
          {filtered.map((article) => (
            <ArticleCard
              key={article.id}
              article={article}
              onOpen={() => onOpen(article.id)}
            />
          ))}
        </div>
        {!filtered.length && !loading && (
          <EmptyState
            icon={FileText}
            title={needle || readingStatus ? "No matching papers" : "Bring in your first PDF"}
          >
            {needle || readingStatus
              ? "Clear a filter or try a broader title or author fragment."
              : "Import PDFs on any device. A managed copy will be available everywhere you sign in."}
          </EmptyState>
        )}
        {loading && (
          <div className="cloud-list-loading">
            <LoaderCircle className="spin" /> Refreshing your library…
          </div>
        )}
      </section>
    </>
  );
}

function SearchView({
  service,
  projects,
  onOpen,
}: {
  service: CloudLibraryService;
  projects: Project[];
  onOpen: (id: EntityId) => void;
}) {
  const [query, setQuery] = useState("");
  const [yearMin, setYearMin] = useState("");
  const [yearMax, setYearMax] = useState("");
  const [readingStatus, setReadingStatus] = useState("");
  const [projectId, setProjectId] = useState("");
  const [results, setResults] = useState<CloudSearchResult[]>([]);
  const [searched, setSearched] = useState(false);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const examples = [
    "bronchoscopy",
    "lung cancer staging",
    "the paper I saved for its unusual follow-up definition",
  ];

  const runSearch = async (nextText = query) => {
    const request: CloudSearchQuery = {
      text: nextText.trim(),
      yearMin: yearMin ? Number(yearMin) : undefined,
      yearMax: yearMax ? Number(yearMax) : undefined,
      readingStatus: readingStatus || undefined,
      projectId: projectId || undefined,
    };
    setQuery(nextText);
    setSearching(true);
    setError("");
    try {
      setResults(await service.searchArticles(request));
      setSearched(true);
    } catch (value) {
      setError(readableError(value));
    } finally {
      setSearching(false);
    }
  };

  return (
    <>
      <section className="cloud-search-hero">
        <span className="eyebrow">Personal recall search</span>
        <h1>Find the paper you half remember</h1>
        <p>
          Search titles, authors, journals, identifiers, abstracts, personal
          summaries, saved context, and indexed passages inside your PDFs.
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void runSearch();
          }}
        >
          <Search />
          <textarea
            autoFocus
            aria-label="Recall search query"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="The lung cancer paper with a section about staging techniques…"
          />
          <button
            className="button primary"
            aria-label="Run recall search"
            disabled={searching}
          >
            {searching ? <LoaderCircle className="spin" /> : <Search />}
            Search
          </button>
        </form>
        <div className="cloud-search-filters" aria-label="Search filters">
          <label>
            From year
            <input
              value={yearMin}
              inputMode="numeric"
              maxLength={4}
              onChange={(event) =>
                setYearMin(event.target.value.replace(/\D/g, ""))
              }
              placeholder="Any"
            />
          </label>
          <label>
            To year
            <input
              value={yearMax}
              inputMode="numeric"
              maxLength={4}
              onChange={(event) =>
                setYearMax(event.target.value.replace(/\D/g, ""))
              }
              placeholder="Any"
            />
          </label>
          <label>
            Reading state
            <select
              value={readingStatus}
              onChange={(event) => setReadingStatus(event.target.value)}
            >
              <option value="">All states</option>
              <option value="unread">Unread</option>
              <option value="reading">Reading</option>
              <option value="reference">Reference</option>
              <option value="finished">Finished</option>
            </select>
          </label>
          <label>
            Project
            <select
              value={projectId}
              onChange={(event) => setProjectId(event.target.value)}
            >
              <option value="">All projects</option>
              {projects.map((project) => (
                <option key={project.id} value={String(project.id)}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        {!searched && (
          <div className="cloud-query-examples">
            {examples.map((example) => (
              <button key={example} onClick={() => void runSearch(example)}>
                {example}
              </button>
            ))}
          </div>
        )}
        <small className="cloud-search-scope">
          Search ranks indexed PDF passages alongside saved metadata and
          personal context. Newly uploaded pages join results after extraction.
        </small>
      </section>

      {error && <div className="error-banner" role="alert">{error}</div>}
      {searched && (
        <section className="cloud-library-panel cloud-search-results">
          <div className="cloud-list-heading">
            <div>
              <span className="eyebrow">Results</span>
              <h2>
                {results.length
                  ? `${results.length} ${results.length === 1 ? "match" : "matches"}`
                  : "No matches yet"}
              </h2>
            </div>
            <small>Only your private library was searched.</small>
          </div>
          <div className="cloud-article-list">
            {results.map((article) => (
              <div className="cloud-search-hit" key={article.id}>
                <ArticleCard
                  article={article}
                  onOpen={() => onOpen(article.id)}
                />
                {article.matchSnippet && (
                  <p>
                    <span>
                      PDF passage
                      {article.matchPageNumber
                        ? ` · page ${article.matchPageNumber}`
                        : ""}
                    </span>
                    {article.matchSnippet}
                  </p>
                )}
              </div>
            ))}
          </div>
          {!results.length && (
            <EmptyState icon={Search} title="No matching paper">
              Try fewer words, an author or journal name, or remove a year or
              project filter.
            </EmptyState>
          )}
        </section>
      )}
    </>
  );
}

function ProjectsView({
  service,
  projects,
  allArticles,
  revision,
  onOpen,
  onRefresh,
  onNotice,
  onError,
}: {
  service: CloudLibraryService;
  projects: Project[];
  allArticles: ArticleSummary[];
  revision: number;
  onOpen: (id: EntityId) => void;
  onRefresh: () => Promise<void>;
  onNotice: (message: string) => void;
  onError: (message: string) => void;
}) {
  const [selectedId, setSelectedId] = useState("");
  const [projectArticles, setProjectArticles] = useState<ArticleSummary[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [articleToAdd, setArticleToAdd] = useState("");
  const [busy, setBusy] = useState(false);
  const selected =
    projects.find((project) => String(project.id) === selectedId) ?? null;

  useEffect(() => {
    if (!projects.length) {
      setSelectedId("");
      return;
    }
    if (!projects.some((project) => String(project.id) === selectedId)) {
      setSelectedId(String(projects[0]?.id ?? ""));
    }
  }, [projects, selectedId]);

  useEffect(() => {
    let active = true;
    if (!selectedId) {
      setProjectArticles([]);
      return () => {
        active = false;
      };
    }
    void service.projectArticles(selectedId).then((next) => {
      if (active) setProjectArticles(next);
    }).catch((value) => {
      if (active) onError(readableError(value));
    });
    return () => {
      active = false;
    };
  }, [onError, revision, selectedId, service]);

  const memberIds = new Set(projectArticles.map((article) => String(article.id)));
  const availableArticles = allArticles.filter(
    (article) => !memberIds.has(String(article.id)),
  );

  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      const project = await service.createProject(name, description);
      setName("");
      setDescription("");
      setShowCreate(false);
      setSelectedId(String(project.id));
      onNotice(`Created “${project.name}”.`);
      await onRefresh();
    } catch (value) {
      onError(readableError(value));
    } finally {
      setBusy(false);
    }
  };

  const addArticle = async () => {
    if (!selected || !articleToAdd) return;
    setBusy(true);
    try {
      await service.addProjectArticle(selected.id, articleToAdd);
      setArticleToAdd("");
      onNotice(`Added a paper to “${selected.name}”.`);
      await onRefresh();
    } catch (value) {
      onError(readableError(value));
    } finally {
      setBusy(false);
    }
  };

  const removeArticle = async (article: ArticleSummary) => {
    if (!selected) return;
    setBusy(true);
    try {
      await service.removeProjectArticle(selected.id, article.id);
      onNotice(`Removed “${article.title}” from this project.`);
      await onRefresh();
    } catch (value) {
      onError(readableError(value));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <ViewHeading
        eyebrow="Focused collections"
        title="Projects"
        description="Organize papers for manuscripts, reviews, teaching, grants, and journal club. Project membership syncs across devices."
        action={
          <button
            className="button primary"
            onClick={() => setShowCreate((current) => !current)}
          >
            {showCreate ? <X /> : <Plus />}
            {showCreate ? "Close" : "New project"}
          </button>
        }
      />

      {showCreate && (
        <form className="cloud-project-create" onSubmit={(event) => void create(event)}>
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
              placeholder="Optional context for this collection"
            />
          </label>
          <button className="button primary" disabled={busy || !name.trim()}>
            {busy ? <LoaderCircle className="spin" /> : <Plus />}
            Create project
          </button>
        </form>
      )}

      {!projects.length ? (
        <section className="cloud-library-panel">
          <EmptyState icon={BriefcaseBusiness} title="No projects yet">
            Create a focused collection, then add any paper from this page or
            from the reader.
          </EmptyState>
        </section>
      ) : (
        <div className="cloud-project-workspace">
          <aside className="cloud-project-list" aria-label="Projects">
            {projects.map((project) => (
              <button
                key={project.id}
                className={selectedId === String(project.id) ? "active" : ""}
                onClick={() => setSelectedId(String(project.id))}
              >
                <BriefcaseBusiness />
                <span>
                  <b>{project.name}</b>
                  <small>{project.description || "Research collection"}</small>
                </span>
                <i>{project.article_count}</i>
              </button>
            ))}
          </aside>

          <section className="cloud-library-panel">
            <div className="cloud-list-heading cloud-project-heading">
              <div>
                <span className="eyebrow">Collection</span>
                <h2>{selected?.name ?? "Select a project"}</h2>
              </div>
              <small>
                {projectArticles.length}{" "}
                {projectArticles.length === 1 ? "paper" : "papers"}
              </small>
            </div>
            {selected && (
              <div className="cloud-project-add">
                <label>
                  <span className="sr-only">Paper to add</span>
                  <select
                    value={articleToAdd}
                    disabled={!availableArticles.length || busy}
                    onChange={(event) => setArticleToAdd(event.target.value)}
                  >
                    <option value="">
                      {availableArticles.length
                        ? "Choose a paper to add…"
                        : "Every library paper is already here"}
                    </option>
                    {availableArticles.map((article) => (
                      <option key={article.id} value={String(article.id)}>
                        {article.title}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  className="button secondary"
                  disabled={!articleToAdd || busy}
                  onClick={() => void addArticle()}
                >
                  <Plus /> Add
                </button>
              </div>
            )}
            <div className="cloud-article-list">
              {projectArticles.map((article) => (
                <ArticleCard
                  key={article.id}
                  article={article}
                  onOpen={() => onOpen(article.id)}
                  action={
                    <button
                      className="icon-button cloud-remove-project-article"
                      aria-label={`Remove ${article.title} from project`}
                      disabled={busy}
                      onClick={() => void removeArticle(article)}
                    >
                      <X />
                    </button>
                  }
                />
              ))}
            </div>
            {selected && !projectArticles.length && (
              <EmptyState icon={BookOpen} title="This project is empty">
                Choose a paper above, or open a paper and add it from the
                reader’s context panel.
              </EmptyState>
            )}
          </section>
        </div>
      )}
    </>
  );
}

function JobRow({ job }: { job: ImportJob }) {
  const Icon =
    job.status === "succeeded"
      ? CheckCircle2
      : job.status === "failed"
        ? XCircle
        : job.status === "running"
          ? LoaderCircle
          : Clock3;
  const progress = job.progress_total
    ? Math.round(job.progress * 100)
    : job.status === "succeeded"
      ? 100
      : 0;
  return (
    <article className={`cloud-job-row ${job.status}`}>
      <span className="cloud-job-icon">
        <Icon className={job.status === "running" ? "spin" : ""} />
      </span>
      <span className="cloud-job-main">
        <span>
          <b>{formatLabel(job.type)}</b>
          <small>{job.source || "Cloud task"}</small>
        </span>
        <span>
          <small>{formatLabel(job.stage)} · {relativeDate(job.updated_at)}</small>
          <i><b style={{ width: `${progress}%` }} /></i>
        </span>
      </span>
      <span className={`cloud-job-status ${job.status}`}>{job.status}</span>
      {job.error_code && (
        <small className="cloud-job-error">{formatLabel(job.error_code)}</small>
      )}
    </article>
  );
}

function ImportsView({
  service,
  jobs,
  refreshing,
  revision,
  onImport,
  onRefresh,
  onError,
}: {
  service: CloudLibraryService;
  jobs: ImportJob[];
  refreshing: boolean;
  revision: number;
  onImport: () => void;
  onRefresh: () => void;
  onError: (message: string) => void;
}) {
  const [connections, setConnections] = useState<CloudDriveConnection[]>([]);
  const [connectorStatus, setConnectorStatus] =
    useState<CloudConnectorStatus | null>(null);
  const [connecting, setConnecting] =
    useState<CloudDriveProvider | null>(null);

  useEffect(() => {
    let active = true;
    void Promise.all([
      service.driveConnections(),
      service.connectorStatus(),
    ]).then(([nextConnections, nextConnectorStatus]) => {
      if (!active) return;
      setConnections(nextConnections);
      setConnectorStatus(nextConnectorStatus);
    }).catch((value) => {
      if (active) onError(readableError(value));
    });
    return () => {
      active = false;
    };
  }, [onError, revision, service]);

  const connect = async (provider: CloudDriveProvider) => {
    setConnecting(provider);
    try {
      await service.connectDrive(provider);
    } catch (value) {
      onError(readableError(value));
      setConnecting(null);
    }
  };

  const driveSource = (provider: CloudDriveProvider) => {
    const connection = connections.find(
      (candidate) => candidate.provider === provider,
    );
    const connected = connection?.status === "connected";
    return (
      <button
        disabled={connected || connecting != null}
        onClick={() => void connect(provider)}
      >
        {connecting === provider
          ? <LoaderCircle className="spin" />
          : <Cloud />}
        <span>
          <b>{providerLabel(provider)}</b>
          <small>
            {connected
              ? `Connected${connection.accountEmail
                ? ` as ${connection.accountEmail}`
                : ""}. File browsing is the next connector step.`
              : connection?.status === "reauthorization_required"
                ? "Reconnect this account to resume imports."
                : connectorAvailabilityLabel(
                  connectorStatus,
                  provider,
                  "Connect an account for direct PDF imports.",
                )}
          </small>
        </span>
        {connected ? <Check /> : <ChevronRight />}
      </button>
    );
  };

  return (
    <>
      <ViewHeading
        eyebrow="Durable background work"
        title="Imports & jobs"
        description="Uploads are resumable and deduplicated. Every managed PDF becomes available to your other signed-in devices."
        action={
          <button className="button primary" onClick={onImport}>
            <FileUp /> Choose PDFs
          </button>
        }
      />

      <section className="cloud-import-source-grid">
        <button onClick={onImport}>
          <HardDrive />
          <span>
            <b>This device</b>
            <small>Choose one or more PDFs.</small>
          </span>
          <ChevronRight />
        </button>
        <button onClick={onImport}>
          <FolderInput />
          <span>
            <b>iCloud Drive / Files</b>
            <small>Available through the system file picker.</small>
          </span>
          <ChevronRight />
        </button>
        {driveSource("google_drive")}
        {driveSource("onedrive")}
      </section>

      <section className="cloud-library-panel">
        <div className="cloud-list-heading">
          <div>
            <span className="eyebrow">Queue</span>
            <h2>Processing history</h2>
          </div>
          <button
            className="text-button"
            disabled={refreshing}
            onClick={onRefresh}
          >
            <RefreshCw className={refreshing ? "spin" : ""} /> Refresh
          </button>
        </div>
        <div className="cloud-job-list">
          {jobs.map((job) => <JobRow key={job.id} job={job} />)}
        </div>
        {!jobs.length && (
          <EmptyState icon={Clock3} title="No jobs yet">
            Uploads and future cloud extraction work will appear here.
          </EmptyState>
        )}
      </section>
    </>
  );
}

function SettingsView({
  service,
  user,
  library,
  trash,
  revision,
  onLibraryChanged,
  onRefresh,
  onNotice,
  onError,
}: {
  service: CloudLibraryService;
  user: CloudUser;
  library: CloudLibrary;
  trash: TrashArticle[];
  revision: number;
  onLibraryChanged: (library: CloudLibrary) => void;
  onRefresh: () => Promise<void>;
  onNotice: (message: string) => void;
  onError: (message: string) => void;
}) {
  const [name, setName] = useState(library.name);
  const [busy, setBusy] = useState(false);
  const [driveBusy, setDriveBusy] =
    useState<CloudDriveProvider | "backup" | null>(null);
  const [connections, setConnections] = useState<CloudDriveConnection[]>([]);
  const [connectorStatus, setConnectorStatus] =
    useState<CloudConnectorStatus | null>(null);
  const [backup, setBackup] = useState<CloudBackupSettings | null>(null);
  const [backupLoading, setBackupLoading] = useState(true);

  useEffect(() => setName(library.name), [library.name]);
  useEffect(() => {
    let active = true;
    setBackupLoading(true);
    void Promise.all([
      service.driveConnections(),
      service.connectorStatus(),
      service.backupSettings(),
    ]).then(([nextConnections, nextConnectorStatus, nextBackup]) => {
      if (!active) return;
      setConnections(nextConnections);
      setConnectorStatus(nextConnectorStatus);
      setBackup(nextBackup);
    }).catch((value) => {
      if (active) onError(readableError(value));
    }).finally(() => {
      if (active) setBackupLoading(false);
    });
    return () => {
      active = false;
    };
  }, [library.id, onError, revision, service]);

  const saveName = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      const updated = await service.updateLibraryName(name);
      onLibraryChanged(updated);
      onNotice("Library name saved.");
    } catch (value) {
      onError(readableError(value));
    } finally {
      setBusy(false);
    }
  };

  const restore = async (article: TrashArticle) => {
    setBusy(true);
    try {
      await service.restoreArticle(article.id);
      onNotice(`Restored “${article.title}”.`);
      await onRefresh();
    } catch (value) {
      onError(readableError(value));
    } finally {
      setBusy(false);
    }
  };

  const connectDrive = async (provider: CloudDriveProvider) => {
    setDriveBusy(provider);
    try {
      await service.connectDrive(provider);
    } catch (value) {
      onError(readableError(value));
      setDriveBusy(null);
    }
  };

  const updateBackup = async (
    patch: Parameters<CloudLibraryService["updateBackupSettings"]>[0],
    message: string,
  ) => {
    setDriveBusy("backup");
    try {
      const updated = await service.updateBackupSettings(patch);
      setBackup(updated);
      onNotice(message);
    } catch (value) {
      onError(readableError(value));
    } finally {
      setDriveBusy(null);
    }
  };

  const connectedDrive = connections.find(
    (connection) =>
      connection.id === backup?.connectionId &&
      connection.status === "connected",
  );

  const connectorCard = (provider: CloudDriveProvider) => {
    const connection = connections.find(
      (candidate) => candidate.provider === provider,
    );
    const connected = connection?.status === "connected";
    return (
      <button
        disabled={connected || driveBusy != null}
        onClick={() => void connectDrive(provider)}
      >
        {driveBusy === provider
          ? <LoaderCircle className="spin" />
          : connected
            ? <Check />
            : <Cloud />}
        <span>
          <b>{providerLabel(provider)}</b>
          <small>
            {connected
              ? connection.accountEmail || connection.accountLabel || "Connected"
              : connection?.status === "reauthorization_required"
                ? "Reconnect"
                : connectorAvailabilityLabel(
                  connectorStatus,
                  provider,
                  "Connect account",
                )}
          </small>
        </span>
      </button>
    );
  };

  return (
    <>
      <ViewHeading
        eyebrow="Account & sync"
        title="Settings"
        description="Manage this synced library, review the signed-in account, and recover recently removed papers."
      />

      <div className="cloud-settings-grid">
        <section className="cloud-settings-card">
          <span className="cloud-settings-icon"><BookOpen /></span>
          <div>
            <span className="eyebrow">Library</span>
            <h2>Name & identity</h2>
          </div>
          <form onSubmit={(event) => void saveName(event)}>
            <label>
              Library name
              <input
                value={name}
                maxLength={500}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <button
              className="button primary"
              disabled={busy || !name.trim() || name.trim() === library.name}
            >
              Save name
            </button>
          </form>
        </section>

        <section className="cloud-settings-card">
          <span className="cloud-settings-icon"><ShieldCheck /></span>
          <div>
            <span className="eyebrow">Account</span>
            <h2>Private by default</h2>
          </div>
          <dl>
            <div><dt>Signed in as</dt><dd>{user.email || "Account user"}</dd></div>
            <div><dt>PDF access</dt><dd>Short-lived signed links</dd></div>
            <div><dt>Data isolation</dt><dd>Row-level security enabled</dd></div>
          </dl>
        </section>

        <section className="cloud-settings-card cloud-drive-card">
          <span className="cloud-settings-icon"><Cloud /></span>
          <div>
            <span className="eyebrow">Cloud drives & redundancy</span>
            <h2>Imports and independent backup</h2>
          </div>
          <p>
            Every import receives a private managed-library copy for
            cross-device access. You can also keep a second app-owned copy in
            a dedicated Google Drive or OneDrive folder, independent of where
            the original PDF came from.
          </p>
          <div className="cloud-connector-list">
            <span><Check /><b>Research Memory Cloud</b><small>Active</small></span>
            {connectorCard("google_drive")}
            {connectorCard("onedrive")}
          </div>
          <div className="cloud-backup-policy">
            <div>
              <span>
                <b>Research Memory Backup folder</b>
                <small>
                  {connectedDrive
                    ? `${providerLabel(connectedDrive.provider)} · ${backup?.folderPath}`
                    : "Connect a drive to prepare this folder, then turn backup on."}
                </small>
              </span>
              {backup && (
                <i className={backup.enabled ? "active" : ""}>
                  {backup.enabled ? "Active" : "Off"}
                </i>
              )}
            </div>
            {backupLoading && (
              <span className="cloud-backup-loading">
                <LoaderCircle className="spin" /> Loading backup policy…
              </span>
            )}
            {backup && !backupLoading && (
              <>
                <label>
                  <input
                    type="checkbox"
                    checked={backup.enabled}
                    disabled={!connectedDrive || driveBusy != null}
                    onChange={(event) => void updateBackup(
                      { enabled: event.target.checked },
                      event.target.checked
                        ? "Drive backup enabled. Existing eligible PDFs were queued."
                        : "Drive backup paused.",
                    )}
                  />
                  <span>
                    <b>Keep a second copy in the backup folder</b>
                    <small>
                      New and existing eligible PDFs are queued without
                      changing or moving their source files.
                    </small>
                  </span>
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={backup.copyDeviceImports}
                    disabled={driveBusy != null}
                    onChange={(event) => void updateBackup(
                      { copyDeviceImports: event.target.checked },
                      "Device-import backup preference saved.",
                    )}
                  />
                  <span>
                    <b>Back up device and Files-picker imports</b>
                    <small>
                      Includes PDFs selected through iCloud Drive in the
                      system Files picker.
                    </small>
                  </span>
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={backup.copyCloudImports}
                    disabled={driveBusy != null}
                    onChange={(event) => void updateBackup(
                      { copyCloudImports: event.target.checked },
                      "Cloud-import backup preference saved.",
                    )}
                  />
                  <span>
                    <b>Also back up PDFs imported from cloud drives</b>
                    <small>
                      Creates a separate app backup even when the source was
                      Google Drive or OneDrive, so moving the original later
                      will not break the backup.
                    </small>
                  </span>
                </label>
                <div className="cloud-backup-counts">
                  <span><b>{backup.queuedCopies}</b><small>Queued</small></span>
                  <span><b>{backup.completedCopies}</b><small>Backed up</small></span>
                  <span><b>{backup.failedCopies}</b><small>Need retry</small></span>
                </div>
              </>
            )}
          </div>
        </section>

        <section className="cloud-settings-card cloud-trash-card">
          <span className="cloud-settings-icon"><Trash2 /></span>
          <div>
            <span className="eyebrow">Recovery</span>
            <h2>Recently deleted</h2>
          </div>
          <p>
            Papers remain recoverable here for 30 days after removal.
          </p>
          <div className="cloud-trash-list">
            {trash.map((article) => (
              <div key={article.id}>
                <span>
                  <b>{article.title}</b>
                  <small>
                    Removed {relativeDate(article.deleted_at)} · scheduled for
                    cleanup{" "}
                    {new Intl.DateTimeFormat(undefined, {
                      month: "short",
                      day: "numeric",
                    }).format(new Date(article.purge_after))}
                  </small>
                </span>
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() => void restore(article)}
                >
                  <ArchiveRestore /> Restore
                </button>
              </div>
            ))}
            {!trash.length && (
              <small className="cloud-trash-empty">
                Trash is empty. Removed papers will appear here before final
                cleanup.
              </small>
            )}
          </div>
        </section>
      </div>
    </>
  );
}

function CloudRuntime({ service }: { service: CloudLibraryService }) {
  const [user, setUser] = useState<CloudUser | null | undefined>(undefined);
  const [passwordRecovery, setPasswordRecovery] = useState(
    () => window.location.pathname.replace(/\/+$/, "") === "/reset-password",
  );
  const [library, setLibrary] = useState<CloudLibrary | null>(null);
  const [view, setView] = useState<View>("home");
  const [articles, setArticles] = useState<ArticleSummary[]>([]);
  const [dashboard, setDashboard] =
    useState<CloudDashboard>(emptyDashboard);
  const [projects, setProjects] = useState<Project[]>([]);
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [trash, setTrash] = useState<TrashArticle[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] =
    useState<UploadProgress | null>(null);
  const [reader, setReader] = useState<ArticleDetail | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const readerId = useRef<EntityId | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    readerId.current = reader?.id ?? null;
  }, [reader?.id]);

  useEffect(() => {
    const callbackUrl = new URL(window.location.href);
    const connector = callbackUrl.searchParams.get("connector");
    const connectorError = callbackUrl.searchParams.get("connector_error");
    if (!connector && !connectorError) return;
    if (connector) {
      setNotice(
        `${formatLabel(connector)} connected. Review its import and backup settings.`,
      );
      setView("settings");
    } else if (connectorError) {
      setError(`Cloud-drive connection failed: ${formatLabel(connectorError)}.`);
      setView("settings");
    }
    callbackUrl.searchParams.delete("connector");
    callbackUrl.searchParams.delete("connector_error");
    window.history.replaceState(
      window.history.state,
      document.title,
      `${callbackUrl.pathname}${callbackUrl.search}${callbackUrl.hash}`,
    );
  }, []);

  const refreshWorkspace = useCallback(async () => {
    setRefreshing(true);
    try {
      const [nextArticles, nextDashboard, nextProjects, nextJobs, nextTrash] =
        await Promise.all([
          service.listArticles(),
          service.dashboard(),
          service.projects(),
          service.jobs(),
          service.trash(),
        ]);
      setArticles(nextArticles);
      setDashboard(nextDashboard);
      setProjects(nextProjects);
      setJobs(nextJobs);
      setTrash(nextTrash);
      setRevision((current) => current + 1);
      setError("");
    } catch (value) {
      setError(readableError(value));
    } finally {
      setRefreshing(false);
      setLoading(false);
    }
  }, [service]);

  useEffect(() => {
    let active = true;
    void service.currentUser().then((next) => {
      if (active) setUser(next);
    }).catch((value) => {
      if (active) {
        setError(readableError(value));
        setUser(null);
      }
    });
    const unsubscribe = service.onAuthChange((next) => {
      if (active) setUser(next);
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, [service]);

  useEffect(() => {
    if (!user) {
      setLibrary(null);
      setArticles([]);
      setDashboard(emptyDashboard);
      setProjects([]);
      setJobs([]);
      setTrash([]);
      setReader(null);
      setLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    void service.ensurePersonalLibrary(user).then(async (next) => {
      if (!active) return;
      setLibrary(next);
      await refreshWorkspace();
    }).catch((value) => {
      if (active) {
        setError(readableError(value));
        setLoading(false);
      }
    });
    const stopSync = service.subscribeToLibrary(user.id, () => {
      void service.ensurePersonalLibrary(user).then((next) => {
        if (active) setLibrary(next);
        return refreshWorkspace();
      }).catch((value) => {
        if (active) setError(readableError(value));
      });
      const openId = readerId.current;
      if (openId != null) {
        void service.article(openId).then(setReader).catch(() => {});
      }
    });
    return () => {
      active = false;
      stopSync();
    };
  }, [refreshWorkspace, service, user]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (
        event.key !== "/" ||
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement
      ) {
        return;
      }
      event.preventDefault();
      setView("search");
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const openArticle = async (id: EntityId) => {
    setError("");
    try {
      setReader(await service.article(id));
    } catch (value) {
      setError(readableError(value));
    }
  };

  const importFiles = async (files: File[]) => {
    if (!files.length) return;
    setUploading(true);
    setError("");
    setNotice("");
    let imported = 0;
    let lastArticle: ArticleDetail | null = null;
    try {
      for (const file of files) {
        lastArticle = await service.uploadPdf(file, setUploadProgress);
        imported += 1;
      }
      setNotice(
        `${imported} ${imported === 1 ? "PDF is" : "PDFs are"} available in your synced library.`,
      );
      await refreshWorkspace();
      if (files.length === 1 && lastArticle) setReader(lastArticle);
    } catch (value) {
      setError(readableError(value));
      await refreshWorkspace();
    } finally {
      setUploading(false);
      setUploadProgress(null);
    }
  };

  if (user === undefined) {
    return (
      <main className="cloud-boot">
        <span className="brand-glyph"><BookOpen /></span>
        <LoaderCircle className="spin" />
        <p>Restoring your private library…</p>
      </main>
    );
  }
  if (!user) return <AuthScreen service={service} initialError={error} />;
  if (passwordRecovery) {
    return (
      <PasswordResetScreen
        service={service}
        onComplete={() => {
          window.history.replaceState(
            window.history.state,
            document.title,
            import.meta.env.BASE_URL || "/",
          );
          setPasswordRecovery(false);
        }}
      />
    );
  }

  const progressPercent = uploadProgress?.bytesTotal
    ? Math.round(
        (uploadProgress.bytesSent / uploadProgress.bytesTotal) * 100,
      )
    : 0;
  const openUploadPicker = () => fileInput.current?.click();

  let content: ReactNode;
  if (!library || loading) {
    content = (
      <div className="cloud-workspace-loading">
        <LoaderCircle className="spin" />
        <span>
          <b>Loading your library</b>
          <small>Syncing papers, projects, and recent activity…</small>
        </span>
      </div>
    );
  } else if (view === "home") {
    content = (
      <HomeView
        library={library}
        dashboard={dashboard}
        onNavigate={setView}
        onOpen={(id) => void openArticle(id)}
        onImport={openUploadPicker}
      />
    );
  } else if (view === "library") {
    content = (
      <LibraryView
        library={library}
        articles={articles}
        loading={refreshing}
        onOpen={(id) => void openArticle(id)}
        onImport={openUploadPicker}
        onRefresh={() => void refreshWorkspace()}
      />
    );
  } else if (view === "search") {
    content = (
      <SearchView
        service={service}
        projects={projects}
        onOpen={(id) => void openArticle(id)}
      />
    );
  } else if (view === "projects") {
    content = (
      <ProjectsView
        service={service}
        projects={projects}
        allArticles={articles}
        revision={revision}
        onOpen={(id) => void openArticle(id)}
        onRefresh={refreshWorkspace}
        onNotice={setNotice}
        onError={setError}
      />
    );
  } else if (view === "imports") {
    content = (
      <ImportsView
        service={service}
        jobs={jobs}
        refreshing={refreshing}
        revision={revision}
        onImport={openUploadPicker}
        onRefresh={() => void refreshWorkspace()}
        onError={setError}
      />
    );
  } else {
    content = (
      <SettingsView
        service={service}
        user={user}
        library={library}
        trash={trash}
        revision={revision}
        onLibraryChanged={setLibrary}
        onRefresh={refreshWorkspace}
        onNotice={setNotice}
        onError={setError}
      />
    );
  }

  return (
    <div className="cloud-app cloud-shell">
      <header className="cloud-header">
        <button className="cloud-brand cloud-brand-button" onClick={() => setView("home")}>
          <span className="brand-glyph"><BookOpen /></span>
          <span>
            <b>Research Memory</b>
            <small>Synced library</small>
          </span>
        </button>

        <button
          className="cloud-command-search"
          onClick={() => setView("search")}
        >
          <Search />
          <span>Search your library</span>
          <kbd>/</kbd>
        </button>

        <div className="cloud-account">
          <a
            className="button secondary cloud-header-download"
            href={macDownloadUrl}
            target="_blank"
            rel="noreferrer"
            aria-label="Download Mac desktop app"
          >
            <Download />
            <span>Mac app</span>
          </a>
          <label
            className={`button primary cloud-header-upload ${uploading ? "disabled" : ""}`}
          >
            {uploading ? <LoaderCircle className="spin" /> : <FileUp />}
            <span>{uploading ? `${progressPercent}%` : "Import"}</span>
            <input
              ref={fileInput}
              id="cloud-pdf-input"
              aria-label="Import PDFs"
              type="file"
              accept="application/pdf,.pdf"
              multiple
              disabled={uploading}
              onChange={(event) => {
                const files = Array.from(event.currentTarget.files ?? []);
                event.currentTarget.value = "";
                void importFiles(files);
              }}
            />
          </label>
          <span className="cloud-live"><i /> Synced</span>
          <span className="cloud-account-email">{user.email || "Signed in"}</span>
          <button
            className="icon-button"
            aria-label="Sign out"
            onClick={() => void service.signOut().catch((value) => {
              setError(readableError(value));
            })}
          >
            <LogOut />
          </button>
        </div>
      </header>

      <div className="cloud-workspace">
        <aside className="cloud-sidebar">
          <nav aria-label="Main navigation">
            {navigation.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.id}
                  className={view === item.id ? "active" : ""}
                  aria-current={view === item.id ? "page" : undefined}
                  onClick={() => setView(item.id)}
                >
                  <Icon />
                  <span>{item.label}</span>
                  {item.id === "imports" && dashboard.activeJobCount > 0 && (
                    <i>{dashboard.activeJobCount}</i>
                  )}
                </button>
              );
            })}
          </nav>
          <div className="cloud-sidebar-status">
            <span><i /></span>
            <div>
              <b>Cloud library active</b>
              <small>{dashboard.articleCount} synced papers</small>
            </div>
          </div>
          <p>
            <ShieldCheck /> Private rows and signed PDF links
          </p>
        </aside>

        <main className="cloud-content">
          {uploadProgress && (
            <div className="cloud-upload-progress" role="status">
              <span>
                <b>{uploadProgress.fileName}</b>
                <small>{progressPercent}% securely uploaded</small>
              </span>
              <div><i style={{ width: `${progressPercent}%` }} /></div>
            </div>
          )}
          {notice && (
            <div className="inline-notice cloud-dismissible" role="status">
              <span>{notice}</span>
              <button aria-label="Dismiss notice" onClick={() => setNotice("")}>
                <X />
              </button>
            </div>
          )}
          {error && (
            <div className="error-banner cloud-dismissible" role="alert">
              <span>{error}</span>
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X />
              </button>
            </div>
          )}
          {content}
        </main>
      </div>

      <nav className="cloud-mobile-nav" aria-label="Mobile navigation">
        {navigation.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              className={view === item.id ? "active" : ""}
              aria-current={view === item.id ? "page" : undefined}
              onClick={() => setView(item.id)}
            >
              <Icon />
              <span>{item.shortLabel}</span>
            </button>
          );
        })}
      </nav>

      {reader && (
        <Suspense fallback={<div className="cloud-reader-loading">Opening PDF…</div>}>
          <PdfReader
            article={reader}
            client={service}
            onClose={() => setReader(null)}
            onArticleChanged={(next) => {
              setReader(next);
              void refreshWorkspace();
            }}
            onTrashed={() => {
              setReader(null);
              void refreshWorkspace();
            }}
          />
        </Suspense>
      )}
    </div>
  );
}

export function CloudApp({ service: injectedService }: CloudAppProps) {
  const resolution = useMemo(() => {
    if (injectedService) return { service: injectedService, error: "" };
    try {
      return { service: createCloudLibraryService(), error: "" };
    } catch (value) {
      return {
        service: null,
        error: readableError(value),
      };
    }
  }, [injectedService]);

  if (!resolution.service) {
    return <ConfigurationScreen message={resolution.error} />;
  }
  return <CloudRuntime service={resolution.service} />;
}
