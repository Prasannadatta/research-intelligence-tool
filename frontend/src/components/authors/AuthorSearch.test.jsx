import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider, createTheme } from "@mui/material/styles";

import AuthorSearch from "./AuthorSearch";
import {
  ENTITY_TYPES,
  FALLBACK_CAPABILITIES,
} from "../../api/searchApi";
import * as searchApi from "../../api/searchApi";

const theme = createTheme({ colorSchemes: { light: true, dark: true } });

function renderSearch(props = {}) {
  return render(
    <ThemeProvider theme={theme}>
      <MemoryRouter>
        <AuthorSearch entityType={ENTITY_TYPES.AUTHORS} {...props} />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

async function typeAuthorQuery(value) {
  const input = screen.getByPlaceholderText(/Search authors/i);
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value } });
  return input;
}

describe("AuthorSearch UI", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.spyOn(searchApi, "fetchSearchCapabilities").mockResolvedValue(
      FALLBACK_CAPABILITIES,
    );
    vi.spyOn(searchApi, "unifiedSearch").mockResolvedValue({
      query: "lin lin",
      entity_type: "authors",
      source: "all",
      results: [
        {
          result_id: "openalex:A1",
          result_type: "author",
          openalex_id: "A1",
          display_name: "Lin Lin",
          source: "openalex",
          primary_institution: {
            id: "I1",
            name: "University of California, Berkeley",
          },
          topics: [{ id: "T1", name: "Machine Learning" }],
          works_count: 10,
        },
        {
          result_id: "orcid:0000-0001-6860-9566",
          result_type: "author",
          orcid: "0000-0001-6860-9566",
          display_name: "Lin Lin ORCID",
          source: "orcid",
          primary_institution: { name: "UC Berkeley" },
          works_count: 4,
        },
      ],
      next_cursor: null,
      has_more: false,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("shows All as the selected source and offers OpenAlex and ORCID", async () => {
    renderSearch();
    await waitFor(() => {
      expect(screen.getByLabelText("Search source")).toHaveTextContent("All");
    });

    fireEvent.mouseDown(screen.getByLabelText("Search source"));
    expect(screen.getByRole("option", { name: "All" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "OpenAlex" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "ORCID" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "arXiv" })).not.toBeInTheDocument();
  });

  it("closes the results dropdown on outside click and keeps it closed", async () => {
    renderSearch();
    await typeAuthorQuery("Lin Lin");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(450);
    });

    await waitFor(() => {
      expect(screen.getByText("Lin Lin ORCID")).toBeInTheDocument();
    });
    expect(screen.getByRole("listbox")).toBeInTheDocument();

    // Simulate document click-away used by MUI Autocomplete.
    fireEvent.mouseDown(document.body);
    fireEvent.click(document.body);

    await waitFor(() => {
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    });

    // Late search resolution must not reopen after dismiss.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("closes on outside click for OpenAlex and ORCID sources", async () => {
    renderSearch();
    await waitFor(() => {
      expect(screen.getByLabelText("Search source")).toBeInTheDocument();
    });

    for (const sourceLabel of ["OpenAlex", "ORCID"]) {
      fireEvent.mouseDown(screen.getByLabelText("Search source"));
      fireEvent.click(screen.getByRole("option", { name: sourceLabel }));

      await typeAuthorQuery("Lin Lin");
      await act(async () => {
        await vi.advanceTimersByTimeAsync(450);
      });

      await waitFor(() => {
        expect(screen.getByRole("listbox")).toBeInTheDocument();
      });

      fireEvent.mouseDown(document.body);
      await waitFor(() => {
        expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
      });
    }
  });

  it("shows source-aware empty results for ORCID", async () => {
    searchApi.unifiedSearch.mockResolvedValue({
      query: "zzz author",
      entity_type: "authors",
      source: "orcid",
      results: [],
      next_cursor: null,
      has_more: false,
    });

    renderSearch();
    await waitFor(() => {
      expect(screen.getByLabelText("Search source")).toBeInTheDocument();
    });

    fireEvent.mouseDown(screen.getByLabelText("Search source"));
    fireEvent.click(screen.getByRole("option", { name: "ORCID" }));

    await typeAuthorQuery("zzz author");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(450);
    });

    await waitFor(() => {
      expect(
        screen.getByText("No matching authors in ORCID."),
      ).toBeInTheDocument();
    });
  });
});
