import { StrictMode } from "react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, within, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ThemeProvider, createTheme } from "@mui/material/styles";

import AuthorInsightsPage from "./AuthorInsightsPage";
import AuthorAnalysisPage from "../../components/authors/AuthorAnalysisPage";
import * as analysisApi from "../../api/analysisApi";
import { clearPublicationsPageCache } from "../../components/authors/authorAnalysisCache";
import { clearAuthorInsightsRequestCacheForTests } from "./authorInsightsRequestCache";
import { createAppTheme, getAnalysisPalette, getInsightsAccent } from "../../theme/analysisPalette";

vi.mock("react-apexcharts", () => ({
  default: ({ series, options, type }) => (
    <div
      data-testid="apex-chart-mock"
      data-chart-type={type}
      data-series={JSON.stringify(series)}
      data-categories={JSON.stringify(options?.xaxis?.categories || [])}
      data-labels={JSON.stringify(options?.labels || [])}
      data-colors={JSON.stringify(options?.colors || [])}
      data-label-colors={JSON.stringify(options?.dataLabels?.style?.colors || [])}
    />
  ),
}));

const theme = createAppTheme();
const darkTheme = createTheme({ palette: { mode: "dark" } });

const AUTHORS = [
  {
    canonical_author_id: "00000000-0000-0000-0000-000000000001",
    provider: "openalex",
    provider_author_id: "A1",
    display_name: "Eneet Kaur",
  },
  {
    canonical_author_id: "00000000-0000-0000-0000-000000000002",
    provider: "openalex",
    provider_author_id: "A2",
    display_name: "Mark M. Wilde",
  },
];

const DEFAULT_COMBINATION_ID = `${AUTHORS[0].canonical_author_id}+${AUTHORS[1].canonical_author_id}`;

function publicationItem({ id, title, year = 2023, venue = "Physical Review A" }) {
  return {
    id,
    result_id: id,
    canonical_work_id: id,
    result_type: "work",
    title,
    authors: [
      {
        display_name: "Eneet Kaur",
        canonical_author_id: AUTHORS[0].canonical_author_id,
        provider_ids: { openalex: ["A1"], orcid: [], arxiv: [] },
        unresolved: false,
      },
      {
        display_name: "Mark M. Wilde",
        canonical_author_id: AUTHORS[1].canonical_author_id,
        provider_ids: { openalex: ["A2"], orcid: [], arxiv: [] },
        unresolved: false,
      },
    ],
    publication_year: year,
    journal: venue,
    primary_source: venue,
    citation_count: 12,
    cited_by_count: 12,
    providers: ["openalex"],
    grants: [],
    analysis_match: { verified: true, method: "stored_author_insights_combination" },
    source: "openalex",
    source_records: [{ provider: "openalex", provider_work_id: id }],
  };
}

const DEFAULT_PUBLICATION_PAGE = {
  combinationId: DEFAULT_COMBINATION_ID,
  items: [publicationItem({ id: "w-preview-1", title: "Real Shared Paper" })],
  pagination: { next_cursor: null, has_more: false },
  nextCursor: null,
  hasMore: false,
};

const BACKEND_INSIGHTS = {
  authors: [
    {
      canonical_author_id: AUTHORS[0].canonical_author_id,
      display_name: "Eneet Kaur",
    },
    {
      canonical_author_id: AUTHORS[1].canonical_author_id,
      display_name: "Mark M. Wilde",
    },
  ],
  metrics: {
    total_unique_publications: 12,
    multi_selected_author_publications: 7,
    all_selected_author_publications: 7,
    multi_institution_publications: 5,
    total_citations: 320,
    average_citations: 26.67,
  },
  combinations: [
    {
      id: DEFAULT_COMBINATION_ID,
      author_ids: [AUTHORS[0].canonical_author_id, AUTHORS[1].canonical_author_id],
      author_names: ["Eneet Kaur", "Mark M. Wilde"],
      label: "Eneet Kaur + Mark M. Wilde",
      publication_count: 7,
      citation_count: 210,
      average_citations: 30,
      institution_count: 4,
      grant_count: 2,
    },
  ],
  collaboration_by_year: [
    { year: 2022, publication_count: 3, percentage_of_year_total: 60 },
    { year: 2023, publication_count: 4, percentage_of_year_total: 80 },
  ],
  participation: {
    selected_author_counts: [
      { selected_author_count: 1, publication_count: 5 },
      { selected_author_count: 2, publication_count: 7 },
    ],
    institution_counts: [
      { institution_count: 1, publication_count: 7 },
      { institution_count: 2, publication_count: 5 },
    ],
  },
  institution_network: {
    nodes: [
      {
        id: "I-A",
        name: "University of Arizona",
        country: "US",
        publication_count: 5,
      },
      {
        id: "I-B",
        name: "Louisiana State University",
        country: "US",
        publication_count: 4,
      },
    ],
    edges: [
      {
        source: "I-A",
        target: "I-B",
        shared_publication_count: 3,
      },
    ],
  },
  institution_partnerships: [
    {
      institution_a: {
        id: "I-A",
        name: "University of Arizona",
        country: "US",
      },
      institution_b: {
        id: "I-B",
        name: "Louisiana State University",
        country: "US",
      },
      shared_publication_count: 3,
      selected_author_ids: [
        AUTHORS[0].canonical_author_id,
        AUTHORS[1].canonical_author_id,
      ],
      selected_author_names: ["Eneet Kaur", "Mark M. Wilde"],
    },
  ],
  citation_activity: [
    {
      year: 2022,
      citation_count: 120,
      cumulative_citations: 120,
      publication_count: 3,
    },
    {
      year: 2023,
      citation_count: 200,
      cumulative_citations: 320,
      publication_count: 4,
    },
  ],
  top_journals: [
    {
      venue: "Physical Review A",
      publication_count: 4,
      citation_count: 120,
      issn: "1050-2947",
      journal_metrics: {
        citescore: 5.1,
        citescore_year: 2024,
        sjr: 1.2,
        sjr_year: 2024,
        snip: 1.1,
        snip_year: 2024,
        source: "scopus",
        scopus_url: "https://www.scopus.com/sourceid/29150",
      },
    },
    {
      venue: "Quantum",
      publication_count: 3,
      citation_count: 90,
      issn: null,
      journal_metrics: null,
    },
  ],
  default_combination_id: DEFAULT_COMBINATION_ID,
  institution_data_quality: {
    total_works: 12,
    works_with_any_institution: 10,
    works_without_institution: 2,
    works_with_partial_institution: 1,
    works_with_complete_institution: 9,
    works_with_multi_institution: 5,
  },
  facets: {
    sources: [{ value: "openalex", label: "OpenAlex", count: 12 }],
    venues: [{ value: "physical review a", label: "Physical Review A", count: 4 }],
    grants: [{ grant_number: "123", funder: "NSF", publication_count: 2 }],
    authors: [],
  },
};

