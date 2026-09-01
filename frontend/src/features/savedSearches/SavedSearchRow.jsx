import { Box, Button, Chip, Paper, Stack, Typography } from "@mui/material";

function formatDate(value) {
  if (!value) {
    return "Never";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown";
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

function providerLabel(value) {
  const text = String(value || "").trim().toLowerCase();
  if (text === "openalex") {
    return "OpenAlex";
  }
  if (text === "arxiv") {
    return "arXiv";
  }
  return text || null;
}

function compactList(values, singular, plural = `${singular}s`) {
  const items = Array.isArray(values) ? values.filter(Boolean) : [];
  if (items.length === 0) {
    return null;
  }
  if (items.length <= 2) {
    return items.join(", ");
  }
  return `${items.length} ${plural}`;
}

function filterSummary(filters = {}, providerContext = {}) {
  const chips = [];
  if (filters.from_year || filters.to_year) {
    chips.push(`${filters.from_year || "..."}-${filters.to_year || "..."}`);
  }
  const provider =
    providerContext.provider ||
    (Array.isArray(providerContext.providers) ? providerContext.providers[0] : null);
  const providerText = providerLabel(provider);
  if (providerText) {
    chips.push(providerText);
  }
  const institutions = compactList(filters.institutions, "institution");
  const venues = compactList(filters.venues, "venue");
  const grants = compactList(filters.grant_numbers, "grant");
  const authors = compactList(filters.authors, "author");
  [institutions, venues, grants, authors].filter(Boolean).forEach((value) => chips.push(value));
  return chips;
}

function authorCountLabel(item) {
  const count = Array.isArray(item.payload?.authors) ? item.payload.authors.length : 0;
  if (count === 0) {
    return "Author search";
  }
  return `${count} author${count === 1 ? "" : "s"}`;
}

function secondaryLine(item) {
  if (item.search_type === "authors") {
    return authorCountLabel(item);
  }
  return item.metadata?.funder_name || item.metadata?.agency || item.payload?.provider || "Grant search";
}

export default function SavedSearchRow({
  item,
  onOpen,
  onDelete,
  onUpdateData,
  updatingData = false,
}) {
  const filters = item.applied_filters || item.payload?.filters || {};
  const chips = filterSummary(filters, item.provider_context);
  const excludedCount =
    item.search_type === "authors"
      ? (item.excluded_work_ids || item.payload?.excluded_work_ids || []).length
      : 0;

  return (
    <Paper
      elevation={0}
      data-testid="saved-search-row"
      sx={{
        p: 1.75,
        border: "1px solid",
        borderColor: "divider",
        borderRadius: "8px",
      }}
    >
      <Box
        sx={{
          display: "flex",
          gap: 1.5,
          alignItems: { xs: "flex-start", sm: "center" },
          justifyContent: "space-between",
          flexDirection: { xs: "column", sm: "row" },
        }}
      >
        <Box sx={{ minWidth: 0 }}>
          <Typography fontWeight={700} sx={{ wordBreak: "break-word" }}>
            {item.display_name}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>
            {secondaryLine(item)}
          </Typography>
          <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
            <Chip size="small" variant="outlined" label={`Last viewed: ${formatDate(item.last_viewed_at)}`} />
            <Chip size="small" variant="outlined" label={`Saved: ${formatDate(item.created_at)}`} />
            <Chip size="small" variant="outlined" label={`${item.view_count || 0} views`} />
            {excludedCount > 0 ? (
              <Chip
                size="small"
                variant="outlined"
                label={`Excluded: ${excludedCount} publication${excludedCount === 1 ? "" : "s"}`}
              />
            ) : null}
          </Stack>
          {chips.length > 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
              Filters: {chips.join(" | ")}
            </Typography>
          ) : null}
        </Box>

        <Stack direction="row" spacing={1} sx={{ flexShrink: 0 }}>
          <Button size="small" variant="contained" disableElevation onClick={() => onOpen(item)} sx={{ textTransform: "none" }}>
            Open
          </Button>
          <Button
            size="small"
            color="inherit"
            variant="outlined"
            onClick={() => onUpdateData(item)}
            disabled={updatingData}
            sx={{ textTransform: "none" }}
          >
            {updatingData ? "Updating..." : "Update Data"}
          </Button>
          <Button size="small" color="error" variant="outlined" onClick={() => onDelete(item)} sx={{ textTransform: "none" }}>
            Delete
          </Button>
        </Stack>
      </Box>
    </Paper>
  );
}
