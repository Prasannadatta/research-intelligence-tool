import {
  createAuthorInsightsJob,
  fetchAuthorInsightsPublications,
  getAuthorInsightsJob,
} from "../../api/analysisApi";
import { adaptAuthorInsightsResponse } from "./authorInsightsAdapter";

export const INSIGHTS_JOB_POLL_MS = 1500;

const insightRequestCache = new Map();
const drilldownRequestCache = new Map();

function abortError() {
  const error = new Error("Aborted");
  error.name = "CanceledError";
  error.code = "ERR_CANCELED";
  return error;
}

function delay(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError());
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(abortError());
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

function jobProgressSnapshot(job = {}) {
  const detail = job.progress_detail || job.progressDetail || null;
  return {
    jobId: job.job_id || job.jobId || null,
    status: job.status || "queued",
    stage: job.progress_stage || job.progressStage || "Preparing",
    percent: Number.isFinite(Number(job.progress_percent))
      ? Math.round(Number(job.progress_percent))
      : Number.isFinite(Number(job.progressPercent))
        ? Math.round(Number(job.progressPercent))
        : 0,
    detail,
  };
}

export function formatInsightsJobProgressMessage(progress) {
  const detail = progress?.detail || {};
  const phase = String(detail.phase || "").toLowerCase();
  const authorName = String(detail.author_name || detail.authorName || "").trim();
  const processed = detail.publications_processed ?? detail.publicationsProcessed;
  const total = detail.publications_total ?? detail.publicationsTotal;

  if (phase === "checking") {
    return "Checking publication coverage…";
  }

  if (authorName && processed != null && total != null) {
    const processedLabel = Number(processed).toLocaleString();
    const totalLabel = Number(total).toLocaleString();
    return `Syncing ${authorName} — ${processedLabel} / ${totalLabel} publications`;
  }

  if (authorName && processed != null) {
    return `Syncing ${authorName} — ${Number(processed).toLocaleString()} publications`;
  }

  if (authorName && String(progress?.stage || "").toLowerCase().includes("sync")) {
    return `Syncing ${authorName}…`;
  }

  const stage = String(progress?.stage || "Preparing")
    .replace(/[.…]+\s*$/, "")
    .trim() || "Preparing";
  const percent = Number.isFinite(Number(progress?.percent))
    ? Math.round(Number(progress.percent))
    : 0;
  return `${stage}… ${percent}%`;
}

function emitInsightsProgress(entry, job) {
  entry.progress = jobProgressSnapshot(job);
  entry.progressListeners.forEach((listener) => {
    listener(entry.progress);
  });
}

function insightsJobFailure(job) {
  const error = new Error(
    job?.error_message || job?.errorMessage || "Unable to load author insights.",
  );
  error.insightsJob = job;
  return error;
}

async function fetchAuthorInsightsViaJob({
  authors,
  filters,
  excludedWorkIds,
  signal,
  onProgress,
} = {}) {
  const created = await createAuthorInsightsJob({
    authors,
    filters,
    excludedWorkIds,
    signal,
  });
  onProgress?.(created);
  if (created?.status === "completed") {
    return created.result || {};
  }
  if (created?.status === "failed") {
    throw insightsJobFailure(created);
  }

  const jobId = created?.job_id || created?.jobId;
  if (!jobId) {
    throw new Error("Insights job did not return a job id.");
  }

  while (true) {
    if (signal?.aborted) {
      throw abortError();
    }
    const job = await getAuthorInsightsJob(jobId, { signal });
    onProgress?.(job);
    if (job?.status === "completed") {
      return job.result || {};
    }
    if (job?.status === "failed") {
      throw insightsJobFailure(job);
    }
    await delay(INSIGHTS_JOB_POLL_MS, signal);
  }
}

