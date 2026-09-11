import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  LinearProgress,
  Stack,
  Typography,
} from "@mui/material";
import CancelRoundedIcon from "@mui/icons-material/CancelRounded";
import PauseRoundedIcon from "@mui/icons-material/PauseRounded";
import PlayArrowRoundedIcon from "@mui/icons-material/PlayArrowRounded";
import RefreshRoundedIcon from "@mui/icons-material/RefreshRounded";

import { analysisPageLayoutSx } from "../../layout/pageLayout";
import {
  cancelDataUpdateJob,
  fetchDataUpdateJob,
  pauseDataUpdateJob,
  resumeDataUpdateJob,
  startDataUpdate,
} from "./dataUpdaterApi";
import {
  clearStoredDataUpdateJobId,
  currentStoredDataUpdateJobId,
  rememberDataUpdateJob,
} from "./dataUpdaterJobStorage";

const ACTIVE_STATUSES = new Set(["queued", "running", "pause_requested", "cancel_requested"]);
const TERMINAL_STATUSES = new Set([
  "succeeded",
  "completed_with_errors",
  "failed",
  "cancelled",
]);
const BUSY_STATUSES = new Set([
  "queued",
  "running",
  "pause_requested",
  "cancel_requested",
  "paused",
]);

const STATUS_LABELS = {
  queued: "Running",
  running: "Running",
  pause_requested: "Running",
  cancel_requested: "Running",
  paused: "Paused",
  cancelled: "Cancelled",
  succeeded: "Completed",
  completed_with_errors: "Completed",
  failed: "Failed",
};

/** Explicit update scopes wired to existing POST /data-updater/refresh jobs. */
export const UPDATE_ACTIONS = [
  {
    id: "authors",
    label: "Update Author Data",
    description: "Refresh author names, ORCID, topics, and profile details.",
    request: { mode: "dataset", dataset: "authors", stale_only: true },
  },
  {
    id: "publications",
    label: "Update Publication Data",
    description: "Refresh titles, venues, DOIs, and publication records.",
    request: { mode: "dataset", dataset: "publications", stale_only: true },
  },
  {
    id: "grants",
    label: "Update Grant Data",
    description: "Refresh funding awards and grant links on publications.",
    request: { mode: "dataset", dataset: "grant_funding", stale_only: true },
  },
  {
    id: "journals",
    label: "Update Journal Metrics",
    description: "Refresh journal and venue details stored on publications.",
    // Closest existing dataset: OpenAlex publication/source metadata (no separate journal-metrics job).
    request: { mode: "dataset", dataset: "publication_metadata", stale_only: true },
  },
  {
    id: "everything",
    label: "Update Everything",
    description: "Refresh all stale author, publication, grant, and cache data.",
    request: { mode: "all_stale", stale_only: true },
    primary: true,
  },
];

const buttonSx = {
  textTransform: "none",
  "&.Mui-disabled": {
    opacity: 0.45,
  },
};

function progressPercent(job) {
  if (!job?.total_records) {
    return job?.status && TERMINAL_STATUSES.has(job.status) ? 100 : 0;
  }
  return Math.min(100, Math.round((job.processed_records / job.total_records) * 100));
}

function statusLabel(job) {
  if (!job?.status) {
    return "Idle";
  }
  return STATUS_LABELS[job.status] || job.status;
}

