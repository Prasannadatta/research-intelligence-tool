/** Shared author summary/details display helpers (popover + details page). */

const PROVIDER_LABELS = {
  openalex: "OpenAlex",
  arxiv: "arXiv",
  orcid: "ORCID",
  scopus: "Scopus",
};

export function cleanText(value) {
  if (value == null) {
    return null;
  }
  const text = String(value).replace(/\s+/g, " ").trim();
  return text || null;
}

export function formatProviderLabel(value) {
  const text = cleanText(value);
  if (!text) {
    return null;
  }
  return PROVIDER_LABELS[text.toLowerCase()] || text;
}

export function formatProviderList(values) {
  if (!Array.isArray(values) || values.length === 0) {
    return null;
  }
  return values.map(formatProviderLabel).filter(Boolean).join(", ");
}

export function formatNumberValue(value) {
  if (value == null || value === "") {
    return "—";
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "—";
  }
  return numeric.toLocaleString();
}

export function formatTextValue(value, fallback = "N/A") {
  return cleanText(value) || fallback;
}

export function getCurrentInstitution(summary) {
  const institutions = Array.isArray(summary?.institutions) ? summary.institutions : [];
  return institutions.find((row) => row?.current) || institutions[0] || null;
}

export function getPreviousInstitutions(summary) {
  const institutions = Array.isArray(summary?.institutions) ? summary.institutions : [];
  const current = getCurrentInstitution(summary);
  return institutions.filter((row) => row && row !== current);
}

export function formatAffiliationYears(years) {
  if (!years || typeof years !== "object") {
    return null;
  }
  const from = years.from ?? years.from_;
  const to = years.to;
  if (from != null && to != null) {
    return `${from}–${to}`;
  }
  if (from != null) {
    return `${from}–`;
  }
  if (to != null) {
    return `–${to}`;
  }
  return null;
}

export function formatAffiliationLine(institution) {
  if (!institution || typeof institution !== "object") {
    return null;
  }
  const parts = [
    cleanText(institution.name),
    cleanText(institution.department),
    cleanText(institution.country_code),
    formatAffiliationYears(institution.years),
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : null;
}

export function formatUpdatedAt(value) {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return cleanText(value);
  }
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function getProviderIds(summary) {
  const raw = summary?.provider_ids || summary?.providerIds || {};
  return {
    openalex: Array.isArray(raw.openalex) ? raw.openalex.filter(Boolean) : [],
    orcid: Array.isArray(raw.orcid) ? raw.orcid.filter(Boolean) : [],
    scopus: Array.isArray(raw.scopus) ? raw.scopus.filter(Boolean) : [],
    arxiv: Array.isArray(raw.arxiv) ? raw.arxiv.filter(Boolean) : [],
  };
}

export function buildPublicationInstitution(author) {
  if (!author || typeof author !== "object") {
    return null;
  }
  const institutions = Array.isArray(author.institutions) ? author.institutions : [];
  const firstInstitution = institutions.find((row) => row);
  const countries = Array.isArray(author.countries) ? author.countries : [];

  let name = null;
  let department = cleanText(author.department);
  let countryCode = cleanText(countries[0]);
  let source = cleanText(author.affiliationSource || author.affiliation_source);

  if (typeof firstInstitution === "string") {
    name = cleanText(firstInstitution);
  } else if (firstInstitution && typeof firstInstitution === "object") {
    name = cleanText(
      firstInstitution.name
        || firstInstitution.display_name
        || firstInstitution.institution_name,
    );
    department = department || cleanText(firstInstitution.department);
    countryCode = countryCode || cleanText(firstInstitution.country_code || firstInstitution.country);
    source = source || cleanText(
      firstInstitution.affiliation_source || firstInstitution.source,
    );
  }

  if (!name && !department && !countryCode) {
    return null;
  }
  return {
    name,
    department,
    country_code: countryCode,
    source,
    publicationSpecific: true,
  };
}
