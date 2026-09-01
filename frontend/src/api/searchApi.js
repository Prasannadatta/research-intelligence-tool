import apiClient from "./client";

export const ENTITY_TYPES = {
  AUTHORS: "authors",
  WORKS: "works",
  GRANTS: "grants",
};

export const SEARCH_SOURCES = {
  OPENALEX: "openalex",
  ARXIV: "arxiv",
  ORCID: "orcid",
  ALL: "all",
};

export const ENTITY_PLACEHOLDERS = {
  authors: "Search authors by name, ORCID, or grant number",
  works: "Search papers by title, topic, author, or grant number",
  grants: "Enter a grant or award number",
};

export const MIN_QUERY_LENGTH = {
  authors: 3,
  works: 3,
  grants: 2,
};

export const FALLBACK_CAPABILITIES = {
  default_source: SEARCH_SOURCES.ALL,
  sources: [
    {
      id: SEARCH_SOURCES.OPENALEX,
      label: "OpenAlex",
      enabled: true,
      supported_entity_types: ["authors", "works", "grants"],
    },
    {
      id: SEARCH_SOURCES.ARXIV,
      label: "arXiv",
      enabled: false,
      supported_entity_types: [],
    },
    {
      id: SEARCH_SOURCES.ORCID,
      label: "ORCID",
      enabled: true,
      supported_entity_types: ["authors"],
    },
    {
      id: SEARCH_SOURCES.ALL,
      label: "All sources",
      enabled: true,
      supported_entity_types: ["authors", "works", "grants"],
    },
  ],
};

const ORCID_ID_RE = /^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/i;

