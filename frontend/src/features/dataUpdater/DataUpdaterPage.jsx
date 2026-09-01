import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Divider,
  LinearProgress,
  MenuItem,
  Stack,
  TextField,
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
  fetchDataUpdaterSavedSearches,
  pauseDataUpdateJob,
  resumeDataUpdateJob,
  searchDataUpdateTargets,
  startAllSavedSearchesDataUpdate,
  startDataUpdate,
  startEntityDataUpdate,
  startSavedSearchDataUpdate,
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

const DATASET_LABELS = {
  authors: "Authors",
  publications: "Publications",
};

function progressPercent(job) {
  if (!job?.total_records) {
    return job?.status && TERMINAL_STATUSES.has(job.status) ? 100 : 0;
  }
  return Math.min(100, Math.round((job.processed_records / job.total_records) * 100));
}

function formatDate(value) {
  if (!value) {
    return "Not updated yet";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Not updated yet";
  }
  return `Last updated: ${date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  })}`;
}

function updateTitle(job) {
  if (!job) {
    return "";
  }
  return job.metadata?.title || "Updating research data";
}

function groupedProgress(job) {
  const idsByDataset = job?.metadata?.record_ids_by_dataset;
  if (!idsByDataset || typeof idsByDataset !== "object") {
    return [];
  }
  const records = Array.isArray(job.records) ? job.records : [];
  return Object.entries(DATASET_LABELS)
    .map(([dataset, label]) => {
      const ids = Array.isArray(idsByDataset[dataset]) ? idsByDataset[dataset] : [];
      if (!ids.length) {
        return null;
      }
      const checked = records.filter((record) => record.dataset === dataset).length;
      return { dataset, label, checked, total: ids.length };
    })
    .filter(Boolean);
}

function technicalFailures(job) {
  const records = Array.isArray(job?.records) ? job.records : [];
  return records.filter((record) => record.status === "failed" && record.message);
}

