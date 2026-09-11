import { describe, expect, it } from "vitest";

import {
  ENTITY_TYPES,
  FALLBACK_CAPABILITIES,
  SEARCH_SOURCES,
  looksLikeOrcidQuery,
  normalizeSearchQuery,
  resolveCompatibleSource,
} from "./searchApi";

describe("searchApi ORCID and default source helpers", () => {
  it("detects bare and URL ORCID queries", () => {
    expect(looksLikeOrcidQuery("0000-0001-6860-9566")).toBe(true);
    expect(looksLikeOrcidQuery("https://orcid.org/0000-0001-6860-9566")).toBe(true);
    expect(looksLikeOrcidQuery("Lin Lin")).toBe(false);
  });

  it("preserves ORCID identifiers when normalizing author queries", () => {
    expect(normalizeSearchQuery("0000-0002-1825-009x", ENTITY_TYPES.AUTHORS)).toBe(
      "0000-0002-1825-009X",
    );
    expect(normalizeSearchQuery("Lin Lin", ENTITY_TYPES.AUTHORS)).toBe("lin lin");
  });

  it("defaults Author Search to All sources (OpenAlex + ORCID)", () => {
    expect(FALLBACK_CAPABILITIES.default_source).toBe(SEARCH_SOURCES.ALL);
    expect(
      resolveCompatibleSource(
        FALLBACK_CAPABILITIES,
        ENTITY_TYPES.AUTHORS,
        SEARCH_SOURCES.ALL,
      ),
    ).toBe(SEARCH_SOURCES.ALL);
    expect(
      resolveCompatibleSource(
        FALLBACK_CAPABILITIES,
        ENTITY_TYPES.AUTHORS,
        SEARCH_SOURCES.OPENALEX,
      ),
    ).toBe(SEARCH_SOURCES.OPENALEX);
    expect(
      resolveCompatibleSource(
        FALLBACK_CAPABILITIES,
        ENTITY_TYPES.AUTHORS,
        SEARCH_SOURCES.ARXIV,
      ),
    ).toBe(SEARCH_SOURCES.ALL);
    expect(
      resolveCompatibleSource(
        FALLBACK_CAPABILITIES,
        ENTITY_TYPES.GRANTS,
        SEARCH_SOURCES.OPENALEX,
      ),
    ).toBe(SEARCH_SOURCES.OPENALEX);
  });
});
