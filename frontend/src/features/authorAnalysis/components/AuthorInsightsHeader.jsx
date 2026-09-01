import { Box, Button, Typography } from "@mui/material";
import ArrowBackRoundedIcon from "@mui/icons-material/ArrowBackRounded";

function AuthorInsightsHeader({ onBack }) {
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
          <Typography
            variant="h4"
            component="h1"
            fontWeight={700}
            sx={{
              fontSize: { xs: "1.6rem", sm: "1.95rem", md: "2.125rem" },
              lineHeight: 1.15,
            }}
          >
            Collaboration Insights
          </Typography>
        </Box>

        <Button
          startIcon={<ArrowBackRoundedIcon />}
          onClick={onBack}
          sx={{ textTransform: "none", color: "text.secondary" }}
        >
          Back to Publications
        </Button>
      </Box>
    </Box>
  );
}

export default AuthorInsightsHeader;
