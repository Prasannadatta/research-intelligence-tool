import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider, createTheme } from "@mui/material/styles";

import SavedSearchEditDialog from "./SavedSearchEditDialog";
import * as savedSearchesApi from "./savedSearchesApi";
import * as searchApi from "../../api/searchApi";
import * as authorResolveApi from "../../api/authorResolveApi";
import { FALLBACK_CAPABILITIES } from "../../api/searchApi";

const theme = createTheme({ colorSchemes: { light: true, dark: true } });

const ITEM = {
  id: "author-1",
  search_type: "authors",
  display_name: "Author A",
  payload: {
    authors: [
      {
        canonical_author_id: "c1",
        display_name: "Author A",
        provider: "openalex",
        provider_author_id: "A1",
      },
    ],
    filters: {
      from_year: 2020,
      to_year: null,
      sources: [],
      institutions: [],
      venues: [],
      grant_numbers: [],
    },
  },
  applied_filters: {
    from_year: 2020,
    to_year: null,
    sources: [],
    institutions: [],
    venues: [],
    grant_numbers: [],
  },
};

function renderDialog(props = {}) {
  return render(
    <ThemeProvider theme={theme}>
      <MemoryRouter>
        <SavedSearchEditDialog
          open
          item={ITEM}
          onClose={vi.fn()}
          onSaved={vi.fn()}
          {...props}
        />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("SavedSearchEditDialog", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.spyOn(searchApi, "fetchSearchCapabilities").mockResolvedValue(FALLBACK_CAPABILITIES);
    vi.spyOn(searchApi, "unifiedSearch").mockResolvedValue({
      query: "author b",
      entity_type: "authors",
      source: "all",
      results: [
        {
          result_id: "openalex:A1",
          result_type: "author",
          openalex_id: "A1",
          display_name: "Author A",
          source: "openalex",
          primary_institution: { name: "UC Berkeley" },
        },
        {
          result_id: "openalex:A2",
          result_type: "author",
          openalex_id: "A2",
          display_name: "Author B",
          source: "openalex",
          primary_institution: { name: "MIT" },
          source_records: [{ provider: "openalex", provider_author_id: "A2" }],
        },
      ],
      next_cursor: null,
      has_more: false,
    });
    vi.spyOn(authorResolveApi, "resolveAuthorSelection").mockImplementation(async (item) => ({
      ...item,
      id: item.openalex_id === "A2" ? "c2" : "c1",
      canonical_author_id: item.openalex_id === "A2" ? "c2" : "c1",
      source_records: [
        { provider: "openalex", provider_author_id: item.openalex_id },
      ],
    }));
    vi.spyOn(savedSearchesApi, "patchSavedSearch").mockResolvedValue({
      ...ITEM,
      outcome: "updated",
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders a large dialog with clear sections and embedded author search", async () => {
    renderDialog();
    expect(screen.getByText("Edit saved search")).toBeInTheDocument();
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("Authors")).toBeInTheDocument();
    expect(screen.getByText("Filters")).toBeInTheDocument();
    expect(screen.getByLabelText("Add author search")).toBeInTheDocument();
    expect(screen.getByLabelText("Search source")).toBeInTheDocument();
    expect(screen.queryByLabelText("Search entity type")).not.toBeInTheDocument();
  });

  it("hides already-selected authors from add results and adds a new author", async () => {
    renderDialog();
    const input = screen.getByLabelText("Add author search");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "author b" } });

    await waitFor(() => {
      expect(searchApi.unifiedSearch).toHaveBeenCalled();
    });

    expect(await screen.findByText("Author B")).toBeInTheDocument();
    // Selected Author A is filtered out of options by shared identity keys.
    const options = screen.getAllByRole("option");
    expect(options.map((node) => node.textContent).join(" ")).toContain("Author B");
    expect(options.map((node) => node.textContent).join(" ")).not.toContain("Author A");

    fireEvent.click(screen.getByText("Author B"));

    await waitFor(() => {
      expect(screen.getByText("Author B")).toBeInTheDocument();
    });
    const authorSection = screen.getByText("Authors").closest("div");
    expect(within(authorSection).getByText("Author A")).toBeInTheDocument();
    expect(within(authorSection).getByText("Author B")).toBeInTheDocument();
  });

  it("removes an author and can re-add after removal", async () => {
    renderDialog();
    const chip = screen.getByText("Author A").closest(".MuiChip-root");
    fireEvent.click(within(chip).getByTestId("CancelIcon"));

    await waitFor(() => {
      expect(screen.queryByText("Author A")).not.toBeInTheDocument();
    });

    const input = screen.getByLabelText("Add author search");
    fireEvent.change(input, { target: { value: "author a" } });
    await waitFor(() => expect(searchApi.unifiedSearch).toHaveBeenCalled());
    expect(await screen.findByText("Author A")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Author A"));
    await waitFor(() => {
      expect(screen.getByText("Author A").closest(".MuiChip-root")).toBeTruthy();
    });
  });

  it("saves author updates and surfaces duplicate conflicts", async () => {
    const onSaved = vi.fn();
    const onClose = vi.fn();
    renderDialog({ onSaved, onClose });

    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => {
      expect(savedSearchesApi.patchSavedSearch).toHaveBeenCalledWith(
        "author-1",
        expect.objectContaining({
          authors: [
            expect.objectContaining({
              canonical_author_id: "c1",
              display_name: "Author A",
            }),
          ],
        }),
      );
    });
    expect(onSaved).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();

    savedSearchesApi.patchSavedSearch.mockRejectedValueOnce({
      response: { data: { detail: "A saved search with this configuration already exists." } },
    });
    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(
      await screen.findByText("A saved search with this configuration already exists."),
    ).toBeInTheDocument();
  });
});
