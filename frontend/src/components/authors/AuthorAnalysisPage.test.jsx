import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ThemeProvider, createTheme } from "@mui/material/styles";

import AuthorAnalysisPage from "./AuthorAnalysisPage";
import { clearPublicationsPageCache } from "./authorAnalysisCache";
import * as analysisApi from "../../api/analysisApi";
import * as savedSearchesApi from "../../features/savedSearches/savedSearchesApi";
import * as publicationStatsRequest from "./publicationStatsRequest";
import { FILTER_DEBOUNCE_MS } from "./authorAnalysisPageLogic";

vi.mock("react-apexcharts", () => ({
  default: ({ options }) => (
    <div
      data-testid="apex-chart-mock"
      data-categories={JSON.stringify(options?.xaxis?.categories || [])}
    />
  ),
}));

const theme = createTheme({ colorSchemes: { light: true, dark: true } });

const AUTHORS = [
  {
    canonical_author_id: "c1",
    provider: "openalex",
    provider_author_id: "A1",
    display_name: "John Smith",
  },
  {
    canonical_author_id: "c2",
    provider: "openalex",
    provider_author_id: "A2",
    display_name: "Jane Doe",
  },
];

function renderPage() {
  return render(
    <ThemeProvider theme={theme}>
      <MemoryRouter
        initialEntries={[{ pathname: "/analyze/authors", state: { authors: AUTHORS } }]}
      >
        <Routes>
          <Route path="/analyze/authors" element={<AuthorAnalysisPage />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

class IntersectionObserverStub {
  constructor(callback) {
    this.callback = callback;
  }

  observe() {}

  disconnect() {}

  unobserve() {}
}

describe("AuthorAnalysisPage", () => {
  beforeEach(() => {
    clearPublicationsPageCache();
    vi.stubGlobal("IntersectionObserver", IntersectionObserverStub);
    vi.spyOn(analysisApi, "fetchAuthorPublications").mockResolvedValue({
      mode: "common_publications",
      authors: AUTHORS,
      items: [{ id: "w1", title: "Paper", analysis_match: { verified: true, method: "x" } }],
      timeline: {
        interval: "year",
        total_dated_publications: 1,
        total_matching_publications: 1,
        items: [{ period: "2024", label: "2024", count: 1 }],
      },
      facets: {
        sources: [{ value: "openalex", label: "OpenAlex", count: 1 }],
        venues: [{ value: "nature medicine", label: "Nature Medicine", count: 1 }],
        grants: [],
      },
      next_cursor: null,
      has_more: false,
      unsupported: false,
      unsupported_reason: null,
    });
    const completedStatsJob = {
      job_id: "stats-1",
      status: "completed",
      progress_stage: "Completed",
      progress_percent: 100,
      result: {
        mode: "common_publications",
        corpus_complete: true,
        total_matching_publications: 1037,
        total_corpus_publications: 1037,
        timeline: {
          interval: "year",
          total_dated_publications: 1037,
          total_matching_publications: 1037,
          items: [{ period: "2024", label: "2024", count: 1037 }],
        },
        facets: {
          sources: [{ value: "openalex", label: "OpenAlex", count: 1037 }],
          institutions: [],
          venues: [{ value: "nature medicine", label: "Nature Medicine", count: 500 }],
          grants: [],
          authors: [],
        },
      },
    };
    vi.spyOn(analysisApi, "createAuthorPublicationStatsJob").mockResolvedValue(
      completedStatsJob,
    );
    vi.spyOn(analysisApi, "getAuthorPublicationStatsJob").mockResolvedValue(
      completedStatsJob,
    );
    vi.spyOn(publicationStatsRequest, "fetchAuthorPublicationCorpusStats").mockImplementation(
      async ({ authors, onProgress }) => {
        const authorCount = (authors || []).length;
        const result =
          authorCount === 1
            ? {
                mode: "single_author",
                corpus_complete: true,
                total_matching_publications: 2,
                timeline: {
                  interval: "year",
                  total_dated_publications: 2,
                  total_matching_publications: 2,
                  items: [
                    { period: "2022", label: "2022", count: 1 },
                    { period: "2023", label: "2023", count: 2 },
                  ],
                },
                facets: {
                  sources: [{ value: "openalex", label: "OpenAlex", count: 2 }],
                  institutions: [],
                  venues: [],
                  grants: [],
                  authors: [],
                },
              }
            : {
                ...completedStatsJob.result,
              };
        onProgress?.({
          status: "completed",
          progress_stage: "Completed",
          progress_percent: 100,
          result,
        });
        return result;
      },
    );
    vi.spyOn(savedSearchesApi, "saveSavedSearch").mockResolvedValue({ id: "saved-1" });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    clearPublicationsPageCache();
  });

  it("renders all authors checked initially and fetches with every author", async () => {
    renderPage();

    expect(screen.getByLabelText("John Smith")).toBeChecked();
    expect(screen.getByLabelText("Jane Doe")).toBeChecked();

    await waitFor(() => {
      expect(analysisApi.fetchAuthorPublications).toHaveBeenCalled();
    });

    const firstCall = analysisApi.fetchAuthorPublications.mock.calls[0][0];
    expect(firstCall.authors).toHaveLength(2);
    expect(firstCall.originalAuthorIds).toEqual(["c1", "c2"]);
  });

  it("saves the current author search definition", async () => {
    renderPage();
    await waitFor(() => expect(analysisApi.fetchAuthorPublications).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "Save search" }));

    await waitFor(() => {
      expect(savedSearchesApi.saveSavedSearch).toHaveBeenCalledWith(
        expect.objectContaining({
          search_type: "authors",
          payload: expect.objectContaining({
            authors: expect.arrayContaining([
              expect.objectContaining({
                canonical_author_id: "c1",
                display_name: "John Smith",
              }),
            ]),
            active_author_ids: ["c1", "c2"],
            filters: {},
            excluded_work_ids: [],
          }),
        }),
      );
    });
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("saves only currently checked authors when an author is unchecked", async () => {
    renderPage();
    await waitFor(() => expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByLabelText("Jane Doe"));
    await sleep(FILTER_DEBOUNCE_MS + 50);
    await waitFor(() =>
      expect(analysisApi.fetchAuthorPublications.mock.calls.length).toBeGreaterThan(1),
    );

    fireEvent.click(screen.getByRole("button", { name: "Save search" }));

    await waitFor(() => {
      expect(savedSearchesApi.saveSavedSearch).toHaveBeenCalled();
    });
    const payload = savedSearchesApi.saveSavedSearch.mock.calls.at(-1)[0].payload;
    expect(payload.authors).toEqual([
      expect.objectContaining({
        canonical_author_id: "c1",
        display_name: "John Smith",
      }),
    ]);
    expect(payload.active_author_ids).toEqual(["c1"]);
    expect(payload.authors).not.toEqual(
      expect.arrayContaining([
        expect.objectContaining({ canonical_author_id: "c2" }),
      ]),
    );
  });

  it("refetches with only active authors when one is unchecked", async () => {
    renderPage();
    await waitFor(() => expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByLabelText("Jane Doe"));
    await sleep(FILTER_DEBOUNCE_MS + 50);

    await waitFor(() =>
      expect(analysisApi.fetchAuthorPublications.mock.calls.length).toBeGreaterThan(1),
    );

    const lastCall =
      analysisApi.fetchAuthorPublications.mock.calls[
        analysisApi.fetchAuthorPublications.mock.calls.length - 1
      ][0];
    expect(lastCall.authors).toHaveLength(1);
    expect(lastCall.authors[0].canonical_author_id).toBe("c1");
  });

  it("does not apply stale responses when a newer request supersedes an older one", async () => {
    let resolveFirst;
    let resolveSecond;
    const firstPromise = new Promise((resolve) => {
      resolveFirst = resolve;
    });
    const secondPromise = new Promise((resolve) => {
      resolveSecond = resolve;
    });

    analysisApi.fetchAuthorPublications
      .mockImplementationOnce(() => firstPromise)
      .mockImplementationOnce(() => secondPromise);

    renderPage();
    await waitFor(() =>
      expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(1),
    );

    fireEvent.click(screen.getByLabelText("Jane Doe"));
    await sleep(FILTER_DEBOUNCE_MS + 50);
    await waitFor(() =>
      expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(2),
    );

    resolveSecond({
      mode: "single_author",
      authors: [AUTHORS[0]],
      items: [{ id: "new", title: "Fresh Paper", analysis_match: { verified: true, method: "x" } }],
      next_cursor: null,
      has_more: false,
      unsupported: false,
      unsupported_reason: null,
    });

    await waitFor(() => expect(screen.getByText("Fresh Paper")).toBeInTheDocument());

    resolveFirst({
      mode: "common_publications",
      authors: AUTHORS,
      items: [{ id: "stale", title: "Stale Paper", analysis_match: { verified: true, method: "x" } }],
      next_cursor: null,
      has_more: false,
      unsupported: false,
      unsupported_reason: null,
    });

    await sleep(50);
    expect(screen.queryByText("Stale Paper")).not.toBeInTheDocument();
    expect(screen.getByText("Fresh Paper")).toBeInTheDocument();
  });

  it("renders publication trends chart from timeline on initial load", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Common publications over time")).toBeInTheDocument();
    });
    expect(await screen.findByTestId("author-publication-trend-chart")).toBeInTheDocument();
    expect(
      await screen.findByText("Timeline based on all 1,037 publications"),
    ).toBeInTheDocument();
  });

  it("refreshes chart when checkbox selection changes", async () => {
    analysisApi.fetchAuthorPublications.mockImplementation(async ({ authors }) => {
      if ((authors || []).length === 1) {
        return {
          mode: "single_author",
          authors: [AUTHORS[0]],
          items: [
            {
              id: "w2",
              title: "Solo Paper",
              analysis_match: { verified: true, method: "x" },
            },
          ],
          next_cursor: null,
          has_more: false,
          unsupported: false,
          unsupported_reason: null,
        };
      }
      return {
        mode: "common_publications",
        authors: AUTHORS,
        items: [{ id: "w1", title: "Paper", analysis_match: { verified: true, method: "x" } }],
        next_cursor: null,
        has_more: false,
        unsupported: false,
        unsupported_reason: null,
      };
    });

    renderPage();
    await waitFor(() => expect(screen.getByText("Common publications over time")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByTestId("apex-chart-mock")).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText("Jane Doe"));
    await sleep(FILTER_DEBOUNCE_MS + 50);

    await waitFor(() => expect(screen.getByText("Solo Paper")).toBeInTheDocument());
    await waitFor(() => {
      expect(screen.getByText("Publications over time")).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(publicationStatsRequest.fetchAuthorPublicationCorpusStats).toHaveBeenCalledWith(
        expect.objectContaining({
          authors: [expect.objectContaining({ canonical_author_id: "c1" })],
        }),
      );
    });
  });

  it("keeps the publication table usable when corpus stats sync fails", async () => {
    publicationStatsRequest.fetchAuthorPublicationCorpusStats.mockRejectedValue(
      new Error(
        "Complete publication statistics are unavailable because coverage sync did not finish.",
      ),
    );

    renderPage();
    await waitFor(() => expect(screen.getByText("Paper")).toBeInTheDocument());
    expect(
      await screen.findByText(
        /Complete publication statistics are unavailable because coverage sync did not finish/i,
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByText(/Based on the first/i)).not.toBeInTheDocument();
  });

  it("does not refetch timeline when loading additional table pages", async () => {
    let observerCallback;
    class MockIntersectionObserver extends IntersectionObserverStub {
      constructor(callback) {
        super(callback);
        observerCallback = callback;
      }
    }
    vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);

    analysisApi.fetchAuthorPublications.mockResolvedValue({
      mode: "common_publications",
      authors: AUTHORS,
      items: [{ id: "w1", title: "Paper", analysis_match: { verified: true, method: "x" } }],
        timeline: {
          interval: "year",
          total_dated_publications: 20,
          total_matching_publications: 20,
          items: [{ period: "2024", label: "2024", count: 20 }],
        },
      provider_total_count: 1037,
      next_cursor: "cursor-2",
      has_more: true,
      unsupported: false,
      unsupported_reason: null,
    });

    renderPage();
    await waitFor(() => expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByText("Timeline based on all 1,037 publications"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/Filter options and counts are from all 1,?037 publications/i),
    ).toBeInTheDocument();
    expect(publicationStatsRequest.fetchAuthorPublicationCorpusStats).toHaveBeenCalled();

    analysisApi.fetchAuthorPublications.mockResolvedValueOnce({
      mode: "common_publications",
      authors: AUTHORS,
      items: [{ id: "w2", title: "Second Paper", analysis_match: { verified: true, method: "x" } }],
      timeline: {
        interval: "year",
        total_dated_publications: 8,
        total_matching_publications: 8,
        items: [{ period: "2010", label: "2010", count: 8 }],
      },
      provider_total_count: 50,
      next_cursor: null,
      has_more: false,
      unsupported: false,
      unsupported_reason: null,
    });

    if (observerCallback) {
      observerCallback([{ isIntersecting: true }]);
    }

    await waitFor(() =>
      expect(analysisApi.fetchAuthorPublications.mock.calls.length).toBeGreaterThan(1),
    );

    const categories = JSON.parse(
      screen.getByTestId("apex-chart-mock").getAttribute("data-categories"),
    );
    expect(categories).toEqual(["2024"]);
    expect(
      screen.getByText("Timeline based on all 1,037 publications"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Timeline based on 8 of 50 publications")).not.toBeInTheDocument();
    expect(await screen.findByText("Second Paper")).toBeInTheDocument();
    expect(screen.getByText("Paper")).toBeInTheDocument();
  });

  it("keeps chart visible when the table is empty", async () => {
    analysisApi.fetchAuthorPublications.mockResolvedValue({
      mode: "common_publications",
      authors: AUTHORS,
      items: [],
      timeline: {
        interval: "year",
        total_dated_publications: 1,
        total_matching_publications: 1,
        items: [{ period: "2020", label: "2020", count: 1 }],
      },
      next_cursor: null,
      has_more: false,
      unsupported: false,
      unsupported_reason: null,
    });

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Common publications over time")).toBeInTheDocument();
    });
    expect(await screen.findByTestId("author-publication-trend-chart")).toBeInTheDocument();
    expect(screen.getByText(/No common publications found/i)).toBeInTheDocument();
  });

  it("does not request the next page while a load-more request is in flight", async () => {
    let observerCallback;
    class MockIntersectionObserver extends IntersectionObserverStub {
      constructor(callback) {
        super(callback);
        observerCallback = callback;
      }
    }
    vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);

    let resolveSecond;
    const secondPromise = new Promise((resolve) => {
      resolveSecond = resolve;
    });

    analysisApi.fetchAuthorPublications
      .mockResolvedValueOnce({
        mode: "common_publications",
        authors: AUTHORS,
        items: [{ id: "w1", title: "Paper", analysis_match: { verified: true, method: "x" } }],
        timeline: {
          interval: "year",
          total_dated_publications: 2,
          total_matching_publications: 2,
          items: [{ period: "2024", label: "2024", count: 1 }],
        },
        next_cursor: "page-2",
        has_more: true,
        unsupported: false,
        unsupported_reason: null,
      })
      .mockImplementationOnce(() => secondPromise);

    renderPage();
    await waitFor(() => expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(1));

    observerCallback([{ isIntersecting: true }]);
    observerCallback([{ isIntersecting: true }]);
    await waitFor(() => expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(2));

    resolveSecond({
      mode: "common_publications",
      authors: AUTHORS,
      items: [{ id: "w2", title: "Second Paper", analysis_match: { verified: true, method: "x" } }],
      timeline: null,
      next_cursor: null,
      has_more: false,
      unsupported: false,
      unsupported_reason: null,
    });

    await waitFor(() => expect(screen.getByText("Second Paper")).toBeInTheDocument());
    expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(2);
  });

  it("resets pagination when active authors change", async () => {
    analysisApi.fetchAuthorPublications
      .mockResolvedValueOnce({
        mode: "common_publications",
        authors: AUTHORS,
        items: [{ id: "w1", title: "Paper", analysis_match: { verified: true, method: "x" } }],
        timeline: {
          interval: "year",
          total_dated_publications: 1,
          total_matching_publications: 1,
          items: [{ period: "2024", label: "2024", count: 1 }],
        },
        next_cursor: "page-2",
        has_more: true,
        unsupported: false,
        unsupported_reason: null,
      })
      .mockResolvedValueOnce({
        mode: "single_author",
        authors: [AUTHORS[0]],
        items: [{ id: "solo", title: "Solo Paper", analysis_match: { verified: true, method: "x" } }],
        timeline: {
          interval: "year",
          total_dated_publications: 1,
          total_matching_publications: 1,
          items: [{ period: "2023", label: "2023", count: 1 }],
        },
        next_cursor: null,
        has_more: false,
        unsupported: false,
        unsupported_reason: null,
      });

    renderPage();
    await waitFor(() => expect(screen.getByText("Paper")).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText("Jane Doe"));
    await sleep(FILTER_DEBOUNCE_MS + 50);

    await waitFor(() => expect(screen.getByText("Solo Paper")).toBeInTheDocument());
    const lastCall =
      analysisApi.fetchAuthorPublications.mock.calls[
        analysisApi.fetchAuthorPublications.mock.calls.length - 1
      ][0];
    expect(lastCall.cursor).toBeNull();
    expect(lastCall.authors).toHaveLength(1);
  });

  it("does not refetch when draft year filters change until Apply", async () => {
    renderPage();
    await waitFor(() => expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    fireEvent.change(screen.getByLabelText("From year"), { target: { value: "2020" } });
    fireEvent.change(screen.getByLabelText("To year"), { target: { value: "2024" } });
    await sleep(FILTER_DEBOUNCE_MS + 50);

    expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Apply filters" })).toBeEnabled();
  });

  it("applies filters with exactly one main refresh", async () => {
    renderPage();
    await waitFor(() => expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    fireEvent.change(screen.getByLabelText("From year"), { target: { value: "2020" } });
    fireEvent.change(screen.getByLabelText("To year"), { target: { value: "2024" } });

    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));

    await waitFor(() =>
      expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(2),
    );

    const lastCall =
      analysisApi.fetchAuthorPublications.mock.calls[
        analysisApi.fetchAuthorPublications.mock.calls.length - 1
      ][0];
    expect(lastCall.cursor).toBeNull();
    expect(lastCall.filters).toEqual({
      from_year: 2020,
      to_year: 2024,
    });
    expect(screen.getByText("2020–2024")).toBeInTheDocument();
  });

  it("disables Apply for an invalid year range", async () => {
    renderPage();
    await waitFor(() => expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    fireEvent.change(screen.getByLabelText("From year"), { target: { value: "2024" } });
    fireEvent.change(screen.getByLabelText("To year"), { target: { value: "2020" } });

    expect(screen.getByRole("button", { name: "Apply filters" })).toBeDisabled();
    expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(1);
  });

  it("resets filters with one unfiltered refresh", async () => {
    renderPage();
    await waitFor(() => expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    fireEvent.change(screen.getByLabelText("From year"), { target: { value: "2020" } });
    fireEvent.change(screen.getByLabelText("To year"), { target: { value: "2024" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Reset" })).not.toBeDisabled(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    await waitFor(() => expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(3));

    const lastCall =
      analysisApi.fetchAuthorPublications.mock.calls[
        analysisApi.fetchAuthorPublications.mock.calls.length - 1
      ][0];
    expect(lastCall.filters == null || Object.keys(lastCall.filters || {}).length === 0).toBe(
      true,
    );
  });

  it("enables Download CSV after results load and exports applied filters only", async () => {
    const exportSpy = vi.spyOn(analysisApi, "exportAuthorPublicationsCsv").mockResolvedValue({
      data: new Blob(["a,b\n"]),
      headers: {
        "content-disposition": 'attachment; filename="author-publications-jane-doe-2026-08-04.csv"',
      },
    });
    const createObjectURL = vi.fn(() => "blob:mock");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });

    renderPage();
    await waitFor(() => expect(screen.getByTestId("download-csv-button")).toBeEnabled());

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    fireEvent.change(screen.getByLabelText("From year"), { target: { value: "2020" } });
    fireEvent.change(screen.getByLabelText("To year"), { target: { value: "2024" } });
    // Draft change should not be used until Apply.
    fireEvent.click(screen.getByTestId("download-csv-button"));

    await waitFor(() => expect(exportSpy).toHaveBeenCalledTimes(1));
    expect(exportSpy.mock.calls[0][0].filters == null || Object.keys(exportSpy.mock.calls[0][0].filters || {}).length === 0).toBe(
      true,
    );

    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByTestId("download-csv-button"));
    await waitFor(() => expect(exportSpy).toHaveBeenCalledTimes(2));
    expect(exportSpy.mock.calls[1][0].filters).toEqual({
      from_year: 2020,
      to_year: 2024,
    });
    expect(exportSpy.mock.calls[1][0].authors).toHaveLength(2);
  });

  it("disables Download CSV when there are zero matching publications", async () => {
    analysisApi.fetchAuthorPublications.mockResolvedValueOnce({
      mode: "common_publications",
      authors: AUTHORS,
      items: [],
      timeline: null,
      facets: { sources: [], venues: [], grants: [] },
      next_cursor: null,
      has_more: false,
      unsupported: false,
      unsupported_reason: null,
    });
    renderPage();
    await waitFor(() => expect(screen.getByTestId("download-csv-button")).toBeDisabled());
  });
});
