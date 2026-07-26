import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { LibraryView } from "../App";
import { core } from "../lib/api";
import type { ArticleSummary, Project } from "../types";

vi.mock("../lib/api", () => ({
  core: {
    articles: vi.fn(),
    projects: vi.fn(),
    addProjectArticles: vi.fn(),
  },
}));

const articles: ArticleSummary[] = [
  {
    id: 11,
    title: "Airway Paper One",
    authors: "A. Author",
    journal: "Chest",
    publication_year: 2022,
    source_type: "journal_article",
    reading_status: "unread",
    importance: 0,
    page_count: 8,
    why_saved: "",
    extraction_status: "indexed",
    review_state: "ready",
  },
  {
    id: 22,
    title: "Airway Paper Two",
    authors: "B. Author",
    journal: "Thorax",
    publication_year: 2023,
    source_type: "journal_article",
    reading_status: "unread",
    importance: 0,
    page_count: 12,
    why_saved: "",
    extraction_status: "indexed",
    review_state: "ready",
  },
];

const projects: Project[] = [
  {
    id: 7,
    name: "Airway Review",
    description: "",
    project_type: "collection",
    central_question: "",
    created_at: "2026-07-26T00:00:00Z",
    updated_at: "2026-07-26T00:00:00Z",
    article_count: 0,
  },
];

beforeEach(() => {
  vi.mocked(core.articles).mockResolvedValue({
    items: articles,
    total: articles.length,
    limit: 100,
    offset: 0,
  });
  vi.mocked(core.projects).mockResolvedValue(projects);
  vi.mocked(core.addProjectArticles).mockResolvedValue({
    project_id: 7,
    requested: 2,
    added: 2,
    already_present: 0,
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

test("adds all selected library articles to one project in a single operation", async () => {
  const user = userEvent.setup();
  const { container } = render(
    <LibraryView onOpen={vi.fn()} onImport={vi.fn()} />,
  );

  const selectAll = await screen.findByRole("checkbox", {
    name: "Select all loaded articles",
  });
  await waitFor(() => expect(selectAll).toBeEnabled());
  await user.click(selectAll);
  expect(screen.getByText("2 selected")).toBeInTheDocument();

  await screen.findByRole("option", { name: "Airway Review (0)" });
  const accessibility = await axe.run(container, {
    rules: {
      "color-contrast": { enabled: false },
    },
  });
  expect(accessibility.violations).toEqual([]);
  await user.selectOptions(
    screen.getByRole("combobox", { name: "Project" }),
    "7",
  );
  await user.click(screen.getByRole("button", { name: "Add to project" }));

  await waitFor(() => {
    expect(core.addProjectArticles).toHaveBeenCalledWith(7, [11, 22]);
  });
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Added 2 papers to Airway Review.",
  );
  expect(
    screen.getByRole("checkbox", { name: "Select all loaded articles" }),
  ).not.toBeChecked();
});

test("selecting a row does not accidentally open its reader", async () => {
  const user = userEvent.setup();
  const onOpen = vi.fn();
  render(<LibraryView onOpen={onOpen} onImport={vi.fn()} />);

  await user.click(
    await screen.findByRole("checkbox", { name: "Select Airway Paper One" }),
  );

  expect(onOpen).not.toHaveBeenCalled();
  expect(screen.getByText("1 selected")).toBeInTheDocument();
});
