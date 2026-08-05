import { useMemo } from "react";
import Chart from "react-apexcharts";
import { Alert, Box, Paper, Skeleton, Typography, useTheme } from "@mui/material";

const CHART_HEIGHT = 300;

function chartTitleForMode(mode) {
  return mode === "common_publications"
    ? "Common publications over time"
    : "Publications over time";
}

function AuthorPublicationTrendChart({ timeline, loading, mode, error, title }) {
  const theme = useTheme();

  const chartTitle = title || chartTitleForMode(mode);

  const { series, options } = useMemo(() => {
    const items = Array.isArray(timeline?.items) ? timeline.items : [];
    const labels = items.map((item) => item.label);
    const counts = items.map((item) => item.count ?? 0);

    const primary = theme.palette.primary.main;
    const textPrimary = theme.palette.text.primary;
    const textSecondary = theme.palette.text.secondary;
    const divider = theme.palette.divider;
    const background = theme.palette.background.paper;

    const chartOptions = {
      chart: {
        type: "bar",
        toolbar: { show: false },
        zoom: { enabled: false },
        background: "transparent",
        fontFamily: theme.typography.fontFamily,
      },
      plotOptions: {
        bar: {
          borderRadius: 4,
          columnWidth: "62%",
        },
      },
      colors: [primary],
      dataLabels: { enabled: false },
      grid: {
        borderColor: divider,
        strokeDashArray: 3,
        xaxis: { lines: { show: false } },
      },
      xaxis: {
        categories: labels,
        labels: {
          style: { colors: textSecondary, fontSize: "11px" },
          rotate: labels.length > 8 ? -45 : 0,
          rotateAlways: labels.length > 8,
          hideOverlappingLabels: true,
        },
        axisBorder: { show: true, color: divider },
        axisTicks: { show: true, color: divider },
        tooltip: { enabled: false },
      },
      yaxis: {
        labels: {
          style: { colors: textSecondary, fontSize: "11px" },
          formatter: (value) => Math.round(value),
        },
        title: {
          text: "Publications",
          style: { color: textSecondary, fontSize: "12px", fontWeight: 500 },
        },
        min: 0,
        forceNiceScale: true,
      },
      tooltip: {
        theme: theme.palette.mode === "dark" ? "dark" : "light",
        x: { show: true },
        y: {
          formatter: (value) => `${value} publication${value === 1 ? "" : "s"}`,
          title: { formatter: () => "Count" },
        },
      },
      theme: { mode: theme.palette.mode },
      legend: { show: false },
      states: {
        hover: { filter: { type: "lighten", value: 0.08 } },
      },
      noData: {
        text: "No publication timeline available",
        align: "center",
        verticalAlign: "middle",
        style: { color: textSecondary, fontSize: "14px" },
      },
    };

    return {
      series: [{ name: "Publications", data: counts }],
      options: chartOptions,
    };
  }, [timeline, theme]);

  const hasTimelineData = Array.isArray(timeline?.items) && timeline.items.length > 0;
  const totalDated = timeline?.total_dated_publications;
  const totalMatching = timeline?.total_matching_publications;
  const showDateCaption =
    hasTimelineData &&
    typeof totalDated === "number" &&
    typeof totalMatching === "number" &&
    totalMatching > 0;

  return (
    <Paper
      elevation={0}
      sx={{
        width: "100%",
        mb: 2.5,
        border: "1px solid",
        borderColor: "divider",
        borderRadius: "18px",
        overflow: "hidden",
        bgcolor: "background.paper",
      }}
    >
      <Box sx={{ px: { xs: 2, sm: 2.5 }, pt: 2, pb: hasTimelineData && !loading && !error ? 0.5 : 2 }}>
        <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 0.5 }}>
          {chartTitle}
        </Typography>
        {showDateCaption ? (
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
            {totalDated} of {totalMatching} publication{totalMatching === 1 ? "" : "s"} have
            usable date metadata
          </Typography>
        ) : null}
        {error ? (
          <Alert severity="error" sx={{ mt: 1.5, mb: 0 }}>
            {error}
          </Alert>
        ) : null}
        {loading ? (
          <Skeleton
            variant="rounded"
            height={CHART_HEIGHT}
            sx={{ mt: 1.5, borderRadius: 2 }}
            aria-label="Loading publication trends chart"
          />
        ) : null}
        {!loading && !error && !hasTimelineData ? (
          <Typography
            color="text.secondary"
            variant="body2"
            sx={{ mt: 2, py: 6, textAlign: "center" }}
          >
            No publication timeline available
          </Typography>
        ) : null}
        {!loading && !error && hasTimelineData ? (
          <Box
            sx={{ width: "100%", height: CHART_HEIGHT, mt: 0.5 }}
            data-testid="author-publication-trend-chart"
            data-chart-mode={mode}
            data-chart-interval={timeline.interval}
          >
            <Chart
              type="bar"
              height={CHART_HEIGHT}
              width="100%"
              series={series}
              options={options}
            />
          </Box>
        ) : null}
      </Box>
    </Paper>
  );
}

export default AuthorPublicationTrendChart;
