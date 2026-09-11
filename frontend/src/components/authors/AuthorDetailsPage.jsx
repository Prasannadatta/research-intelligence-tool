import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Box,
  Button,
  Chip,
  Collapse,
  Link,
  Skeleton,
  Stack,
  Typography,
} from "@mui/material";
import ArrowBackRoundedIcon from "@mui/icons-material/ArrowBackRounded";

import { analysisPageLayoutSx } from "../../layout/pageLayout";
import {
  enrichAuthorSummary,
  fetchAuthorDetails,
  getCachedAuthorDetails,
  setCachedAuthorDetails,
} from "./authorSummaryCache";
import {
  formatAffiliationLine,
  formatNumberValue,
  formatProviderLabel,
  formatProviderList,
  formatTextValue,
  formatUpdatedAt,
  getCurrentInstitution,
  getPreviousInstitutions,
  getProviderIds,
} from "./authorSummaryDisplay";

function Section({ title, children, testId }) {
  return (
    <Box
      component="section"
      data-testid={testId}
      sx={{
        pt: 2.5,
        mt: 2.5,
        borderTop: "1px solid",
        borderColor: "divider",
      }}
    >
      <Typography variant="subtitle2" sx={{ mb: 1.25, fontWeight: 600 }}>
        {title}
      </Typography>
      {children}
    </Box>
  );
}

function EmptyNote({ children }) {
  return (
    <Typography variant="body2" color="text.secondary">
      {children}
    </Typography>
  );
}

function MetaRow({ label, children }) {
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: { xs: "1fr", sm: "140px 1fr" },
        columnGap: 2,
        rowGap: 0.25,
        alignItems: "baseline",
        py: 0.35,
      }}
    >
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
      <Box sx={{ minWidth: 0 }}>{children}</Box>
    </Box>
  );
}

function SourceChips({ sources }) {
  const labels = (Array.isArray(sources) ? sources : [])
    .map(formatProviderLabel)
    .filter(Boolean);
  if (labels.length === 0) {
    return null;
  }
  return (
    <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap" sx={{ mt: 0.5 }}>
      {labels.map((label) => (
        <Chip key={label} label={label} size="small" variant="outlined" sx={{ height: 22 }} />
      ))}
    </Stack>
  );
}

