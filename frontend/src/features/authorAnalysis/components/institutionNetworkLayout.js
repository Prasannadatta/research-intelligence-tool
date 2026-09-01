import { getInsightsAccent, mixHex } from "../../../theme/analysisPalette";

export const PREVIEW_NODE_LIMIT = 24;
export const FULL_NODE_LIMIT = 48;
export const PREVIEW_EDGE_LIMIT = 28;
export const FULL_EDGE_LIMIT = 56;
export const PREVIEW_LABEL_LIMIT = 12;
export const FULL_LABEL_LIMIT = 12;

export const NETWORK_VIEW = {
  width: 220,
  height: 156,
  cx: 110,
  cy: 78,
  ringRadius: 56,
  labelRadius: 71,
};

const NODE_EDGE_GAP = 2.6;

export const NODE_RADIUS = { min: 2.3, max: 11.4 };

const INSTITUTION_LABEL_OVERRIDES = [
  [/massachusetts institute of technology/i, "MIT"],
  [/university of california,\s*santa barbara/i, "UC Santa Barbara"],
  [/university of california,\s*berkeley/i, "UC Berkeley"],
  [/lawrence berkeley national laboratory/i, "LBNL"],
  [/louisiana state university/i, "LSU"],
];

export function institutionDisplayLabel(name = "", maxChars = 18) {
  const cleaned = String(name).trim();
  const override = INSTITUTION_LABEL_OVERRIDES.find(([pattern]) => pattern.test(cleaned));
  if (override) {
    return override[1];
  }
  const withoutCommonWords = cleaned
    .replace(/^the\s+/i, "")
    .replace(/\b(university|institute|college|school|department|of|the)\b/gi, "")
    .replace(/\s+/g, " ")
    .trim();
  const fallback = withoutCommonWords || cleaned;
  if (fallback.length <= maxChars) {
    return fallback;
  }
  return `${fallback.slice(0, Math.max(1, maxChars - 1)).trim()}…`;
}

function edgeKey(source, target) {
  return [source, target].sort().join("|");
}

export function publicationVolume(publications, maxPublications) {
  return Math.max(0, Math.min(1, (publications || 0) / Math.max(1, maxPublications)));
}

export function nodeRadius(publications, maxPublications, sizeScale = 1) {
  const volume = publicationVolume(publications, maxPublications);
  const shaped = volume ** 0.72;
  const raw = NODE_RADIUS.min + (NODE_RADIUS.max - NODE_RADIUS.min) * shaped;
  return raw * sizeScale;
}

export function networkDensityScale(nodeCount) {
  if (nodeCount <= 20) {
    return 1;
  }
  if (nodeCount <= 36) {
    return 0.78;
  }
  if (nodeCount <= 60) {
    return 0.64;
  }
  return 0.52;
}

export function nodeFillStops(theme) {
  const { main, strong } = getInsightsAccent(theme, "institutionNetwork");
  const isDark = theme?.palette?.mode === "dark";
  if (isDark) {
    return [
      mixHex(main, "#1a2433", 0.28),
      mixHex(main, "#1a2433", 0.1),
      main,
      strong,
    ];
  }
  return [
    mixHex(main, "#ffffff", 0.36),
    mixHex(main, "#ffffff", 0.16),
    main,
    mixHex(main, "#163044", 0.24),
  ];
}

export function nodeFill(theme, volumeT, stops = nodeFillStops(theme)) {
  const scaled = publicationVolume(volumeT, 1) * (stops.length - 1);
  const index = Math.min(stops.length - 2, Math.floor(scaled));
  return mixHex(stops[index], stops[index + 1], scaled - index);
}

function buildSharedLookup(edges) {
  const map = new Map();
  const add = (from, to, weight) => {
    let row = map.get(from);
    if (!row) {
      row = new Map();
      map.set(from, row);
    }
    row.set(to, (row.get(to) || 0) + weight);
  };
  edges.forEach((edge) => {
    const weight = edge.sharedPublications || 0;
    add(edge.source, edge.target, weight);
    add(edge.target, edge.source, weight);
  });
  return map;
}

