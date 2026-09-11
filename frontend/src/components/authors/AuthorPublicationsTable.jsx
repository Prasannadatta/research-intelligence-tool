import { useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Box,
  ButtonBase,
  Checkbox,
  Chip,
  IconButton,
  Link,
  Paper,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TableSortLabel,
  Tooltip,
  Typography,
} from "@mui/material";
import { getAnalysisPalette } from "../../theme/analysisPalette";
import LinkIcon from "@mui/icons-material/Link";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";

import { buildGrantPublicationsPath } from "../../api/grantsApi";
import {
  getWorkAuthors,
  getWorkCitationCount,
  getWorkDate,
  getWorkGrants,
  getWorkId,
  getWorkLinks,
  getWorkProviders,
  getWorkVenue,
} from "./authorPublicationHelpers";
import { AuthorNameLink } from "./AuthorInfoPopover";
import {
  PUBLICATION_SORT_FIELDS,
  nextPublicationSort,
  normalizePublicationSort,
} from "./publicationSorting";

export const COLUMN_COUNT = 8;

const SKELETON_ROW_COUNT = 5;

const headerCellSx = {
  fontWeight: 600,
  color: "text.secondary",
  fontSize: "0.75rem",
  letterSpacing: "0.04em",
  textTransform: "uppercase",
  whiteSpace: "nowrap",
  borderBottom: "1px solid",
  borderColor: "divider",
  py: 1.25,
};

const bodyCellSx = {
  verticalAlign: "top",
  borderBottom: "1px solid",
  borderColor: "divider",
  py: 1.5,
  px: 2,
  fontSize: "0.875rem",
  lineHeight: 1.5,
};

function EmDash() {
  return (
    <Typography component="span" color="text.disabled" variant="body2">
      —
    </Typography>
  );
}

function ExternalLink({ href, label, children }) {
  return (
    <Link
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={label}
      sx={{
        color: "primary.main",
        textDecoration: "none",
        "&:hover": { textDecoration: "underline" },
      }}
    >
      {children}
    </Link>
  );
}

function TitleCell({ work }) {
  const title = work?.title || "Untitled";

  // Titles are display-only for now — no internal or external navigation.
  return (
    <Typography variant="body2" fontWeight={600} sx={{ wordBreak: "break-word" }}>
      {title}
    </Typography>
  );
}

function AuthorsCell({ work }) {
  const authors = getWorkAuthors(work);
  if (authors.length === 0) {
    return <EmDash />;
  }

  return (
    <Box
      className="authors-cell"
      sx={{
        fontSize: "0.875rem",
        lineHeight: 1.5,
        color: "text.secondary",
        whiteSpace: "normal",
        wordBreak: "break-word",
        cursor: "default",
      }}
    >
      {authors.map((author, index) => (
        <Box component="span" key={`${author.canonicalAuthorId || author.name}-${index}`} sx={{ display: "inline" }}>
          <AuthorNameLink author={author} name={author.name} />
          {index < authors.length - 1 ? (
            <Box component="span" aria-hidden="true" sx={{ cursor: "default" }}>
              ,{" "}
            </Box>
          ) : null}
        </Box>
      ))}
    </Box>
  );
}

function CitationsCell({ work }) {
  const count = getWorkCitationCount(work);
  if (count == null) {
    return <EmDash />;
  }
  return <Typography variant="body2">{count.toLocaleString()}</Typography>;
}

const GRANTS_VISIBLE_COUNT = 3;

