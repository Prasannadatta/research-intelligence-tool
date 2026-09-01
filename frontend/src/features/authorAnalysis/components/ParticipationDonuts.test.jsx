import { ThemeProvider } from "@mui/material/styles";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { createAppTheme } from "../../../theme/analysisPalette";
import ParticipationDonuts, {
  summarizeInstitutionLegend,
} from "./ParticipationDonuts";

vi.mock("react-apexcharts", () => ({
  default: ({ series, options }) => (
    <div
      data-testid="apex-chart-mock"
      data-series={JSON.stringify(series)}
      data-labels={JSON.stringify(options?.labels || [])}
      data-legend={JSON.stringify(options?.legend || {})}
    />
  ),
}));

describe("summarizeInstitutionLegend", () => {
  it("keeps a short list intact and collapses a long tail into Other", () => {
    const shortRows = [
      { label: "1 institution", value: 10 },
      { label: "2 institutions", value: 5 },
    ];
    expect(summarizeInstitutionLegend(shortRows).other).toBeNull();
    expect(summarizeInstitutionLegend(shortRows).items).toHaveLength(2);

    const longRows = Array.from({ length: 12 }, (_, index) => ({
      label: `${index + 1} institution${index === 0 ? "" : "s"}`,
      value: 20 - index,
    }));
    const legend = summarizeInstitutionLegend(longRows);
    expect(legend.items).toHaveLength(7);
    expect(legend.other.categoryCount).toBe(5);
    expect(legend.other.value).toBe(55);
  });
});

describe("Institution participation legend", () => {
  it("keeps full donut slices and shows a compact legend with Other", () => {
    const institutions = Array.from({ length: 12 }, (_, index) => ({
      label: `${index + 1} institution${index === 0 ? "" : "s"}`,
      value: 20 - index,
    }));
    render(
      <ThemeProvider theme={createAppTheme()}>
        <ParticipationDonuts
          participation={{
            selectedAuthors: [{ label: "1 selected author", value: 4 }],
            institutions,
            sharedByTwoOrMoreAuthors: 0,
            multiInstitutionPapers: 9,
          }}
        />
      </ThemeProvider>,
    );

    const institutionCard = screen.getByTestId("institution-participation-card");
    const chart = within(institutionCard).getByTestId("apex-chart-mock");
    expect(JSON.parse(chart.getAttribute("data-labels"))).toHaveLength(12);
    expect(JSON.parse(chart.getAttribute("data-series"))).toEqual(
      institutions.map((row) => row.value),
    );
    expect(JSON.parse(chart.getAttribute("data-legend")).show).toBe(false);

    const legend = within(institutionCard).getByTestId("institution-participation-legend");
    expect(within(legend).getByText("1 institution")).toBeInTheDocument();
    expect(within(legend).queryByText("12 institutions")).not.toBeInTheDocument();
    expect(within(legend).getByText("Other (5)")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("institution-participation-view-all"));
    const dialog = screen.getByTestId("institution-participation-view-all-dialog");
    expect(within(dialog).getByText("12 institutions")).toBeInTheDocument();
  });
});