class IntersectionObserverStub {
  observe() {}

  disconnect() {}

  unobserve() {}
}

function renderInsights(initialEntry, { strict = false, renderTheme = theme } = {}) {
  const tree = (
    <ThemeProvider theme={renderTheme}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/analyze/authors" element={<AuthorAnalysisPage />} />
          <Route path="/analyze/authors/insights" element={<AuthorInsightsPage />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>
  );

  return render(strict ? <StrictMode>{tree}</StrictMode> : tree);
}

function renderInsightsWithAuthors(options = {}) {
  return renderInsights(
    {
      pathname: "/analyze/authors/insights",
      state: {
        authors: options.authors || AUTHORS,
        filters: options.filters,
      },
    },
    { renderTheme: options.renderTheme || theme },
  );
}

function pendingPromise() {
  return new Promise(() => {});
}

function completedInsightsJob(result = BACKEND_INSIGHTS) {
  return {
    job_id: "job-1",
    status: "completed",
    result,
    progress_percent: 100,
    progress_stage: "Completed",
    error_message: null,
  };
}

function queuedInsightsJob(jobId = "job-1") {
  return {
    job_id: jobId,
    status: "queued",
    result: null,
    progress_percent: 0,
    progress_stage: "Preparing",
    error_message: null,
  };
}

describe("AuthorInsightsPage", () => {
  beforeEach(() => {
    clearPublicationsPageCache();
    clearAuthorInsightsRequestCacheForTests();
    vi.stubGlobal("IntersectionObserver", IntersectionObserverStub);
    vi.spyOn(analysisApi, "fetchAuthorPublications").mockResolvedValue({
      mode: "common_publications",
      authors: AUTHORS,
      items: [{ id: "w1", title: "Paper", analysis_match: { verified: true, method: "x" } }],
      timeline: {
        interval: "year",
        items: [{ period: "2024", label: "2024", count: 1 }],
      },
      facets: {
        sources: [{ value: "openalex", label: "OpenAlex", count: 1 }],
        venues: [],
        grants: [],
      },
      next_cursor: null,
      has_more: false,
      unsupported: false,
    });
    vi.spyOn(analysisApi, "createAuthorInsightsJob").mockResolvedValue(
      completedInsightsJob(),
    );
    vi.spyOn(analysisApi, "getAuthorInsightsJob").mockResolvedValue(
      completedInsightsJob(),
    );
    vi.spyOn(analysisApi, "fetchAuthorInsightsPublications").mockResolvedValue(
      DEFAULT_PUBLICATION_PAGE,
    );
    vi.spyOn(analysisApi, "fetchAuthorPublicationFacets").mockResolvedValue({
      sources: [{ value: "live-overlay", label: "Live Overlay", count: 99 }],
      institutions: [],
      venues: [],
      grants: [],
      authors: [],
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    clearPublicationsPageCache();
    clearAuthorInsightsRequestCacheForTests();
  });

  it("calls the real author insights API", async () => {
    renderInsightsWithAuthors();

    await waitFor(() => {
      expect(analysisApi.createAuthorInsightsJob).toHaveBeenCalledTimes(1);
    });
    expect(analysisApi.getAuthorInsightsJob).not.toHaveBeenCalled();
    expect(await screen.findByTestId("author-insights-page")).toBeInTheDocument();
    expect(await screen.findByTestId("insights-job-success-snackbar")).toHaveTextContent(
      "Collaboration Insights ready",
    );
    expect(analysisApi.fetchAuthorPublicationFacets).not.toHaveBeenCalled();
    expect(analysisApi.fetchAuthorPublications).not.toHaveBeenCalled();
  });

  it("uses dashboard job facets instead of live publication facet overlay", async () => {
    renderInsightsWithAuthors();

    await screen.findByTestId("author-insights-page");
    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    fireEvent.mouseDown(screen.getByPlaceholderText("Select sources"));

    expect(await screen.findByText("OpenAlex")).toBeInTheDocument();
    expect(screen.queryByText("Live Overlay")).not.toBeInTheDocument();
    expect(analysisApi.fetchAuthorPublicationFacets).not.toHaveBeenCalled();
  });

  it("sends selected canonical author IDs and filters", async () => {
    renderInsightsWithAuthors({
      filters: {
        from_year: 2020,
        to_year: 2024,
        sources: ["openalex"],
        venues: ["Physical Review A"],
        grant_numbers: ["123"],
      },
    });

    await waitFor(() => {
      expect(analysisApi.createAuthorInsightsJob).toHaveBeenCalled();
    });

    const call = analysisApi.createAuthorInsightsJob.mock.calls[0][0];
    expect(call.authors).toEqual([
      {
        canonical_author_id: AUTHORS[0].canonical_author_id,
        display_name: "Eneet Kaur",
      },
      {
        canonical_author_id: AUTHORS[1].canonical_author_id,
        display_name: "Mark M. Wilde",
      },
    ]);
    expect(call.filters).toEqual({
      from_year: 2020,
      to_year: 2024,
      sources: ["openalex"],
      venues: ["Physical Review A"],
      grant_numbers: ["123"],
    });
    expect(call.signal).toBeInstanceOf(AbortSignal);
  });

  it("selects publications, excludes them, and passes session state to Insights", async () => {
    renderInsights({
      pathname: "/analyze/authors",
      state: { authors: AUTHORS },
    });

    const publicationCheckbox = await screen.findByTestId("publication-select-w1");
    fireEvent.click(publicationCheckbox);
    expect(await screen.findByTestId("publication-selection-actions")).toHaveTextContent(
      "1 selected",
    );

    fireEvent.click(screen.getByRole("button", { name: "Exclude from Insights" }));

    expect(screen.getByTestId("excluded-count")).toHaveTextContent(
      "Excluded from Insights: 1",
    );
    expect(screen.getAllByText("Paper").length).toBeGreaterThan(0);
    expect(screen.getByText("Excluded from Insights")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("open-author-insights"));

    await waitFor(() => {
      expect(analysisApi.createAuthorInsightsJob).toHaveBeenCalled();
    });
    const call = analysisApi.createAuthorInsightsJob.mock.calls[0][0];
    expect(call.authors.map((author) => author.canonical_author_id)).toEqual([
      AUTHORS[0].canonical_author_id,
      AUTHORS[1].canonical_author_id,
    ]);
    expect(call.excludedWorkIds).toEqual(["w1"]);
  });

  it("selects visible publications and excludes canonical work IDs", async () => {
    renderInsights({
      pathname: "/analyze/authors",
      state: { authors: AUTHORS },
    });

    await screen.findByTestId("publication-row-w1");
    const visibleCheckbox = await screen.findByTestId("publication-select-visible");
    fireEvent.click(visibleCheckbox);

    expect(await screen.findByTestId("publication-selection-actions")).toHaveTextContent(
      "1 selected",
    );
    fireEvent.click(screen.getByRole("button", { name: "Exclude from Insights" }));

    expect(screen.getByTestId("excluded-count")).toHaveTextContent(
      "Excluded from Insights: 1",
    );
    expect(await screen.findByTestId("publication-row-w1")).toHaveTextContent(
      "Excluded from Insights",
    );
  });

  it("sorts the Author Analysis table by Year ascending and descending", async () => {
    renderInsights({
      pathname: "/analyze/authors",
      state: { authors: AUTHORS },
    });

    await screen.findByTestId("publication-row-w1");
    expect(analysisApi.fetchAuthorPublications.mock.calls[0][0]).toMatchObject({
      sortBy: "year",
      sortDirection: "desc",
      cursor: null,
    });

    fireEvent.click(screen.getByRole("button", { name: /Year/i }));
    await waitFor(() => {
      expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(2);
    });
    expect(analysisApi.fetchAuthorPublications.mock.calls[1][0]).toMatchObject({
      sortBy: "year",
      sortDirection: "asc",
      cursor: null,
    });

    fireEvent.click(screen.getByRole("button", { name: /Year/i }));
    await waitFor(() => {
      expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(3);
    });
    expect(analysisApi.fetchAuthorPublications.mock.calls[2][0]).toMatchObject({
      sortBy: "year",
      sortDirection: "desc",
      cursor: null,
    });
  });

  it("preserves filters and exclusions when Author Analysis sorting changes", async () => {
    renderInsights({
      pathname: "/analyze/authors",
      state: {
        authors: AUTHORS,
        filters: { from_year: 2020 },
      },
    });

    await screen.findByTestId("publication-row-w1");
    fireEvent.click(await screen.findByTestId("publication-select-w1"));
    fireEvent.click(screen.getByRole("button", { name: "Exclude from Insights" }));

    fireEvent.click(screen.getByRole("button", { name: /Citations/i }));
    await waitFor(() => {
      expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(2);
    });

    expect(screen.getByTestId("excluded-count")).toHaveTextContent(
      "Excluded from Insights: 1",
    );
    expect(analysisApi.fetchAuthorPublications.mock.calls[1][0]).toMatchObject({
      filters: { from_year: 2020 },
      sortBy: "citations",
      sortDirection: "asc",
      cursor: null,
    });
  });

  it("renders original authors as Insights checkboxes and refreshes when changed", async () => {
    const authorC = {
      canonical_author_id: "00000000-0000-0000-0000-000000000003",
      provider: "openalex",
      provider_author_id: "A3",
      display_name: "Author C",
    };
    renderInsights({
      pathname: "/analyze/authors/insights",
      state: {
        originalAuthors: [...AUTHORS, authorC],
        activeAuthors: AUTHORS,
        excludedWorkIds: ["w-excluded"],
      },
    });

    await screen.findByTestId("insights-metric-cards");
    expect(screen.getByTestId("insights-author-selection")).toBeInTheDocument();
    expect(screen.getByText("Authors included")).toBeInTheDocument();
    expect(screen.queryByTestId("selected-author-chips")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Author C")).not.toBeChecked();

    fireEvent.click(screen.getByLabelText("Author C"));

    await waitFor(() => {
      expect(analysisApi.createAuthorInsightsJob).toHaveBeenCalledTimes(2);
    });
    const call = analysisApi.createAuthorInsightsJob.mock.calls[1][0];
    expect(call.authors.map((author) => author.canonical_author_id)).toEqual([
      AUTHORS[0].canonical_author_id,
      AUTHORS[1].canonical_author_id,
      authorC.canonical_author_id,
    ]);
    expect(call.excludedWorkIds).toEqual(["w-excluded"]);
  });

  it("supports one active author without combinations", async () => {
    analysisApi.createAuthorInsightsJob.mockResolvedValueOnce(
      completedInsightsJob({
        ...BACKEND_INSIGHTS,
        authors: [BACKEND_INSIGHTS.authors[0]],
        metrics: {
          ...BACKEND_INSIGHTS.metrics,
          total_unique_publications: 4,
          multi_selected_author_publications: 0,
          all_selected_author_publications: 4,
        },
        combinations: [],
        default_combination_id: null,
      }),
    );

    renderInsights({
      pathname: "/analyze/authors/insights",
      state: {
        originalAuthors: AUTHORS,
        activeAuthors: [AUTHORS[0]],
      },
    });

    const cards = await screen.findByTestId("insights-metric-cards");
    expect(within(cards).getByTestId("metric-card-totalUniquePublications")).toHaveTextContent(
      "4",
    );
    expect(screen.queryByTestId(`combination-row-${DEFAULT_COMBINATION_ID}`)).not.toBeInTheDocument();
    expect(analysisApi.fetchAuthorInsightsPublications).not.toHaveBeenCalled();
  });

  it("restores an exclusion on Insights and refreshes once", async () => {
    renderInsights({
      pathname: "/analyze/authors/insights",
      state: {
        originalAuthors: AUTHORS,
        activeAuthors: AUTHORS,
        excludedWorkIds: ["w-excluded"],
        excludedWorksById: {
          "w-excluded": { title: "Excluded Paper", publication_year: 2022 },
        },
      },
    });

    await screen.findByTestId("insights-metric-cards");
    expect(analysisApi.createAuthorInsightsJob.mock.calls[0][0].excludedWorkIds).toEqual([
      "w-excluded",
    ]);

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    fireEvent.click(screen.getByRole("button", { name: "Restore" }));

    await waitFor(() => {
      expect(analysisApi.createAuthorInsightsJob).toHaveBeenCalledTimes(2);
    });
    expect(analysisApi.createAuthorInsightsJob.mock.calls[1][0].excludedWorkIds).toEqual([]);
  });

  it("Back to Publications preserves original authors active authors exclusions and filters", async () => {
    renderInsights({
      pathname: "/analyze/authors/insights",
      state: {
        originalAuthors: AUTHORS,
        activeAuthors: [AUTHORS[0]],
        excludedWorkIds: ["w1"],
        excludedWorksById: {
          w1: { title: "Paper", publication_year: 2024 },
        },
        filters: { from_year: 2020 },
      },
    });

    await screen.findByTestId("insights-metric-cards");
    fireEvent.click(screen.getAllByRole("button", { name: "Back to Publications" })[0]);

    await screen.findByTestId("open-author-insights");
    expect(screen.getByLabelText("Eneet Kaur")).toBeChecked();
    expect(screen.getByLabelText("Mark M. Wilde")).not.toBeChecked();
    expect(screen.getByTestId("excluded-count")).toHaveTextContent(
      "Excluded from Insights: 1",
    );
    expect(await screen.findByTestId("publication-row-w1")).toHaveTextContent(
      "Excluded from Insights",
    );
    await waitFor(() => {
      const call = analysisApi.fetchAuthorPublications.mock.calls.at(-1)[0];
      expect(call.authors.map((author) => author.canonical_author_id)).toEqual([
        AUTHORS[0].canonical_author_id,
      ]);
      expect(call.filters).toEqual({ from_year: 2020 });
    });
  });

  it("renders loading skeletons while waiting", () => {
    analysisApi.createAuthorInsightsJob.mockReturnValue(pendingPromise());

    renderInsightsWithAuthors();

    expect(screen.getByTestId("author-insights-loading")).toBeInTheDocument();
    expect(screen.getAllByText("Collaboration Insights")[0]).toBeInTheDocument();
    expect(screen.getByTestId("insights-job-progress-snackbar")).toHaveTextContent(
      "Preparing… 0%",
    );
  });

    it("polls the insights job until completed and shows stage progress", async () => {
    analysisApi.createAuthorInsightsJob.mockResolvedValue(queuedInsightsJob());
    analysisApi.getAuthorInsightsJob
      .mockResolvedValueOnce({
        job_id: "job-1",
        status: "running",
        progress_stage: "Syncing publications for Martin Head-Gordon — 420 / 1,037",
        progress_percent: 25,
        progress_detail: {
          phase: "syncing",
          author_name: "Martin Head-Gordon",
          publications_processed: 420,
          publications_total: 1037,
          provider: "openalex",
          sync_status: "partial",
        },
        result: null,
        error_message: null,
      })
      .mockResolvedValueOnce(completedInsightsJob());

    renderInsightsWithAuthors();

    await waitFor(() => {
      expect(screen.getByTestId("insights-job-progress-snackbar")).toHaveTextContent(
        "Syncing Martin Head-Gordon — 420 / 1,037 publications",
      );
    });
    await waitFor(
      () => {
        expect(screen.getByTestId("insights-metric-cards")).toBeInTheDocument();
      },
      { timeout: 4000 },
    );
    expect(analysisApi.getAuthorInsightsJob).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("insights-job-success-snackbar")).toHaveTextContent(
      "Collaboration Insights ready",
    );
  });

  it("shows the backend error when an insights job fails", async () => {
    analysisApi.createAuthorInsightsJob.mockResolvedValue(queuedInsightsJob());
    analysisApi.getAuthorInsightsJob.mockResolvedValue({
      job_id: "job-1",
      status: "failed",
      progress_stage: "Failed",
      progress_percent: 12,
      error_message: "OpenAlex unavailable",
      result: null,
    });

    renderInsightsWithAuthors();

    const error = await screen.findByTestId("author-insights-error");
    expect(error).toHaveTextContent("OpenAlex unavailable");
    expect(screen.getByTestId("insights-job-error-snackbar")).toHaveTextContent(
      "OpenAlex unavailable",
    );
    expect(analysisApi.getAuthorInsightsJob).toHaveBeenCalled();
  });

  it("renders real summary metrics", async () => {
    renderInsightsWithAuthors();

    const cards = await screen.findByTestId("insights-metric-cards");
    expect(within(cards).getByTestId("metric-card-totalUniquePublications")).toHaveTextContent(
      "12",
    );
    expect(within(cards).getByTestId("metric-card-sharedByTwoOrMore")).toHaveTextContent("7");
    expect(within(cards).getByTestId("metric-card-sharedByAll")).toHaveTextContent("7");
    expect(
      within(cards).getByTestId("metric-card-multiInstitutionPublications"),
    ).toHaveTextContent("5");
    expect(within(cards).getByTestId("metric-card-sharedByTwoOrMore")).toHaveTextContent("58.3%");
  });

  it("renders real combinations and preserves row selection", async () => {
    renderInsightsWithAuthors();

    const row = await screen.findByTestId(
      `combination-row-${BACKEND_INSIGHTS.default_combination_id}`,
    );
    expect(row).toHaveTextContent("Eneet Kaur + Mark M. Wilde");
    expect(row).toHaveTextContent("7");
    fireEvent.click(row);
    expect(row).toHaveClass("Mui-selected");
  });

  it("renders every backend combination for a three-author response", async () => {
    const authorC = {
      canonical_author_id: "00000000-0000-0000-0000-000000000003",
      provider: "openalex",
      provider_author_id: "A3",
      display_name: "Author C",
    };
    const threeAuthors = [...AUTHORS, authorC];
    const ab = `${AUTHORS[0].canonical_author_id}+${AUTHORS[1].canonical_author_id}`;
    const ac = `${AUTHORS[0].canonical_author_id}+${authorC.canonical_author_id}`;
    const bc = `${AUTHORS[1].canonical_author_id}+${authorC.canonical_author_id}`;
    const abc = `${AUTHORS[0].canonical_author_id}+${AUTHORS[1].canonical_author_id}+${authorC.canonical_author_id}`;

    analysisApi.createAuthorInsightsJob.mockResolvedValueOnce(
      completedInsightsJob({
      ...BACKEND_INSIGHTS,
      authors: threeAuthors.map((author) => ({
        canonical_author_id: author.canonical_author_id,
        display_name: author.display_name,
      })),
      metrics: {
        ...BACKEND_INSIGHTS.metrics,
        total_unique_publications: 6,
        multi_selected_author_publications: 5,
        all_selected_author_publications: 1,
      },
      combinations: [
        {
          ...BACKEND_INSIGHTS.combinations[0],
          id: ab,
          author_ids: [AUTHORS[0].canonical_author_id, AUTHORS[1].canonical_author_id],
          author_names: ["Eneet Kaur", "Mark M. Wilde"],
          label: "Eneet Kaur + Mark M. Wilde",
          publication_count: 3,
        },
        {
          ...BACKEND_INSIGHTS.combinations[0],
          id: ac,
          author_ids: [AUTHORS[0].canonical_author_id, authorC.canonical_author_id],
          author_names: ["Eneet Kaur", "Author C"],
          label: "Eneet Kaur + Author C",
          publication_count: 2,
        },
        {
          ...BACKEND_INSIGHTS.combinations[0],
          id: bc,
          author_ids: [AUTHORS[1].canonical_author_id, authorC.canonical_author_id],
          author_names: ["Mark M. Wilde", "Author C"],
          label: "Mark M. Wilde + Author C",
          publication_count: 2,
        },
        {
          ...BACKEND_INSIGHTS.combinations[0],
          id: abc,
          author_ids: [
            AUTHORS[0].canonical_author_id,
            AUTHORS[1].canonical_author_id,
            authorC.canonical_author_id,
          ],
          author_names: ["Eneet Kaur", "Mark M. Wilde", "Author C"],
          label: "Eneet Kaur + Mark M. Wilde + Author C",
          publication_count: 1,
        },
      ],
      default_combination_id: ab,
      }),
    );

    renderInsightsWithAuthors({ authors: threeAuthors });

    expect(await screen.findByTestId(`combination-row-${ab}`)).toHaveTextContent("3");
    expect(screen.getByTestId(`combination-row-${ac}`)).toHaveTextContent("2");
    expect(screen.getByTestId(`combination-row-${bc}`)).toHaveTextContent("2");
    expect(screen.getByTestId(`combination-row-${abc}`)).toHaveTextContent("1");
  });

  it("limits collaboration chart and summary to the top 10 and opens View all", async () => {
    const extraCombinations = Array.from({ length: 12 }, (_, index) => ({
      ...BACKEND_INSIGHTS.combinations[0],
      id: `combo-${index + 1}`,
      label: `Author Pair ${index + 1}`,
      publication_count: 12 - index,
      author_ids: [AUTHORS[0].canonical_author_id, AUTHORS[1].canonical_author_id],
      author_names: ["Eneet Kaur", "Mark M. Wilde"],
    }));
    analysisApi.createAuthorInsightsJob.mockResolvedValueOnce(
      completedInsightsJob({
        ...BACKEND_INSIGHTS,
        combinations: extraCombinations,
        default_combination_id: extraCombinations[0].id,
        institution_partnerships: Array.from({ length: 12 }, (_, index) => ({
          institution_a: { id: `I-A${index}`, name: `Institution A${index}` },
          institution_b: { id: `I-B${index}`, name: `Institution B${index}` },
          shared_publication_count: 12 - index,
        })),
        top_journals: Array.from({ length: 12 }, (_, index) => ({
          venue: `Venue ${index + 1}`,
          publication_count: 12 - index,
          citation_count: 10,
          issn: null,
          journal_metrics: null,
        })),
      }),
    );

    renderInsightsWithAuthors();

    await screen.findByTestId("author-combination-table");
    const combinationChart = screen.getAllByTestId("apex-chart-mock").find((node) => {
      const categories = JSON.parse(node.getAttribute("data-categories") || "[]");
      return categories.includes("Author Pair 1");
    });
    expect(combinationChart).toBeTruthy();
    expect(JSON.parse(combinationChart.getAttribute("data-categories"))).toEqual(
      extraCombinations.slice(0, 10).map((row) => row.label),
    );
    expect(screen.getByTestId("author-combination-chart-labels")).toBeInTheDocument();
    expect(screen.getByTestId("combination-chart-label-combo-1")).toHaveTextContent(
      "Author Pair 1",
    );

    const summary = screen.getByTestId("author-combination-table");
    expect(within(summary).getByTestId("combination-row-combo-1")).toBeInTheDocument();
    expect(within(summary).queryByTestId("combination-row-combo-11")).not.toBeInTheDocument();
    expect(within(summary).getByTestId("combination-view-all-button")).toBeInTheDocument();
    expect(screen.getByTestId("combination-chart-view-all-button")).toBeInTheDocument();

    fireEvent.click(within(summary).getByTestId("combination-view-all-button"));
    const dialog = await screen.findByTestId("combination-view-all-dialog");
    expect(within(dialog).getByText("All collaborations")).toBeInTheDocument();
    expect(within(dialog).getByTestId("combination-dialog-row-combo-12")).toHaveTextContent(
      "Author Pair 12",
    );
    fireEvent.click(within(dialog).getByTestId("insights-view-all-close"));

    const partnershipTable = screen.getByTestId("institution-partnership-table");
    expect(within(partnershipTable).queryByText("Institution A10 × Institution B10")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("institution-partnership-view-all-button"));
    const partnershipDialog = await screen.findByTestId("institution-partnership-view-all-dialog");
    expect(within(partnershipDialog).getByText("Institution A10 × Institution B10")).toBeInTheDocument();
    fireEvent.click(within(partnershipDialog).getByTestId("insights-view-all-close"));

    const journalsTable = screen.getByTestId("top-journals-table");
    expect(within(journalsTable).queryByText("Venue 11")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("journals-view-all-button"));
    const journalsDialog = await screen.findByTestId("journals-view-all-dialog");
    expect(within(journalsDialog).getByText("Venue 12")).toBeInTheDocument();
  });

  it("does not render or fetch the publication preview block", async () => {
    renderInsightsWithAuthors();

    await screen.findByTestId("insights-metric-cards");
    expect(screen.queryByTestId("insights-publication-preview")).not.toBeInTheDocument();
    expect(screen.queryByText("Real Shared Paper")).not.toBeInTheDocument();
    expect(analysisApi.fetchAuthorInsightsPublications).not.toHaveBeenCalled();
  });

  it("does not render the old local preview or demo label", async () => {
    renderInsightsWithAuthors();

    await screen.findByTestId("insights-metric-cards");
    expect(screen.queryByText("Demo data")).not.toBeInTheDocument();
    expect(screen.queryByText(/Temporary local preview/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Mock results/i)).not.toBeInTheDocument();
  });

  it("selecting a combination does not fetch preview publications", async () => {
    const authorC = {
      canonical_author_id: "00000000-0000-0000-0000-000000000003",
      display_name: "Nilanjana Datta",
    };
    const secondCombinationId = `${AUTHORS[0].canonical_author_id}+${authorC.canonical_author_id}`;
    analysisApi.createAuthorInsightsJob.mockResolvedValue(
      completedInsightsJob({
      ...BACKEND_INSIGHTS,
      authors: [...BACKEND_INSIGHTS.authors, authorC],
      combinations: [
        BACKEND_INSIGHTS.combinations[0],
        {
          ...BACKEND_INSIGHTS.combinations[0],
          id: secondCombinationId,
          author_ids: [AUTHORS[0].canonical_author_id, authorC.canonical_author_id],
          author_names: ["Eneet Kaur", "Nilanjana Datta"],
          label: "Eneet Kaur + Nilanjana Datta",
          publication_count: 2,
        },
      ],
      default_combination_id: DEFAULT_COMBINATION_ID,
      }),
    );

    renderInsightsWithAuthors({ authors: [...AUTHORS, authorC] });

    const secondRow = await screen.findByTestId(`combination-row-${secondCombinationId}`);
    fireEvent.click(secondRow);

    expect(secondRow).toHaveClass("Mui-selected");
    expect(analysisApi.fetchAuthorInsightsPublications).not.toHaveBeenCalled();
  });

  it("filters refresh the dashboard once on Apply", async () => {
    renderInsightsWithAuthors();

    await screen.findByTestId("insights-metric-cards");
    expect(analysisApi.createAuthorInsightsJob).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    fireEvent.change(screen.getByLabelText("From year"), {
      target: { value: "2020" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));

    await waitFor(() => {
      expect(analysisApi.createAuthorInsightsJob).toHaveBeenCalledTimes(2);
    });
    expect(analysisApi.createAuthorInsightsJob.mock.calls[1][0].filters).toEqual({
      from_year: 2020,
    });
    expect(analysisApi.fetchAuthorInsightsPublications).not.toHaveBeenCalled();
    expect(analysisApi.fetchAuthorPublicationFacets).not.toHaveBeenCalled();
  });

  it("Reset triggers one unfiltered dashboard refresh", async () => {
    renderInsightsWithAuthors({
      filters: {
        from_year: 2020,
      },
    });

    await screen.findByTestId("insights-metric-cards");
    expect(analysisApi.createAuthorInsightsJob).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));

    await waitFor(() => {
      expect(analysisApi.createAuthorInsightsJob).toHaveBeenCalledTimes(2);
    });
    expect(analysisApi.createAuthorInsightsJob.mock.calls[1][0].filters).toEqual({});
  });

  it("shows clean empty states for sparse institution citation and venue data", async () => {
    analysisApi.createAuthorInsightsJob.mockResolvedValue(
      completedInsightsJob({
        ...BACKEND_INSIGHTS,
        metrics: {
          ...BACKEND_INSIGHTS.metrics,
          total_citations: 0,
          average_citations: 0,
        },
        institution_network: { nodes: [], edges: [] },
        institution_partnerships: [],
        citation_activity: [],
        top_journals: [],
      }),
    );
    renderInsightsWithAuthors();

    expect(
      await screen.findAllByText("No institution collaboration data available"),
    ).toHaveLength(2);
    expect(screen.getByText("No citation data available")).toBeInTheDocument();
    expect(screen.getByText("No venue data available")).toBeInTheDocument();
    expect(screen.queryByTestId("insights-publication-preview")).not.toBeInTheDocument();
  });

  it("renders collaboration year data", async () => {
    renderInsightsWithAuthors();

    await screen.findByTestId("collaboration-year-chart");
    const charts = screen.getAllByTestId("apex-chart-mock");
    const yearChart = charts.find((node) => {
      const categories = JSON.parse(node.getAttribute("data-categories") || "[]");
      return categories.includes(2022) && categories.includes(2023);
    });
    expect(yearChart).toBeTruthy();
    expect(JSON.parse(yearChart.getAttribute("data-series"))[0].data).toEqual([3, 4]);
  });

  it("renders participation data", async () => {
    renderInsightsWithAuthors();

    await screen.findByTestId("participation-donuts");
    expect(screen.getByText("7 papers involve 2+ selected authors.")).toBeInTheDocument();
    expect(screen.getByText("5 papers involve 2+ institutions.")).toBeInTheDocument();
    const charts = screen.getAllByTestId("apex-chart-mock");
    expect(
      charts.some((node) =>
        JSON.parse(node.getAttribute("data-labels") || "[]").includes("2 selected authors"),
      ),
    ).toBe(true);
    expect(
      charts.some((node) =>
        JSON.parse(node.getAttribute("data-labels") || "[]").includes("2 institutions"),
      ),
    ).toBe(true);
    expect(screen.getByTestId("institution-participation-legend")).toHaveTextContent(
      "2 institutions",
    );
    expect(screen.queryByTestId("institution-participation-view-all")).not.toBeInTheDocument();
  });

  it("renders institution partnerships", async () => {
    renderInsightsWithAuthors();

    const table = await screen.findByTestId("institution-partnership-table");
    expect(
      within(table).getByText("University of Arizona × Louisiana State University"),
    ).toBeInTheDocument();
    expect(within(table).getByText("3")).toBeInTheDocument();
  });

  it("passes institution network data to the visualization", async () => {
    renderInsightsWithAuthors();

    await screen.findByTestId("institution-network-preview");
    expect(screen.getByTestId("institution-node-I-A")).toHaveAttribute(
      "data-publications",
      "5",
    );
    expect(screen.getByTestId("institution-edge-I-A-I-B")).toHaveAttribute(
      "data-shared-publications",
      "3",
    );

    fireEvent.mouseEnter(screen.getByTestId("institution-node-I-A"));
    const tooltip = await screen.findByTestId("institution-network-tooltip");
    expect(tooltip).toHaveTextContent("University of Arizona");
    expect(tooltip).toHaveTextContent("Publications: 5");
    expect(tooltip).toHaveTextContent("Partner institutions: 1");
    expect(tooltip).toHaveTextContent("Louisiana State University");
    expect(tooltip).toHaveTextContent("Shared publications with strongest partner: 3");

    expect(screen.getByTestId("institution-network-view-all-button")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("institution-network-view-all-button"));
    const dialog = await screen.findByTestId("institution-network-view-all-dialog");
    expect(within(dialog).getByText("Institution network")).toBeInTheDocument();
    expect(within(dialog).getByTestId("full-institution-node-I-A")).toBeInTheDocument();
    expect(within(dialog).getByTestId("full-institution-edge-I-A-I-B")).toBeInTheDocument();
  });

  it("renders citation activity", async () => {
    renderInsightsWithAuthors();

    const section = await screen.findByTestId("citation-activity-chart");
    expect(within(section).getByText("Total citations")).toBeInTheDocument();
    expect(within(section).getByText("320")).toBeInTheDocument();
    expect(within(section).getByText("26.7")).toBeInTheDocument();
    const charts = screen.getAllByTestId("apex-chart-mock");
    expect(
      charts.some((node) =>
        JSON.parse(node.getAttribute("data-series") || "[]").some(
          (series) =>
            series.name === "Cumulative citations" &&
            JSON.stringify(series.data) === JSON.stringify([120, 320]),
        ),
      ),
    ).toBe(true);
  });

  it("renders top journals", async () => {
    renderInsightsWithAuthors();

    const table = await screen.findByTestId("top-journals-table");
    expect(within(table).getByText("Physical Review A")).toBeInTheDocument();
    expect(within(table).getByText("Quantum")).toBeInTheDocument();
    expect(within(table).getByText("4")).toBeInTheDocument();
    expect(within(table).getByText("CiteScore")).toBeInTheDocument();
    expect(within(table).getByText("SJR")).toBeInTheDocument();
    expect(within(table).getByText("SNIP")).toBeInTheDocument();
    expect(within(table).getByText("5.1")).toBeInTheDocument();
    expect(within(table).getByText("1.20")).toBeInTheDocument();
    expect(within(table).getByText("1.10")).toBeInTheDocument();
    expect(within(table).getAllByText("—").length).toBeGreaterThanOrEqual(3);
    expect(within(table).getByTestId("scopus-attribution")).toHaveTextContent(
      "Journal metrics powered by Scopus.",
    );
    expect(within(table).getByRole("link", { name: "5.1" })).toHaveAttribute(
      "href",
      "https://www.scopus.com/sourceid/29150",
    );
  });

  it("uses a distinct Insights accent per chart", async () => {
    renderInsightsWithAuthors();

    await screen.findByTestId("insights-metric-cards");
    const accents = getAnalysisPalette(theme);
    const collaborationAccent = getInsightsAccent(theme, "authorCollaborations");
    const yearAccent = getInsightsAccent(theme, "collaborationByYear");
    const citationAccent = getInsightsAccent(theme, "citationActivity");

    const combinationChart = within(screen.getByTestId("author-combination-chart")).getByTestId(
      "apex-chart-mock",
    );
    expect(JSON.parse(combinationChart.getAttribute("data-colors"))).toEqual([
      collaborationAccent.main,
    ]);

    const yearChart = within(screen.getByTestId("collaboration-year-chart")).getByTestId(
      "apex-chart-mock",
    );
    expect(JSON.parse(yearChart.getAttribute("data-colors"))).toEqual([yearAccent.main]);

    const citationChart = within(screen.getByTestId("citation-activity-chart")).getByTestId(
      "apex-chart-mock",
    );
    expect(JSON.parse(citationChart.getAttribute("data-colors"))).toEqual([
      citationAccent.main,
      citationAccent.strong,
    ]);

    const participationColors = within(screen.getByTestId("participation-donuts"))
      .getAllByTestId("apex-chart-mock")
      .flatMap((node) => JSON.parse(node.getAttribute("data-colors") || "[]"));
    expect(participationColors).not.toContain(accents.navy);
    expect(participationColors).not.toContain(accents.coral);
    expect(participationColors).not.toContain(accents.teal);
    expect(new Set(participationColors).size).toBeGreaterThan(1);
  });

  it("renders Author Insights in dark mode with the shared palette fallback", async () => {
    renderInsightsWithAuthors({ renderTheme: darkTheme });

    expect(await screen.findByTestId("insights-metric-cards")).toBeInTheDocument();
    const accents = getAnalysisPalette(darkTheme);
    const combinationChart = within(screen.getByTestId("author-combination-chart")).getByTestId(
      "apex-chart-mock",
    );
    expect(JSON.parse(combinationChart.getAttribute("data-colors"))).toEqual([accents.navy]);
    const yearChart = within(screen.getByTestId("collaboration-year-chart")).getByTestId(
      "apex-chart-mock",
    );
    expect(JSON.parse(yearChart.getAttribute("data-colors"))).toEqual([accents.teal]);
  });

  it("shows an error state when the API fails", async () => {
    analysisApi.createAuthorInsightsJob.mockRejectedValue(new Error("Insights unavailable"));

    renderInsightsWithAuthors();

    const error = await screen.findByTestId("author-insights-error");
    expect(error).toHaveTextContent("Insights unavailable");
    expect(screen.queryByTestId("insights-metric-cards")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Retry" }).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByRole("button", { name: "Back to Publications" })).toHaveLength(2);
    expect(screen.getByTestId("insights-job-error-snackbar")).toHaveTextContent(
      "Insights unavailable",
    );
  });

  it("retries after an API failure", async () => {
    analysisApi.createAuthorInsightsJob
      .mockRejectedValueOnce(new Error("Insights unavailable"))
      .mockResolvedValueOnce(completedInsightsJob());

    renderInsightsWithAuthors();

    await screen.findByTestId("author-insights-error");
    fireEvent.click(screen.getAllByRole("button", { name: "Retry" })[0]);

    expect(await screen.findByTestId("insights-metric-cards")).toBeInTheDocument();
    expect(analysisApi.createAuthorInsightsJob).toHaveBeenCalledTimes(2);
  });

  it("shows no-authors state when opened directly without selected authors", () => {
    renderInsights("/analyze/authors/insights");

    expect(screen.getByTestId("author-insights-no-authors")).toHaveTextContent(
      "No authors selected",
    );
    expect(analysisApi.createAuthorInsightsJob).not.toHaveBeenCalled();
  });

  it("prevents duplicate StrictMode fetches for the same request key", async () => {
    renderInsights(
      {
        pathname: "/analyze/authors/insights",
        state: { authors: AUTHORS },
      },
      { strict: true },
    );

    await screen.findByTestId("insights-metric-cards");
    expect(analysisApi.createAuthorInsightsJob).toHaveBeenCalledTimes(1);
  });

  it("keeps the existing Author Analyze page entry point working", async () => {
    renderInsights({
      pathname: "/analyze/authors",
      state: { authors: AUTHORS },
    });

    await waitFor(() => {
      expect(analysisApi.fetchAuthorPublications).toHaveBeenCalled();
    });
    expect(screen.getByTestId("open-author-insights")).toBeInTheDocument();
  });

  it("navigates from Insight button with active selected authors", async () => {
    renderInsights({
      pathname: "/analyze/authors",
      state: { authors: AUTHORS },
    });

    await waitFor(() => {
      expect(screen.getByTestId("open-author-insights")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("open-author-insights"));

    await waitFor(() => {
      expect(analysisApi.createAuthorInsightsJob).toHaveBeenCalled();
    });
    expect(screen.getByTestId("author-insights-page")).toBeInTheDocument();
    const call = analysisApi.createAuthorInsightsJob.mock.calls[0][0];
    expect(call.authors.map((author) => author.canonical_author_id)).toEqual([
      AUTHORS[0].canonical_author_id,
      AUTHORS[1].canonical_author_id,
    ]);
  });
});
