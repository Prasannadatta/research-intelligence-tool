import { useMemo } from "react";
import Chart from "react-apexcharts";
import { Box, Paper, Typography, useTheme } from "@mui/material";

const CHART_HEIGHT = 250;

function buildDonutOptions(theme, labels) {
  return {
    chart: {
      type: "donut",
      background: "transparent",
      fontFamily: theme.typography.fontFamily,
    },
    labels,
    legend: {
      position: "bottom",
      labels: { colors: theme.palette.text.secondary },
    },
    dataLabels: { enabled: false },
    stroke: { width: 0 },
    colors: [
      theme.palette.primary.main,
      theme.palette.text.secondary,
      theme.palette.success?.main || "#2e7d32",
    ],
    tooltip: {
      theme: theme.palette.mode === "dark" ? "dark" : "light",
    },
    theme: { mode: theme.palette.mode },
    plotOptions: {
      pie: {
        donut: { size: "68%" },
      },
    },
  };
}

function ParticipationDonuts({ participation }) {
  const theme = useTheme();
  const authorSeries = (participation?.selectedAuthors || []).map((row) => row.value);
  const authorLabels = (participation?.selectedAuthors || []).map((row) => row.label);
  const institutionSeries = (participation?.institutions || []).map((row) => row.value);
  const institutionLabels = (participation?.institutions || []).map((row) => row.label);

  const authorOptions = useMemo(
    () => buildDonutOptions(theme, authorLabels),
    [authorLabels, theme],
  );
  const institutionOptions = useMemo(
    () => buildDonutOptions(theme, institutionLabels),
    [institutionLabels, theme],
  );

  return (
    <Box
      data-testid="participation-donuts"
      sx={{
        display: "grid",
        gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" },
        gap: 2,
        mb: 2.5,
      }}
    >
      <Paper
        elevation={0}
        sx={{
          border: "1px solid",
          borderColor: "divider",
          borderRadius: "18px",
          bgcolor: "background.paper",
          p: { xs: 2, sm: 2.5 },
        }}
      >
        <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 0.5 }}>
          Selected-author participation
        </Typography>
        <Box sx={{ height: CHART_HEIGHT }}>
          <Chart
            type="donut"
            height={CHART_HEIGHT}
            width="100%"
            series={authorSeries}
            options={authorOptions}
          />
        </Box>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          {(participation?.sharedByTwoOrMoreAuthors || 0).toLocaleString()} papers involve 2+
          selected authors.
        </Typography>
      </Paper>

      <Paper
        elevation={0}
        sx={{
          border: "1px solid",
          borderColor: "divider",
          borderRadius: "18px",
          bgcolor: "background.paper",
          p: { xs: 2, sm: 2.5 },
        }}
      >
        <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 0.5 }}>
          Institution participation
        </Typography>
        <Box sx={{ height: CHART_HEIGHT }}>
          <Chart
            type="donut"
            height={CHART_HEIGHT}
            width="100%"
            series={institutionSeries}
            options={institutionOptions}
          />
        </Box>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          {(participation?.multiInstitutionPapers || 0).toLocaleString()} papers involve 2+
          institutions.
        </Typography>
      </Paper>
    </Box>
  );
}

export default ParticipationDonuts;
