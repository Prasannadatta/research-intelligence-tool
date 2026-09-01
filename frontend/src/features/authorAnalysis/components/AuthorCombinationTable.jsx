import { useMemo, useState } from "react";
import {
  Box,
  Button,
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
import { getInsightsAccent } from "../../../theme/analysisPalette";
import InsightsViewAllDialog from "./InsightsViewAllDialog";

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
export const COMBINATION_PREVIEW_LIMIT = 10;

export function rankCombinations(combinations = []) {
  return [...combinations].sort((left, right) => {
    const byCount =
      (right.sharedPublications || 0) - (left.sharedPublications || 0);
    if (byCount !== 0) {
      return byCount;
    }
    return String(left.label || "").localeCompare(String(right.label || ""));
  });
}

export function CombinationSummaryTable({
  combinations = [],
  selectedId,
  onSelect,
  stickyHeader = false,
  rowTestIdPrefix = "combination-row",
}) {
  return (
    <Table size="small" stickyHeader={stickyHeader}>
      <TableHead>
        <TableRow>
          <TableCell
            sx={(theme) => ({
              ...headerCellSx,
              bgcolor: getInsightsAccent(theme, "combinationSummary").soft,
            })}
          >
            Authors
          </TableCell>
          <TableCell
            sx={(theme) => ({
              ...headerCellSx,
              bgcolor: getInsightsAccent(theme, "combinationSummary").soft,
            })}
            align="right"
          >
            Shared Publications
          </TableCell>
          <TableCell
            sx={(theme) => ({
              ...headerCellSx,
              bgcolor: getInsightsAccent(theme, "combinationSummary").soft,
            })}
            align="right"
          >
            Citations
          </TableCell>
          <TableCell
            sx={(theme) => ({
              ...headerCellSx,
              bgcolor: getInsightsAccent(theme, "combinationSummary").soft,
            })}
            align="right"
          >
            Institutions
          </TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {combinations.length === 0 ? (
          <TableRow>
            <TableCell colSpan={4} sx={{ ...bodyCellSx, py: 4, textAlign: "center" }}>
              <Typography variant="body2" color="text.secondary">
                No collaboration combinations available
              </Typography>
            </TableCell>
          </TableRow>
        ) : (
          combinations.map((row) => {
            const selected = row.id === selectedId;
            return (
              <TableRow
                key={row.id}
                hover
                selected={selected}
                onClick={() => onSelect?.(row.id)}
                sx={(theme) => {
                  const accent = getInsightsAccent(theme, "combinationSummary");
                  return {
                    cursor: "pointer",
                    "&.Mui-selected": {
                      bgcolor: accent.soft,
                    },
                    "&.Mui-selected:hover": {
                      bgcolor: accent.soft,
                    },
                  };
                }}
                data-testid={`${rowTestIdPrefix}-${row.id}`}
              >
                <TableCell sx={{ ...bodyCellSx, maxWidth: 360 }}>
                  <Tooltip title={row.label || ""} placement="top">
                    <Typography
                      variant="body2"
                      fontWeight={selected ? 600 : 500}
                      noWrap
                      sx={(theme) => ({
                        color: selected
                          ? getInsightsAccent(theme, "combinationSummary").main
                          : "text.primary",
                      })}
                    >
                      {row.label}
                    </Typography>
                  </Tooltip>
                </TableCell>
                <TableCell
                  sx={(theme) => ({
                    ...bodyCellSx,
                    color: getInsightsAccent(theme, "combinationSummary").main,
                    fontWeight: 600,
                  })}
                  align="right"
                >
                  {(row.sharedPublications || 0).toLocaleString()}
                </TableCell>
                <TableCell sx={bodyCellSx} align="right">
                  {(row.citations || 0).toLocaleString()}
                </TableCell>
                <TableCell sx={bodyCellSx} align="right">
                  {row.institutions}
                </TableCell>
              </TableRow>
            );
          })
        )}
      </TableBody>
    </Table>
  );
}

function AuthorCombinationTable({ combinations = [], selectedId, onSelect }) {
  const [viewAllOpen, setViewAllOpen] = useState(false);
  const ranked = useMemo(() => rankCombinations(combinations), [combinations]);
  const previewRows = ranked.slice(0, COMBINATION_PREVIEW_LIMIT);
  const showViewAll = ranked.length > COMBINATION_PREVIEW_LIMIT;

  return (
    <Paper
      elevation={0}
      data-testid="author-combination-table"
      sx={{
        border: "1px solid",
        borderColor: "divider",
        borderRadius: "18px",
        bgcolor: "background.paper",
        overflow: "hidden",
        mb: 0,
        width: "100%",
        flex: 1,
        height: "100%",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <Box
        sx={{
          px: { xs: 2, sm: 2.5 },
          pt: 2,
          pb: 1,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 1,
        }}
      >
        <Typography variant="subtitle2" sx={tableTitleSx}>
          Combination summary
        </Typography>
        {showViewAll ? (
          <Button
            size="small"
            onClick={() => setViewAllOpen(true)}
            sx={{ textTransform: "none", flexShrink: 0 }}
            data-testid="combination-view-all-button"
          >
            View all
          </Button>
        ) : null}
      </Box>
      <TableContainer sx={{ overflowX: "auto", flex: 1 }}>
        <CombinationSummaryTable
          combinations={previewRows}
          selectedId={selectedId}
          onSelect={onSelect}
        />
      </TableContainer>
      <InsightsViewAllDialog
        open={viewAllOpen}
        onClose={() => setViewAllOpen(false)}
        title="All collaborations"
        data-testid="combination-view-all-dialog"
      >
        <TableContainer sx={{ maxHeight: { xs: "64vh", md: "70vh" } }}>
          <CombinationSummaryTable
            combinations={ranked}
            selectedId={selectedId}
            onSelect={onSelect}
            stickyHeader
            rowTestIdPrefix="combination-dialog-row"
          />
        </TableContainer>
      </InsightsViewAllDialog>
    </Paper>
  );
}

export default AuthorCombinationTable;
