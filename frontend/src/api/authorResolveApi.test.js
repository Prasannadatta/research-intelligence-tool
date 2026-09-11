import { describe, expect, it } from "vitest";

import {
  isResolvedAuthorSelection,
  shouldResolveAuthorOnSelect,
} from "./authorResolveApi";

describe("authorResolveApi", () => {
  it("skips resolve for already-canonical selections", () => {
    expect(
      isResolvedAuthorSelection({
        id: "11111111-1111-4111-8111-111111111111",
      }),
    ).toBe(true);
    expect(
      shouldResolveAuthorOnSelect({
        id: "11111111-1111-4111-8111-111111111111",
        source: "openalex",
        openalex_id: "A1",
      }),
    ).toBe(false);
  });

  it("resolves OpenAlex and ORCID search hits on select", () => {
    expect(
      shouldResolveAuthorOnSelect({
        source: "openalex",
        openalex_id: "A1",
      }),
    ).toBe(true);
    expect(
      shouldResolveAuthorOnSelect({
        source: "orcid",
        orcid: "0000-0001-6860-9566",
      }),
    ).toBe(true);
  });

  it("never resolves arXiv author-name aggregates", () => {
    expect(
      shouldResolveAuthorOnSelect({
        source: "arxiv",
        result_type: "author_name",
        display_name: "Lin Lin",
      }),
    ).toBe(false);
  });
});
