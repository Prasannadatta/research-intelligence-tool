import { useMemo } from "react";
import Chart from "react-apexcharts";
import { Box, Paper, Typography, useTheme } from "@mui/material";

const CHART_HEIGHT = 300;

function CitationActivityChart({ citationActivity }) {
  const theme = useTheme();
  const years = citationActivity?.years || [];
  const citations = citationActivity?.citations || [];
  const cumulative = citationActivity?.cumulative || [];

  const { series, options } = useMemo(
    () => ({
      series: [
        { name: "Citations by year", type: "column", data: citations },
        { name: "Cumulative citations", type: "line", data: cumulative },
      ],
      options: {
        chart: {
          type: "line",
          toolbar: { show: false },
          background: "transparent",
          fontFamily: theme.typography.fontFamily,
        },
        stroke: { width: [0, 2.5], curve: "smooth" },
        plotOptions: {
          bar: { borderRadius: 4, columnWidth: "55%" },
        },
        colors: [theme.palette.primary.main, theme.palette.text.secondary],
        dataLabels: { enabled: false },
        grid: {
          borderColor: theme.palette.divider,
          strokeDashArray: 3,
        },
        xaxis: {
          categories: years,
          labels: {
            style: { colors: theme.palette.text.secondary, fontSize: "11px" },
          },
        },
        yaxis: [
          {
            title: {
              text: "Citations",
              style: {
                color: theme.palette.text.secondary,
                fontSize: "12px",
                fontWeight: 500,
              },
            },
            labels: {
              style: { colors: theme.palette.text.secondary, fontSize: "11px" },
            },
          },
          {
            opposite: true,
            title: {
              text: "Cumulative",
              style: {
                color: theme.palette.text.secondary,
                fontSize: "12px",
                fontWeight: 500,
              },
            },
            labels: {
              style: { colors: theme.palette.text.secondary, fontSize: "11px" },
            },
          },
        ],
        legend: {
          position: "top",
          horizontalAlign: "left",
          labels: { colors: theme.palette.text.secondary },
        },
        tooltip: {
          theme: theme.palette.mode === "dark" ? "dark" : "light",
          shared: true,
        },
        theme: { mode: theme.palette.mode },
      },
    }),
    [citations, cumulative, theme, years],
  );

  return (
    <Paper
      elevation={0}
      data-testid="citation-activity-chart"
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
        Citation activity of selected publications
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Yearly and cumulative citation activity for the demonstration set, 2019–2026.
      </Typography>

      <Box sx={{ height: CHART_HEIGHT, mb: 2 }}>
        <Chart type="line" height={CHART_HEIGHT} width="100%" series={series} options={options} />
      </Box>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", sm: "repeat(3, 1fr)" },
          gap: 1.5,
        }}
      >
        <Box sx={{ p: 1.5, borderRadius: "14px", border: "1px solid", borderColor: "divider" }}>
          <Typography variant="caption" color="text.secondary" fontWeight={600}>
            Total citations
          </Typography>
          <Typography variant="body1" fontWeight={700} sx={{ mt: 0.5 }}>
            {(citationActivity?.totalCitations || 0).toLocaleString()}
          </Typography>
        </Box>
        <Box sx={{ p: 1.5, borderRadius: "14px", border: "1px solid", borderColor: "divider" }}>
          <Typography variant="caption" color="text.secondary" fontWeight={600}>
            Average citations per publication
          </Typography>
          <Typography variant="body1" fontWeight={700} sx={{ mt: 0.5 }}>
            {Number(citationActivity?.averageCitations || 0).toLocaleString(undefined, {
              minimumFractionDigits: 1,
              maximumFractionDigits: 1,
            })}
          </Typography>
        </Box>
        <Box sx={{ p: 1.5, borderRadius: "14px", border: "1px solid", borderColor: "divider" }}>
          <Typography variant="caption" color="text.secondary" fontWeight={600}>
            Most cited shared publication
          </Typography>
          <Typography
            variant="body2"
            fontWeight={600}
            sx={{
              mt: 0.5,
              display: "-webkit-box",
              WebkitLineClamp: 2,
              WebkitBoxOrient: "vertical",
              overflow: "hidden",
            }}
          >
            {citationActivity?.mostCitedShared
              ? `${citationActivity.mostCitedShared.citations.toLocaleString()} · ${citationActivity.mostCitedShared.title}`
              : "—"}
          </Typography>
        </Box>
      </Box>
    </Paper>
  );
}

export default CitationActivityChart;
