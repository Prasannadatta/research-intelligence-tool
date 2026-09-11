import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";

import {
  clearAuthorSummaryCache,
  fetchAuthorDetails,
} from "./authorSummaryCache";
import * as authorSummaryApi from "../../api/authorSummaryApi";

vi.mock("../../api/authorSummaryApi");

describe("fetchAuthorDetails abort safety", () => {
  beforeEach(() => {
    clearAuthorSummaryCache();
    vi.clearAllMocks();
  });

  afterEach(() => {
    clearAuthorSummaryCache();
  });

  it("does not cancel a shared in-flight details request when a caller aborts", async () => {
    let resolveDetails;
    authorSummaryApi.fetchAuthorDetailsByCanonicalId.mockImplementation(
      () => new Promise((resolve) => {
        resolveDetails = resolve;
      }),
    );

    const controller = new AbortController();
    const first = fetchAuthorDetails("canonical-1", { signal: controller.signal });
    const second = fetchAuthorDetails("canonical-1", { signal: new AbortController().signal });

    controller.abort();

    resolveDetails({
      id: "canonical-1",
      display_name: "Jane Doe",
      enrichment: { pending: [] },
      grants: [],
      publications: [],
    });

    await expect(first).resolves.toMatchObject({ id: "canonical-1" });
    await expect(second).resolves.toMatchObject({ id: "canonical-1" });
    expect(authorSummaryApi.fetchAuthorDetailsByCanonicalId).toHaveBeenCalledTimes(1);
    expect(authorSummaryApi.fetchAuthorDetailsByCanonicalId).toHaveBeenCalledWith("canonical-1");
  });
});
