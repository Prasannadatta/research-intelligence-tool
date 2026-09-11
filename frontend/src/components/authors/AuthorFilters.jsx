import { useEffect, useRef, useState } from "react";
import {
  Autocomplete,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  Fade,
  TextField,
  Typography,
} from "@mui/material";
import FilterListRoundedIcon from "@mui/icons-material/FilterListRounded";
import CloseRoundedIcon from "@mui/icons-material/CloseRounded";

import { searchInstitutions, searchTopics } from "../../api/searchApi";

const FILTER_DEBOUNCE_MS = 400;
const MIN_FILTER_QUERY_LENGTH = 2;

const chipSx = {
  maxWidth: "100%",
  bgcolor: "action.selected",
  borderColor: "divider",
  transition: "background-color 140ms ease, box-shadow 140ms ease",
  "& .MuiChip-label": {
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  "& .MuiChip-deleteIcon": {
    color: "text.secondary",
    "&:hover": { color: "text.primary" },
  },
};

function useDebouncedLookup(lookupFn) {
  const [inputValue, setInputValue] = useState("");
  const [options, setOptions] = useState([]);
  const [loading, setLoading] = useState(false);
  const requestIdRef = useRef(0);
  const abortRef = useRef(null);

  useEffect(() => {
    const cleaned = inputValue.trim().replace(/\s+/g, " ");
    if (cleaned.length < MIN_FILTER_QUERY_LENGTH) {
      requestIdRef.current += 1;
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
      setOptions([]);
      setLoading(false);
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
        const results = await lookupFn(cleaned, { signal: controller.signal });
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
    }, FILTER_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [inputValue, lookupFn]);

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

function FilterAutocomplete({
  label,
  placeholder,
  value,
  onChange,
  lookupState,
}) {
  return (
    <Autocomplete
      size="small"
      options={lookupState.options}
      loading={lookupState.loading}
      value={value}
      inputValue={lookupState.inputValue}
      filterOptions={(x) => x}
      getOptionLabel={(option) => option?.display_name || ""}
      isOptionEqualToValue={(option, selected) => option?.id === selected?.id}
      slotProps={{
        paper: {
          sx: {
            mt: 0.5,
            borderRadius: 2,
            border: "1px solid",
            borderColor: "divider",
            boxShadow: (theme) =>
              theme.palette.mode === "dark"
                ? "0 8px 20px rgba(0,0,0,0.28)"
                : "0 8px 20px rgba(15,23,42,0.08)",
          },
        },
      }}
      onInputChange={(_event, next, reason) => {
        if (reason === "reset") {
          return;
        }
        lookupState.setInputValue(next);
      }}
      onChange={(_event, next) => {
        onChange(next);
        if (next) {
          lookupState.reset();
        }
      }}
      noOptionsText={
        lookupState.inputValue.trim().length < MIN_FILTER_QUERY_LENGTH
          ? "Type at least 2 characters"
          : lookupState.loading
            ? "Searching…"
            : "No matches"
      }
      renderOption={(props, option) => {
        const { key, ...optionProps } = props;
        const meta = [
          option.country_code || option.type,
          option.works_count != null
            ? `${Number(option.works_count).toLocaleString()} works`
            : null,
        ]
          .filter(Boolean)
          .join(" · ");

        return (
          <Box component="li" key={key} {...optionProps} sx={{ display: "block" }}>
            <Typography variant="body2" fontWeight={600}>
              {option.display_name}
            </Typography>
            {meta ? (
              <Typography variant="caption" color="text.secondary">
                {meta}
              </Typography>
            ) : null}
            {option.description ? (
              <Typography
                variant="caption"
                color="text.disabled"
                sx={{
                  display: "block",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {option.description}
              </Typography>
            ) : null}
          </Box>
        );
      }}
      renderInput={(params) => {
        const inputSlot = params.slotProps?.input ?? {};
        return (
          <TextField
            {...params}
            label={label}
            placeholder={placeholder}
            slotProps={{
              ...params.slotProps,
              input: {
                ...inputSlot,
                endAdornment: (
                  <>
                    {lookupState.loading ? (
                      <CircularProgress color="inherit" size={14} />
                    ) : null}
                    {inputSlot.endAdornment}
                  </>
                ),
              },
            }}
          />
        );
      }}
    />
  );
}

function AuthorFilters({
  institution,
  topic,
  onInstitutionChange,
  onTopicChange,
}) {
  const [filtersOpen, setFiltersOpen] = useState(false);
  const institutionLookup = useDebouncedLookup(searchInstitutions);
  const topicLookup = useDebouncedLookup(searchTopics);
  const hasAnyFilter = Boolean(institution || topic);
  const missingFilterSlots = !institution || !topic;
  const activeCount = Number(Boolean(institution)) + Number(Boolean(topic));

  useEffect(() => {
    if (institution && topic) {
      setFiltersOpen(false);
    }
  }, [institution, topic]);

  const clearAll = () => {
    if (institution) {
      onInstitutionChange(null);
    }
    if (topic) {
      onTopicChange(null);
    }
  };

  return (
    <Box sx={{ mt: 1, textAlign: "left" }}>
      <Box
        sx={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: 0.75,
          minHeight: 32,
        }}
      >
        <Fade in={Boolean(institution)} unmountOnExit>
          <Chip
            size="small"
            variant="outlined"
            color="primary"
            label={`Institution: ${institution?.display_name || ""}`}
            onDelete={() => onInstitutionChange(null)}
            deleteIcon={<CloseRoundedIcon sx={{ fontSize: "14px !important" }} />}
            sx={chipSx}
          />
        </Fade>

        <Fade in={Boolean(topic)} unmountOnExit>
          <Chip
            size="small"
            variant="outlined"
            color="primary"
            label={`Research: ${topic?.display_name || ""}`}
            onDelete={() => onTopicChange(null)}
            deleteIcon={<CloseRoundedIcon sx={{ fontSize: "14px !important" }} />}
            sx={chipSx}
          />
        </Fade>

        {missingFilterSlots ? (
          <Button
            size="small"
            color="inherit"
            startIcon={<FilterListRoundedIcon sx={{ fontSize: 16 }} />}
            onClick={() => setFiltersOpen((open) => !open)}
            aria-expanded={filtersOpen}
            sx={{
              textTransform: "none",
              color: filtersOpen || hasAnyFilter ? "text.primary" : "text.secondary",
              fontWeight: 600,
              minWidth: 0,
              px: 1,
              py: 0.25,
              borderRadius: 999,
              bgcolor: filtersOpen ? "action.hover" : "transparent",
              transition: "background-color 140ms ease, color 140ms ease",
              "&:hover": {
                bgcolor: "action.hover",
                color: "text.primary",
              },
            }}
          >
            {filtersOpen ? "Hide filters" : hasAnyFilter ? "Add filter" : "Filters"}
            {!filtersOpen && activeCount > 0 ? ` (${activeCount})` : ""}
          </Button>
        ) : null}

        <Fade in={hasAnyFilter} unmountOnExit>
          <Button
            size="small"
            color="inherit"
            onClick={clearAll}
            sx={{
              textTransform: "none",
              color: "text.secondary",
              fontWeight: 500,
              minWidth: 0,
              px: 0.75,
              py: 0.25,
              borderRadius: 999,
              "&:hover": {
                bgcolor: "action.hover",
                color: "text.primary",
              },
            }}
          >
            Clear
          </Button>
        </Fade>
      </Box>

      <Collapse in={filtersOpen && missingFilterSlots} timeout={160} unmountOnExit>
        <Box
          sx={{
            mt: 1,
            p: 1.25,
            borderRadius: 2,
            border: "1px solid",
            borderColor: "divider",
            bgcolor: "action.hover",
            display: "grid",
            gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
            gap: 1,
          }}
        >
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ gridColumn: "1 / -1", mb: 0.25 }}
          >
            Narrow OpenAlex authors by institution or research area.
          </Typography>
          {!institution ? (
            <FilterAutocomplete
              label="Institution"
              placeholder="Search institutions"
              value={null}
              onChange={onInstitutionChange}
              lookupState={institutionLookup}
            />
          ) : null}
          {!topic ? (
            <FilterAutocomplete
              label="Research area"
              placeholder="Search research areas"
              value={null}
              onChange={onTopicChange}
              lookupState={topicLookup}
            />
          ) : null}
        </Box>
      </Collapse>
    </Box>
  );
}

export default AuthorFilters;
