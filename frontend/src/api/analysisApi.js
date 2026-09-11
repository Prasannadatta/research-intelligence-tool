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
  sortKey = "",
  cursor = "*",
  page = 1,
  limit = 20,
}) {
  const sortedIds = [...canonicalAuthorIds].filter(Boolean).sort().join(",");
  const pageCursor = cursor == null || cursor === "" ? "*" : String(cursor);
  const pageNumber = Number.isFinite(Number(page)) && Number(page) >= 1 ? Number(page) : 1;
  return [
    "author-publications",
    mode || "single",
    sortedIds || "none",
    providerRecordsKey || "-",
    filtersKey || "-",
    sortKey || "-",
    `page-${pageNumber}`,
    `limit-${limit}`,
    pageCursor === "*" ? "start" : pageCursor,
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
  const orcidRecord = sourceRecords.find((row) => row?.provider === "orcid");

  // Prefer OpenAlex for analysis crawl/sync; fall back to arXiv, then ORCID.
  let provider = openalex?.provider || arxiv?.provider || null;
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
    } else if (item?.orcid || orcidRecord?.provider_author_id) {
      // ORCID-only: allow Analyze to open with an explicit incomplete/unsupported path.
      provider = "orcid";
      providerAuthorId = item?.orcid || orcidRecord.provider_author_id;
    } else if (item?.source === "orcid" && item?.provider_author_id) {
      provider = "orcid";
      providerAuthorId = item.provider_author_id;
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
  sortBy,
  sortDirection,
  limit = 20,
  cursor,
  page,
  signal,
} = {}) {
  const payload = {
    authors: Array.isArray(authors) ? authors : [],
    limit,
    cursor: cursor == null || cursor === "" ? null : cursor,
  };

  if (page != null && Number(page) >= 1) {
    payload.page = Number(page);
  }

  if (Array.isArray(originalAuthorIds) && originalAuthorIds.length > 0) {
    payload.original_author_ids = originalAuthorIds;
  }

  if (filters && typeof filters === "object" && Object.keys(filters).length > 0) {
    payload.filters = filters;
  }
  if (sortBy) {
    payload.sort_by = sortBy;
    payload.sort_direction = sortDirection === "asc" ? "asc" : "desc";
  }

  const started = performance.now();
  console.info("[analysis-timing] publications_start", {
    authors: payload.authors.length,
    cursor: payload.cursor,
    page: payload.page ?? null,
    hasFilters: Boolean(payload.filters),
  });
  const response = await apiClient.post("/analysis/authors/publications", payload, {
    timeout: 45000,
    signal,
  });
  console.info("[analysis-timing] publications_done", {
    ms: Math.round(performance.now() - started),
    items: Array.isArray(response.data?.items) ? response.data.items.length : 0,
    hasMore: Boolean(response.data?.pagination?.has_more),
    page: response.data?.pagination?.page ?? null,
    total: response.data?.pagination?.total ?? null,
  });

  const data = response.data || {};
  const pagination = data.pagination || {};
  return {
    mode: data.mode || analysisModeForAuthors(payload.authors),
    authors: Array.isArray(data.authors) ? data.authors : payload.authors,
    items: Array.isArray(data.items) ? data.items : [],
    timeline: data.timeline ?? null,
    facets: data.facets || { sources: [], institutions: [], venues: [], grants: [], authors: [] },
    provider_total_count: Number.isFinite(Number(data.provider_total_count))
      && data.provider_total_count != null
      && data.provider_total_count !== ""
      && Number(data.provider_total_count) >= 0
      ? Number(data.provider_total_count)
      : null,
    pagination: {
      next_cursor: pagination.next_cursor ?? null,
      has_more: Boolean(pagination.has_more),
      page: Number.isFinite(Number(pagination.page)) ? Number(pagination.page) : (page || 1),
      offset: Number.isFinite(Number(pagination.offset)) ? Number(pagination.offset) : 0,
      limit: Number.isFinite(Number(pagination.limit)) ? Number(pagination.limit) : limit,
      total: Number.isFinite(Number(pagination.total)) && pagination.total != null
        ? Number(pagination.total)
        : null,
      corpus_source: pagination.corpus_source || null,
    },
    next_cursor: pagination.next_cursor ?? null,
    has_more: Boolean(pagination.has_more),
    unsupported: Boolean(data.unsupported),
    unsupported_reason: data.unsupported_reason || null,
  };
}

function buildAuthorInsightsPayload({
  authors,
  filters,
  excludedWorkIds,
  retryIncompleteOnly = false,
} = {}) {
  const normalizedAuthors = Array.isArray(authors)
    ? authors
        .map((author) => ({
          canonical_author_id: String(author?.canonical_author_id || "").trim(),
          display_name: String(author?.display_name || author?.name || "").trim(),
        }))
        .filter((author) => author.canonical_author_id)
    : [];

  const payload = {
    authors: normalizedAuthors,
    excluded_work_ids: Array.isArray(excludedWorkIds)
      ? excludedWorkIds.map((id) => String(id)).filter(Boolean)
      : [],
    filters: {
      from_year: filters?.from_year ?? null,
      to_year: filters?.to_year ?? null,
      sources: Array.isArray(filters?.sources) ? filters.sources : [],
      institutions: Array.isArray(filters?.institutions) ? filters.institutions : [],
      venues: Array.isArray(filters?.venues) ? filters.venues : [],
      grant_numbers: Array.isArray(filters?.grant_numbers)
        ? filters.grant_numbers
        : [],
    },
  };
  if (retryIncompleteOnly) {
    payload.retry_incomplete_only = true;
  }
  return payload;
}

