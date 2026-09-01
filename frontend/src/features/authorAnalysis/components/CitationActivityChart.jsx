import { useMemo } from "react";
import Chart from "react-apexcharts";
import { Box, Paper, Typography, useTheme } from "@mui/material";
import { getInsightsAccent } from "../../../theme/analysisPalette";

const CHART_HEIGHT = 280;
const EMPTY_SERIES = [];
const chartTitleSx = { mb: 0.5, fontSize: "0.98rem", fontWeight: 600 };
const chartDescriptionSx = { mb: 1.25, fontSize: "0.85rem", fontWeight: 400 };
const metricLabelSx = { display: "block", lineHeight: 1.35 };
const metricValueSx = { mt: 0.5, lineHeight: 1.3 };

function CitationActivityChart({ citationActivity }) {
  const theme = useTheme();
  const accent = getInsightsAccent(theme, "citationActivity");
  const years = citationActivity?.years || EMPTY_SERIES;
  const citations = citationActivity?.citations || EMPTY_SERIES;
  const cumulative = citationActivity?.cumulative || EMPTY_SERIES;
  const hasCitationData =
    years.length > 0 &&
    (citations.some((value) => Number(value) > 0) ||
      cumulative.some((value) => Number(value) > 0));

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
          parentHeightOffset: 0,
          width: "100%",
        },
        stroke: { width: [0, 2.5], curve: "smooth" },
        plotOptions: {
          bar: { borderRadius: 4, columnWidth: "36%" },
        },
        colors: [accent.main, accent.strong],
        dataLabels: { enabled: false },
        grid: {
          borderColor: theme.palette.divider,
          strokeDashArray: 3,
          padding: { left: 4, right: 8, top: 4, bottom: 0 },
        },
        xaxis: {
          categories: years,
          tickPlacement: "on",
          labels: {
            style: { colors: theme.palette.text.secondary, fontSize: "11px" },
            hideOverlappingLabels: true,
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
    [accent.main, accent.strong, citations, cumulative, theme, years],
  );

  return (
    <Paper
      elevation={0}
      data-testid="citation-activity-chart"
      sx={{
        mb: 0,
        border: "1px solid",
        borderColor: "divider",
        borderRadius: "18px",
        bgcolor: "background.paper",
        p: { xs: 2, sm: 2.5 },
        height: "100%",
        width: "100%",
        minWidth: 0,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <Typography variant="subtitle2" sx={chartTitleSx}>
        Citation activity of selected publications
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={chartDescriptionSx}>
        Yearly and cumulative citation activity for the selected publication set.
      </Typography>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "minmax(0, 1fr)",
            md: "minmax(0, 3.5fr) minmax(188px, 1fr)",
          },
          columnGap: { md: 0 },
          rowGap: { xs: 1.5, md: 0 },
          flex: 1,
          minHeight: { xs: CHART_HEIGHT + 8, md: CHART_HEIGHT },
          alignItems: "stretch",
        }}
      >
        {hasCitationData ? (
          <Box
            sx={{
              minWidth: 0,
              width: "100%",
              height: { xs: CHART_HEIGHT, md: "100%" },
              minHeight: CHART_HEIGHT,
            }}
          >
            <Chart type="line" height={CHART_HEIGHT} width="100%" series={series} options={options} />
          </Box>
        ) : (
          <Box
            sx={{
              minHeight: CHART_HEIGHT,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              border: "1px dashed",
              borderColor: "divider",
              borderRadius: "14px",
            }}
          >
            <Typography variant="body2" color="text.secondary">
              No citation data available
            </Typography>
          </Box>
        )}

        <Box
          sx={{
            minWidth: 0,
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            gap: 2,
            pl: { xs: 0, md: 2.25 },
            ml: { xs: 0, md: 2.25 },
            pt: { xs: 0.5, md: 0 },
            borderTop: { xs: "1px solid", md: "none" },
            borderLeft: { xs: "none", md: "1px solid" },
            borderColor: "divider",
          }}
        >
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="caption" color="text.secondary" fontWeight={600} sx={metricLabelSx}>
              Total citations
            </Typography>
            <Typography variant="body1" fontWeight={700} sx={{ ...metricValueSx, color: accent.main }}>
              {(citationActivity?.totalCitations || 0).toLocaleString()}
            </Typography>
          </Box>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="caption" color="text.secondary" fontWeight={600} sx={metricLabelSx}>
              Average citations per publication
            </Typography>
            <Typography variant="body1" fontWeight={700} sx={{ ...metricValueSx, color: accent.strong }}>
              {Number(citationActivity?.averageCitations || 0).toLocaleString(undefined, {
                minimumFractionDigits: 1,
                maximumFractionDigits: 1,
              })}
            </Typography>
          </Box>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="caption" color="text.secondary" fontWeight={600} sx={metricLabelSx}>
              Most cited shared publication
            </Typography>
            <Typography
              variant="body2"
              fontWeight={600}
              sx={{
                ...metricValueSx,
                color: citationActivity?.mostCitedShared ? accent.main : "text.primary",
                display: "-webkit-box",
                WebkitLineClamp: 4,
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
      </Box>
    </Paper>
  );
}

export default CitationActivityChart;
