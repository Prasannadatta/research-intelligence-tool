import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ThemeProvider, createTheme } from "@mui/material/styles";

import AuthorAnalysisPage from "./AuthorAnalysisPage";
import AuthorPublicationsTable, { COLUMN_COUNT } from "./AuthorPublicationsTable";
import GrantPublicationsPage from "../grants/GrantPublicationsPage";
import { clearPublicationsPageCache } from "./authorAnalysisCache";
import * as analysisApi from "../../api/analysisApi";

vi.mock("react-apexcharts", () => ({
  default: () => <div data-testid="apex-chart-mock" />,
}));

const theme = createTheme({ colorSchemes: { light: true, dark: true } });

const FULL_WORK = {
  id: "work-1",
  title: "Quantum Entanglement in Practice",
  authors: [
    { name: "Alice Alpha", canonical_author_id: "auth-a" },
    { name: "Bob Beta" },
    { name: "Carol Gamma", canonical_author_id: "auth-c" },
    { name: "Dan Delta" },
    { name: "Eve Echo" },
  ],
  publication_date: "2024-06-15",
  journal: "Nature Physics",
  citation_count: 0,
  grants: [{ award_id: "R01GM111111" }, { award_id: "R01GM222222" }],
  providers: ["openalex", "arxiv"],
  source: "openalex",
  doi: "10.1000/example",
  arxiv_id: "2406.00001",
  url: "https://openalex.org/W1",
};

