import apiClient from "../../api/client";

export async function fetchDataUpdaterCategories({ signal } = {}) {
  const response = await apiClient.get("/data-updater/categories", { signal });
  const data = response.data || {};
  return Array.isArray(data.items) ? data.items : [];
}

export async function startDataUpdate(payload) {
  const response = await apiClient.post("/data-updater/refresh", payload);
  return response.data || {};
}

export async function searchDataUpdateTargets(query, { signal } = {}) {
  const response = await apiClient.get("/data-updater/search", {
    params: { q: query },
    signal,
  });
  const data = response.data || {};
  return Array.isArray(data.items) ? data.items : [];
}

export async function fetchDataUpdaterSavedSearches({ signal } = {}) {
  const response = await apiClient.get("/data-updater/saved-searches", { signal });
  const data = response.data || {};
  return Array.isArray(data.items) ? data.items : [];
}

export async function startEntityDataUpdate(payload) {
  const response = await apiClient.post("/data-updater/refresh/entity", payload);
  return response.data || {};
}

export async function startSavedSearchDataUpdate(savedSearchId) {
  const response = await apiClient.post("/data-updater/refresh/saved-search", {
    saved_search_id: savedSearchId,
    stale_only: true,
  });
  return response.data || {};
}

export async function startAllSavedSearchesDataUpdate() {
  const response = await apiClient.post("/data-updater/refresh/saved-searches");
  return response.data || {};
}

export async function fetchDataUpdateJob(id, { signal } = {}) {
  const response = await apiClient.get(`/data-updater/jobs/${encodeURIComponent(id)}`, {
    signal,
  });
  return response.data || {};
}

export async function pauseDataUpdateJob(id) {
  const response = await apiClient.post(`/data-updater/jobs/${encodeURIComponent(id)}/pause`);
  return response.data || {};
}

export async function resumeDataUpdateJob(id) {
  const response = await apiClient.post(`/data-updater/jobs/${encodeURIComponent(id)}/resume`);
  return response.data || {};
}

export async function cancelDataUpdateJob(id) {
  const response = await apiClient.post(`/data-updater/jobs/${encodeURIComponent(id)}/cancel`);
  return response.data || {};
}
