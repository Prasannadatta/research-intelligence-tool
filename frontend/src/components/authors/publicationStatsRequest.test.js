import { describe, expect, it } from "vitest";

import { formatPublicationStatsProgressMessage } from "./publicationStatsRequest";

describe("formatPublicationStatsProgressMessage", () => {
  it("keeps aggregate-only progress for large author cohorts", () => {
    const message = formatPublicationStatsProgressMessage({
      stage: "Syncing",
      detail: {
        authors_ready: 18,
        authors_total: 22,
        author_name: "Ada Lovelace",
        publications_processed: 12,
        publications_total: 40,
      },
    });
    expect(message).toBe("18 of 22 authors ready");
  });

  it("includes current author detail for smaller cohorts", () => {
    const message = formatPublicationStatsProgressMessage({
      stage: "Syncing",
      detail: {
        authors_ready: 2,
        authors_total: 5,
        author_name: "Ada Lovelace",
        publications_processed: 12,
        publications_total: 40,
      },
    });
    expect(message).toBe("2 of 5 authors ready — syncing Ada Lovelace (12 / 40)");
  });
});
