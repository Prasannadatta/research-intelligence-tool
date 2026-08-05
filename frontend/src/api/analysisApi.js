import apiClient from "./client";

/**
 * Build a session-cache key for author publication analysis pages.
 * Example: author-publications:common:author-1,author-2:cursor-20
 */
export function buildAuthorPublicationsCacheKey({
  mode,
  canonicalAuthorIds = [],
  providerRecordsKey = "",
  filtersKey = "",
  cursor = "*",
  limit = 20,
}) {
  const sortedIds = [...canonicalAuthorIds].filter(Boolean).sort().join(",");
  const pageCursor = cursor == null || cursor === "" ? "*" : String(cursor);
  const cursorLabel = pageCursor === "*" ? "start" : `cursor-${limit}`;
  return [
    "author-publications",
    mode || "single",
    sortedIds || "none",
    providerRecordsKey || "-",
    filtersKey || "-",
    cursorLabel,
    pageCursor,
  ].join(":");
}

export function toAnalysisAuthorPayload(item) {
  if (!item || typeof item !== "object") {
    return null;
  }

  // Already in analysis request shape.
  if (
    item.canonical_author_id &&
    item.provider &&
    item.provider_author_id &&
    item.display_name
  ) {
    return {
      canonical_author_id: String(item.canonical_author_id),
      provider: String(item.provider).toLowerCase(),
      provider_author_id: String(item.provider_author_id),
      display_name: String(item.display_name).trim(),
    };
  }

  const sourceRecords = Array.isArray(item?.source_records)
    ? item.source_records
    : [];
  const openalex = sourceRecords.find((row) => row?.provider === "openalex");
  const arxiv = sourceRecords.find((row) => row?.provider === "arxiv");

  let provider = openalex?.provider || arxiv?.provider || item?.source || null;
  let providerAuthorId =
    openalex?.provider_author_id ||
    arxiv?.provider_author_id ||
    item?.openalex_id ||
    null;

  if (!provider || !providerAuthorId) {
    if (item?.openalex_id) {
      provider = "openalex";
      providerAuthorId = item.openalex_id;
    } else if (item?.result_type === "author_name" || item?.source === "arxiv") {
      provider = "arxiv";
      providerAuthorId = item?.result_id || item?.display_name;
    }
  }

  const canonicalAuthorId =
    item?.id || item?.result_id || item?.canonical_author_id;
  const displayName = item?.display_name || "";

  if (!canonicalAuthorId || !provider || !providerAuthorId || !displayName) {
    return null;
  }

  return {
    canonical_author_id: String(canonicalAuthorId),
    provider: String(provider).toLowerCase(),
    provider_author_id: String(providerAuthorId),
    display_name: String(displayName).trim(),
  };
}

export function analysisModeForAuthors(authors) {
  return Array.isArray(authors) && authors.length > 1
    ? "common_publications"
    : "single_author";
}

/**
 * POST /api/analysis/authors/publications
 */
export async function fetchAuthorPublications({
  authors,
  originalAuthorIds,
  filters,
  limit = 20,
  cursor,
  signal,
} = {}) {
  const payload = {
    authors: Array.isArray(authors) ? authors : [],
    limit,
    cursor: cursor == null || cursor === "" ? null : cursor,
  };

  if (Array.isArray(originalAuthorIds) && originalAuthorIds.length > 0) {
    payload.original_author_ids = originalAuthorIds;
  }

  if (filters && typeof filters === "object" && Object.keys(filters).length > 0) {
    payload.filters = filters;
  }

  const response = await apiClient.post("/analysis/authors/publications", payload, {
    timeout: 45000,
    signal,
  });

  const data = response.data || {};
  return {
    mode: data.mode || analysisModeForAuthors(payload.authors),
    authors: Array.isArray(data.authors) ? data.authors : payload.authors,
    items: Array.isArray(data.items) ? data.items : [],
    timeline: data.timeline ?? null,
    facets: data.facets || { sources: [], venues: [], grants: [] },
    pagination: data.pagination || {
      next_cursor: null,
      has_more: false,
    },
    next_cursor: data.pagination?.next_cursor ?? null,
    has_more: Boolean(data.pagination?.has_more),
    unsupported: Boolean(data.unsupported),
    unsupported_reason: data.unsupported_reason || null,
  };
}

/**
 * POST /api/analysis/authors/publications/venues/search
 */
export async function searchAuthorPublicationVenues({
  authors,
  query = "",
  limit = 20,
  signal,
} = {}) {
  const response = await apiClient.post(
    "/analysis/authors/publications/venues/search",
    {
      authors: Array.isArray(authors) ? authors : [],
      query,
      limit,
    },
    { timeout: 30000, signal },
  );
  return Array.isArray(response.data) ? response.data : [];
}

/**
 * POST /api/analysis/authors/publications/grants/search
 */
export async function searchAuthorPublicationGrants({
  authors,
  query = "",
  limit = 20,
  signal,
} = {}) {
  const response = await apiClient.post(
    "/analysis/authors/publications/grants/search",
    {
      authors: Array.isArray(authors) ? authors : [],
      query,
      limit,
    },
    { timeout: 30000, signal },
  );
  return Array.isArray(response.data) ? response.data : [];
}

/**
 * POST /api/analysis/authors/publications/export
 * Returns the raw axios response (blob) for client-side download.
 */
export async function exportAuthorPublicationsCsv({
  authors,
  filters,
  signal,
} = {}) {
  const payload = {
    authors: Array.isArray(authors) ? authors : [],
  };

  if (filters && typeof filters === "object" && Object.keys(filters).length > 0) {
    payload.filters = filters;
  }

  return apiClient.post("/analysis/authors/publications/export", payload, {
    timeout: 120000,
    signal,
    responseType: "blob",
  });
}
