import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import {
  appendUniqueSavedSearchAuthor,
  removeSavedSearchAuthor,
  savedSearchAuthorFromSearchHit,
} from "./savedSearchAuthorEdit";
import * as authorResolveApi from "../../api/authorResolveApi";
import * as analysisApi from "../../api/analysisApi";

describe("savedSearchAuthorEdit", () => {
  beforeEach(() => {
    vi.spyOn(authorResolveApi, "resolveAuthorSelection").mockImplementation(async (item) => ({
      ...item,
      id: "11111111-1111-4111-8111-111111111111",
      canonical_author_id: "11111111-1111-4111-8111-111111111111",
      source_records: [
        { provider: "openalex", provider_author_id: item.openalex_id || "A9" },
      ],
    }));
    vi.spyOn(analysisApi, "toAnalysisAuthorPayload").mockImplementation((item) => ({
      canonical_author_id: item.canonical_author_id || item.id,
      display_name: item.display_name,
      provider: "openalex",
      provider_author_id: item.openalex_id || item.source_records?.[0]?.provider_author_id,
    }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("resolves a search hit into a saved-search author row", async () => {
    const author = await savedSearchAuthorFromSearchHit({
      result_id: "openalex:A9",
      display_name: "New Author",
      openalex_id: "A9",
      source: "openalex",
    });
    expect(authorResolveApi.resolveAuthorSelection).toHaveBeenCalled();
    expect(author).toEqual({
      canonical_author_id: "11111111-1111-4111-8111-111111111111",
      display_name: "New Author",
      provider: "openalex",
      provider_author_id: "A9",
    });
  });

  it("adds, skips duplicates by provider identity, removes, and allows re-add", () => {
    const first = {
      canonical_author_id: "c1",
      display_name: "Author A",
      provider: "openalex",
      provider_author_id: "A1",
    };
    const duplicateHit = {
      canonical_author_id: "c1-other",
      display_name: "Author A copy",
      provider: "openalex",
      provider_author_id: "A1",
    };
    const second = {
      canonical_author_id: "c2",
      display_name: "Author B",
      provider: "openalex",
      provider_author_id: "A2",
    };

    let authors = appendUniqueSavedSearchAuthor([], first);
    expect(authors).toHaveLength(1);
    authors = appendUniqueSavedSearchAuthor(authors, duplicateHit);
    expect(authors).toHaveLength(1);
    authors = appendUniqueSavedSearchAuthor(authors, second);
    expect(authors).toHaveLength(2);

    authors = removeSavedSearchAuthor(authors, "c1");
    expect(authors.map((row) => row.canonical_author_id)).toEqual(["c2"]);

    authors = appendUniqueSavedSearchAuthor(authors, first);
    expect(authors.map((row) => row.canonical_author_id)).toEqual(["c2", "c1"]);
  });

  it("handles large author lists without dropping identity checks", () => {
    const many = Array.from({ length: 25 }, (_, index) => ({
      canonical_author_id: `c${index}`,
      display_name: `Author ${index}`,
      provider: "openalex",
      provider_author_id: `A${index}`,
    }));
    const next = appendUniqueSavedSearchAuthor(many, many[3]);
    expect(next).toHaveLength(25);
    expect(appendUniqueSavedSearchAuthor(many, {
      canonical_author_id: "c-new",
      display_name: "New",
      provider: "openalex",
      provider_author_id: "A-new",
    })).toHaveLength(26);
  });
});
