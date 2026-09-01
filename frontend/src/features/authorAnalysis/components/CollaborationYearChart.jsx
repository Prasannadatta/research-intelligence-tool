import { useMemo } from "react";
import Chart from "react-apexcharts";
import { Box, Paper, Typography, useTheme } from "@mui/material";
import { getInsightsAccent } from "../../../theme/analysisPalette";

const chartTitleSx = { mb: 0.5, fontSize: "0.98rem", fontWeight: 600 };
const chartDescriptionSx = { mb: 1.5, fontSize: "0.85rem", fontWeight: 400 };

function CollaborationYearChart({ collaborationByYear }) {
  const theme = useTheme();
  const accent = getInsightsAccent(theme, "collaborationByYear");
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
          parentHeightOffset: 0,
          offsetY: 0,
        },
        plotOptions: {
          bar: {
            borderRadius: 4,
            columnWidth: "48%",
            dataLabels: { position: "top" },
          },
        },
        colors: [accent.main],
        dataLabels: {
          enabled: true,
          offsetY: -16,
          style: {
            fontSize: "11px",
            colors: [accent.strong],
          },
        },
        grid: {
          borderColor: theme.palette.divider,
          strokeDashArray: 3,
          padding: { top: 24, right: 8, bottom: 4, left: 4 },
          xaxis: { lines: { show: false } },
        },
        xaxis: {
          categories: years,
          tickPlacement: "on",
          title: {
            text: "Year",
            offsetY: -2,
            style: {
              color: theme.palette.text.secondary,
              fontSize: "12px",
              fontWeight: 500,
            },
          },
          labels: {
            style: { colors: theme.palette.text.secondary, fontSize: "11px" },
            offsetY: 0,
            hideOverlappingLabels: true,
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
    [accent.main, accent.strong, counts, theme, total, years],
  );

  return (
    <Paper
      elevation={0}
      data-testid="collaboration-year-chart"
      sx={{
        mb: 0,
        border: "1px solid",
        borderColor: "divider",
        borderRadius: "18px",
        bgcolor: "background.paper",
        p: { xs: 2, sm: 2.5 },
        width: "100%",
        flex: 1,
        height: "100%",
        minHeight: 0,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <Typography variant="subtitle2" sx={chartTitleSx}>
        Collaborative publications by year
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={chartDescriptionSx}>
        Publications involving two or more selected authors, 2019–2026.
      </Typography>
      <Box
        sx={{
          flex: 1,
          minHeight: { xs: 240, md: 0 },
          width: "100%",
          position: "relative",
        }}
      >
        <Box sx={{ position: "absolute", inset: 0 }}>
          <Chart type="bar" height="100%" width="100%" series={series} options={options} />
        </Box>
      </Box>
    </Paper>
  );
}

export default CollaborationYearChart;
