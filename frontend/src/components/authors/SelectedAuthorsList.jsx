import {
  Avatar,
  Box,
  Button,
  Divider,
  IconButton,
  Paper,
  Typography,
} from "@mui/material";
import CloseRoundedIcon from "@mui/icons-material/CloseRounded";

import { ENTITY_TYPES } from "../../api/searchApi";

function getInitials(name = "") {
  return String(name)
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

function formatCount(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return null;
  }
  return Number(value).toLocaleString();
}

function getItemKey(item) {
  return item?.result_id || "";
}

function getHeading(entityType, count) {
  if (entityType === ENTITY_TYPES.WORKS) {
    return count === 1 ? "Selected work" : "Selected works";
  }
  if (entityType === ENTITY_TYPES.GRANTS) {
    return count === 1 ? "Selected publication" : "Selected publications";
  }
  return count === 1 ? "Selected author" : "Selected authors";
}

function getAnalyzeLabel(entityType, count) {
  if (entityType === ENTITY_TYPES.WORKS) {
    return count <= 1 ? "Analyze work" : "Analyze works";
  }
  if (entityType === ENTITY_TYPES.GRANTS) {
    return count <= 1 ? "Analyze publication" : "Analyze publications";
  }
  return count <= 1 ? "Analyze author" : "Analyze authors";
}

function AuthorSelectedRow({ item }) {
  const institution =
    item.primary_institution?.name?.trim() || "Institution unavailable";
  const topics = (Array.isArray(item.topics) ? item.topics : [])
    .map((topic) => topic?.name)
    .filter(Boolean)
    .slice(0, 2)
    .join(" · ");
  const works = formatCount(item.works_count);
  const detail = [topics, works != null ? `${works} works` : null]
    .filter(Boolean)
    .join(" · ");

  return (
    <>
      <Avatar
        alt=""
        aria-hidden
        sx={{
          width: 36,
          height: 36,
          mt: 0.15,
          fontSize: "0.8rem",
          fontWeight: 600,
          bgcolor: "action.selected",
          color: "text.primary",
          flexShrink: 0,
        }}
      >
        {getInitials(item.display_name)}
      </Avatar>
      <Box sx={{ minWidth: 0, flex: 1 }}>
        <Typography variant="body1" fontWeight={600} sx={{ lineHeight: 1.35 }}>
          {item.display_name}
          {item.orcid ? (
            <Box
              component="span"
              sx={{
                ml: 1,
                fontSize: "0.7rem",
                fontWeight: 500,
                color: "text.disabled",
                verticalAlign: "middle",
              }}
            >
              ORCID
            </Box>
          ) : null}
        </Typography>
        <Typography
          variant="body2"
          color="text.secondary"
          sx={{ lineHeight: 1.4, mt: 0.1 }}
        >
          {institution}
        </Typography>
        {detail ? (
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ display: "block", lineHeight: 1.4, mt: 0.1 }}
          >
            {detail}
          </Typography>
        ) : null}
      </Box>
    </>
  );
}

function WorkSelectedRow({ item }) {
  const authors = (Array.isArray(item.authors) ? item.authors : [])
    .map((author) => author?.name)
    .filter(Boolean)
    .slice(0, 4)
    .join(", ");
  const meta = [item.publication_year, item.primary_source || (item.source === "arxiv" ? "arXiv" : null)]
    .filter(Boolean)
    .join(" · ");

  return (
    <Box sx={{ minWidth: 0, flex: 1 }}>
      <Typography variant="body1" fontWeight={600} sx={{ lineHeight: 1.35 }}>
        {item.title}
      </Typography>
      {authors ? (
        <Typography
          variant="body2"
          color="text.secondary"
          sx={{ lineHeight: 1.4, mt: 0.1 }}
        >
          {authors}
        </Typography>
      ) : null}
      {meta ? (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: "block", lineHeight: 1.4, mt: 0.1 }}
        >
          {meta}
        </Typography>
      ) : null}
      {item.source === "arxiv" ? (
        <Typography
          variant="caption"
          color="text.disabled"
          sx={{ display: "block", lineHeight: 1.35, mt: 0.1 }}
        >
          arXiv
        </Typography>
      ) : null}
    </Box>
  );
}

function ArxivAuthorNameSelectedRow({ item }) {
  const paperCount =
    item.matching_papers_count != null
      ? Number(item.matching_papers_count).toLocaleString()
      : null;

  return (
    <Box sx={{ minWidth: 0, flex: 1 }}>
      <Typography variant="body1" fontWeight={600} sx={{ lineHeight: 1.35 }}>
        {item.display_name}
      </Typography>
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ display: "block", lineHeight: 1.4, mt: 0.1 }}
      >
        From arXiv paper metadata
        {paperCount != null ? ` · ${paperCount} papers` : ""}
      </Typography>
      <Typography
        variant="caption"
        color="warning.main"
        sx={{ display: "block", lineHeight: 1.35, mt: 0.1, fontWeight: 500 }}
      >
        Unverified author identity
      </Typography>
    </Box>
  );
}

