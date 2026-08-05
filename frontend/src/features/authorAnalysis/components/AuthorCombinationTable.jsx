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

function AuthorCombinationTable({ combinations = [], selectedId, onSelect }) {
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
        mb: 2.5,
      }}
    >
      <Box sx={{ px: { xs: 2, sm: 2.5 }, pt: 2, pb: 1 }}>
        <Typography variant="subtitle1" fontWeight={600}>
          Combination summary
        </Typography>
      </Box>
      <TableContainer sx={{ overflowX: "auto" }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell sx={headerCellSx}>Authors</TableCell>
              <TableCell sx={headerCellSx} align="right">
                Shared Publications
              </TableCell>
              <TableCell sx={headerCellSx} align="right">
                Citations
              </TableCell>
              <TableCell sx={headerCellSx} align="right">
                Institutions
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {combinations.map((row) => {
              const selected = row.id === selectedId;
              return (
                <TableRow
                  key={row.id}
                  hover
                  selected={selected}
                  onClick={() => onSelect?.(row.id)}
                  sx={{ cursor: "pointer" }}
                  data-testid={`combination-row-${row.id}`}
                >
                  <TableCell sx={bodyCellSx}>
                    <Typography variant="body2" fontWeight={selected ? 600 : 500}>
                      {row.label}
                    </Typography>
                  </TableCell>
                  <TableCell sx={bodyCellSx} align="right">
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
            })}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
}

export default AuthorCombinationTable;