function GrantsCell({ work, searchedGrantNumber = null, grantProvider = "openalex" }) {
  const [expanded, setExpanded] = useState(false);
  const grants = getWorkGrants(work);
  if (grants.length === 0) {
    return <EmDash />;
  }

  const searchedKey = String(searchedGrantNumber || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
  const visible = expanded ? grants : grants.slice(0, GRANTS_VISIBLE_COUNT);
  const hiddenCount = grants.length - visible.length;

  return (
    <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, alignItems: "center" }}>
      {visible.map((grant) => {
        const isMatched =
          Boolean(grant.is_searched_grant) ||
          (searchedKey &&
            String(grant.normalized_grant_number || "").toLowerCase() === searchedKey);
        const path = buildGrantPublicationsPath(grant.grant_number, grantProvider);
        const label = isMatched ? `${grant.grant_number} · Matched` : grant.grant_number;
        const chip = (
          <Chip
            key={grant.normalized_grant_number || grant.grant_number}
            label={label}
            size="small"
            color={isMatched ? "primary" : "default"}
            variant={isMatched ? "filled" : "outlined"}
            clickable={Boolean(path)}
            component={path ? RouterLink : "div"}
            to={path || undefined}
            sx={{
              height: 22,
              fontSize: "0.7rem",
              borderColor: isMatched ? undefined : "divider",
              bgcolor: isMatched
                ? (theme) => getAnalysisPalette(theme).navy
                : "action.hover",
              maxWidth: "100%",
              "& .MuiChip-label": {
                overflow: "hidden",
                textOverflow: "ellipsis",
              },
            }}
          />
        );
        return chip;
      })}
      {hiddenCount > 0 ? (
        <ButtonBase
          onClick={() => setExpanded(true)}
          sx={{
            px: 0.75,
            py: 0.25,
            borderRadius: 1,
            typography: "caption",
            color: "primary.main",
            fontWeight: 600,
          }}
        >
          +{hiddenCount} more
        </ButtonBase>
      ) : null}
      {expanded && grants.length > GRANTS_VISIBLE_COUNT ? (
        <ButtonBase
          onClick={() => setExpanded(false)}
          sx={{
            px: 0.75,
            py: 0.25,
            borderRadius: 1,
            typography: "caption",
            color: "text.secondary",
            fontWeight: 500,
          }}
        >
          Show less
        </ButtonBase>
      ) : null}
    </Box>
  );
}

function SourceCell({ work }) {
  const providers = getWorkProviders(work);
  if (providers.length === 0) {
    return <EmDash />;
  }

  return (
    <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
      {providers.map((provider) => (
        <Chip
          key={provider}
          label={provider}
          size="small"
          variant="outlined"
          sx={{
            height: 22,
            fontSize: "0.7rem",
            borderColor: "divider",
            bgcolor: "transparent",
          }}
        />
      ))}
    </Box>
  );
}

function LinksCell({ work }) {
  const links = getWorkLinks(work);
  const seenHrefs = new Set();
  const actions = [
    links.doi
      ? {
          key: "doi",
          href: links.doi,
          label: "Open DOI",
          icon: LinkIcon,
        }
      : null,
    links.arxiv
      ? {
          key: "arxiv",
          href: links.arxiv,
          label: "View on arXiv",
          icon: OpenInNewIcon,
        }
      : null,
    links.provider
      ? {
          key: "provider",
          href: links.provider,
          label: "Open provider page",
          icon: OpenInNewIcon,
        }
      : null,
  ]
    .filter(Boolean)
    .filter((action) => {
      if (seenHrefs.has(action.href)) {
        return false;
      }
      seenHrefs.add(action.href);
      return true;
    });

  if (actions.length === 0) {
    return <EmDash />;
  }

  return (
    <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.25 }}>
      {actions.map((action) => {
        const Icon = action.icon;
        const button = (
          <IconButton
            size="small"
            aria-label={action.label}
            component="a"
            href={action.href}
            target="_blank"
            rel="noopener noreferrer"
            sx={{ color: "text.secondary" }}
          >
            <Icon fontSize="small" />
          </IconButton>
        );
        return (
          <Tooltip key={action.key} title={action.label}>
            <span>{button}</span>
          </Tooltip>
        );
      })}
    </Box>
  );
}

