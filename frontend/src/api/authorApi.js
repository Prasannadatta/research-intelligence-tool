import apiClient from "./client";

/**
 * Search authors by query string.
 * Skips the network request when the trimmed query is shorter than 2 characters.
 */
export async function searchAuthors(query) {
  const cleanedQuery = query.trim();

  if (cleanedQuery.length < 2) {
    return [];
  }

  const response = await apiClient.get("/authors/search", {
    params: { query: cleanedQuery },
  });

  return response.data;
}
