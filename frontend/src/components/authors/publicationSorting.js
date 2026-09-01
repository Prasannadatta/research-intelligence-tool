export const PUBLICATION_SORT_FIELDS = {
  YEAR: "year",
  CITATIONS: "citations",
  TITLE: "title",
  VENUE: "venue",
  AUTHOR_COUNT: "author_count",
};

export const DEFAULT_PUBLICATION_SORT = {
  sortBy: PUBLICATION_SORT_FIELDS.YEAR,
  sortDirection: "desc",
};

export function normalizePublicationSort(sort) {
  const sortBy = Object.values(PUBLICATION_SORT_FIELDS).includes(sort?.sortBy)
    ? sort.sortBy
    : DEFAULT_PUBLICATION_SORT.sortBy;
  const sortDirection = sort?.sortDirection === "asc" ? "asc" : "desc";
  return { sortBy, sortDirection };
}

export function publicationSortKey(sort) {
  const normalized = normalizePublicationSort(sort);
  return `${normalized.sortBy}:${normalized.sortDirection}`;
}

export function nextPublicationSort(current, field) {
  const normalized = normalizePublicationSort(current);
  if (normalized.sortBy !== field) {
    return { sortBy: field, sortDirection: "asc" };
  }
  return {
    sortBy: field,
    sortDirection: normalized.sortDirection === "asc" ? "desc" : "asc",
  };
}
