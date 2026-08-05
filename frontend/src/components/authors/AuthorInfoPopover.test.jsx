import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider, createTheme } from "@mui/material/styles";

import AuthorPublicationsTable from "./AuthorPublicationsTable";
import { AuthorInfoPopoverProvider, AuthorNameLink } from "./AuthorInfoPopover";
import { clearAuthorSummaryCache, fetchAuthorSummary } from "./authorSummaryCache";
import * as authorSummaryApi from "../../api/authorSummaryApi";

vi.mock("../../api/authorSummaryApi");

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const OPEN_DELAY = 250;
const CLOSE_DELAY = 250;

const theme = createTheme({ colorSchemes: { light: true, dark: true } });

const AUTHOR = {
  name: "Jane Doe",
  canonicalAuthorId: "canonical-1",
  providerIds: { openalex: ["A1234567890"], orcid: [], arxiv: [] },
  unresolved: false,
};

const SUMMARY = {
  id: "canonical-1",
  display_name: "Jane Doe",
  aliases: ["J. Doe"],
  institutions: [
    {
      name: "University of California, Berkeley",
      department: "Department of Biology",
      current: true,
      sources: ["openalex"],
    },
  ],
  works_count: 84,
  citation_count: 1520,
  h_index: 19,
  topics: ["Genomics"],
  providers: ["openalex"],
  updated_at: "2025-01-01T00:00:00Z",
};

function renderWithProvider(ui) {
  return render(
    <ThemeProvider theme={theme}>
      <MemoryRouter>
        <AuthorInfoPopoverProvider>{ui}</AuthorInfoPopoverProvider>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

function getAuthorButton(label = "View profile for Jane Doe") {
  return screen.getByRole("button", { name: label });
}

async function openAuthorPopover(button = getAuthorButton()) {
  fireEvent.mouseEnter(button);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(OPEN_DELAY);
  });
  await waitFor(() => {
    expect(screen.getByRole("presentation")).toBeInTheDocument();
  });
}

describe("authorSummaryCache", () => {
  beforeEach(() => {
    clearAuthorSummaryCache();
    vi.mocked(authorSummaryApi.fetchAuthorSummaryByCanonicalId).mockClear();
    vi.mocked(authorSummaryApi.fetchAuthorSummaryByOpenAlexId).mockClear();
    vi.mocked(authorSummaryApi.fetchAuthorSummaryByCanonicalId).mockResolvedValue(SUMMARY);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    clearAuthorSummaryCache();
  });

  it("deduplicates concurrent summary requests for the same author", async () => {
    let resolveRequest;
    const pending = new Promise((resolve) => {
      resolveRequest = resolve;
    });
    vi.mocked(authorSummaryApi.fetchAuthorSummaryByCanonicalId).mockReturnValue(pending);

    const first = fetchAuthorSummary(AUTHOR);
    const second = fetchAuthorSummary(AUTHOR);

    resolveRequest(SUMMARY);

    await Promise.all([first, second]);
    expect(authorSummaryApi.fetchAuthorSummaryByCanonicalId).toHaveBeenCalledTimes(1);
  });
});

