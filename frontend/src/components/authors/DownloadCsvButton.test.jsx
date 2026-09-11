import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import DownloadCsvButton, {
  downloadBlobFile,
  filenameFromContentDisposition,
} from "./DownloadCsvButton";

describe("DownloadCsvButton helpers", () => {
  it("parses content-disposition filenames", () => {
    expect(
      filenameFromContentDisposition(
        'attachment; filename="grant-R01-publications-2026-08-04.csv"',
        "fallback.csv",
      ),
    ).toBe("grant-R01-publications-2026-08-04.csv");
  });

  it("downloads a blob and cleans up the temporary URL", () => {
    const click = vi.fn();
    const remove = vi.fn();
    const revoke = vi.fn();
    const createObjectURL = vi.fn(() => "blob:mock");
    vi.stubGlobal("URL", {
      createObjectURL,
      revokeObjectURL: revoke,
    });

    const originalCreate = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag) => {
      if (tag === "a") {
        return {
          href: "",
          download: "",
          style: {},
          click,
          remove,
        };
      }
      return originalCreate(tag);
    });
    const appendSpy = vi.spyOn(document.body, "appendChild").mockImplementation(() => {});

    downloadBlobFile(new Blob(["a,b"]), "out.csv");

    expect(createObjectURL).toHaveBeenCalled();
    expect(click).toHaveBeenCalled();
    expect(remove).toHaveBeenCalled();
    expect(revoke).toHaveBeenCalledWith("blob:mock");

    appendSpy.mockRestore();
    vi.unstubAllGlobals();
  });
});

describe("DownloadCsvButton", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows loading state while exporting", async () => {
    let resolveExport;
    const onExport = vi.fn(
      () =>
        new Promise((resolve) => {
          resolveExport = resolve;
        }),
    );

    render(<DownloadCsvButton onExport={onExport} disabled={false} />);
    fireEvent.click(screen.getByTestId("download-csv-button"));

    expect(screen.getByText("Preparing CSV…")).toBeInTheDocument();
    expect(screen.getByTestId("download-csv-button")).toBeDisabled();

    resolveExport();
    await waitFor(() => {
      expect(screen.getByText("Download CSV")).toBeInTheDocument();
    });
  });

  it("shows an error when export fails", async () => {
    const onExport = vi.fn().mockRejectedValue(new Error("boom"));
    render(<DownloadCsvButton onExport={onExport} />);
    fireEvent.click(screen.getByTestId("download-csv-button"));

    await waitFor(() => {
      expect(screen.getByText("boom")).toBeInTheDocument();
    });
    expect(screen.getByTestId("download-csv-button")).not.toBeDisabled();
  });

  it("disables when there are zero matching publications", () => {
    render(<DownloadCsvButton disabled onExport={vi.fn()} />);
    expect(screen.getByTestId("download-csv-button")).toBeDisabled();
    expect(
      screen.getByText(
        "Exports all filtered publications with available author, institution, grant, venue, and source metadata.",
      ),
    ).toBeInTheDocument();
  });

  it("hides helper text in compact mode", () => {
    render(
      <DownloadCsvButton
        compact
        disabled
        onExport={vi.fn()}
        helperText="Exports all filtered publications with available author, institution, grant, venue, and source metadata."
      />,
    );
    expect(screen.getByTestId("download-csv-button")).toBeDisabled();
    expect(
      screen.queryByText(/Exports all filtered publications/i),
    ).not.toBeInTheDocument();
  });
});
