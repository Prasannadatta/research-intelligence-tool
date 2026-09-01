function percent(part, total) {
  if (!total) {
    return 0;
  }
  return Number(((Number(part || 0) / Number(total)) * 100).toFixed(1));
}

function numberValue(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

function buildNetworkNodes(nodes = []) {
  const count = nodes.length;
  if (count === 0) {
    return [];
  }

  return nodes.map((node, index) => {
    const angle = count === 1 ? 0 : (Math.PI * 2 * index) / count - Math.PI / 2;
    const radius = count <= 3 ? 36 : 40;
    return {
      id: node.id,
      name: node.name,
      country: node.country ?? null,
      publications: numberValue(node.publication_count),
      x: Number((50 + Math.cos(angle) * radius).toFixed(2)),
      y: Number((50 + Math.sin(angle) * radius).toFixed(2)),
    };
  });
}

function selectedAuthorLabel(count) {
  return `${count} selected author${count === 1 ? "" : "s"}`;
}

function institutionLabel(count) {
  return `${count} institution${count === 1 ? "" : "s"}`;
}

export function adaptAuthorInsightsResponse(response = {}) {
  const authors = Array.isArray(response.authors) ? response.authors : [];
  const metrics = response.metrics || {};
  const totalUniquePublications = numberValue(metrics.total_unique_publications);
  const sharedByTwoOrMore = numberValue(metrics.multi_selected_author_publications);
  const sharedByAll = numberValue(metrics.all_selected_author_publications);
  const multiInstitutionPublications = numberValue(
    metrics.multi_institution_publications,
  );

  const collaborationRows = Array.isArray(response.collaboration_by_year)
    ? response.collaboration_by_year
    : [];
  const citationRows = Array.isArray(response.citation_activity)
    ? response.citation_activity
    : [];
  const citationYears = citationRows.map((row) => row.year);
  const citationActivity = {
    years: citationYears,
    citations: citationRows.map((row) => numberValue(row.citation_count)),
    cumulative: citationRows.map((row) => numberValue(row.cumulative_citations)),
    totalCitations: numberValue(metrics.total_citations),
    averageCitations: numberValue(metrics.average_citations),
    mostCitedShared: null,
  };

  return {
    authorNames: authors
      .map((author) => author.display_name)
      .filter((name) => typeof name === "string" && name.trim()),
    authors,
    metrics: {
      totalUniquePublications,
      sharedByTwoOrMore,
      sharedByAll,
      multiInstitutionPublications,
      sharedByTwoOrMorePercent: percent(sharedByTwoOrMore, totalUniquePublications),
      sharedByAllPercent: percent(sharedByAll, totalUniquePublications),
      multiInstitutionPercent: percent(
        multiInstitutionPublications,
        totalUniquePublications,
      ),
    },
    combinations: (Array.isArray(response.combinations) ? response.combinations : []).map(
      (row) => ({
        id: row.id,
        authorIds: Array.isArray(row.author_ids) ? row.author_ids : [],
        authors: Array.isArray(row.author_names) ? row.author_names : [],
        label: row.label,
        sharedPublications: numberValue(row.publication_count),
        citations: numberValue(row.citation_count),
        averageCitations: numberValue(row.average_citations),
        institutions: numberValue(row.institution_count),
        grants: numberValue(row.grant_count),
      }),
    ),
    collaborationByYear: {
      years: collaborationRows.map((row) => row.year),
      counts: collaborationRows.map((row) => numberValue(row.publication_count)),
      percentages: collaborationRows.map((row) =>
        numberValue(row.percentage_of_year_total),
      ),
      total: collaborationRows.reduce(
        (sum, row) => sum + numberValue(row.publication_count),
        0,
      ),
    },
    participation: {
      selectedAuthors: (
        response.participation?.selected_author_counts || []
      ).map((row) => ({
        label: selectedAuthorLabel(numberValue(row.selected_author_count)),
        value: numberValue(row.publication_count),
      })),
      institutions: (response.participation?.institution_counts || []).map((row) => ({
        label: institutionLabel(numberValue(row.institution_count)),
        value: numberValue(row.publication_count),
      })),
      sharedByTwoOrMoreAuthors: sharedByTwoOrMore,
      multiInstitutionPapers: multiInstitutionPublications,
    },
    institutionNetwork: {
      nodes: buildNetworkNodes(response.institution_network?.nodes || []),
      edges: (response.institution_network?.edges || []).map((edge) => ({
        source: edge.source,
        target: edge.target,
        sharedPublications: numberValue(edge.shared_publication_count),
      })),
    },
    institutionPartnerships: (
      Array.isArray(response.institution_partnerships)
        ? response.institution_partnerships
        : []
    ).map((row) => {
      const institutionA = row.institution_a?.name || row.institution_a?.id || "";
      const institutionB = row.institution_b?.name || row.institution_b?.id || "";
      return {
        partnership: [institutionA, institutionB].filter(Boolean).join(" × "),
        sharedPublications: numberValue(row.shared_publication_count),
        selectedAuthorIds: Array.isArray(row.selected_author_ids)
          ? row.selected_author_ids
          : [],
        selectedAuthorNames: Array.isArray(row.selected_author_names)
          ? row.selected_author_names
          : [],
      };
    }),
    citationActivity,
    topJournals: (Array.isArray(response.top_journals) ? response.top_journals : []).map(
      (row) => ({
        venue: row.venue,
        publications: numberValue(row.publication_count),
        citations: numberValue(row.citation_count),
        issn: row.issn || null,
        journalMetrics: row.journal_metrics || null,
      }),
    ),
    defaultCombinationId: response.default_combination_id ?? null,
    institutionDataQuality: response.institution_data_quality || null,
    facets: response.facets || {
      sources: [],
      institutions: [],
      venues: [],
      grants: [],
      authors: [],
    },
  };
}
