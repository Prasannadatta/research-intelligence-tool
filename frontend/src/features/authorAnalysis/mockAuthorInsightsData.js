/**
 * Frontend-only demonstration data for a minimal Author Collaboration Analysis prototype.
 * Not connected to production APIs or persistence.
 */

export const DEMO_AUTHOR_NAMES = [
  "Eneet Kaur",
  "Mark M. Wilde",
  "Nilanjana Datta",
];

export const DEMO_NOTICE =
  "This page currently uses demonstration data to preview planned analysis capabilities.";

/**
 * Resolve selected author display names from router state, falling back to demo names.
 */
export function resolveSelectedAuthorNames(locationState) {
  const fromAuthors = Array.isArray(locationState?.authors)
    ? locationState.authors
        .map((item) => item?.display_name || item?.name || item)
        .filter((name) => typeof name === "string" && name.trim())
        .map((name) => name.trim())
    : [];

  const fromNames = Array.isArray(locationState?.authorNames)
    ? locationState.authorNames
        .filter((name) => typeof name === "string" && name.trim())
        .map((name) => name.trim())
    : [];

  const resolved = fromAuthors.length > 0 ? fromAuthors : fromNames;
  if (resolved.length > 0) {
    return resolved;
  }
  return [...DEMO_AUTHOR_NAMES];
}

const COMBINATIONS = [
  {
    id: "a+b",
    authors: ["Eneet Kaur", "Mark M. Wilde"],
    label: "Eneet Kaur + Mark M. Wilde",
    sharedPublications: 21,
    citations: 620,
    institutions: 4,
  },
  {
    id: "a+c",
    authors: ["Eneet Kaur", "Nilanjana Datta"],
    label: "Eneet Kaur + Nilanjana Datta",
    sharedPublications: 8,
    citations: 210,
    institutions: 3,
  },
  {
    id: "b+c",
    authors: ["Mark M. Wilde", "Nilanjana Datta"],
    label: "Mark M. Wilde + Nilanjana Datta",
    sharedPublications: 14,
    citations: 470,
    institutions: 4,
  },
  {
    id: "a+b+c",
    authors: ["Eneet Kaur", "Mark M. Wilde", "Nilanjana Datta"],
    label: "All selected authors",
    sharedPublications: 5,
    citations: 145,
    institutions: 2,
  },
];

