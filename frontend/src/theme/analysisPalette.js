import { createTheme } from "@mui/material/styles";

export const analysisPalette = {
  light: {
    navy: "#2f5d86",
    teal: "#2a8f84",
    indigo: "#4f63a8",
    coral: "#c57a6e",
    amber: "#b47d1f",
    sage: "#4f8a5c",
    slate: "#4d6d88",
    navySoft: "#e4eef7",
    tealSoft: "#def3f0",
    indigoSoft: "#e8ecf8",
    coralSoft: "#f8ebe8",
    amberSoft: "#f8eed8",
    sageSoft: "#e5f2e8",
    slateSoft: "#e7eef4",
  },
  dark: {
    navy: "#8fb4d6",
    teal: "#6ec4b8",
    indigo: "#a8b4e6",
    coral: "#e09a90",
    amber: "#d4b05a",
    sage: "#8fbe97",
    slate: "#9ab0c4",
    navySoft: "rgba(143, 180, 214, 0.18)",
    tealSoft: "rgba(110, 196, 184, 0.18)",
    indigoSoft: "rgba(168, 180, 230, 0.18)",
    coralSoft: "rgba(224, 154, 144, 0.16)",
    amberSoft: "rgba(212, 176, 90, 0.18)",
    sageSoft: "rgba(143, 190, 151, 0.18)",
    slateSoft: "rgba(154, 176, 196, 0.16)",
  },
};

export function getAnalysisPalette(theme) {
  const mode = theme?.palette?.mode === "dark" ? "dark" : "light";
  return theme?.palette?.analysis || analysisPalette[mode];
}

export function getAnalysisChartPalette(theme) {
  const accents = getAnalysisPalette(theme);
  return [
    accents.navy,
    accents.teal,
    accents.indigo,
    accents.coral,
    accents.amber,
    accents.sage,
    accents.slate,
  ];
}

export const INSIGHTS_ACCENTS = {
  authorCollaborations: "navy",
  collaborationByYear: "teal",
  participation: "sage",
  citationActivity: "amber",
  institutionNetwork: "indigo",
  combinationSummary: "navy",
  institutionPartnerships: "teal",
  topJournals: "indigo",
};

function hexToRgb(hex) {
  const value = String(hex || "").replace("#", "");
  if (value.length !== 6) {
    return null;
  }
  return [
    Number.parseInt(value.slice(0, 2), 16),
    Number.parseInt(value.slice(2, 4), 16),
    Number.parseInt(value.slice(4, 6), 16),
  ];
}

function rgbToHex([r, g, b]) {
  return `#${[r, g, b]
    .map((channel) => Math.round(channel).toString(16).padStart(2, "0"))
    .join("")}`;
}

export function mixHex(from, to, amount) {
  const start = hexToRgb(from);
  const end = hexToRgb(to);
  if (!start || !end) {
    return from;
  }
  const t = Math.max(0, Math.min(1, amount));
  return rgbToHex(start.map((channel, index) => channel + (end[index] - channel) * t));
}

export function getInsightsAccent(theme, component) {
  const palette = getAnalysisPalette(theme);
  const key = INSIGHTS_ACCENTS[component] || "navy";
  const main = palette[key];
  const soft = palette[`${key}Soft`];
  const isDark = theme?.palette?.mode === "dark";
  const strong = mixHex(main, isDark ? "#f4f7fb" : "#163044", isDark ? 0.12 : 0.22);
  const muted = mixHex(main, isDark ? "#1a2433" : "#ffffff", isDark ? 0.18 : 0.22);
  return { key, main, soft, strong, muted };
}

export function insightsCategoryColors(theme, component, count = 3) {
  const { main, strong, muted } = getInsightsAccent(theme, component);
  const size = Math.max(1, count);
  if (size === 1) {
    return [main];
  }
  const stops = [muted, main, strong];
  return Array.from({ length: size }, (_, index) => {
    const position = (index / (size - 1)) * (stops.length - 1);
    const stop = Math.min(stops.length - 2, Math.floor(position));
    return mixHex(stops[stop], stops[stop + 1], position - stop);
  });
}

export function createAppTheme() {
  return createTheme({
    colorSchemes: {
      light: {
        palette: {
          analysis: analysisPalette.light,
        },
      },
      dark: {
        palette: {
          analysis: analysisPalette.dark,
        },
      },
    },
    typography: {
      fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
    },
    shape: {
      borderRadius: 14,
    },
  });
}
