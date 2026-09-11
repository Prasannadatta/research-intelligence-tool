/**
 * Stable author identity keys for client-side selected-hit exclusion.
 * Never uses display name.
 */

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const ORCID_RE = /^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/i;

function normalizeOrcid(value) {
  const text = String(value || "")
    .trim()
    .replace(/^https?:\/\/orcid\.org\//i, "")
    .replace(/\/$/, "");
  if (!ORCID_RE.test(text)) {
    return "";
  }
  return text.slice(0, -1) + text.slice(-1).toUpperCase();
}

function addCanonical(keys, value) {
  const id = String(value || "").trim();
  if (UUID_RE.test(id)) {
    keys.add(`canonical:${id}`);
  }
}

/**
 * Collect OpenAlex / ORCID / canonical identity keys for an author row.
 */
export function authorIdentityKeys(item) {
  const keys = new Set();
  if (!item || typeof item !== "object") {
    return keys;
  }

  addCanonical(keys, item.canonical_author_id);
  addCanonical(keys, item.id);
  addCanonical(keys, item.result_id);

  const openalexId = String(item.openalex_id || "").trim();
  if (openalexId) {
    keys.add(`openalex:${openalexId}`);
  }

  const orcid = normalizeOrcid(item.orcid);
  if (orcid) {
    keys.add(`orcid:${orcid}`);
  }

  // Analysis / saved-search author rows store provider identity at the top level.
  const topProvider = String(item.provider || "")
    .trim()
    .toLowerCase();
  const topProviderAuthorId = String(item.provider_author_id || "").trim();
  if (topProvider && topProviderAuthorId) {
    if (topProvider === "orcid") {
      const normalized = normalizeOrcid(topProviderAuthorId);
      if (normalized) {
        keys.add(`orcid:${normalized}`);
      }
    } else {
      keys.add(`${topProvider}:${topProviderAuthorId}`);
    }
  }

  const records = Array.isArray(item.source_records) ? item.source_records : [];
  for (const row of records) {
    const provider = String(row?.provider || "")
      .trim()
      .toLowerCase();
    const providerAuthorId = String(row?.provider_author_id || "").trim();
    if (!provider || !providerAuthorId) {
      continue;
    }
    if (provider === "orcid") {
      const normalized = normalizeOrcid(providerAuthorId);
      if (normalized) {
        keys.add(`orcid:${normalized}`);
      }
      continue;
    }
    keys.add(`${provider}:${providerAuthorId}`);
  }

  return keys;
}

/** Build a Set of identity keys covering every selected author. */
export function selectedAuthorIdentityKeySet(selectedAuthors) {
  const keys = new Set();
  if (!Array.isArray(selectedAuthors)) {
    return keys;
  }
  for (const item of selectedAuthors) {
    for (const key of authorIdentityKeys(item)) {
      keys.add(key);
    }
  }
  return keys;
}

/** True when the search hit shares any stable identity with a selected author. */
export function isAuthorAlreadySelected(item, selectedKeySet) {
  if (!(selectedKeySet instanceof Set) || selectedKeySet.size === 0) {
    return false;
  }
  for (const key of authorIdentityKeys(item)) {
    if (selectedKeySet.has(key)) {
      return true;
    }
  }
  return false;
}