function renderTable(props = {}) {
  const sentinelRef = { current: null };
  return render(
    <ThemeProvider theme={theme}>
      <MemoryRouter>
        <AuthorPublicationsTable
          works={[]}
          loading={false}
          loadingMore={false}
          error={null}
          mode="single_author"
          sentinelRef={sentinelRef}
          emptyCopy={{
            heading: "No publications found",
            body: "Nothing here.",
          }}
          initialEmpty={false}
          {...props}
        />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("AuthorPublicationsTable", () => {
  it("renders publications as table rows", () => {
    renderTable({ works: [FULL_WORK] });

    expect(screen.getByRole("table", { name: "Author publications" })).toBeInTheDocument();
    expect(screen.getByText("Quantum Entanglement in Practice")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Title" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Authors" })).toBeInTheDocument();
  });

  it("shows the complete author list without truncation", () => {
    renderTable({ works: [FULL_WORK] });

    const row = screen.getByText("Quantum Entanglement in Practice").closest("tr");
    const authorsText = within(row).getAllByRole("cell")[1].textContent;

    expect(authorsText).toContain("Alice Alpha");
    expect(authorsText).toContain("Bob Beta");
    expect(authorsText).toContain("Carol Gamma");
    expect(authorsText).toContain("Dan Delta");
    expect(authorsText).toContain("Eve Echo");
    expect(authorsText).not.toMatch(/et al\./i);
  });

  it("renders missing metadata safely", () => {
    renderTable({
      works: [
        {
          id: "sparse-work",
          title: "Sparse Paper",
          authors: [],
          analysis_match: { verified: true, method: "x" },
        },
      ],
    });

    const row = screen.getByText("Sparse Paper").closest("tr");
    expect(row).toBeTruthy();
    expect(within(row).getAllByText("—").length).toBeGreaterThan(0);
  });

  it("renders grant and provider chips correctly", () => {
    renderTable({ works: [FULL_WORK] });

    expect(screen.getByText("R01GM111111")).toBeInTheDocument();
    expect(screen.getByText("R01GM222222")).toBeInTheDocument();
    expect(screen.getByText("OpenAlex")).toBeInTheDocument();
    expect(screen.getByText("arXiv")).toBeInTheDocument();
  });

  it("marks the searched grant and links secondary grants", () => {
    renderTable({
      works: [
        {
          ...FULL_WORK,
          grants: [
            {
              grant_number: "R01CA123456",
              normalized_grant_number: "r01ca123456",
              is_searched_grant: true,
            },
            {
              grant_number: "P30CA045508",
              normalized_grant_number: "p30ca045508",
              is_searched_grant: false,
            },
            {
              grant_number: "U01CA987654",
              normalized_grant_number: "u01ca987654",
              is_searched_grant: false,
            },
            {
              grant_number: "T32CA000001",
              normalized_grant_number: "t32ca000001",
              is_searched_grant: false,
            },
          ],
        },
      ],
      searchedGrantNumber: "R01CA123456",
      grantProvider: "openalex",
    });

    expect(screen.getByText("R01CA123456 · Matched")).toBeInTheDocument();
    expect(screen.getByText("P30CA045508")).toBeInTheDocument();
    expect(screen.getByText("+1 more")).toBeInTheDocument();
    expect(screen.queryByText("U01CA987654")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("+1 more"));
    expect(screen.getByText("U01CA987654")).toBeInTheDocument();
    expect(screen.getByText("T32CA000001")).toBeInTheDocument();

    const secondary = screen.getByText("P30CA045508").closest("a");
    expect(secondary).toHaveAttribute(
      "href",
      "/grants/P30CA045508?provider=openalex",
    );
  });

  it("mounts the infinite-scroll sentinel as a full-width table row", () => {
    const sentinelRef = { current: null };
    renderTable({ works: [FULL_WORK], sentinelRef });

    const sentinel = screen.getByTestId("publications-scroll-sentinel");
    expect(sentinel.tagName).toBe("TR");
    expect(sentinelRef.current).toBe(sentinel);
    expect(sentinel.querySelector("td")).toHaveAttribute("colspan", String(COLUMN_COUNT));
  });

  it("shows loading, empty, and error states spanning all columns", () => {
    const { rerender } = renderTable({ loading: true });
    expect(screen.getAllByRole("row").length).toBeGreaterThan(1);

    rerender(
      <ThemeProvider theme={theme}>
        <MemoryRouter>
          <AuthorPublicationsTable
            works={[]}
            loading={false}
            loadingMore={false}
            error="Something went wrong"
            mode="single_author"
            sentinelRef={{ current: null }}
            emptyCopy={{ heading: "No publications found", body: "Nothing here." }}
            initialEmpty={false}
          />
        </MemoryRouter>
      </ThemeProvider>,
    );
    let statusCell = screen.getByText("Something went wrong").closest("td");
    expect(statusCell).toHaveAttribute("colspan", String(COLUMN_COUNT));

    rerender(
      <ThemeProvider theme={theme}>
        <MemoryRouter>
          <AuthorPublicationsTable
            works={[]}
            loading={false}
            loadingMore={false}
            error={null}
            mode="single_author"
            sentinelRef={{ current: null }}
            emptyCopy={{ heading: "No publications found", body: "Nothing here." }}
            initialEmpty
          />
        </MemoryRouter>
      </ThemeProvider>,
    );
    statusCell = screen.getByText("No publications found").closest("td");
    expect(statusCell).toHaveAttribute("colspan", String(COLUMN_COUNT));
  });
});

