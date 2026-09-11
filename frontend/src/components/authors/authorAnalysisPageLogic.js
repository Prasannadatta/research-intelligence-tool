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

export const CORPUS_STATUS = {
  VERIFIED: "verified",
  SYNCING: "syncing",
  PARTIAL: "partial",
  RATE_LIMITED: "rate_limited",
  FAILED: "failed",
};

function isRateLimitMessage(value) {
  return /rate limit/i.test(String(value || ""));
}

export function deriveCorpusStatus({
  corpusComplete = false,
  statsLoading = false,
  statsError = null,
  statsProgress = null,
  hasLoadedOnce = false,
} = {}) {
  const detail = statsProgress?.detail || {};
  if (detail.rate_limited || detail.rateLimited || isRateLimitMessage(statsError)) {
    return CORPUS_STATUS.RATE_LIMITED;
  }
  if (statsLoading) {
    return CORPUS_STATUS.SYNCING;
  }
  if (statsError) {
    if (/coverage|not verified|did not finish|incomplete|partial/i.test(String(statsError))) {
      return CORPUS_STATUS.PARTIAL;
    }
    return CORPUS_STATUS.FAILED;
  }
  if (corpusComplete) {
    return CORPUS_STATUS.VERIFIED;
  }
  if (hasLoadedOnce) {
    return CORPUS_STATUS.PARTIAL;
  }
  return null;
}

export function corpusStatusLabel(status) {
  switch (status) {
    case CORPUS_STATUS.VERIFIED:
      return "Verified";
    case CORPUS_STATUS.SYNCING:
      return "Syncing";
    case CORPUS_STATUS.PARTIAL:
      return "Partial";
    case CORPUS_STATUS.RATE_LIMITED:
      return "Rate limited";
    case CORPUS_STATUS.FAILED:
      return "Failed";
    default:
      return null;
  }
}

export function providerDisplayLabel(authors) {
  const providers = [
    ...new Set(
      (Array.isArray(authors) ? authors : [])
        .map((author) => String(author?.provider || "").toLowerCase())
        .filter(Boolean),
    ),
  ];
  if (providers.length === 1) {
    if (providers[0] === "openalex") {
      return "OpenAlex";
    }
    if (providers[0] === "arxiv") {
      return "arXiv";
    }
    if (providers[0] === "orcid") {
      return "ORCID";
    }
    return providers[0];
  }
  if (providers.length > 1) {
    return "provider";
  }
  return "OpenAlex";
}

export function formatProviderDedupCaption({
  uniqueCount,
  providerTotalCount,
  providerLabel = "OpenAlex",
} = {}) {
  const unique = Number(uniqueCount);
  const providerTotal = Number(providerTotalCount);
  if (
    !Number.isFinite(unique)
    || !Number.isFinite(providerTotal)
    || unique < 0
    || providerTotal < 0
    || providerTotal <= unique
  ) {
    return null;
  }
  const uniqueWord = unique === 1 ? "publication" : "publications";
  const recordWord = providerTotal === 1 ? "record" : "records";
  return `${unique.toLocaleString()} unique ${uniqueWord} from ${providerTotal.toLocaleString()} ${providerLabel} ${recordWord}`;
}
