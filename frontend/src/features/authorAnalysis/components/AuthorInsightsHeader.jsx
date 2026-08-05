import { Box, Button, Chip, Typography } from "@mui/material";
import ArrowBackRoundedIcon from "@mui/icons-material/ArrowBackRounded";

function AuthorInsightsHeader({ authorNames = [], onBack }) {
  return (
    <Box sx={{ mb: 2.5 }} data-testid="author-insights-header">
      <Box
        sx={{
          display: "flex",
          flexDirection: { xs: "column", sm: "row" },
          gap: 1.5,
          alignItems: { xs: "flex-start", sm: "center" },
          justifyContent: "space-between",
          mb: 1.5,
        }}
      >
        <Box
          sx={{
            display: "flex",
            flexWrap: "wrap",
            gap: 1,
            alignItems: "center",
            minWidth: 0,
          }}
        >
          <Typography variant="h4" component="h1" fontWeight={600}>
            Author Collaboration Analysis
          </Typography>
          <Chip
            size="small"
            label="Demo data"
            color="warning"
            variant="outlined"
            data-testid="demo-data-badge"
            sx={{ fontWeight: 600 }}
          />
        </Box>

        <Button
          startIcon={<ArrowBackRoundedIcon />}
          onClick={onBack}
          sx={{ textTransform: "none", color: "text.secondary" }}
        >
          Back to Publications
        </Button>
      </Box>

      <Box
        sx={{ display: "flex", flexWrap: "wrap", gap: 0.75, alignItems: "center" }}
        data-testid="selected-author-chips"
      >
        <Typography variant="body2" color="text.secondary" sx={{ mr: 0.5 }}>
          Selected authors
        </Typography>
        {authorNames.map((name) => (
          <Chip key={name} size="small" label={name} />
        ))}
      </Box>
    </Box>
  );
}

export default AuthorInsightsHeader;
