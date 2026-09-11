import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Autocomplete,
  Box,
  Button,
  Checkbox,
  Chip,
  Collapse,
  Stack,
  TextField,
  Typography,
} from "@mui/material";

import {
  searchAuthorPublicationGrants,
  searchAuthorPublicationVenues,
} from "../../api/analysisApi";
import { getAnalysisPalette } from "../../theme/analysisPalette";
import {
  PUBLICATION_FILTER_DEBOUNCE_MS,
  buildAppliedFilterChips,
  clonePublicationFilters,
  emptyPublicationFilters,
  publicationFiltersEqual,
  validatePublicationFilters,
} from "./publicationFilters";

const YEAR_FIELD_SX = {
  width: { xs: "calc(50% - 5px)", sm: 110 },
  minWidth: 0,
  maxWidth: { xs: "calc(50% - 5px)", sm: 120 },
  flex: { xs: "1 1 calc(50% - 5px)", sm: "0 1 110px" },
  position: "relative",
};

const MAX_VISIBLE_TAGS = 1;

export function formatCompleteCorpusFilterCaption(totalCount) {
  const total = Number(totalCount);
  if (!Number.isFinite(total) || total < 0) {
    return "Filter options and counts are from all matching publications.";
  }
  if (total === 0) {
    return "Filter options will appear once matching publications are available.";
  }
  return `Filter options and counts are from all ${total.toLocaleString("en-US")} publications.`;
}

const FILTER_WIDTHS = {
  source: { xs: "100%", sm: 232 },
  institution: { xs: "100%", sm: 340 },
  venue: { xs: "100%", sm: 340 },
  grant: { xs: "100%", sm: 320 },
  authors: { xs: "100%", sm: 320 },
};

const FILTER_FIELD_SX = {
  flex: { xs: "1 1 100%", sm: "1 1 240px", md: "1 1 280px" },
  minWidth: 0,
  maxWidth: "100%",
};

const FILTER_ACTIONS_SX = {
  flex: { xs: "1 1 100%", sm: "0 1 auto" },
  display: "flex",
  gap: 1,
  flexWrap: "wrap",
  alignItems: "center",
  justifyContent: { xs: "stretch", sm: "flex-start" },
  minWidth: 0,
  "& .MuiButton-root": {
    flex: { xs: "1 1 0", sm: "0 0 auto" },
    minWidth: { xs: 0, sm: "auto" },
    whiteSpace: "nowrap",
  },
};

const FILTER_AUTOCOMPLETE_SX = {
  "& .MuiAutocomplete-inputRoot": {
    flexWrap: "nowrap",
    alignItems: "center",
    overflow: "hidden",
    minHeight: 40,
    height: 40,
    py: "0 !important",
    boxSizing: "border-box",
  },
  "& .MuiAutocomplete-input": {
    minWidth: "48px !important",
    width: "0 !important",
    flexGrow: 1,
  },
  "& .MuiAutocomplete-tag": {
    maxWidth: "calc(100% - 52px)",
    margin: "0 2px 0 0",
  },
  "& .MuiChip-root": {
    height: 22,
    maxWidth: "100%",
  },
  "& .MuiChip-label": {
    overflow: "hidden",
    textOverflow: "ellipsis",
    px: 0.75,
  },
};

const LISTBOX_SLOT_PROPS = {
  sx: {
    py: 0.5,
    "& .MuiAutocomplete-option": {
      minHeight: 36,
      alignItems: "flex-start",
      py: 0.5,
      px: 1,
    },
  },
};

function isLookupContextReady(context) {
  if (!context || typeof context !== "object") {
    return false;
  }
  if (Array.isArray(context.authors)) {
    return context.authors.length > 0;
  }
  if (context.grantNumber != null) {
    return Boolean(String(context.grantNumber).trim());
  }
  return Object.keys(context).length > 0;
}

