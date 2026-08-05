import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, within, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ThemeProvider, createTheme } from "@mui/material/styles";

import AuthorInsightsPage from "./AuthorInsightsPage";
import AuthorAnalysisPage from "../../components/authors/AuthorAnalysisPage";
import {
  DEMO_AUTHOR_NAMES,
  DEMO_NOTICE,
  resolveSelectedAuthorNames,
} from "./mockAuthorInsightsData";
import * as analysisApi from "../../api/analysisApi";
import { clearPublicationsPageCache } from "../../components/authors/authorAnalysisCache";

vi.mock("react-apexcharts", () => ({
  default: ({ series, options, type }) => (
    <div
      data-testid="apex-chart-mock"
      data-chart-type={type}
      data-series={JSON.stringify(series)}
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
    display_name: "Eneet Kaur",
  },
  {
    canonical_author_id: "c2",
    provider: "openalex",
    provider_author_id: "A2",
    display_name: "Mark M. Wilde",
  },
];

class IntersectionObserverStub {
  observe() {}

  disconnect() {}

  unobserve() {}
}

function renderInsights(initialEntry) {
  return render(
    <ThemeProvider theme={theme}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/analyze/authors" element={<AuthorAnalysisPage />} />
          <Route path="/analyze/authors/insights" element={<AuthorInsightsPage />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("resolveSelectedAuthorNames", () => {
  it("falls back to demo authors when opened directly", () => {
    expect(resolveSelectedAuthorNames(undefined)).toEqual(DEMO_AUTHOR_NAMES);
    expect(resolveSelectedAuthorNames({})).toEqual(DEMO_AUTHOR_NAMES);
  });

  it("uses author names from router state when available", () => {
    expect(resolveSelectedAuthorNames({ authors: AUTHORS })).toEqual([
      "Eneet Kaur",
      "Mark M. Wilde",
    ]);
  });
});

describe("AuthorInsightsPage", () => {
  beforeEach(() => {
    clearPublicationsPageCache();
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
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    clearPublicationsPageCache();
  });

  it("navigates from Analysis button with selected authors", async () => {
    renderInsights({
      pathname: "/analyze/authors",
      state: { authors: AUTHORS },
    });

    await waitFor(() => {
      expect(screen.getByTestId("open-author-insights")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("open-author-insights"));

    expect(await screen.findByTestId("author-insights-page")).toBeInTheDocument();
    expect(screen.getByText("Author Collaboration Analysis")).toBeInTheDocument();
    const chips = screen.getByTestId("selected-author-chips");
    expect(within(chips).getByText("Eneet Kaur")).toBeInTheDocument();
    expect(within(chips).getByText("Mark M. Wilde")).toBeInTheDocument();
  });

  it("uses demo authors when opened directly without state", () => {
    renderInsights("/analyze/authors/insights");

    expect(screen.getByTestId("author-insights-page")).toBeInTheDocument();
    const chips = screen.getByTestId("selected-author-chips");
    DEMO_AUTHOR_NAMES.forEach((name) => {
      expect(within(chips).getByText(name)).toBeInTheDocument();
    });
  });

  it("renders demo-data notice and badge", () => {
    renderInsights("/analyze/authors/insights");

    expect(screen.getByTestId("insights-demo-notice")).toHaveTextContent(DEMO_NOTICE);
    expect(screen.getByTestId("demo-data-badge")).toHaveTextContent("Demo data");
  });

  it("renders summary metrics with expected demo values", () => {
    renderInsights("/analyze/authors/insights");

    const cards = screen.getByTestId("insights-metric-cards");
    expect(within(cards).getByTestId("metric-card-totalUniquePublications")).toHaveTextContent(
      "186",
    );
    expect(within(cards).getByTestId("metric-card-sharedByTwoOrMore")).toHaveTextContent("47");
    expect(within(cards).getByTestId("metric-card-sharedByAll")).toHaveTextContent("9");
    expect(
      within(cards).getByTestId("metric-card-multiInstitutionPublications"),
    ).toHaveTextContent("38");
    expect(within(cards).getByTestId("metric-card-sharedByTwoOrMore")).toHaveTextContent("25.3%");
  });

  it("updates publication preview when a combination row is selected", () => {
    renderInsights("/analyze/authors/insights");

    fireEvent.click(screen.getByTestId("combination-row-a+b+c"));

    const preview = screen.getByTestId("insights-publication-preview");
    expect(preview).toHaveTextContent("All selected authors");
    expect(preview).toHaveTextContent("Multipartite quantum channel discrimination");
  });

  it("renders yearly collaboration chart with 2019–2026 categories", () => {
    renderInsights("/analyze/authors/insights");

    expect(screen.getByTestId("collaboration-year-chart")).toBeInTheDocument();
    expect(screen.getByText("Collaborative publications by year")).toBeInTheDocument();

    const charts = screen.getAllByTestId("apex-chart-mock");
    const yearChart = charts.find((node) => {
      const categories = JSON.parse(node.getAttribute("data-categories") || "[]");
      return categories.includes(2019) && categories.includes(2026);
    });
    expect(yearChart).toBeTruthy();
    expect(JSON.parse(yearChart.getAttribute("data-categories"))).toEqual([
      2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026,
    ]);
  });

  it("renders institution partnership table rows", () => {
    renderInsights("/analyze/authors/insights");

    const table = screen.getByTestId("institution-partnership-table");
    expect(within(table).getByText("University of Arizona × LSU")).toBeInTheDocument();
    expect(within(table).getByText("Cambridge × UTS")).toBeInTheDocument();
    expect(within(table).getByText("12")).toBeInTheDocument();
  });

  it("renders citation activity chart and summary values", () => {
    renderInsights("/analyze/authors/insights");

    const section = screen.getByTestId("citation-activity-chart");
    expect(within(section).getByText("Citation activity of selected publications")).toBeInTheDocument();
    expect(within(section).getByText("4,540")).toBeInTheDocument();
    expect(within(section).getByText("24.4")).toBeInTheDocument();
    expect(within(section).getByText(/Quantum channels with memory/)).toBeInTheDocument();
  });

  it("renders publication preview rows for the default combination", () => {
    renderInsights("/analyze/authors/insights");

    const preview = screen.getByTestId("insights-publication-preview");
    expect(preview).toHaveTextContent("Eneet Kaur + Mark M. Wilde");
    expect(preview).toHaveTextContent("Amortized entanglement of a quantum channel");
    expect(preview).toHaveTextContent("Physical Review A");
  });

  it("returns to publications via Back to Publications", async () => {
    renderInsights({
      pathname: "/analyze/authors/insights",
      state: { authors: AUTHORS, authorNames: ["Eneet Kaur", "Mark M. Wilde"] },
    });

    fireEvent.click(screen.getAllByRole("button", { name: "Back to Publications" })[0]);
    await waitFor(() => {
      expect(screen.getByTestId("open-author-insights")).toBeInTheDocument();
    });
  });
});
