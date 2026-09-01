export const CURRENT_DATA_UPDATE_JOB_STORAGE_KEY =
  "researchIntelligence.dataUpdater.currentJobId";

const TERMINAL_STATUSES = new Set([
  "succeeded",
  "completed_with_errors",
  "failed",
  "cancelled",
]);

export function currentStoredDataUpdateJobId() {
  try {
    return window.localStorage.getItem(CURRENT_DATA_UPDATE_JOB_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function clearStoredDataUpdateJobId() {
  try {
    window.localStorage.removeItem(CURRENT_DATA_UPDATE_JOB_STORAGE_KEY);
  } catch {
    // Storage can be unavailable in private/test environments.
  }
}

export function rememberDataUpdateJob(job) {
  if (!job?.id) {
    return;
  }
  if (TERMINAL_STATUSES.has(job.status)) {
    clearStoredDataUpdateJobId();
    return;
  }
  try {
    window.localStorage.setItem(CURRENT_DATA_UPDATE_JOB_STORAGE_KEY, job.id);
  } catch {
    // Progress still works on the current page even if storage is unavailable.
  }
}
