import {
  Box,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";

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
  borderBottom: "1px solid",
  borderColor: "divider",
  py: 1.25,
  fontSize: "0.875rem",
};

function TopJournalsTable({ journals = [] }) {
  return (
    <Paper
      elevation={0}
      data-testid="top-journals-table"
      sx={{
        mb: 2.5,
        border: "1px solid",
        borderColor: "divider",
        borderRadius: "18px",
        bgcolor: "background.paper",
        overflow: "hidden",
      }}
    >
      <Box sx={{ px: { xs: 2, sm: 2.5 }, pt: 2, pb: 1 }}>
        <Typography variant="subtitle1" fontWeight={600}>
          Top journals / venues
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Venues with the most collaborative publications in this demo set.
        </Typography>
      </Box>
      <TableContainer sx={{ overflowX: "auto" }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell sx={headerCellSx}>Journal / Venue</TableCell>
              <TableCell sx={headerCellSx} align="right">
                Publications
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {journals.map((row) => (
              <TableRow key={row.venue} hover>
                <TableCell sx={bodyCellSx}>{row.venue}</TableCell>
                <TableCell sx={bodyCellSx} align="right">
                  {row.publications}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
}

export default TopJournalsTable;