function partnerStatsFromList(partners) {
  const sorted = [...partners].sort(
    (left, right) =>
      right.sharedPublications - left.sharedPublications ||
      String(left.name).localeCompare(String(right.name)),
  );
  const strongest = sorted[0] || null;
  return {
    partnerCount: sorted.length,
    strongestPartnerName: strongest?.name || null,
    strongestPartnerShared: strongest?.sharedPublications || 0,
    neighborIds: new Set(sorted.map((row) => row.id)),
  };
}

function attachPartnerStats(visibleNodes, edges, nodeMap) {
  const lists = new Map(visibleNodes.map((node) => [node.id, []]));
  edges.forEach((edge) => {
    const weight = edge.sharedPublications || 0;
    if (lists.has(edge.source) && nodeMap[edge.target]) {
      lists.get(edge.source).push({
        id: edge.target,
        name: nodeMap[edge.target].name,
        sharedPublications: weight,
      });
    }
    if (lists.has(edge.target) && nodeMap[edge.source]) {
      lists.get(edge.target).push({
        id: edge.source,
        name: nodeMap[edge.source].name,
        sharedPublications: weight,
      });
    }
  });
  return lists;
}

function orderRingToReduceCrossings(nodes, sharedMap) {
  if (nodes.length <= 2) {
    return [...nodes];
  }
  const remaining = new Map(nodes.map((node) => [node.id, node]));
  const start = [...nodes].sort(
    (left, right) =>
      (right.publications || 0) - (left.publications || 0) ||
      String(left.name || "").localeCompare(String(right.name || "")),
  )[0];
  const ordered = [start];
  remaining.delete(start.id);

  const toPlaced = new Map();
  const startAdj = sharedMap.get(start.id);
  remaining.forEach((_, id) => {
    toPlaced.set(id, startAdj?.get(id) || 0);
  });

  while (remaining.size > 0) {
    const last = ordered[ordered.length - 1];
    const lastAdj = sharedMap.get(last.id);
    let best = null;
    let bestScore = -1;
    remaining.forEach((node, id) => {
      const adjacent = lastAdj?.get(id) || 0;
      const score = adjacent * 4 + (toPlaced.get(id) || 0) + (node.publications || 0) / 1000;
      if (score > bestScore) {
        bestScore = score;
        best = node;
      }
    });
    ordered.push(best);
    remaining.delete(best.id);
    const bestAdj = sharedMap.get(best.id);
    remaining.forEach((_, id) => {
      toPlaced.set(id, (toPlaced.get(id) || 0) + (bestAdj?.get(id) || 0));
    });
  }
  return ordered;
}

export function buildInstitutionNetworkView(
  nodes = [],
  edges = [],
  {
    nodeLimit,
    edgeLimit,
    labelLimit = PREVIEW_LABEL_LIMIT,
    includeAllEdges = false,
    sizeScale = 1,
  } = {},
) {
  const rankedNodes = [...nodes].sort(
    (left, right) =>
      (right.publications || 0) - (left.publications || 0) ||
      String(left.name || "").localeCompare(String(right.name || "")),
  );
  const visibleNodes =
    Number.isFinite(nodeLimit) && nodeLimit > 0
      ? rankedNodes.slice(0, nodeLimit)
      : rankedNodes;
  const visibleIds = new Set(visibleNodes.map((node) => node.id));
  const internalEdges = edges
    .filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target))
    .sort(
      (left, right) =>
        (right.sharedPublications || 0) - (left.sharedPublications || 0),
    );

  let visibleEdges = internalEdges;
  if (!includeAllEdges) {
    const keptKeys = new Set();
    const coveredNodes = new Set();
    internalEdges.forEach((edge) => {
      if (!coveredNodes.has(edge.source) || !coveredNodes.has(edge.target)) {
        keptKeys.add(edgeKey(edge.source, edge.target));
        coveredNodes.add(edge.source);
        coveredNodes.add(edge.target);
      }
    });

    const maxShared = Math.max(
      1,
      ...internalEdges.map((edge) => edge.sharedPublications || 0),
    );
    const threshold = internalEdges.length <= 8 ? 1 : Math.max(2, Math.ceil(maxShared * 0.25));
    const maxEdges = edgeLimit || PREVIEW_EDGE_LIMIT;
    internalEdges.forEach((edge) => {
      if (keptKeys.size >= maxEdges) {
        return;
      }
      if ((edge.sharedPublications || 0) < threshold) {
        return;
      }
      keptKeys.add(edgeKey(edge.source, edge.target));
    });
    visibleEdges = internalEdges.filter((edge) =>
      keptKeys.has(edgeKey(edge.source, edge.target)),
    );
  }

  const nodeMap = Object.fromEntries(nodes.map((node) => [node.id, node]));
  const labeledIds = new Set(
    [...visibleNodes]
      .sort((left, right) => (right.publications || 0) - (left.publications || 0))
      .slice(0, Math.min(labelLimit, visibleNodes.length))
      .map((node) => node.id),
  );
  const maxPublications = Math.max(1, ...visibleNodes.map((node) => node.publications || 0));
  const partnerLists = attachPartnerStats(visibleNodes, edges, nodeMap);

  return {
    nodes: visibleNodes.map((node) => ({
      ...node,
      volumeT: publicationVolume(node.publications, maxPublications),
      r: nodeRadius(node.publications, maxPublications, sizeScale),
      ...partnerStatsFromList(partnerLists.get(node.id) || []),
    })),
    visibleEdges,
    latentEdges: internalEdges,
    maxShared: Math.max(
      1,
      ...internalEdges.map((edge) => edge.sharedPublications || 0),
    ),
    maxPublications,
    labeledIds,
    labelScale: sizeScale,
    truncated: nodes.length > visibleNodes.length,
    hiddenNodeCount: Math.max(0, nodes.length - visibleNodes.length),
  };
}

