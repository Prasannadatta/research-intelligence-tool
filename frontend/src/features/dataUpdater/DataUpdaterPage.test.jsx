import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ThemeProvider, createTheme } from "@mui/material/styles";

import DataUpdaterPage, { UPDATE_ACTIONS } from "./DataUpdaterPage";
import * as dataUpdaterApi from "./dataUpdaterApi";

const theme = createTheme({ colorSchemes: { light: true, dark: true } });

const JOB = {
  id: "job-1",
  mode: "dataset",
  dataset: "authors",
  status: "running",
  current_dataset: "authors",
  total_records: 421,
  processed_records: 286,
  updated_count: 63,
  unchanged_count: 215,
  retrying_count: 3,
  failed_count: 0,
  metadata: {
    title: "Updating author data",
  },
  records: [],
  updated_at: "2026-08-03T12:00:00Z",
  completed_at: null,
};

function renderPage() {
  return render(
    <ThemeProvider theme={theme}>
      <MemoryRouter initialEntries={["/data-updater"]}>
        <Routes>
          <Route path="/data-updater" element={<DataUpdaterPage />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

function installLocalStorageStub() {
  const store = new Map();
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: vi.fn((key) => store.get(key) || null),
      setItem: vi.fn((key, value) => {
        store.set(key, String(value));
      }),
      removeItem: vi.fn((key) => {
        store.delete(key);
      }),
      clear: vi.fn(() => {
        store.clear();
      }),
    },
  });
}

