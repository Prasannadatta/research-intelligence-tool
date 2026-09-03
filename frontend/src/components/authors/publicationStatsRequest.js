import {
  createAuthorPublicationStatsJob,
  getAuthorPublicationStatsJob,
} from "../../api/analysisApi";

export const PUBLICATION_STATS_JOB_POLL_MS = 1500;

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

export function formatPublicationStatsProgressMessage(progress) {
  const detail = progress?.detail || {};
  const processed = detail.publications_processed ?? detail.publicationsProcessed;
  const total = detail.publications_total ?? detail.publicationsTotal;
  const stage = String(progress?.stage || "Preparing")
    .replace(/[.…]+\s*$/, "")
    .trim();

  if (processed != null && total != null) {
    return `Building complete publication statistics — ${Number(processed).toLocaleString()} / ${Number(total).toLocaleString()}`;
  }
  if (stage.toLowerCase().includes("checking")) {
    return "Checking publication coverage…";
  }
  if (stage) {
    const percent = Number.isFinite(Number(progress?.percent))
      ? Math.round(Number(progress.percent))
      : null;
    return percent != null ? `${stage}… ${percent}%` : `${stage}…`;
  }
  return "Building complete publication statistics…";
}

export async function fetchAuthorPublicationCorpusStats({
  authors,
  filters,
  signal,
  onProgress,
} = {}) {
  const created = await createAuthorPublicationStatsJob({
    authors,
    filters,
    signal,
  });
  onProgress?.(created);
  if (created?.status === "completed") {
    return created.result || {};
  }
  if (created?.status === "failed") {
    const error = new Error(
      created?.error_message ||
        created?.errorMessage ||
        "Unable to build complete publication statistics.",
    );
    error.statsJob = created;
    throw error;
  }

  const jobId = created?.job_id || created?.jobId;
  if (!jobId) {
    throw new Error("Publication statistics job did not return a job id.");
  }

  while (true) {
    if (signal?.aborted) {
      throw abortError();
    }
    const job = await getAuthorPublicationStatsJob(jobId, { signal });
    onProgress?.(job);
    if (job?.status === "completed") {
      return job.result || {};
    }
    if (job?.status === "failed") {
      const error = new Error(
        job?.error_message ||
          job?.errorMessage ||
          "Unable to build complete publication statistics.",
      );
      error.statsJob = job;
      throw error;
    }
    await delay(PUBLICATION_STATS_JOB_POLL_MS, signal);
  }
}