function ringRadiusForEdgeGap(radii, edgeGap = NODE_EDGE_GAP) {
  const count = radii.length;
  if (count === 0) {
    return NETWORK_VIEW.ringRadius;
  }
  if (count === 1) {
    return NETWORK_VIEW.ringRadius;
  }
  let minRadius = 0;
  for (let index = 0; index < count; index += 1) {
    minRadius = Math.max(
      minRadius,
      (radii[index] + radii[(index + 1) % count] + edgeGap) / 2 + 0.05,
    );
  }
  const { cx, cy, width, height } = NETWORK_VIEW;
  const maxNodeRadius = Math.max(...radii);
  const maxAllowed =
    Math.min(cx, cy, width - cx, height - cy) - maxNodeRadius - 16;
  const chordOf = (index, ringRadius) => {
    const chord = radii[index] + radii[(index + 1) % count] + edgeGap;
    return 2 * Math.asin(Math.min(0.999999, chord / (2 * ringRadius)));
  };
  let low = minRadius;
  let high = Math.max(minRadius + 1, NETWORK_VIEW.ringRadius * 2);
  for (let step = 0; step < 28; step += 1) {
    const mid = (low + high) / 2;
    let sum = 0;
    for (let index = 0; index < count; index += 1) {
      sum += chordOf(index, mid);
    }
    if (sum > Math.PI * 2) {
      low = mid;
    } else {
      high = mid;
    }
  }
  return Math.min(maxAllowed, Math.max(minRadius, high));
}

export function layoutInstitutionNetwork(nodes, edges, { edgeGap = NODE_EDGE_GAP } = {}) {
  const { cx, cy } = NETWORK_VIEW;
  if (nodes.length === 0) {
    return [];
  }
  const ordered = orderRingToReduceCrossings(nodes, buildSharedLookup(edges));
  const radii = ordered.map((node) => node.r || NODE_RADIUS.min);
  const ringRadius = ringRadiusForEdgeGap(radii, edgeGap);
  const count = ordered.length;

  if (count === 1) {
    const angle = -Math.PI / 2;
    return [
      {
        ...ordered[0],
        x: Number((cx + Math.cos(angle) * ringRadius).toFixed(2)),
        y: Number((cy + Math.sin(angle) * ringRadius).toFixed(2)),
        angle,
        ringRadius,
      },
    ];
  }

  const angles = radii.map((radius, index) => {
    const chord = radius + radii[(index + 1) % count] + edgeGap;
    return 2 * Math.asin(Math.min(0.999999, chord / (2 * ringRadius)));
  });
  const scale = (Math.PI * 2) / angles.reduce((sum, angle) => sum + angle, 0);

  let angle = -Math.PI / 2;
  return ordered.map((node, index) => {
    const placed = {
      ...node,
      x: Number((cx + Math.cos(angle) * ringRadius).toFixed(2)),
      y: Number((cy + Math.sin(angle) * ringRadius).toFixed(2)),
      angle,
      ringRadius,
    };
    angle += angles[index] * scale;
    return placed;
  });
}

