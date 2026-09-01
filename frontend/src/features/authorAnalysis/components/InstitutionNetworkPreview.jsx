import { memo, useCallback, useMemo, useState } from "react";
import {
  Box,
  Button,
  Paper,
  Typography,
  useTheme,
} from "@mui/material";
import { getInsightsAccent } from "../../../theme/analysisPalette";
import InsightsViewAllDialog from "./InsightsViewAllDialog";
import {
  NETWORK_VIEW,
  allNetworkViewOptions,
  hoverLabelsForView,
  lookupLatentEdge,
  prepareInstitutionNetworkView,
  topNetworkViewOptions,
} from "./institutionNetworkLayout";

const EMPTY_ROWS = [];
const EMPTY_EDGES = [];
const chartTitleSx = { mb: 0.5, fontSize: "0.98rem", fontWeight: 600 };
const chartDescriptionSx = { mb: 1, fontSize: "0.85rem", fontWeight: 400 };
const tooltipLineSx = { display: "block", lineHeight: 1.35, fontSize: "0.72rem" };
const svgStyle = { display: "block", maxWidth: "100%", maxHeight: "100%" };
const tooltipBoxSx = {
  position: "absolute",
  left: 12,
  bottom: 12,
  px: 1.1,
  py: 0.65,
  borderRadius: "8px",
  bgcolor: "background.paper",
  border: "1px solid",
  borderColor: "divider",
  maxWidth: "70%",
};

function cssEscape(value) {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
    return CSS.escape(String(value));
  }
  return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

function readNetworkHover(event) {
  const target = event.target;
  if (!(target instanceof Element)) {
    return null;
  }
  const nodeEl = target.closest("[data-network-node]");
  if (nodeEl) {
    return { type: "node", id: nodeEl.getAttribute("data-network-node") };
  }
  const edgeEl = target.closest("[data-network-edge]");
  if (edgeEl) {
    return {
      type: "edge",
      source: edgeEl.getAttribute("data-source"),
      target: edgeEl.getAttribute("data-target"),
    };
  }
  return null;
}

const StaticNetworkLayer = memo(function StaticNetworkLayer({
  view,
  theme,
  testIdPrefix,
  onEnter,
  onLeave,
}) {
  const scale = view.labelScale || 1;
  return (
    <g className="inst-static">
      {view.visibleEdges.map((edge) => (
        <path
          key={edge.key}
          className="inst-edge"
          data-network-edge=""
          data-source={edge.source}
          data-target={edge.target}
          data-testid={`${testIdPrefix}institution-edge-${edge.source}-${edge.target}`}
          data-shared-publications={edge.sharedPublications}
          d={edge.d}
          fill="none"
          stroke={edge.stroke}
          opacity={edge.opacity}
          strokeWidth={edge.width}
          onMouseEnter={onEnter}
          onMouseLeave={onLeave}
        />
      ))}
      {view.baseLabels.map((label) =>
        label.leader ? (
          <line
            key={`leader-${label.id}`}
            className="inst-leader"
            data-label-id={label.id}
            x1={label.leader.x1}
            y1={label.leader.y1}
            x2={label.leader.x2}
            y2={label.leader.y2}
            stroke={theme.palette.text.secondary}
            strokeWidth="0.35"
            opacity="0.28"
          />
        ) : null,
      )}
      {view.nodes.map((node) => (
        <g key={node.id}>
          <circle
            className="inst-hit"
            data-network-node={node.id}
            data-testid={`${testIdPrefix}institution-node-${node.id}`}
            data-publications={node.publications}
            cx={node.x}
            cy={node.y}
            r={node.hitRadius}
            fill="transparent"
            onMouseEnter={onEnter}
            onMouseLeave={onLeave}
          />
          <circle
            className="inst-node"
            data-id={node.id}
            data-neighbors={node.neighborToken}
            cx={node.x}
            cy={node.y}
            r={node.r || 4}
            fill={node.fill}
            opacity="0.96"
            stroke={theme.palette.background.paper}
            strokeWidth="0.35"
            style={{ pointerEvents: "none" }}
          />
        </g>
      ))}
      {view.baseLabels.map((label) => (
        <text
          key={`label-${label.id}`}
          className="inst-label"
          data-label-id={label.id}
          x={label.x}
          y={label.y}
          textAnchor={label.textAnchor}
          dominantBaseline="middle"
          fontSize={4.2 * scale}
          fontWeight={550}
          fill={theme.palette.text.secondary}
          style={{ pointerEvents: "none" }}
        >
          {label.text}
        </text>
      ))}
    </g>
  );
});

