import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";

import AuthorPublicationTrendChart from "./AuthorPublicationTrendChart";

vi.mock("react-apexcharts", () => ({
  default: ({ series, options }) => (
    <div
      data-testid="apex-chart-mock"
      data-series={JSON.stringify(series)}
      data-categories={JSON.stringify(options?.xaxis?.categories || [])}
    />
  ),
}));

const theme = createTheme({ colorSchemes: { light: true, dark: true } });

function renderChart(props) {
  return render(
    <ThemeProvider theme={theme}>
      <AuthorPublicationTrendChart
        timeline={null}
        loading={false}
        mode="single_author"
        error={null}
        {...props}
      />
    </ThemeProvider>,
  );
}

describe("AuthorPublicationTrendChart", () => {
  it("shows loading skeleton while loading", () => {
    renderChart({ loading: true });
    expect(
      screen.getByLabelText("Loading publication trends chart"),
    ).toBeInTheDocument();
  });

  it("shows no-data message when timeline is empty", () => {
    renderChart({ timeline: { interval: "year", items: [] } });
    expect(screen.getByText("No publication timeline available")).toBeInTheDocument();
  });

  it("renders monthly timeline in chronological order for single author mode", () => {
    renderChart({
      mode: "single_author",
      timeline: {
        interval: "month",
        total_dated_publications: 3,
        total_matching_publications: 3,
        items: [
          { period: "2024-01", label: "Jan 2024", count: 2 },
          { period: "2024-02", label: "Feb 2024", count: 0 },
          { period: "2024-03", label: "Mar 2024", count: 1 },
        ],
      },
    });

    expect(screen.getByText("Publications over time")).toBeInTheDocument();
    expect(
      screen.getByText("3 of 3 publications have usable date metadata"),
    ).toBeInTheDocument();
    const chart = screen.getByTestId("author-publication-trend-chart");
    expect(chart).toHaveAttribute("data-chart-interval", "month");
    const categories = JSON.parse(
      screen.getByTestId("apex-chart-mock").getAttribute("data-categories"),
    );
    expect(categories).toEqual(["Jan 2024", "Feb 2024", "Mar 2024"]);
  });

  it("uses common-publications title for multiple authors", () => {
    renderChart({
      mode: "common_publications",
      timeline: {
        interval: "year",
        items: [{ period: "2023", label: "2023", count: 1 }],
      },
    });
    expect(screen.getByText("Common publications over time")).toBeInTheDocument();
  });

  it("shows chart-specific error without blocking layout", () => {
    renderChart({ error: "Could not load publication timeline." });
    expect(screen.getByText("Could not load publication timeline.")).toBeInTheDocument();
  });

  it("describes a page-local sample when the provider total is known", () => {
    renderChart({
      pageLocal: true,
      providerTotalCount: 1037,
      timeline: {
        interval: "year",
        total_dated_publications: 20,
        total_matching_publications: 20,
        items: [{ period: "2021", label: "2021", count: 20 }],
      },
    });
    expect(
      screen.getByText("Timeline based on 20 of 1,037 publications"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("20 of 20 publications have usable date metadata"),
    ).not.toBeInTheDocument();
  });

  it("falls back when the provider total is unavailable", () => {
    renderChart({
      pageLocal: true,
      timeline: {
        interval: "year",
        total_dated_publications: 20,
        total_matching_publications: 20,
        items: [{ period: "2021", label: "2021", count: 20 }],
      },
    });
    expect(
      screen.getByText("Based on the first 20 loaded publications"),
    ).toBeInTheDocument();
  });
});
