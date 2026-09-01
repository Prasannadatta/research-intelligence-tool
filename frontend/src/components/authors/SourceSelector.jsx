import { FormControl, MenuItem, Select, Tooltip, Typography, Box } from "@mui/material";

import { SEARCH_SOURCES, isSourceCompatible } from "../../api/searchApi";

function optionDisabledReason(source, entityType) {
  if (!source.enabled) {
    return "This source is not available.";
  }
  if (!isSourceCompatible(source, entityType)) {
    return "This source is not available for the selected entity.";
  }
  return null;
}

function SourceSelector({
  sources = [],
  value,
  entityType,
  onChange,
  disabled = false,
}) {
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
        Source:
      </Typography>
      <FormControl size="small" variant="standard" disabled={disabled}>
        <Select
          value={value || SEARCH_SOURCES.ALL}
          onChange={(event) => onChange?.(event.target.value)}
          disableUnderline
          inputProps={{ "aria-label": "Search source" }}
          sx={{
            fontSize: "0.8125rem",
            fontWeight: 500,
            color: "text.secondary",
            "& .MuiSelect-select": {
              py: 0.35,
              pr: "22px !important",
              pl: 0.5,
            },
          }}
          renderValue={(selected) => {
            const match = sources.find((item) => item.id === selected);
            return match?.label || selected;
          }}
        >
          {sources.map((source) => {
            const reason = optionDisabledReason(source, entityType);
            const menuItem = (
              <MenuItem
                key={source.id}
                value={source.id}
                disabled={Boolean(reason)}
                sx={{ fontSize: "0.875rem" }}
              >
                {source.label}
                {source.id === SEARCH_SOURCES.ARXIV &&
                Array.isArray(source.experimental_entity_types) &&
                source.experimental_entity_types.includes(entityType)
                  ? " (experimental)"
                  : ""}
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