function NetworkHoverStyle({ hover, accents, theme }) {
  const rules = [
    ".inst-net-root .inst-edge,.inst-net-root .inst-node,.inst-net-root .inst-label,.inst-net-root .inst-leader{transition:none}",
    ".inst-net-root .inst-hit,.inst-net-root .inst-edge{cursor:pointer}",
  ];
  if (hover?.type === "node") {
    const id = cssEscape(hover.id);
    rules.push(`
      .inst-net-root[data-hover-node] .inst-edge { opacity: 0.05; }
      .inst-net-root[data-hover-node] .inst-edge[data-source="${id}"],
      .inst-net-root[data-hover-node] .inst-edge[data-target="${id}"] {
        opacity: 0.88;
        stroke: ${accents.main};
      }
      .inst-net-root[data-hover-node] .inst-node { opacity: 0.18; }
      .inst-net-root[data-hover-node] .inst-node[data-id="${id}"],
      .inst-net-root[data-hover-node] .inst-node[data-neighbors~="${id}"] { opacity: 0.96; }
      .inst-net-root[data-hover-node] .inst-node[data-id="${id}"] {
        stroke: ${accents.strong};
        stroke-width: 0.85;
        opacity: 1;
      }
      .inst-net-root[data-hover-node] .inst-label[data-label-id="${id}"],
      .inst-net-root[data-hover-node] .inst-leader[data-label-id="${id}"] { display: none; }
    `);
  } else if (hover?.type === "edge") {
    const source = cssEscape(hover.source);
    const target = cssEscape(hover.target);
    rules.push(`
      .inst-net-root[data-hover-edge] .inst-edge { opacity: 0.05; }
      .inst-net-root[data-hover-edge] .inst-edge[data-source="${source}"][data-target="${target}"],
      .inst-net-root[data-hover-edge] .inst-edge[data-source="${target}"][data-target="${source}"] {
        opacity: 0.88;
        stroke: ${accents.main};
      }
      .inst-net-root[data-hover-edge] .inst-node { opacity: 0.18; }
      .inst-net-root[data-hover-edge] .inst-node[data-id="${source}"],
      .inst-net-root[data-hover-edge] .inst-node[data-id="${target}"] { opacity: 0.96; }
    `);
  }
  return <style>{rules.join("\n")}</style>;
}

function HoverLabelLayer({ view, hover, accents, theme }) {
  const labels = useMemo(() => hoverLabelsForView(view, hover), [hover, view]);
  const scale = view.labelScale || 1;
  if (hover?.type !== "node") {
    return null;
  }
  const active = labels.find((label) => label.id === hover.id);
  if (!active) {
    return null;
  }
  return (
    <g className="inst-hover-label" style={{ pointerEvents: "none" }}>
      {active.leader ? (
        <line
          x1={active.leader.x1}
          y1={active.leader.y1}
          x2={active.leader.x2}
          y2={active.leader.y2}
          stroke={theme.palette.text.secondary}
          strokeWidth="0.35"
          opacity="0.7"
        />
      ) : null}
      <text
        x={active.x}
        y={active.y}
        textAnchor={active.textAnchor}
        dominantBaseline="middle"
        fontSize={5.2 * scale}
        fontWeight={700}
        fill={accents.main}
      >
        {active.text}
      </text>
    </g>
  );
}

function ExtraHoverEdges({ view, hover, accents, onEnter, onLeave }) {
  if (hover?.type !== "node") {
    return null;
  }
  const extra = view.extraEdgesByNode[hover.id] || EMPTY_EDGES;
  if (extra.length === 0) {
    return null;
  }
  return (
    <g className="inst-extra-edges">
      {extra.map((edge) => (
        <path
          key={edge.key}
          className="inst-edge"
          data-network-edge=""
          data-source={edge.source}
          data-target={edge.target}
          data-testid={`institution-edge-${edge.source}-${edge.target}`}
          data-shared-publications={edge.sharedPublications}
          d={edge.d}
          fill="none"
          stroke={accents.main}
          opacity="0.88"
          strokeWidth={edge.activeWidth}
          onMouseEnter={onEnter}
          onMouseLeave={onLeave}
        />
      ))}
    </g>
  );
}