const PUBLICATIONS_BY_COMBINATION = {
  "a+b": [
    {
      id: "p-ab-1",
      title: "Amortized entanglement of a quantum channel",
      authors: ["Eneet Kaur", "Mark M. Wilde"],
      year: 2020,
      venue: "Physical Review A",
      citations: 54,
      institutions: ["Louisiana State University", "University of Arizona"],
    },
    {
      id: "p-ab-2",
      title: "Extendibility limits the performance of quantum processors",
      authors: ["Eneet Kaur", "Mark M. Wilde"],
      year: 2019,
      venue: "Physical Review Letters",
      citations: 112,
      institutions: ["Louisiana State University"],
    },
    {
      id: "p-ab-3",
      title: "Conditional mutual information and quantum Markov chains",
      authors: ["Eneet Kaur", "Mark M. Wilde"],
      year: 2022,
      venue: "Quantum",
      citations: 41,
      institutions: ["University of Arizona", "Louisiana State University"],
    },
    {
      id: "p-ab-4",
      title: "Quantum channels with memory and their capacities",
      authors: ["Eneet Kaur", "Mark M. Wilde"],
      year: 2019,
      venue: "IEEE Transactions on Information Theory",
      citations: 312,
      institutions: ["Louisiana State University"],
    },
    {
      id: "p-ab-5",
      title: "Entanglement-assisted classical capacity bounds",
      authors: ["Eneet Kaur", "Mark M. Wilde"],
      year: 2021,
      venue: "IEEE Transactions on Information Theory",
      citations: 86,
      institutions: ["University of Arizona", "Louisiana State University"],
    },
  ],
  "a+c": [
    {
      id: "p-ac-1",
      title: "Smoothing of quantum relative entropy",
      authors: ["Eneet Kaur", "Nilanjana Datta"],
      year: 2021,
      venue: "Journal of Mathematical Physics",
      citations: 33,
      institutions: ["University of Arizona", "University of Cambridge"],
    },
    {
      id: "p-ac-2",
      title: "Finite-blocklength quantum coding bounds",
      authors: ["Eneet Kaur", "Nilanjana Datta"],
      year: 2023,
      venue: "Quantum",
      citations: 19,
      institutions: ["University of Arizona", "University of Cambridge"],
    },
    {
      id: "p-ac-3",
      title: "One-shot resource inequalities for quantum channels",
      authors: ["Eneet Kaur", "Nilanjana Datta"],
      year: 2020,
      venue: "Communications in Mathematical Physics",
      citations: 47,
      institutions: ["University of Cambridge"],
    },
    {
      id: "p-ac-4",
      title: "Continuity bounds for quantum capacities",
      authors: ["Eneet Kaur", "Nilanjana Datta"],
      year: 2022,
      venue: "IEEE Transactions on Information Theory",
      citations: 28,
      institutions: ["University of Arizona", "University of Cambridge"],
    },
    {
      id: "p-ac-5",
      title: "Approximate recoverability in quantum networks",
      authors: ["Eneet Kaur", "Nilanjana Datta"],
      year: 2024,
      venue: "Physical Review A",
      citations: 15,
      institutions: ["University of Arizona", "University of Cambridge"],
    },
  ],
  "b+c": [
    {
      id: "p-bc-1",
      title: "Recoverability of quantum channels",
      authors: ["Mark M. Wilde", "Nilanjana Datta"],
      year: 2020,
      venue: "Communications in Mathematical Physics",
      citations: 95,
      institutions: ["University of Cambridge", "Louisiana State University"],
    },
    {
      id: "p-bc-2",
      title: "Quantum relative entropy inequalities",
      authors: ["Mark M. Wilde", "Nilanjana Datta"],
      year: 2021,
      venue: "Journal of Mathematical Physics",
      citations: 47,
      institutions: ["University of Cambridge", "Louisiana State University"],
    },
    {
      id: "p-bc-3",
      title: "Second-order asymptotics for quantum hypothesis testing",
      authors: ["Mark M. Wilde", "Nilanjana Datta"],
      year: 2019,
      venue: "IEEE Transactions on Information Theory",
      citations: 128,
      institutions: ["University of Cambridge", "Louisiana State University"],
    },
    {
      id: "p-bc-4",
      title: "Strong converse exponents for quantum channels",
      authors: ["Mark M. Wilde", "Nilanjana Datta"],
      year: 2022,
      venue: "Quantum",
      citations: 39,
      institutions: ["University of Arizona", "University of Cambridge"],
    },
    {
      id: "p-bc-5",
      title: "Entropy bounds for multipartite quantum states",
      authors: ["Mark M. Wilde", "Nilanjana Datta"],
      year: 2023,
      venue: "Physical Review A",
      citations: 31,
      institutions: ["Louisiana State University", "University of Cambridge"],
    },
  ],
  "a+b+c": [
    {
      id: "p-abc-1",
      title: "Multipartite quantum channel discrimination",
      authors: ["Eneet Kaur", "Mark M. Wilde", "Nilanjana Datta"],
      year: 2022,
      venue: "Quantum",
      citations: 38,
      institutions: ["University of Arizona", "University of Cambridge"],
    },
    {
      id: "p-abc-2",
      title: "Collaborative bounds on quantum capacities",
      authors: ["Eneet Kaur", "Mark M. Wilde", "Nilanjana Datta"],
      year: 2023,
      venue: "IEEE Transactions on Information Theory",
      citations: 27,
      institutions: [
        "University of Arizona",
        "Louisiana State University",
        "University of Cambridge",
      ],
    },
    {
      id: "p-abc-3",
      title: "Unified framework for quantum resource theories",
      authors: ["Eneet Kaur", "Mark M. Wilde", "Nilanjana Datta"],
      year: 2024,
      venue: "Communications in Mathematical Physics",
      citations: 22,
      institutions: ["University of Arizona", "University of Cambridge"],
    },
    {
      id: "p-abc-4",
      title: "Entropy inequalities for multi-author quantum networks",
      authors: ["Eneet Kaur", "Mark M. Wilde", "Nilanjana Datta"],
      year: 2021,
      venue: "Physical Review A",
      citations: 41,
      institutions: ["Louisiana State University", "University of Cambridge"],
    },
    {
      id: "p-abc-5",
      title: "Shared entanglement across institutional collaborations",
      authors: ["Eneet Kaur", "Mark M. Wilde", "Nilanjana Datta"],
      year: 2020,
      venue: "Journal of Mathematical Physics",
      citations: 17,
      institutions: ["University of Arizona", "Louisiana State University"],
    },
  ],
};