function formatDate(value) {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function updateTitle(job, actionLabel) {
  if (job?.metadata?.title) {
    return job.metadata.title;
  }
  if (actionLabel) {
    return actionLabel.replace(/^Update /, "Updating ");
  }
  if (!job) {
    return "";
  }
  if (job.mode === "all_stale") {
    return "Updating everything";
  }
  if (job.dataset === "authors") {
    return "Updating author data";
  }
  if (job.dataset === "publications") {
    return "Updating publication data";
  }
  if (job.dataset === "grant_funding") {
    return "Updating grant data";
  }
  if (job.dataset === "publication_metadata") {
    return "Updating journal metrics";
  }
  return "Updating research data";
}

function progressSummary(job, pct) {
  if (!job) {
    return "No update in progress";
  }
  const processed = job.processed_records ?? 0;
  const total = job.total_records ?? 0;
  if (!total) {
    return `${pct}%`;
  }
  return `${pct}% · ${processed} / ${total} items checked`;
}

function lastUpdatedLabel(job) {
  const stamp = formatDate(job?.completed_at || job?.updated_at || job?.started_at);
  return stamp ? `Last updated ${stamp}` : "Not updated yet";
}

export default function DataUpdaterPage() {
  const [job, setJob] = useState(null);
  const [activeActionLabel, setActiveActionLabel] = useState("");
  const [starting, setStarting] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const rememberedJobId = currentStoredDataUpdateJobId();
    if (!rememberedJobId) {
      return undefined;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const restoredJob = await fetchDataUpdateJob(rememberedJobId, {
          signal: controller.signal,
        });
        setJob(restoredJob);
        rememberDataUpdateJob(restoredJob);
      } catch (err) {
        if (err?.response?.status === 404) {
          clearStoredDataUpdateJobId();
        } else if (err?.name !== "CanceledError" && err?.code !== "ERR_CANCELED") {
          setError("Could not restore the current update status.");
        }
      }
    }, 0);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, []);

  useEffect(() => {
    if (!job?.id || !ACTIVE_STATUSES.has(job.status)) {
      return undefined;
    }
    const controller = new AbortController();
    let cancelled = false;

    const refreshJob = async () => {
      try {
        const nextJob = await fetchDataUpdateJob(job.id, {
          signal: controller.signal,
        });
        if (cancelled) {
          return;
        }
        setJob(nextJob);
        rememberDataUpdateJob(nextJob);

        if (nextJob.status === "cancel_requested") {
          const updatedAt = nextJob.updated_at ? Date.parse(nextJob.updated_at) : 0;
          const ageMs = Number.isFinite(updatedAt) ? Date.now() - updatedAt : 0;
          if (ageMs >= 8_000) {
            const finalized = await cancelDataUpdateJob(nextJob.id);
            if (!cancelled) {
              setJob(finalized);
              rememberDataUpdateJob(finalized);
            }
          }
        }
      } catch (err) {
        if (err?.name !== "CanceledError" && err?.code !== "ERR_CANCELED") {
          setError("Could not refresh update status.");
        }
      }
    };

    const timer = setInterval(refreshJob, 1200);
    refreshJob();
    return () => {
      cancelled = true;
      clearInterval(timer);
      controller.abort();
    };
  }, [job?.id, job?.status]);

  const startJob = async (action) => {
    if (starting || controlling || (job && BUSY_STATUSES.has(job.status))) {
      return;
    }
    setStarting(true);
    setError(null);
    setActiveActionLabel(action.label);
    try {
      const nextJob = await startDataUpdate(action.request);
      setJob(nextJob);
      rememberDataUpdateJob(nextJob);
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not start the update.");
    } finally {
      setStarting(false);
    }
  };

  const controlJob = async (action) => {
    if (!job?.id || controlling) {
      return;
    }
    setControlling(true);
    setError(null);
    try {
      const nextJob = await action(job.id);
      setJob(nextJob);
      rememberDataUpdateJob(nextJob);
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not update the job status.");
      try {
        const fresh = await fetchDataUpdateJob(job.id);
        setJob(fresh);
        rememberDataUpdateJob(fresh);
      } catch {
        // Keep the previous error message; status refresh is best-effort.
      }
    } finally {
      setControlling(false);
    }
  };

  const pct = progressPercent(job);
  const jobBusy = Boolean(job && BUSY_STATUSES.has(job.status));
  const startDisabled = starting || controlling || jobBusy;
  const status = job?.status || null;
  const canPause = status === "queued" || status === "running";
  const canResume = status === "paused";
  const canCancel = Boolean(status && !TERMINAL_STATUSES.has(status));
  const isActive = Boolean(job && ACTIVE_STATUSES.has(job.status));
  const displayStatus = statusLabel(job);

  return (
    <Box sx={{ ...analysisPageLayoutSx, maxWidth: 720 }}>
      <Typography variant="h4" component="h1" fontWeight={700} sx={{ mb: 0.5 }}>
        Data Updater
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        Choose what to refresh. Updates run in the background so you can pause or cancel anytime.
      </Typography>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      ) : null}

      <Stack spacing={2.5}>
        <Stack spacing={1.5} data-testid="data-update-actions">
          {UPDATE_ACTIONS.map((action) => (
            <Box key={action.id}>
              <Button
                startIcon={<RefreshRoundedIcon />}
                variant={action.primary ? "contained" : "outlined"}
                disableElevation={Boolean(action.primary)}
                onClick={() => startJob(action)}
                disabled={startDisabled}
                sx={buttonSx}
              >
                {action.label}
              </Button>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                {action.description}
              </Typography>
            </Box>
          ))}
        </Stack>

        <Box data-testid="data-update-progress">
          <Stack
            direction="row"
            spacing={1}
            alignItems="baseline"
            justifyContent="space-between"
            sx={{ mb: 1 }}
          >
            <Typography
              data-testid="data-update-status"
              variant="subtitle1"
              fontWeight={700}
            >
              {displayStatus}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {progressSummary(job, pct)}
            </Typography>
          </Stack>

          <LinearProgress
            variant={isActive && !job?.total_records ? "indeterminate" : "determinate"}
            value={pct}
            sx={{ height: 6, borderRadius: 1, mb: 1 }}
          />

          <Typography variant="body2" color="text.secondary" sx={{ mb: 0.75 }}>
            {job
              ? updateTitle(job, activeActionLabel)
              : "No update selected yet."}
            {job?.failed_count ? ` · ${job.failed_count} could not be updated` : ""}
          </Typography>
          <Typography
            variant="caption"
            color="text.secondary"
            data-testid="data-update-last-updated"
            sx={{ display: "block", mb: 1.5 }}
          >
            {lastUpdatedLabel(job)}
          </Typography>

          {job?.error && job.status === "failed" ? (
            <Alert severity="error" sx={{ mb: 1.5 }}>
              The update stopped before it finished.
            </Alert>
          ) : null}

          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            {canResume ? (
              <Button
                startIcon={<PlayArrowRoundedIcon />}
                variant="outlined"
                onClick={() => controlJob(resumeDataUpdateJob)}
                disabled={controlling}
                sx={buttonSx}
              >
                Resume
              </Button>
            ) : (
              <Button
                startIcon={<PauseRoundedIcon />}
                variant="outlined"
                onClick={() => controlJob(pauseDataUpdateJob)}
                disabled={controlling || !canPause}
                sx={buttonSx}
              >
                Pause
              </Button>
            )}
            <Button
              startIcon={<CancelRoundedIcon />}
              variant="outlined"
              onClick={() => controlJob(cancelDataUpdateJob)}
              disabled={controlling || !canCancel}
              sx={buttonSx}
            >
              Cancel
            </Button>
          </Stack>
        </Box>
      </Stack>
    </Box>
  );
}
