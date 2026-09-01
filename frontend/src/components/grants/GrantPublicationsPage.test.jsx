import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ThemeProvider, createTheme } from "@mui/material/styles";

import GrantPublicationsPage, {
  clearGrantPublicationsPageCache,
} from "./GrantPublicationsPage";
import * as grantsApi from "../../api/grantsApi";
import * as authorSummaryApi from "../../api/authorSummaryApi";
import * as savedSearchesApi from "../../features/savedSearches/savedSearchesApi";
import { clearAuthorSummaryCache } from "../authors/authorSummaryCache";

vi.mock("react-apexcharts", () => ({
  default: () => <div data-testid="apex-chart-mock" />,
}));

const theme = createTheme({ colorSchemes: { light: true, dark: true } });

const BASE_RESPONSE = {
  items: [
    {
      id: "g1",
      title: "Grant Paper",
      authors: [
        {
          name: "Ada Lovelace",
          canonical_author_id: "aaaaaaaa-1111-4111-8111-111111111111",
          provider_ids: { openalex: ["A1234567890"], orcid: [], arxiv: [] },
          institutions: [
            {
              name: "Analytical Engine Institute",
              department: "Department of Mathematics",
              country_code: "GB",
            },
          ],
          countries: ["GB"],
        },
      ],
      publication_year: 2022,
    },
  ],
  timeline: {
    interval: "year",
    total_dated_publications: 1,
    total_matching_publications: 1,
    items: [{ period: "2022", label: "2022", count: 1 }],
  },
  facets: {
    sources: [{ value: "openalex", label: "OpenAlex", count: 1 }],
    venues: [],
    grants: [],
    authors: [],
  },
  next_cursor: null,
  has_more: false,
  funder_name: "NIH",
  verified: true,
  match_type: "exact",
};

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

