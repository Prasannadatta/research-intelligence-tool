import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { ThemeProvider, createTheme } from "@mui/material/styles";

import SavedSearchesPage from "./SavedSearchesPage";
import * as savedSearchesApi from "./savedSearchesApi";
import * as dataUpdaterApi from "../dataUpdater/dataUpdaterApi";

const theme = createTheme({ colorSchemes: { light: true, dark: true } });

const AUTHOR_SEARCH = {
  id: "author-1",
  search_type: "authors",
  display_name: "Author A + Author B + Author C",
  payload: {
    authors: [
      {
        canonical_author_id: "c1",
        display_name: "Author A",
        provider: "openalex",
        provider_author_id: "A1",
      },
      {
        canonical_author_id: "c2",
        display_name: "Author B",
        provider: "openalex",
        provider_author_id: "A2",
      },
      {
        canonical_author_id: "c3",
        display_name: "Author C",
        provider: "openalex",
        provider_author_id: "A3",
      },
    ],
    active_author_ids: ["c1", "c3"],
    analysis_mode: "common_publications",
    filters: {
      from_year: 2020,
      to_year: 2026,
      sources: ["openalex"],
      institutions: ["UC Berkeley"],
      venues: [],
      grant_numbers: [],
    },
    excluded_work_ids: ["W1", "W2"],
  },
  applied_filters: {
    from_year: 2020,
    to_year: 2026,
    sources: ["openalex"],
    institutions: ["UC Berkeley"],
    venues: [],
    grant_numbers: [],
  },
  provider_context: { providers: ["openalex"], mode: "common_publications" },
  excluded_work_ids: ["W1", "W2"],
  created_at: "2026-08-12T00:00:00Z",
  updated_at: "2026-08-12T00:00:00Z",
  last_viewed_at: "2026-08-17T00:00:00Z",
  view_count: 2,
};

const LARGE_AUTHOR_SEARCH = {
  ...AUTHOR_SEARCH,
  id: "author-large",
  display_name: "Large team",
  payload: {
    ...AUTHOR_SEARCH.payload,
    authors: Array.from({ length: 20 }, (_, index) => ({
      canonical_author_id: `c${index + 1}`,
      display_name: `Author ${index + 1}`,
      provider: "openalex",
      provider_author_id: `A${index + 1}`,
    })),
    active_author_ids: Array.from({ length: 20 }, (_, index) => `c${index + 1}`),
  },
};

const GRANT_SEARCH = {
  id: "grant-1",
  search_type: "grant",
  display_name: "R01GM123456",
  payload: {
    grant_number: "R01GM123456",
    provider: "openalex",
    filters: {
      venues: ["Nature Medicine"],
      sources: ["openalex"],
      institutions: [],
      authors: [],
    },
  },
  applied_filters: {
    venues: ["Nature Medicine"],
    sources: ["openalex"],
    institutions: [],
    authors: [],
  },
  provider_context: { provider: "openalex" },
  created_at: "2026-08-10T00:00:00Z",
  updated_at: "2026-08-10T00:00:00Z",
  last_viewed_at: null,
  view_count: 0,
  metadata: { funder_name: "NIH" },
};

function LocationStateProbe() {
  const location = useLocation();
  return (
    <pre data-testid="location-state">
      {JSON.stringify({ pathname: location.pathname, search: location.search, state: location.state })}
    </pre>
  );
}

function renderPage() {
  return render(
    <ThemeProvider theme={theme}>
      <MemoryRouter initialEntries={["/saved-searches"]}>
        <Routes>
          <Route path="/saved-searches" element={<SavedSearchesPage />} />
          <Route path="/analyze/authors" element={<LocationStateProbe />} />
          <Route path="/grants/:grantNumber" element={<LocationStateProbe />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

function installLocalStorageStub() {
  const store = new Map();
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: vi.fn((key) => store.get(key) || null),
      setItem: vi.fn((key, value) => {
        store.set(key, String(value));
      }),
      removeItem: vi.fn((key) => {
        store.delete(key);
      }),
      clear: vi.fn(() => {
        store.clear();
      }),
    },
  });
}

