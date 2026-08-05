/**
 * Pure helpers for publication filters on /analyze/authors and grant publications.
 */

export const PUBLICATION_FILTER_DEBOUNCE_MS = 300;

export function emptyPublicationFilters() {
  return {
    fromYear: "",
    toYear: "",
    sources: [],
    venues: [],
    grants: [],
    authors: [],
  };
}

export function clonePublicationFilters(filters) {
  const source = filters && typeof filters === "object" ? filters : emptyPublicationFilters();
  return {
    fromYear: source.fromYear ?? "",
    toYear: source.toYear ?? "",
    sources: Array.isArray(source.sources) ? [...source.sources] : [],
    venues: Array.isArray(source.venues) ? source.venues.map((row) => ({ ...row })) : [],
    grants: Array.isArray(source.grants) ? source.grants.map((row) => ({ ...row })) : [],
    authors: Array.isArray(source.authors) ? source.authors.map((row) => ({ ...row })) : [],
  };
}

function yearInputText(value) {
  if (value == null) {
    return "";
  }
  return String(value).trim();
}

export function normalizeYearInput(value) {
  const text = yearInputText(value);
  if (!text) {
    return null;
  }
  if (!/^\d{4}$/.test(text)) {
    return null;
  }
  const parsed = Number.parseInt(text, 10);
  if (!Number.isFinite(parsed) || parsed < 1000 || parsed > 2100) {
    return null;
  }
  return parsed;
}

/**
 * Validate draft year fields. Empty years are allowed.
 * Partially typed non-empty values are invalid until they are four digits.
 */
export function validatePublicationFilters(filters) {
  const fromText = yearInputText(filters?.fromYear);
  const toText = yearInputText(filters?.toYear);
  const errors = {};

  let fromYear = null;
  let toYear = null;

  if (fromText) {
    if (!/^\d{4}$/.test(fromText)) {
      errors.fromYear = "Enter a four-digit year";
    } else {
      fromYear = Number.parseInt(fromText, 10);
      if (fromYear < 1000 || fromYear > 2100) {
        errors.fromYear = "Year must be between 1000 and 2100";
        fromYear = null;
      }
    }
  }

  if (toText) {
    if (!/^\d{4}$/.test(toText)) {
      errors.toYear = "Enter a four-digit year";
    } else {
      toYear = Number.parseInt(toText, 10);
      if (toYear < 1000 || toYear > 2100) {
        errors.toYear = "Year must be between 1000 and 2100";
        toYear = null;
      }
    }
  }

  if (fromYear != null && toYear != null && fromYear > toYear) {
    errors.range = "From year cannot be greater than To year";
  }

  return {
    valid: Object.keys(errors).length === 0,
    errors,
    fromYear,
    toYear,
  };
}

export function toPublicationFiltersPayload(filters) {
  const validation = validatePublicationFilters(filters);
  if (!validation.valid) {
    return {};
  }

  const sources = Array.isArray(filters?.sources)
    ? [...new Set(filters.sources.map((value) => String(value).toLowerCase()).filter(Boolean))]
    : [];
  const venues = Array.isArray(filters?.venues)
    ? filters.venues
        .map((row) => row?.label || row?.value || row)
        .map((value) => String(value || "").trim())
        .filter(Boolean)
    : [];
  const grantNumbers = Array.isArray(filters?.grants)
    ? filters.grants
        .map((row) => row?.grant_number || row)
        .map((value) => String(value || "").trim())
        .filter(Boolean)
    : [];
  const authors = Array.isArray(filters?.authors)
    ? [
        ...new Set(
          filters.authors
            .map((row) => row?.value || row)
            .map((value) => String(value || "").trim())
            .filter(Boolean),
        ),
      ]
    : [];

  const payload = {};
  if (validation.fromYear != null) {
    payload.from_year = validation.fromYear;
  }
  if (validation.toYear != null) {
    payload.to_year = validation.toYear;
  }
  if (sources.length > 0) {
    payload.sources = sources;
  }
  if (venues.length > 0) {
    payload.venues = venues;
  }
  if (grantNumbers.length > 0) {
    payload.grant_numbers = grantNumbers;
  }
  if (authors.length > 0) {
    payload.authors = authors;
  }
  return payload;
}

export function publicationFiltersKey(filters) {
  const payload = toPublicationFiltersPayload(filters);
  return [
    `from:${payload.from_year ?? ""}`,
    `to:${payload.to_year ?? ""}`,
    `sources:${(payload.sources || []).join(",")}`,
    `venues:${(payload.venues || []).slice().sort().join("|")}`,
    `grants:${(payload.grant_numbers || []).slice().sort().join("|")}`,
    `authors:${(payload.authors || []).slice().sort().join("|")}`,
  ].join(";");
}

export function hasActivePublicationFilters(filters) {
  return Object.keys(toPublicationFiltersPayload(filters)).length > 0;
}

export function countActivePublicationFilters(filters) {
  const payload = toPublicationFiltersPayload(filters);
  let count = 0;
  if (payload.from_year != null || payload.to_year != null) {
    count += 1;
  }
  count += (payload.sources || []).length;
  count += (payload.venues || []).length;
  count += (payload.grant_numbers || []).length;
  count += (payload.authors || []).length;
  return count;
}

export function publicationFiltersEqual(left, right) {
  return publicationFiltersKey(left) === publicationFiltersKey(right);
}

export function buildAppliedFilterChips(filters, sourceOptions = []) {
  const chips = [];
  const validation = validatePublicationFilters(filters);
  if (!validation.valid) {
    return chips;
  }

  if (validation.fromYear != null || validation.toYear != null) {
    const fromLabel = validation.fromYear != null ? String(validation.fromYear) : "…";
    const toLabel = validation.toYear != null ? String(validation.toYear) : "…";
    chips.push({
      id: "years",
      kind: "years",
      label: `${fromLabel}–${toLabel}`,
    });
  }

  for (const value of filters?.sources || []) {
    const option = sourceOptions.find((row) => row.value === value);
    chips.push({
      id: `source:${value}`,
      kind: "source",
      value,
      label: option?.label || value,
    });
  }

  for (const venue of filters?.venues || []) {
    chips.push({
      id: `venue:${venue.value}`,
      kind: "venue",
      value: venue.value,
      label: venue.label || venue.value,
    });
  }

  for (const grant of filters?.grants || []) {
    chips.push({
      id: `grant:${grant.grant_number}`,
      kind: "grant",
      value: grant.grant_number,
      label: grant.grant_number,
    });
  }

  for (const author of filters?.authors || []) {
    chips.push({
      id: `author:${author.value}`,
      kind: "author",
      value: author.value,
      label: author.label || author.value,
    });
  }

  return chips;
}

export function removeFilterChip(filters, chip) {
  const next = clonePublicationFilters(filters);
  if (!chip) {
    return next;
  }
  if (chip.kind === "years") {
    next.fromYear = "";
    next.toYear = "";
    return next;
  }
  if (chip.kind === "source") {
    next.sources = next.sources.filter((value) => value !== chip.value);
    return next;
  }
  if (chip.kind === "venue") {
    next.venues = next.venues.filter((row) => row.value !== chip.value);
    return next;
  }
  if (chip.kind === "grant") {
    next.grants = next.grants.filter((row) => row.grant_number !== chip.value);
    return next;
  }
  if (chip.kind === "author") {
    next.authors = next.authors.filter((row) => row.value !== chip.value);
  }
  return next;
}

export function emptyFacets() {
  return {
    sources: [],
    venues: [],
    grants: [],
    authors: [],
  };
}
