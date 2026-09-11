import { describe, expect, it } from "vitest";

import {
  formatAffiliationLine,
  formatProviderLabel,
  getPreviousInstitutions,
  getProviderIds,
} from "./authorSummaryDisplay";

describe("authorSummaryDisplay", () => {
  it("formats provider labels and affiliation lines", () => {
    expect(formatProviderLabel("openalex")).toBe("OpenAlex");
    expect(formatAffiliationLine({
      name: "UC Berkeley",
      department: "Biology",
      country_code: "US",
      years: { from: 2018, to: 2020 },
    })).toBe("UC Berkeley · Biology · US · 2018–2020");
  });

  it("keeps previous affiliations source-aware and provider ids stable", () => {
    const summary = {
      institutions: [
        { name: "Current U", current: true, sources: ["openalex"] },
        { name: "Past U", current: false, sources: ["orcid"] },
      ],
      provider_ids: {
        openalex: ["A1"],
        orcid: ["0000-0002-1825-0097"],
        scopus: ["999"],
      },
    };
    expect(getPreviousInstitutions(summary)).toEqual([
      { name: "Past U", current: false, sources: ["orcid"] },
    ]);
    expect(getProviderIds(summary).scopus).toEqual(["999"]);
  });
});
