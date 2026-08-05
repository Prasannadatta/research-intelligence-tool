import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider, createTheme } from "@mui/material/styles";

import App from "./App";
import * as searchApi from "./api/searchApi";

const theme = createTheme({ colorSchemes: { light: true, dark: true } });

function renderApp(initialEntry = "/") {
  return render(
    <ThemeProvider theme={theme}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <App />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

function getEntitySelect() {
  return screen.getByLabelText("Search entity type");
}

describe("App sidebar search navigation", () => {
  beforeEach(() => {
    vi.spyOn(searchApi, "fetchSearchCapabilities").mockResolvedValue(
      searchApi.FALLBACK_CAPABILITIES,
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("navigates to search home with entity query when menu items are clicked", async () => {
    renderApp("/");

    fireEvent.click(screen.getByRole("button", { name: "Grants" }));
    await waitFor(() => {
      expect(getEntitySelect()).toHaveTextContent("Grants");
    });

    fireEvent.click(screen.getByRole("button", { name: "Works / Publications" }));
    await waitFor(() => {
      expect(getEntitySelect()).toHaveTextContent("Works");
    });

    fireEvent.click(screen.getByRole("button", { name: "Authors" }));
    await waitFor(() => {
      expect(getEntitySelect()).toHaveTextContent("Authors");
    });
  });

  it("syncs entity selector from URL on load and refresh", async () => {
    renderApp("/?entity=grants");

    await waitFor(() => {
      expect(getEntitySelect()).toHaveTextContent("Grants");
    });
  });

  it("updates entity selector when URL entity changes", async () => {
    renderApp("/?entity=authors");

    await waitFor(() => {
      expect(getEntitySelect()).toHaveTextContent("Authors");
    });

    fireEvent.click(screen.getByRole("button", { name: "Grants" }));
    await waitFor(() => {
      expect(getEntitySelect()).toHaveTextContent("Grants");
    });
  });

  it("keeps menu highlight and selector aligned when switching entity", async () => {
    renderApp("/?entity=authors");

    fireEvent.click(screen.getByRole("button", { name: "Works / Publications" }));
    await waitFor(() => {
      expect(getEntitySelect()).toHaveTextContent("Works");
      expect(screen.getByRole("button", { name: "Works / Publications" })).toHaveClass(
        "Mui-selected",
      );
    });
  });

  it("highlights Authors on analyze route", async () => {
    renderApp("/analyze/authors");

    expect(screen.getByRole("button", { name: "Authors" })).toHaveClass("Mui-selected");
    expect(screen.getByRole("button", { name: "Grants" })).not.toHaveClass("Mui-selected");
  });

  it("highlights Grants on grant publications route", async () => {
    const grantsApi = await import("./api/grantsApi");
    vi.spyOn(grantsApi, "fetchGrantPublications").mockResolvedValue({
      items: [],
      next_cursor: null,
      has_more: false,
      funder_name: null,
      verified: true,
      match_type: null,
    });

    renderApp("/grants/R01GM123456");

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Grants" })).toHaveClass("Mui-selected");
    });
  });

  it("supports /search alias with entity query", async () => {
    renderApp("/search?entity=works");

    await waitFor(() => {
      expect(getEntitySelect()).toHaveTextContent("Works");
    });
  });
});