/**
 * Build the full mock dashboard payload for the insights prototype.
 */
export function getMockAuthorInsightsData({ authorNames } = {}) {
  const names =
    Array.isArray(authorNames) && authorNames.length > 0
      ? authorNames
      : [...DEMO_AUTHOR_NAMES];

  const metrics = {
    totalUniquePublications: 186,
    sharedByTwoOrMore: 47,
    sharedByAll: 9,
    multiInstitutionPublications: 38,
    sharedByTwoOrMorePercent: 25.3,
    sharedByAllPercent: 4.8,
    multiInstitutionPercent: 20.4,
  };

  const collaborationByYear = {
    years: [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026],
    counts: [4, 5, 6, 8, 7, 6, 5, 6],
  };
  const collaborationYearTotal = collaborationByYear.counts.reduce(
    (sum, value) => sum + value,
    0,
  );

  const citationActivity = {
    years: [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026],
    citations: [520, 610, 740, 820, 690, 540, 410, 210],
    cumulative: [520, 1130, 1870, 2690, 3380, 3920, 4330, 4540],
    totalCitations: 4540,
    averageCitations: 24.4,
    mostCitedShared: {
      title: "Quantum channels with memory and their capacities",
      citations: 312,
      year: 2019,
    },
  };

  return {
    authorNames: names,
    demoNotice: DEMO_NOTICE,
    metrics,
    combinations: COMBINATIONS.map((row) => ({
      ...row,
      authors: [...row.authors],
    })),
    collaborationByYear: {
      ...collaborationByYear,
      total: collaborationYearTotal,
    },
    participation: {
      selectedAuthors: [
        { label: "One selected author", value: 139 },
        { label: "Two selected authors", value: 38 },
        { label: "Three selected authors", value: 9 },
      ],
      institutions: [
        { label: "Single institution", value: 148 },
        { label: "Multiple institutions", value: 38 },
      ],
      sharedByTwoOrMoreAuthors: 47,
      multiInstitutionPapers: 38,
    },
    institutionNetwork: {
      nodes: [
        { id: "arizona", name: "University of Arizona", publications: 42, x: 18, y: 42 },
        { id: "lsu", name: "Louisiana State University", publications: 38, x: 48, y: 18 },
        { id: "cambridge", name: "University of Cambridge", publications: 29, x: 78, y: 38 },
        { id: "uts", name: "University of Technology Sydney", publications: 21, x: 62, y: 72 },
        { id: "bristol", name: "University of Bristol", publications: 17, x: 28, y: 78 },
      ],
      edges: [
        { source: "arizona", target: "lsu", sharedPublications: 12 },
        { source: "cambridge", target: "uts", sharedPublications: 8 },
        { source: "arizona", target: "cambridge", sharedPublications: 6 },
        { source: "lsu", target: "bristol", sharedPublications: 5 },
        { source: "cambridge", target: "bristol", sharedPublications: 4 },
      ],
    },
    institutionPartnerships: [
      { partnership: "University of Arizona × LSU", sharedPublications: 12 },
      { partnership: "Cambridge × UTS", sharedPublications: 8 },
      { partnership: "Arizona × Cambridge", sharedPublications: 6 },
      { partnership: "LSU × Bristol", sharedPublications: 5 },
    ],
    citationActivity,
    topJournals: [
      { venue: "IEEE Transactions on Information Theory", publications: 28 },
      { venue: "Physical Review A", publications: 22 },
      { venue: "Quantum", publications: 18 },
      { venue: "Communications in Mathematical Physics", publications: 14 },
      { venue: "Journal of Mathematical Physics", publications: 11 },
      { venue: "Physical Review Letters", publications: 9 },
      { venue: "New Journal of Physics", publications: 7 },
    ],
    publicationsByCombination: Object.fromEntries(
      Object.entries(PUBLICATIONS_BY_COMBINATION).map(([key, rows]) => [
        key,
        rows.map((row) => ({
          ...row,
          authors: [...row.authors],
          institutions: [...row.institutions],
        })),
      ]),
    ),
    defaultCombinationId: "a+b",
  };
}

export function getPublicationsForCombination(data, combinationId) {
  if (!data?.publicationsByCombination) {
    return [];
  }
  return data.publicationsByCombination[combinationId] || [];
}
