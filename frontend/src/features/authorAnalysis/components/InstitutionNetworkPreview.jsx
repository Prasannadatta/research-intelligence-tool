import { useMemo, useState } from "react";
import { Box, Paper, Typography, useTheme } from "@mui/material";

function InstitutionNetworkPreview({ network }) {
  const theme = useTheme();
  const nodes = network?.nodes || [];
  const edges = network?.edges || [];
  const [hover, setHover] = useState(null);

  const nodeMap = useMemo(() => {
    const map = {};
    nodes.forEach((node) => {
      map[node.id] = node;
    });
    return map;
  }, [nodes]);

  const hoverText = useMemo(() => {
    if (!hover) {
      return null;
    }
    if (hover.type === "node") {
      const node = nodeMap[hover.id];
      if (!node) {
        return null;
      }
      return `${node.name} · ${node.publications} publications`;
    }
    const edge = edges.find(
      (row) => row.source === hover.source && row.target === hover.target,
    );
    if (!edge) {
      return null;
    }
    const a = nodeMap[edge.source]?.name || edge.source;
    const b = nodeMap[edge.target]?.name || edge.target;
    return `${a} × ${b} · ${edge.sharedPublications} shared publications`;
  }, [edges, hover, nodeMap]);

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
      }}
    >
      <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 0.5 }}>
        Institution network preview
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Nodes are institutions; lines show shared publications.
      </Typography>

      <Box
        sx={{
          position: "relative",
          width: "100%",
          height: 260,
          borderRadius: "14px",
          border: "1px dashed",
          borderColor: "divider",
          bgcolor: "action.hover",
          overflow: "hidden",
        }}
      >
        <svg
          viewBox="0 0 100 100"
          width="100%"
          height="100%"
          role="img"
          aria-label="Institution collaboration network"
        >
          {edges.map((edge) => {
            const source = nodeMap[edge.source];
            const target = nodeMap[edge.target];
            if (!source || !target) {
              return null;
            }
            const active =
              hover?.type === "edge" &&
              hover.source === edge.source &&
              hover.target === edge.target;
            return (
              <line
                key={`${edge.source}-${edge.target}`}
                x1={source.x}
                y1={source.y}
                x2={target.x}
                y2={target.y}
                stroke={active ? theme.palette.text.primary : theme.palette.divider}
                strokeWidth={active ? 1.4 : Math.max(0.6, edge.sharedPublications / 10)}
                style={{ cursor: "pointer" }}
                onMouseEnter={() =>
                  setHover({ type: "edge", source: edge.source, target: edge.target })
                }
                onMouseLeave={() => setHover(null)}
              />
            );
          })}
          {nodes.map((node) => {
            const active = hover?.type === "node" && hover.id === node.id;
            const radius = 3.2 + Math.min(2.5, (node.publications || 0) / 30);
            return (
              <g key={node.id}>
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={radius}
                  fill={active ? theme.palette.text.primary : theme.palette.primary.main}
                  opacity={0.95}
                  style={{ cursor: "pointer" }}
                  onMouseEnter={() => setHover({ type: "node", id: node.id })}
                  onMouseLeave={() => setHover(null)}
                />
                <text
                  x={node.x}
                  y={node.y + radius + 3.5}
                  textAnchor="middle"
                  fontSize="2.8"
                  fill={theme.palette.text.secondary}
                >
                  {node.name.split(" ").slice(-1)[0]}
                </text>
              </g>
            );
          })}
        </svg>

        {hoverText ? (
          <Box
            sx={{
              position: "absolute",
              left: 12,
              bottom: 12,
              px: 1.25,
              py: 0.75,
              borderRadius: "10px",
              bgcolor: "background.paper",
              border: "1px solid",
              borderColor: "divider",
              maxWidth: "90%",
            }}
          >
            <Typography variant="caption" color="text.secondary">
              {hoverText}
            </Typography>
          </Box>
        ) : null}
      </Box>
    </Paper>
  );
}

export default InstitutionNetworkPreview;
