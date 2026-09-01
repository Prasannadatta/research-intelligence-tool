import { useMemo, useState } from "react";
import Chart from "react-apexcharts";
import { Box, Button, Paper, Typography, useTheme } from "@mui/material";
import { insightsCategoryColors } from "../../../theme/analysisPalette";
import InsightsViewAllDialog from "./InsightsViewAllDialog";

const CHART_HEIGHT = 236;
const INSTITUTION_DONUT_HEIGHT = 210;
const INSTITUTION_LEGEND_LIMIT = 7;
const chartTitleSx = { mb: 0.5, fontSize: "0.98rem", fontWeight: 600 };
const chartDescriptionSx = { mt: 1, mb: 0, fontSize: "0.85rem", fontWeight: 400 };

export function summarizeInstitutionLegend(rows = [], limit = INSTITUTION_LEGEND_LIMIT) {
  const ranked = [...rows].sort(
    (left, right) =>
      (right.value || 0) - (left.value || 0) ||
      String(left.label || "").localeCompare(String(right.label || "")),
  );
  if (ranked.length <= limit + 1) {
    return { items: ranked, other: null, hidden: [] };
  }
  const items = ranked.slice(0, limit);
  const hidden = ranked.slice(limit);
  return {
    items,
    hidden,
    other: {
      label: "Other",
      value: hidden.reduce((sum, row) => sum + (row.value || 0), 0),
      categoryCount: hidden.length,
    },
  };
}

function buildDonutOptions(theme, labels, colors, { showLegend = true, series = [] } = {}) {
  const total = series.reduce((sum, value) => sum + (Number(value) || 0), 0);
  return {
    chart: {
      type: "donut",
      background: "transparent",
      fontFamily: theme.typography.fontFamily,
      parentHeightOffset: 0,
      offsetY: 0,
      sparkline: { enabled: false },
    },
    labels,
    legend: showLegend
      ? {
          position: "bottom",
          horizontalAlign: "center",
          fontSize: "12px",
          markers: { size: 6 },
          itemMargin: { horizontal: 10, vertical: 0 },
          labels: { colors: theme.palette.text.secondary },
        }
      : { show: false },
    dataLabels: { enabled: false },
    stroke: { width: 0 },
    colors,
    tooltip: {
      theme: theme.palette.mode === "dark" ? "dark" : "light",
      y: {
        formatter: (value) => {
          const amount = Number(value) || 0;
          const percent = total > 0 ? ((amount / total) * 100).toFixed(1) : "0.0";
          return `${amount.toLocaleString()} papers (${percent}%)`;
        },
      },
    },
    theme: { mode: theme.palette.mode },
    plotOptions: {
      pie: {
        offsetY: showLegend ? 4 : 0,
        donut: { size: showLegend ? "62%" : "60%" },
      },
    },
  };
}

