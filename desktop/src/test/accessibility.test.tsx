import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App, ReaderErrorBoundary } from "../App";

const status = {
  status: "ok" as const,
  version: "0.2.0",
  schema_version: 7,
  documents: 0,
  review_needed: 0,
  jobs_running: 0,
  embedding_backend: "hash-v1",
  embedding_warning: null,
  ocr_available: true,
  network_metadata_enabled: false,
  diagnostics_enabled: false,
};

vi.mock("../lib/api", () => ({
  core: {
    status: vi.fn(async () => status),
    articles: vi.fn(async () => ({ items: [], total: 0, limit: 100, offset: 0 })),
    jobs: vi.fn(async () => []),
    chooseImportFolder: vi.fn(async () => null),
    chooseImportFiles: vi.fn(async () => []),
    importZotero: vi.fn(),
    search: vi.fn(async () => []),
    projects: vi.fn(async () => []),
    trash: vi.fn(async () => []),
  },
}));

vi.mock("../components/PdfReader", () => ({
  PdfReader: () => null,
}));

beforeEach(() => {
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
    clear: () => values.clear(),
  });
  localStorage.setItem("research-memory:onboarded", "true");
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("primary desktop shell has no automated accessibility violations", async () => {
  const { container } = render(<App />);
  await screen.findByRole("navigation", { name: "Primary" });
  const result = await axe.run(container, {
    rules: {
      "color-contrast": { enabled: false },
    },
  });
  expect(result.violations).toEqual([]);
});

test("onboarding has no automated accessibility violations", async () => {
  localStorage.removeItem("research-memory:onboarded");
  const { container } = render(<App />);
  await screen.findByRole("heading", { name: "Choose your literature" });
  const result = await axe.run(container, {
    rules: {
      "color-contrast": { enabled: false },
    },
  });
  expect(result.violations).toEqual([]);
});

test("settings and recoverable trash have no automated accessibility violations", async () => {
  const { container } = render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
  await screen.findByRole("heading", { name: "Trash" });
  const result = await axe.run(container, {
    rules: {
      "color-contrast": { enabled: false },
    },
  });
  expect(result.violations).toEqual([]);
});

test("recall search clearly reports when no evidence-backed matches exist", async () => {
  const { container } = render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Recall Search" }));
  fireEvent.change(
    screen.getByPlaceholderText(
      "The paper where navigation success was around 94% but strict diagnostic yield was closer to 70%…",
    ),
    { target: { value: "the paper about aliens taking over the world" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Search" }));

  await screen.findByRole("heading", { name: "No strong matches" });
  expect(screen.queryByText(/likely matches/i)).not.toBeInTheDocument();
  const result = await axe.run(container, {
    rules: {
      "color-contrast": { enabled: false },
    },
  });
  expect(result.violations).toEqual([]);
});

test("reader errors preserve a recoverable application surface", () => {
  const close = vi.fn();
  vi.spyOn(console, "error").mockImplementation(() => {});
  const BrokenReader = () => {
    throw new Error("Broken reader fixture");
  };

  render(
    <ReaderErrorBoundary onClose={close}>
      <BrokenReader />
    </ReaderErrorBoundary>,
  );

  expect(screen.getByRole("alert")).toHaveTextContent(
    "The reader couldn’t open this paper",
  );
  fireEvent.click(screen.getByRole("button", { name: "Close reader" }));
  expect(close).toHaveBeenCalledOnce();
});
