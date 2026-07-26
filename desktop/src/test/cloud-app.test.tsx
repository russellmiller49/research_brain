import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, expect, test, vi } from "vitest";
import { CloudApp } from "../cloud/CloudApp";
import type {
  CloudLibraryService,
  CloudUser,
} from "../cloud/service";
import type { ArticleDetail, ArticleSummary } from "../types";

vi.mock("../components/PdfReader", () => ({
  PdfReader: () => <div>Cloud PDF reader</div>,
}));

const user: CloudUser = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "reader@example.test",
};

const summary: ArticleSummary = {
  id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  title: "Synced airway navigation study",
  authors: "A. Researcher",
  journal: "Chest",
  publication_year: 2026,
  source_type: "journal_article",
  reading_status: "unread",
  importance: 0,
  page_count: 12,
  why_saved: "",
  extraction_status: "queued",
  review_state: "ready",
};

const detail: ArticleDetail = {
  ...summary,
  doi: "",
  pmid: "",
  abstract: "",
  user_summary: "",
  metadata_conflicts: [],
  assets: [],
  annotations: [],
};

function fakeService(
  currentUser: CloudUser | null,
): CloudLibraryService {
  return {
    currentUser: vi.fn(async () => currentUser),
    onAuthChange: vi.fn(() => () => {}),
    sendMagicLink: vi.fn(async () => {}),
    signInWithProvider: vi.fn(async () => {}),
    signOut: vi.fn(async () => {}),
    ensurePersonalLibrary: vi.fn(async () => ({
      id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      ownerId: user.id,
      name: "My Research Library",
    })),
    updateLibraryName: vi.fn(async (name: string) => ({
      id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      ownerId: user.id,
      name,
    })),
    dashboard: vi.fn(async () => ({
      articleCount: currentUser ? 1 : 0,
      unreadCount: currentUser ? 1 : 0,
      readingCount: 0,
      annotationCount: 0,
      projectCount: 0,
      activeJobCount: 0,
      reviewCount: 0,
      recentArticles: currentUser ? [summary] : [],
    })),
    listArticles: vi.fn(async () => (currentUser ? [summary] : [])),
    searchArticles: vi.fn(async () => (currentUser ? [summary] : [])),
    driveConnections: vi.fn(async () => []),
    connectorStatus: vi.fn(async () => ({
      serviceAvailable: true,
      providers: { google_drive: true, onedrive: true },
    })),
    connectDrive: vi.fn(async () => {}),
    backupSettings: vi.fn(async () => ({
      id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
      connectionId: null,
      enabled: false,
      copyDeviceImports: true,
      copyCloudImports: true,
      folderName: "Research Memory Backup",
      folderPath: "Research Memory Backup",
      queuedCopies: 0,
      completedCopies: 0,
      failedCopies: 0,
      lastErrorCode: null,
    })),
    updateBackupSettings: vi.fn(async (patch) => ({
      id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
      connectionId: null,
      enabled: patch.enabled ?? false,
      copyDeviceImports: patch.copyDeviceImports ?? true,
      copyCloudImports: patch.copyCloudImports ?? true,
      folderName: "Research Memory Backup",
      folderPath: "Research Memory Backup",
      queuedCopies: 0,
      completedCopies: 0,
      failedCopies: 0,
      lastErrorCode: null,
    })),
    article: vi.fn(async () => detail),
    uploadPdf: vi.fn(async () => detail),
    subscribeToLibrary: vi.fn(() => () => {}),
    assetUrl: vi.fn(async () => "blob:pdf"),
    unlockArticle: vi.fn(async () => {
      throw new Error("Not supported in test");
    }),
    projects: vi.fn(async () => []),
    createProject: vi.fn(async (name: string, description: string) => ({
      id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      name,
      description,
      project_type: "collection",
      central_question: "",
      created_at: "2026-07-26T12:00:00Z",
      updated_at: "2026-07-26T12:00:00Z",
      article_count: 0,
    })),
    projectArticles: vi.fn(async () => []),
    removeProjectArticle: vi.fn(async () => {}),
    jobs: vi.fn(async () => []),
    trash: vi.fn(async () => []),
    restoreArticle: vi.fn(async () => {}),
    createAnnotation: vi.fn(async () => {
      throw new Error("Not used in test");
    }),
    exportArticle: vi.fn(async () => null),
    resolveArticleReview: vi.fn(async () => detail),
    deleteAnnotation: vi.fn(async () => {}),
    updateArticle: vi.fn(async () => detail),
    addProjectArticle: vi.fn(async () => {}),
    trashArticle: vi.fn(async () => true),
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

test("offers scoped passwordless sign-in without accessibility violations", async () => {
  const service = fakeService(null);
  const interaction = userEvent.setup();
  const { container } = render(<CloudApp service={service} />);

  await screen.findByRole("heading", { name: "Sign in to your library" });
  expect(
    screen.getByRole("link", { name: "Download for Mac" }),
  ).toHaveAttribute(
    "href",
    "https://github.com/russellmiller49/research_brain/releases",
  );
  await interaction.type(
    screen.getByRole("textbox", { name: "Email address" }),
    "reader@example.test",
  );
  await interaction.click(
    screen.getByRole("button", { name: "Email me a secure link" }),
  );

  await waitFor(() => {
    expect(service.sendMagicLink).toHaveBeenCalledWith(
      "reader@example.test",
    );
  });
  expect(screen.getByRole("status")).toHaveTextContent("Check your email");
  expect(
    screen.queryByRole("button", { name: "Google" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Microsoft" }),
  ).not.toBeInTheDocument();
  const result = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations).toEqual([]);
});

test("loads the signed-in library and imports a PDF through the shared service", async () => {
  const service = fakeService(user);
  const interaction = userEvent.setup();
  render(<CloudApp service={service} />);

  expect(
    await screen.findByRole("heading", { name: "My Research Library" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Download Mac desktop app" }),
  ).toHaveAttribute(
    "href",
    "https://github.com/russellmiller49/research_brain/releases",
  );
  expect(
    await screen.findByText("Synced airway navigation study"),
  ).toBeInTheDocument();
  expect(service.subscribeToLibrary).toHaveBeenCalledWith(
    user.id,
    expect.any(Function),
  );

  const file = new File(["%PDF-1.7"], "new-paper.pdf", {
    type: "application/pdf",
  });
  await interaction.upload(screen.getByLabelText("Import PDFs"), file);

  await waitFor(() => {
    expect(service.uploadPdf).toHaveBeenCalledWith(
      file,
      expect.any(Function),
    );
  });
  expect(await screen.findByRole("status")).toHaveTextContent(
    "1 PDF is available in your synced library.",
  );
  expect(await screen.findByText("Cloud PDF reader")).toBeInTheDocument();
});

test("keeps the signed-in cloud workspace free of automated accessibility violations", async () => {
  const service = fakeService(user);
  const { container } = render(<CloudApp service={service} />);

  await screen.findByRole("heading", { name: "My Research Library" });
  const result = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations).toEqual([]);
});

test("runs recall search from the web navigation", async () => {
  const service = fakeService(user);
  const interaction = userEvent.setup();
  render(<CloudApp service={service} />);

  await screen.findByRole("heading", { name: "My Research Library" });
  await interaction.click(
    screen.getByRole("button", { name: "Recall search" }),
  );
  await screen.findByRole("heading", {
    name: "Find the paper you half remember",
  });
  await interaction.type(
    screen.getByRole("textbox", { name: "Recall search query" }),
    "airway navigation",
  );
  await interaction.click(
    screen.getByRole("button", { name: "Run recall search" }),
  );

  await waitFor(() => {
    expect(service.searchArticles).toHaveBeenCalledWith({
      text: "airway navigation",
      yearMin: undefined,
      yearMax: undefined,
      readingStatus: undefined,
      projectId: undefined,
    });
  });
  expect(await screen.findByRole("heading", { name: "1 match" }))
    .toBeInTheDocument();
});

test("creates a project from the responsive projects view", async () => {
  const service = fakeService(user);
  const interaction = userEvent.setup();
  render(<CloudApp service={service} />);

  await screen.findByRole("heading", { name: "My Research Library" });
  await interaction.click(
    screen.getAllByRole("button", { name: "Projects" })[0]!,
  );
  await screen.findByRole("heading", { name: "Projects" });
  await interaction.click(
    screen.getByRole("button", { name: "New project" }),
  );
  await interaction.type(
    screen.getByRole("textbox", { name: "Project name" }),
    "Airway review",
  );
  await interaction.type(
    screen.getByRole("textbox", { name: "Description" }),
    "Evidence collection",
  );
  await interaction.click(
    screen.getByRole("button", { name: "Create project" }),
  );

  await waitFor(() => {
    expect(service.createProject).toHaveBeenCalledWith(
      "Airway review",
      "Evidence collection",
    );
  });
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Created “Airway review”.",
  );
});

test("lets a user include cloud-origin PDFs in the independent backup policy", async () => {
  const service = fakeService(user);
  const interaction = userEvent.setup();
  const { container } = render(<CloudApp service={service} />);

  await screen.findByRole("heading", { name: "My Research Library" });
  await interaction.click(
    screen.getAllByRole("button", { name: "Settings" })[0]!,
  );
  await screen.findByRole("heading", { name: "Settings" });

  const cloudImportPolicy = await screen.findByRole("checkbox", {
    name: /Also back up PDFs imported from cloud drives/i,
  });
  expect(cloudImportPolicy).toBeChecked();
  await interaction.click(cloudImportPolicy);

  await waitFor(() => {
    expect(service.updateBackupSettings).toHaveBeenCalledWith({
      copyCloudImports: false,
    });
  });
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Cloud-import backup preference saved.",
  );
  const result = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations).toEqual([]);
});

test("shows cloud connector setup state before a user tries to attach a drive", async () => {
  const service = fakeService(user);
  vi.mocked(service.connectorStatus).mockResolvedValue({
    serviceAvailable: false,
    providers: { google_drive: false, onedrive: false },
  });
  const interaction = userEvent.setup();
  render(<CloudApp service={service} />);

  await screen.findByRole("heading", { name: "My Research Library" });
  await interaction.click(
    screen.getAllByRole("button", { name: "Settings" })[0]!,
  );

  expect(
    await screen.findAllByText("Connector service is stopped"),
  ).toHaveLength(2);
});
