import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { StrictMode } from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ThemeProvider, createTheme } from "@mui/material/styles";

import AuthorDetailsPage from "./AuthorDetailsPage";
import { AuthorInfoPopoverProvider, AuthorNameLink } from "./AuthorInfoPopover";
import {
  clearAuthorSummaryCache,
  fetchAuthorDetails,
} from "./authorSummaryCache";
import * as authorSummaryApi from "../../api/authorSummaryApi";

vi.mock("../../api/authorSummaryApi");

const theme = createTheme({ colorSchemes: { light: true, dark: true } });

const DETAILS = {
  id: "canonical-1",
  display_name: "Jane Doe",
  aliases: ["J. Doe"],
  institutions: [
    {
      name: "UC Berkeley",
      department: "Biology",
      country_code: "US",
      current: true,
      sources: ["openalex"],
      years: { from: 2018, to: null },
    },
    {
      name: "Stanford",
      department: null,
      country_code: "US",
      current: false,
      sources: ["orcid"],
      years: { from: 2012, to: 2017 },
    },
  ],
  orcid: "0000-0002-1234-5678",
  provider_ids: {
    openalex: ["A1234567890"],
    orcid: ["0000-0002-1234-5678"],
    scopus: ["999"],
    arxiv: [],
  },
  topics: ["Genomics"],
  works_count: 84,
  citation_count: 1520,
  h_index: 19,
  providers: ["openalex", "orcid", "scopus"],
  updated_at: "2025-01-01T00:00:00Z",
  enrichment: {
    pending: ["orcid"],
    sources: { openalex: true, orcid: false, scopus: false },
  },
  grants: [
    {
      award_id: "ABC-123",
      funder_name: "NSF",
      provider: "openalex",
      verified: true,
      publication_count: 2,
    },
  ],
  publications: [
    {
      id: "work-1",
      title: "High Impact Paper",
      publication_year: 2024,
      journal: "Nature",
      citation_count: 100,
      citations_by_provider: { openalex: 100 },
      providers: ["openalex"],
      doi: "10.1000/hi",
      url: null,
      grants: [],
    },
  ],
  stored_publication_count: 1,
};

function renderDetails(initialPath = "/authors/canonical-1", { strict = false } = {}) {
  const tree = (
    <ThemeProvider theme={theme}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/authors/:id" element={<AuthorDetailsPage />} />
          <Route path="/analyze/authors" element={<div>Analyze</div>} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>
  );
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree);
}