describe("AuthorAnalysisPage infinite scroll", () => {
  const AUTHORS = [
    {
      canonical_author_id: "c1",
      provider: "openalex",
      provider_author_id: "A1",
      display_name: "John Smith",
    },
  ];

  beforeEach(() => {
    clearPublicationsPageCache();
    vi.spyOn(analysisApi, "fetchAuthorPublications");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    clearPublicationsPageCache();
  });

  it("appends rows without duplicates when loading more", async () => {
    let observerCallback;

    analysisApi.fetchAuthorPublications
      .mockResolvedValueOnce({
        mode: "single_author",
        authors: [AUTHORS[0]],
        items: [
          {
            id: "w1",
            title: "First Paper",
            publication_year: 2020,
            analysis_match: { verified: true, method: "x" },
          },
        ],
        timeline: {
          interval: "year",
          total_dated_publications: 2,
          total_matching_publications: 2,
          items: [{ period: "2020", label: "2020", count: 1 }],
        },
        next_cursor: "page-2",
        has_more: true,
        unsupported: false,
        unsupported_reason: null,
      })
      .mockResolvedValueOnce({
        mode: "single_author",
        authors: [AUTHORS[0]],
        items: [
          {
            id: "w1",
            title: "First Paper",
            publication_year: 2020,
            analysis_match: { verified: true, method: "x" },
          },
          {
            id: "w2",
            title: "Second Paper",
            publication_year: 2021,
            analysis_match: { verified: true, method: "x" },
          },
        ],
        timeline: null,
        next_cursor: null,
        has_more: false,
        unsupported: false,
        unsupported_reason: null,
      });

    class IntersectionObserverMock {
      constructor(callback) {
        observerCallback = callback;
      }

      observe = vi.fn();

      disconnect = vi.fn();

      unobserve = vi.fn();
    }

    vi.stubGlobal("IntersectionObserver", IntersectionObserverMock);

    render(
      <ThemeProvider theme={theme}>
        <MemoryRouter
          initialEntries={[
            { pathname: "/analyze/authors", state: { authors: [AUTHORS[0]] } },
          ]}
        >
          <Routes>
            <Route path="/analyze/authors" element={<AuthorAnalysisPage />} />
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    await waitFor(() => expect(screen.getByText("First Paper")).toBeInTheDocument());

    observerCallback([{ isIntersecting: true }]);
    await waitFor(() => expect(screen.getByText("Second Paper")).toBeInTheDocument());

    expect(screen.getAllByText("First Paper")).toHaveLength(1);
    expect(analysisApi.fetchAuthorPublications).toHaveBeenCalledTimes(2);
    expect(analysisApi.fetchAuthorPublications.mock.calls[1][0].cursor).toBe("page-2");
  });

  it("keeps the sentinel mounted after the chart renders", async () => {
    analysisApi.fetchAuthorPublications.mockResolvedValue({
      mode: "single_author",
      authors: [AUTHORS[0]],
      items: [
        {
          id: "w1",
          title: "First Paper",
          publication_year: 2020,
          analysis_match: { verified: true, method: "x" },
        },
      ],
      timeline: {
        interval: "year",
        total_dated_publications: 1,
        total_matching_publications: 1,
        items: [{ period: "2020", label: "2020", count: 1 }],
      },
      next_cursor: "page-2",
      has_more: true,
      unsupported: false,
      unsupported_reason: null,
    });

    render(
      <ThemeProvider theme={theme}>
        <MemoryRouter
          initialEntries={[
            { pathname: "/analyze/authors", state: { authors: [AUTHORS[0]] } },
          ]}
        >
          <Routes>
            <Route path="/analyze/authors" element={<AuthorAnalysisPage />} />
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    await waitFor(() => expect(screen.getByText("First Paper")).toBeInTheDocument());
    expect(screen.getByTestId("publications-scroll-sentinel")).toBeInTheDocument();
    expect(screen.getByText("Publications over time")).toBeInTheDocument();
  });
});

describe("Other publication pages", () => {
  it("renders grant publications with the shared publications table", async () => {
    const grantsApi = await import("../../api/grantsApi");
    const { clearGrantPublicationsPageCache } = await import("../grants/GrantPublicationsPage");
    clearGrantPublicationsPageCache();
    vi.spyOn(grantsApi, "fetchGrantPublications").mockResolvedValue({
      items: [{ id: "g1", title: "Grant Paper" }],
      timeline: null,
      facets: { sources: [], venues: [], grants: [], authors: [] },
      next_cursor: null,
      has_more: false,
      funder_name: null,
      verified: true,
      match_type: null,
    });

    render(
      <ThemeProvider theme={theme}>
        <MemoryRouter initialEntries={["/grants/R01GM123456"]}>
          <Routes>
            <Route path="/grants/:grantNumber" element={<GrantPublicationsPage />} />
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    await waitFor(() => expect(screen.getByText("Grant Paper")).toBeInTheDocument());
    expect(screen.getByRole("table", { name: "Author publications" })).toBeInTheDocument();
    clearGrantPublicationsPageCache();
  });
});
