export const MISSING_JOURNAL_METRIC = "—";

export function formatJournalMetric(value, { digits = 2 } = {}) {
  if (value === null || value === undefined || value === "") {
    return MISSING_JOURNAL_METRIC;
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return MISSING_JOURNAL_METRIC;
  }
  return numeric.toFixed(digits);
}

export function formatCiteScore(value) {
  return formatJournalMetric(value, { digits: 1 });
}

export function formatSjr(value) {
  return formatJournalMetric(value, { digits: 2 });
}

export function formatSnip(value) {
  return formatJournalMetric(value, { digits: 2 });
}

export function journalMetricTooltip(label, value, year) {
  const formatted = formatJournalMetric(
    value,
    { digits: label === "CiteScore" ? 1 : 2 },
  );
  if (formatted === MISSING_JOURNAL_METRIC) {
    return `${label} unavailable`;
  }
  return year ? `${label} ${formatted} · ${year}` : `${label} ${formatted}`;
}

export function journalMetricsFromRow(row = {}) {
  const metrics = row.journalMetrics || row.journal_metrics || null;
  if (!metrics || typeof metrics !== "object") {
    return null;
  }
  return {
    citescore: metrics.citescore ?? null,
    citescoreYear: metrics.citescoreYear ?? metrics.citescore_year ?? null,
    sjr: metrics.sjr ?? null,
    sjrYear: metrics.sjrYear ?? metrics.sjr_year ?? null,
    snip: metrics.snip ?? null,
    snipYear: metrics.snipYear ?? metrics.snip_year ?? null,
    source: metrics.source || "scopus",
    scopusUrl: metrics.scopusUrl ?? metrics.scopus_url ?? null,
  };
}
