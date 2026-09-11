import {
  enrichAuthorSummaryByCanonicalId,
  fetchAuthorDetailsByCanonicalId,
  fetchAuthorSummaryByCanonicalId,
  fetchAuthorSummaryByOpenAlexId,
} from "../../api/authorSummaryApi";

const summaryCache = new Map();
const detailsCache = new Map();
const inflightRequests = new Map();
const inflightEnrichRequests = new Map();
const inflightDetailsRequests = new Map();

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

export function setCachedAuthorSummary(authorOrKey, summary) {
  const key = typeof authorOrKey === "string"
    ? authorOrKey
    : getAuthorSummaryCacheKey(authorOrKey);
  if (!key || !summary) {
    return;
  }
  summaryCache.set(key, summary);
  // Mirror openalex→canonical when we learn the canonical id.
  if (summary.id && key.startsWith("openalex:")) {
    summaryCache.set(`canonical:${summary.id}`, summary);
  }
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
  detailsCache.clear();
  inflightRequests.clear();
  inflightEnrichRequests.clear();
  inflightDetailsRequests.clear();
}

export function getCachedAuthorDetails(canonicalAuthorId) {
  if (!canonicalAuthorId) {
    return null;
  }
  return detailsCache.get(`canonical:${canonicalAuthorId}`) ?? null;
}

export function setCachedAuthorDetails(canonicalAuthorId, details) {
  if (!canonicalAuthorId || !details) {
    return;
  }
  detailsCache.set(`canonical:${canonicalAuthorId}`, details);
  // Keep hover-card summary cache in sync with identity/metric fields.
  setCachedAuthorSummary(`canonical:${canonicalAuthorId}`, details);
}

function summaryNeedsEnrichment(summary) {
  const pending = summary?.enrichment?.pending;
  return Array.isArray(pending) && pending.length > 0;
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
    setCachedAuthorSummary(key, data);
    return data;
  })();

  inflightRequests.set(key, request);

  return request.finally(() => {
    if (inflightRequests.get(key) === request) {
      inflightRequests.delete(key);
    }
  });
}

/**
 * Background enrichment. Dedupes in-flight calls; does not use abort on hover leave
 * so the first hover can finish and warm the cache for the next open.
 */
export function enrichAuthorSummary(author, { summary } = {}) {
  const key = getAuthorSummaryCacheKey(author);
  if (!key) {
    return Promise.resolve(summary ?? null);
  }

  const current = summary ?? summaryCache.get(key);
  const canonicalId = author.canonicalAuthorId || current?.id;
  if (!canonicalId) {
    return Promise.resolve(current ?? null);
  }
  if (!summaryNeedsEnrichment(current)) {
    return Promise.resolve(current ?? null);
  }

  const enrichKey = `enrich:canonical:${canonicalId}`;
  const inflight = inflightEnrichRequests.get(enrichKey);
  if (inflight) {
    return inflight;
  }

  const request = (async () => {
    try {
      const data = await enrichAuthorSummaryByCanonicalId(canonicalId);
      setCachedAuthorSummary(key, data);
      if (data?.id) {
        setCachedAuthorSummary(`canonical:${data.id}`, data);
        const existingDetails = detailsCache.get(`canonical:${data.id}`);
        if (existingDetails) {
          setCachedAuthorDetails(data.id, { ...existingDetails, ...data });
        }
      }
      return data;
    } catch {
      // Enrichment failures must not break the hover card.
      return current ?? null;
    }
  })();

  inflightEnrichRequests.set(enrichKey, request);
  return request.finally(() => {
    if (inflightEnrichRequests.get(enrichKey) === request) {
      inflightEnrichRequests.delete(enrichKey);
    }
  });
}

/**
 * Author details page loader. Uses local cache first; does not block on enrich.
 *
 * Do not abort the shared in-flight network call via caller AbortSignals.
 * React StrictMode remounts (and multi-subscriber joins) would cancel the only
 * request and leave the page stuck in loading when cancel errors are ignored.
 * Callers should ignore stale results with a local `cancelled` flag instead.
 */
export function fetchAuthorDetails(canonicalAuthorId, { signal } = {}) {
  const id = String(canonicalAuthorId || "").trim();
  if (!id) {
    return Promise.reject(new Error("Author id is required."));
  }

  const cacheKey = `canonical:${id}`;
  const cached = detailsCache.get(cacheKey);
  if (cached) {
    return Promise.resolve(cached);
  }

  const inflight = inflightDetailsRequests.get(cacheKey);
  if (inflight) {
    return inflight;
  }

  const request = (async () => {
    void signal; // intentionally unused — see docstring above
    const data = await fetchAuthorDetailsByCanonicalId(id);
    setCachedAuthorDetails(id, data);
    return data;
  })();

  inflightDetailsRequests.set(cacheKey, request);
  return request.finally(() => {
    if (inflightDetailsRequests.get(cacheKey) === request) {
      inflightDetailsRequests.delete(cacheKey);
    }
  });
}
