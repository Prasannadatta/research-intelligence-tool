import { describe, expect, it } from "vitest";

import {
  buildAuthorSavedSearchBody,
  formatAuthorsCompact,
  formatImportantFilters,
  matchesSavedSearchQuery,
} from "./savedSearchDisplay";

describe("savedSearchDisplay", () => {
  it("compacts large author lists", () => {
    const authors = Array.from({ length: 20 }, (_, index) => ({
      canonical_author_id: `c${index}`,
      display_name: `Author ${index + 1}`,
    }));
    expect(formatAuthorsCompact(authors)).toBe(
      "Author 1, Author 2, Author 3 +17 more",
    );
  });

  it("matches search by name and author names", () => {
    const item = {
      display_name: "Berkeley lab",
      payload: {
        authors: [{ display_name: "Alex Roe", canonical_author_id: "c3" }],
      },
    };
    expect(matchesSavedSearchQuery(item, "berkeley")).toBe(true);
    expect(matchesSavedSearchQuery(item, "alex")).toBe(true);
    expect(matchesSavedSearchQuery(item, "missing")).toBe(false);
  });

  it("summarizes important filters", () => {
    expect(
      formatImportantFilters(
        { from_year: 2020, to_year: 2024, institutions: ["UC Berkeley", "MIT"] },
        { mode: "common_publications" },
      ),
    ).toContain("2020–2024");
  });

  it("builds save bodies without requiring a custom name", () => {
    const body = buildAuthorSavedSearchBody({
      authors: [
        {
          canonical_author_id: "c1",
          display_name: "John Smith",
          provider: "openalex",
          provider_author_id: "A1",
        },
      ],
      filters: { from_year: 2020 },
      mode: "single_author",
      displayName: "   ",
    });
    expect(body.display_name).toBeUndefined();
    expect(body.payload.authors).toHaveLength(1);
    expect(body.payload.analysis_mode).toBe("single_author");
  });
});
