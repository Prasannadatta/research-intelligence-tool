/**
 * Pure helpers for AuthorAnalysisPage checkbox filtering and display.
 */

export const FILTER_DEBOUNCE_MS = 200;

export function getInitialActiveAuthorIds(authors) {
  return new Set(
    (Array.isArray(authors) ? authors : [])
      .map((author) => author?.canonical_author_id)
      .filter(Boolean),
  );
}

export function getActiveAuthors(originalAuthors, activeAuthorIds) {
  const ids = activeAuthorIds instanceof Set ? activeAuthorIds : new Set(activeAuthorIds);
  return (Array.isArray(originalAuthors) ? originalAuthors : []).filter((author) =>
    ids.has(author?.canonical_author_id),
  );
}

export function toggleActiveAuthor(activeAuthorIds, authorId) {
  const current =
    activeAuthorIds instanceof Set ? activeAuthorIds : new Set(activeAuthorIds);
  const next = new Set(current);

  if (next.has(authorId)) {
    if (next.size <= 1) {
      return current;
    }
    next.delete(authorId);
  } else {
    next.add(authorId);
  }
  return next;
}

export function isAuthorCheckboxDisabled(activeAuthorIds, authorId) {
  const current =
    activeAuthorIds instanceof Set ? activeAuthorIds : new Set(activeAuthorIds);
  return current.size === 1 && current.has(authorId);
}

export function analysisTitleForAuthors(activeAuthors) {
  const authors = Array.isArray(activeAuthors) ? activeAuthors : [];
  if (authors.length === 1) {
    return `Publications by ${authors[0].display_name}`;
  }
  return "Common Publications";
}

export function analysisSubtitleForAuthors(activeAuthors) {
  const authors = Array.isArray(activeAuthors) ? activeAuthors : [];
  if (authors.length <= 1) {
    return null;
  }
  return authors
    .map((author) => author?.display_name)
    .filter(Boolean)
    .join(", ");
}

export function emptyStateCopy(mode) {
  if (mode === "common_publications") {
    return {
      heading: "No common publications found",
      body: "We could not find any publications containing all currently selected authors. Try a different combination.",
    };
  }
  return {
    heading: "No publications found",
    body: "We could not find publications connected to this author from the available sources.",
  };
}

export function providerRecordsKey(authors) {
  return (Array.isArray(authors) ? authors : [])
    .map(
      (author) =>
        `${author.canonical_author_id}:${author.provider}:${author.provider_author_id}`,
    )
    .sort()
    .join("|");
}

export function activeAuthorIdsKey(activeAuthorIds) {
  return [...(activeAuthorIds instanceof Set ? activeAuthorIds : activeAuthorIds)]
    .filter(Boolean)
    .sort()
    .join(",");
}
