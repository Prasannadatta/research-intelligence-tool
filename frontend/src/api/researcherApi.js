import apiClient from "./client";

/**
 * Normalize an autocomplete query for caching and request dedupe.
 */
export function normalizeAutocompleteQuery(query) {
  return query.trim().toLowerCase().replace(/\s+/g, " ");
}

/**
 * Lightweight OpenAlex autocomplete via the backend.
 * Never sends or stores OpenAlex API keys in the frontend.
 */
export async function autocompleteResearchers(query, { signal } = {}) {
  const cleanedQuery = query.trim().replace(/\s+/g, " ");

  if (cleanedQuery.length < 3) {
    return [];
  }

  const response = await apiClient.get("/researchers/autocomplete", {
    params: { query: cleanedQuery },
    timeout: 15000,
    signal,
  });

  const results = Array.isArray(response.data) ? response.data : [];
  return results.slice(0, 10);
}

/**
 * Fetch the full OpenAlex researcher record after selection.
 */
export async function getResearcherById(openalexId, { signal } = {}) {
  const cleanedId = String(openalexId || "").trim();
  if (!cleanedId) {
    throw new Error("Missing OpenAlex author ID.");
  }

  const response = await apiClient.get(`/researchers/${encodeURIComponent(cleanedId)}`, {
    timeout: 15000,
    signal,
  });

  return response.data;
}
