import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";

import { ENTITY_TYPES, FALLBACK_CAPABILITIES, SEARCH_SOURCES } from "../../api/searchApi";
import SourceSelector from "./SourceSelector";

const theme = createTheme();

function renderSelector({
  sources = FALLBACK_CAPABILITIES.sources,
  value = SEARCH_SOURCES.ALL,
  entityType = ENTITY_TYPES.AUTHORS,
  onChange = vi.fn(),
  ...props
} = {}) {
  return render(
    <ThemeProvider theme={theme}>
      <SourceSelector
        sources={sources}
        value={value}
        entityType={entityType}
        onChange={onChange}
        {...props}
      />
    </ThemeProvider>,
  );
}

describe("SourceSelector", () => {
  it("shows All as the selected value for authors", () => {
    renderSelector();
    expect(screen.getByLabelText("Search source")).toHaveTextContent("All");
  });

  it("lists All, OpenAlex, and ORCID for author search", () => {
    renderSelector();
    fireEvent.mouseDown(screen.getByLabelText("Search source"));
    expect(screen.getByRole("option", { name: "All" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "OpenAlex" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "ORCID" })).toBeInTheDocument();
  });

  it("does not offer arXiv for author search", () => {
    const sources = [
      ...FALLBACK_CAPABILITIES.sources.filter((s) => s.id !== SEARCH_SOURCES.ARXIV),
      {
        id: SEARCH_SOURCES.ARXIV,
        label: "arXiv",
        enabled: true,
        supported_entity_types: ["authors", "grants"],
      },
    ];
    renderSelector({ sources });
    fireEvent.mouseDown(screen.getByLabelText("Search source"));
    expect(screen.queryByRole("option", { name: "arXiv" })).not.toBeInTheDocument();
  });
});
