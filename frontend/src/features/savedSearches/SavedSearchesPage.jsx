import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  Select,
  Skeleton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from "@mui/material";

import { buildGrantPublicationsPath } from "../../api/grantsApi";
import { analysisPageLayoutSx } from "../../layout/pageLayout";
import { startSavedSearchDataUpdate } from "../dataUpdater/dataUpdaterApi";
import { rememberDataUpdateJob } from "../dataUpdater/dataUpdaterJobStorage";
import SavedSearchEditDialog from "./SavedSearchEditDialog";
import {
  authorEntries,
  formatAuthorsCompact,
  formatImportantFilters,
  formatSavedDate,
  matchesSavedSearchQuery,
} from "./savedSearchDisplay";
import {
  deleteSavedSearch,
  fetchSavedSearches,
  markSavedSearchViewed,
  patchSavedSearch,
  SAVED_SEARCH_SORT_OPTIONS,
  SAVED_SEARCH_TYPES,
} from "./savedSearchesApi";

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

const headCellSx = {
  fontWeight: 700,
  fontSize: "0.8125rem",
  letterSpacing: "0.01em",
  color: "text.secondary",
  py: 1.25,
  whiteSpace: "nowrap",
  borderBottomWidth: 1,
};

const bodyCellSx = {
  py: 1.15,
  verticalAlign: "middle",
};

const ellipsisSx = {
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
  display: "block",
  maxWidth: "100%",
};

function TruncatedText({ text, sx }) {
  const value = text == null || text === "" ? "—" : String(text);
  return (
    <Tooltip title={value} enterDelay={400} describeChild>
      <Box component="span" sx={{ ...ellipsisSx, ...sx }}>
        {value}
      </Box>
    </Tooltip>
  );
}

function authorLine(authors) {
  const names = (Array.isArray(authors) ? authors : [])
    .map((author) => String(author?.display_name || "").trim())
    .filter(Boolean);
  return {
    compact: formatAuthorsCompact(authors, { visible: 3 }),
    full: names.length > 0 ? names.join(", ") : "—",
  };
}

