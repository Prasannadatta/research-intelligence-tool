import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";

import { ENTITY_TYPES, FALLBACK_CAPABILITIES, SEARCH_SOURCES } from "../../api/searchApi";
import SourceSelector from "./SourceSelector";

const theme = createTheme({ colorSchemes: { light: true, dark: true } });

function renderSelector(props = {}) {
  return render(
    <ThemeProvider theme={theme}>
      <SourceSelector
        sources={FALLBACK_CAPABILITIES.sources}
        value={SEARCH_SOURCES.ALL}
        entityType={ENTITY_TYPES.AUTHORS}
        onChange={vi.fn()}
        {...props}
      />
    </ThemeProvider>,
  );
}

describe("SourceSelector", () => {
  it("shows All sources as the selected value", () => {
    renderSelector();
    expect(screen.getByLabelText("Search source")).toHaveTextContent("All sources");
  });
});
