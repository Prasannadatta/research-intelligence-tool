import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
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

function publicationsPayload(overrides = {}) {
  return {
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
    pagination: {
      page: 1,
      total: 1,
      has_more: false,
      next_cursor: null,
      corpus_source: null,
    },
    next_cursor: null,
    has_more: false,
    unsupported: false,
    unsupported_reason: null,
    ...overrides,
  };
}

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

async function waitForSettledFetchCount(minCount = 1) {
  await waitFor(() =>
    expect(analysisApi.fetchAuthorPublications.mock.calls.length).toBeGreaterThanOrEqual(minCount),
  );
  // Allow any corpus-rebind fetch triggered by corpus_complete to settle.
  await waitFor(() => {
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  }).catch(() => {});
  return analysisApi.fetchAuthorPublications.mock.calls.length;
}

describe("AuthorAnalysisPage", () => {
  beforeEach(() => {
    clearPublicationsPageCache();
    vi.spyOn(analysisApi, "fetchAuthorPublications").mockResolvedValue(publicationsPayload());
    const incompleteStatsJob = {
      job_id: "stats-1",
      status: "completed",
      progress_stage: "Completed",
      progress_percent: 100,
      result: {
        mode: "common_publications",
        corpus_complete: false,
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
      incompleteStatsJob,
    );
    vi.spyOn(analysisApi, "getAuthorPublicationStatsJob").mockResolvedValue(
      incompleteStatsJob,
    );
    vi.spyOn(publicationStatsRequest, "fetchAuthorPublicationCorpusStats").mockImplementation(
      async ({ authors, onProgress }) => {
        const authorCount = (authors || []).length;
        const result =
          authorCount === 1
            ? {
                mode: "single_author",
                corpus_complete: false,
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
                ...incompleteStatsJob.result,
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
    clearPublicationsPageCache();
  });

  function mockCompleteCorpusStats() {
    const completedResult = {
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
    };
    publicationStatsRequest.fetchAuthorPublicationCorpusStats.mockImplementation(
      async ({ onProgress }) => {
        onProgress?.({
          status: "completed",
          progress_stage: "Completed",
          progress_percent: 100,
          result: completedResult,
        });
        return completedResult;
      },
    );
    return completedResult;
  }

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
    const pendingByAuthorCount = {
      2: firstPromise,
      1: secondPromise,
    };
    const resolvedByAuthorCount = {};

    analysisApi.fetchAuthorPublications.mockImplementation(({ authors }) => {
      const authorCount = (authors || []).length;
      if (resolvedByAuthorCount[authorCount]) {
        return Promise.resolve(resolvedByAuthorCount[authorCount]);
      }
      return pendingByAuthorCount[authorCount];
    });

    renderPage();
    await waitFor(() =>
      expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(1),
    );

    fireEvent.click(screen.getByLabelText("Jane Doe"));
    await sleep(FILTER_DEBOUNCE_MS + 50);
    await waitFor(() =>
      expect(analysisApi.fetchAuthorPublications.mock.calls.length).toBeGreaterThanOrEqual(2),
    );

    const freshPayload = publicationsPayload({
      mode: "single_author",
      authors: [AUTHORS[0]],
      items: [{ id: "new", title: "Fresh Paper", analysis_match: { verified: true, method: "x" } }],
      timeline: null,
      facets: { sources: [], venues: [], grants: [] },
    });
    resolvedByAuthorCount[1] = freshPayload;
    resolveSecond(freshPayload);

    await waitFor(() => expect(screen.getByText("Fresh Paper")).toBeInTheDocument());

    const stalePayload = publicationsPayload({
      items: [{ id: "stale", title: "Stale Paper", analysis_match: { verified: true, method: "x" } }],
      timeline: null,
    });
    resolvedByAuthorCount[2] = stalePayload;
    resolveFirst(stalePayload);

    await sleep(50);
    expect(screen.queryByText("Stale Paper")).not.toBeInTheDocument();
    expect(screen.getByText("Fresh Paper")).toBeInTheDocument();
  });

  it("renders publication trends chart from timeline on initial load", async () => {
    mockCompleteCorpusStats();
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
        return publicationsPayload({
          mode: "single_author",
          authors: [AUTHORS[0]],
          items: [
            {
              id: "w2",
              title: "Solo Paper",
              analysis_match: { verified: true, method: "x" },
            },
          ],
          timeline: null,
          facets: { sources: [], venues: [], grants: [] },
        });
      }
      return publicationsPayload({
        timeline: null,
        facets: { sources: [], venues: [], grants: [] },
      });
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
      await screen.findAllByText(
        /Complete publication statistics are unavailable because coverage sync did not finish/i,
      ),
    ).not.toHaveLength(0);
    expect(screen.getAllByRole("button", { name: "Retry" }).length).toBeGreaterThan(0);
    expect(screen.queryByText(/Based on the first/i)).not.toBeInTheDocument();
  });

  it("shows a rate-limit warning without labeling stats complete", async () => {
    const rateLimitError = new Error(
      "OpenAlex rate limit reached. Your existing data is safe; please try again shortly.",
    );
    rateLimitError.statsJob = {
      status: "failed",
      progress_detail: { rate_limited: true, provider: "openalex", corpus_complete: false },
    };
    publicationStatsRequest.fetchAuthorPublicationCorpusStats.mockRejectedValue(
      rateLimitError,
    );

    renderPage();
    await waitFor(() => expect(screen.getByText("Paper")).toBeInTheDocument());
    expect(await screen.findByTestId("publication-corpus-status")).toBeInTheDocument();
    expect(screen.getByText("Rate limited")).toBeInTheDocument();
    expect(
      screen.getAllByText(/OpenAlex rate limit reached\. Your existing data is safe/i).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByTestId("publication-stats-ready-snackbar")).not.toBeInTheDocument();
  });

  it("keeps primary page actions in the top action area", async () => {
    renderPage();
    const actions = await screen.findByTestId("author-analysis-page-actions");
    expect(within(actions).getByTestId("download-csv-button")).toBeInTheDocument();
    expect(within(actions).getByRole("button", { name: "Save search" })).toBeInTheDocument();
    expect(within(actions).getByTestId("open-author-insights")).toBeInTheDocument();
  });

  it("explains provider-record deduplication near the publication count", async () => {
    analysisApi.fetchAuthorPublications.mockResolvedValue(
      publicationsPayload({
        provider_total_count: 107,
        pagination: {
          page: 1,
          total: 97,
          has_more: true,
          next_cursor: "cursor-2",
          corpus_source: null,
        },
        next_cursor: "cursor-2",
        has_more: true,
      }),
    );

    renderPage();
    expect(await screen.findByTestId("publications-dedup-caption")).toHaveTextContent(
      "97 unique publications from 107 OpenAlex records",
    );
    expect(screen.getByTestId("publications-range-label")).toHaveTextContent(
      /Showing 1–1 of 97 unique publications/,
    );
  });

  it("does not refetch timeline when changing table pages", async () => {
    mockCompleteCorpusStats();
    analysisApi.fetchAuthorPublications.mockImplementation(async ({ page = 1 }) => {
      if (page === 2) {
        return publicationsPayload({
          items: [
            { id: "w2", title: "Second Paper", analysis_match: { verified: true, method: "x" } },
          ],
          timeline: {
            interval: "year",
            total_dated_publications: 8,
            total_matching_publications: 8,
            items: [{ period: "2010", label: "2010", count: 8 }],
          },
          provider_total_count: 50,
          pagination: {
            page: 2,
            total: 1037,
            has_more: true,
            next_cursor: "page-3",
            corpus_source: "stored",
          },
          next_cursor: "page-3",
          has_more: true,
        });
      }
      return publicationsPayload({
        provider_total_count: 1037,
        pagination: {
          page: 1,
          total: 1037,
          has_more: true,
          next_cursor: "cursor-2",
          corpus_source: "stored",
        },
        next_cursor: "cursor-2",
        has_more: true,
      });
    });

    renderPage();
    expect(
      await screen.findByText("Timeline based on all 1,037 publications"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/Filter options and counts are from all 1,?037 publications/i),
    ).toBeInTheDocument();
    expect(publicationStatsRequest.fetchAuthorPublicationCorpusStats).toHaveBeenCalled();

    // Initial load + optional stored-corpus rebind after corpus_complete.
    await waitFor(() =>
      expect(analysisApi.fetchAuthorPublications.mock.calls.length).toBeGreaterThanOrEqual(2),
    );

    const pagination = await screen.findByTestId("publications-pagination");
    await waitFor(() => {
      expect(
        within(pagination).getByRole("button", { name: "Go to page 2" }),
      ).not.toBeDisabled();
    });
    fireEvent.click(within(pagination).getByRole("button", { name: "Go to page 2" }));

    await waitFor(() => expect(screen.getByText("Second Paper")).toBeInTheDocument());
    expect(screen.queryByText("Paper")).not.toBeInTheDocument();

    const pageTwoCall = analysisApi.fetchAuthorPublications.mock.calls.find(
      ([payload]) => payload.page === 2,
    );
    expect(pageTwoCall).toBeTruthy();
    expect(pageTwoCall[0]).toEqual(
      expect.objectContaining({
        page: 2,
        cursor: null,
      }),
    );

    const categories = JSON.parse(
      screen.getByTestId("apex-chart-mock").getAttribute("data-categories"),
    );
    expect(categories).toEqual(["2024"]);
    expect(
      screen.getByText("Timeline based on all 1,037 publications"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Timeline based on 8 of 50 publications")).not.toBeInTheDocument();
  });

  it("paginates with page controls and shows range", async () => {
    analysisApi.fetchAuthorPublications.mockResolvedValue(
      publicationsPayload({
        provider_total_count: 1037,
        pagination: {
          page: 1,
          total: 1037,
          has_more: true,
          next_cursor: "cursor-2",
          corpus_source: null,
        },
        next_cursor: "cursor-2",
        has_more: true,
      }),
    );

    renderPage();
    await waitFor(() => expect(screen.getByText("Paper")).toBeInTheDocument());
    await waitFor(() => {
      expect(screen.getByTestId("publications-range-label")).toBeInTheDocument();
      expect(screen.getByTestId("publications-pagination")).toBeInTheDocument();
    });
    expect(screen.getByTestId("publications-range-label")).toHaveTextContent(
      /Showing 1–1 of 1,?037 unique publications/,
    );
  });

  it("keeps chart visible when the table is empty", async () => {
    analysisApi.fetchAuthorPublications.mockResolvedValue(
      publicationsPayload({
        items: [],
        timeline: {
          interval: "year",
          total_dated_publications: 1,
          total_matching_publications: 1,
          items: [{ period: "2020", label: "2020", count: 1 }],
        },
        pagination: {
          page: 1,
          total: 0,
          has_more: false,
          next_cursor: null,
          corpus_source: null,
        },
      }),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Common publications over time")).toBeInTheDocument();
    });
    expect(await screen.findByTestId("author-publication-trend-chart")).toBeInTheDocument();
    expect(screen.getByText(/No common publications found/i)).toBeInTheDocument();
  });

  it("resets pagination when active authors change", async () => {
    analysisApi.fetchAuthorPublications.mockImplementation(async ({ authors, page = 1 }) => {
      if ((authors || []).length === 1) {
        return publicationsPayload({
          mode: "single_author",
          authors: [AUTHORS[0]],
          items: [
            { id: "solo", title: "Solo Paper", analysis_match: { verified: true, method: "x" } },
          ],
          timeline: {
            interval: "year",
            total_dated_publications: 1,
            total_matching_publications: 1,
            items: [{ period: "2023", label: "2023", count: 1 }],
          },
          pagination: {
            page: 1,
            total: 1,
            has_more: false,
            next_cursor: null,
            corpus_source: null,
          },
          next_cursor: null,
          has_more: false,
        });
      }
      return publicationsPayload({
        items: [{ id: "w1", title: "Paper", analysis_match: { verified: true, method: "x" } }],
        pagination: {
          page,
          total: 40,
          has_more: true,
          next_cursor: "page-2",
          corpus_source: null,
        },
        next_cursor: "page-2",
        has_more: true,
      });
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
    expect(lastCall.page).toBe(1);
    expect(lastCall.authors).toHaveLength(1);
  });

  it("does not refetch when draft year filters change until Apply", async () => {
    renderPage();
    const callsBefore = await waitForSettledFetchCount(1);

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    fireEvent.change(screen.getByLabelText("From year"), { target: { value: "2020" } });
    fireEvent.change(screen.getByLabelText("To year"), { target: { value: "2024" } });
    await sleep(FILTER_DEBOUNCE_MS + 50);

    expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(callsBefore);
    expect(screen.getByRole("button", { name: "Apply filters" })).toBeEnabled();
  });

  it("applies filters with exactly one main refresh", async () => {
    renderPage();
    const callsBefore = await waitForSettledFetchCount(1);

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    fireEvent.change(screen.getByLabelText("From year"), { target: { value: "2020" } });
    fireEvent.change(screen.getByLabelText("To year"), { target: { value: "2024" } });

    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));

    await waitFor(() =>
      expect(analysisApi.fetchAuthorPublications.mock.calls.length).toBeGreaterThan(callsBefore),
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
    const callsBefore = await waitForSettledFetchCount(1);

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    fireEvent.change(screen.getByLabelText("From year"), { target: { value: "2024" } });
    fireEvent.change(screen.getByLabelText("To year"), { target: { value: "2020" } });

    expect(screen.getByRole("button", { name: "Apply filters" })).toBeDisabled();
    expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(callsBefore);
  });

  it("resets filters with one unfiltered refresh", async () => {
    renderPage();
    let callsBefore = await waitForSettledFetchCount(1);

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    fireEvent.change(screen.getByLabelText("From year"), { target: { value: "2020" } });
    fireEvent.change(screen.getByLabelText("To year"), { target: { value: "2024" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() =>
      expect(analysisApi.fetchAuthorPublications.mock.calls.length).toBeGreaterThan(callsBefore),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Reset" })).not.toBeDisabled(),
    );

    callsBefore = analysisApi.fetchAuthorPublications.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    await waitFor(() =>
      expect(analysisApi.fetchAuthorPublications.mock.calls.length).toBeGreaterThan(callsBefore),
    );

    const lastCall =
      analysisApi.fetchAuthorPublications.mock.calls[
        analysisApi.fetchAuthorPublications.mock.calls.length - 1
      ][0];
    expect(lastCall.filters == null || Object.keys(lastCall.filters || {}).length === 0).toBe(
      true,
    );
  });

  it("enables Download CSV after verified corpus is ready and exports applied filters only", async () => {
    mockCompleteCorpusStats();
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

    const callsBeforeApply = analysisApi.fetchAuthorPublications.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() =>
      expect(analysisApi.fetchAuthorPublications.mock.calls.length).toBeGreaterThan(callsBeforeApply),
    );
    await waitFor(() => expect(screen.getByTestId("download-csv-button")).toBeEnabled());
    fireEvent.click(screen.getByTestId("download-csv-button"));
    await waitFor(() => expect(exportSpy).toHaveBeenCalledTimes(2));
    expect(exportSpy.mock.calls[1][0].filters).toEqual({
      from_year: 2020,
      to_year: 2024,
    });
    expect(exportSpy.mock.calls[1][0].authors).toHaveLength(2);
  });

  it("keeps Download CSV disabled until the corpus is verified complete", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId("download-csv-button")).toBeDisabled());
  });

  it("disables Download CSV when there are zero matching publications", async () => {
    mockCompleteCorpusStats();
    analysisApi.fetchAuthorPublications.mockResolvedValueOnce(
      publicationsPayload({
        items: [],
        timeline: null,
        facets: { sources: [], venues: [], grants: [] },
        pagination: {
          page: 1,
          total: 0,
          has_more: false,
          next_cursor: null,
          corpus_source: null,
        },
      }),
    );
    renderPage();
    await waitFor(() => expect(screen.getByTestId("download-csv-button")).toBeDisabled());
  });
});