function PublicationRow({
  work,
  searchedGrantNumber = null,
  grantProvider = "openalex",
  selectable = false,
  selected = false,
  excluded = false,
  onToggleSelected,
}) {
  const venue = getWorkVenue(work);
  const date = getWorkDate(work);
  const workId = getWorkId(work);

  return (
    <TableRow
      data-testid={`publication-row-${workId || work.title}`}
      sx={(theme) => {
        const accents = getAnalysisPalette(theme);
        return {
        "&:last-child td": { borderBottom: 0 },
          bgcolor: excluded ? accents.amberSoft : "inherit",
        };
      }}
    >
      {selectable ? (
        <TableCell sx={{ ...bodyCellSx, width: 48, px: 1 }}>
          <Checkbox
            size="small"
            checked={selected}
            disabled={!workId}
            onChange={() => onToggleSelected?.(workId)}
            slotProps={{
              input: {
                "aria-label": `Select ${work?.title || "publication"}`,
                "data-testid": `publication-select-${workId}`,
              },
            }}
          />
        </TableCell>
      ) : null}
      <TableCell sx={{ ...bodyCellSx, minWidth: 220, maxWidth: 360 }}>
        <TitleCell work={work} />
        {excluded ? (
          <Chip
            label="Excluded from Insights"
            size="small"
            sx={(theme) => {
              const accents = getAnalysisPalette(theme);
              return {
                mt: 0.75,
                height: 22,
                fontSize: "0.7rem",
                bgcolor: accents.amberSoft,
                color: theme.palette.mode === "dark" ? accents.amber : "text.secondary",
                fontWeight: 600,
              };
            }}
          />
        ) : null}
      </TableCell>
      <TableCell
        sx={{
          ...bodyCellSx,
          minWidth: 180,
          maxWidth: 280,
          cursor: "default",
          "& .author-name-interactive": {
            cursor: "pointer",
          },
        }}
      >
        <AuthorsCell work={work} />
      </TableCell>
      <TableCell sx={{ ...bodyCellSx, whiteSpace: "nowrap", width: 96 }}>
        {date ? (
          <Typography variant="body2" color="text.secondary">
            {date}
          </Typography>
        ) : (
          <EmDash />
        )}
      </TableCell>
      <TableCell sx={{ ...bodyCellSx, minWidth: 120, maxWidth: 180 }}>
        {venue ? (
          <Typography variant="body2" color="text.secondary" sx={{ wordBreak: "break-word" }}>
            {venue}
          </Typography>
        ) : (
          <EmDash />
        )}
      </TableCell>
      <TableCell sx={{ ...bodyCellSx, whiteSpace: "nowrap", width: 88 }}>
        <CitationsCell work={work} />
      </TableCell>
      <TableCell sx={{ ...bodyCellSx, minWidth: 120, maxWidth: 160 }}>
        <GrantsCell
          work={work}
          searchedGrantNumber={searchedGrantNumber}
          grantProvider={grantProvider}
        />
      </TableCell>
      <TableCell sx={{ ...bodyCellSx, minWidth: 96, maxWidth: 120 }}>
        <SourceCell work={work} />
      </TableCell>
      <TableCell sx={{ ...bodyCellSx, whiteSpace: "nowrap", width: 120 }}>
        <LinksCell work={work} />
      </TableCell>
    </TableRow>
  );
}

function SkeletonRows({ columnCount = COLUMN_COUNT }) {
  return Array.from({ length: SKELETON_ROW_COUNT }, (_, index) => (
    <TableRow key={`skeleton-${index}`}>
      {Array.from({ length: columnCount }, (__, cellIndex) => (
        <TableCell key={cellIndex} sx={bodyCellSx}>
          <Skeleton variant="text" width={cellIndex === 0 ? "90%" : "70%"} />
        </TableCell>
      ))}
    </TableRow>
  ));
}

function StatusRow({ children, colSpan = COLUMN_COUNT }) {
  return (
    <TableRow>
      <TableCell colSpan={colSpan} sx={{ ...bodyCellSx, py: 4, textAlign: "center" }}>
        {children}
      </TableCell>
    </TableRow>
  );
}

const SORTABLE_HEADERS = [
  { label: "Title", sortBy: PUBLICATION_SORT_FIELDS.TITLE },
  { label: "Authors", sortBy: PUBLICATION_SORT_FIELDS.AUTHOR_COUNT },
  { label: "Year", sortBy: PUBLICATION_SORT_FIELDS.YEAR },
  { label: "Journal / Venue", sortBy: PUBLICATION_SORT_FIELDS.VENUE },
  { label: "Citations", sortBy: PUBLICATION_SORT_FIELDS.CITATIONS },
  { label: "Grants" },
  { label: "Source" },
  { label: "Links" },
];