function GrantSelectedRow({ item }) {
  const secondary = [item.funder_name, item.funder_award_id]
    .filter(Boolean)
    .join(" · ");
  const years =
    item.start_year || item.end_year
      ? [item.start_year, item.end_year].filter((v) => v != null).join("–")
      : null;
  const tertiary = [item.lead_investigator, years].filter(Boolean).join(" · ");

  return (
    <Box sx={{ minWidth: 0, flex: 1 }}>
      <Typography variant="body1" fontWeight={600} sx={{ lineHeight: 1.35 }}>
        {item.display_name || "Untitled grant"}
      </Typography>
      {secondary ? (
        <Typography
          variant="body2"
          color="text.secondary"
          sx={{ lineHeight: 1.4, mt: 0.1 }}
        >
          {secondary}
        </Typography>
      ) : null}
      {tertiary ? (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: "block", lineHeight: 1.4, mt: 0.1 }}
        >
          {tertiary}
        </Typography>
      ) : null}
    </Box>
  );
}

function SelectedAuthorsList({
  entityType = ENTITY_TYPES.AUTHORS,
  items = [],
  onRemove,
  onClearAll,
  onAnalyze,
}) {
  const count = items.length;
  const hasItems = count > 0;
  const heading = getHeading(entityType, count);

  return (
    <Paper
      elevation={0}
      aria-hidden={!hasItems}
      sx={{
        mt: { xs: 2.5, md: 0 },
        width: "100%",
        minHeight: 180,
        maxHeight: 340,
        textAlign: "left",
        border: "1px solid",
        borderColor: "divider",
        borderRadius: "18px",
        bgcolor: "background.paper",
        boxShadow: (theme) =>
          theme.palette.mode === "dark"
            ? "0 6px 18px rgba(0,0,0,0.22)"
            : "0 6px 18px rgba(15,23,42,0.05)",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        visibility: hasItems ? "visible" : "hidden",
        pointerEvents: hasItems ? "auto" : "none",
        opacity: hasItems ? 1 : 0,
        transition: "opacity 120ms ease",
      }}
    >
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 1.5,
          px: 2.25,
          pt: 1.75,
          pb: 1.25,
          flexShrink: 0,
        }}
      >
        <Typography variant="body2" color="text.secondary" fontWeight={500}>
          {heading}
          <Box component="span" sx={{ mx: 0.75, opacity: 0.55 }}>
            ·
          </Box>
          {count}
        </Typography>

        {count >= 2 ? (
          <Button
            variant="text"
            color="inherit"
            size="small"
            onClick={onClearAll}
            aria-label="Clear all selected items"
            sx={{
              minWidth: 0,
              px: 1,
              color: "text.secondary",
              textTransform: "none",
              fontWeight: 500,
              "&:hover": {
                bgcolor: "action.hover",
                color: "text.primary",
              },
            }}
          >
            Clear all
          </Button>
        ) : null}
      </Box>

      <Divider sx={{ borderColor: "divider", flexShrink: 0 }} />

      <Box
        sx={{
          flex: 1,
          minHeight: 0,
          maxHeight: 200,
          overflowY: "auto",
          overflowX: "hidden",
          pr: 0.5,
          scrollbarGutter: "stable",
          scrollbarWidth: "thin",
          scrollbarColor: (theme) =>
            `${theme.palette.action.disabled} transparent`,
          "&::-webkit-scrollbar": {
            width: 8,
          },
          "&::-webkit-scrollbar-track": {
            background: "transparent",
          },
          "&::-webkit-scrollbar-thumb": {
            backgroundColor: "action.disabled",
            borderRadius: 8,
          },
          "&::-webkit-scrollbar-thumb:hover": {
            backgroundColor: "action.active",
          },
        }}
      >
        {items.map((item, index) => {
          const key = getItemKey(item);
          const label = item.display_name || item.title || "Selected item";

          return (
            <Box key={key}>
              {index > 0 ? <Divider sx={{ borderColor: "divider" }} /> : null}

              <Box
                sx={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 1.5,
                  px: 2.25,
                  py: 1.5,
                }}
              >
                {item.result_type === "author_name" ? (
                  <ArxivAuthorNameSelectedRow item={item} />
                ) : entityType === ENTITY_TYPES.WORKS ||
                  entityType === ENTITY_TYPES.GRANTS ||
                  item.result_type === "work" ? (
                  <WorkSelectedRow item={item} />
                ) : item.result_type === "grant" ? (
                  <GrantSelectedRow item={item} />
                ) : (
                  <AuthorSelectedRow item={item} />
                )}

                <IconButton
                  size="small"
                  onClick={() => onRemove(key)}
                  aria-label={`Remove ${label}`}
                  sx={{
                    mt: 0.1,
                    color: "text.secondary",
                    "&:hover": {
                      bgcolor: "action.hover",
                      color: "text.primary",
                    },
                  }}
                >
                  <CloseRoundedIcon fontSize="small" />
                </IconButton>
              </Box>
            </Box>
          );
        })}
      </Box>

      <Divider sx={{ borderColor: "divider", flexShrink: 0 }} />

      <Box
        sx={{
          display: "flex",
          justifyContent: "center",
          px: 2.25,
          py: 1.75,
          flexShrink: 0,
        }}
      >
        <Button
          variant="contained"
          color="inherit"
          disableElevation
          onClick={onAnalyze}
          disabled={!hasItems}
          sx={{
            px: 2.5,
            py: 1,
            borderRadius: 999,
            textTransform: "none",
            fontWeight: 600,
            bgcolor: "text.primary",
            color: "background.paper",
            "&:hover": {
              bgcolor: "text.secondary",
            },
            "&.Mui-disabled": {
              bgcolor: "action.disabledBackground",
              color: "text.disabled",
            },
          }}
        >
          {getAnalyzeLabel(entityType, count)}
        </Button>
      </Box>
    </Paper>
  );
}

export default SelectedAuthorsList;
