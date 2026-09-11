/**
 * Display helpers for saved searches.
 * Author identity is always by canonical/provider IDs — never name-only matching.
 */

export function authorEntries(item) {
  const authors = item?.payload?.authors;
  return Array.isArray(authors) ? authors.filter(Boolean) : [];
}

/** Compact author list: "A, B, C +17 more" for large selections. */
export function formatAuthorsCompact(authors, { visible = 3 } = {}) {
  const names = (Array.isArray(authors) ? authors : [])
    .map((author) => String(author?.display_name || "").trim())
    .filter(Boolean);
  if (names.length === 0) {
    return "—";
  }
  if (names.length <= visible) {
    return names.join(", ");
  }
  const shown = names.slice(0, visible).join(", ");
  return `${shown} +${names.length - visible} more`;
}

export function formatImportantFilters(filters = {}, providerContext = {}) {
  const parts = [];
  if (filters.from_year || filters.to_year) {
    parts.push(`${filters.from_year || "…"}–${filters.to_year || "…"}`);
  }
  const mode = providerContext?.mode || filters.analysis_mode;
  if (mode === "common_publications") {
    parts.push("Common pubs");
  } else if (mode === "single_author") {
    parts.push("Single author");
  }
  const sources = Array.isArray(filters.sources) ? filters.sources.filter(Boolean) : [];
  if (sources.length === 1) {
    parts.push(sources[0]);
  } else if (sources.length > 1) {
    parts.push(`${sources.length} sources`);
  }
  const institutions = Array.isArray(filters.institutions)
    ? filters.institutions.filter(Boolean)
    : [];
  if (institutions.length === 1) {
    parts.push(institutions[0]);
  } else if (institutions.length > 1) {
    parts.push(`${institutions.length} institutions`);
  }
  const venues = Array.isArray(filters.venues) ? filters.venues.filter(Boolean) : [];
  if (venues.length === 1) {
    parts.push(venues[0]);
  } else if (venues.length > 1) {
    parts.push(`${venues.length} venues`);
  }
  const grants = Array.isArray(filters.grant_numbers)
    ? filters.grant_numbers.filter(Boolean)
    : [];
  if (grants.length === 1) {
    parts.push(grants[0]);
  } else if (grants.length > 1) {
    parts.push(`${grants.length} grants`);
  }
  const authors = Array.isArray(filters.authors) ? filters.authors.filter(Boolean) : [];
  if (authors.length === 1) {
    parts.push(authors[0]);
  } else if (authors.length > 1) {
    parts.push(`${authors.length} authors`);
  }
  return parts.length > 0 ? parts.join(" · ") : "No filters";
}

export function formatSavedDate(value) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

export function matchesSavedSearchQuery(item, query) {
  const needle = String(query || "")
    .trim()
    .toLowerCase();
  if (!needle) {
    return true;
  }
  if (String(item?.display_name || "")
    .toLowerCase()
    .includes(needle)) {
    return true;
  }
  for (const author of authorEntries(item)) {
    if (
      String(author.display_name || "")
        .toLowerCase()
        .includes(needle)
    ) {
      return true;
    }
  }
  const grantNumber = String(item?.payload?.grant_number || "").toLowerCase();
  return Boolean(grantNumber && grantNumber.includes(needle));
}

/** Build the POST/lookup body for the current Analyze Authors configuration. */
export function buildAuthorSavedSearchBody({
  authors,
  filters,
  excludedWorkIds = [],
  mode,
  displayName,
}) {
  const authorsToSave = (Array.isArray(authors) ? authors : []).filter(
    (author) => author?.canonical_author_id && author?.display_name,
  );
  const activeIds = authorsToSave.map((author) => author.canonical_author_id);
  const providerContext = {
    providers: [
      ...new Set(
        authorsToSave
          .map((author) => String(author.provider || "").toLowerCase())
          .filter(Boolean),
      ),
    ],
    mode,
  };
  const body = {
    search_type: "authors",
    payload: {
      authors: authorsToSave.map((author) => ({
        canonical_author_id: author.canonical_author_id,
        display_name: author.display_name,
        provider: author.provider,
        provider_author_id: author.provider_author_id,
      })),
      active_author_ids: activeIds,
      analysis_mode: mode,
      filters: filters || {},
      excluded_work_ids: excludedWorkIds,
      provider_context: providerContext,
    },
    applied_filters: filters || {},
    provider_context: providerContext,
    excluded_work_ids: excludedWorkIds,
    metadata: {
      author_count: authorsToSave.length,
      active_author_count: authorsToSave.length,
    },
  };
  const name = String(displayName || "").trim();
  if (name) {
    body.display_name = name;
  }
  return body;
}

export function filtersFromSavedPayload(filters = {}) {
  return {
    from_year: filters.from_year ?? null,
    to_year: filters.to_year ?? null,
    sources: Array.isArray(filters.sources) ? [...filters.sources] : [],
    institutions: Array.isArray(filters.institutions) ? [...filters.institutions] : [],
    venues: Array.isArray(filters.venues) ? [...filters.venues] : [],
    grant_numbers: Array.isArray(filters.grant_numbers) ? [...filters.grant_numbers] : [],
    authors: Array.isArray(filters.authors) ? [...filters.authors] : [],
  };
}