export function computeLabelLayout(nodes, labeledIds, hoverId, { maxChars = 16 } = {}) {
  const { cx, cy, height, width } = NETWORK_VIEW;
  const labels = [];

  nodes.forEach((node) => {
    const active = node.id === hoverId;
    if (!labeledIds.has(node.id) && !active) {
      return;
    }
    const ringRadius = node.ringRadius || NETWORK_VIEW.ringRadius;
    const right = Math.cos(node.angle) >= 0;
    const vertical = Math.sin(node.angle);
    let labelRadiusAdjusted = ringRadius + 15;
    if (vertical < -0.72) {
      labelRadiusAdjusted += 2.5;
    } else if (vertical > 0.72) {
      labelRadiusAdjusted += 2;
    }
    const labelX = cx + Math.cos(node.angle) * labelRadiusAdjusted + (right ? 1.2 : -1.2);
    const labelY = cy + Math.sin(node.angle) * labelRadiusAdjusted + vertical * 1.4;
    const nodeEdgeX = node.x + Math.cos(node.angle) * ((node.r || 4) + 1.1);
    const nodeEdgeY = node.y + Math.sin(node.angle) * ((node.r || 4) + 1.1);
    labels.push({
      id: node.id,
      text: active ? node.name : institutionDisplayLabel(node.name, maxChars),
      x: Number(labelX.toFixed(2)),
      y: Number(labelY.toFixed(2)),
      textAnchor: right ? "start" : "end",
      side: right ? "right" : "left",
      leader: {
        x1: Number(nodeEdgeX.toFixed(2)),
        y1: Number(nodeEdgeY.toFixed(2)),
        x2: Number(labelX.toFixed(2)),
        y2: Number(labelY.toFixed(2)),
      },
      active,
    });
  });

  ["left", "right"].forEach((side) => {
    const group = labels.filter((label) => label.side === side).sort((a, b) => a.y - b.y);
    const minGap = 6.8;
    for (let index = 1; index < group.length; index += 1) {
      if (group[index].y - group[index - 1].y < minGap) {
        group[index].y = group[index - 1].y + minGap;
      }
    }
    group.forEach((label) => {
      label.y = Math.min(height - 7, Math.max(8, label.y));
      label.x = side === "right" ? Math.min(width - 4, label.x) : Math.max(4, label.x);
      if (label.leader) {
        label.leader.y2 = label.y;
        label.leader.x2 = label.x;
      }
    });
  });

  return labels;
}

export function edgePath(source, target) {
  const { cx, cy } = NETWORK_VIEW;
  const mx = (source.x + target.x) / 2;
  const my = (source.y + target.y) / 2;
  const inwardX = cx - mx;
  const inwardY = cy - my;
  const dist = Math.hypot(inwardX, inwardY) || 1;
  const qx = mx + (inwardX / dist) * 14;
  const qy = my + (inwardY / dist) * 14;
  return `M ${source.x} ${source.y} Q ${qx.toFixed(2)} ${qy.toFixed(2)} ${target.x} ${target.y}`;
}

export function edgeWeight(sharedPublications, maxShared) {
  const strength = Math.max(0, sharedPublications || 0) / Math.max(1, maxShared);
  return {
    strength,
    width: 0.4 + strength * 1.7,
    opacity: 0.16 + strength * 0.42,
  };
}

export function networkEdgeStroke(theme, strength) {
  const { main } = getInsightsAccent(theme, "institutionNetwork");
  const isDark = theme?.palette?.mode === "dark";
  const lightEnd = mixHex(main, isDark ? "#1a2433" : "#ffffff", isDark ? 0.22 : 0.42);
  return mixHex(lightEnd, main, 0.2 + strength * 0.8);
}

export const ALL_LABEL_LIMIT = 12;

export function topNetworkViewOptions() {
  return {
    nodeLimit: PREVIEW_NODE_LIMIT,
    edgeLimit: PREVIEW_EDGE_LIMIT,
    labelLimit: PREVIEW_LABEL_LIMIT,
    includeAllEdges: false,
    sizeScale: 1,
    edgeGap: NODE_EDGE_GAP,
    labelMaxChars: 16,
  };
}