describe("SavedSearchesPage", () => {
  beforeEach(() => {
    installLocalStorageStub();
    window.localStorage.clear();
    vi.spyOn(savedSearchesApi, "fetchSavedSearches").mockImplementation(({ type }) =>
      Promise.resolve(type === "grant" ? [GRANT_SEARCH] : [AUTHOR_SEARCH, LARGE_AUTHOR_SEARCH]),
    );
    vi.spyOn(savedSearchesApi, "markSavedSearchViewed").mockImplementation((id) => {
      if (id === "grant-1") {
        return Promise.resolve(GRANT_SEARCH);
      }
      if (id === "author-large") {
        return Promise.resolve(LARGE_AUTHOR_SEARCH);
      }
      return Promise.resolve(AUTHOR_SEARCH);
    });
    vi.spyOn(savedSearchesApi, "deleteSavedSearch").mockResolvedValue();
    vi.spyOn(savedSearchesApi, "patchSavedSearch").mockImplementation((id, patch) =>
      Promise.resolve({
        ...(id === "author-large" ? LARGE_AUTHOR_SEARCH : AUTHOR_SEARCH),
        ...patch,
        display_name:
          patch.display_name === ""
            ? "Author A + Author B + Author C"
            : patch.display_name ?? AUTHOR_SEARCH.display_name,
        outcome: "updated",
      }),
    );
    vi.spyOn(dataUpdaterApi, "startSavedSearchDataUpdate").mockResolvedValue({
      id: "job-1",
      status: "running",
    });
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("renders a searchable table with compact author lists", async () => {
    renderPage();

    expect(await screen.findByRole("table", { name: "Saved searches" })).toBeInTheDocument();
    expect(screen.getByText("Author A + Author B + Author C")).toBeInTheDocument();
    expect(screen.getByText("Author 1, Author 2, Author 3 +17 more")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Name or author"), {
      target: { value: "large" },
    });
    expect(screen.getByText("Large team")).toBeInTheDocument();
    expect(screen.queryByText("Author A + Author B + Author C")).not.toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Name or author"), {
      target: { value: "Author B" },
    });
    expect(await screen.findByText("Author A + Author B + Author C")).toBeInTheDocument();
  });

  it("switches to grants and opens restored route state", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Grants" }));
    await waitFor(() => {
      expect(screen.getAllByText("R01GM123456").length).toBeGreaterThan(0);
    });

    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    const probe = await screen.findByTestId("location-state");
    const state = JSON.parse(probe.textContent);
    expect(state.pathname).toBe("/grants/R01GM123456");
    expect(state.state.filters.venues).toEqual(["Nature Medicine"]);
  });

  it("opens an author search with restored route state", async () => {
    renderPage();
    await screen.findByText("Author A + Author B + Author C");

    const row = screen.getByText("Author A + Author B + Author C").closest("tr");
    fireEvent.click(within(row).getByRole("button", { name: "Open" }));

    const probe = await screen.findByTestId("location-state");
    const state = JSON.parse(probe.textContent);
    expect(state.pathname).toBe("/analyze/authors");
    expect(state.state.originalAuthors).toHaveLength(3);
    expect(state.state.activeAuthors.map((author) => author.canonical_author_id)).toEqual([
      "c1",
      "c3",
    ]);
    expect(state.state.excludedWorkIds).toEqual(["W1", "W2"]);
    expect(state.state.filters.from_year).toBe(2020);
  });

  it("renames with an empty custom name", async () => {
    renderPage();
    await screen.findByText("Author A + Author B + Author C");
    const row = screen.getByText("Author A + Author B + Author C").closest("tr");
    fireEvent.click(within(row).getByRole("button", { name: "Rename" }));

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(savedSearchesApi.patchSavedSearch).toHaveBeenCalledWith("author-1", {
        display_name: "",
      });
    });
    expect(await screen.findByText("Renamed")).toBeInTheDocument();
  });

  it("edits authors and surfaces duplicate conflicts", async () => {
    savedSearchesApi.patchSavedSearch.mockRejectedValueOnce({
      response: { data: { detail: "A saved search with this configuration already exists." } },
    });
    renderPage();
    await screen.findByText("Author A + Author B + Author C");
    const row = screen.getByText("Author A + Author B + Author C").closest("tr");
    fireEvent.click(within(row).getByRole("button", { name: "Edit" }));

    expect(await screen.findByText("Edit saved search")).toBeInTheDocument();
    expect(screen.getByLabelText("Add author search")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(
      await screen.findByText("A saved search with this configuration already exists."),
    ).toBeInTheDocument();
  });

  it("confirms delete and removes the row", async () => {
    renderPage();
    await screen.findByText("Author A + Author B + Author C");
    const row = screen.getByText("Author A + Author B + Author C").closest("tr");
    fireEvent.click(within(row).getByRole("button", { name: "Delete" }));
    expect(screen.getByText("Delete saved search?")).toBeInTheDocument();
    fireEvent.click(screen.getAllByText("Delete").at(-1));

    await waitFor(() => {
      expect(savedSearchesApi.deleteSavedSearch).toHaveBeenCalledWith("author-1");
    });
    expect(screen.queryByText("Author A + Author B + Author C")).not.toBeInTheDocument();
  });

  it("starts a data update for a specific saved search", async () => {
    renderPage();
    await screen.findByText("Author A + Author B + Author C");
    const row = screen.getByText("Author A + Author B + Author C").closest("tr");
    fireEvent.click(within(row).getByRole("button", { name: "Update data" }));

    await waitFor(() => {
      expect(dataUpdaterApi.startSavedSearchDataUpdate).toHaveBeenCalledWith("author-1");
    });
    expect(await screen.findByText(/Updating data for/)).toBeInTheDocument();
    expect(window.localStorage.setItem).toHaveBeenCalledWith(
      "researchIntelligence.dataUpdater.currentJobId",
      "job-1",
    );
  });

  it("shows empty and retry states", async () => {
    savedSearchesApi.fetchSavedSearches.mockRejectedValueOnce({
      response: { data: { detail: "API failed" } },
    });
    renderPage();

    expect(await screen.findByText("API failed")).toBeInTheDocument();
    savedSearchesApi.fetchSavedSearches.mockResolvedValueOnce([]);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("No saved author searches yet.")).toBeInTheDocument();
  });
});
