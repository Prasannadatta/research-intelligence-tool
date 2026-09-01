import { ThemeProvider } from "@mui/material/styles";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createAppTheme } from "../../../theme/analysisPalette";
import InstitutionNetworkPreview from "./InstitutionNetworkPreview";
import * as networkLayout from "./institutionNetworkLayout";

function denseNetwork(nodeCount = 36) {
  const nodes = Array.from({ length: nodeCount }, (_, index) => ({
    id: `I-${index}`,
    name: `Institution ${index}`,
    publications: nodeCount - index,
  }));
  const edges = [];
  for (let index = 0; index < nodeCount; index += 1) {
    for (let offset = 1; offset <= 4; offset += 1) {
      const other = index + offset;
      if (other >= nodeCount) {
        break;
      }
      edges.push({
        source: `I-${index}`,
        target: `I-${other}`,
        sharedPublications: 5 - offset,
      });
    }
  }
  return { nodes, edges };
}

describe("InstitutionNetworkPreview performance", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("precomputes the Top preview once and prepares All only when View all opens", () => {
    const prepareSpy = vi.spyOn(networkLayout, "prepareInstitutionNetworkView");
    const theme = createAppTheme();

    render(
      <ThemeProvider theme={theme}>
        <InstitutionNetworkPreview network={denseNetwork(36)} />
      </ThemeProvider>,
    );

    expect(screen.getByTestId("institution-network-preview")).toBeInTheDocument();
    expect(prepareSpy.mock.calls.length).toBe(1);

    fireEvent.mouseEnter(screen.getByTestId("institution-node-I-0"));
    expect(prepareSpy.mock.calls.length).toBe(1);
    expect(screen.getByTestId("institution-network-tooltip")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("institution-network-view-all-button"));
    expect(screen.getByTestId("institution-network-view-all-dialog")).toBeInTheDocument();
    expect(prepareSpy.mock.calls.length).toBe(2);
    expect(screen.getByTestId("full-institution-node-I-0")).toBeInTheDocument();
  });
});