function useDebouncedFacetLookup(lookupFn, context) {
  const [inputValue, setInputValue] = useState("");
  const [options, setOptions] = useState([]);
  const [loading, setLoading] = useState(false);
  const requestIdRef = useRef(0);
  const abortRef = useRef(null);
  const contextReady = isLookupContextReady(context);

  useEffect(() => {
    const cleaned = inputValue.trim().replace(/\s+/g, " ");
    if (!contextReady || cleaned.length < 1) {
      requestIdRef.current += 1;
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
      /* eslint-disable react-hooks/set-state-in-effect -- Lookup state must clear immediately when context/input is no longer searchable. */
      setOptions([]);
      setLoading(false);
      /* eslint-enable react-hooks/set-state-in-effect */
      return undefined;
    }

    const requestId = ++requestIdRef.current;
    setLoading(true);
    const timeoutId = window.setTimeout(async () => {
      if (abortRef.current) {
        abortRef.current.abort();
      }
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const results = await lookupFn({
          ...context,
          query: cleaned,
          limit: 25,
          signal: controller.signal,
        });
        if (requestId !== requestIdRef.current) {
          return;
        }
        setOptions(Array.isArray(results) ? results : []);
      } catch (err) {
        if (
          requestId !== requestIdRef.current ||
          err?.code === "ERR_CANCELED" ||
          err?.name === "CanceledError" ||
          err?.name === "AbortError"
        ) {
          return;
        }
        setOptions([]);
      } finally {
        if (requestId === requestIdRef.current) {
          setLoading(false);
        }
      }
    }, PUBLICATION_FILTER_DEBOUNCE_MS);

    return () => window.clearTimeout(timeoutId);
  }, [context, contextReady, inputValue, lookupFn]);

  return {
    inputValue,
    setInputValue,
    options,
    loading,
    reset: () => {
      requestIdRef.current += 1;
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
      setInputValue("");
      setOptions([]);
      setLoading(false);
    },
  };
}

function publicationCountLabel(count) {
  if (count == null) {
    return null;
  }
  const n = Number(count);
  if (!Number.isFinite(n)) {
    return null;
  }
  return `${n} publication${n === 1 ? "" : "s"}`;
}

function mergeSelectedOptions(options, selected, getKey, buildUnavailable) {
  const rows = Array.isArray(options) ? [...options] : [];
  const seen = new Set(rows.map((row) => getKey(row)).filter(Boolean));
  for (const item of selected || []) {
    const key = getKey(item);
    if (!key || seen.has(key)) {
      continue;
    }
    seen.add(key);
    rows.push(buildUnavailable(item));
  }
  return rows;
}

function renderCheckboxOption(props, option, { selected }, { primary, secondary }) {
  const { key, ...optionProps } = props;
  return (
    <li key={key} {...optionProps}>
      <Checkbox
        size="small"
        checked={selected}
        tabIndex={-1}
        disableRipple
        sx={{ mr: 1, py: 0, mt: 0.125 }}
      />
      <Box sx={{ minWidth: 0, py: 0.125 }}>
        <Typography variant="body2" component="div" noWrap>
          {primary}
        </Typography>
        {secondary ? (
          <Typography variant="caption" color="text.secondary" component="div" noWrap>
            {secondary}
          </Typography>
        ) : null}
      </Box>
    </li>
  );
}

function renderLimitedValue(value, getItemProps, getLabel) {
  const visible = value.slice(0, MAX_VISIBLE_TAGS);
  const extra = value.length - MAX_VISIBLE_TAGS;
  const chips = visible.map((option, index) => {
    const { key, ...itemProps } = getItemProps({ index });
    return (
      <Chip
        key={key}
        size="small"
        label={getLabel(option)}
        {...itemProps}
        sx={{
          maxWidth: extra > 0 ? "68%" : "100%",
          ...(itemProps.sx || {}),
        }}
      />
    );
  });
  if (extra > 0) {
    chips.push(
      <Chip
        key="plus-more"
        size="small"
        label={`+${extra}`}
        sx={{
          cursor: "default",
          flexShrink: 0,
          maxWidth: "none",
          "& .MuiChip-label": { px: 0.75 },
        }}
      />,
    );
  }
  return chips;
}