describe("AuthorDetailsPage", () => {
  beforeEach(() => {
    clearAuthorSummaryCache();
    vi.clearAllMocks();
    authorSummaryApi.fetchAuthorDetailsByCanonicalId.mockResolvedValue(DETAILS);
    authorSummaryApi.enrichAuthorSummaryByCanonicalId.mockResolvedValue({
      ...DETAILS,
      enrichment: {
        pending: [],
        sources: { openalex: true, orcid: true, scopus: true },
        contacted: ["orcid"],
      },
    });
  });

  afterEach(() => {
    clearAuthorSummaryCache();
  });

  it("loads cached/local details and renders core sections", async () => {
    renderDetails();

    expect(await screen.findByRole("heading", { name: "Jane Doe" })).toBeInTheDocument();
    expect(screen.getByText(/Also known as: J\. Doe/)).toBeInTheDocument();
    expect(screen.getByText("A1234567890")).toBeInTheDocument();
    expect(screen.getByText("0000-0002-1234-5678")).toBeInTheDocument();
    expect(screen.getByText("999")).toBeInTheDocument();
    expect(screen.getByTestId("author-details-affiliations")).toHaveTextContent("Stanford");
    expect(screen.getByTestId("author-details-topics")).toHaveTextContent("Genomics");
    expect(screen.getByTestId("author-details-metrics")).toHaveTextContent("1,520");
    expect(screen.getByTestId("author-details-grants")).toHaveTextContent("ABC-123");
    expect(screen.getByTestId("author-details-publications")).toHaveTextContent("High Impact Paper");
    expect(authorSummaryApi.fetchAuthorDetailsByCanonicalId).toHaveBeenCalledWith("canonical-1");
  });

  it("does not stay stuck loading under StrictMode remounts", async () => {
    let resolveDetails;
    authorSummaryApi.fetchAuthorDetailsByCanonicalId.mockImplementation(
      () => new Promise((resolve) => {
        resolveDetails = resolve;
      }),
    );

    renderDetails("/authors/canonical-1", { strict: true });
    expect(screen.getByTestId("author-details-loading")).toBeInTheDocument();

    await waitFor(() => {
      expect(authorSummaryApi.fetchAuthorDetailsByCanonicalId).toHaveBeenCalled();
    });

    resolveDetails(DETAILS);

    expect(await screen.findByRole("heading", { name: "Jane Doe" })).toBeInTheDocument();
    expect(screen.queryByTestId("author-details-loading")).not.toBeInTheDocument();
  });

  it("shows an error with retry when details GET fails, without leaving the skeleton", async () => {
    authorSummaryApi.fetchAuthorDetailsByCanonicalId
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce(DETAILS);

    renderDetails();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Author details could not be loaded.",
    );
    expect(screen.queryByTestId("author-details-loading")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("heading", { name: "Jane Doe" })).toBeInTheDocument();
    expect(authorSummaryApi.fetchAuthorDetailsByCanonicalId).toHaveBeenCalledTimes(2);
    expect(authorSummaryApi.enrichAuthorSummaryByCanonicalId).toHaveBeenCalled();
  });

  it("keeps the page rendered when background enrichment fails", async () => {
    authorSummaryApi.enrichAuthorSummaryByCanonicalId.mockRejectedValue(
      new Error("enrich failed"),
    );

    renderDetails();
    expect(await screen.findByRole("heading", { name: "Jane Doe" })).toBeInTheDocument();
    expect(screen.queryByTestId("author-details-loading")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("lazy-enriches without blocking the first paint", async () => {
    let resolveEnrich;
    authorSummaryApi.enrichAuthorSummaryByCanonicalId.mockReturnValue(
      new Promise((resolve) => {
        resolveEnrich = resolve;
      }),
    );

    renderDetails();
    expect(await screen.findByRole("heading", { name: "Jane Doe" })).toBeInTheDocument();

    await waitFor(() => {
      expect(authorSummaryApi.enrichAuthorSummaryByCanonicalId).toHaveBeenCalled();
    });

    resolveEnrich({
      ...DETAILS,
      enrichment: {
        pending: [],
        sources: { openalex: true, orcid: true, scopus: true },
        contacted: ["orcid"],
      },
    });

    await waitFor(() => {
      expect(screen.getByText(/Enriched:/)).toBeInTheDocument();
    });
  });

  it("shows graceful empty states when optional fields are missing", async () => {
    authorSummaryApi.fetchAuthorDetailsByCanonicalId.mockResolvedValue({
      ...DETAILS,
      aliases: [],
      topics: [],
      grants: [],
      publications: [],
      stored_publication_count: 0,
      institutions: [],
      enrichment: { pending: [], sources: { openalex: true, orcid: true, scopus: true } },
    });

    renderDetails();
    expect(await screen.findByRole("heading", { name: "Jane Doe" })).toBeInTheDocument();
    expect(screen.getByText(/No affiliation data available/)).toBeInTheDocument();
    expect(screen.getByText(/No research areas available/)).toBeInTheDocument();
    expect(screen.getByText(/No grant\/funding links/)).toBeInTheDocument();
    expect(screen.getByText(/No stored publications yet/)).toBeInTheDocument();
  });

  it("reuses the details cache across loads", async () => {
    await fetchAuthorDetails("canonical-1");
    expect(authorSummaryApi.fetchAuthorDetailsByCanonicalId).toHaveBeenCalledTimes(1);

    renderDetails();
    expect(await screen.findByRole("heading", { name: "Jane Doe" })).toBeInTheDocument();
    expect(authorSummaryApi.fetchAuthorDetailsByCanonicalId).toHaveBeenCalledTimes(1);
  });
});

describe("Author details navigation from Analyze table", () => {
  beforeEach(() => {
    clearAuthorSummaryCache();
    vi.clearAllMocks();
    authorSummaryApi.fetchAuthorSummaryByCanonicalId.mockResolvedValue({
      id: "canonical-1",
      display_name: "Jane Doe",
      aliases: [],
      institutions: [],
      orcid: null,
      works_count: 1,
      citation_count: 0,
      h_index: 0,
      topics: [],
      providers: ["openalex"],
      enrichment: { pending: [], sources: { openalex: true } },
    });
    authorSummaryApi.fetchAuthorDetailsByCanonicalId.mockResolvedValue(DETAILS);
    authorSummaryApi.enrichAuthorSummaryByCanonicalId.mockResolvedValue(DETAILS);
  });

  it("opens details from the popover View details control, not the name click", async () => {
    render(
      <ThemeProvider theme={theme}>
        <MemoryRouter initialEntries={["/analyze/authors"]}>
          <AuthorInfoPopoverProvider>
            <Routes>
              <Route
                path="/analyze/authors"
                element={(
                  <AuthorNameLink
                    author={{
                      name: "Jane Doe",
                      canonicalAuthorId: "canonical-1",
                      providerIds: { openalex: ["A1"], orcid: [], arxiv: [] },
                    }}
                  />
                )}
              />
              <Route path="/authors/:id" element={<AuthorDetailsPage />} />
            </Routes>
          </AuthorInfoPopoverProvider>
        </MemoryRouter>
      </ThemeProvider>,
    );

    const nameButton = screen.getByRole("button", { name: /Author details for Jane Doe/ });
    fireEvent.click(nameButton);
    expect(screen.queryByTestId("author-details-page")).not.toBeInTheDocument();

    const viewDetails = await screen.findByRole("button", { name: "View details" });
    fireEvent.click(viewDetails);

    expect(await screen.findByTestId("author-details-page")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Jane Doe" })).toBeInTheDocument();
  });
});