export function looksLikeOrcidQuery(query) {
  const text = String(query || "")
    .trim()
    .replace(/^https?:\/\/orcid\.org\//i, "")
    .replace(/\/$/, "");
  return ORCID_ID_RE.test(text);
}

/**
 * Normalize search query for requests and cache keys.
 * Grants preserve letter case; authors/works use lowercase.
 */
export function normalizeSearchQuery(query, entityType = ENTITY_TYPES.AUTHORS) {
  const collapsed = String(query || "")
    .trim()
    .replace(/\s+/g, " ");
  if (entityType === ENTITY_TYPES.GRANTS) {
    return collapsed;
  }
  if (entityType === ENTITY_TYPES.AUTHORS && looksLikeOrcidQuery(collapsed)) {
    const bare = collapsed.replace(/^https?:\/\/orcid\.org\//i, "").replace(/\/$/, "");
    return bare.slice(0, -1) + bare.slice(-1).toUpperCase();
  }
  return collapsed.toLowerCase();
}

export function minQueryLengthForEntity(entityType) {
  return MIN_QUERY_LENGTH[entityType] ?? 3;
}

export function isSourceCompatible(sourceCapability, entityType) {
  if (!sourceCapability?.enabled) {
    return false;
  }
  const supported = Array.isArray(sourceCapability.supported_entity_types)
    ? sourceCapability.supported_entity_types
    : [];
  return supported.includes(entityType);
}

export function resolveCompatibleSource(capabilities, entityType, preferredSource) {
  const sources = Array.isArray(capabilities?.sources) ? capabilities.sources : [];
  const preferred = sources.find((item) => item.id === preferredSource);
  if (preferred && isSourceCompatible(preferred, entityType)) {
    return preferred.id;
  }
  const defaultSource = capabilities?.default_source;
  const defaultCapability = sources.find((item) => item.id === defaultSource);
  if (defaultCapability && isSourceCompatible(defaultCapability, entityType)) {
    return defaultCapability.id;
  }
  const all = sources.find((item) => item.id === SEARCH_SOURCES.ALL);
  if (all && isSourceCompatible(all, entityType)) {
    return SEARCH_SOURCES.ALL;
  }
  const openalex = sources.find((item) => item.id === SEARCH_SOURCES.OPENALEX);
  if (openalex && isSourceCompatible(openalex, entityType)) {
    return SEARCH_SOURCES.OPENALEX;
  }
  const first = sources.find((item) => isSourceCompatible(item, entityType));
  return first?.id || SEARCH_SOURCES.ALL;
}

/**
 * Build a session-cache key. Cursor is opaque and never decoded.
 */
export function buildSearchCacheKey({
  source = SEARCH_SOURCES.OPENALEX,
  entityType,
  query,
  cursor = "*",
  institutionId = "",
  topicId = "",
}) {
  const normalizedQuery = normalizeSearchQuery(query, entityType);
  const pageCursor = cursor == null || cursor === "" ? "*" : String(cursor);
  return [
    source || SEARCH_SOURCES.OPENALEX,
    entityType,
    normalizedQuery,
    institutionId || "",
    topicId || "",
    pageCursor,
  ].join("|");
}

export async function fetchSearchCapabilities({ signal } = {}) {
  try {
    const response = await apiClient.get("/search/capabilities", {
      timeout: 10000,
      signal,
    });
    const data = response.data || {};
    if (!Array.isArray(data.sources) || data.sources.length === 0) {
      return FALLBACK_CAPABILITIES;
    }
    return {
      default_source: data.default_source || SEARCH_SOURCES.ALL,
      sources: data.sources,
    };
  } catch {
    return FALLBACK_CAPABILITIES;
  }
}

/**
 * Unified search via the backend.
 * Never sends or stores API keys in the frontend.
 * Never inspects or modifies provider cursors.
 */
export async function unifiedSearch({
  query,
  entityType,
  source = SEARCH_SOURCES.ALL,
  limit = 20,
  cursor,
  institutionId,
  topicId,
  knownAuthorIds = [],
  searchSessionId,
  signal,
} = {}) {
  const cleanedQuery = normalizeSearchQuery(query, entityType);
  const minLength = minQueryLengthForEntity(entityType);
  const sourceId = source || SEARCH_SOURCES.ALL;

  if (cleanedQuery.length < minLength) {
    return {
      query: cleanedQuery,
      entity_type: entityType,
      source: sourceId,
      results: [],
      items: [],
      updates: [],
      next_cursor: null,
      has_more: false,
      search_session_id: null,
    };
  }

  const params = {
    // Provider owns the entire search flow on the backend.
    provider: sourceId,
    source: sourceId,
    entity_type: entityType,
    entity: entityType,
    query: cleanedQuery,
    q: cleanedQuery,
    limit,
  };

  if (cursor != null && cursor !== "") {
    params.cursor = cursor;
  }

  if (
    (sourceId === SEARCH_SOURCES.OPENALEX || sourceId === SEARCH_SOURCES.ALL) &&
    entityType === ENTITY_TYPES.AUTHORS &&
    institutionId
  ) {
    params.institution_id = institutionId;
  }
  if (
    (sourceId === SEARCH_SOURCES.OPENALEX || sourceId === SEARCH_SOURCES.ALL) &&
    entityType === ENTITY_TYPES.AUTHORS &&
    topicId
  ) {
    params.topic_id = topicId;
  }

  if (
    entityType === ENTITY_TYPES.AUTHORS &&
    Array.isArray(knownAuthorIds) &&
    knownAuthorIds.length > 0
  ) {
    params.known_author_ids = knownAuthorIds.filter(Boolean).join(",");
  }

  if (
    (entityType === ENTITY_TYPES.WORKS || entityType === ENTITY_TYPES.GRANTS) &&
    searchSessionId
  ) {
    params.search_session_id = searchSessionId;
  }

  const started = performance.now();
  const response = await apiClient.get("/search", {
    params,
    timeout: 30000,
    signal,
  });
  console.info("[search-timing] unified_search_done", {
    ms: Math.round(performance.now() - started),
    source: sourceId,
    entityType,
    query: cleanedQuery,
    resultCount: Array.isArray(response.data?.results) ? response.data.results.length : 0,
  });

  const data = response.data || {};
  const results = Array.isArray(data.results) ? data.results.slice(0, 20) : [];

  return {
    query: data.query || cleanedQuery,
    entity_type: data.entity_type || entityType,
    source: data.source || sourceId,
    results,
    items: Array.isArray(data.items) ? data.items : [],
    updates: Array.isArray(data.updates) ? data.updates : [],
    pagination: data.pagination || null,
    next_cursor: data.next_cursor ?? data.pagination?.next_cursor ?? null,
    has_more: Boolean(data.has_more ?? data.pagination?.has_more),
    search_session_id: data.search_session_id || null,
  };
}

export async function searchInstitutions(query, { signal, limit = 10 } = {}) {
  const cleanedQuery = String(query || "").trim().replace(/\s+/g, " ");
  if (cleanedQuery.length < 2) {
    return [];
  }

  const response = await apiClient.get("/search/filters/institutions", {
    params: { query: cleanedQuery, limit },
    timeout: 15000,
    signal,
  });

  return Array.isArray(response.data) ? response.data.slice(0, 10) : [];
}

export async function searchTopics(query, { signal, limit = 10 } = {}) {
  const cleanedQuery = String(query || "").trim().replace(/\s+/g, " ");
  if (cleanedQuery.length < 2) {
    return [];
  }

  const response = await apiClient.get("/search/filters/topics", {
    params: { query: cleanedQuery, limit },
    timeout: 15000,
    signal,
  });

  return Array.isArray(response.data) ? response.data.slice(0, 10) : [];
}
