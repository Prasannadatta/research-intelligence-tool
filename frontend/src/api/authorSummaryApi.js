import apiClient from "./client";

/**
 * GET /api/authors/{canonical_author_id}/summary
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