function DonutCard({ title, series, options, footer, height = CHART_HEIGHT }) {
  return (
    <Paper
      elevation={0}
      sx={{
        border: "1px solid",
        borderColor: "divider",
        borderRadius: "18px",
        bgcolor: "background.paper",
        p: { xs: 2, sm: 2.5 },
        height: "100%",
        minWidth: 0,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <Typography variant="subtitle2" sx={chartTitleSx}>
        {title}
      </Typography>
      <Box
        sx={{
          flex: 1,
          minHeight: height,
          height,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Box sx={{ width: "100%", height, maxWidth: 360 }}>
          <Chart type="donut" height={height} width="100%" series={series} options={options} />
        </Box>
      </Box>
      <Typography variant="body2" color="text.secondary" sx={chartDescriptionSx}>
        {footer}
      </Typography>
    </Paper>
  );
}

function CompactInstitutionLegend({ items, other, colorsByLabel, onViewAll }) {
  return (
    <Box data-testid="institution-participation-legend" sx={{ mt: 0.5, flexShrink: 0 }}>
      <Box
        sx={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          gap: 0.75,
          rowGap: 0.5,
        }}
      >
        {items.map((row) => (
          <Box
            key={row.label}
            sx={{
              display: "inline-flex",
              alignItems: "center",
              gap: 0.5,
              maxWidth: "100%",
            }}
          >
            <Box
              aria-hidden
              sx={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                bgcolor: colorsByLabel[row.label] || "text.disabled",
                flexShrink: 0,
              }}
            />
            <Typography
              variant="caption"
              color="text.secondary"
              noWrap
              sx={{ fontSize: "0.72rem", lineHeight: 1.2 }}
            >
              {row.label}
            </Typography>
          </Box>
        ))}
        {other ? (
          <Box sx={{ display: "inline-flex", alignItems: "center", gap: 0.5 }}>
            <Box
              aria-hidden
              sx={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                bgcolor: "text.disabled",
                flexShrink: 0,
              }}
            />
            <Typography variant="caption" color="text.secondary" sx={{ fontSize: "0.72rem", lineHeight: 1.2 }}>
              Other ({other.categoryCount})
            </Typography>
          </Box>
        ) : null}
      </Box>
      {onViewAll ? (
        <Box sx={{ display: "flex", justifyContent: "center", mt: 0.25 }}>
          <Button
            size="small"
            onClick={onViewAll}
            sx={{ textTransform: "none", minWidth: 0, py: 0, fontSize: "0.75rem" }}
            data-testid="institution-participation-view-all"
          >
            View all categories
          </Button>
        </Box>
      ) : null}
    </Box>
  );
}

function InstitutionParticipationCard({ rows, footer, theme }) {
  const [viewAllOpen, setViewAllOpen] = useState(false);
  const series = rows.map((row) => row.value);
  const labels = rows.map((row) => row.label);
  const colors = insightsCategoryColors(theme, "participation", labels.length || 4);
  const colorsByLabel = Object.fromEntries(labels.map((label, index) => [label, colors[index]]));
  const legend = summarizeInstitutionLegend(rows);
  const options = useMemo(
    () =>
      buildDonutOptions(theme, labels, colors, {
        showLegend: false,
        series,
      }),
    [colors, labels, series, theme],
  );

  return (
    <Paper
      elevation={0}
      data-testid="institution-participation-card"
      sx={{
        border: "1px solid",
        borderColor: "divider",
        borderRadius: "18px",
        bgcolor: "background.paper",
        p: { xs: 2, sm: 2.5 },
        height: "100%",
        minWidth: 0,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <Typography variant="subtitle2" sx={chartTitleSx}>
        Institution participation
      </Typography>
      <Box
        sx={{
          flex: 1,
          minHeight: INSTITUTION_DONUT_HEIGHT,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Box sx={{ width: "100%", height: INSTITUTION_DONUT_HEIGHT, maxWidth: 340 }}>
          <Chart
            type="donut"
            height={INSTITUTION_DONUT_HEIGHT}
            width="100%"
            series={series}
            options={options}
          />
        </Box>
      </Box>
      <CompactInstitutionLegend
        items={legend.items}
        other={legend.other}
        colorsByLabel={colorsByLabel}
        onViewAll={legend.other ? () => setViewAllOpen(true) : null}
      />
      <Typography variant="body2" color="text.secondary" sx={chartDescriptionSx}>
        {footer}
      </Typography>
      <InsightsViewAllDialog
        open={viewAllOpen}
        onClose={() => setViewAllOpen(false)}
        title="Institution participation categories"
        maxWidth="sm"
        data-testid="institution-participation-view-all-dialog"
      >
        <Box sx={{ px: 2.5, py: 1.5 }}>
          {rows.map((row) => (
            <Box
              key={row.label}
              sx={{
                display: "flex",
                justifyContent: "space-between",
                gap: 2,
                py: 0.75,
                borderBottom: "1px solid",
                borderColor: "divider",
              }}
            >
              <Typography variant="body2">{row.label}</Typography>
              <Typography variant="body2" fontWeight={600}>
                {(row.value || 0).toLocaleString()}
              </Typography>
            </Box>
          ))}
        </Box>
      </InsightsViewAllDialog>
    </Paper>
  );
}

function ParticipationDonuts({ participation }) {
  const theme = useTheme();
  const authorSeries = (participation?.selectedAuthors || []).map((row) => row.value);
  const authorLabels = (participation?.selectedAuthors || []).map((row) => row.label);
  const institutionRows = participation?.institutions || [];

  const authorOptions = useMemo(
    () =>
      buildDonutOptions(
        theme,
        authorLabels,
        insightsCategoryColors(theme, "participation", authorLabels.length || 3),
        { showLegend: true, series: authorSeries },
      ),
    [authorLabels, authorSeries, theme],
  );

  return (
    <Box
      data-testid="participation-donuts"
      sx={{
        display: "grid",
        gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
        gap: { xs: 2, md: 2.5 },
        mb: 0,
        alignItems: "stretch",
        width: "100%",
      }}
    >
      <DonutCard
        title="Selected-author participation"
        series={authorSeries}
        options={authorOptions}
        footer={`${(participation?.sharedByTwoOrMoreAuthors || 0).toLocaleString()} papers involve 2+ selected authors.`}
      />
      <InstitutionParticipationCard
        rows={institutionRows}
        theme={theme}
        footer={`${(participation?.multiInstitutionPapers || 0).toLocaleString()} papers involve 2+ institutions.`}
      />
    </Box>
  );
}

export default ParticipationDonuts;
