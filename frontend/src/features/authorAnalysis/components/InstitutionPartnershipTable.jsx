import { useState } from "react";
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
  py: 0.9,
  fontSize: "0.875rem",
};
const tableTitleSx = { fontSize: "0.98rem", fontWeight: 600 };
const DEFAULT_VISIBLE_ROWS = 10;

function PartnershipTable({ partnerships, stickyHeader = false }) {
  const maxShared = Math.max(
    1,
    ...partnerships.map((row) => Number(row.sharedPublications) || 0),
  );

  return (
    <Table size="small" stickyHeader={stickyHeader}>
      <TableHead>
        <TableRow>
          <TableCell
            sx={(theme) => ({
              ...headerCellSx,
              bgcolor: getInsightsAccent(theme, "institutionPartnerships").soft,
            })}
          >
            Partnership
          </TableCell>
          <TableCell
            sx={(theme) => ({
              ...headerCellSx,
              bgcolor: getInsightsAccent(theme, "institutionPartnerships").soft,
            })}
            align="right"
          >
            Shared Publications
          </TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {partnerships.length === 0 ? (
          <TableRow>
            <TableCell colSpan={2} sx={{ ...bodyCellSx, py: 4, textAlign: "center" }}>
              <Typography variant="body2" color="text.secondary">
                No institution collaboration data available
              </Typography>
            </TableCell>
          </TableRow>
        ) : (
          partnerships.map((row) => (
            <TableRow key={row.partnership} hover>
              <TableCell sx={{ ...bodyCellSx, minWidth: 190 }}>{row.partnership}</TableCell>
              <TableCell
                sx={(theme) => ({
                  ...bodyCellSx,
                  color: getInsightsAccent(theme, "institutionPartnerships").main,
                  fontWeight: 700,
                  minWidth: 130,
                })}
                align="right"
              >
                <Box
                  sx={{
                    display: "grid",
                    gridTemplateColumns: "1fr auto",
                    gap: 1,
                    alignItems: "center",
                  }}
                >
                  <Box
                    aria-hidden
                    sx={(theme) => ({
                      height: 5,
                      borderRadius: 999,
                      bgcolor: "action.hover",
                      overflow: "hidden",
                      "&::before": {
                        content: '""',
                        display: "block",
                        width: `${Math.max(
                          10,
                          ((Number(row.sharedPublications) || 0) / maxShared) * 100,
                        )}%`,
                        height: "100%",
                        bgcolor: getInsightsAccent(theme, "institutionPartnerships").main,
                      },
                    })}
                  />
                  <span>{row.sharedPublications}</span>
                </Box>
              </TableCell>
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  );
}

function InstitutionPartnershipTable({ partnerships = [] }) {
  const [viewAllOpen, setViewAllOpen] = useState(false);
  const previewRows = partnerships.slice(0, DEFAULT_VISIBLE_ROWS);
  const showViewAll = partnerships.length > DEFAULT_VISIBLE_ROWS;

  return (
    <Paper
      elevation={0}
      data-testid="institution-partnership-table"
      sx={{
        border: "1px solid",
        borderColor: "divider",
        borderRadius: "18px",
        bgcolor: "background.paper",
        overflow: "hidden",
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
          Top institution partnerships
        </Typography>
        {showViewAll ? (
          <Button
            size="small"
            onClick={() => setViewAllOpen(true)}
            sx={{ textTransform: "none", flexShrink: 0 }}
            data-testid="institution-partnership-view-all-button"
          >
            View all
          </Button>
        ) : null}
      </Box>
      <TableContainer sx={{ overflowX: "auto", flex: 1 }}>
        <PartnershipTable partnerships={previewRows} />
      </TableContainer>
      <InsightsViewAllDialog
        open={viewAllOpen}
        onClose={() => setViewAllOpen(false)}
        title="All institution partnerships"
        data-testid="institution-partnership-view-all-dialog"
      >
        <TableContainer sx={{ maxHeight: { xs: "64vh", md: "70vh" } }}>
          <PartnershipTable partnerships={partnerships} stickyHeader />
        </TableContainer>
      </InsightsViewAllDialog>
    </Paper>
  );
}

export default InstitutionPartnershipTable;