describe("AuthorInfoPopover", () => {
  beforeEach(() => {
    clearAuthorSummaryCache();
    vi.mocked(authorSummaryApi.fetchAuthorSummaryByCanonicalId).mockClear();
    vi.mocked(authorSummaryApi.fetchAuthorSummaryByOpenAlexId).mockClear();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(authorSummaryApi.fetchAuthorSummaryByCanonicalId).mockResolvedValue(SUMMARY);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    clearAuthorSummaryCache();
  });

  it("opens the popover once after the hover delay", async () => {
    renderWithProvider(<AuthorNameLink author={AUTHOR} name="Jane Doe" />);
    await openAuthorPopover();

    expect(screen.getByText("University of California, Berkeley")).toBeInTheDocument();
    expect(authorSummaryApi.fetchAuthorSummaryByCanonicalId).toHaveBeenCalledTimes(1);
  });

  it("does not repeatedly reopen while remaining over the author", async () => {
    renderWithProvider(<AuthorNameLink author={AUTHOR} name="Jane Doe" />);
    const button = getAuthorButton();

    fireEvent.mouseEnter(button);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(OPEN_DELAY);
    });
    await waitFor(() => expect(screen.getByText("Genomics")).toBeInTheDocument());

    fireEvent.mouseEnter(button);
    fireEvent.mouseEnter(button);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(OPEN_DELAY * 2);
    });

    expect(screen.getByText("Genomics")).toBeInTheDocument();
    expect(authorSummaryApi.fetchAuthorSummaryByCanonicalId).toHaveBeenCalledTimes(1);
  });

  it("opens the popover on keyboard focus without hover delay", async () => {
    renderWithProvider(<AuthorNameLink author={AUTHOR} name="Jane Doe" />);

    fireEvent.focus(getAuthorButton());

    await waitFor(() => {
      expect(screen.getByText("Loading author details…")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText("Genomics")).toBeInTheDocument();
    });
    expect(authorSummaryApi.fetchAuthorSummaryByCanonicalId).toHaveBeenCalledTimes(1);
  });

  it("shows loading state before metadata finishes", async () => {
    let resolveRequest;
    const pending = new Promise((resolve) => {
      resolveRequest = resolve;
    });
    vi.mocked(authorSummaryApi.fetchAuthorSummaryByCanonicalId).mockReturnValue(pending);

    renderWithProvider(<AuthorNameLink author={AUTHOR} name="Jane Doe" />);
    await openAuthorPopover();

    expect(screen.getByText("Loading author details…")).toBeInTheDocument();

    await act(async () => {
      resolveRequest(SUMMARY);
    });

    await waitFor(() => {
      expect(screen.getByText("Genomics")).toBeInTheDocument();
    });
  });

  it("keeps the popover open when moving from the trigger into the popover", async () => {
    renderWithProvider(<AuthorNameLink author={AUTHOR} name="Jane Doe" />);
    const button = getAuthorButton();

    await openAuthorPopover(button);
    fireEvent.mouseLeave(button);
    fireEvent.mouseEnter(screen.getByText("Genomics"));

    expect(screen.getByText("Genomics")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(CLOSE_DELAY + 50);
    });

    expect(screen.getByText("Genomics")).toBeInTheDocument();
  });

  it("closes once after leaving both trigger and popover", async () => {
    renderWithProvider(<AuthorNameLink author={AUTHOR} name="Jane Doe" />);
    const button = getAuthorButton();

    await openAuthorPopover(button);
    fireEvent.mouseLeave(button);
    fireEvent.mouseLeave(screen.getByText("Genomics"));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(CLOSE_DELAY + 20);
    });

    await waitFor(() => {
      expect(screen.queryByText("Genomics")).not.toBeInTheDocument();
    });
  });

  it("keeps the popover open while metadata updates", async () => {
    let resolveRequest;
    const pending = new Promise((resolve) => {
      resolveRequest = resolve;
    });
    vi.mocked(authorSummaryApi.fetchAuthorSummaryByCanonicalId).mockReturnValue(pending);

    renderWithProvider(<AuthorNameLink author={AUTHOR} name="Jane Doe" />);
    await openAuthorPopover();

    expect(screen.getByText("Loading author details…")).toBeInTheDocument();

    await act(async () => {
      resolveRequest(SUMMARY);
    });

    await waitFor(() => {
      expect(screen.getByText("Genomics")).toBeInTheDocument();
    });
    expect(screen.getByRole("presentation")).toBeInTheDocument();
  });

  it("does not close when metadata finishes loading", async () => {
    renderWithProvider(<AuthorNameLink author={AUTHOR} name="Jane Doe" />);
    const button = getAuthorButton();

    fireEvent.mouseEnter(button);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(OPEN_DELAY);
    });

    await waitFor(() => expect(screen.getByText("Genomics")).toBeInTheDocument());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    expect(screen.getByText("Genomics")).toBeInTheDocument();
  });

  it("reuses cached metadata for repeated hovers", async () => {
    renderWithProvider(<AuthorNameLink author={AUTHOR} name="Jane Doe" />);
    const button = getAuthorButton();

    await openAuthorPopover(button);
    expect(screen.getByText("Genomics")).toBeInTheDocument();

    fireEvent.mouseLeave(button);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CLOSE_DELAY + 20);
    });

    fireEvent.mouseEnter(button);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(OPEN_DELAY);
    });

    expect(await screen.findByText("Genomics")).toBeInTheDocument();
    expect(authorSummaryApi.fetchAuthorSummaryByCanonicalId).toHaveBeenCalledTimes(1);
  });

  it("shows an error state when the API fails", async () => {
    vi.mocked(authorSummaryApi.fetchAuthorSummaryByCanonicalId).mockRejectedValue(
      new Error("network"),
    );

    renderWithProvider(<AuthorNameLink author={AUTHOR} name="Jane Doe" />);
    await openAuthorPopover();

    expect(await screen.findByText("Author information could not be loaded")).toBeInTheDocument();
  });

  it("opens for authors without canonical IDs and shows the empty state", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    renderWithProvider(
      <AuthorNameLink
        author={{
          name: "Name Only Author",
          canonicalAuthorId: null,
          providerIds: { openalex: [], orcid: [], arxiv: [] },
          unresolved: true,
        }}
        name="Name Only Author"
      />,
    );

    await openAuthorPopover(
      screen.getByRole("button", { name: "Author details for Name Only Author" }),
    );

    expect(screen.getByText("No additional author information available")).toBeInTheDocument();
    expect(authorSummaryApi.fetchAuthorSummaryByCanonicalId).not.toHaveBeenCalled();
    expect(warnSpy).toHaveBeenCalled();

    warnSpy.mockRestore();
  });

  it("navigates to the author profile on click", () => {
    mockNavigate.mockClear();
    renderWithProvider(<AuthorNameLink author={AUTHOR} name="Jane Doe" />);
    fireEvent.click(getAuthorButton());
    expect(mockNavigate).toHaveBeenCalledWith("/authors/canonical-1");
  });

  it("does not flicker open and closed while hovered", async () => {
    renderWithProvider(<AuthorNameLink author={AUTHOR} name="Jane Doe" />);
    const button = getAuthorButton();

    fireEvent.mouseEnter(button);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(OPEN_DELAY);
    });

    await waitFor(() => expect(screen.getByText("Genomics")).toBeInTheDocument());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(screen.getByText("Genomics")).toBeInTheDocument();
    expect(screen.getByRole("presentation")).toBeInTheDocument();
  });
});

