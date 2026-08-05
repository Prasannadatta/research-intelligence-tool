import { useMemo } from "react";
import Chart from "react-apexcharts";
import { Box, Paper, Typography, useTheme } from "@mui/material";

const CHART_HEIGHT = 300;

function CollaborationYearChart({ collaborationByYear }) {
  const theme = useTheme();
  const years = collaborationByYear?.years || [];
  const counts = collaborationByYear?.counts || [];
  const total = collaborationByYear?.total || counts.reduce((sum, value) => sum + value, 0);

  const { series, options } = useMemo(
    () => ({
      series: [{ name: "2+ selected authors", data: counts }],
      options: {
        chart: {
          type: "bar",
          toolbar: { show: false },
          background: "transparent",
          fontFamily: theme.typography.fontFamily,
        },
        plotOptions: {
          bar: {
            borderRadius: 4,
            columnWidth: "58%",
            dataLabels: { position: "top" },
          },
        },
        colors: [theme.palette.primary.main],
        dataLabels: {
          enabled: true,
          offsetY: -18,
          style: {
            fontSize: "11px",
            colors: [theme.palette.text.secondary],
          },
        },
        grid: {
          borderColor: theme.palette.divider,
          strokeDashArray: 3,
          xaxis: { lines: { show: false } },
        },
        xaxis: {
          categories: years,
          title: {
            text: "Year",
            style: {
              color: theme.palette.text.secondary,
              fontSize: "12px",
              fontWeight: 500,
            },
          },
          labels: {
            style: { colors: theme.palette.text.secondary, fontSize: "11px" },
          },
          axisBorder: { color: theme.palette.divider },
          axisTicks: { color: theme.palette.divider },
        },
        yaxis: {
          min: 0,
          forceNiceScale: true,
          title: {
            text: "Publications",
            style: {
              color: theme.palette.text.secondary,
              fontSize: "12px",
              fontWeight: 500,
            },
          },
          labels: {
            style: { colors: theme.palette.text.secondary, fontSize: "11px" },
            formatter: (value) => Math.round(value),
          },
        },
        tooltip: {
          theme: theme.palette.mode === "dark" ? "dark" : "light",
          y: {
            formatter: (value) => {
              const percent = total > 0 ? ((value / total) * 100).toFixed(1) : "0.0";
              return `${value} publications (${percent}%)`;
            },
          },
        },
        theme: { mode: theme.palette.mode },
        legend: { show: false },
      },
    }),
    [counts, theme, total, years],
  );

  return (
    <Paper
      elevation={0}
      data-testid="collaboration-year-chart"
      sx={{
        mb: 2.5,
        border: "1px solid",
        borderColor: "divider",
        borderRadius: "18px",
        bgcolor: "background.paper",
        p: { xs: 2, sm: 2.5 },
      }}
    >
      <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 0.5 }}>
        Collaborative publications by year
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        Publications involving two or more selected authors, 2019–2026.
      </Typography>
      <Box sx={{ width: "100%", height: CHART_HEIGHT }}>
        <Chart type="bar" height={CHART_HEIGHT} width="100%" series={series} options={options} />
      </Box>
    </Paper>
  );
}

export default CollaborationYearChart;