export default function DataUpdaterPage() {
  const [savedSearches, setSavedSearches] = useState([]);
  const [selectedSavedSearch, setSelectedSavedSearch] = useState("");
  const [targetOptions, setTargetOptions] = useState([]);
  const [targetSearch, setTargetSearch] = useState("");
  const [selectedTarget, setSelectedTarget] = useState(null);
  const [job, setJob] = useState(null);
  const [loadingSavedSearches, setLoadingSavedSearches] = useState(false);
  const [loadingTargets, setLoadingTargets] = useState(false);
  const [starting, setStarting] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [error, setError] = useState(null);

  const selectedSavedSearchItem = useMemo(
    () => savedSearches.find((item) => item.id === selectedSavedSearch) || null,
    [savedSearches, selectedSavedSearch],
  );

  const loadSavedSearches = useCallback(async ({ signal } = {}) => {
    setLoadingSavedSearches(true);
    try {
      const items = await fetchDataUpdaterSavedSearches({ signal });
      setSavedSearches(items);
      setSelectedSavedSearch((current) => current || items[0]?.id || "");
    } catch (err) {
      if (err?.name !== "CanceledError" && err?.code !== "ERR_CANCELED") {
        setError("Could not load saved searches.");
      }
    } finally {
      setLoadingSavedSearches(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      loadSavedSearches({ signal: controller.signal });
    }, 0);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [loadSavedSearches]);

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
    if (targetSearch.trim().length < 2) {
      return undefined;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setLoadingTargets(true);
      try {
        const items = await searchDataUpdateTargets(targetSearch, {
          signal: controller.signal,
        });
        setTargetOptions(items);
      } catch (err) {
        if (err?.name !== "CanceledError" && err?.code !== "ERR_CANCELED") {
          setError("Could not search update targets.");
        }
      } finally {
        setLoadingTargets(false);
      }
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [targetSearch]);

  useEffect(() => {
    if (!job?.id || !ACTIVE_STATUSES.has(job.status)) {
      return undefined;
    }
    const controller = new AbortController();
    const timer = setInterval(async () => {
      try {
        const nextJob = await fetchDataUpdateJob(job.id, {
          signal: controller.signal,
        });
        setJob(nextJob);
        rememberDataUpdateJob(nextJob);
      } catch (err) {
        if (err?.name !== "CanceledError" && err?.code !== "ERR_CANCELED") {
          setError("Could not refresh update status.");
        }
      }
    }, 1200);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [job?.id, job?.status]);

  const startJob = async (action) => {
    setStarting(true);
    setError(null);
    try {
      const nextJob = await action();
      setJob(nextJob);
      rememberDataUpdateJob(nextJob);
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not start the update.");
    } finally {
      setStarting(false);
    }
  };

  const controlJob = async (action) => {
    if (!job?.id) {
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
    } finally {
      setControlling(false);
    }
  };

  const handleUpdateAll = () => {
    startJob(() =>
      startDataUpdate({
        mode: "all_stale",
        stale_only: true,
      }),
    );
  };

  const handleUpdateSavedSearch = () => {
    if (!selectedSavedSearch) {
      setError("Choose a saved search to update.");
      return;
    }
    startJob(() => startSavedSearchDataUpdate(selectedSavedSearch));
  };

  const handleUpdateAllSavedSearches = () => {
    startJob(() => startAllSavedSearchesDataUpdate());
  };

  const handleUpdateTarget = () => {
    if (!selectedTarget) {
      setError("Choose an author, publication, or institution to update.");
      return;
    }
    startJob(() =>
      startEntityDataUpdate({
        type: selectedTarget.type,
        id: selectedTarget.id,
        stale_only: false,
      }),
    );
  };

  const pct = progressPercent(job);
  const groups = groupedProgress(job);
  const failures = technicalFailures(job);
  const canControl = job?.id && !TERMINAL_STATUSES.has(job.status);
  const paused = job?.status === "paused";

  return (
    <Box sx={{ ...analysisPageLayoutSx, maxWidth: 980 }}>
      <Typography variant="h4" component="h1" fontWeight={700} sx={{ mb: 0.75 }}>
        Data Updater
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 3, lineHeight: 1.6 }}>
        Keep your research data current.
      </Typography>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      ) : null}

      <Stack spacing={3}>
        <Box>
          <Button
            startIcon={<RefreshRoundedIcon />}
            variant="contained"
            disableElevation
            onClick={handleUpdateAll}
            disabled={starting}
            sx={{ textTransform: "none" }}
          >
            Update All Data
          </Button>
        </Box>

        <Divider />

        <Box>
          <Typography variant="h6" component="h2" fontWeight={700} sx={{ mb: 1.25 }}>
            Update Saved Search
          </Typography>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.25} alignItems="stretch">
            <TextField
              select
              size="small"
              label="Saved Searches"
              value={selectedSavedSearch}
              onChange={(event) => setSelectedSavedSearch(event.target.value)}
              disabled={loadingSavedSearches || savedSearches.length === 0}
              sx={{ minWidth: { sm: 320 } }}
            >
              {savedSearches.map((item) => (
                <MenuItem key={item.id} value={item.id}>
                  {item.name}
                </MenuItem>
              ))}
            </TextField>
            <Button
              startIcon={<RefreshRoundedIcon />}
              variant="outlined"
              color="inherit"
              onClick={handleUpdateSavedSearch}
              disabled={starting || !selectedSavedSearch}
              sx={{ textTransform: "none" }}
            >
              Update This Saved Search
            </Button>
            <Button
              variant="text"
              color="inherit"
              onClick={handleUpdateAllSavedSearches}
              disabled={starting || savedSearches.length === 0}
              sx={{ textTransform: "none" }}
            >
              Update All Saved Searches
            </Button>
          </Stack>
          {selectedSavedSearchItem ? (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
              {formatDate(selectedSavedSearchItem.updated_at)}
            </Typography>
          ) : null}
        </Box>

        <Divider />

        <Box>
          <Typography variant="h6" component="h2" fontWeight={700} sx={{ mb: 1.25 }}>
            Update Specific Item
          </Typography>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.25} alignItems="stretch">
            <Autocomplete
              fullWidth
              size="small"
              options={targetOptions}
              value={selectedTarget}
              inputValue={targetSearch}
              loading={loadingTargets}
              onInputChange={(_event, value) => {
                setTargetSearch(value);
                if (value.trim().length < 2) {
                  setTargetOptions([]);
                }
              }}
              onChange={(_event, value) => setSelectedTarget(value)}
              getOptionLabel={(option) => option?.title || ""}
              isOptionEqualToValue={(option, value) =>
                option.id === value.id && option.type === value.type
              }
              noOptionsText={
                targetSearch.trim().length < 2
                  ? "Type to search"
                  : "No matching authors, publications, or institutions"
              }
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Search authors, publications, or institutions"
                />
              )}
              renderOption={(props, option) => (
                <Box component="li" {...props}>
                  <Box>
                    <Typography variant="body2" fontWeight={700}>
                      {option.title}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {option.subtitle} · {formatDate(option.last_updated)}
                    </Typography>
                  </Box>
                </Box>
              )}
            />
            <Button
              startIcon={<RefreshRoundedIcon />}
              variant="outlined"
              color="inherit"
              onClick={handleUpdateTarget}
              disabled={starting || !selectedTarget}
              sx={{ textTransform: "none", minWidth: 116 }}
            >
              Update
            </Button>
          </Stack>
        </Box>

        {job ? (
          <>
            <Divider />
            <Box data-testid="data-update-progress">
              <Typography variant="h6" component="h2" fontWeight={700} sx={{ mb: 0.5 }}>
                Current Update
              </Typography>
              <Typography fontWeight={700}>{updateTitle(job)}</Typography>
              <LinearProgress
                variant="determinate"
                value={pct}
                sx={{ height: 8, borderRadius: 999, my: 1.25, maxWidth: 520 }}
              />
              <Typography color="text.secondary" sx={{ mb: 1 }}>
                {pct}% · {job.processed_records} / {job.total_records} items checked
              </Typography>
              {groups.length ? (
                <Stack spacing={0.25} sx={{ mb: 1 }}>
                  {groups.map((group) => (
                    <Typography key={group.dataset} variant="body2" color="text.secondary">
                      {group.label}: {group.checked} / {group.total}
                    </Typography>
                  ))}
                </Stack>
              ) : null}
              <Typography variant="body2" color="text.secondary">
                Updated: {job.updated_count} · Unchanged: {job.unchanged_count} · Retrying:{" "}
                {job.retrying_count}
                {job.failed_count ? ` · ${job.failed_count} could not be updated` : ""}
              </Typography>
              {job.status === "paused" ? (
                <Alert severity="info" sx={{ mt: 1.5, maxWidth: 520 }}>
                  This update is paused.
                </Alert>
              ) : null}
              {job.error ? (
                <Alert severity="error" sx={{ mt: 1.5, maxWidth: 520 }}>
                  The update stopped before it finished.
                </Alert>
              ) : null}
              <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
                {paused ? (
                  <Button
                    startIcon={<PlayArrowRoundedIcon />}
                    variant="outlined"
                    color="inherit"
                    onClick={() => controlJob(resumeDataUpdateJob)}
                    disabled={controlling}
                    sx={{ textTransform: "none" }}
                  >
                    Resume
                  </Button>
                ) : (
                  <Button
                    startIcon={<PauseRoundedIcon />}
                    variant="outlined"
                    color="inherit"
                    onClick={() => controlJob(pauseDataUpdateJob)}
                    disabled={controlling || !canControl}
                    sx={{ textTransform: "none" }}
                  >
                    Pause
                  </Button>
                )}
                <Button
                  startIcon={<CancelRoundedIcon />}
                  variant="outlined"
                  color="inherit"
                  onClick={() => controlJob(cancelDataUpdateJob)}
                  disabled={controlling || !canControl}
                  sx={{ textTransform: "none" }}
                >
                  Cancel
                </Button>
              </Stack>
              {failures.length ? (
                <Box
                  component="details"
                  sx={{
                    mt: 1.5,
                    maxWidth: 720,
                    color: "text.secondary",
                    "& summary": { cursor: "pointer" },
                  }}
                >
                  <Typography component="summary" variant="body2">
                    Technical details
                  </Typography>
                  <Stack spacing={0.5} sx={{ mt: 1 }}>
                    {failures.slice(0, 6).map((record) => (
                      <Typography key={record.id} variant="caption">
                        {record.dataset}: {record.message}
                      </Typography>
                    ))}
                  </Stack>
                </Box>
              ) : null}
            </Box>
          </>
        ) : null}
      </Stack>
    </Box>
  );
}
