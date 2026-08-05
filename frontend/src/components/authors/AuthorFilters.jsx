import { useEffect, useRef, useState } from "react";
import {
  Autocomplete,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  TextField,
  Typography,
} from "@mui/material";
import FilterListRoundedIcon from "@mui/icons-material/FilterListRounded";
import CloseRoundedIcon from "@mui/icons-material/CloseRounded";

import { searchInstitutions, searchTopics } from "../../api/searchApi";

const FILTER_DEBOUNCE_MS = 400;
const MIN_FILTER_QUERY_LENGTH = 2;

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
      renderOption={(props, option) => {
        const { key, ...optionProps } = props;
        const meta = [option.country_code || option.type, option.works_count != null
          ? `${Number(option.works_count).toLocaleString()} works`
          : null]
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
        const inputProps = params.InputProps ?? params.slotProps?.input ?? {};
        return (
          <TextField
            {...params}
            label={label}
            placeholder={placeholder}
            InputProps={{
              ...inputProps,
              endAdornment: (
                <>
                  {lookupState.loading ? (
                    <CircularProgress color="inherit" size={14} />
                  ) : null}
                  {inputProps.endAdornment}
                </>
              ),
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

  useEffect(() => {
    if (institution && topic) {
      setFiltersOpen(false);
    }
  }, [institution, topic]);

  return (
    <Box sx={{ mt: 1, textAlign: "left" }}>
      <Box
        sx={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: 0.75,
          minHeight: 28,
        }}
      >
        {institution ? (
          <Chip
            size="small"
            label={`Institution: ${institution.display_name}`}
            onDelete={() => onInstitutionChange(null)}
            deleteIcon={<CloseRoundedIcon sx={{ fontSize: "14px !important" }} />}
            sx={{
              maxWidth: "100%",
              bgcolor: "action.hover",
              "& .MuiChip-label": {
                overflow: "hidden",
                textOverflow: "ellipsis",
              },
            }}
          />
        ) : null}

        {topic ? (
          <Chip
            size="small"
            label={`Research: ${topic.display_name}`}
            onDelete={() => onTopicChange(null)}
            deleteIcon={<CloseRoundedIcon sx={{ fontSize: "14px !important" }} />}
            sx={{
              maxWidth: "100%",
              bgcolor: "action.hover",
              "& .MuiChip-label": {
                overflow: "hidden",
                textOverflow: "ellipsis",
              },
            }}
          />
        ) : null}

        {(!institution || !topic) && (
          <Button
            size="small"
            color="inherit"
            startIcon={<FilterListRoundedIcon sx={{ fontSize: 16 }} />}
            onClick={() => setFiltersOpen((open) => !open)}
            sx={{
              textTransform: "none",
              color: "text.secondary",
              fontWeight: 500,
              minWidth: 0,
              px: 1,
              py: 0.25,
              borderRadius: 999,
              "&:hover": {
                bgcolor: "action.hover",
                color: "text.primary",
              },
            }}
          >
            {filtersOpen ? "Hide filters" : "Filters"}
          </Button>
        )}
      </Box>

      <Collapse in={filtersOpen && (!institution || !topic)} unmountOnExit>
        <Box
          sx={{
            mt: 1,
            display: "grid",
            gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
            gap: 1,
          }}
        >
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