export function allNetworkViewOptions(nodeCount) {
  return {
    nodeLimit: null,
    edgeLimit: null,
    labelLimit: ALL_LABEL_LIMIT,
    includeAllEdges: true,
    sizeScale: networkDensityScale(nodeCount),
    edgeGap: nodeCount > 24 ? 1.7 : NODE_EDGE_GAP,
    labelMaxChars: nodeCount > 24 ? 12 : 16,
  };
}

function prepareEdge(edge, nodeById, maxShared, theme) {
  const source = nodeById[edge.source];
  const target = nodeById[edge.target];
  if (!source || !target) {
    return null;
  }
  const weight = edgeWeight(edge.sharedPublications, maxShared);
  return {
    key: `${edge.source}-${edge.target}`,
    source: edge.source,
    target: edge.target,
    sharedPublications: edge.sharedPublications,
    d: edgePath(source, target),
    width: weight.width,
    opacity: weight.opacity,
    stroke: networkEdgeStroke(theme, weight.strength),
    activeWidth: Math.max(1.4, weight.width + 0.55),
  };
}

export function prepareInstitutionNetworkView(nodes, edges, options, theme) {
  const graph = buildInstitutionNetworkView(nodes, edges, options);
  const laidOut = layoutInstitutionNetwork(graph.nodes, graph.visibleEdges, {
    edgeGap: options.edgeGap ?? NODE_EDGE_GAP,
  });
  const stops = nodeFillStops(theme);
  const nodeById = {};
  const preparedNodes = laidOut.map((node) => {
    const prepared = {
      ...node,
      fill: nodeFill(theme, node.volumeT, stops),
      hitRadius: (node.r || 4) + 2.6,
      neighborToken: [...(node.neighborIds || [])].join(" "),
    };
    nodeById[node.id] = prepared;
    return prepared;
  });

  const visibleEdges = graph.visibleEdges
    .map((edge) => prepareEdge(edge, nodeById, graph.maxShared, theme))
    .filter(Boolean);
  const visibleKeySet = new Set(
    visibleEdges.map((edge) => edgeKey(edge.source, edge.target)),
  );

  const extraEdgesByNode = {};
  graph.latentEdges.forEach((edge) => {
    if (visibleKeySet.has(edgeKey(edge.source, edge.target))) {
      return;
    }
    const prepared = prepareEdge(edge, nodeById, graph.maxShared, theme);
    if (!prepared) {
      return;
    }
    (extraEdgesByNode[edge.source] ||= []).push(prepared);
    (extraEdgesByNode[edge.target] ||= []).push(prepared);
  });

  const latentByKey = {};
  graph.latentEdges.forEach((edge) => {
    latentByKey[edgeKey(edge.source, edge.target)] = edge;
  });

  const labelMaxChars = options.labelMaxChars || 16;
  const baseLabels = computeLabelLayout(preparedNodes, graph.labeledIds, null, {
    maxChars: labelMaxChars,
  });
  const labelById = {};
  baseLabels.forEach((label) => {
    labelById[label.id] = label;
  });

  return {
    nodes: preparedNodes,
    nodeById,
    visibleEdges,
    extraEdgesByNode,
    latentByKey,
    baseLabels,
    labelById,
    labeledIds: graph.labeledIds,
    labelMaxChars,
    labelScale: graph.labelScale,
    maxShared: graph.maxShared,
    ringRadius: preparedNodes[0]?.ringRadius || NETWORK_VIEW.ringRadius,
  };
}

export function hoverLabelsForView(view, hover) {
  if (!view || hover?.type !== "node") {
    return view?.baseLabels || [];
  }
  const node = view.nodeById[hover.id];
  if (!node) {
    return view.baseLabels;
  }
  if (view.labelById[hover.id]) {
    return view.baseLabels.map((label) =>
      label.id === hover.id ? { ...label, text: node.name, active: true } : label,
    );
  }
  const extra = computeLabelLayout([node], new Set(), hover.id, {
    maxChars: view.labelMaxChars,
  });
  return extra.length ? [...view.baseLabels, extra[0]] : view.baseLabels;
}

export function lookupLatentEdge(view, source, target) {
  if (!view) {
    return null;
  }
  return (
    view.latentByKey[edgeKey(source, target)] ||
    view.visibleEdges.find((edge) => edge.source === source && edge.target === target) ||
    null
  );
}
