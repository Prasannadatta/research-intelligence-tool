import { Box, Paper, Typography } from "@mui/material";

const METRIC_ITEMS = [
  {
    key: "totalUniquePublications",
    label: "Total unique publications",
    percentKey: null,
  },
  {
    key: "sharedByTwoOrMore",
    label: "Publications with 2+ selected authors",
    percentKey: "sharedByTwoOrMorePercent",
  },
  {
    key: "sharedByAll",
    label: "Shared by all selected authors",
    percentKey: "sharedByAllPercent",
  },
  {
    key: "multiInstitutionPublications",
    label: "Multi-institution publications",
    percentKey: "multiInstitutionPercent",
  },
];

function InsightsMetricCards({ metrics }) {
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
        mb: 2.5,
      }}
    >
      {METRIC_ITEMS.map((item) => {
        const value = metrics?.[item.key];
        const percent = item.percentKey ? metrics?.[item.percentKey] : null;
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
            <Typography variant="h5" fontWeight={700} sx={{ lineHeight: 1.2 }}>
              {value == null ? "—" : Number(value).toLocaleString()}
            </Typography>
            {percent != null ? (
              <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: "block" }}>
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
