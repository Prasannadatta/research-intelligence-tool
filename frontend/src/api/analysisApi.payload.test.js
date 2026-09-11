import { describe, expect, it } from "vitest";

import { toAnalysisAuthorPayload } from "./analysisApi";

describe("toAnalysisAuthorPayload", () => {
  it("prefers OpenAlex when ORCID selection was linked", () => {
    const payload = toAnalysisAuthorPayload({
      id: "c-1",
      display_name: "Lin Lin",
      orcid: "0000-0001-6860-9566",
      source: "orcid",
      openalex_id: "A5107195431",
      source_records: [
        { provider: "orcid", provider_author_id: "0000-0001-6860-9566" },
        { provider: "openalex", provider_author_id: "A5107195431" },
      ],
    });
    expect(payload).toEqual({
      canonical_author_id: "c-1",
      provider: "openalex",
      provider_author_id: "A5107195431",
      display_name: "Lin Lin",
    });
  });

  it("keeps ORCID-only selections analyzable without claiming OpenAlex", () => {
    const payload = toAnalysisAuthorPayload({
      id: "c-2",
      display_name: "Lin Lin",
      orcid: "0000-0002-2400-5864",
      source: "orcid",
      source_records: [
        { provider: "orcid", provider_author_id: "0000-0002-2400-5864" },
      ],
    });
    expect(payload).toEqual({
      canonical_author_id: "c-2",
      provider: "orcid",
      provider_author_id: "0000-0002-2400-5864",
      display_name: "Lin Lin",
    });
  });

  it("maps OpenAlex selections normally", () => {
    const payload = toAnalysisAuthorPayload({
      id: "c-3",
      display_name: "Ada Lovelace",
      openalex_id: "A123",
      source: "openalex",
      source_records: [{ provider: "openalex", provider_author_id: "A123" }],
    });
    expect(payload).toEqual({
      canonical_author_id: "c-3",
      provider: "openalex",
      provider_author_id: "A123",
      display_name: "Ada Lovelace",
    });
  });
});
