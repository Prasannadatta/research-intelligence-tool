import { useState } from "react";
import {
  Box,
  Button,
  Link,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import { getInsightsAccent } from "../../../theme/analysisPalette";
import InsightsViewAllDialog from "./InsightsViewAllDialog";
import {
  MISSING_JOURNAL_METRIC,
  formatCiteScore,
  formatSjr,
  formatSnip,
  journalMetricTooltip,
  journalMetricsFromRow,
} from "../../journalMetrics/journalMetrics";

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
  bgcolor: "background.paper",
};

const bodyCellSx = {
  borderBottom: "1px solid",
  borderColor: "divider",
  py: 1.25,
  fontSize: "0.875rem",
};
const tableTitleSx = { fontSize: "0.98rem", fontWeight: 600 };
const tableDescriptionSx = { fontSize: "0.85rem", fontWeight: 400 };
const METRICS_HELP =
  "CiteScore, SJR, and SNIP are Scopus journal metrics.";
const JOURNAL_PREVIEW_LIMIT = 10;

function MetricCell({ label, value, year, href, digitsFormatter }) {
  const formatted = digitsFormatter(value);
  const tooltip = journalMetricTooltip(label, value, year);
  const content =
    formatted !== MISSING_JOURNAL_METRIC && href ? (
      <Link
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        underline="hover"
        color="inherit"
      >
        {formatted}
      </Link>
    ) : (
      formatted
    );
  return (
    <Tooltip title={tooltip} placement="top">
      <TableCell sx={bodyCellSx} align="right">
        {content}
      </TableCell>
    </Tooltip>
  );
}

function JournalsTable({ journals, stickyHeader = false }) {
  const maxPublications = Math.max(
    1,
    ...journals.map((row) => Number(row.publications) || 0),
  );

  return (
    <Table size="small" stickyHeader={stickyHeader}>
      <TableHead>
        <TableRow>
          <TableCell
            sx={(theme) => ({
              ...headerCellSx,
              bgcolor: getInsightsAccent(theme, "topJournals").soft,
            })}
          >
            Journal / Venue
          </TableCell>
          <TableCell
            sx={(theme) => ({
              ...headerCellSx,
              bgcolor: getInsightsAccent(theme, "topJournals").soft,
            })}
            align="right"
          >
            Publications
          </TableCell>
          <TableCell
            sx={(theme) => ({
              ...headerCellSx,
              bgcolor: getInsightsAccent(theme, "topJournals").soft,
            })}
            align="right"
          >
            CiteScore
          </TableCell>
          <TableCell
            sx={(theme) => ({
              ...headerCellSx,
              bgcolor: getInsightsAccent(theme, "topJournals").soft,
            })}
            align="right"
          >
            SJR
          </TableCell>
          <TableCell
            sx={(theme) => ({
              ...headerCellSx,
              bgcolor: getInsightsAccent(theme, "topJournals").soft,
            })}
            align="right"
          >
            SNIP
          </TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {journals.length === 0 ? (
          <TableRow>
            <TableCell colSpan={5} sx={{ ...bodyCellSx, py: 4, textAlign: "center" }}>
              <Typography variant="body2" color="text.secondary">
                No venue data available
              </Typography>
            </TableCell>
          </TableRow>
        ) : (
          journals.map((row) => {
            const metrics = journalMetricsFromRow(row);
            return (
              <TableRow key={row.venue} hover>
                <TableCell sx={{ ...bodyCellSx, minWidth: 220 }}>{row.venue}</TableCell>
                <TableCell
                  sx={(theme) => ({
                    ...bodyCellSx,
                    color: getInsightsAccent(theme, "topJournals").main,
                    fontWeight: 700,
                    minWidth: 140,
                  })}
                  align="right"
                >
                  <Box
                    sx={{
                      display: "grid",
                      gridTemplateColumns: "minmax(72px, 1fr) auto",
                      gap: 1.5,
                      alignItems: "center",
                    }}
                  >
                    <Box
                      aria-hidden
                      sx={(theme) => ({
                        height: 8,
                        borderRadius: 999,
                        bgcolor: "action.hover",
                        overflow: "hidden",
                        "&::before": {
                          content: '""',
                          display: "block",
                          width: `${Math.max(
                            8,
                            ((Number(row.publications) || 0) / maxPublications) * 100,
                          )}%`,
                          height: "100%",
                          bgcolor: getInsightsAccent(theme, "topJournals").main,
                        },
                      })}
                    />
                    <span>{row.publications}</span>
                  </Box>
                </TableCell>
                <MetricCell
                  label="CiteScore"
                  value={metrics?.citescore}
                  year={metrics?.citescoreYear}
                  href={metrics?.scopusUrl}
                  digitsFormatter={formatCiteScore}
                />
                <MetricCell
                  label="SJR"
                  value={metrics?.sjr}
                  year={metrics?.sjrYear}
                  href={metrics?.scopusUrl}
                  digitsFormatter={formatSjr}
                />
                <MetricCell
                  label="SNIP"
                  value={metrics?.snip}
                  year={metrics?.snipYear}
                  href={metrics?.scopusUrl}
                  digitsFormatter={formatSnip}
                />
              </TableRow>
            );
          })
        )}
      </TableBody>
    </Table>
  );
}