describe("AuthorPublicationsTable author popovers", () => {
  beforeEach(() => {
    clearAuthorSummaryCache();
    vi.mocked(authorSummaryApi.fetchAuthorSummaryByCanonicalId).mockClear();
    vi.mocked(authorSummaryApi.fetchAuthorSummaryByOpenAlexId).mockClear();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(authorSummaryApi.fetchAuthorSummaryByCanonicalId).mockResolvedValue({
      id: "auth-a",
      display_name: "Alice Alpha",
      aliases: [],
      institutions: [],
      topics: [],
      providers: ["openalex"],
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    clearAuthorSummaryCache();
  });

  it("renders interactive author names in the table", async () => {
    render(
      <ThemeProvider theme={theme}>
        <MemoryRouter>
          <AuthorInfoPopoverProvider>
            <AuthorPublicationsTable
              works={[
                {
                  id: "work-1",
                  title: "Example",
                  authors: [
                    {
                      name: "Alice Alpha",
                      canonical_author_id: "auth-a",
                      provider_ids: { openalex: ["A9999999999"], orcid: [], arxiv: [] },
                    },
                  ],
                  analysis_match: { verified: true, method: "x" },
                },
              ]}
              loading={false}
              loadingMore={false}
              error={null}
              mode="single_author"
              sentinelRef={{ current: null }}
              emptyCopy={{ heading: "No publications found", body: "Nothing here." }}
              initialEmpty={false}
            />
          </AuthorInfoPopoverProvider>
        </MemoryRouter>
      </ThemeProvider>,
    );

    fireEvent.mouseEnter(screen.getByRole("button", { name: "View profile for Alice Alpha" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(OPEN_DELAY);
    });

    expect(authorSummaryApi.fetchAuthorSummaryByCanonicalId).toHaveBeenCalledWith(
      "auth-a",
      expect.any(Object),
    );
    expect(authorSummaryApi.fetchAuthorSummaryByCanonicalId).toHaveBeenCalledTimes(1);
  });

  it("stays stable when table props rerender while popover is open", async () => {
    const { rerender } = render(
      <ThemeProvider theme={theme}>
        <MemoryRouter>
          <AuthorInfoPopoverProvider>
            <AuthorPublicationsTable
              works={[
                {
                  id: "work-1",
                  title: "Example",
                  authors: [
                    {
                      name: "Alice Alpha",
                      canonical_author_id: "auth-a",
                      provider_ids: { openalex: ["A9999999999"], orcid: [], arxiv: [] },
                    },
                  ],
                  analysis_match: { verified: true, method: "x" },
                },
              ]}
              loading={false}
              loadingMore={false}
              error={null}
              mode="single_author"
              sentinelRef={{ current: null }}
              emptyCopy={{ heading: "No publications found", body: "Nothing here." }}
              initialEmpty={false}
            />
          </AuthorInfoPopoverProvider>
        </MemoryRouter>
      </ThemeProvider>,
    );

    const button = screen.getByRole("button", { name: "View profile for Alice Alpha" });
    fireEvent.mouseEnter(button);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(OPEN_DELAY);
    });

    rerender(
      <ThemeProvider theme={theme}>
        <MemoryRouter>
          <AuthorInfoPopoverProvider>
            <AuthorPublicationsTable
              works={[
                {
                  id: "work-1",
                  title: "Example updated",
                  authors: [
                    {
                      name: "Alice Alpha",
                      canonical_author_id: "auth-a",
                      provider_ids: { openalex: ["A9999999999"], orcid: [], arxiv: [] },
                    },
                  ],
                  analysis_match: { verified: true, method: "x" },
                },
              ]}
              loading={false}
              loadingMore
              error={null}
              mode="single_author"
              sentinelRef={{ current: null }}
              emptyCopy={{ heading: "No publications found", body: "Nothing here." }}
              initialEmpty={false}
            />
          </AuthorInfoPopoverProvider>
        </MemoryRouter>
      </ThemeProvider>,
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    expect(screen.getByRole("presentation")).toBeInTheDocument();
    expect(authorSummaryApi.fetchAuthorSummaryByCanonicalId).toHaveBeenCalledTimes(1);
  });
});