function renderPage(path = "/grants/R01GM123456?provider=openalex") {
  return render(
    <ThemeProvider theme={theme}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/grants/:grantNumber" element={<GrantPublicationsPage />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("GrantPublicationsPage filters", () => {
  beforeEach(() => {
    clearGrantPublicationsPageCache();
    clearAuthorSummaryCache();
    vi.stubGlobal("IntersectionObserver", IntersectionObserverStub);
    vi.spyOn(grantsApi, "fetchGrantPublications").mockResolvedValue(BASE_RESPONSE);
    vi.spyOn(savedSearchesApi, "saveSavedSearch").mockResolvedValue({ id: "saved-grant" });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    clearGrantPublicationsPageCache();
    clearAuthorSummaryCache();
  });

  it("does not refetch when draft year filters change until Apply", async () => {
    renderPage();
    await waitFor(() => expect(grantsApi.fetchGrantPublications).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    fireEvent.change(screen.getByLabelText("From year"), { target: { value: "2020" } });
    fireEvent.change(screen.getByLabelText("To year"), { target: { value: "2024" } });
    await sleep(50);

    expect(grantsApi.fetchGrantPublications).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Apply filters" })).toBeEnabled();
  });

  it("saves the current grant search definition", async () => {
    renderPage();
    await waitFor(() => expect(grantsApi.fetchGrantPublications).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Save search" }));

    await waitFor(() => {
      expect(savedSearchesApi.saveSavedSearch).toHaveBeenCalledWith(
        expect.objectContaining({
          search_type: "grant",
          payload: {
            grant_number: "R01GM123456",
            provider: "openalex",
            filters: {},
          },
          metadata: expect.objectContaining({
            funder_name: "NIH",
            verified: true,
            match_type: "exact",
          }),
        }),
      );
    });
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("applies filters with exactly one refresh including filters", async () => {
    renderPage();
    await waitFor(() => expect(grantsApi.fetchGrantPublications).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    fireEvent.change(screen.getByLabelText("From year"), { target: { value: "2020" } });
    fireEvent.change(screen.getByLabelText("To year"), { target: { value: "2024" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));

    await waitFor(() => expect(grantsApi.fetchGrantPublications).toHaveBeenCalledTimes(2));

    const lastCall =
      grantsApi.fetchGrantPublications.mock.calls[
        grantsApi.fetchGrantPublications.mock.calls.length - 1
      ][0];
    expect(lastCall.cursor).toBeNull();
    expect(lastCall.filters).toEqual({
      from_year: 2020,
      to_year: 2024,
    });
    expect(screen.getByText("2020–2024")).toBeInTheDocument();
  });

  it("sorts grant publications and preserves filter context", async () => {
    renderPage();
    await waitFor(() => expect(grantsApi.fetchGrantPublications).toHaveBeenCalledTimes(1));
    expect(grantsApi.fetchGrantPublications.mock.calls[0][0]).toMatchObject({
      sortBy: "year",
      sortDirection: "desc",
      cursor: null,
    });

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    fireEvent.change(screen.getByLabelText("From year"), { target: { value: "2020" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(grantsApi.fetchGrantPublications).toHaveBeenCalledTimes(2));

    fireEvent.click(screen.getByRole("button", { name: /Citations/i }));
    await waitFor(() => expect(grantsApi.fetchGrantPublications).toHaveBeenCalledTimes(3));

    expect(grantsApi.fetchGrantPublications.mock.calls[2][0]).toMatchObject({
      grantNumber: "R01GM123456",
      provider: "openalex",
      filters: { from_year: 2020 },
      sortBy: "citations",
      sortDirection: "asc",
      cursor: null,
    });
  });

  it("resets filters with one unfiltered refresh", async () => {
    renderPage();
    await waitFor(() => expect(grantsApi.fetchGrantPublications).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    fireEvent.change(screen.getByLabelText("From year"), { target: { value: "2020" } });
    fireEvent.change(screen.getByLabelText("To year"), { target: { value: "2024" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(grantsApi.fetchGrantPublications).toHaveBeenCalledTimes(2));

    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    await waitFor(() => expect(grantsApi.fetchGrantPublications).toHaveBeenCalledTimes(3));

    const lastCall =
      grantsApi.fetchGrantPublications.mock.calls[
        grantsApi.fetchGrantPublications.mock.calls.length - 1
      ][0];
    expect(lastCall.filters == null || Object.keys(lastCall.filters || {}).length === 0).toBe(
      true,
    );
  });

  it("orders filters before chart before table", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("Grant Paper")).toBeInTheDocument());

    const chart = screen.getByTestId("author-publication-trend-chart");
    const filters = screen.getByTestId("publication-filters");
    const table = screen.getByRole("table", { name: "Author publications" });

    expect(filters.compareDocumentPosition(chart) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(chart.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("Publications over time")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show filters" })).toBeInTheDocument();
  });

  it("shows Authors autocomplete instead of Grant in grant filter mode", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("Grant Paper")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    expect(screen.getByLabelText("Authors")).toBeInTheDocument();
    expect(screen.queryByLabelText("Grant")).not.toBeInTheDocument();
  });

  it("uses the shared author popover in the grant publications table", async () => {
    vi.spyOn(authorSummaryApi, "fetchAuthorSummaryByCanonicalId").mockResolvedValue({
      id: "aaaaaaaa-1111-4111-8111-111111111111",
      display_name: "Ada Lovelace",
      aliases: [],
      institutions: [
        {
          name: "Analytical Engine Institute",
          department: "Department of Mathematics",
          country_code: "GB",
          current: true,
        },
      ],
      works_count: 12,
      citation_count: 340,
      h_index: 7,
      orcid: null,
      providers: ["openalex"],
    });

    renderPage();
    const authorButton = await screen.findByRole("button", {
      name: "View profile for Ada Lovelace",
    });
    fireEvent.mouseEnter(authorButton);

    await waitFor(() => {
      expect(screen.getByText("Analytical Engine Institute")).toBeInTheDocument();
    });
    expect(screen.getByText("Department")).toBeInTheDocument();
    expect(screen.getByText("Department of Mathematics")).toBeInTheDocument();
    expect(screen.getByText("Country")).toBeInTheDocument();
    expect(screen.getByText("GB")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("340")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("N/A")).toBeInTheDocument();
    expect(screen.getByText("OpenAlex")).toBeInTheDocument();
  });

  it("exports CSV with applied filters and route grant number", async () => {
    const exportSpy = vi.spyOn(grantsApi, "exportGrantPublicationsCsv").mockResolvedValue({
      data: new Blob(["a,b\n"]),
      headers: {
        "content-disposition":
          'attachment; filename="grant-R01GM123456-publications-2026-08-04.csv"',
      },
    });
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:mock"),
      revokeObjectURL: vi.fn(),
    });

    renderPage();
    await waitFor(() => expect(screen.getByTestId("download-csv-button")).toBeEnabled());

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    fireEvent.change(screen.getByLabelText("From year"), { target: { value: "2020" } });
    fireEvent.change(screen.getByLabelText("To year"), { target: { value: "2024" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(grantsApi.fetchGrantPublications).toHaveBeenCalledTimes(2));

    fireEvent.click(screen.getByTestId("download-csv-button"));
    await waitFor(() => expect(exportSpy).toHaveBeenCalledTimes(1));
    expect(exportSpy.mock.calls[0][0]).toMatchObject({
      grantNumber: "R01GM123456",
      provider: "openalex",
      filters: { from_year: 2020, to_year: 2024 },
    });
  });

  it("disables Download CSV for empty grant results", async () => {
    grantsApi.fetchGrantPublications.mockResolvedValueOnce({
      ...BASE_RESPONSE,
      items: [],
      timeline: null,
    });
    renderPage();
    await waitFor(() => expect(screen.getByTestId("download-csv-button")).toBeDisabled());
  });
});