function InstitutionNetworkGraph({ view, hover, onHover, theme, testIdPrefix = "" }) {
  const accents = getInsightsAccent(theme, "institutionNetwork");
  const handleEnter = useCallback((event) => {
    const next = readNetworkHover({ target: event.currentTarget });
    if (!next) {
      return;
    }
    onHover((prev) => {
      if (
        prev?.type === next.type &&
        prev?.id === next.id &&
        prev?.source === next.source &&
        prev?.target === next.target
      ) {
        return prev;
      }
      return next;
    });
  }, [onHover]);
  const handleLeave = useCallback(() => onHover(null), [onHover]);

  return (
    <svg
      className="inst-net-root"
      viewBox={`0 0 ${NETWORK_VIEW.width} ${NETWORK_VIEW.height}`}
      width="100%"
      height="100%"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label="Institution collaboration network"
      style={svgStyle}
      data-hover-node={hover?.type === "node" ? hover.id : undefined}
      data-hover-edge={hover?.type === "edge" ? `${hover.source}|${hover.target}` : undefined}
      onMouseLeave={handleLeave}
    >
      <NetworkHoverStyle hover={hover} accents={accents} theme={theme} />
      <circle
        cx={NETWORK_VIEW.cx}
        cy={NETWORK_VIEW.cy}
        r={view.ringRadius}
        fill="none"
        stroke={theme.palette.divider}
        strokeWidth="0.45"
        opacity="0.45"
      />
      <StaticNetworkLayer
        view={view}
        theme={theme}
        testIdPrefix={testIdPrefix}
        onEnter={handleEnter}
        onLeave={handleLeave}
      />
      <ExtraHoverEdges
        view={view}
        hover={hover}
        accents={accents}
        onEnter={handleEnter}
        onLeave={handleLeave}
      />
      <HoverLabelLayer view={view} hover={hover} accents={accents} theme={theme} />
    </svg>
  );
}

function NetworkTooltip({ hover, view, testId = "institution-network-tooltip" }) {
  if (!hover || !view) {
    return null;
  }
  if (hover.type === "node") {
    const node = view.nodeById[hover.id];
    if (!node) {
      return null;
    }
    return (
      <Box data-testid={testId}>
        <Typography variant="caption" sx={{ ...tooltipLineSx, fontWeight: 700, color: "text.primary" }}>
          {node.name}
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={tooltipLineSx}>
          Publications: {(node.publications || 0).toLocaleString()}
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={tooltipLineSx}>
          Partner institutions: {node.partnerCount}
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={tooltipLineSx}>
          Strongest partner: {node.strongestPartnerName || "None"}
        </Typography>
        {node.strongestPartnerName ? (
          <Typography variant="caption" color="text.secondary" sx={tooltipLineSx}>
            Shared publications with strongest partner: {node.strongestPartnerShared}
          </Typography>
        ) : null}
      </Box>
    );
  }
  const edge = lookupLatentEdge(view, hover.source, hover.target);
  if (!edge) {
    return null;
  }
  return (
    <Box data-testid={testId}>
      <Typography variant="caption" sx={{ ...tooltipLineSx, fontWeight: 700, color: "text.primary" }}>
        {view.nodeById[edge.source]?.name || edge.source} × {view.nodeById[edge.target]?.name || edge.target}
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={tooltipLineSx}>
        Shared publications: {(edge.sharedPublications || 0).toLocaleString()}
      </Typography>
    </Box>
  );
}

function NetworkLegend({ testId = "institution-network-legend" }) {
  return (
    <Box
      data-testid={testId}
      sx={{
        position: "absolute",
        right: 10,
        bottom: 10,
        px: 1,
        py: 0.5,
        borderRadius: "8px",
        bgcolor: "background.paper",
        border: "1px solid",
        borderColor: "divider",
        opacity: 0.92,
        pointerEvents: "none",
      }}
    >
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", fontSize: "0.65rem", lineHeight: 1.4 }}>
        Circle size → Publications
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", fontSize: "0.65rem", lineHeight: 1.4 }}>
        Circle shade → Publication volume
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", fontSize: "0.65rem", lineHeight: 1.4 }}>
        Line thickness → Shared publications
      </Typography>
    </Box>
  );
}

