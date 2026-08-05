import apiClient from "./client";

export const GRANT_SUGGESTION_MIN_CHARS = 2;
export const GRANT_SUGGESTION_LIMIT = 10;
export const GRANT_PUBLICATIONS_PAGE_SIZE = 20;

/**
 * Normalize a grant number for display / navigation (preserve case, collapse spaces).
 */
export function normalizeGrantInput(value) {
  return String(value || "")
    .trim()
    .replace(/\s+/g, " ");
}

/**
 * Compact alphanumeric form used for stable keys / comparison.
 */
export function compactGrantNumber(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

export function grantSuggestionKey(item) {
  if (!item) {
    return "";
  }
  const provider = String(item.provider || "").toLowerCase();
  const normalized =
    item.normalized_grant_number || compactGrantNumber(item.grant_number);
  return `${provider}:${normalized}`;
}

export function buildGrantPublicationsPath(grantNumber, provider) {
  const cleaned = normalizeGrantInput(grantNumber);
  if (!cleaned) {
    return null;
  }
  const source = String(provider || "openalex").toLowerCase();
  return `/grants/${encodeURIComponent(cleaned)}?provider=${encodeURIComponent(source)}`;
}

export function isValidGrantNavigationInput(value) {
  return normalizeGrantInput(value).length >= GRANT_SUGGESTION_MIN_CHARS;
}

export function buildGrantPublicationsCacheKey({
  grantNumber,
  provider,
  filtersKey = "",
  cursor = "*",
  limit = GRANT_PUBLICATIONS_PAGE_SIZE,
}) {
  const normalized = compactGrantNumber(grantNumber) || "none";
  const source = String(provider || "openalex").toLowerCase();
  const pageCursor = cursor == null || cursor === "" ? "*" : String(cursor);
  const cursorLabel = pageCursor === "*" ? "start" : `cursor-${limit}`;
  return [
    "grant-publications",
    source,
    normalized,
    filtersKey || "-",
    cursorLabel,
    pageCursor,
  ].join(":");
}

/**
 * GET /api/grants/suggestions
 */
export async function fetchGrantSuggestions({
  q,
  provider,
  limit = GRANT_SUGGESTION_LIMIT,
  signal,
} = {}) {
  const query = normalizeGrantInput(q);
  const response = await apiClient.get("/grants/suggestions", {
    params: {
      q: query,
      provider: String(provider || "openalex").toLowerCase(),
      limit,
    },
    timeout: 20000,
    signal,
  });
  const data = response.data || {};
  const items = Array.isArray(data.items) ? data.items : [];
  return { items };
}

/**
 * GET /api/grants/{grant_number}/publications
 */
export async function fetchGrantPublications({
  grantNumber,
  provider,
  cursor,
  limit = GRANT_PUBLICATIONS_PAGE_SIZE,
  filters,
  signal,
} = {}) {
  const cleaned = normalizeGrantInput(grantNumber);
  const params = {
    provider: String(provider || "openalex").toLowerCase(),
    limit,
    cursor: cursor == null || cursor === "" ? undefined : cursor,
  };

  if (filters && typeof filters === "object" && Object.keys(filters).length > 0) {
    params.filters = JSON.stringify(filters);
  }

  const response = await apiClient.get(
    `/grants/${encodeURIComponent(cleaned)}/publications`,
    {
      params,
      timeout: 45000,
      signal,
    },
  );

  const data = response.data || {};
  return {
    grant_number: data.grant_number || cleaned,
    normalized_grant_number: data.normalized_grant_number || compactGrantNumber(cleaned),
    provider: data.provider || String(provider || "openalex").toLowerCase(),
    funder_name: data.funder_name || null,
    verified: Boolean(data.verified),
    match_type: data.match_type || null,
    items: Array.isArray(data.items) ? data.items : [],
    timeline: data.timeline ?? null,
    facets: data.facets || { sources: [], venues: [], grants: [], authors: [] },
    pagination: data.pagination || {
      next_cursor: null,
      has_more: false,
    },
    next_cursor: data.pagination?.next_cursor ?? null,
    has_more: Boolean(data.pagination?.has_more),
  };
}

/**
 * GET /api/grants/{grant_number}/publications/venues/search
 */
export async function searchGrantPublicationVenues({
  grantNumber,
  provider,
  query = "",
  limit = 20,
  signal,
} = {}) {
  const cleaned = normalizeGrantInput(grantNumber);
  const response = await apiClient.get(
    `/grants/${encodeURIComponent(cleaned)}/publications/venues/search`,
    {
      params: {
        provider: String(provider || "openalex").toLowerCase(),
        q: query,
        limit,
      },
      timeout: 30000,
      signal,
    },
  );
  const data = response.data;
  if (Array.isArray(data)) {
    return data;
  }
  return Array.isArray(data?.items) ? data.items : [];
}

/**
 * GET /api/grants/{grant_number}/publications/authors/search
 */
export async function searchGrantPublicationAuthors({
  grantNumber,
  provider,
  query = "",
  limit = 20,
  signal,
} = {}) {
  const cleaned = normalizeGrantInput(grantNumber);
  const response = await apiClient.get(
    `/grants/${encodeURIComponent(cleaned)}/publications/authors/search`,
    {
      params: {
        provider: String(provider || "openalex").toLowerCase(),
        q: query,
        limit,
      },
      timeout: 30000,
      signal,
    },
  );
  const data = response.data;
  if (Array.isArray(data)) {
    return data;
  }
  return Array.isArray(data?.items) ? data.items : [];
}

/**
 * POST /api/grants/{grant_number}/publications/export
 * Returns the raw axios response (blob) for client-side download.
 */
export async function exportGrantPublicationsCsv({
  grantNumber,
  provider,
  filters,
  signal,
} = {}) {
  const cleaned = normalizeGrantInput(grantNumber);
  const payload = {
    provider: String(provider || "openalex").toLowerCase(),
  };

  if (filters && typeof filters === "object" && Object.keys(filters).length > 0) {
    payload.filters = filters;
  }

  return apiClient.post(
    `/grants/${encodeURIComponent(cleaned)}/publications/export`,
    payload,
    {
      timeout: 120000,
      signal,
      responseType: "blob",
    },
  );
}
