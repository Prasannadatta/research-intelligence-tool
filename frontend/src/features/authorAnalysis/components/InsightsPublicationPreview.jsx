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

function InsightsPublicationPreview({
  publications = [],
  combinationLabel,
  onBack,
}) {
  return (
    <Paper
      elevation={0}
      data-testid="insights-publication-preview"
      sx={{
        mb: 2,
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
          pb: 1.5,
          display: "flex",
          flexWrap: "wrap",
          gap: 1,
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <Box>
          <Typography variant="subtitle1" fontWeight={600}>
            Publication preview
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Mock results for {combinationLabel || "selected combination"}
          </Typography>
        </Box>
        <Button
          variant="contained"
          color="inherit"
          disableElevation
          onClick={onBack}
          sx={{ textTransform: "none", borderRadius: 999 }}
        >
          Back to Publications
        </Button>
      </Box>

      <TableContainer sx={{ overflowX: "auto" }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell sx={headerCellSx}>Title</TableCell>
              <TableCell sx={headerCellSx}>Authors</TableCell>
              <TableCell sx={headerCellSx}>Year</TableCell>
              <TableCell sx={headerCellSx}>Journal / Venue</TableCell>
              <TableCell sx={headerCellSx} align="right">
                Citations
              </TableCell>
              <TableCell sx={headerCellSx}>Institutions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {publications.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} sx={{ py: 4, textAlign: "center" }}>
                  <Typography color="text.secondary" variant="body2">
                    No mock publications for this combination.
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              publications.map((work) => (
                <TableRow key={work.id} hover>
                  <TableCell sx={{ ...bodyCellSx, minWidth: 220 }}>
                    <Typography variant="body2" fontWeight={600}>
                      {work.title}
                    </Typography>
                  </TableCell>
                  <TableCell sx={{ ...bodyCellSx, minWidth: 180 }}>
                    {(work.authors || []).join(", ")}
                  </TableCell>
                  <TableCell sx={bodyCellSx}>{work.year}</TableCell>
                  <TableCell sx={{ ...bodyCellSx, minWidth: 160 }}>{work.venue}</TableCell>
                  <TableCell sx={bodyCellSx} align="right">
                    {(work.citations || 0).toLocaleString()}
                  </TableCell>
                  <TableCell sx={{ ...bodyCellSx, minWidth: 160 }}>
                    {(work.institutions || []).join(", ")}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
}

export default InsightsPublicationPreview;
