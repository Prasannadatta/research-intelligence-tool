import { Box, Paper, Typography, useTheme } from "@mui/material";
import { getAnalysisPalette } from "../../../theme/analysisPalette";

const METRIC_ITEMS = [
  {
    key: "totalUniquePublications",
    label: "Total unique publications",
    percentKey: null,
    accent: "navy",
  },
  {
    key: "sharedByTwoOrMore",
    label: "Publications with 2+ selected authors",
    percentKey: "sharedByTwoOrMorePercent",
    accent: "teal",
  },
  {
    key: "sharedByAll",
    label: "Shared by all selected authors",
    percentKey: "sharedByAllPercent",
    accent: "indigo",
  },
  {
    key: "multiInstitutionPublications",
    label: "Multi-institution publications",
    percentKey: "multiInstitutionPercent",
    accent: "sage",
  },
];

function InsightsMetricCards({ metrics }) {
  const theme = useTheme();
  const accents = getAnalysisPalette(theme);

  return (
    <Box
      data-testid="insights-metric-cards"
      sx={{
        display: "grid",
        gridTemplateColumns: {
          xs: "repeat(2, minmax(0, 1fr))",
          md: "repeat(4, minmax(0, 1fr))",
        },
        gap: 1.5,
        mb: 0,
        alignItems: "stretch",
      }}
    >
      {METRIC_ITEMS.map((item) => {
        const value = metrics?.[item.key];
        const percent = item.percentKey ? metrics?.[item.percentKey] : null;
        const accent = accents[item.accent] || accents.navy;
        return (
          <Paper
            key={item.key}
            elevation={0}
            data-testid={`metric-card-${item.key}`}
            sx={{
              p: 1.75,
              border: "1px solid",
              borderColor: "divider",
              borderRadius: "16px",
              bgcolor: "background.paper",
              minWidth: 0,
              height: "100%",
              display: "flex",
              flexDirection: "column",
            }}
          >
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{
                display: "block",
                mb: 0.75,
                lineHeight: 1.35,
                fontWeight: 600,
              }}
            >
              {item.label}
            </Typography>
            <Typography
              variant="h4"
              fontWeight={700}
              sx={{ lineHeight: 1.1, color: accent, mt: "auto" }}
            >
              {value == null ? "—" : Number(value).toLocaleString()}
            </Typography>
            {percent != null ? (
              <Typography
                variant="caption"
                sx={{
                  mt: 0.75,
                  display: "block",
                  color: "text.secondary",
                  fontWeight: 600,
                }}
              >
                {Number(percent).toLocaleString(undefined, {
                  minimumFractionDigits: 1,
                  maximumFractionDigits: 1,
                })}
                % of unique publications
              </Typography>
            ) : null}
          </Paper>
        );
      })}
    </Box>
  );
}

export default InsightsMetricCards;
