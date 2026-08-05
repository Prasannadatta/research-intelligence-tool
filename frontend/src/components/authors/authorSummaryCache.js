import {
  fetchAuthorSummaryByCanonicalId,
  fetchAuthorSummaryByOpenAlexId,
} from "../../api/authorSummaryApi";

const summaryCache = new Map();
const inflightRequests = new Map();

export function getAuthorSummaryCacheKey(author) {
  if (!author || typeof author !== "object") {
    return null;
  }
  if (author.canonicalAuthorId) {
    return `canonical:${author.canonicalAuthorId}`;
  }
  const openalexId = author.providerIds?.openalex?.[0];
  if (openalexId) {
    return `openalex:${openalexId}`;
  }
  return null;
}

export function getAuthorLookupKey(author) {
  return getAuthorSummaryCacheKey(author) || `name:${author?.name || "unknown"}`;
}

export function getCachedAuthorSummary(author) {
  const key = getAuthorSummaryCacheKey(author);
  if (!key) {
    return null;
  }
  return summaryCache.get(key) ?? null;
}

export function hasInflightAuthorSummary(author) {
  const key = getAuthorSummaryCacheKey(author);
  if (!key) {
    return false;
  }
  return inflightRequests.has(key);
}

export function clearAuthorSummaryCache() {
  summaryCache.clear();
  inflightRequests.clear();
}

export function fetchAuthorSummary(author, { signal } = {}) {
  const key = getAuthorSummaryCacheKey(author);
  if (!key) {
    return Promise.reject(new Error("Author does not have a stable identifier."));
  }

  const cached = summaryCache.get(key);
  if (cached) {
    return Promise.resolve(cached);
  }

  const inflight = inflightRequests.get(key);
  if (inflight) {
    return inflight;
  }

  const request = (async () => {
    let data;
    if (author.canonicalAuthorId) {
      data = await fetchAuthorSummaryByCanonicalId(author.canonicalAuthorId, { signal });
    } else {
      const openalexId = author.providerIds?.openalex?.[0];
      data = await fetchAuthorSummaryByOpenAlexId(openalexId, { signal });
    }
    summaryCache.set(key, data);
    return data;
  })();

  inflightRequests.set(key, request);

  return request.finally(() => {
    if (inflightRequests.get(key) === request) {
      inflightRequests.delete(key);
    }
  });
}
