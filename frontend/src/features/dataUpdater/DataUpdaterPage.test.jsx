import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ThemeProvider, createTheme } from "@mui/material/styles";

import DataUpdaterPage from "./DataUpdaterPage";
import * as dataUpdaterApi from "./dataUpdaterApi";

const theme = createTheme({ colorSchemes: { light: true, dark: true } });

const SAVED_SEARCHES = [
  {
    id: "saved-1",
    name: "Quantum Error Correction Researchers",
    search_type: "authors",
    updated_at: "2026-08-01T12:00:00Z",
  },
];

const TARGETS = [
  {
    id: "author-1",
    type: "author",
    title: "John Preskill",
    subtitle: "Author · Caltech",
    last_updated: "2026-08-03T12:00:00Z",
  },
];

const JOB = {
  id: "job-1",
  mode: "saved_search",
  dataset: null,
  status: "running",
  current_dataset: "authors",
  total_records: 421,
  processed_records: 286,
  updated_count: 63,
  unchanged_count: 215,
  retrying_count: 3,
  failed_count: 0,
  metadata: {
    title: "Updating Quantum Error Correction Researchers",
    record_ids_by_dataset: {
      authors: Array.from({ length: 24 }, (_item, index) => `author-${index}`),
      publications: Array.from({ length: 290 }, (_item, index) => `work-${index}`),
    },
  },
  records: [
    ...Array.from({ length: 18 }, (_item, index) => ({
      id: `author-record-${index}`,
      dataset: "authors",
      status: "unchanged",
    })),
    ...Array.from({ length: 214 }, (_item, index) => ({
      id: `work-record-${index}`,
      dataset: "publications",
      status: "updated",
    })),
  ],
};

function renderPage() {
  return render(
    <ThemeProvider theme={theme}>
      <MemoryRouter initialEntries={["/data-updater"]}>
        <Routes>
          <Route path="/data-updater" element={<DataUpdaterPage />} />
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

describe("DataUpdaterPage", () => {
  beforeEach(() => {
    installLocalStorageStub();
    window.localStorage.clear();
    vi.spyOn(dataUpdaterApi, "fetchDataUpdaterSavedSearches").mockResolvedValue(
      SAVED_SEARCHES,
    );
    vi.spyOn(dataUpdaterApi, "searchDataUpdateTargets").mockResolvedValue(TARGETS);
    vi.spyOn(dataUpdaterApi, "startDataUpdate").mockResolvedValue(JOB);
    vi.spyOn(dataUpdaterApi, "startSavedSearchDataUpdate").mockResolvedValue(JOB);
    vi.spyOn(dataUpdaterApi, "startAllSavedSearchesDataUpdate").mockResolvedValue(JOB);
    vi.spyOn(dataUpdaterApi, "startEntityDataUpdate").mockResolvedValue(JOB);
    vi.spyOn(dataUpdaterApi, "fetchDataUpdateJob").mockResolvedValue(JOB);
    vi.spyOn(dataUpdaterApi, "pauseDataUpdateJob").mockResolvedValue({
      ...JOB,
      status: "paused",
    });
    vi.spyOn(dataUpdaterApi, "resumeDataUpdateJob").mockResolvedValue({
      ...JOB,
      status: "queued",
    });
    vi.spyOn(dataUpdaterApi, "cancelDataUpdateJob").mockResolvedValue({
      ...JOB,
      status: "cancelled",
    });
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("starts an all-data stale refresh", async () => {
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Update All Data" }));

    await waitFor(() => {
      expect(dataUpdaterApi.startDataUpdate).toHaveBeenCalledWith({
        mode: "all_stale",
        stale_only: true,
      });
    });
    expect(await screen.findByTestId("data-update-progress")).toHaveTextContent(
      "286 / 421 items checked",
    );
  });

  it("updates one saved search and all saved searches", async () => {
    renderPage();

    expect(
      await screen.findByText("Quantum Error Correction Researchers"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Update This Saved Search" }));
    await waitFor(() => {
      expect(dataUpdaterApi.startSavedSearchDataUpdate).toHaveBeenCalledWith("saved-1");
    });

    fireEvent.click(screen.getByRole("button", { name: "Update All Saved Searches" }));
    await waitFor(() => {
      expect(dataUpdaterApi.startAllSavedSearchesDataUpdate).toHaveBeenCalled();
    });
  });

  it("searches human-readable targets and updates the selected item", async () => {
    renderPage();

    const searchInput = screen.getByLabelText(
      "Search authors, publications, or institutions",
    );
    fireEvent.focus(searchInput);
    fireEvent.change(searchInput, { target: { value: "John" } });
    await waitFor(() => {
      expect(dataUpdaterApi.searchDataUpdateTargets).toHaveBeenCalledWith(
        "John",
        expect.any(Object),
      );
    });
    fireEvent.keyDown(searchInput, { key: "ArrowDown" });

    const option = await screen.findByText("John Preskill");
    fireEvent.click(option);
    fireEvent.click(screen.getByRole("button", { name: "Update" }));

    await waitFor(() => {
      expect(dataUpdaterApi.startEntityDataUpdate).toHaveBeenCalledWith({
        type: "author",
        id: "author-1",
        stale_only: false,
      });
    });
  });

  it("shows simple progress and supports pause, resume, and cancel", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Update All Data" }));

    const progress = await screen.findByTestId("data-update-progress");
    expect(progress).toHaveTextContent("68%");
    expect(progress).toHaveTextContent("Authors: 18 / 24");
    expect(progress).toHaveTextContent("Publications: 214 / 290");
    expect(progress).toHaveTextContent("Updated: 63");

    fireEvent.click(within(progress).getByRole("button", { name: "Pause" }));
    await waitFor(() => {
      expect(dataUpdaterApi.pauseDataUpdateJob).toHaveBeenCalledWith("job-1");
    });

    fireEvent.click(await screen.findByRole("button", { name: "Resume" }));
    await waitFor(() => {
      expect(dataUpdaterApi.resumeDataUpdateJob).toHaveBeenCalledWith("job-1");
    });

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(dataUpdaterApi.cancelDataUpdateJob).toHaveBeenCalledWith("job-1");
    });
  });

  it("restores an unfinished update after leaving and returning to the page", async () => {
    const firstRender = renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Update All Data" }));

    await waitFor(() => {
      expect(dataUpdaterApi.startDataUpdate).toHaveBeenCalled();
    });
    firstRender.unmount();

    renderPage();

    const progress = await screen.findByTestId("data-update-progress");
    expect(dataUpdaterApi.fetchDataUpdateJob).toHaveBeenCalledWith(
      "job-1",
      expect.any(Object),
    );
    expect(progress).toHaveTextContent("Updating Quantum Error Correction Researchers");
    expect(progress).toHaveTextContent("286 / 421 items checked");
  });
});
