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

  it("loads institution options via autocomplete and selects one", async () => {
    const onInstitutionChange = vi.fn();
    renderFilters({ onInstitutionChange });

    fireEvent.click(screen.getByRole("button", { name: "Filters" }));
    const input = screen.getByLabelText("Institution");
    fireEvent.change(input, { target: { value: "Berkeley" } });

    await vi.advanceTimersByTimeAsync(450);

    await waitFor(() => {
      expect(searchInstitutions).toHaveBeenCalledWith(
        "Berkeley",
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
    });

    const option = await screen.findByText("University of California, Berkeley");
    fireEvent.click(option);

    expect(onInstitutionChange).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "I95457486",
        display_name: "University of California, Berkeley",
      }),
    );
  });

  it("loads research-area options via autocomplete and selects one", async () => {
    const onTopicChange = vi.fn();
    renderFilters({ onTopicChange });

    fireEvent.click(screen.getByRole("button", { name: "Filters" }));
    const input = screen.getByLabelText("Research area");
    fireEvent.change(input, { target: { value: "machine learning" } });

    await vi.advanceTimersByTimeAsync(450);

    await waitFor(() => {
      expect(searchTopics).toHaveBeenCalledWith(
        "machine learning",
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
    });

    const option = await screen.findByText("Machine Learning in Materials Science");
    fireEvent.click(option);

    expect(onTopicChange).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "T11948",
        display_name: "Machine Learning in Materials Science",
      }),
    );
  });

  it("shows selected filter chips and clears them", () => {
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
    expect(screen.queryByRole("button", { name: "Filters" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(onInstitutionChange).toHaveBeenCalledWith(null);
    expect(onTopicChange).toHaveBeenCalledWith(null);
  });

  it("opens filter fields and explains OpenAlex narrowing", () => {
    renderFilters();
    fireEvent.click(screen.getByRole("button", { name: "Filters" }));
    expect(
      screen.getByText("Narrow OpenAlex authors by institution or research area."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Institution")).toBeInTheDocument();
    expect(screen.getByLabelText("Research area")).toBeInTheDocument();
  });
});
