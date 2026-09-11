import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  authorIdentityKeys,
  isAuthorAlreadySelected,
  selectedAuthorIdentityKeySet,
} from "./authorSearchIdentity";
import {
  ENTITY_TYPES,
  SEARCH_SOURCES,
  sourceUsesOpenAlexAuthorFilters,
  unifiedSearch,
} from "./searchApi";

vi.mock("./client", () => ({
  default: {
    get: vi.fn(),
  },
}));

import apiClient from "./client";

describe("authorSearchIdentity", () => {
  it("matches resolved canonical authors to OpenAlex search hits", () => {
    const selected = {
      id: "11111111-1111-4111-8111-111111111111",
      result_id: "11111111-1111-4111-8111-111111111111",
      openalex_id: "A501",
      orcid: "0000-0001-6860-9566",
      source_records: [
        { provider: "openalex", provider_author_id: "A501" },
        { provider: "orcid", provider_author_id: "0000-0001-6860-9566" },
      ],
    };
    const hit = {
      result_id: "openalex:A501",
      source: "openalex",
      openalex_id: "A501",
      display_name: "Lin Lin",
    };
    const keys = selectedAuthorIdentityKeySet([selected]);
    expect(isAuthorAlreadySelected(hit, keys)).toBe(true);
    expect(authorIdentityKeys(hit).has("openalex:A501")).toBe(true);
  });

  it("matches ORCID search hits without using names", () => {
    const selected = {
      result_id: "orcid:0000-0001-6860-9566",
      source: "orcid",
      orcid: "0000-0001-6860-9566",
      display_name: "Lin Lin",
    };
    const samePerson = {
      result_id: "openalex:A9",
      source: "openalex",
      openalex_id: "A9",
      orcid: "https://orcid.org/0000-0001-6860-9566",
      display_name: "L. Lin",
    };
    const otherPerson = {
      result_id: "openalex:A0",
      source: "openalex",
      openalex_id: "A0",
      orcid: null,
      display_name: "Lin Lin",
    };
    const keys = selectedAuthorIdentityKeySet([selected]);
    expect(isAuthorAlreadySelected(samePerson, keys)).toBe(true);
    expect(isAuthorAlreadySelected(otherPerson, keys)).toBe(false);
  });
});

describe("unifiedSearch author source and filters", () => {
  beforeEach(() => {
    apiClient.get.mockReset();
    apiClient.get.mockResolvedValue({
      data: { results: [], next_cursor: null, has_more: false, source: "all" },
    });
  });

  it("sends the selected source and OpenAlex filters", async () => {
    await unifiedSearch({
      query: "Lin Lin",
      entityType: ENTITY_TYPES.AUTHORS,
      source: SEARCH_SOURCES.OPENALEX,
      institutionId: "I123",
      topicId: "T456",
    });

    expect(apiClient.get).toHaveBeenCalledWith(
      "/search",
      expect.objectContaining({
        params: expect.objectContaining({
          source: "openalex",
          provider: "openalex",
          entity_type: "authors",
          institution_id: "I123",
          topic_id: "T456",
        }),
      }),
    );
  });

  it("sends ORCID source without OpenAlex filters", async () => {
    await unifiedSearch({
      query: "Lin Lin",
      entityType: ENTITY_TYPES.AUTHORS,
      source: SEARCH_SOURCES.ORCID,
      institutionId: "I123",
      topicId: "T456",
    });

    const params = apiClient.get.mock.calls[0][1].params;
    expect(params.source).toBe("orcid");
    expect(params.institution_id).toBeUndefined();
    expect(params.topic_id).toBeUndefined();
  });

  it("only enables author filters for OpenAlex and All", () => {
    expect(sourceUsesOpenAlexAuthorFilters(SEARCH_SOURCES.ALL)).toBe(true);
    expect(sourceUsesOpenAlexAuthorFilters(SEARCH_SOURCES.OPENALEX)).toBe(true);
    expect(sourceUsesOpenAlexAuthorFilters(SEARCH_SOURCES.ORCID)).toBe(false);
  });
});
