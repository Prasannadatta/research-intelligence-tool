const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function normalizeDoi(value) {
  if (value == null || value === "") {
    return null;
  }
  const text = String(value).trim();
  if (!text) {
    return null;
  }
  return text.replace(/^https?:\/\/(dx\.)?doi\.org\//i, "");
}

function normalizeProviderIds(raw) {
  const providerIds = { openalex: [], orcid: [], arxiv: [] };
  if (!raw || typeof raw !== "object") {
    return providerIds;
  }
  for (const key of ["openalex", "orcid", "arxiv"]) {
    const values = raw[key];
    if (Array.isArray(values)) {
      providerIds[key] = values.map((value) => String(value)).filter(Boolean);
    } else if (values) {
      providerIds[key] = [String(values)];
    }
  }
  return providerIds;
}

function authorCanonicalId(author) {
  if (!author || typeof author !== "object") {
    return null;
  }
  if (author.canonical_author_id) {
    return String(author.canonical_author_id);
  }
  if (author.canonicalAuthorId) {
    return String(author.canonicalAuthorId);
  }
  const id = author.id;
  if (id && UUID_RE.test(String(id))) {
    return String(id);
  }
  return null;
}

function buildProviderIds(author) {
  const providerIds = normalizeProviderIds(author?.provider_ids || author?.providerIds);
  if (author?.orcid && !providerIds.orcid.includes(String(author.orcid))) {
    providerIds.orcid.push(String(author.orcid));
  }
  const openalexId = author?.openalex_id || author?.id;
  if (
    openalexId &&
    /^A\d/i.test(String(openalexId)) &&
    !providerIds.openalex.includes(String(openalexId))
  ) {
    providerIds.openalex.push(String(openalexId));
  }
  return providerIds;
}

export function normalizeTableAuthor(author) {
  const name = author?.name || author?.display_name || "";
  const canonicalAuthorId = authorCanonicalId(author);
  const providerIds = buildProviderIds(author);
  const hasStableId = Boolean(canonicalAuthorId || providerIds.openalex.length > 0);
  return {
    name: String(name).trim(),
    canonicalAuthorId,
    providerIds,
    institutions: Array.isArray(author?.institutions) ? author.institutions : [],
    institutionIds: Array.isArray(author?.institution_ids)
      ? author.institution_ids
      : Array.isArray(author?.institutionIds)
        ? author.institutionIds
        : [],
    countries: Array.isArray(author?.countries) ? author.countries : [],
    department: author?.department || null,
    rawAffiliationText: author?.raw_affiliation_text || author?.rawAffiliationText || null,
    affiliationSource: author?.affiliation_source || author?.affiliationSource || null,
    affiliationConfidence: author?.affiliation_confidence ?? author?.affiliationConfidence ?? null,
    orcid: author?.orcid || providerIds.orcid[0] || null,
    provider: author?.provider || null,
    canonicalWorkId: author?.canonical_work_id || author?.canonicalWorkId || null,
    unresolved: Boolean(author?.unresolved ?? (!canonicalAuthorId && !hasStableId)),
  };
}

export function getWorkAuthors(work) {
  const authors = Array.isArray(work?.authors) ? work.authors : [];
  const canonicalWorkId = getWorkId(work);
  return authors
    .map((author) => normalizeTableAuthor({ ...author, canonical_work_id: canonicalWorkId }))
    .filter((author) => author.name);
}

export function getWorkDate(work) {
  if (work?.publication_date) {
    return String(work.publication_date);
  }
  if (work?.published_date) {
    return String(work.published_date);
  }
  if (work?.publication_year != null && !Number.isNaN(Number(work.publication_year))) {
    return String(work.publication_year);
  }
  if (work?.year != null && !Number.isNaN(Number(work.year))) {
    return String(work.year);
  }
  return null;
}

export function getWorkVenue(work) {
  return (
    work?.journal ||
    work?.venue ||
    work?.primary_source ||
    work?.source_name ||
    null
  );
}

const PROVIDER_LABELS = {
  openalex: "OpenAlex",
  arxiv: "arXiv",
};

export function getWorkProviders(work) {
  const providers = new Set();
  if (Array.isArray(work?.providers)) {
    for (const provider of work.providers) {
      if (provider) {
        providers.add(String(provider).toLowerCase());
      }
    }
  }
  if (work?.source) {
    providers.add(String(work.source).toLowerCase());
  }

  return [...providers].map((provider) => PROVIDER_LABELS[provider] || provider);
}

export function getWorkGrants(work) {
  const grants = [];
  const seen = new Set();

  const pushGrant = (raw) => {
    if (!raw) {
      return;
    }
    if (typeof raw === "string") {
      const grantNumber = String(raw).trim();
      if (!grantNumber) {
        return;
      }
      const key = grantNumber.toLowerCase().replace(/[^a-z0-9]+/g, "");
      if (!key || seen.has(key)) {
        return;
      }
      seen.add(key);
      grants.push({
        grant_number: grantNumber,
        normalized_grant_number: key,
        funder: null,
        agency: null,
        is_searched_grant: false,
      });
      return;
    }

    const grantNumber = String(
      raw.grant_number || raw.award_id || raw.funder_award_id || "",
    ).trim();
    if (!grantNumber) {
      return;
    }
    const key = String(
      raw.normalized_grant_number || grantNumber.toLowerCase().replace(/[^a-z0-9]+/g, ""),
    );
    if (!key || seen.has(key)) {
      return;
    }
    seen.add(key);
    grants.push({
      grant_number: grantNumber,
      normalized_grant_number: key,
      funder: raw.funder || raw.funder_name || null,
      agency: raw.agency || null,
      is_searched_grant: Boolean(raw.is_searched_grant),
      verified: Boolean(raw.verified),
      match_type: raw.match_type || null,
      provider: raw.provider || null,
    });
  };

  if (Array.isArray(work?.grants)) {
    for (const grant of work.grants) {
      pushGrant(grant);
    }
  }
  if (grants.length === 0 && work?.matched_grant_number) {
    pushGrant(work.matched_grant_number);
  }

  grants.sort((left, right) => {
    if (left.is_searched_grant !== right.is_searched_grant) {
      return left.is_searched_grant ? -1 : 1;
    }
    return String(left.grant_number).localeCompare(String(right.grant_number));
  });

  return grants;
}

export function getWorkId(work) {
  return work?.id || work?.canonical_work_id || work?.result_id || null;
}

export function getWorkLinks(work) {
  const workId = getWorkId(work);
  const doi = normalizeDoi(work?.doi);
  const arxivId =
    work?.arxiv_id ||
    (String(work?.source || "").toLowerCase() === "arxiv" ? work?.source_id : null);

  let arxivUrl = null;
  if (arxivId) {
    arxivUrl = `https://arxiv.org/abs/${arxivId}`;
  } else if (work?.entry_url && /arxiv\.org/i.test(String(work.entry_url))) {
    arxivUrl = String(work.entry_url);
  }

  const providerUrl = work?.url || work?.entry_url || null;

  return {
    internal: workId ? `/works/${workId}` : null,
    doi: doi ? `https://doi.org/${doi}` : null,
    arxiv: arxivUrl,
    provider: providerUrl,
  };
}

export function getWorkTitleHref(work) {
  const links = getWorkLinks(work);
  if (links.internal) {
    return { href: links.internal, external: false };
  }
  if (links.doi) {
    return { href: links.doi, external: true };
  }
  if (links.provider) {
    return { href: links.provider, external: true };
  }
  return null;
}

export function getWorkCitationCount(work) {
  const value = work?.citation_count ?? work?.cited_by_count;
  if (value == null || Number.isNaN(Number(value))) {
    return null;
  }
  return Number(value);
}
