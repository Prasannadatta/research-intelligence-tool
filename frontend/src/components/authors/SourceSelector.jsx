import { FormControl, MenuItem, Select, Tooltip, Typography, Box } from "@mui/material";

import {
  ENTITY_TYPES,
  SEARCH_SOURCES,
  isSourceCompatible,
} from "../../api/searchApi";

const AUTHOR_SOURCE_ORDER = [
  SEARCH_SOURCES.ALL,
  SEARCH_SOURCES.OPENALEX,
  SEARCH_SOURCES.ORCID,
];

const SOURCE_LABELS = {
  [SEARCH_SOURCES.ALL]: "All",
  [SEARCH_SOURCES.OPENALEX]: "OpenAlex",
  [SEARCH_SOURCES.ORCID]: "ORCID",
  [SEARCH_SOURCES.ARXIV]: "arXiv",
};

function sourceLabel(source) {
  return SOURCE_LABELS[source?.id] || source?.label || source?.id || "";
}

function optionDisabledReason(source, entityType) {
  if (!source.enabled) {
    return "This source is not available.";
  }
  if (!isSourceCompatible(source, entityType)) {
    return "This source is not available for the selected entity.";
  }
  return null;
}

/** Author search never offers arXiv (UI-only; grants still can). */
function sourcesForEntity(sources, entityType) {
  const list = Array.isArray(sources) ? sources : [];
  if (entityType !== ENTITY_TYPES.AUTHORS) {
    return list;
  }
  const withoutArxiv = list.filter((source) => source.id !== SEARCH_SOURCES.ARXIV);
  return [...withoutArxiv].sort((left, right) => {
    const leftRank = AUTHOR_SOURCE_ORDER.indexOf(left.id);
    const rightRank = AUTHOR_SOURCE_ORDER.indexOf(right.id);
    return (
      (leftRank === -1 ? AUTHOR_SOURCE_ORDER.length : leftRank) -
      (rightRank === -1 ? AUTHOR_SOURCE_ORDER.length : rightRank)
    );
  });
}

function SourceSelector({
  sources = [],
  value,
  entityType,
  onChange,
  disabled = false,
}) {
  const visibleSources = sourcesForEntity(sources, entityType);
  const selected = value || SEARCH_SOURCES.ALL;
  const selectedLabel =
    sourceLabel(visibleSources.find((item) => item.id === selected)) || selected;

  return (
    <Box
      sx={{
        display: "flex",
        justifyContent: "flex-end",
        alignItems: "center",
        gap: 0.75,
        mb: 1,
        minHeight: 32,
      }}
    >
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ fontWeight: 500, letterSpacing: 0.01 }}
      >
        Source
      </Typography>
      <FormControl size="small" variant="standard" disabled={disabled}>
        <Select
          value={selected}
          onChange={(event) => onChange?.(event.target.value)}
          disableUnderline
          inputProps={{ "aria-label": "Search source" }}
          MenuProps={{
            transitionDuration: 0,
          }}
          sx={{
            fontSize: "0.8125rem",
            fontWeight: 600,
            color: "text.primary",
            transition: "color 120ms ease",
            "& .MuiSelect-select": {
              py: 0.35,
              pr: "22px !important",
              pl: 0.5,
              borderRadius: 1,
            },
          }}
          renderValue={() => selectedLabel}
        >
          {visibleSources.map((source) => {
            const reason = optionDisabledReason(source, entityType);
            const label = sourceLabel(source);
            const menuItem = (
              <MenuItem
                key={source.id}
                value={source.id}
                disabled={Boolean(reason)}
                sx={{ fontSize: "0.875rem", fontWeight: source.id === selected ? 600 : 400 }}
              >
                {label}
              </MenuItem>
            );

            if (!reason) {
              return menuItem;
            }

            return (
              <Tooltip key={source.id} title={reason} placement="left">
                <Box component="span" sx={{ display: "block" }}>
                  {menuItem}
                </Box>
              </Tooltip>
            );
          })}
        </Select>
      </FormControl>
    </Box>
  );
}

export default SourceSelector;
