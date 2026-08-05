import { describe, expect, it, vi } from "vitest";

import { ENTITY_TYPES } from "../api/searchApi";
import {
  buildSearchHomePath,
  clearSelectionsForEntity,
  getActiveSearchMenuEntity,
  parseEntityParam,
} from "./searchNavigation";

describe("searchNavigation", () => {
  it("parses valid entity query values", () => {
    expect(parseEntityParam("authors")).toBe(ENTITY_TYPES.AUTHORS);
    expect(parseEntityParam("grants")).toBe(ENTITY_TYPES.GRANTS);
    expect(parseEntityParam("works")).toBe(ENTITY_TYPES.WORKS);
  });

  it("defaults invalid or missing entity values to authors", () => {
    expect(parseEntityParam(null)).toBe(ENTITY_TYPES.AUTHORS);
    expect(parseEntityParam("invalid")).toBe(ENTITY_TYPES.AUTHORS);
    expect(parseEntityParam("")).toBe(ENTITY_TYPES.AUTHORS);
  });

  it("builds search home paths with entity query", () => {
    expect(buildSearchHomePath("grants")).toBe("/?entity=grants");
    expect(buildSearchHomePath("bogus")).toBe("/?entity=authors");
  });

  it("resolves active menu entity from routes and query", () => {
    expect(
      getActiveSearchMenuEntity("/analyze/authors", new URLSearchParams()),
    ).toBe(ENTITY_TYPES.AUTHORS);
    expect(
      getActiveSearchMenuEntity("/grants/R01GM123456", new URLSearchParams()),
    ).toBe(ENTITY_TYPES.GRANTS);
    expect(
      getActiveSearchMenuEntity("/works/abc-123", new URLSearchParams()),
    ).toBe(ENTITY_TYPES.WORKS);
    expect(
      getActiveSearchMenuEntity("/", new URLSearchParams("entity=works")),
    ).toBe(ENTITY_TYPES.WORKS);
    expect(
      getActiveSearchMenuEntity("/search", new URLSearchParams("entity=grants")),
    ).toBe(ENTITY_TYPES.GRANTS);
  });

  it("clears incompatible selections when switching entity", () => {
    const setSelectedAuthors = vi.fn();
    const setSelectedWorks = vi.fn();

    clearSelectionsForEntity(ENTITY_TYPES.AUTHORS, {
      setSelectedAuthors,
      setSelectedWorks,
    });
    expect(setSelectedWorks).toHaveBeenCalledWith([]);
    expect(setSelectedAuthors).not.toHaveBeenCalled();

    clearSelectionsForEntity(ENTITY_TYPES.GRANTS, {
      setSelectedAuthors,
      setSelectedWorks,
    });
    expect(setSelectedAuthors).toHaveBeenCalledWith([]);
  });
});