function NetworkStage({
  view,
  hover,
  onHover,
  theme,
  testIdPrefix = "",
  tooltipTestId = "institution-network-tooltip",
  legendTestId = "institution-network-legend",
}) {
  return (
    <>
      <InstitutionNetworkGraph
        view={view}
        hover={hover}
        onHover={onHover}
        theme={theme}
        testIdPrefix={testIdPrefix}
      />
      <NetworkLegend testId={legendTestId} />
      {hover ? (
        <Box sx={tooltipBoxSx}>
          <NetworkTooltip hover={hover} view={view} testId={tooltipTestId} />
        </Box>
      ) : null}
    </>
  );
}

function InstitutionNetworkPreview({ network }) {
  const theme = useTheme();
  const nodes = network?.nodes || EMPTY_ROWS;
  const edges = network?.edges || EMPTY_ROWS;
  const [hover, setHover] = useState(null);
  const [dialogHover, setDialogHover] = useState(null);
  const [viewAllOpen, setViewAllOpen] = useState(false);
  const colorMode = theme.palette.mode;

  const topView = useMemo(() => {
    if (nodes.length === 0 || edges.length === 0) {
      return null;
    }
    return prepareInstitutionNetworkView(nodes, edges, topNetworkViewOptions(), theme);
  }, [colorMode, edges, nodes]);

  const allView = useMemo(() => {
    if (!viewAllOpen || nodes.length === 0 || edges.length === 0) {
      return null;
    }
    return prepareInstitutionNetworkView(
      nodes,
      edges,
      allNetworkViewOptions(nodes.length),
      theme,
    );
  }, [colorMode, edges, nodes, viewAllOpen]);

  const empty = !topView;

  return (
    <Paper
      elevation={0}
      data-testid="institution-network-preview"
      sx={{
        border: "1px solid",
        borderColor: "divider",
        borderRadius: "18px",
        bgcolor: "background.paper",
        p: { xs: 2, sm: 2.5 },
        height: "100%",
        minWidth: 0,
        maxWidth: "100%",
        overflow: "hidden",
        boxSizing: "border-box",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <Box
        sx={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 1,
        }}
      >
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="subtitle2" sx={chartTitleSx}>
            Institution network preview
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={chartDescriptionSx}>
            Institutions on a circle; size and shade show publication volume.
          </Typography>
        </Box>
        {!empty ? (
          <Button
            size="small"
            onClick={() => {
              setViewAllOpen(true);
              setHover(null);
            }}
            sx={{ textTransform: "none", flexShrink: 0 }}
            data-testid="institution-network-view-all-button"
          >
            View all
          </Button>
        ) : null}
      </Box>

      <Box
        sx={{
          position: "relative",
          width: "100%",
          height: { xs: 340, sm: 390, lg: 460, xl: 500 },
          maxWidth: "100%",
          bgcolor: "transparent",
          overflow: "hidden",
          boxSizing: "border-box",
        }}
      >
        {empty ? (
          <Box
            sx={{
              height: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              px: 2,
              textAlign: "center",
            }}
          >
            <Typography variant="body2" color="text.secondary">
              No institution collaboration data available
            </Typography>
          </Box>
        ) : (
          <NetworkStage
            view={topView}
            hover={hover}
            onHover={setHover}
            theme={theme}
          />
        )}
      </Box>

      <InsightsViewAllDialog
        open={viewAllOpen}
        onClose={() => {
          setViewAllOpen(false);
          setDialogHover(null);
        }}
        title="Institution network"
        maxWidth="xl"
        paperSx={{
          maxWidth: { xs: "100%", sm: 980, md: 1120 },
          width: "calc(100% - 24px)",
          m: { xs: 1, sm: 2 },
        }}
        contentSx={{
          p: 0,
          overflow: "auto",
        }}
        data-testid="institution-network-view-all-dialog"
      >
        <Box
          sx={{
            position: "relative",
            width: "100%",
            height: { xs: "min(70vh, 560px)", md: "min(78vh, 720px)" },
            minHeight: { xs: 380, md: 520 },
            overflow: "hidden",
            boxSizing: "border-box",
          }}
        >
          {allView ? (
            <NetworkStage
              view={allView}
              hover={dialogHover}
              onHover={setDialogHover}
              theme={theme}
              testIdPrefix="full-"
              tooltipTestId="institution-network-full-tooltip"
              legendTestId="institution-network-full-legend"
            />
          ) : null}
        </Box>
      </InsightsViewAllDialog>
    </Paper>
  );
}

export default InstitutionNetworkPreview;
