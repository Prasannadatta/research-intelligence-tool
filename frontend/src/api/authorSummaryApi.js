import apiClient from "./client";

/**
 * GET /api/authors/{canonical_author_id}/summary
 * Local-first: returns cached DB profile without blocking on ORCID/Scopus.
 */
export async function fetchAuthorSummaryByCanonicalId(canonicalAuthorId, { signal } = {}) {
  const response = await apiClient.get(`/authors/${encodeURIComponent(canonicalAuthorId)}/summary`, {
    signal,
    timeout: 20000,
  });
  return response.data;
}

/**
 * GET /api/authors/by-provider/openalex/{openalex_id}/summary
 */
export async function fetchAuthorSummaryByOpenAlexId(openalexId, { signal } = {}) {
  const response = await apiClient.get(
    `/authors/by-provider/openalex/${encodeURIComponent(openalexId)}/summary`,
    { signal, timeout: 20000 },
  );
  return response.data;
}

/**
 * POST /api/authors/{canonical_author_id}/summary/enrich
 * Lazy ORCID/Scopus (+ stale OpenAlex) enrichment. Safe to call repeatedly.
 */
export async function enrichAuthorSummaryByCanonicalId(canonicalAuthorId, { signal } = {}) {
  const response = await apiClient.post(
    `/authors/${encodeURIComponent(canonicalAuthorId)}/summary/enrich`,
    null,
    { signal, timeout: 45000 },
  );
  return response.data;
}

/**
 * GET /api/authors/{canonical_author_id}/details
 * Local-first profile page payload (summary + stored grants/pubs).
 */
export async function fetchAuthorDetailsByCanonicalId(canonicalAuthorId, { signal } = {}) {
  const response = await apiClient.get(
    `/authors/${encodeURIComponent(canonicalAuthorId)}/details`,
    { signal, timeout: 20000 },
  );
  return response.data;
}
