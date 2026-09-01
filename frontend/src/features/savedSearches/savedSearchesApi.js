import apiClient from "../../api/client";

export const SAVED_SEARCH_TYPES = {
  AUTHORS: "authors",
  GRANT: "grant",
};

export const SAVED_SEARCH_SORT_OPTIONS = [
  { value: "last_viewed_at", label: "Last viewed", defaultDirection: "desc" },
  { value: "created_at", label: "Recently saved", defaultDirection: "desc" },
  { value: "updated_at", label: "Recently updated", defaultDirection: "desc" },
  { value: "display_name", label: "Name", defaultDirection: "asc" },
  { value: "view_count", label: "Most viewed", defaultDirection: "desc" },
];

export async function fetchSavedSearches({
  type = SAVED_SEARCH_TYPES.AUTHORS,
  sortBy = "last_viewed_at",
  sortDirection = "desc",
  signal,
} = {}) {
  const response = await apiClient.get("/saved-searches", {
    params: {
      type,
      sort_by: sortBy,
      sort_direction: sortDirection,
    },
    signal,
  });
  const data = response.data || {};
  return Array.isArray(data.items) ? data.items : [];
}

export async function saveSavedSearch(payload) {
  const response = await apiClient.post("/saved-searches", payload);
  return response.data || {};
}

export async function markSavedSearchViewed(id) {
  const response = await apiClient.post(`/saved-searches/${encodeURIComponent(id)}/view`);
  return response.data || {};
}

export async function deleteSavedSearch(id) {
  await apiClient.delete(`/saved-searches/${encodeURIComponent(id)}`);
}
