import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Paper,
  Skeleton,
  Snackbar,
  Typography,
} from "@mui/material";

import {
  formatInsightsJobProgressMessage,
  releaseInsightsRequest,
  resetInsightsRequest,
  retainInsightsRequest,
  subscribeInsightsJobProgress,
} from "./authorInsightsRequestCache";
import AuthorPublicationFilters from "../../components/authors/AuthorPublicationFilters";
import AuthorIncludedSelector from "../../components/authors/AuthorIncludedSelector";
import { AuthorInfoPopoverProvider } from "../../components/authors/AuthorInfoPopover";
import {
  clonePublicationFilters,
  emptyPublicationFilters,
  removeFilterChip,
  toPublicationFiltersPayload,
} from "../../components/authors/publicationFilters";
import AuthorInsightsHeader from "./components/AuthorInsightsHeader";
import InsightsMetricCards from "./components/InsightsMetricCards";
import AuthorCombinationChart from "./components/AuthorCombinationChart";
import AuthorCombinationTable from "./components/AuthorCombinationTable";
import CollaborationYearChart from "./components/CollaborationYearChart";
import ParticipationDonuts from "./components/ParticipationDonuts";
import InstitutionNetworkPreview from "./components/InstitutionNetworkPreview";
import InstitutionPartnershipTable from "./components/InstitutionPartnershipTable";
import CitationActivityChart from "./components/CitationActivityChart";
import TopJournalsTable from "./components/TopJournalsTable";
import PublicationExclusionManager from "./components/PublicationExclusionManager";
import { analysisPageLayoutSx, dashboardRowSx } from "../../layout/pageLayout";

const pageLayoutSx = analysisPageLayoutSx;
const sectionHeadingSx = { mb: 1.5 };
const sectionTitleSx = { mb: 0.5, fontSize: "1.1rem", fontWeight: 700 };
const sectionDescriptionSx = { fontSize: "0.85rem", fontWeight: 400 };

const EMPTY_FACETS = { sources: [], institutions: [], venues: [], grants: [], authors: [] };

function normalizeAuthorArray(authors) {
  const seen = new Set();
  return (Array.isArray(authors) ? authors : [])
    .map((author) => ({
      canonical_author_id: String(author?.canonical_author_id || "").trim(),
      display_name: String(author?.display_name || author?.name || "").trim(),
      provider: author?.provider ? String(author.provider).toLowerCase() : undefined,
      provider_author_id: author?.provider_author_id
        ? String(author.provider_author_id)
        : undefined,
    }))
    .filter((author) => {
      if (!author.canonical_author_id || seen.has(author.canonical_author_id)) {
        return false;
      }
      seen.add(author.canonical_author_id);
      return true;
    });
}

function normalizedAuthorSelection(locationState) {
  return normalizeAuthorArray(
    locationState?.originalAuthors || locationState?.authors || [],
  );
}

function initialActiveAuthorIds(locationState, originalAuthors) {
  const active = normalizeAuthorArray(locationState?.activeAuthors || locationState?.authors || []);
  const ids = active.length > 0 ? active : originalAuthors;
  return new Set(ids.map((author) => author.canonical_author_id).filter(Boolean));
}

function filtersDraftFromPayload(filters) {
  const empty = emptyPublicationFilters();
  return {
    ...empty,
    fromYear: filters?.from_year != null ? String(filters.from_year) : "",
    toYear: filters?.to_year != null ? String(filters.to_year) : "",
    sources: Array.isArray(filters?.sources) ? [...filters.sources] : [],
    institutions: Array.isArray(filters?.institutions)
      ? filters.institutions.map((value) => ({ value, label: value }))
      : [],
    venues: Array.isArray(filters?.venues)
      ? filters.venues.map((value) => ({ value, label: value }))
      : [],
    grants: Array.isArray(filters?.grant_numbers)
      ? filters.grant_numbers.map((value) => ({
          grant_number: value,
          publication_count: null,
        }))
      : [],
    authors: [],
  };
}

function normalizedFilters(filters) {
  return {
    from_year: filters?.from_year ?? null,
    to_year: filters?.to_year ?? null,
    sources: Array.isArray(filters?.sources) ? filters.sources : [],
    institutions: Array.isArray(filters?.institutions) ? filters.institutions : [],
    venues: Array.isArray(filters?.venues) ? filters.venues : [],
    grant_numbers: Array.isArray(filters?.grant_numbers)
      ? filters.grant_numbers
      : [],
  };
}

