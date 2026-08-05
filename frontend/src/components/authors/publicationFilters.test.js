import { describe, expect, it } from "vitest";

import {
  buildAppliedFilterChips,
  clonePublicationFilters,
  countActivePublicationFilters,
  emptyPublicationFilters,
  hasActivePublicationFilters,
  publicationFiltersEqual,
  publicationFiltersKey,
  removeFilterChip,
  toPublicationFiltersPayload,
  validatePublicationFilters,
} from "./publicationFilters";

describe("publicationFilters helpers", () => {
  it("builds API payload without swapping an invalid year range", () => {
    const invalid = validatePublicationFilters({
      ...emptyPublicationFilters(),
      fromYear: "2020",
      toYear: "2018",
    });
    expect(invalid.valid).toBe(false);
    expect(toPublicationFiltersPayload({
      fromYear: "2020",
      toYear: "2018",
      sources: ["openalex"],
      venues: [],
      grants: [],
    })).toEqual({});

    const payload = toPublicationFiltersPayload({
      fromYear: "2018",
      toYear: "2020",
      sources: ["openalex", "arxiv", "openalex"],
      venues: [{ value: "nature medicine", label: "Nature Medicine" }],
      grants: [{ grant_number: "R01CA123456", funder: "NCI" }],
      authors: [{ value: "openalex:A1", label: "Ada Lovelace" }],
    });

    expect(payload).toEqual({
      from_year: 2018,
      to_year: 2020,
      sources: ["openalex", "arxiv"],
      venues: ["Nature Medicine"],
      grant_numbers: ["R01CA123456"],
      authors: ["openalex:A1"],
    });
  });

  it("validates four-digit years and empty years", () => {
    expect(validatePublicationFilters(emptyPublicationFilters()).valid).toBe(true);
    expect(validatePublicationFilters({
      ...emptyPublicationFilters(),
      fromYear: "20",
    }).valid).toBe(false);
    expect(validatePublicationFilters({
      ...emptyPublicationFilters(),
      fromYear: "2020",
      toYear: "",
    }).valid).toBe(true);
  });

  it("detects active filters, equality, chips, and removals", () => {
    const empty = emptyPublicationFilters();
    expect(hasActivePublicationFilters(empty)).toBe(false);

    const active = {
      ...empty,
      fromYear: "2020",
      toYear: "2025",
      sources: ["openalex"],
      venues: [{ value: "nature medicine", label: "Nature Medicine" }],
      grants: [{ grant_number: "R01CA123456" }],
      authors: [{ value: "openalex:A1", label: "Ada Lovelace" }],
    };
    expect(hasActivePublicationFilters(active)).toBe(true);
    expect(countActivePublicationFilters(active)).toBe(5);
    expect(publicationFiltersKey(active)).toContain("sources:openalex");
    expect(publicationFiltersKey(active)).toContain("authors:openalex:A1");
    expect(publicationFiltersEqual(active, clonePublicationFilters(active))).toBe(true);

    const chips = buildAppliedFilterChips(active, [
      { value: "openalex", label: "OpenAlex" },
    ]);
    expect(chips.map((chip) => chip.label)).toEqual([
      "2020–2025",
      "OpenAlex",
      "Nature Medicine",
      "R01CA123456",
      "Ada Lovelace",
    ]);

    const withoutSource = removeFilterChip(active, chips[1]);
    expect(withoutSource.sources).toEqual([]);
    expect(withoutSource.fromYear).toBe("2020");

    const withoutAuthor = removeFilterChip(active, chips[4]);
    expect(withoutAuthor.authors).toEqual([]);
    expect(withoutAuthor.grants).toHaveLength(1);
  });

  it("includes authors in empty and clone helpers", () => {
    const empty = emptyPublicationFilters();
    expect(empty.authors).toEqual([]);
    expect(clonePublicationFilters({ authors: [{ value: "name:ada", label: "Ada" }] }).authors).toEqual([
      { value: "name:ada", label: "Ada" },
    ]);
  });
});