/**
 * POST /api/analysis/authors/insights/jobs
 * Uses the default client timeout. Do not use the old 45s Insights timeout.
 */
export async function createAuthorInsightsJob({
  authors,
  filters,
  excludedWorkIds,
  retryIncompleteOnly = false,
  signal,
} = {}) {
  const response = await apiClient.post(
    "/analysis/authors/insights/jobs",
    buildAuthorInsightsPayload({ authors, filters, excludedWorkIds, retryIncompleteOnly }),
    { signal },
  );
  return response.data || {};
}

/**
 * GET /api/analysis/authors/insights/jobs/{jobId}
 */
export async function getAuthorInsightsJob(jobId, { signal } = {}) {
  const response = await apiClient.get(`/analysis/authors/insights/jobs/${jobId}`, {
    signal,
  });
  return response.data || {};
}

/**
 * POST /api/analysis/authors/publications/stats/jobs
 */
export async function createAuthorPublicationStatsJob({
  authors,
  filters,
  retryIncompleteOnly = false,
  signal,
} = {}) {
  const response = await apiClient.post(
    "/analysis/authors/publications/stats/jobs",
    buildAuthorInsightsPayload({ authors, filters, retryIncompleteOnly }),
    { signal },
  );
  return response.data || {};
}

/**
 * GET /api/analysis/authors/publications/stats/jobs/{jobId}
 */
export async function getAuthorPublicationStatsJob(jobId, { signal } = {}) {
  const response = await apiClient.get(
    `/analysis/authors/publications/stats/jobs/${jobId}`,
    { signal },
  );
  return response.data || {};
}

/**
 * POST /api/analysis/authors/insights (legacy blocking endpoint)
 */
export async function fetchAuthorInsights({ authors, filters, excludedWorkIds, signal } = {}) {
  const response = await apiClient.post(
    "/analysis/authors/insights",
    buildAuthorInsightsPayload({ authors, filters, excludedWorkIds }),
    {
      timeout: 45000,
      signal,
    },
  );
  return response.data || {};
}

/**
 * POST /api/analysis/authors/insights/publications
 */
export async function fetchAuthorInsightsPublications({
  authors,
  combinationId,
  filters,
  excludedWorkIds,
  cursor,
  limit = 20,
  signal,
} = {}) {
  const normalizedAuthors = Array.isArray(authors)
    ? authors
        .map((author) => ({
          canonical_author_id: String(author?.canonical_author_id || "").trim(),
          display_name: String(author?.display_name || author?.name || "").trim(),
        }))
        .filter((author) => author.canonical_author_id)
    : [];

  const payload = {
    authors: normalizedAuthors,
    combination_id: String(combinationId || "").trim(),
    excluded_work_ids: Array.isArray(excludedWorkIds)
      ? excludedWorkIds.map((id) => String(id)).filter(Boolean)
      : [],
    filters: {
      from_year: filters?.from_year ?? null,
      to_year: filters?.to_year ?? null,
      sources: Array.isArray(filters?.sources) ? filters.sources : [],
      institutions: Array.isArray(filters?.institutions) ? filters.institutions : [],
      venues: Array.isArray(filters?.venues) ? filters.venues : [],
      grant_numbers: Array.isArray(filters?.grant_numbers)
        ? filters.grant_numbers
        : [],
    },
    cursor: cursor == null || cursor === "" ? null : cursor,
    limit,
  };

  const response = await apiClient.post(
    "/analysis/authors/insights/publications",
    payload,
    {
      timeout: 45000,
      signal,
    },
  );
  const data = response.data || {};
  return {
    combinationId: data.combination_id || payload.combination_id,
    items: Array.isArray(data.items) ? data.items : [],
    pagination: data.pagination || {
      next_cursor: null,
      has_more: false,
    },
    nextCursor: data.pagination?.next_cursor ?? null,
    hasMore: Boolean(data.pagination?.has_more),
  };
}

/**
 * POST /api/analysis/authors/publications/facets
 */
export async function fetchAuthorPublicationFacets({
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
  const started = performance.now();
  console.info("[analysis-timing] facets_start", {
    authors: payload.authors.length,
    hasFilters: Boolean(payload.filters),
  });
  const response = await apiClient.post("/analysis/authors/publications/facets", payload, {
    timeout: 45000,
    signal,
  });
  console.info("[analysis-timing] facets_done", {
    ms: Math.round(performance.now() - started),
    authors: payload.authors.map((row) => ({
      canonical_author_id: row.canonical_author_id,
      provider: row.provider,
      provider_author_id: row.provider_author_id,
    })),
    sources: (response.data?.sources || []).length,
    institutions: (response.data?.institutions || []).length,
    venues: (response.data?.venues || []).length,
    grants: (response.data?.grants || []).length,
    authors: (response.data?.authors || []).length,
  });
  return response.data || { sources: [], institutions: [], venues: [], grants: [], authors: [] };
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
