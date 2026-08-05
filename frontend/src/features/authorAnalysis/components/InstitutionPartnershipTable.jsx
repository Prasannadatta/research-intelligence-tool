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

function InstitutionPartnershipTable({ partnerships = [] }) {
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
      }}
    >
      <Box sx={{ px: { xs: 2, sm: 2.5 }, pt: 2, pb: 1 }}>
        <Typography variant="subtitle1" fontWeight={600}>
          Top institution partnerships
        </Typography>
      </Box>
      <TableContainer sx={{ overflowX: "auto" }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell sx={headerCellSx}>Partnership</TableCell>
              <TableCell sx={headerCellSx} align="right">
                Shared Publications
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {partnerships.map((row) => (
              <TableRow key={row.partnership} hover>
                <TableCell sx={bodyCellSx}>{row.partnership}</TableCell>
                <TableCell sx={bodyCellSx} align="right">
                  {row.sharedPublications}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
}

export default InstitutionPartnershipTable;
