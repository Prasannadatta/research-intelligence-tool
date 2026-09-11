import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";

import AuthorFilters from "./AuthorFilters";

vi.mock("../../api/searchApi", () => ({
  searchInstitutions: vi.fn(),
  searchTopics: vi.fn(),
}));

import { searchInstitutions, searchTopics } from "../../api/searchApi";

const theme = createTheme({ colorSchemes: { light: true, dark: true } });

function renderFilters(props = {}) {
  return render(
    <ThemeProvider theme={theme}>
      <AuthorFilters
        institution={null}
        topic={null}
        onInstitutionChange={vi.fn()}
        onTopicChange={vi.fn()}
        {...props}
      />
    </ThemeProvider>,
  );
}

describe("AuthorFilters", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    searchInstitutions.mockReset();
    searchTopics.mockReset();
    searchInstitutions.mockResolvedValue([
      {
        id: "I95457486",
        display_name: "University of California, Berkeley",
        country_code: "US",
        type: "education",
        works_count: 100,
      },
    ]);
    searchTopics.mockResolvedValue([
      {
        id: "T11948",
        display_name: "Machine Learning in Materials Science",
        description: "ML materials",
        works_count: 50,
      },
    ]);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("always shows Institution and Research area fields", () => {
    renderFilters();
    expect(screen.getByLabelText("Institution")).toBeInTheDocument();
    expect(screen.getByLabelText("Research area")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Optional: narrow OpenAlex results by institution or research area.",
      ),
    ).toBeInTheDocument();
  });

  it("loads institution options and selects one into a chip", async () => {
    const onInstitutionChange = vi.fn();
    renderFilters({ onInstitutionChange });

    fireEvent.change(screen.getByLabelText("Institution"), {
      target: { value: "Berkeley" },
    });
    await vi.advanceTimersByTimeAsync(350);

    await waitFor(() => {
      expect(searchInstitutions).toHaveBeenCalledWith(
        "Berkeley",
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
    });

    fireEvent.click(
      await screen.findByText("University of California, Berkeley"),
    );
    expect(onInstitutionChange).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "I95457486",
        display_name: "University of California, Berkeley",
      }),
    );
  });

  it("loads research-area options and selects one", async () => {
    const onTopicChange = vi.fn();
    renderFilters({ onTopicChange });

    fireEvent.change(screen.getByLabelText("Research area"), {
      target: { value: "machine learning" },
    });
    await vi.advanceTimersByTimeAsync(350);

    await waitFor(() => {
      expect(searchTopics).toHaveBeenCalledWith(
        "machine learning",
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
    });

    fireEvent.click(
      await screen.findByText("Machine Learning in Materials Science"),
    );
    expect(onTopicChange).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "T11948",
        display_name: "Machine Learning in Materials Science",
      }),
    );
  });

  it("shows chips for selected filters and clears them", () => {
    const onInstitutionChange = vi.fn();
    const onTopicChange = vi.fn();
    renderFilters({
      institution: {
        id: "I95457486",
        display_name: "University of California, Berkeley",
      },
      topic: {
        id: "T11948",
        display_name: "Machine Learning in Materials Science",
      },
      onInstitutionChange,
      onTopicChange,
    });

    expect(
      screen.getByText("Institution: University of California, Berkeley"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Research: Machine Learning in Materials Science"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Institution")).toBeEnabled();
    expect(screen.getByLabelText("Research area")).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(onInstitutionChange).toHaveBeenCalledWith(null);
    expect(onTopicChange).toHaveBeenCalledWith(null);
  });

  it("removes a single filter from its chip", () => {
    const onInstitutionChange = vi.fn();
    renderFilters({
      institution: {
        id: "I95457486",
        display_name: "University of California, Berkeley",
      },
      onInstitutionChange,
    });

    const chip = screen.getByText(
      "Institution: University of California, Berkeley",
    ).parentElement;
    const deleteButton = chip?.querySelector(".MuiChip-deleteIcon");
    expect(deleteButton).toBeTruthy();
    fireEvent.click(deleteButton);
    expect(onInstitutionChange).toHaveBeenCalledWith(null);
  });
});
