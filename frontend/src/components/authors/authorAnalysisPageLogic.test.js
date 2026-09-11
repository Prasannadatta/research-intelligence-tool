import { describe, expect, it } from "vitest";

import {
  analysisModeForAuthors,
  buildAuthorPublicationsCacheKey,
} from "../../api/analysisApi";
import {
  activeAuthorIdsKey,
  analysisTitleForAuthors,
  CORPUS_STATUS,
  deriveCorpusStatus,
  emptyStateCopy,
  formatProviderDedupCaption,
  getActiveAuthors,
  getInitialActiveAuthorIds,
  isAuthorCheckboxDisabled,
  providerDisplayLabel,
  toggleActiveAuthor,
} from "./authorAnalysisPageLogic";

const AUTHORS = [
  {
    canonical_author_id: "c1",
    provider: "openalex",
    provider_author_id: "A1",
    display_name: "John Smith",
  },
  {
    canonical_author_id: "c2",
    provider: "openalex",
    provider_author_id: "A2",
    display_name: "Jane Doe",
  },
  {
    canonical_author_id: "c3",
    provider: "openalex",
    provider_author_id: "A3",
    display_name: "Alex Chen",
  },
];

describe("authorAnalysisPageLogic", () => {
  it("checks all authors on initial load", () => {
    const active = getInitialActiveAuthorIds(AUTHORS);
    expect(active.size).toBe(3);
    expect(active.has("c1")).toBe(true);
    expect(active.has("c2")).toBe(true);
    expect(active.has("c3")).toBe(true);
  });

  it("unchecking one author removes it from active authors", () => {
    const initial = getInitialActiveAuthorIds(AUTHORS);
    const next = toggleActiveAuthor(initial, "c2");
    const active = getActiveAuthors(AUTHORS, next);
    expect(active.map((a) => a.canonical_author_id)).toEqual(["c1", "c3"]);
  });

  it("prevents unchecking the final remaining author", () => {
    let active = getInitialActiveAuthorIds(AUTHORS);
    active = toggleActiveAuthor(active, "c2");
    active = toggleActiveAuthor(active, "c3");
    expect(active.size).toBe(1);
    expect(isAuthorCheckboxDisabled(active, "c1")).toBe(true);
    const blocked = toggleActiveAuthor(active, "c1");
    expect(blocked).toBe(active);
    expect(blocked.size).toBe(1);
  });

  it("updates title for one vs multiple active authors", () => {
    const single = getActiveAuthors(AUTHORS, new Set(["c1"]));
    expect(analysisTitleForAuthors(single)).toBe("Publications by John Smith");

    const multi = getActiveAuthors(AUTHORS, new Set(["c1", "c2"]));
    expect(analysisTitleForAuthors(multi)).toBe("Common Publications");
  });

  it("uses distinct empty-state copy by mode", () => {
    expect(emptyStateCopy("single_author").heading).toBe("No publications found");
    expect(emptyStateCopy("common_publications").heading).toBe(
      "No common publications found",
    );
    expect(emptyStateCopy("common_publications").body).toContain(
      "Try a different combination",
    );
  });

  it("builds distinct cache keys for different author combinations", () => {
    const keyAll = buildAuthorPublicationsCacheKey({
      mode: "common_publications",
      canonicalAuthorIds: ["c1", "c2", "c3"],
      providerRecordsKey: "records-a",
      cursor: "*",
      limit: 20,
    });
    const keySubset = buildAuthorPublicationsCacheKey({
      mode: "single_author",
      canonicalAuthorIds: ["c1"],
      providerRecordsKey: "records-b",
      cursor: "*",
      limit: 20,
    });
    expect(keyAll).not.toBe(keySubset);
  });

  it("uses stable active author selection keys for pagination reset", () => {
    const allKey = activeAuthorIdsKey(new Set(["c1", "c2", "c3"]));
    const subsetKey = activeAuthorIdsKey(new Set(["c1"]));
    expect(allKey).not.toBe(subsetKey);
  });

  it("derives analysis mode from active author count", () => {
    expect(analysisModeForAuthors(getActiveAuthors(AUTHORS, new Set(["c1"])))).toBe(
      "single_author",
    );
    expect(
      analysisModeForAuthors(getActiveAuthors(AUTHORS, new Set(["c1", "c2"]))),
    ).toBe("common_publications");
  });

  it("derives compact corpus status labels", () => {
    expect(
      deriveCorpusStatus({
        corpusComplete: true,
        statsLoading: false,
        hasLoadedOnce: true,
      }),
    ).toBe(CORPUS_STATUS.VERIFIED);
    expect(
      deriveCorpusStatus({
        statsLoading: true,
        hasLoadedOnce: true,
      }),
    ).toBe(CORPUS_STATUS.SYNCING);
    expect(
      deriveCorpusStatus({
        statsError: "OpenAlex rate limit reached.",
        hasLoadedOnce: true,
      }),
    ).toBe(CORPUS_STATUS.RATE_LIMITED);
    expect(
      deriveCorpusStatus({
        statsError: "coverage sync did not finish",
        hasLoadedOnce: true,
      }),
    ).toBe(CORPUS_STATUS.PARTIAL);
    expect(
      deriveCorpusStatus({
        statsError: "Unable to build complete publication statistics.",
        hasLoadedOnce: true,
      }),
    ).toBe(CORPUS_STATUS.FAILED);
  });

  it("formats provider dedup captions only when records exceed unique works", () => {
    expect(
      formatProviderDedupCaption({
        uniqueCount: 97,
        providerTotalCount: 107,
        providerLabel: providerDisplayLabel(AUTHORS),
      }),
    ).toBe("97 unique publications from 107 OpenAlex records");
    expect(
      formatProviderDedupCaption({
        uniqueCount: 10,
        providerTotalCount: 10,
        providerLabel: "OpenAlex",
      }),
    ).toBeNull();
  });
});