describe("DataUpdaterPage", () => {
  beforeEach(() => {
    installLocalStorageStub();
    window.localStorage.clear();
    vi.spyOn(dataUpdaterApi, "startDataUpdate").mockResolvedValue(JOB);
    vi.spyOn(dataUpdaterApi, "fetchDataUpdateJob").mockResolvedValue(JOB);
    vi.spyOn(dataUpdaterApi, "pauseDataUpdateJob").mockImplementation(async () => {
      const next = { ...JOB, status: "paused" };
      dataUpdaterApi.fetchDataUpdateJob.mockResolvedValue(next);
      return next;
    });
    vi.spyOn(dataUpdaterApi, "resumeDataUpdateJob").mockImplementation(async () => {
      const next = { ...JOB, status: "queued" };
      dataUpdaterApi.fetchDataUpdateJob.mockResolvedValue(next);
      return next;
    });
    vi.spyOn(dataUpdaterApi, "cancelDataUpdateJob").mockImplementation(async () => {
      const next = { ...JOB, status: "cancelled" };
      dataUpdaterApi.fetchDataUpdateJob.mockResolvedValue(next);
      return next;
    });
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("shows explicit update actions with short descriptions", () => {
    renderPage();

    const actions = screen.getByTestId("data-update-actions");
    for (const action of UPDATE_ACTIONS) {
      expect(within(actions).getByRole("button", { name: action.label })).toBeInTheDocument();
      expect(actions).toHaveTextContent(action.description);
    }
    expect(screen.queryByLabelText(/saved search/i)).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText(/author, publication, or institution/i),
    ).not.toBeInTheDocument();
  });

  it("starts each update action with the correct existing refresh scope", async () => {
    renderPage();

    for (const action of UPDATE_ACTIONS) {
      dataUpdaterApi.startDataUpdate.mockClear();
      dataUpdaterApi.startDataUpdate.mockResolvedValueOnce({
        ...JOB,
        id: `job-${action.id}`,
        status: "succeeded",
        dataset: action.request.dataset || null,
        mode: action.request.mode,
      });

      fireEvent.click(screen.getByRole("button", { name: action.label }));

      await waitFor(() => {
        expect(dataUpdaterApi.startDataUpdate).toHaveBeenCalledWith(action.request);
      });
      expect(dataUpdaterApi.startDataUpdate).toHaveBeenCalledTimes(1);
    }
  });

  it("shows idle status, then progress after starting an update", async () => {
    renderPage();

    expect(screen.getByTestId("data-update-status")).toHaveTextContent("Idle");
    expect(screen.getByTestId("data-update-progress")).toHaveTextContent(
      "No update in progress",
    );
    expect(screen.getByTestId("data-update-last-updated")).toHaveTextContent(
      "Not updated yet",
    );

    fireEvent.click(screen.getByRole("button", { name: "Update Author Data" }));

    await waitFor(() => {
      expect(dataUpdaterApi.startDataUpdate).toHaveBeenCalledWith({
        mode: "dataset",
        dataset: "authors",
        stale_only: true,
      });
    });
    const progress = await screen.findByTestId("data-update-progress");
    expect(progress).toHaveTextContent("68% · 286 / 421 items checked");
    expect(screen.getByTestId("data-update-status")).toHaveTextContent("Running");
    expect(screen.getByTestId("data-update-last-updated")).toHaveTextContent(
      /Last updated/i,
    );
  });

  it("keeps Pause / Resume / Cancel with the progress area, separate from start actions", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Update Everything" }));

    const progress = await screen.findByTestId("data-update-progress");
    const actions = screen.getByTestId("data-update-actions");
    expect(within(progress).getByRole("button", { name: "Pause" })).toBeInTheDocument();
    expect(within(progress).getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(
      within(progress).queryByRole("button", { name: "Update Everything" }),
    ).not.toBeInTheDocument();
    expect(within(actions).getByRole("button", { name: "Update Everything" })).toBeDisabled();

    fireEvent.click(within(progress).getByRole("button", { name: "Pause" }));
    await waitFor(() => {
      expect(dataUpdaterApi.pauseDataUpdateJob).toHaveBeenCalledWith("job-1");
    });
    expect(await screen.findByTestId("data-update-status")).toHaveTextContent("Paused");

    fireEvent.click(await screen.findByRole("button", { name: "Resume" }));
    await waitFor(() => {
      expect(dataUpdaterApi.resumeDataUpdateJob).toHaveBeenCalledWith("job-1");
    });

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(dataUpdaterApi.cancelDataUpdateJob).toHaveBeenCalledWith("job-1");
    });
    expect(await screen.findByTestId("data-update-status")).toHaveTextContent("Cancelled");
  });

  it("does not start duplicate jobs while one is active", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Update Author Data" }));

    await screen.findByTestId("data-update-progress");
    expect(screen.getByRole("button", { name: "Update Author Data" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Update Everything" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Update Author Data" }));
    fireEvent.click(screen.getByRole("button", { name: "Update Everything" }));

    expect(dataUpdaterApi.startDataUpdate).toHaveBeenCalledTimes(1);
  });

  it("keeps Cancel enabled during cancel_requested and re-enables Update after cancelled", async () => {
    const cancelRequested = {
      ...JOB,
      status: "cancel_requested",
      updated_at: new Date().toISOString(),
    };
    dataUpdaterApi.startDataUpdate.mockResolvedValueOnce(cancelRequested);
    dataUpdaterApi.fetchDataUpdateJob.mockResolvedValue(cancelRequested);
    dataUpdaterApi.cancelDataUpdateJob.mockImplementationOnce(async () => {
      const next = { ...JOB, status: "cancelled" };
      dataUpdaterApi.fetchDataUpdateJob.mockResolvedValue(next);
      return next;
    });

    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Update Grant Data" }));

    await screen.findByTestId("data-update-progress");
    expect(screen.getByRole("button", { name: "Update Grant Data" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Pause" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(dataUpdaterApi.cancelDataUpdateJob).toHaveBeenCalledWith("job-1");
    });
    expect(await screen.findByTestId("data-update-status")).toHaveTextContent("Cancelled");
    expect(screen.getByRole("button", { name: "Update Grant Data" })).toBeEnabled();
  });

  it("shows Completed and Failed final statuses", async () => {
    dataUpdaterApi.startDataUpdate.mockResolvedValueOnce({
      ...JOB,
      status: "succeeded",
      completed_at: "2026-08-03T12:00:00Z",
    });
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Update Publication Data" }));
    expect(await screen.findByTestId("data-update-status")).toHaveTextContent("Completed");

    dataUpdaterApi.startDataUpdate.mockResolvedValueOnce({
      ...JOB,
      status: "failed",
      error: "boom",
    });
    fireEvent.click(screen.getByRole("button", { name: "Update Journal Metrics" }));
    expect(await screen.findByTestId("data-update-status")).toHaveTextContent("Failed");
  });

  it("restores an unfinished update after leaving and returning to the page", async () => {
    const firstRender = renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Update Author Data" }));

    await waitFor(() => {
      expect(dataUpdaterApi.startDataUpdate).toHaveBeenCalled();
    });
    firstRender.unmount();

    renderPage();

    const progress = await screen.findByTestId("data-update-progress");
    expect(dataUpdaterApi.fetchDataUpdateJob).toHaveBeenCalledWith(
      "job-1",
      expect.any(Object),
    );
    expect(progress).toHaveTextContent("Updating author data");
    expect(progress).toHaveTextContent("286 / 421 items checked");
  });
});
