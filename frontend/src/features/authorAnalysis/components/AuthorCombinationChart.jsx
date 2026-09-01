import { useMemo, useState } from "react";
import Chart from "react-apexcharts";
import {
  Box,
  Button,
  Paper,
  TableContainer,
  Tooltip,
  Typography,
  useTheme,
} from "@mui/material";
import { getInsightsAccent } from "../../../theme/analysisPalette";
import InsightsViewAllDialog from "./InsightsViewAllDialog";
import {
  CombinationSummaryTable,
  rankCombinations,
} from "./AuthorCombinationTable";

const CHART_HEIGHT = 450;
const CHART_TOP_N = 10;
const chartTitleSx = { mb: 0.5, fontSize: "0.98rem", fontWeight: 600 };
const chartDescriptionSx = { mb: 0, fontSize: "0.85rem", fontWeight: 400 };

function AuthorCombinationChart({ combinations = [], selectedId, onSelect }) {
  const theme = useTheme();
  const accent = getInsightsAccent(theme, "authorCollaborations");
  const [viewAllOpen, setViewAllOpen] = useState(false);

  const ranked = useMemo(() => rankCombinations(combinations), [combinations]);
  const topRows = useMemo(() => ranked.slice(0, CHART_TOP_N), [ranked]);
  const showViewAll = ranked.length > CHART_TOP_N;

  const { series, options } = useMemo(() => {
    const labels = topRows.map((row) => row.label || row.id);
    const values = topRows.map((row) => row.sharedPublications || 0);
    return {
      series: [{ name: "Shared publications", data: values }],
      options: {
        chart: {
          type: "bar",
          toolbar: { show: false },
          background: "transparent",
          fontFamily: theme.typography.fontFamily,
          parentHeightOffset: 0,
          offsetX: 0,
          events: {
            dataPointSelection: (_event, _ctx, config) => {
              const row = topRows[config.dataPointIndex];
              if (row && onSelect) {
                onSelect(row.id);
              }
            },
          },
        },
        plotOptions: {
          bar: {
            horizontal: true,
            borderRadius: 4,
            barHeight: topRows.length >= 8 ? "42%" : topRows.length >= 4 ? "34%" : "22%",
            distributed: false,
            dataLabels: {
              position: "top",
              hideOverflowingLabels: false,
            },
          },
        },
        colors: [accent.main],
        dataLabels: {
          enabled: true,
          formatter: (value) => Number(value || 0).toLocaleString(),
          textAnchor: "start",
          offsetX: 8,
          style: {
            fontSize: "11px",
            fontWeight: 600,
            colors: [theme.palette.text.primary],
          },
        },
        legend: { show: false },
        grid: {
          borderColor: theme.palette.divider,
          strokeDashArray: 3,
          padding: { left: 4, right: 36, top: 8, bottom: 0 },
          xaxis: { lines: { show: true } },
          yaxis: { lines: { show: false } },
        },
        xaxis: {
          categories: labels,
          title: {
            text: "Shared publications",
            style: {
              color: theme.palette.text.secondary,
              fontSize: "12px",
              fontWeight: 500,
            },
          },
          labels: {
            style: { colors: theme.palette.text.secondary, fontSize: "11px" },
            formatter: (value) => Math.round(Number(value) || 0),
          },
        },
        yaxis: {
          labels: {
            show: false,
          },
        },
        tooltip: {
          theme: theme.palette.mode === "dark" ? "dark" : "light",
          x: {
            formatter: (_value, { dataPointIndex }) =>
              topRows[dataPointIndex]?.label || labels[dataPointIndex] || "",
          },
          y: {
            formatter: (value) =>
              `${Number(value || 0).toLocaleString()} shared publication${
                Number(value) === 1 ? "" : "s"
              }`,
          },
        },
        theme: { mode: theme.palette.mode },
      },
    };
  }, [accent.main, onSelect, theme, topRows]);

  return (
    <Paper
      elevation={0}
      data-testid="author-combination-chart"
      sx={{
        border: "1px solid",
        borderColor: "divider",
        borderRadius: "18px",
        bgcolor: "background.paper",
        p: { xs: 2, sm: 2.5 },
        mb: 0,
      }}
    >
      <Box
        sx={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 1,
          mb: 1,
        }}
      >
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="subtitle2" sx={chartTitleSx}>
            Top author collaborations
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={chartDescriptionSx}>
            Ranked by shared publication count
            {ranked.length > CHART_TOP_N
              ? `, showing the top ${CHART_TOP_N} of ${ranked.length}.`
              : "."}
          </Typography>
        </Box>
        {showViewAll ? (
          <Button
            size="small"
            onClick={() => setViewAllOpen(true)}
            sx={{ textTransform: "none", flexShrink: 0 }}
            data-testid="combination-chart-view-all-button"
          >
            View all collaborations
          </Button>
        ) : null}
      </Box>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "minmax(92px, 38%) minmax(0, 1fr)",
            sm: "minmax(160px, 240px) minmax(0, 1fr)",
            md: "minmax(200px, 280px) minmax(0, 1fr)",
          },
          columnGap: { xs: 1, sm: 1.5 },
          width: "100%",
          height: CHART_HEIGHT,
          minWidth: 0,
        }}
      >
        <Box
          data-testid="author-combination-chart-labels"
          sx={{
            display: "flex",
            flexDirection: "column",
            minWidth: 0,
            pt: "8px",
            pb: "52px",
          }}
        >
          {topRows.map((row) => {
            const selected = row.id === selectedId;
            const label = row.label || row.id;
            return (
              <Tooltip key={row.id} title={label} placement="top-start" enterDelay={250}>
                <Box
                  component="button"
                  type="button"
                  onClick={() => onSelect?.(row.id)}
                  data-testid={`combination-chart-label-${row.id}`}
                  sx={{
                    flex: 1,
                    minHeight: 0,
                    minWidth: 0,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "flex-start",
                    width: "100%",
                    m: 0,
                    px: 0,
                    py: 0.25,
                    border: 0,
                    background: "none",
                    cursor: "pointer",
                    textAlign: "left",
                    color: selected ? accent.main : "text.secondary",
                    fontFamily: theme.typography.fontFamily,
                    fontSize: { xs: "0.7rem", sm: "0.75rem" },
                    fontWeight: selected ? 600 : 500,
                    lineHeight: 1.25,
                  }}
                >
                  <Typography
                    component="span"
                    noWrap
                    title={label}
                    sx={{
                      display: "block",
                      width: "100%",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      color: "inherit",
                      fontSize: "inherit",
                      fontWeight: "inherit",
                      lineHeight: "inherit",
                    }}
                  >
                    {label}
                  </Typography>
                </Box>
              </Tooltip>
            );
          })}
        </Box>
        <Box sx={{ minWidth: 0, width: "100%", height: "100%" }}>
          <Chart type="bar" height={CHART_HEIGHT} width="100%" series={series} options={options} />
        </Box>
      </Box>
      <InsightsViewAllDialog
        open={viewAllOpen}
        onClose={() => setViewAllOpen(false)}
        title="All collaborations"
        data-testid="combination-chart-view-all-dialog"
      >
        <TableContainer sx={{ maxHeight: { xs: "64vh", md: "70vh" } }}>
          <CombinationSummaryTable
            combinations={ranked}
            selectedId={selectedId}
            onSelect={onSelect}
            stickyHeader
            rowTestIdPrefix="combination-chart-dialog-row"
          />
        </TableContainer>
      </InsightsViewAllDialog>
    </Paper>
  );
}

export default AuthorCombinationChart;