function buildInsightsRequestKey(authors, filters, excludedWorkIds) {
  const authorKey = [...authors]
    .map((author) => author.canonical_author_id)
    .filter(Boolean)
    .sort()
    .join(",");
  const filterKey = JSON.stringify(normalizedFilters(filters));
  const excludedKey = [...excludedWorkIds].filter(Boolean).sort().join(",");
  return `${authorKey}::${excludedKey}::${filterKey}`;
}

function isAbortError(error) {
  return (
    error?.name === "AbortError" ||
    error?.name === "CanceledError" ||
    error?.code === "ERR_CANCELED"
  );
}

function errorMessage(error) {
  return (
    error?.response?.data?.detail ||
    error?.message ||
    "Unable to load author insights."
  );
}

function facetLookup(rows, query, labelForRow) {
  const needle = String(query || "").trim().toLowerCase();
  const filtered = needle
    ? rows.filter((row) => labelForRow(row).toLowerCase().includes(needle))
    : rows;
  return Promise.resolve(filtered.slice(0, 25));
}

function institutionQualityCaption(quality) {
  if (!quality || !quality.total_works) {
    return null;
  }
  return `Institution analysis is based on ${quality.works_with_any_institution} of ${quality.total_works} publications with available affiliation metadata.`;
}

function InsightsJobStatusSnackbars({
  progressOpen,
  progressMessage,
  successOpen,
  errorOpen,
  errorText,
  onCloseSuccess,
  onCloseError,
  onRetry,
}) {
  return (
    <>
      <Snackbar
        open={progressOpen}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        data-testid="insights-job-progress-snackbar"
      >
        <Alert
          severity="info"
          variant="filled"
          icon={<CircularProgress size={18} color="inherit" />}
          sx={{ alignItems: "center" }}
        >
          {progressMessage}
        </Alert>
      </Snackbar>
      <Snackbar
        open={successOpen}
        autoHideDuration={4000}
        onClose={onCloseSuccess}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        data-testid="insights-job-success-snackbar"
      >
        <Alert severity="success" variant="filled" onClose={onCloseSuccess}>
          Collaboration Insights ready
        </Alert>
      </Snackbar>
      <Snackbar
        open={errorOpen}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        data-testid="insights-job-error-snackbar"
        onClose={onCloseError}
      >
        <Alert
          severity="error"
          variant="filled"
          onClose={onCloseError}
          action={
            <Button color="inherit" size="small" onClick={onRetry}>
              Retry
            </Button>
          }
        >
          {errorText}
        </Alert>
      </Snackbar>
    </>
  );
}

function InsightsLoadingState({ authorNames, onBack }) {
  return (
    <Box sx={pageLayoutSx} data-testid="author-insights-page">
      <AuthorInsightsHeader authorNames={authorNames} onBack={onBack} />
      <Box
        data-testid="author-insights-loading"
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "repeat(2, minmax(0, 1fr))",
            md: "repeat(4, minmax(0, 1fr))",
          },
          gap: 1.5,
          mb: 2.5,
        }}
      >
        {[0, 1, 2, 3].map((item) => (
          <Paper
            key={item}
            elevation={0}
            sx={{
              p: 1.75,
              border: "1px solid",
              borderColor: "divider",
              borderRadius: "16px",
            }}
          >
            <Skeleton width="70%" />
            <Skeleton width="45%" height={36} />
            <Skeleton width="55%" />
          </Paper>
        ))}
      </Box>
      {[220, 180, 260, 240, 180].map((height, index) => (
        <Paper
          key={height + index}
          elevation={0}
          sx={{
            mb: 2,
            p: 2.5,
            border: "1px solid",
            borderColor: "divider",
            borderRadius: "18px",
          }}
        >
          <Skeleton width="35%" />
          <Skeleton variant="rounded" height={height} sx={{ mt: 1.5 }} />
        </Paper>
      ))}
    </Box>
  );
}

function AuthorInsightsPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const requestSeqRef = useRef(0);

  const selectedAuthors = useMemo(
    () => normalizedAuthorSelection(location.state),
    [location.state],
  );
  const [activeAuthorIds, setActiveAuthorIds] = useState(() =>
    initialActiveAuthorIds(location.state, selectedAuthors),
  );
  const [excludedWorkIds, setExcludedWorkIds] = useState(
    () => new Set(Array.isArray(location.state?.excludedWorkIds) ? location.state.excludedWorkIds : []),
  );
  const [excludedWorksById] = useState(() => location.state?.excludedWorksById || {});
  const activeAuthors = useMemo(
    () => selectedAuthors.filter((author) => activeAuthorIds.has(author.canonical_author_id)),
    [activeAuthorIds, selectedAuthors],
  );
  const activeAuthorApiPayload = useMemo(
    () =>
      activeAuthors.map((author) => ({
        canonical_author_id: author.canonical_author_id,
        display_name: author.display_name,
      })),
    [activeAuthors],
  );
  const excludedWorkIdList = useMemo(
    () => [...excludedWorkIds].filter(Boolean).sort(),
    [excludedWorkIds],
  );

  const initialFilters = useMemo(
    () => filtersDraftFromPayload(location.state?.filters),
    [location.state?.filters],
  );
  const [draftFilters, setDraftFilters] = useState(initialFilters);
  const [appliedFilters, setAppliedFilters] = useState(initialFilters);
  const appliedFiltersPayload = useMemo(
    () => toPublicationFiltersPayload(appliedFilters),
    [appliedFilters],
  );
  const requestKey = useMemo(
    () => buildInsightsRequestKey(activeAuthors, appliedFiltersPayload, excludedWorkIds),
    [activeAuthors, appliedFiltersPayload, excludedWorkIds],
  );
  const authorNames = useMemo(
    () =>
      activeAuthors
        .map((author) => author.display_name || author.canonical_author_id)
        .filter(Boolean),
    [activeAuthors],
  );

  const [data, setData] = useState(null);
  const [facets, setFacets] = useState(EMPTY_FACETS);
  const [selectedCombinationId, setSelectedCombinationId] = useState(null);
  const [loading, setLoading] = useState(activeAuthors.length > 0);
  const [error, setError] = useState(null);
  const [retryToken, setRetryToken] = useState(0);
  const [jobProgress, setJobProgress] = useState(null);
  const [successSnackbarOpen, setSuccessSnackbarOpen] = useState(false);

  useEffect(() => {
    if (activeAuthors.length === 0) {
      return undefined;
    }

    const sequence = requestSeqRef.current + 1;
    requestSeqRef.current = sequence;
    let active = true;

    /* eslint-disable react-hooks/set-state-in-effect -- Fetch state must update immediately when the request key changes. */
    setLoading(true);
    setError(null);
    setJobProgress({ status: "queued", stage: "Preparing", percent: 0 });
    setSuccessSnackbarOpen(false);
    /* eslint-enable react-hooks/set-state-in-effect */

    const entry = retainInsightsRequest(requestKey, {
      authors: activeAuthorApiPayload,
      filters: appliedFiltersPayload,
      excludedWorkIds: excludedWorkIdList,
      retryIncompleteOnly: retryToken > 0,
    });
    const unsubscribeProgress = subscribeInsightsJobProgress(entry, (progress) => {
      if (!active || requestSeqRef.current !== sequence) {
        return;
      }
      setJobProgress((previous) => {
        const sameJob =
          previous?.jobId
          && progress?.jobId
          && String(previous.jobId) === String(progress.jobId);
        if (!sameJob) {
          return progress;
        }
        return {
          ...progress,
          percent: Math.max(Number(previous.percent) || 0, Number(progress.percent) || 0),
        };
      });
    });

    entry.promise
      .then((adapted) => {
        if (!active || requestSeqRef.current !== sequence) {
          return;
        }
        setData(adapted);
        setFacets(adapted.facets || EMPTY_FACETS);
        setSelectedCombinationId((current) => {
          if (current && adapted.combinations.some((row) => row.id === current)) {
            return current;
          }
          return adapted.defaultCombinationId || adapted.combinations[0]?.id || null;
        });
        setSuccessSnackbarOpen(true);
      })
      .catch((requestError) => {
        if (!active || requestSeqRef.current !== sequence || isAbortError(requestError)) {
          return;
        }
        setError(errorMessage(requestError));
        setData(null);
        setFacets(EMPTY_FACETS);
        setSuccessSnackbarOpen(false);
      })
      .finally(() => {
        if (!active || requestSeqRef.current !== sequence) {
          return;
        }
        setLoading(false);
      });

    return () => {
      active = false;
      unsubscribeProgress();
      releaseInsightsRequest(requestKey, entry);
    };
  }, [activeAuthors, activeAuthorApiPayload, appliedFiltersPayload, excludedWorkIdList, requestKey, retryToken]);

  const selectedCombination = useMemo(
    () =>
      data?.combinations.find((row) => row.id === selectedCombinationId) ||
      data?.combinations[0],
    [data?.combinations, selectedCombinationId],
  );

  const handleBack = () => {
    navigate("/analyze/authors", {
      state:
        selectedAuthors.length > 0
          ? {
              originalAuthors: selectedAuthors,
              activeAuthors,
              authors: activeAuthors,
              excludedWorkIds: excludedWorkIdList,
              excludedWorksById,
              filters: appliedFiltersPayload,
            }
          : undefined,
    });
  };

  const handleRetry = () => {
    resetInsightsRequest(requestKey);
    setRetryToken((current) => current + 1);
  };

  const statusSnackbars = (
    <InsightsJobStatusSnackbars
      progressOpen={loading && !error}
      progressMessage={formatInsightsJobProgressMessage(jobProgress)}
      successOpen={successSnackbarOpen && !loading && !error}
      errorOpen={Boolean(error)}
      errorText={error}
      onCloseSuccess={() => setSuccessSnackbarOpen(false)}
      onCloseError={() => {}}
      onRetry={handleRetry}
    />
  );

  const handleApplyFilters = (nextFilters) => {
    setDraftFilters(clonePublicationFilters(nextFilters));
    setAppliedFilters(clonePublicationFilters(nextFilters));
  };

  const handleResetFilters = () => {
    const empty = emptyPublicationFilters();
    setDraftFilters(empty);
    setAppliedFilters(empty);
  };

  const handleRemoveFilterChip = (chip) => {
    const next = removeFilterChip(appliedFilters, chip);
    setDraftFilters(clonePublicationFilters(next));
    setAppliedFilters(clonePublicationFilters(next));
  };

  const handleToggleAuthor = (authorId) => {
    setActiveAuthorIds((current) => {
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
    });
  };

  const handleRestoreExcluded = (workId) => {
    setExcludedWorkIds((current) => {
      const next = new Set(current);
      next.delete(workId);
      return next;
    });
  };

  const handleRestoreAllExcluded = () => {
    setExcludedWorkIds(new Set());
  };

  const authorSelectionControls = (
    <AuthorIncludedSelector
      authors={selectedAuthors}
      activeAuthorIds={activeAuthorIds}
      onToggleAuthor={handleToggleAuthor}
      getDisabled={(_authorId, checked) => checked && activeAuthorIds.size <= 1}
      title="Authors included"
      data-testid="insights-author-selection"
      sx={{ mb: 2 }}
    />
  );

  if (selectedAuthors.length === 0 || activeAuthors.length === 0) {
    return (
      <Box sx={pageLayoutSx} data-testid="author-insights-page">
        <Alert
          severity="info"
          data-testid="author-insights-no-authors"
          sx={{ mb: 2, borderRadius: "14px" }}
        >
          <Typography variant="subtitle1" fontWeight={600}>
            No authors selected
          </Typography>
          <Typography variant="body2">
            Return to Author Search and select authors to analyze.
          </Typography>
        </Alert>
        <Button onClick={handleBack} sx={{ textTransform: "none" }}>
          Back to Publications
        </Button>
      </Box>
    );
  }

  if (loading && !data) {
    return (
      <>
        <InsightsLoadingState authorNames={authorNames} onBack={handleBack} />
        {statusSnackbars}
      </>
    );
  }

  if (error) {
    return (
      <Box sx={pageLayoutSx} data-testid="author-insights-page">
        <AuthorInsightsHeader authorNames={authorNames} onBack={handleBack} />
        <Alert
          severity="error"
          data-testid="author-insights-error"
          sx={{ mb: 2, borderRadius: "14px" }}
          action={
            <Box sx={{ display: "flex", gap: 1 }}>
              <Button color="inherit" size="small" onClick={handleRetry}>
                Retry
              </Button>
              <Button color="inherit" size="small" onClick={handleBack}>
                Back to Publications
              </Button>
            </Box>
          }
        >
          {error}
        </Alert>
        {statusSnackbars}
      </Box>
    );
  }

  if (!data) {
    return null;
  }

  return (
    <AuthorInfoPopoverProvider>
      <Box sx={pageLayoutSx} data-testid="author-insights-page">
        <AuthorInsightsHeader authorNames={data.authorNames} onBack={handleBack} />

        {authorSelectionControls}

        <PublicationExclusionManager
          excludedWorkIds={excludedWorkIdList}
          excludedWorksById={excludedWorksById}
          onRestore={handleRestoreExcluded}
          onRestoreAll={handleRestoreAllExcluded}
          compact
        />

        <AuthorPublicationFilters
          authors={activeAuthors}
          draftFilters={draftFilters}
          appliedFilters={appliedFilters}
          onDraftChange={setDraftFilters}
          onApply={handleApplyFilters}
          onReset={handleResetFilters}
          onRemoveChip={handleRemoveFilterChip}
          facets={facets || data.facets || EMPTY_FACETS}
          disabled={loading}
          applying={loading}
          venueSearchFn={({ query }) =>
            facetLookup(facets?.venues || [], query, (row) => row.label || row.value || "")
          }
          secondarySearchFn={({ query }) =>
            facetLookup(
              facets?.grants || [],
              query,
              (row) => `${row.grant_number || ""} ${row.funder || ""}`,
            )
          }
          lookupContext={{ authors: activeAuthors }}
        />

        <Box sx={{ mb: { xs: 2, md: 2.5 } }}>
          <InsightsMetricCards metrics={data.metrics} />
        </Box>

        <Box sx={sectionHeadingSx}>
          <Typography variant="subtitle1" sx={sectionTitleSx}>
            Collaboration
          </Typography>
        </Box>
        <Box sx={{ ...dashboardRowSx, gridTemplateColumns: "minmax(0, 1fr)" }}>
          <AuthorCombinationChart
            combinations={data.combinations}
            selectedId={selectedCombination?.id}
            onSelect={setSelectedCombinationId}
          />
        </Box>
        <Box
          sx={{
            ...dashboardRowSx,
            gridTemplateColumns: {
              xs: "minmax(0, 1fr)",
              lg: "minmax(0, 0.45fr) minmax(0, 0.55fr)",
            },
            alignItems: "stretch",
          }}
        >
          <Box sx={{ minWidth: 0, height: "100%", display: "flex" }}>
            <CollaborationYearChart collaborationByYear={data.collaborationByYear} />
          </Box>
          <Box sx={{ minWidth: 0, height: "100%", display: "flex" }}>
            <AuthorCombinationTable
              combinations={data.combinations}
              selectedId={selectedCombination?.id}
              onSelect={setSelectedCombinationId}
            />
          </Box>
        </Box>

        <Box sx={sectionHeadingSx}>
          <Typography variant="subtitle1" sx={sectionTitleSx}>
            Participation and impact
          </Typography>
          <Typography
            variant="body2"
            color="text.secondary"
            sx={sectionDescriptionSx}
          >
            How selected authors, institutions, and citations appear across the publication set.
          </Typography>
        </Box>
        <Box
          sx={{
            ...dashboardRowSx,
            mb: { xs: 2, md: 2.5 },
          }}
        >
          <ParticipationDonuts participation={data.participation} />
        </Box>
        <Box sx={dashboardRowSx}>
          <CitationActivityChart citationActivity={data.citationActivity} />
        </Box>

        <Box sx={sectionHeadingSx}>
          <Typography variant="subtitle1" sx={sectionTitleSx}>
            Institution partnerships
          </Typography>
          <Typography
            variant="body2"
            color="text.secondary"
            sx={sectionDescriptionSx}
          >
            A preview of co-publishing institutions and their shared publication counts.
          </Typography>
          {institutionQualityCaption(data.institutionDataQuality) ? (
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.75 }}>
              {institutionQualityCaption(data.institutionDataQuality)}
            </Typography>
          ) : null}
        </Box>
        <Box
          data-testid="institution-partnerships-section"
          sx={{
            ...dashboardRowSx,
            gridTemplateColumns: { xs: "minmax(0, 1fr)", lg: "repeat(12, minmax(0, 1fr))" },
            alignItems: "stretch",
          }}
        >
          <Box sx={{ gridColumn: { xs: "1 / -1", lg: "span 8" }, minWidth: 0 }}>
            <InstitutionNetworkPreview network={data.institutionNetwork} />
          </Box>
          <Box sx={{ gridColumn: { xs: "1 / -1", lg: "span 4" }, minWidth: 0 }}>
            <InstitutionPartnershipTable partnerships={data.institutionPartnerships} />
          </Box>
        </Box>

        <Box sx={sectionHeadingSx}>
          <Typography variant="subtitle1" sx={sectionTitleSx}>
            Top journals / venues
          </Typography>
        </Box>
        <Box sx={{ ...dashboardRowSx, gridTemplateColumns: "minmax(0, 1fr)", mb: 0 }}>
          <TopJournalsTable journals={data.topJournals} />
        </Box>

      </Box>
      {statusSnackbars}
    </AuthorInfoPopoverProvider>
  );
}

export default AuthorInsightsPage;
