import { useMemo } from "react";
import Chart from "react-apexcharts";
import { Box, Paper, Typography, useTheme } from "@mui/material";

const CHART_HEIGHT = 240;

function AuthorCombinationChart({ combinations = [], selectedId, onSelect }) {
  const theme = useTheme();

  const ranked = useMemo(
    () =>
      [...combinations].sort(
        (a, b) => (b.sharedPublications || 0) - (a.sharedPublications || 0),
      ),
    [combinations],
  );

  const { series, options } = useMemo(() => {
    const labels = ranked.map((row) => row.label);
    const values = ranked.map((row) => row.sharedPublications || 0);
    const colors = ranked.map((row) =>
      row.id === selectedId ? theme.palette.primary.main : theme.palette.text.secondary,
    );

    return {
      series: [{ name: "Shared publications", data: values }],
      options: {
        chart: {
          type: "bar",
          toolbar: { show: false },
          background: "transparent",
          fontFamily: theme.typography.fontFamily,
          events: {
            dataPointSelection: (_event, _ctx, config) => {
              const row = ranked[config.dataPointIndex];
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
            barHeight: "62%",
            distributed: true,
          },
        },
        colors,
        dataLabels: { enabled: false },
        legend: { show: false },
        grid: {
          borderColor: theme.palette.divider,
          strokeDashArray: 3,
          yaxis: { lines: { show: false } },
        },
        xaxis: {
          categories: labels,
          labels: {
            style: { colors: theme.palette.text.secondary, fontSize: "11px" },
          },
        },
        yaxis: {
          labels: {
            style: { colors: theme.palette.text.secondary, fontSize: "11px" },
            maxWidth: 240,
          },
        },
        tooltip: {
          theme: theme.palette.mode === "dark" ? "dark" : "light",
          y: {
            formatter: (value) => `${value} shared publication${value === 1 ? "" : "s"}`,
          },
        },
        theme: { mode: theme.palette.mode },
      },
    };
  }, [onSelect, ranked, selectedId, theme]);

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
        mb: 2,
      }}
    >
      <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 0.5 }}>
        Author collaboration combinations
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        Shared publication counts for pairs and the full selected set.
      </Typography>
      <Box sx={{ width: "100%", height: CHART_HEIGHT }}>
        <Chart type="bar" height={CHART_HEIGHT} width="100%" series={series} options={options} />
      </Box>
    </Paper>
  );
}

export default AuthorCombinationChart;