export function retainInsightsRequest(key, requestParams) {
  const existing = insightRequestCache.get(key);
  if (existing) {
    if (existing.cleanupTimer) {
      clearTimeout(existing.cleanupTimer);
      existing.cleanupTimer = null;
    }
    existing.subscribers += 1;
    return existing;
  }

  const controller = new AbortController();
  const entry = {
    controller,
    subscribers: 1,
    cleanupTimer: null,
    status: "pending",
    progress: jobProgressSnapshot({
      status: "queued",
      progress_stage: "Preparing",
      progress_percent: 0,
    }),
    progressListeners: new Set(),
    promise: null,
  };
  entry.promise = fetchAuthorInsightsViaJob({
    ...requestParams,
    signal: controller.signal,
    onProgress: (job) => emitInsightsProgress(entry, job),
  })
    .then((response) => {
      entry.status = "fulfilled";
      return adaptAuthorInsightsResponse(response);
    })
    .catch((error) => {
      entry.status = "rejected";
      insightRequestCache.delete(key);
      throw error;
    });
  insightRequestCache.set(key, entry);
  return entry;
}

export function subscribeInsightsJobProgress(entry, listener) {
  if (!entry || typeof listener !== "function") {
    return () => {};
  }
  entry.progressListeners.add(listener);
  if (entry.progress) {
    listener(entry.progress);
  }
  return () => {
    entry.progressListeners.delete(listener);
  };
}

export function releaseInsightsRequest(key, entry) {
  entry.subscribers -= 1;
  if (entry.subscribers > 0) {
    return;
  }

  entry.cleanupTimer = setTimeout(() => {
    if (entry.subscribers > 0) {
      return;
    }
    if (entry.status === "pending") {
      entry.controller.abort();
    }
    insightRequestCache.delete(key);
  }, 0);
}

export function resetInsightsRequest(key) {
  const entry = insightRequestCache.get(key);
  if (!entry) {
    return;
  }
  if (entry.status === "pending") {
    entry.controller.abort();
  }
  if (entry.cleanupTimer) {
    clearTimeout(entry.cleanupTimer);
  }
  insightRequestCache.delete(key);
}

export function clearAuthorInsightsRequestCacheForTests() {
  insightRequestCache.forEach((entry) => {
    if (entry.status === "pending") {
      entry.controller.abort();
    }
    if (entry.cleanupTimer) {
      clearTimeout(entry.cleanupTimer);
    }
  });
  insightRequestCache.clear();
  drilldownRequestCache.forEach((entry) => {
    if (entry.status === "pending") {
      entry.controller.abort();
    }
    if (entry.cleanupTimer) {
      clearTimeout(entry.cleanupTimer);
    }
  });
  drilldownRequestCache.clear();
}

export function retainInsightsDrilldownRequest(key, requestParams) {
  const existing = drilldownRequestCache.get(key);
  if (existing) {
    if (existing.cleanupTimer) {
      clearTimeout(existing.cleanupTimer);
      existing.cleanupTimer = null;
    }
    existing.subscribers += 1;
    return existing;
  }

  const controller = new AbortController();
  const entry = {
    controller,
    subscribers: 1,
    cleanupTimer: null,
    status: "pending",
    promise: fetchAuthorInsightsPublications({
      ...requestParams,
      signal: controller.signal,
    })
      .then((response) => {
        entry.status = "fulfilled";
        return response;
      })
      .catch((error) => {
        entry.status = "rejected";
        drilldownRequestCache.delete(key);
        throw error;
      }),
  };
  drilldownRequestCache.set(key, entry);
  return entry;
}

export function releaseInsightsDrilldownRequest(key, entry) {
  entry.subscribers -= 1;
  if (entry.subscribers > 0) {
    return;
  }

  entry.cleanupTimer = setTimeout(() => {
    if (entry.subscribers > 0) {
      return;
    }
    if (entry.status === "pending") {
      entry.controller.abort();
    }
    drilldownRequestCache.delete(key);
  }, 0);
}

export function resetInsightsDrilldownRequest(key) {
  const entry = drilldownRequestCache.get(key);
  if (!entry) {
    return;
  }
  if (entry.status === "pending") {
    entry.controller.abort();
  }
  if (entry.cleanupTimer) {
    clearTimeout(entry.cleanupTimer);
  }
  drilldownRequestCache.delete(key);
}
