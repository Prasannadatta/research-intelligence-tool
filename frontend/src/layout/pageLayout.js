export const closedDrawerRailWidth = 56;
export const closedDrawerContentGap = 24;
export const closedDrawerContentInset =
  closedDrawerRailWidth + closedDrawerContentGap;

export const analysisPagePaddingLeftVar = "--analysis-page-padding-left";

export const analysisPageLayoutSx = {
  width: "100%",
  maxWidth: "none",
  pl: {
    xs: 2,
    sm: 3,
    md: `var(${analysisPagePaddingLeftVar}, 32px)`,
  },
  pr: { xs: 2, sm: 3, md: 4 },
  pt: { xs: 9, md: 8 },
  pb: 3,
  boxSizing: "border-box",
  textAlign: "left",
};

export const dashboardRowSx = {
  display: "grid",
  gap: { xs: 2, md: 2.5 },
  mb: { xs: 2.5, md: 3 },
  minWidth: 0,
};
