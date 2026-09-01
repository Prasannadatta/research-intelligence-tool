import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControl,
  InputLabel,
  Select,
  Skeleton,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";

import { buildGrantPublicationsPath } from "../../api/grantsApi";
import { startSavedSearchDataUpdate } from "../dataUpdater/dataUpdaterApi";
import { rememberDataUpdateJob } from "../dataUpdater/dataUpdaterJobStorage";
import { analysisPageLayoutSx } from "../../layout/pageLayout";
import SavedSearchRow from "./SavedSearchRow";
import {
  deleteSavedSearch,
  fetchSavedSearches,
  markSavedSearchViewed,
  SAVED_SEARCH_SORT_OPTIONS,
  SAVED_SEARCH_TYPES,
} from "./savedSearchesApi";

const SORT_DIRECTION_LABELS = {
  desc: "Newest first",
  asc: "Oldest first",
};

function activeAuthorsForPayload(payload) {
  const authors = Array.isArray(payload?.authors) ? payload.authors : [];
  const activeIds = Array.isArray(payload?.active_author_ids)
    ? new Set(payload.active_author_ids)
    : null;
  if (!activeIds) {
    return authors;
  }
  return authors.filter((author) => activeIds.has(author.canonical_author_id));
}

function SavedSearchesPage() {
  const navigate = useNavigate();
  const [searchType, setSearchType] = useState(SAVED_SEARCH_TYPES.AUTHORS);
  const [sortBy, setSortBy] = useState("last_viewed_at");
  const [sortDirection, setSortDirection] = useState("desc");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [updatingSearchId, setUpdatingSearchId] = useState(null);
  const [updateNotice, setUpdateNotice] = useState(null);

  const selectedSort = useMemo(
    () => SAVED_SEARCH_SORT_OPTIONS.find((option) => option.value === sortBy),
    [sortBy],
  );

  const loadItems = useCallback(
    async ({ signal } = {}) => {
      setLoading(true);
      setError(null);
      try {
        const nextItems = await fetchSavedSearches({
          type: searchType,
          sortBy,
          sortDirection,
          signal,
        });
        setItems(nextItems);
      } catch (err) {
        if (err?.name === "CanceledError" || err?.code === "ERR_CANCELED") {
          return;
        }
        setError(err?.response?.data?.detail || "Could not load saved searches.");
        setItems([]);
      } finally {
        setLoading(false);
      }
    },
    [searchType, sortBy, sortDirection],
  );

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      loadItems({ signal: controller.signal });
    }, 0);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [loadItems]);

  const handleTypeChange = (_event, nextType) => {
    if (nextType) {
      setSearchType(nextType);
    }
  };

  const handleSortChange = (event) => {
    const nextSort = event.target.value;
    const option = SAVED_SEARCH_SORT_OPTIONS.find((row) => row.value === nextSort);
    setSortBy(nextSort);
    setSortDirection(option?.defaultDirection || "desc");
  };

  const handleOpen = async (item) => {
    const viewed = await markSavedSearchViewed(item.id);
    const saved = viewed?.id ? viewed : item;
    const payload = saved.payload || {};
    const filters = payload.filters || saved.applied_filters || {};

    if (saved.search_type === SAVED_SEARCH_TYPES.AUTHORS) {
      const authors = Array.isArray(payload.authors) ? payload.authors : [];
      const activeAuthors = activeAuthorsForPayload(payload);
      navigate("/analyze/authors", {
        state: {
          originalAuthors: authors,
          authors,
          activeAuthors,
          excludedWorkIds: payload.excluded_work_ids || saved.excluded_work_ids || [],
          filters,
        },
      });
      return;
    }

    const path = buildGrantPublicationsPath(payload.grant_number, payload.provider);
    if (path) {
      navigate(path, {
        state: {
          filters,
          providerContext: saved.provider_context || {},
        },
      });
    }
  };

  const handleDeleteConfirmed = async () => {
    if (!deleteTarget) {
      return;
    }
    setDeleteError(null);
    try {
      await deleteSavedSearch(deleteTarget.id);
      setItems((current) => current.filter((item) => item.id !== deleteTarget.id));
      setDeleteTarget(null);
    } catch (err) {
      setDeleteError(err?.response?.data?.detail || "Could not delete saved search.");
    }
  };

  const handleUpdateData = async (item) => {
    setUpdatingSearchId(item.id);
    setUpdateNotice(null);
    setError(null);
    try {
      const job = await startSavedSearchDataUpdate(item.id);
      rememberDataUpdateJob(job);
      setUpdateNotice({
        severity: "success",
        message: `Updating data for "${item.display_name}".`,
      });
    } catch (err) {
      setUpdateNotice({
        severity: "error",
        message: err?.response?.data?.detail || "Could not start data update.",
      });
    } finally {
      setUpdatingSearchId(null);
    }
  };

  const emptyCopy =
    searchType === SAVED_SEARCH_TYPES.AUTHORS
      ? "No saved author searches yet."
      : "No saved grant searches yet.";

  return (
    <Box sx={analysisPageLayoutSx}>
      <Typography variant="h4" component="h1" fontWeight={700} sx={{ mb: 2 }}>
        Saved Searches
      </Typography>

      <Box
        sx={{
          display: "flex",
          alignItems: { xs: "stretch", sm: "center" },
          justifyContent: "space-between",
          flexDirection: { xs: "column", sm: "row" },
          gap: 1.5,
          mb: 2,
        }}
      >
        <ToggleButtonGroup
          size="small"
          exclusive
          value={searchType}
          onChange={handleTypeChange}
          aria-label="Saved search type"
          sx={{
            "& .MuiToggleButton-root": {
              px: 2,
              py: 0.6,
              textTransform: "none",
              borderRadius: "999px",
            },
          }}
        >
          <ToggleButton value={SAVED_SEARCH_TYPES.AUTHORS}>Authors</ToggleButton>
          <ToggleButton value={SAVED_SEARCH_TYPES.GRANT}>Grants</ToggleButton>
        </ToggleButtonGroup>

        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
          <FormControl size="small" sx={{ minWidth: 170 }}>
            <InputLabel id="saved-search-sort-label">Sort</InputLabel>
            <Select
              native
              labelId="saved-search-sort-label"
              label="Sort"
              value={sortBy}
              onChange={handleSortChange}
              inputProps={{ "aria-label": "Sort" }}
            >
              {SAVED_SEARCH_SORT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </FormControl>
          <Button
            size="small"
            variant="outlined"
            color="inherit"
            onClick={() => setSortDirection((current) => (current === "desc" ? "asc" : "desc"))}
            sx={{ textTransform: "none", minWidth: 104 }}
          >
            {SORT_DIRECTION_LABELS[sortDirection]}
          </Button>
        </Stack>
      </Box>

      {selectedSort ? (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          {selectedSort.label} - {sortDirection === "desc" ? "descending" : "ascending"}
        </Typography>
      ) : null}

      {error ? (
        <Alert
          severity="error"
          action={
            <Button color="inherit" size="small" onClick={() => loadItems()}>
              Retry
            </Button>
          }
          sx={{ mb: 2 }}
        >
          {error}
        </Alert>
      ) : null}

      {updateNotice ? (
        <Alert
          severity={updateNotice.severity}
          sx={{ mb: 2 }}
          onClose={() => setUpdateNotice(null)}
          action={
            updateNotice.severity === "success" ? (
              <Button color="inherit" size="small" onClick={() => navigate("/data-updater")}>
                View progress
              </Button>
            ) : null
          }
        >
          {updateNotice.message}
        </Alert>
      ) : null}

      {loading ? (
        <Stack spacing={1.25} data-testid="saved-searches-loading">
          {[0, 1, 2].map((index) => (
            <Skeleton key={index} variant="rounded" height={92} />
          ))}
        </Stack>
      ) : null}

      {!loading && !error && items.length === 0 ? (
        <Box
          sx={{
            border: "1px solid",
            borderColor: "divider",
            borderRadius: "8px",
            p: 2,
          }}
        >
          <Typography fontWeight={600}>{emptyCopy}</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Save a search from an Author Analysis or Grant Publications page to review it later.
          </Typography>
        </Box>
      ) : null}

      {!loading && !error && items.length > 0 ? (
        <Stack spacing={1.25}>
          {items.map((item) => (
            <SavedSearchRow
              key={item.id}
              item={item}
              onOpen={handleOpen}
              onDelete={setDeleteTarget}
              onUpdateData={handleUpdateData}
              updatingData={updatingSearchId === item.id}
            />
          ))}
        </Stack>
      ) : null}

      <Dialog open={Boolean(deleteTarget)} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>Delete saved search?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            This removes only the saved search definition.
          </DialogContentText>
          {deleteError ? (
            <Alert severity="error" sx={{ mt: 2 }}>
              {deleteError}
            </Alert>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)} sx={{ textTransform: "none" }}>
            Cancel
          </Button>
          <Button color="error" onClick={handleDeleteConfirmed} sx={{ textTransform: "none" }}>
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default SavedSearchesPage;