function AuthorPublicationsTable({
  works,
  loading,
  loadingMore = false,
  error,
  mode,
  sentinelRef = null,
  emptyCopy,
  initialEmpty,
  searchedGrantNumber = null,
  grantProvider = "openalex",
  selectedWorkIds = new Set(),
  excludedWorkIds = new Set(),
  onToggleSelected,
  onToggleVisible,
  sort,
  onSortChange,
  embedded = false,
}) {
  const showEmpty = !loading && !error && (initialEmpty || works.length === 0);
  const selectable = Boolean(onToggleSelected);
  const visibleWorkIds = works.map((work) => getWorkId(work)).filter(Boolean);
  const visibleSelectedCount = visibleWorkIds.filter((id) => selectedWorkIds.has(id)).length;
  const allVisibleSelected = visibleWorkIds.length > 0 && visibleSelectedCount === visibleWorkIds.length;
  const someVisibleSelected = visibleSelectedCount > 0 && !allVisibleSelected;
  const colSpan = COLUMN_COUNT + (selectable ? 1 : 0);
  const normalizedSort = normalizePublicationSort(sort);

  return (
    <Paper
      elevation={0}
      sx={{
        width: "100%",
        maxWidth: "none",
        border: embedded ? "none" : "1px solid",
        borderColor: "divider",
        borderRadius: embedded ? 0 : "18px",
        overflow: "hidden",
        bgcolor: "background.paper",
      }}
    >
      <TableContainer sx={{ width: "100%", maxWidth: "none", overflowX: "auto" }}>
        <Table sx={{ minWidth: 1100 }} aria-label="Author publications">
          <TableHead>
            <TableRow>
              {selectable ? (
                <TableCell sx={{ ...headerCellSx, width: 48, px: 1 }}>
                  <Checkbox
                    size="small"
                    checked={allVisibleSelected}
                    indeterminate={someVisibleSelected}
                    disabled={visibleWorkIds.length === 0}
                    onChange={() => onToggleVisible?.(visibleWorkIds, !allVisibleSelected)}
                    slotProps={{
                      input: {
                        "aria-label": "Select visible publications",
                        "data-testid": "publication-select-visible",
                      },
                    }}
                  />
                </TableCell>
              ) : null}
              {SORTABLE_HEADERS.map(({ label, sortBy }) => (
                <TableCell key={label} sx={headerCellSx}>
                  {sortBy && onSortChange ? (
                    <TableSortLabel
                      active={normalizedSort.sortBy === sortBy}
                      direction={
                        normalizedSort.sortBy === sortBy
                          ? normalizedSort.sortDirection
                          : "asc"
                      }
                      onClick={() =>
                        onSortChange(nextPublicationSort(normalizedSort, sortBy))
                      }
                    >
                      {label}
                    </TableSortLabel>
                  ) : (
                    label
                  )}
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {loading ? <SkeletonRows columnCount={colSpan} /> : null}

            {!loading && error ? (
              <StatusRow colSpan={colSpan}>
                <Typography color="error" variant="body2">
                  {typeof error === "string" ? error : "Publication analysis failed."}
                </Typography>
              </StatusRow>
            ) : null}

            {!loading && !error && showEmpty ? (
              <StatusRow colSpan={colSpan}>
                <Box sx={{ maxWidth: 480, mx: "auto" }}>
                  <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 0.75 }}>
                    {emptyCopy?.heading ||
                      (mode === "common_publications"
                        ? "No common publications found"
                        : "No publications found")}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {emptyCopy?.body ||
                      "We could not find publications for the selected authors."}
                  </Typography>
                </Box>
              </StatusRow>
            ) : null}

            {!loading && !error && works.length > 0
              ? works.map((work) => (
                  <PublicationRow
                    key={getWorkId(work) || work.title}
                    work={work}
                    searchedGrantNumber={searchedGrantNumber}
                    grantProvider={grantProvider}
                    selectable={selectable}
                    selected={selectedWorkIds.has(getWorkId(work))}
                    excluded={excludedWorkIds.has(getWorkId(work))}
                    onToggleSelected={onToggleSelected}
                  />
                ))
              : null}

            {/* Optional sentinel retained for Grant publications infinite scroll only. */}
            {!loading && !error && works.length > 0 && sentinelRef ? (
              <TableRow ref={sentinelRef} data-testid="publications-scroll-sentinel">
                <TableCell colSpan={colSpan} sx={{ p: 0, border: 0 }}>
                  <Box sx={{ minHeight: 16, py: loadingMore ? 1.25 : 0, textAlign: "center" }}>
                    {loadingMore ? (
                      <Typography variant="body2" color="text.secondary">
                        Loading more publications…
                      </Typography>
                    ) : null}
                  </Box>
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
}

export default AuthorPublicationsTable;