function IdValue({ value }) {
  if (!value) {
    return (
      <Typography variant="body2" color="text.secondary">
        —
      </Typography>
    );
  }
  return (
    <Typography variant="body2" sx={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", overflowWrap: "anywhere" }}>
      {value}
    </Typography>
  );
}

function AuthorDetailsSkeleton() {
  return (
    <Box data-testid="author-details-loading">
      <Skeleton width={120} height={32} sx={{ mb: 1 }} />
      <Skeleton width="40%" height={36} sx={{ mb: 1 }} />
      <Skeleton width="55%" height={22} sx={{ mb: 2 }} />
      <Skeleton variant="rounded" height={72} sx={{ mb: 2 }} />
      <Skeleton variant="rounded" height={120} sx={{ mb: 2 }} />
      <Skeleton variant="rounded" height={160} />
    </Box>
  );
}

function enrichmentStatusLabel(details) {
  const pending = details?.enrichment?.pending;
  if (Array.isArray(pending) && pending.length > 0) {
    const labels = pending.map(formatProviderLabel).filter(Boolean).join(", ");
    return labels ? `Refreshing ${labels}…` : "Refreshing enrichment…";
  }
  const sources = details?.enrichment?.sources;
  if (sources && typeof sources === "object") {
    const ready = Object.entries(sources)
      .filter(([, ok]) => ok)
      .map(([key]) => formatProviderLabel(key))
      .filter(Boolean);
    if (ready.length > 0) {
      return `Enriched: ${ready.join(", ")}`;
    }
  }
  return null;
}

function AuthorDetailsPage() {
  const navigate = useNavigate();
  const { id: authorIdParam } = useParams();
  const authorId = String(authorIdParam || "").trim();

  const [details, setDetails] = useState(() => getCachedAuthorDetails(authorId));
  const [loading, setLoading] = useState(() => !getCachedAuthorDetails(authorId));
  const [error, setError] = useState(null);
  const [enriching, setEnriching] = useState(false);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    if (!authorId) {
      setDetails(null);
      setLoading(false);
      setError("Author not found.");
      return undefined;
    }

    let cancelled = false;
    const cached = getCachedAuthorDetails(authorId);
    if (cached) {
      setDetails(cached);
      setLoading(false);
      setError(null);
    } else {
      setLoading(true);
      setError(null);
    }

    // Do not AbortController the shared details fetch — StrictMode remounts would
    // cancel the only in-flight request and leave loading stuck. Ignore stale
    // results via `cancelled` instead. Enrichment is always non-blocking.
    fetchAuthorDetails(authorId)
      .then((data) => {
        if (cancelled) {
          return;
        }
        setDetails(data);
        setLoading(false);
        setError(null);

        if (data?.enrichment?.pending?.length) {
          setEnriching(true);
          enrichAuthorSummary(
            { canonicalAuthorId: authorId },
            { summary: data },
          ).then((enriched) => {
            if (cancelled || !enriched) {
              return;
            }
            const merged = {
              ...data,
              ...enriched,
              grants: data.grants,
              publications: data.publications,
              stored_publication_count: data.stored_publication_count,
            };
            setCachedAuthorDetails(authorId, merged);
            setDetails(merged);
          }).catch(() => {
            // Enrichment failures must not block or blank the page.
          }).finally(() => {
            if (!cancelled) {
              setEnriching(false);
            }
          });
        } else if (!cancelled) {
          setEnriching(false);
        }
      })
      .catch((err) => {
        if (cancelled) {
          return;
        }
        // Defensive: cancel noise must never leave the skeleton forever.
        if (err?.name === "CanceledError" || err?.code === "ERR_CANCELED") {
          setLoading(false);
          setError("Author details could not be loaded.");
          return;
        }
        setError("Author details could not be loaded.");
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [authorId, retryToken]);

  const providerIds = useMemo(() => getProviderIds(details), [details]);
  const currentInstitution = useMemo(() => getCurrentInstitution(details), [details]);
  const previousInstitutions = useMemo(() => getPreviousInstitutions(details), [details]);
  const statusLabel = useMemo(() => {
    if (enriching) {
      const pending = details?.enrichment?.pending || [];
      const labels = pending.map(formatProviderLabel).filter(Boolean).join(", ");
      return labels ? `Refreshing ${labels}…` : "Refreshing enrichment…";
    }
    return enrichmentStatusLabel(details);
  }, [details, enriching]);

  const handleBack = () => {
    if (window.history.length > 1) {
      navigate(-1);
      return;
    }
    navigate("/analyze/authors");
  };

  const handleRetryDetails = () => {
    setRetryToken((value) => value + 1);
  };

  return (
    <Box sx={analysisPageLayoutSx} data-testid="author-details-page">
      <Button
        startIcon={<ArrowBackRoundedIcon />}
        onClick={handleBack}
        sx={{ mb: 1.5, px: 0, minWidth: 0, textTransform: "none" }}
      >
        Back
      </Button>

      {loading && !details ? <AuthorDetailsSkeleton /> : null}

      {!loading && error && !details ? (
        <Box role="alert" sx={{ display: "grid", gap: 1, maxWidth: 420 }}>
          <Typography color="error">
            {error}
          </Typography>
          <Box>
            <Button
              size="small"
              variant="outlined"
              onClick={handleRetryDetails}
              sx={{ textTransform: "none" }}
            >
              Retry
            </Button>
          </Box>
        </Box>
      ) : null}

      <Collapse in={Boolean(details)} timeout={180}>
        {details ? (
          <Box>
            <Typography variant="h5" component="h1" sx={{ fontWeight: 600, mb: 0.5 }}>
              {formatTextValue(details.display_name, "Unknown author")}
            </Typography>

            {Array.isArray(details.aliases) && details.aliases.length > 0 ? (
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                Also known as: {details.aliases.join(" · ")}
              </Typography>
            ) : null}

            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mb: 1.5 }}>
              {(details.providers || []).map((provider) => {
                const label = formatProviderLabel(provider);
                return label ? (
                  <Chip key={provider} label={label} size="small" variant="outlined" />
                ) : null;
              })}
              {statusLabel ? (
                <Chip
                  label={statusLabel}
                  size="small"
                  color={enriching ? "default" : "success"}
                  variant="outlined"
                />
              ) : null}
              {formatUpdatedAt(details.updated_at) ? (
                <Typography variant="caption" color="text.secondary" sx={{ alignSelf: "center" }}>
                  Updated {formatUpdatedAt(details.updated_at)}
                </Typography>
              ) : null}
            </Stack>

            <Box
              data-testid="author-details-summary"
              sx={{
                display: "grid",
                gap: 0.25,
                py: 1,
              }}
            >
              <MetaRow label="OpenAlex">
                <IdValue value={providerIds.openalex[0] || null} />
              </MetaRow>
              <MetaRow label="ORCID">
                <IdValue value={providerIds.orcid[0] || details.orcid || null} />
              </MetaRow>
              <MetaRow label="Scopus">
                <IdValue value={providerIds.scopus[0] || null} />
              </MetaRow>
              <MetaRow label="Institution">
                <Typography variant="body2">
                  {formatTextValue(currentInstitution?.name, "—")}
                </Typography>
                {currentInstitution?.department ? (
                  <Typography variant="body2" color="text.secondary">
                    {currentInstitution.department}
                  </Typography>
                ) : null}
                <SourceChips sources={currentInstitution?.sources} />
              </MetaRow>
            </Box>

            <Section title="Affiliations" testId="author-details-affiliations">
              {!currentInstitution && previousInstitutions.length === 0 ? (
                <EmptyNote>No affiliation data available.</EmptyNote>
              ) : (
                <Stack spacing={1.25}>
                  {currentInstitution ? (
                    <Box>
                      <Typography variant="body2" color="text.secondary" sx={{ mb: 0.25 }}>
                        Current
                      </Typography>
                      <Typography variant="body2">
                        {formatAffiliationLine(currentInstitution) || "—"}
                      </Typography>
                      <SourceChips sources={currentInstitution.sources} />
                    </Box>
                  ) : null}
                  {previousInstitutions.length > 0 ? (
                    <Box>
                      <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                        Previous
                      </Typography>
                      <Stack spacing={1}>
                        {previousInstitutions.map((row, index) => (
                          <Box key={`${row.id || row.name || "aff"}-${index}`}>
                            <Typography variant="body2">
                              {formatAffiliationLine(row) || "—"}
                            </Typography>
                            <SourceChips sources={row.sources} />
                          </Box>
                        ))}
                      </Stack>
                    </Box>
                  ) : null}
                </Stack>
              )}
            </Section>

            <Section title="Research areas" testId="author-details-topics">
              {Array.isArray(details.topics) && details.topics.length > 0 ? (
                <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
                  {details.topics.map((topic) => (
                    <Chip key={topic} label={topic} size="small" variant="outlined" />
                  ))}
                </Stack>
              ) : (
                <EmptyNote>No research areas available.</EmptyNote>
              )}
            </Section>

            <Section title="Metrics" testId="author-details-metrics">
              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: { xs: "1fr", sm: "repeat(3, minmax(0, 1fr))" },
                  gap: 1.5,
                }}
              >
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Publications
                  </Typography>
                  <Typography variant="h6" sx={{ fontWeight: 600 }}>
                    {formatNumberValue(details.works_count)}
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Citations
                  </Typography>
                  <Typography variant="h6" sx={{ fontWeight: 600 }}>
                    {formatNumberValue(details.citation_count)}
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    h-index
                  </Typography>
                  <Typography variant="h6" sx={{ fontWeight: 600 }}>
                    {formatNumberValue(details.h_index)}
                  </Typography>
                </Box>
              </Box>
              {formatProviderList(details.providers) ? (
                <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
                  Sources: {formatProviderList(details.providers)}
                </Typography>
              ) : null}
            </Section>

            <Section title="Grants" testId="author-details-grants">
              {Array.isArray(details.grants) && details.grants.length > 0 ? (
                <Stack spacing={1}>
                  {details.grants.map((grant) => (
                    <Box key={`${grant.provider || "grant"}-${grant.award_id}`}>
                      <Typography variant="body2" sx={{ fontWeight: 500 }}>
                        {grant.award_id || "Unknown award"}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        {[
                          grant.funder_name,
                          grant.publication_count
                            ? `${grant.publication_count} publication${grant.publication_count === 1 ? "" : "s"}`
                            : null,
                        ]
                          .filter(Boolean)
                          .join(" · ") || "—"}
                      </Typography>
                      <SourceChips sources={grant.provider ? [grant.provider] : []} />
                    </Box>
                  ))}
                </Stack>
              ) : (
                <EmptyNote>No grant/funding links in the stored publication corpus.</EmptyNote>
              )}
            </Section>

            <Section title="Publications" testId="author-details-publications">
              {Array.isArray(details.publications) && details.publications.length > 0 ? (
                <>
                  {details.stored_publication_count != null ? (
                    <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
                      Showing top {details.publications.length} of{" "}
                      {formatNumberValue(details.stored_publication_count)} stored works
                    </Typography>
                  ) : null}
                  <Stack spacing={1.25}>
                    {details.publications.map((pub) => {
                      const href = pub.doi
                        ? `https://doi.org/${String(pub.doi).replace(/^https?:\/\/(dx\.)?doi\.org\//i, "")}`
                        : pub.url || null;
                      return (
                        <Box key={pub.id}>
                          <Typography variant="body2" sx={{ fontWeight: 500 }}>
                            {href ? (
                              <Link href={href} target="_blank" rel="noopener noreferrer" underline="hover" color="inherit">
                                {pub.title || "Untitled work"}
                              </Link>
                            ) : (
                              pub.title || "Untitled work"
                            )}
                          </Typography>
                          <Typography variant="body2" color="text.secondary">
                            {[
                              pub.publication_year,
                              pub.journal,
                              pub.citation_count != null
                                ? `${formatNumberValue(pub.citation_count)} citations`
                                : null,
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </Typography>
                          <SourceChips sources={pub.providers} />
                        </Box>
                      );
                    })}
                  </Stack>
                </>
              ) : (
                <EmptyNote>
                  No stored publications yet. Analyze this author to sync works into the local corpus.
                </EmptyNote>
              )}
            </Section>
          </Box>
        ) : null}
      </Collapse>
    </Box>
  );
}

export default AuthorDetailsPage;
