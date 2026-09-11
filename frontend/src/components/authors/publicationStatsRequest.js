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
  if (detail.rate_limited || detail.rateLimited) {
    const provider = String(detail.provider || "OpenAlex");
    const label =
      provider.toLowerCase() === "openalex"
        ? "OpenAlex"
        : provider.toLowerCase() === "arxiv"
          ? "arXiv"
          : provider;
    return `${label} rate limit reached. Your existing data is safe; please try again shortly.`;
  }
  const processed = detail.publications_processed ?? detail.publicationsProcessed;
  const total = detail.publications_total ?? detail.publicationsTotal;
  const stage = String(progress?.stage || "Preparing")
    .replace(/[.…]+\s*$/, "")
    .trim();

  if (processed != null && total != null) {
    return `Syncing publications — ${Number(processed).toLocaleString()} / ${Number(total).toLocaleString()}`;
  }
  if (stage.toLowerCase().includes("checking")) {
    return "Checking publication coverage…";
  }
  if (stage.toLowerCase().includes("rate limit")) {
    return stage.endsWith(".") ? stage : `${stage}. Your existing data is safe; please try again shortly.`;
  }
  if (stage) {
    const percent = Number.isFinite(Number(progress?.percent))
      ? Math.round(Number(progress.percent))
      : null;
    return percent != null ? `${stage}… ${percent}%` : `${stage}…`;
  }
  return "Building complete publication statistics…";
}

export function formatPublicationStatsErrorMessage(error) {
  const job = error?.statsJob || {};
  const detail = job.progress_detail || job.progressDetail || {};
  if (detail.rate_limited || detail.rateLimited || /rate limit/i.test(String(error?.message || ""))) {
    const provider = String(detail.provider || "openalex");
    const label =
      provider.toLowerCase() === "openalex"
        ? "OpenAlex"
        : provider.toLowerCase() === "arxiv"
          ? "arXiv"
          : provider;
    return `${label} rate limit reached. Your existing data is safe; please try again shortly.`;
  }
  return (
    error?.message ||
    job.error_message ||
    job.errorMessage ||
    "Complete publication statistics are temporarily unavailable."
  );
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
    const result = created.result || {};
    if (result.corpus_complete === false) {
      const error = new Error(
        "Complete publication statistics are unavailable because coverage was not verified complete.",
      );
      error.statsJob = created;
      throw error;
    }
    return result;
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
      const result = job.result || {};
      if (result.corpus_complete === false) {
        const error = new Error(
          "Complete publication statistics are unavailable because coverage was not verified complete.",
        );
        error.statsJob = job;
        throw error;
      }
      return result;
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
