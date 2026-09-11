import { useEffect, useRef, useState } from "react";
import {
  Autocomplete,
  Box,
  Button,
  Chip,
  CircularProgress,
  Stack,
  TextField,
  Typography,
} from "@mui/material";

import { searchInstitutions, searchTopics } from "../../api/searchApi";

const DEBOUNCE_MS = 300;
const MIN_QUERY_LENGTH = 2;

function useFilterOptions(lookupFn) {
  const [inputValue, setInputValue] = useState("");
  const [options, setOptions] = useState([]);
  const [loading, setLoading] = useState(false);
  const requestIdRef = useRef(0);
  const abortRef = useRef(null);

  useEffect(() => {
    const query = inputValue.trim().replace(/\s+/g, " ");
    if (query.length < MIN_QUERY_LENGTH) {
      requestIdRef.current += 1;
      abortRef.current?.abort();
      abortRef.current = null;
      setOptions([]);
      setLoading(false);
      return undefined;
    }

    const requestId = ++requestIdRef.current;
    setLoading(true);
    const timeoutId = window.setTimeout(async () => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const results = await lookupFn(query, { signal: controller.signal });
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
    }, DEBOUNCE_MS);

    return () => window.clearTimeout(timeoutId);
  }, [inputValue, lookupFn]);

  const reset = () => {
    requestIdRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    setInputValue("");
    setOptions([]);
    setLoading(false);
  };

  return { inputValue, setInputValue, options, loading, reset };
}

function FilterSearchField({
  id,
  label,
  placeholder,
  onSelect,
  lookupFn,
  getOptionMeta,
}) {
  const { inputValue, setInputValue, options, loading, reset } =
    useFilterOptions(lookupFn);

  return (
    <Autocomplete
      id={id}
      size="small"
      fullWidth
      options={options}
      loading={loading}
      value={null}
      inputValue={inputValue}
      filterOptions={(items) => items}
      getOptionLabel={(option) => option?.display_name || ""}
      isOptionEqualToValue={(option, selected) => option?.id === selected?.id}
      clearOnBlur={false}
      blurOnSelect
      onInputChange={(_event, next, reason) => {
        if (reason === "reset") {
          return;
        }
        setInputValue(next);
      }}
      onChange={(_event, next) => {
        if (!next) {
          return;
        }
        onSelect(next);
        reset();
      }}
      noOptionsText={
        inputValue.trim().length < MIN_QUERY_LENGTH
          ? "Type at least 2 characters"
          : loading
            ? "Searching…"
            : "No matches"
      }
      renderOption={(props, option) => {
        const { key, ...optionProps } = props;
        const meta = getOptionMeta?.(option);
        return (
          <li key={key} {...optionProps}>
            <Box sx={{ py: 0.25 }}>
              <Typography variant="body2" fontWeight={600}>
                {option.display_name}
              </Typography>
              {meta ? (
                <Typography variant="caption" color="text.secondary" display="block">
                  {meta}
                </Typography>
              ) : null}
            </Box>
          </li>
        );
      }}
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          placeholder={placeholder}
          slotProps={{
            ...params.slotProps,
            input: {
              ...(params.slotProps?.input || {}),
              endAdornment: (
                <>
                  {loading ? (
                    <CircularProgress color="inherit" size={14} sx={{ mr: 0.5 }} />
                  ) : null}
                  {params.slotProps?.input?.endAdornment}
                </>
              ),
            },
          }}
        />
      )}
    />
  );
}

/**
 * OpenAlex author filters — always-visible Institution + Research Area fields.
 * Selection is shown as chips; parent hides this for ORCID-only.
 */
function AuthorFilters({
  institution,
  topic,
  onInstitutionChange,
  onTopicChange,
}) {
  const hasFilters = Boolean(institution || topic);

  return (
    <Box sx={{ mt: 1.25, textAlign: "left" }} data-testid="author-filters">
      <Stack
        direction={{ xs: "column", sm: "row" }}
        spacing={1}
        useFlexGap
      >
        <FilterSearchField
          id="author-filter-institution"
          label="Institution"
          placeholder="Search institutions"
          onSelect={onInstitutionChange}
          lookupFn={searchInstitutions}
          getOptionMeta={(option) =>
            [
              option.country_code || option.type,
              option.works_count != null
                ? `${Number(option.works_count).toLocaleString()} works`
                : null,
            ]
              .filter(Boolean)
              .join(" · ")
          }
        />
        <FilterSearchField
          id="author-filter-topic"
          label="Research area"
          placeholder="Search research areas"
          onSelect={onTopicChange}
          lookupFn={searchTopics}
          getOptionMeta={(option) =>
            option.works_count != null
              ? `${Number(option.works_count).toLocaleString()} works`
              : null
          }
        />
      </Stack>

      {hasFilters ? (
        <Stack
          direction="row"
          spacing={0.75}
          useFlexGap
          flexWrap="wrap"
          alignItems="center"
          sx={{ mt: 1 }}
        >
          {institution ? (
            <Chip
              size="small"
              color="primary"
              variant="outlined"
              label={`Institution: ${institution.display_name}`}
              onDelete={() => onInstitutionChange(null)}
            />
          ) : null}
          {topic ? (
            <Chip
              size="small"
              color="primary"
              variant="outlined"
              label={`Research: ${topic.display_name}`}
              onDelete={() => onTopicChange(null)}
            />
          ) : null}
          <Button
            size="small"
            color="inherit"
            onClick={() => {
              onInstitutionChange(null);
              onTopicChange(null);
            }}
            sx={{
              textTransform: "none",
              color: "text.secondary",
              fontWeight: 500,
              minWidth: 0,
              px: 0.75,
            }}
          >
            Clear filters
          </Button>
        </Stack>
      ) : (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: "block", mt: 0.75 }}
        >
          Optional: narrow OpenAlex results by institution or research area.
        </Typography>
      )}
    </Box>
  );
}

export default AuthorFilters;