function TopJournalsTable({ journals = [] }) {
  const [viewAllOpen, setViewAllOpen] = useState(false);
  const previewRows = journals.slice(0, JOURNAL_PREVIEW_LIMIT);
  const showViewAll = journals.length > JOURNAL_PREVIEW_LIMIT;

  return (
    <Paper
      elevation={0}
      data-testid="top-journals-table"
      sx={{
        mb: 0,
        border: "1px solid",
        borderColor: "divider",
        borderRadius: "18px",
        bgcolor: "background.paper",
        overflow: "hidden",
      }}
    >
      <Box
        sx={{
          px: { xs: 2, sm: 2.5 },
          pt: 2,
          pb: 1,
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 1,
        }}
      >
        <Box>
          <Box sx={{ display: "flex", alignItems: "center", gap: 0.75 }}>
            <Typography variant="subtitle2" sx={tableTitleSx}>
              Top journals / venues
            </Typography>
            <Tooltip title={METRICS_HELP} placement="top">
              <InfoOutlinedIcon
                data-testid="journal-metrics-info"
                sx={{ fontSize: 16, color: "text.secondary", cursor: "default" }}
                aria-label={METRICS_HELP}
              />
            </Tooltip>
          </Box>
          <Typography variant="body2" color="text.secondary" sx={tableDescriptionSx}>
            Venues with the most collaborative publications in this selected set.
          </Typography>
        </Box>
        {showViewAll ? (
          <Button
            size="small"
            onClick={() => setViewAllOpen(true)}
            sx={{ textTransform: "none", flexShrink: 0 }}
            data-testid="journals-view-all-button"
          >
            View all
          </Button>
        ) : null}
      </Box>
      <TableContainer sx={{ overflowX: "auto" }}>
        <JournalsTable journals={previewRows} />
      </TableContainer>
      <Typography
        variant="caption"
        color="text.secondary"
        data-testid="scopus-attribution"
        sx={{ display: "block", px: { xs: 2, sm: 2.5 }, py: 1, fontSize: "0.72rem" }}
      >
        Journal metrics powered by Scopus.
      </Typography>
      <InsightsViewAllDialog
        open={viewAllOpen}
        onClose={() => setViewAllOpen(false)}
        title="All journals / venues"
        data-testid="journals-view-all-dialog"
      >
        <TableContainer sx={{ maxHeight: { xs: "64vh", md: "70vh" } }}>
          <JournalsTable journals={journals} stickyHeader />
        </TableContainer>
      </InsightsViewAllDialog>
    </Paper>
  );
}

export default TopJournalsTable;