function CheckboxFilterAutocomplete({
  label,
  placeholder,
  options,
  value,
  onChange,
  disabled,
  loading = false,
  inputValue,
  onInputChange,
  getOptionLabel,
  isOptionEqualToValue,
  getTagLabel,
  getOptionPrimary,
  getOptionSecondary,
  sx,
}) {
  const hasSelection = Array.isArray(value) && value.length > 0;
  return (
    <Autocomplete
      multiple
      disableCloseOnSelect
      size="small"
      disabled={disabled}
      options={options}
      value={value}
      inputValue={inputValue}
      loading={loading}
      filterOptions={(x) => x}
      getOptionLabel={getOptionLabel}
      isOptionEqualToValue={isOptionEqualToValue}
      onInputChange={onInputChange}
      onChange={(_event, next) => onChange(next)}
      renderOption={(props, option, state) =>
        renderCheckboxOption(props, option, state, {
          primary: getOptionPrimary(option),
          secondary: getOptionSecondary?.(option) || null,
        })
      }
      renderValue={(selected, getItemProps) =>
        renderLimitedValue(selected, getItemProps, getTagLabel)
      }
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          placeholder={hasSelection ? "" : placeholder}
        />
      )}
      slotProps={{ listbox: LISTBOX_SLOT_PROPS }}
      sx={{ ...FILTER_AUTOCOMPLETE_SX, ...FILTER_FIELD_SX, ...sx }}
    />
  );
}

