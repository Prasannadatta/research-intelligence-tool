import { memo } from "react";
import { Box, Typography } from "@mui/material";

const clampOneLine = {
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const clampTwoLines = {
  overflow: "hidden",
  display: "-webkit-box",
  WebkitBoxOrient: "vertical",
  WebkitLineClamp: 2,
};

function formatCount(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return null;
  }
  return Number(value).toLocaleString();
}

/**
 * Shared publication / work row used by search results and author analysis.
 */
const WorkCard = memo(function WorkCard({ option }) {
  const authors = (Array.isArray(option.authors) ? option.authors : [])
    .map((author) => author?.name)
    .filter(Boolean)
    .slice(0, 4)
    .join(", ");
  const year =
    option.publication_year != null ? String(option.publication_year) : null;
  const citations =
    option.citation_count != null
      ? formatCount(option.citation_count)
      : option.cited_by_count != null
        ? formatCount(option.cited_by_count)
        : null;
  const isArxiv =
    option.source === "arxiv" ||
    (Array.isArray(option.providers) && option.providers.includes("arxiv") && option.source !== "openalex");
  const categoryLine = isArxiv
    ? Array.isArray(option.categories) && option.categories.length > 0
      ? option.categories.slice(0, 3).join(" · ")
      : "arXiv"
    : option.journal || option.primary_source;
  const sourceLine = [
    year,
    categoryLine,
    citations != null ? `${citations} citations` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const primaryGrant =
    Array.isArray(option.grants) && option.grants.length > 0
      ? option.grants[0]
      : null;
  const grantLine = primaryGrant
    ? primaryGrant.verified === false
      ? `Grant (unverified metadata): ${primaryGrant.award_id || "matched grant"}`
      : `Grant: ${primaryGrant.award_id || primaryGrant.funder_name || "matched grant"}`
    : option.matched_grant_number
      ? option.grant_match?.verified === false
        ? `Grant (unverified metadata): ${option.matched_grant_number}`
        : `Grant: ${option.matched_grant_number}`
      : option.match_reason === "grant_number"
        ? `Funded by ${
            option.matched_grant?.award_id ||
            option.matched_grant?.display_name ||
            "matched grant"
          }`
        : "";

  const experimental =
    option.analysis_match && option.analysis_match.verified === false;

  return (
    <Box sx={{ minWidth: 0, textAlign: "left", minHeight: 78 }}>
      <Box sx={{ display: "flex", alignItems: "flex-start", gap: 0.75 }}>
        <Typography
          variant="body1"
          fontWeight={600}
          sx={{ lineHeight: 1.35, flex: 1, minWidth: 0, ...clampTwoLines }}
        >
          {option.title}
        </Typography>
        {isArxiv ? (
          <Typography
            variant="caption"
            sx={{
              flexShrink: 0,
              mt: 0.2,
              px: 0.6,
              py: 0.1,
              borderRadius: 1,
              bgcolor: "action.hover",
              color: "text.secondary",
              fontWeight: 600,
              letterSpacing: 0.02,
            }}
          >
            arXiv
          </Typography>
        ) : null}
      </Box>
      <Typography
        variant="body2"
        color="text.secondary"
        sx={{ lineHeight: 1.4, mt: 0.15, minHeight: 20, ...clampOneLine }}
      >
        {authors}
      </Typography>
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{
          display: "block",
          lineHeight: 1.4,
          mt: 0.15,
          minHeight: 18,
          ...clampOneLine,
        }}
      >
        {sourceLine}
      </Typography>
      {grantLine ? (
        <Typography
          variant="caption"
          color="text.disabled"
          sx={{
            display: "block",
            lineHeight: 1.35,
            mt: 0.1,
            minHeight: 16,
            ...clampOneLine,
          }}
        >
          {grantLine}
        </Typography>
      ) : null}
      {experimental ? (
        <Typography
          variant="caption"
          color="warning.main"
          sx={{
            display: "block",
            lineHeight: 1.35,
            mt: 0.1,
            fontWeight: 500,
          }}
        >
          Unverified author match
        </Typography>
      ) : null}
    </Box>
  );
});

export default WorkCard;