function SavedSearchesPage() {
  const navigate = useNavigate();
  const [searchType, setSearchType] = useState(SAVED_SEARCH_TYPES.AUTHORS);
  const [sortBy, setSortBy] = useState("updated_at");
  const [sortDirection, setSortDirection] = useState("desc");
  const [query, setQuery] = useState("");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [renameTarget, setRenameTarget] = useState(null);
  const [renameValue, setRenameValue] = useState("");
  const [editTarget, setEditTarget] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [updatingSearchId, setUpdatingSearchId] = useState(null);

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

  const filteredItems = useMemo(
    () => items.filter((item) => matchesSavedSearchQuery(item, query)),
    [items, query],
  );

  const handleTypeChange = (_event, nextType) => {
    if (nextType) {
      setSearchType(nextType);
      setQuery("");
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
    setActionError(null);
    try {
      await deleteSavedSearch(deleteTarget.id);
      setItems((current) => current.filter((item) => item.id !== deleteTarget.id));
      setStatus({ severity: "success", message: "Deleted" });
      setDeleteTarget(null);
    } catch (err) {
      setActionError(err?.response?.data?.detail || "Could not delete saved search.");
    }
  };

  const handleRenameConfirmed = async () => {
    if (!renameTarget) {
      return;
    }
    setActionError(null);
    try {
      const updated = await patchSavedSearch(renameTarget.id, {
        display_name: renameValue.trim(),
      });
      setItems((current) =>
        current.map((item) => (item.id === updated.id ? { ...item, ...updated } : item)),
      );
      setStatus({ severity: "success", message: "Renamed" });
      setRenameTarget(null);
    } catch (err) {
      setActionError(err?.response?.data?.detail || "Could not rename saved search.");
    }
  };

  const handleUpdateData = async (item) => {
    setUpdatingSearchId(item.id);
    setStatus(null);
    setError(null);
    try {
      const job = await startSavedSearchDataUpdate(item.id);
      rememberDataUpdateJob(job);
      setStatus({
        severity: "success",
        message: `Updating data for "${item.display_name}".`,
        showProgressLink: true,
      });
    } catch (err) {
      setStatus({
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
    <Box sx={{ ...analysisPageLayoutSx, minWidth: 0, overflowX: "hidden" }}>
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
          mb: 1.5,
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
            },
          }}
        >
          <ToggleButton value={SAVED_SEARCH_TYPES.AUTHORS}>Authors</ToggleButton>
          <ToggleButton value={SAVED_SEARCH_TYPES.GRANT}>Grants</ToggleButton>
        </ToggleButtonGroup>

        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={1}
          sx={{
            alignItems: { xs: "stretch", sm: "center" },
            width: { xs: "100%", sm: "auto" },
            ml: { sm: "auto" },
          }}
        >
          <TextField
            size="small"
            label="Search"
            placeholder="Name or author"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            sx={{ width: { xs: "100%", sm: 260 } }}
            inputProps={{ "aria-label": "Search saved searches" }}
          />
          <FormControl size="small" sx={{ minWidth: { xs: "100%", sm: 140 } }}>
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
            sx={{ textTransform: "none", minWidth: 104, alignSelf: { xs: "stretch", sm: "center" } }}
          >
            {sortDirection === "desc" ? "Newest first" : "Oldest first"}
          </Button>
        </Stack>
      </Box>

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

      {status ? (
        <Alert
          severity={status.severity}
          sx={{ mb: 2 }}
          onClose={() => setStatus(null)}
          action={
            status.showProgressLink ? (
              <Button color="inherit" size="small" onClick={() => navigate("/data-updater")}>
                View progress
              </Button>
            ) : null
          }
        >
          {status.message}
        </Alert>
      ) : null}

      {loading ? (
        <Stack spacing={1} data-testid="saved-searches-loading">
          {[0, 1, 2].map((index) => (
            <Skeleton key={index} variant="rounded" height={44} />
          ))}
        </Stack>
      ) : null}

      {!loading && !error && items.length === 0 ? (
        <Box
          sx={{
            border: "1px solid",
            borderColor: "divider",
            borderRadius: 1,
            p: 2,
          }}
        >
          <Typography fontWeight={600}>{emptyCopy}</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Save a search from Analyze Authors or Grant Publications to review it later.
          </Typography>
        </Box>
      ) : null}

      {!loading && !error && items.length > 0 && filteredItems.length === 0 ? (
        <Typography color="text.secondary" sx={{ mb: 2 }}>
          No saved searches match “{query.trim()}”.
        </Typography>
      ) : null}

      {!loading && !error && filteredItems.length > 0 ? (
        <TableContainer
          sx={{
            width: "100%",
            maxWidth: "100%",
            minWidth: 0,
            border: "1px solid",
            borderColor: "divider",
            borderRadius: 1,
            overflowX: "auto",
          }}
        >
          <Table
            size="small"
            aria-label="Saved searches"
            sx={{
              width: "100%",
              minWidth: 0,
              tableLayout: "fixed",
            }}
          >
            <TableHead>
              <TableRow>
                <TableCell sx={{ ...headCellSx, width: "22%" }}>Name</TableCell>
                <TableCell sx={{ ...headCellSx, width: "28%" }}>
                  {searchType === SAVED_SEARCH_TYPES.AUTHORS ? "Authors" : "Grant"}
                </TableCell>
                <TableCell sx={{ ...headCellSx, width: "16%" }}>Filters</TableCell>
                <TableCell sx={{ ...headCellSx, width: "9%" }}>Updated</TableCell>
                <TableCell
                  align="right"
                  sx={{ ...headCellSx, width: "25%", pr: 1.25 }}
                >
                  Actions
                </TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {filteredItems.map((item) => {
                const filters = item.applied_filters || item.payload?.filters || {};
                const authors = authorEntries(item);
                const authorText = authorLine(authors);
                const filterText = formatImportantFilters(filters, {
                  ...(item.provider_context || {}),
                  mode: item.payload?.analysis_mode || item.provider_context?.mode,
                });
                const grantLabel = item.payload?.grant_number || item.display_name;
                return (
                  <TableRow
                    key={item.id}
                    hover
                    data-testid="saved-search-row"
                    sx={{ height: 52 }}
                  >
                    <TableCell sx={{ ...bodyCellSx, maxWidth: 0 }}>
                      <TruncatedText text={item.display_name} sx={{ fontWeight: 600 }} />
                    </TableCell>
                    <TableCell sx={{ ...bodyCellSx, maxWidth: 0 }}>
                      {item.search_type === SAVED_SEARCH_TYPES.AUTHORS ? (
                        <Tooltip title={authorText.full} enterDelay={400} describeChild>
                          <Box component="span" sx={ellipsisSx}>
                            {authorText.compact}
                          </Box>
                        </Tooltip>
                      ) : (
                        <TruncatedText text={grantLabel} />
                      )}
                    </TableCell>
                    <TableCell sx={{ ...bodyCellSx, maxWidth: 0, color: "text.secondary" }}>
                      <TruncatedText text={filterText} />
                    </TableCell>
                    <TableCell sx={{ ...bodyCellSx, whiteSpace: "nowrap" }}>
                      {formatSavedDate(item.updated_at || item.created_at)}
                    </TableCell>
                    <TableCell align="right" sx={{ ...bodyCellSx, pr: 0.75 }}>
                      <Stack
                        direction="row"
                        spacing={0}
                        useFlexGap
                        justifyContent="flex-end"
                        flexWrap="wrap"
                        sx={{
                          display: "inline-flex",
                          maxWidth: "100%",
                          rowGap: 0.25,
                        }}
                      >
                        <Button
                          size="small"
                          onClick={() => handleOpen(item)}
                          sx={{ textTransform: "none", minWidth: 0, px: 0.75 }}
                        >
                          Open
                        </Button>
                        <Button
                          size="small"
                          onClick={() => setEditTarget(item)}
                          sx={{ textTransform: "none", minWidth: 0, px: 0.75 }}
                        >
                          Edit
                        </Button>
                        <Button
                          size="small"
                          onClick={() => {
                            setRenameTarget(item);
                            setRenameValue(item.display_name || "");
                            setActionError(null);
                          }}
                          sx={{ textTransform: "none", minWidth: 0, px: 0.75 }}
                        >
                          Rename
                        </Button>
                        <Button
                          size="small"
                          color="inherit"
                          onClick={() => handleUpdateData(item)}
                          disabled={updatingSearchId === item.id}
                          sx={{ textTransform: "none", minWidth: 0, px: 0.75 }}
                        >
                          {updatingSearchId === item.id ? "Updating..." : "Update data"}
                        </Button>
                        <Button
                          size="small"
                          color="error"
                          onClick={() => {
                            setDeleteTarget(item);
                            setActionError(null);
                          }}
                          sx={{ textTransform: "none", minWidth: 0, px: 0.75 }}
                        >
                          Delete
                        </Button>
                      </Stack>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      ) : null}

      <Dialog open={Boolean(deleteTarget)} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>Delete saved search?</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary">
            This removes only the saved search definition.
          </Typography>
          {actionError ? (
            <Alert severity="error" sx={{ mt: 2 }}>
              {actionError}
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

      <Dialog open={Boolean(renameTarget)} onClose={() => setRenameTarget(null)} fullWidth maxWidth="xs">
        <DialogTitle>Rename saved search</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            size="small"
            label="Name"
            value={renameValue}
            onChange={(event) => setRenameValue(event.target.value)}
            placeholder="Leave empty for an author-based label"
            sx={{ mt: 0.5 }}
          />
          {actionError ? (
            <Alert severity="error" sx={{ mt: 2 }}>
              {actionError}
            </Alert>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRenameTarget(null)} sx={{ textTransform: "none" }}>
            Cancel
          </Button>
          <Button onClick={handleRenameConfirmed} sx={{ textTransform: "none" }}>
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <SavedSearchEditDialog
        open={Boolean(editTarget)}
        item={editTarget}
        onClose={() => setEditTarget(null)}
        onSaved={(updated, message) => {
          setItems((current) =>
            current.map((item) => (item.id === updated.id ? { ...item, ...updated } : item)),
          );
          setStatus({ severity: "success", message: message || "Updated" });
        }}
      />
    </Box>
  );
}

export default SavedSearchesPage;
