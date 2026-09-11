import apiClient from "./client";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const RESOLVE_CACHE_MAX = 100;
/** Session cache of resolved authors keyed by provider identity. */
const resolveCache = new Map();

function providerIdentityKey(item) {
  if (!item || typeof item !== "object") {
    return "";
  }
  if (item.openalex_id) {
    return `openalex:${item.openalex_id}`;
  }
  if (item.orcid) {
    return `orcid:${item.orcid}`;
  }
  const record = Array.isArray(item.source_records)
    ? item.source_records.find((row) => row?.provider && row?.provider_author_id)
    : null;
  if (record) {
    return `${record.provider}:${record.provider_author_id}`;
  }
  return "";
}

function rememberResolved(key, author) {
  if (!key || !author) {
    return author;
  }
  if (resolveCache.has(key)) {
    resolveCache.delete(key);
  }
  resolveCache.set(key, author);
  while (resolveCache.size > RESOLVE_CACHE_MAX) {
    const oldest = resolveCache.keys().next().value;
    resolveCache.delete(oldest);
  }
  return author;
}

/**
 * True when the search hit is already a canonical author identity.
 */
export function isResolvedAuthorSelection(item) {
  if (!item || typeof item !== "object") {
    return false;
  }
  const id = String(item.canonical_author_id || item.id || item.result_id || "").trim();
  return UUID_RE.test(id);
}

/**
 * arXiv author-name aggregates are experimental, not authoritative identities.
 */
export function shouldResolveAuthorOnSelect(item) {
  if (!item || typeof item !== "object") {
    return false;
  }
  if (isResolvedAuthorSelection(item)) {
    return false;
  }
  if (item.result_type === "author_name" || item.source === "arxiv") {
    return false;
  }
  return Boolean(
    item.openalex_id ||
      item.source === "openalex" ||
      item.source === "orcid" ||
      item.orcid,
  );
}

/**
 * Resolve a selected author search hit into a canonical identity record.
 * Called on selection only — not during typeahead.
 * Reuses an in-session cache for previously resolved provider identities.
 */
export async function resolveAuthorSelection(author, { signal } = {}) {
  if (!shouldResolveAuthorOnSelect(author)) {
    return author;
  }
  const cacheKey = providerIdentityKey(author);
  if (cacheKey && resolveCache.has(cacheKey)) {
    return resolveCache.get(cacheKey);
  }
  const response = await apiClient.post(
    "/authors/resolve",
    { authors: [author] },
    { signal, timeout: 20000 },
  );
  const results = Array.isArray(response.data?.results) ? response.data.results : [];
  const resolved = results[0] || author;
  return rememberResolved(cacheKey, resolved);
}