function AuthorPublicationFilters({
  authors,
  draftFilters,
  appliedFilters,
  onDraftChange,
  onApply,
  onReset,
  onRemoveChip,
  facets,
  disabled = false,
  applying = false,
  filterMode = "author-analysis",
  venueSearchFn,
  secondarySearchFn,
  lookupContext,
  showLoadedSampleHint = false,
  corpusComplete = false,
  corpusTotalCount = null,
  facetsLoading = false,
}) {
  const [expanded, setExpanded] = useState(false);
  const isGrantMode = filterMode === "grant";
  const completeCorpusHint =
    corpusComplete && !isGrantMode
      ? formatCompleteCorpusFilterCaption(corpusTotalCount)
      : null;
  const facetControlsDisabled = disabled || facetsLoading;

  const resolvedLookupContext = useMemo(() => {
    if (lookupContext != null) {
      return lookupContext;
    }
    return { authors: authors || [] };
  }, [authors, lookupContext]);

  const sourceOptions = useMemo(() => {
    const rows = Array.isArray(facets?.sources) ? facets.sources : [];
    return rows.map((row) => ({
      value: row.value,
      label: row.label || row.value,
      count: row.count,
    }));
  }, [facets]);

  const selectedSources = useMemo(
    () => (draftFilters.sources || []).map((value) => {
      const option = sourceOptions.find((row) => row.value === value);
      return option || { value, label: value, count: 0, unavailable: true };
    }),
    [draftFilters.sources, sourceOptions],
  );
  const sourceOptionsWithSelected = useMemo(
    () =>
      mergeSelectedOptions(
        sourceOptions,
        selectedSources,
        (row) => row?.value,
        (row) => ({ ...row, count: 0, unavailable: true }),
      ),
    [sourceOptions, selectedSources],
  );

  const institutionFacetOptions = useMemo(
    () => (Array.isArray(facets?.institutions) ? facets.institutions : []),
    [facets],
  );
  const selectedInstitutions = useMemo(
    () => (Array.isArray(draftFilters.institutions) ? draftFilters.institutions : []),
    [draftFilters.institutions],
  );
  const institutionOptions = useMemo(
    () =>
      mergeSelectedOptions(
        institutionFacetOptions,
        selectedInstitutions,
        (row) => row?.value,
        (row) => ({ ...row, count: 0, unavailable: true }),
      ),
    [institutionFacetOptions, selectedInstitutions],
  );

  const venueFacetOptions = useMemo(
    () => (Array.isArray(facets?.venues) ? facets.venues : []),
    [facets],
  );
  const grantFacetOptions = useMemo(
    () => (Array.isArray(facets?.grants) ? facets.grants : []),
    [facets],
  );
  const authorFacetOptions = useMemo(
    () => (Array.isArray(facets?.authors) ? facets.authors : []),
    [facets],
  );

  const searchVenues = useCallback(
    (args) => (venueSearchFn || searchAuthorPublicationVenues)(args),
    [venueSearchFn],
  );
  const searchSecondary = useCallback(
    (args) =>
      (secondarySearchFn || searchAuthorPublicationGrants)(args),
    [secondarySearchFn],
  );

  const venueLookup = useDebouncedFacetLookup(searchVenues, resolvedLookupContext);
  const secondaryLookup = useDebouncedFacetLookup(
    searchSecondary,
    resolvedLookupContext,
  );

  const venueFacetOptionsWithSelected = useMemo(
    () =>
      mergeSelectedOptions(
        venueFacetOptions,
        draftFilters.venues || [],
        (row) => row?.value,
        (row) => ({ ...row, count: 0, unavailable: true }),
      ),
    [draftFilters.venues, venueFacetOptions],
  );
  const grantFacetOptionsWithSelected = useMemo(
    () =>
      mergeSelectedOptions(
        grantFacetOptions,
        draftFilters.grants || [],
        (row) => row?.grant_number,
        (row) => ({ ...row, publication_count: 0, count: 0, unavailable: true }),
      ),
    [draftFilters.grants, grantFacetOptions],
  );
  const authorFacetOptionsWithSelected = useMemo(
    () =>
      mergeSelectedOptions(
        authorFacetOptions,
        draftFilters.authors || [],
        (row) => row?.value,
        (row) => ({ ...row, count: 0, unavailable: true }),
      ),
    [authorFacetOptions, draftFilters.authors],
  );

  const venueOptions = venueLookup.inputValue.trim()
    ? venueLookup.options
    : venueFacetOptionsWithSelected;
  const grantOptions = secondaryLookup.inputValue.trim()
    ? secondaryLookup.options
    : grantFacetOptionsWithSelected;
  const authorOptions = secondaryLookup.inputValue.trim()
    ? secondaryLookup.options
    : authorFacetOptionsWithSelected;

  const validation = useMemo(
    () => validatePublicationFilters(draftFilters),
    [draftFilters],
  );
  const hasUnsavedChanges = !publicationFiltersEqual(draftFilters, appliedFilters);
  const appliedChips = useMemo(
    () => buildAppliedFilterChips(appliedFilters, sourceOptions),
    [appliedFilters, sourceOptions],
  );

  const canApply =
    !disabled &&
    !applying &&
    validation.valid &&
    hasUnsavedChanges;

  const updateDraft = (patch) => {
    onDraftChange({ ...draftFilters, ...patch });
  };

  const handleReset = () => {
    venueLookup.reset();
    secondaryLookup.reset();
    onDraftChange(emptyPublicationFilters());
    onReset();
  };

  const handleApply = () => {
    if (!canApply) {
      return;
    }
    onApply(clonePublicationFilters(draftFilters));
  };

  const handleLookupInputChange = (setInputValue) => (_event, next, reason) => {
    if (reason === "reset") {
      return;
    }
    setInputValue(next);
  };

  return (
    <Box sx={{ mb: 0 }} data-testid="publication-filters">
      <Stack
        direction="row"
        alignItems="center"
        justifyContent="space-between"
        spacing={1}
        sx={{ mb: expanded || appliedChips.length > 0 ? 0.75 : 0 }}
      >
        <Stack
          direction="row"
          flexWrap="wrap"
          useFlexGap
          spacing={0.75}
          sx={{ flex: 1, minWidth: 0, alignItems: "center" }}
        >
          {appliedChips.map((chip) => (
            <Chip
              key={chip.id}
              size="small"
              label={chip.label}
              onDelete={disabled || applying ? undefined : () => onRemoveChip(chip)}
              sx={(theme) => {
                const palette = getAnalysisPalette(theme);
                return {
                  bgcolor: palette.navySoft,
                  color: palette.navy,
                  fontWeight: 600,
                  "& .MuiChip-deleteIcon": {
                    color: palette.navy,
                  },
                };
              }}
            />
          ))}
        </Stack>
        <Button
          size="small"
          onClick={() => setExpanded((current) => !current)}
          sx={{ textTransform: "none", flexShrink: 0 }}
        >
          {expanded ? "Hide filters" : "Show filters"}
        </Button>
      </Stack>
      {completeCorpusHint ? (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: "block", mb: expanded ? 1 : 0 }}
          data-testid="publication-filter-corpus-hint"
        >
          {completeCorpusHint}
        </Typography>
      ) : showLoadedSampleHint && !isGrantMode ? (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: "block", mb: expanded ? 1 : 0 }}
          data-testid="publication-filter-sample-hint"
        >
          Filter options and counts are from currently loaded publications, not the full
          corpus.
        </Typography>
      ) : null}

      <Collapse in={expanded} timeout="auto" unmountOnExit={false}>
        <Stack
          direction="row"
          flexWrap="wrap"
          useFlexGap
          spacing={1.25}
          sx={{
            alignItems: "center",
            width: "100%",
            minWidth: 0,
            overflow: "hidden",
          }}
        >
          <TextField
            size="small"
            label="From year"
            value={draftFilters.fromYear}
            disabled={disabled}
            error={Boolean(validation.errors.fromYear || validation.errors.range)}
            helperText={validation.errors.fromYear || undefined}
            slotProps={{
              htmlInput: {
                inputMode: "numeric",
                pattern: "[0-9]*",
                maxLength: 4,
                "aria-label": "From year",
              },
              formHelperText: {
                sx: { position: "absolute", top: "100%", m: 0, whiteSpace: "nowrap" },
              },
            }}
            onChange={(event) => {
              const next = event.target.value.replace(/[^\d]/g, "").slice(0, 4);
              updateDraft({ fromYear: next });
            }}
            sx={YEAR_FIELD_SX}
          />
          <TextField
            size="small"
            label="To year"
            value={draftFilters.toYear}
            disabled={disabled}
            error={Boolean(validation.errors.toYear || validation.errors.range)}
            helperText={validation.errors.toYear || validation.errors.range || undefined}
            slotProps={{
              htmlInput: {
                inputMode: "numeric",
                pattern: "[0-9]*",
                maxLength: 4,
                "aria-label": "To year",
              },
              formHelperText: {
                sx: { position: "absolute", top: "100%", m: 0, whiteSpace: "nowrap" },
              },
            }}
            onChange={(event) => {
              const next = event.target.value.replace(/[^\d]/g, "").slice(0, 4);
              updateDraft({ toYear: next });
            }}
            sx={YEAR_FIELD_SX}
          />

          <CheckboxFilterAutocomplete
            label="Source"
            placeholder="Select sources"
            options={sourceOptionsWithSelected}
            value={selectedSources}
            disabled={facetControlsDisabled || sourceOptions.length === 0}
            loading={facetsLoading}
            getOptionLabel={(option) => option?.label || ""}
            isOptionEqualToValue={(option, selected) => option?.value === selected?.value}
            getTagLabel={(option) => option?.label || option?.value || ""}
            getOptionPrimary={(option) => option?.label || option?.value || ""}
            getOptionSecondary={(option) => publicationCountLabel(option?.count)}
            onChange={(next) =>
              updateDraft({ sources: next.map((row) => row.value) })
            }
            sx={{ width: FILTER_WIDTHS.source }}
          />

          <CheckboxFilterAutocomplete
            label="Institution"
            placeholder="Select institutions"
            options={institutionOptions}
            value={selectedInstitutions}
            disabled={facetControlsDisabled}
            loading={facetsLoading}
            getOptionLabel={(option) => option?.label || ""}
            isOptionEqualToValue={(option, selected) => option?.value === selected?.value}
            getTagLabel={(option) => option?.label || option?.value || ""}
            getOptionPrimary={(option) => option?.label || option?.value || ""}
            getOptionSecondary={(option) => {
              const countText = publicationCountLabel(option?.count);
              const country = option?.country ? String(option.country).trim() : "";
              if (country && countText) {
                return `${country} · ${countText}`;
              }
              return countText || country || null;
            }}
            onChange={(next) => updateDraft({ institutions: next })}
            sx={{ width: FILTER_WIDTHS.institution }}
          />

          <CheckboxFilterAutocomplete
            label="Journal / Venue"
            placeholder="Search venues"
            options={venueOptions}
            value={draftFilters.venues}
            disabled={facetControlsDisabled}
            loading={facetsLoading || venueLookup.loading}
            inputValue={venueLookup.inputValue}
            onInputChange={handleLookupInputChange(venueLookup.setInputValue)}
            getOptionLabel={(option) => option?.label || ""}
            isOptionEqualToValue={(option, selected) => option?.value === selected?.value}
            getTagLabel={(option) => option?.label || option?.value || ""}
            getOptionPrimary={(option) => option?.label || option?.value || ""}
            getOptionSecondary={(option) => publicationCountLabel(option?.count)}
            onChange={(next) => updateDraft({ venues: next })}
            sx={{ width: FILTER_WIDTHS.venue }}
          />

          {isGrantMode ? (
            <CheckboxFilterAutocomplete
              label="Authors"
              placeholder="Search authors"
              options={authorOptions}
              value={draftFilters.authors || []}
              disabled={facetControlsDisabled}
              loading={facetsLoading || secondaryLookup.loading}
              inputValue={secondaryLookup.inputValue}
              onInputChange={handleLookupInputChange(secondaryLookup.setInputValue)}
              getOptionLabel={(option) => option?.label || ""}
              isOptionEqualToValue={(option, selected) => option?.value === selected?.value}
              getTagLabel={(option) => option?.label || option?.value || ""}
              getOptionPrimary={(option) => option?.label || option?.value || ""}
              getOptionSecondary={(option) => publicationCountLabel(option?.count)}
              onChange={(next) => updateDraft({ authors: next })}
              sx={{ width: FILTER_WIDTHS.authors }}
            />
          ) : (
            <CheckboxFilterAutocomplete
              label="Grant"
              placeholder="Search grants"
              options={grantOptions}
              value={draftFilters.grants}
              disabled={facetControlsDisabled}
              loading={facetsLoading || secondaryLookup.loading}
              inputValue={secondaryLookup.inputValue}
              onInputChange={handleLookupInputChange(secondaryLookup.setInputValue)}
              getOptionLabel={(option) => option?.grant_number || ""}
              isOptionEqualToValue={(option, selected) =>
                option?.grant_number === selected?.grant_number
              }
              getTagLabel={(option) => option?.grant_number || ""}
              getOptionPrimary={(option) => option?.grant_number || ""}
              getOptionSecondary={(option) => {
                const countText = publicationCountLabel(
                  option?.publication_count ?? option?.count,
                );
                const funder = option?.funder ? String(option.funder).trim() : "";
                if (countText && funder) {
                  return `${countText} · ${funder}`;
                }
                return countText || funder || null;
              }}
              onChange={(next) => updateDraft({ grants: next })}
              sx={{ width: FILTER_WIDTHS.grant }}
            />
          )}

          <Box sx={FILTER_ACTIONS_SX}>
            <Button
              size="small"
              variant="contained"
              disableElevation
              disabled={!canApply}
              onClick={handleApply}
              sx={{ textTransform: "none" }}
            >
              {applying ? "Applying…" : "Apply filters"}
            </Button>
            <Button
              size="small"
              disabled={disabled || applying}
              onClick={handleReset}
              sx={{ textTransform: "none" }}
            >
              Reset
            </Button>
          </Box>
        </Stack>
      </Collapse>
    </Box>
  );
}

export default AuthorPublicationFilters;
