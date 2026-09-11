import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Stack,
  TextField,
  Typography,
} from "@mui/material";

import AuthorSearch from "../../components/authors/AuthorSearch";
import { ENTITY_TYPES } from "../../api/searchApi";
import { filtersFromSavedPayload } from "./savedSearchDisplay";
import {
  appendUniqueSavedSearchAuthor,
  removeSavedSearchAuthor,
  savedSearchAuthorFromSearchHit,
} from "./savedSearchAuthorEdit";
import { patchSavedSearch, SAVED_SEARCH_TYPES } from "./savedSearchesApi";

function SectionLabel({ children }) {
  return (
    <Typography
      variant="subtitle2"
      sx={{ fontWeight: 700, letterSpacing: "0.01em", mb: 1 }}
    >
      {children}
    </Typography>
  );
}

export default function SavedSearchEditDialog({
  open,
  item,
  onClose,
  onSaved,
}) {
  const isAuthors = item?.search_type === SAVED_SEARCH_TYPES.AUTHORS;
  const [displayName, setDisplayName] = useState("");
  const [authors, setAuthors] = useState([]);
  const [filters, setFilters] = useState(filtersFromSavedPayload());
  const [addingAuthor, setAddingAuthor] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [searchKey, setSearchKey] = useState(0);

  useEffect(() => {
    if (!open || !item) {
      return;
    }
    setDisplayName(item.display_name || "");
    setAuthors(
      Array.isArray(item.payload?.authors)
        ? item.payload.authors.map((author) => ({ ...author }))
        : [],
    );
    setFilters(filtersFromSavedPayload(item.applied_filters || item.payload?.filters));
    setError(null);
    setSaving(false);
    setAddingAuthor(false);
    setSearchKey((value) => value + 1);
  }, [open, item]);

  const canSave = useMemo(() => {
    if (!isAuthors) {
      return true;
    }
    return authors.some((author) => author.canonical_author_id);
  }, [authors, isAuthors]);

  const handleAuthorSelected = async (hit) => {
    if (!hit || addingAuthor) {
      return;
    }
    setAddingAuthor(true);
    setError(null);
    try {
      const nextAuthor = await savedSearchAuthorFromSearchHit(hit);
      if (!nextAuthor) {
        setError("Could not add this author. Try another OpenAlex or ORCID result.");
        return;
      }
      setAuthors((current) => {
        const next = appendUniqueSavedSearchAuthor(current, nextAuthor);
        if (next === current) {
          return current;
        }
        return next;
      });
    } catch {
      setError("Could not add this author. Try again.");
    } finally {
      setAddingAuthor(false);
    }
  };

  const handleRemoveAuthor = (canonicalAuthorId) => {
    setAuthors((current) => removeSavedSearchAuthor(current, canonicalAuthorId));
    setError(null);
  };

  const handleSave = async () => {
    if (!item || saving || !canSave) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const patch = {
        display_name: displayName.trim(),
        filters: {
          from_year: filters.from_year || null,
          to_year: filters.to_year || null,
          sources: filters.sources || [],
          institutions: filters.institutions || [],
          venues: filters.venues || [],
          ...(isAuthors
            ? { grant_numbers: filters.grant_numbers || [] }
            : { authors: filters.authors || [] }),
        },
      };
      if (isAuthors) {
        patch.authors = authors.map((author) => ({
          canonical_author_id: author.canonical_author_id,
          display_name: author.display_name,
          provider: author.provider,
          provider_author_id: author.provider_author_id,
        }));
      }
      const updated = await patchSavedSearch(item.id, patch);
      onSaved?.(updated, "Updated");
      onClose?.();
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(
        typeof detail === "string"
          ? detail
          : "Could not update saved search.",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={saving ? undefined : onClose}
      fullWidth
      maxWidth="md"
      scroll="paper"
      slotProps={{
        paper: {
          sx: {
            width: { xs: "100%", sm: "min(920px, calc(100vw - 32px))" },
            height: { xs: "100%", sm: "min(880px, calc(100vh - 48px))" },
            maxHeight: { xs: "100%", sm: "calc(100vh - 48px)" },
            m: { xs: 0, sm: 2 },
            borderRadius: { xs: 0, sm: 2 },
            display: "flex",
            flexDirection: "column",
          },
        },
      }}
    >
      <DialogTitle sx={{ pb: 1.25 }}>Edit saved search</DialogTitle>
      <DialogContent
        dividers
        sx={{
          flex: 1,
          overflow: "auto",
          display: "flex",
          flexDirection: "column",
          gap: 2.5,
          py: 2,
        }}
      >
        <Box>
          <SectionLabel>Name</SectionLabel>
          <TextField
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            placeholder="Optional — leave empty for an author-based label"
            fullWidth
            size="small"
            inputProps={{ "aria-label": "Saved search name" }}
          />
        </Box>

        <Divider />

        {isAuthors ? (
          <Box>
            <SectionLabel>Authors</SectionLabel>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.25 }}>
              Search OpenAlex and ORCID with the same sources and deduplication as
              main Author Search. Selected authors are hidden from results.
            </Typography>

            <Box
              sx={{
                maxHeight: { xs: 140, sm: 180 },
                overflow: "auto",
                border: "1px solid",
                borderColor: "divider",
                borderRadius: 1.5,
                p: 1,
                mb: 1.5,
                bgcolor: "action.hover",
              }}
            >
              {authors.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ px: 0.5, py: 0.75 }}>
                  No authors selected.
                </Typography>
              ) : (
                <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
                  {authors.map((author) => (
                    <Chip
                      key={author.canonical_author_id}
                      label={author.display_name}
                      onDelete={
                        saving ? undefined : () => handleRemoveAuthor(author.canonical_author_id)
                      }
                      size="small"
                      sx={{ maxWidth: "100%" }}
                    />
                  ))}
                </Stack>
              )}
            </Box>

            <AuthorSearch
              key={searchKey}
              embedded
              entityType={ENTITY_TYPES.AUTHORS}
              selectedAuthors={authors}
              onResultSelected={handleAuthorSelected}
            />
            {addingAuthor ? (
              <Typography variant="caption" color="text.secondary" sx={{ mt: 0.75, display: "block" }}>
                Adding author…
              </Typography>
            ) : null}
          </Box>
        ) : (
          <Box>
            <SectionLabel>Grant</SectionLabel>
            <Typography variant="body2" color="text.secondary">
              {item?.payload?.grant_number || item?.display_name}
            </Typography>
          </Box>
        )}

        <Divider />

        <Box>
          <SectionLabel>Filters</SectionLabel>
          <Stack spacing={1.5}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1.25}>
              <TextField
                label="From year"
                size="small"
                value={filters.from_year ?? ""}
                onChange={(event) =>
                  setFilters((current) => ({
                    ...current,
                    from_year: event.target.value.replace(/\D/g, "").slice(0, 4),
                  }))
                }
                fullWidth
              />
              <TextField
                label="To year"
                size="small"
                value={filters.to_year ?? ""}
                onChange={(event) =>
                  setFilters((current) => ({
                    ...current,
                    to_year: event.target.value.replace(/\D/g, "").slice(0, 4),
                  }))
                }
                fullWidth
              />
            </Stack>

            <Autocomplete
              multiple
              freeSolo
              options={[]}
              value={filters.institutions || []}
              onChange={(_event, value) =>
                setFilters((current) => ({ ...current, institutions: value }))
              }
              renderInput={(params) => (
                <TextField {...params} size="small" label="Institutions" />
              )}
            />
            <Autocomplete
              multiple
              freeSolo
              options={[]}
              value={filters.venues || []}
              onChange={(_event, value) =>
                setFilters((current) => ({ ...current, venues: value }))
              }
              renderInput={(params) => (
                <TextField {...params} size="small" label="Venues" />
              )}
            />
            {isAuthors ? (
              <Autocomplete
                multiple
                freeSolo
                options={[]}
                value={filters.grant_numbers || []}
                onChange={(_event, value) =>
                  setFilters((current) => ({ ...current, grant_numbers: value }))
                }
                renderInput={(params) => (
                  <TextField {...params} size="small" label="Grant numbers" />
                )}
              />
            ) : null}
          </Stack>
        </Box>

        <Collapse in={Boolean(error)} unmountOnExit>
          <Alert severity="error" role="alert" sx={{ mt: 0.5 }}>
            {error}
          </Alert>
        </Collapse>
      </DialogContent>
      <DialogActions sx={{ px: 3, py: 1.75, gap: 1 }}>
        <Button onClick={onClose} disabled={saving} sx={{ textTransform: "none" }}>
          Cancel
        </Button>
        <Button
          variant="contained"
          disableElevation
          onClick={handleSave}
          disabled={saving || !canSave || addingAuthor}
          sx={{ textTransform: "none" }}
        >
          {saving ? "Saving..." : "Save changes"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
