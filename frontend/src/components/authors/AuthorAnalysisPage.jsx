import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  Fade,
  Pagination,
  Paper,
  Snackbar,
  Stack,
  Typography,
} from "@mui/material";
import ArrowBackRoundedIcon from "@mui/icons-material/ArrowBackRounded";
import InsightsOutlinedIcon from "@mui/icons-material/InsightsOutlined";
import BookmarkAddRoundedIcon from "@mui/icons-material/BookmarkAddRounded";
import BookmarkAddedRoundedIcon from "@mui/icons-material/BookmarkAddedRounded";
import BookmarkRemoveRoundedIcon from "@mui/icons-material/BookmarkRemoveRounded";

import {
  analysisModeForAuthors,
  buildAuthorPublicationsCacheKey,
  exportAuthorPublicationsCsv,
  fetchAuthorPublicationFacets,
  fetchAuthorPublications,
  toAnalysisAuthorPayload,
} from "../../api/analysisApi";
import AuthorPublicationsTable from "./AuthorPublicationsTable";
import AuthorIncludedSelector from "./AuthorIncludedSelector";
import AuthorPublicationTrendChart from "./AuthorPublicationTrendChart";
import AuthorPublicationFilters from "./AuthorPublicationFilters";
import usePublicationFacetPreview from "./usePublicationFacetPreview";
import DownloadCsvButton, { downloadCsvFromResponse } from "./DownloadCsvButton";
import { AuthorInfoPopoverProvider } from "./AuthorInfoPopover";
import { publicationsPageCache } from "./authorAnalysisCache";
import {
  FILTER_DEBOUNCE_MS,
  CORPUS_STATUS,
  activeAuthorIdsKey,
  analysisTitleForAuthors,
  corpusStatusLabel,
  deriveCorpusStatus,
  emptyStateCopy,
  formatProviderDedupCaption,
  getActiveAuthors,
  getInitialActiveAuthorIds,
  isAuthorCheckboxDisabled,
  providerDisplayLabel,
  providerRecordsKey,
  toggleActiveAuthor,
} from "./authorAnalysisPageLogic";
import {
  emptyFacets,
  emptyPublicationFilters,
  clonePublicationFilters,
  hasActivePublicationFilters,
  publicationFiltersKey,
  removeFilterChip,
  toPublicationFiltersPayload,
} from "./publicationFilters";
import {
  DEFAULT_PUBLICATION_SORT,
  isDefaultPublicationSort,
  normalizePublicationSort,
  publicationSortChipLabel,
  publicationSortKey,
} from "./publicationSorting";
import { getWorkDate, getWorkId } from "./authorPublicationHelpers";
import PublicationExclusionManager from "../../features/authorAnalysis/components/PublicationExclusionManager";
import { buildAuthorSavedSearchBody } from "../../features/savedSearches/savedSearchDisplay";
import {
  deleteSavedSearch,
  lookupSavedSearch,
  saveSavedSearch,
} from "../../features/savedSearches/savedSearchesApi";
import { analysisPageLayoutSx } from "../../layout/pageLayout";
import * as publicationStatsRequest from "./publicationStatsRequest";

const PAGE_SIZE = 20;

const CORPUS_STATUS_CHIP_SX = {
  [CORPUS_STATUS.VERIFIED]: { color: "success" },
  [CORPUS_STATUS.SYNCING]: { color: "info" },
  [CORPUS_STATUS.PARTIAL]: { color: "default" },
  [CORPUS_STATUS.RATE_LIMITED]: { color: "warning" },
  [CORPUS_STATUS.FAILED]: { color: "warning" },
};

function asProviderTotalCount(value) {
  if (value == null || value === "") {
    return null;
  }
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : null;
}

function asMatchedTotal(value) {
  if (value == null || value === "") {
    return null;
  }
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : null;
}

function formatPublicationRange({
  page,
  pageSize,
  itemCount,
  matchedTotal,
  corpusTotalCount,
  providerTotalCount,
  corpusComplete,
}) {
  if (!itemCount) {
    return null;
  }
  const offset = Math.max(0, (Math.max(1, page) - 1) * pageSize);
  const from = offset + 1;
  const to = offset + itemCount;
  const total =
    matchedTotal
    ?? (corpusComplete ? corpusTotalCount : null)
    ?? providerTotalCount;
  const totalLabel = total != null
    ? Number(total).toLocaleString()
    : null;
  const range = `${from.toLocaleString()}–${to.toLocaleString()}`;
  if (totalLabel != null) {
    return `Showing ${range} of ${totalLabel} unique publication${Number(total) === 1 ? "" : "s"}`;
  }
  return `Showing ${range} publication${itemCount === 1 ? "" : "s"}`;
}
const EMPTY_FILTERS_KEY = publicationFiltersKey(emptyPublicationFilters());

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

const pageLayoutSx = analysisPageLayoutSx;

function AuthorAnalysisPage() {
  const navigate = useNavigate();
  const location = useLocation();

  const originalAuthors = useMemo(() => {
    const fromState = location.state?.originalAuthors || location.state?.authors;
    if (Array.isArray(fromState) && fromState.length > 0) {
      return fromState
        .map((item) => toAnalysisAuthorPayload(item) || item)
        .filter(
          (item) =>
            item?.canonical_author_id &&
            item?.provider &&
            item?.provider_author_id &&
            item?.display_name,
        );
    }
    return [];
  }, [location.state]);

  const originalAuthorIds = useMemo(
    () => originalAuthors.map((author) => author.canonical_author_id),
    [originalAuthors],
  );

  const [activeAuthorIds, setActiveAuthorIds] = useState(() =>
    getInitialActiveAuthorIds(location.state?.activeAuthors || originalAuthors),
  );
  const [excludedWorkIds, setExcludedWorkIds] = useState(
    () => new Set(Array.isArray(location.state?.excludedWorkIds) ? location.state.excludedWorkIds : []),
  );
  const [selectedTableWorkIds, setSelectedTableWorkIds] = useState(() => new Set());
  const [excludedWorksById, setExcludedWorksById] = useState(
    () => location.state?.excludedWorksById || {},
  );

  const skipDebounceRef = useRef(true);

  useEffect(() => {
    skipDebounceRef.current = true;
    /* eslint-disable react-hooks/set-state-in-effect -- Router state is the source of truth when returning from Insights. */
    setActiveAuthorIds(getInitialActiveAuthorIds(location.state?.activeAuthors || originalAuthors));
    setExcludedWorkIds(
      new Set(Array.isArray(location.state?.excludedWorkIds) ? location.state.excludedWorkIds : []),
    );
    setExcludedWorksById(location.state?.excludedWorksById || {});
    setSelectedTableWorkIds(new Set());
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [location.state?.activeAuthors, location.state?.excludedWorkIds, location.state?.excludedWorksById, originalAuthors]);

  const activeAuthors = useMemo(
    () => getActiveAuthors(originalAuthors, activeAuthorIds),
    [originalAuthors, activeAuthorIds],
  );

  const mode = analysisModeForAuthors(activeAuthors);
  const recordsKey = useMemo(
    () => providerRecordsKey(activeAuthors),
    [activeAuthors],
  );
  const authorIds = useMemo(
    () => activeAuthors.map((author) => author.canonical_author_id),
    [activeAuthors],
  );
  const selectionKey = useMemo(
    () => activeAuthorIdsKey(activeAuthorIds),
    [activeAuthorIds],
  );

  const [draftFilters, setDraftFilters] = useState(() =>
    filtersDraftFromPayload(location.state?.filters),
  );
  const [appliedFilters, setAppliedFilters] = useState(() =>
    filtersDraftFromPayload(location.state?.filters),
  );
  const [publicationSort, setPublicationSort] = useState(DEFAULT_PUBLICATION_SORT);
  const [facets, setFacets] = useState(emptyFacets);
  const [corpusComplete, setCorpusComplete] = useState(false);
  const [statsLoading, setStatsLoading] = useState(false);
  const [statsError, setStatsError] = useState(null);
  const [statsProgress, setStatsProgress] = useState(null);
  const [corpusTotalCount, setCorpusTotalCount] = useState(null);
  const [statsRetryToken, setStatsRetryToken] = useState(0);
  const [statsReadySnackbarOpen, setStatsReadySnackbarOpen] = useState(false);

  const appliedFiltersKey = useMemo(
    () => publicationFiltersKey(appliedFilters),
    [appliedFilters],
  );
  const appliedFiltersPayload = useMemo(
    () => toPublicationFiltersPayload(appliedFilters),
    [appliedFilters],
  );
  const sortKey = useMemo(
    () => publicationSortKey(publicationSort),
    [publicationSort],
  );

  const [items, setItems] = useState([]);
  const [timeline, setTimeline] = useState(null);
  const [timelineError, setTimelineError] = useState(null);
  const [providerTotalCount, setProviderTotalCount] = useState(null);
  const [matchedTotal, setMatchedTotal] = useState(null);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [unsupported, setUnsupported] = useState(false);
  const [unsupportedReason, setUnsupportedReason] = useState(null);
  const [initialEmpty, setInitialEmpty] = useState(false);
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);
  const [saveStatus, setSaveStatus] = useState({
    saving: false,
    message: null,
    severity: "success",
  });
  const [matchedSavedSearch, setMatchedSavedSearch] = useState(null);

  const requestIdRef = useRef(0);
  const resetAbortRef = useRef(null);
  const applyInFlightRef = useRef(false);
  const selectionKeyRef = useRef(selectionKey);
  const sortRef = useRef(publicationSort);
  const sortKeyRef = useRef(sortKey);
  const requestKeyRef = useRef(`${selectionKey}::${appliedFiltersKey}::${sortKey}`);
  const filtersPayloadRef = useRef(appliedFiltersPayload);
  const appliedFiltersKeyRef = useRef(appliedFiltersKey);
  const appliedFiltersRef = useRef(appliedFilters);
  const hasLoadedOnceRef = useRef(false);
  const pageRef = useRef(1);
  const corpusCompleteRef = useRef(false);
  const boundToStoredCorpusRef = useRef(false);
  // Live-mode only: cursor required to request page N before the verified corpus exists.
  const pageCursorByPageRef = useRef(new Map([[1, null]]));
  const paginationStateRef = useRef({
    hasMore: false,
    page: 1,
    loading: false,
    unsupported: false,
    error: null,
    matchedTotal: null,
  });

  /* eslint-disable react-hooks/refs -- This page keeps request guards in refs so async pagination callbacks see the latest state. */
  selectionKeyRef.current = selectionKey;
  sortRef.current = publicationSort;
  sortKeyRef.current = sortKey;
  appliedFiltersKeyRef.current = appliedFiltersKey;
  appliedFiltersRef.current = appliedFilters;
  filtersPayloadRef.current = appliedFiltersPayload;
  requestKeyRef.current = `${selectionKey}::${appliedFiltersKey}::${sortKey}`;
  pageRef.current = page;
  corpusCompleteRef.current = corpusComplete;
  paginationStateRef.current = {
    hasMore,
    page,
    loading,
    unsupported,
    error,
    matchedTotal,
  };
  /* eslint-enable react-hooks/refs */

  const markLoadedOnce = useCallback((value) => {
    hasLoadedOnceRef.current = value;
    setHasLoadedOnce(value);
  }, []);

  const title = useMemo(() => analysisTitleForAuthors(activeAuthors), [activeAuthors]);
  const emptyCopy = useMemo(() => {
    const base = emptyStateCopy(mode);
    if (hasActivePublicationFilters(appliedFilters)) {
      return {
        heading: "No publications match these filters",
        body: "Try adjusting the year range, source, institution, venue, or grant filters.",
      };
    }
    return base;
  }, [mode, appliedFilters]);

  const resetAndLoad = useCallback(
    async ({
      filtersOverride,
      filtersKeyOverride,
      sortOverride,
      sortKeyOverride,
      preserveExisting: preserveExistingOption,
      forceRefresh = false,
      preserveCorpusStats = false,
      page: pageOverride = 1,
      resetPagination = true,
    } = {}) => {
      if (activeAuthors.length === 0) {
        setItems([]);
        setTimeline(null);
        setTimelineError(null);
        setFacets(emptyFacets());
        setProviderTotalCount(null);
        setMatchedTotal(null);
        setPage(1);
        pageRef.current = 1;
        pageCursorByPageRef.current = new Map([[1, null]]);
        setHasMore(false);
        applyInFlightRef.current = false;
        setUnsupported(false);
        setUnsupportedReason(null);
        setInitialEmpty(false);
        setError(null);
        markLoadedOnce(false);
        setLoading(false);
        return;
      }

      if (resetAbortRef.current) {
        resetAbortRef.current.abort();
      }

      const controller = new AbortController();
      resetAbortRef.current = controller;
      const requestId = ++requestIdRef.current;

      const filtersForRequest =
        filtersOverride !== undefined
          ? filtersOverride
          : filtersPayloadRef.current;
      const filtersKeyForCache =
        filtersKeyOverride !== undefined
          ? filtersKeyOverride
          : appliedFiltersKeyRef.current;
      const sortForRequest = normalizePublicationSort(
        sortOverride !== undefined ? sortOverride : sortRef.current,
      );
      const sortKeyForCache =
        sortKeyOverride !== undefined
          ? sortKeyOverride
          : publicationSortKey(sortForRequest);
      const fetchRequestKey = `${selectionKeyRef.current}::${filtersKeyForCache}::${sortKeyForCache}`;
      const targetPage = Math.max(1, Number(pageOverride) || 1);

      filtersPayloadRef.current = filtersForRequest;
      appliedFiltersKeyRef.current = filtersKeyForCache;
      sortRef.current = sortForRequest;
      sortKeyRef.current = sortKeyForCache;
      requestKeyRef.current = fetchRequestKey;

      if (resetPagination) {
        pageCursorByPageRef.current = new Map([[1, null]]);
      }

      const useStoredPaging = corpusCompleteRef.current;
      const pageCursor = useStoredPaging
        ? null
        : (pageCursorByPageRef.current.has(targetPage)
          ? pageCursorByPageRef.current.get(targetPage)
          : (targetPage === 1 ? null : undefined));
      if (!useStoredPaging && targetPage > 1 && pageCursor === undefined) {
        // Cannot jump ahead in live mode without the prior page cursor.
        return;
      }

      const preserveExisting =
        preserveExistingOption !== undefined
          ? preserveExistingOption
          : hasLoadedOnceRef.current;

      const cacheKey = buildAuthorPublicationsCacheKey({
        mode,
        canonicalAuthorIds: authorIds,
        providerRecordsKey: recordsKey,
        filtersKey: filtersKeyForCache,
        sortKey: sortKeyForCache,
        cursor: useStoredPaging ? `stored-page-${targetPage}` : (pageCursor ?? "*"),
        page: targetPage,
        limit: PAGE_SIZE,
      });

      const cached = forceRefresh
        ? null
        : publicationsPageCache.get(cacheKey);
      if (cached) {
        setItems(cached.items || []);
        if (!preserveCorpusStats) {
          setTimeline(null);
          setTimelineError(null);
          setFacets(emptyFacets());
          setCorpusComplete(false);
          setCorpusTotalCount(null);
          setStatsError(null);
        }
        setProviderTotalCount(asProviderTotalCount(cached.provider_total_count));
        setMatchedTotal(asMatchedTotal(cached.matched_total));
        setPage(cached.page || targetPage);
        pageRef.current = cached.page || targetPage;
        setHasMore(Boolean(cached.has_more));
        if (cached.next_cursor) {
          pageCursorByPageRef.current.set((cached.page || targetPage) + 1, cached.next_cursor);
        }
        setUnsupported(Boolean(cached.unsupported));
        setUnsupportedReason(cached.unsupported_reason || null);
        setInitialEmpty(
          !cached.unsupported &&
            Array.isArray(cached.items) &&
            cached.items.length === 0,
        );
        setError(null);
        setLoading(false);
        markLoadedOnce(true);
        applyInFlightRef.current = false;
        return;
      }

      setLoading(true);
      setError(null);
      setTimelineError(null);
      setUnsupported(false);
      setUnsupportedReason(null);
      setInitialEmpty(false);
      if (!preserveExisting) {
        setItems([]);
        setProviderTotalCount(null);
        setMatchedTotal(null);
        if (!preserveCorpusStats) {
          setTimeline(null);
          setFacets(emptyFacets());
          setCorpusComplete(false);
          setCorpusTotalCount(null);
          setStatsError(null);
        }
      }
      setPage(targetPage);
      pageRef.current = targetPage;
      setHasMore(false);

      try {
        const response = await fetchAuthorPublications({
          authors: activeAuthors,
          originalAuthorIds,
          filters: filtersForRequest,
          sortBy: sortForRequest.sortBy,
          sortDirection: sortForRequest.sortDirection,
          limit: PAGE_SIZE,
          page: targetPage,
          cursor: useStoredPaging ? null : pageCursor,
          signal: controller.signal,
        });

        if (
          requestId !== requestIdRef.current ||
          fetchRequestKey !== requestKeyRef.current
        ) {
          return;
        }

        const pageItems = Array.isArray(response.items) ? response.items : [];
        const responsePage = response.pagination?.page || targetPage;
        const responseMatched = asMatchedTotal(response.pagination?.total);
        const responseHasMore = Boolean(response.has_more);
        const responseNextCursor = response.next_cursor ?? null;

        publicationsPageCache.set(cacheKey, {
          items: pageItems,
          timeline: null,
          facets: emptyFacets(),
          provider_total_count: asProviderTotalCount(response.provider_total_count),
          matched_total: responseMatched,
          page: responsePage,
          next_cursor: responseNextCursor,
          has_more: responseHasMore,
          unsupported: response.unsupported,
          unsupported_reason: response.unsupported_reason,
          corpus_source: response.pagination?.corpus_source || null,
        });

        setItems(pageItems);
        if (!preserveCorpusStats) {
          setTimeline(null);
          setTimelineError(null);
          setFacets(emptyFacets());
          setCorpusComplete(false);
          setCorpusTotalCount(null);
          setStatsError(null);
        }
        setProviderTotalCount(asProviderTotalCount(response.provider_total_count));
        setMatchedTotal(responseMatched);
        setPage(responsePage);
        pageRef.current = responsePage;
        setHasMore(responseHasMore);
        pageCursorByPageRef.current.set(responsePage, useStoredPaging ? null : pageCursor);
        if (responseNextCursor) {
          pageCursorByPageRef.current.set(responsePage + 1, responseNextCursor);
        }
        setUnsupported(Boolean(response.unsupported));
        setUnsupportedReason(response.unsupported_reason || null);
        setInitialEmpty(!response.unsupported && pageItems.length === 0);
        markLoadedOnce(true);
      } catch (err) {
        if (err?.name === "CanceledError" || err?.code === "ERR_CANCELED") {
          return;
        }
        if (
          requestId !== requestIdRef.current ||
          fetchRequestKey !== requestKeyRef.current
        ) {
          return;
        }
        setError(
          err?.response?.data?.detail ||
            "Publication analysis is temporarily unavailable. Please try again.",
        );
        if (!preserveExisting) {
          setItems([]);
          setProviderTotalCount(null);
          setMatchedTotal(null);
          if (!preserveCorpusStats) {
            setTimeline(null);
          }
        }
        setTimelineError(null);
        setHasMore(false);
      } finally {
        applyInFlightRef.current = false;
        if (
          requestId === requestIdRef.current &&
          fetchRequestKey === requestKeyRef.current
        ) {
          setLoading(false);
        }
      }
    },
    [
      activeAuthors,
      authorIds,
      markLoadedOnce,
      mode,
      originalAuthorIds,
      recordsKey,
    ],
  );

  const resetAndLoadRef = useRef(resetAndLoad);
  /* eslint-disable react-hooks/refs -- Pagination callbacks call the latest load function. */
  resetAndLoadRef.current = resetAndLoad;
  /* eslint-enable react-hooks/refs */

  const handlePageChange = useCallback(
    (_event, nextPage) => {
      const target = Math.max(1, Number(nextPage) || 1);
      if (target === pageRef.current || loading) {
        return;
      }
      setSelectedTableWorkIds(new Set());
      resetAndLoad({
        filtersOverride: filtersPayloadRef.current,
        filtersKeyOverride: appliedFiltersKeyRef.current,
        sortOverride: sortRef.current,
        sortKeyOverride: sortKeyRef.current,
        preserveExisting: false,
        forceRefresh: false,
        preserveCorpusStats: true,
        page: target,
        resetPagination: false,
      });
    },
    [loading, resetAndLoad],
  );

  const handleExportCsv = useCallback(async () => {
    const response = await exportAuthorPublicationsCsv({
      authors: activeAuthors,
      filters: appliedFiltersPayload,
    });
    await downloadCsvFromResponse(
      response,
      `author-publications-export.csv`,
    );
  }, [activeAuthors, appliedFiltersPayload]);

  const fetchFacetPreview = useCallback(
    ({ filters, signal }) =>
      fetchAuthorPublicationFacets({
        authors: activeAuthors,
        filters,
        signal,
      }),
    [activeAuthors],
  );

  // Facet option counts come from the complete-corpus stats job, not live provider crawls.
  usePublicationFacetPreview({
    enabled: false,
    requestKey: `${selectionKey}::${recordsKey}`,
    draftFilters,
    fetchFacets: fetchFacetPreview,
    onFacets: setFacets,
  });

  const statsRequestIdRef = useRef(0);

  useEffect(() => {
    if (!hasLoadedOnce || unsupported || activeAuthors.length === 0) {
      return undefined;
    }

    const controller = new AbortController();
    const requestId = ++statsRequestIdRef.current;
    setStatsLoading(true);
    setStatsError(null);
    setStatsProgress({
      status: "queued",
      stage: "Preparing",
      percent: 0,
      detail: { phase: "preparing" },
    });
    setStatsReadySnackbarOpen(false);
    setCorpusComplete(false);
    setTimeline(null);
    setFacets(emptyFacets());
    setCorpusTotalCount(null);

    const statsAuthors = activeAuthors.map((author) => ({
      canonical_author_id: author.canonical_author_id,
      display_name: author.display_name,
    }));

    publicationStatsRequest
      .fetchAuthorPublicationCorpusStats({
        authors: statsAuthors,
        filters: appliedFiltersPayload,
        retryIncompleteOnly: statsRetryToken > 0,
        signal: controller.signal,
        onProgress: (job) => {
          if (requestId !== statsRequestIdRef.current) {
            return;
          }
          const nextPercent = Number(job.progress_percent ?? job.progressPercent ?? 0);
          setStatsProgress((previous) => {
            const sameJob =
              previous?.jobId
              && (job.job_id || job.jobId)
              && String(previous.jobId) === String(job.job_id || job.jobId);
            const percent = sameJob
              ? Math.max(Number(previous.percent) || 0, nextPercent)
              : nextPercent;
            return {
              jobId: job.job_id || job.jobId || previous?.jobId || null,
              status: job.status || "running",
              stage: job.progress_stage || job.progressStage || "Preparing",
              percent,
              detail: job.progress_detail || job.progressDetail || null,
            };
          });
        },
      })
      .then((result) => {
        if (requestId !== statsRequestIdRef.current) {
          return;
        }
        setTimeline(result.timeline ?? null);
        setFacets(result.facets || emptyFacets());
        setCorpusTotalCount(
          Number.isFinite(Number(result.total_matching_publications))
            ? Number(result.total_matching_publications)
            : null,
        );
        setCorpusComplete(Boolean(result.corpus_complete));
        setStatsError(null);
        setStatsReadySnackbarOpen(Boolean(result.corpus_complete));
      })
      .catch((err) => {
        if (
          requestId !== statsRequestIdRef.current ||
          err?.name === "CanceledError" ||
          err?.code === "ERR_CANCELED"
        ) {
          return;
        }
        setCorpusComplete(false);
        setTimeline(null);
        setFacets(emptyFacets());
        setCorpusTotalCount(null);
        setStatsError(
          publicationStatsRequest.formatPublicationStatsErrorMessage(err),
        );
      })
      .finally(() => {
        if (requestId === statsRequestIdRef.current) {
          setStatsLoading(false);
        }
      });

    return () => {
      controller.abort();
    };
  }, [
    activeAuthors,
    appliedFiltersPayload,
    hasLoadedOnce,
    statsRetryToken,
    unsupported,
  ]);

  // Author selection drives the main fetch. Draft filter edits never fetch here.
  useEffect(() => {
    const startingFilters =
      !hasLoadedOnceRef.current && location.state?.filters
        ? filtersDraftFromPayload(location.state.filters)
        : emptyPublicationFilters();
    setDraftFilters(startingFilters);
    setAppliedFilters(startingFilters);
    setFacets(emptyFacets());

    const startingPayload = toPublicationFiltersPayload(startingFilters);
    const startingFiltersKey = publicationFiltersKey(startingFilters);
    filtersPayloadRef.current = startingPayload;
    appliedFiltersKeyRef.current = startingFiltersKey;
    appliedFiltersRef.current = startingFilters;
    requestKeyRef.current = `${selectionKey}::${startingFiltersKey}::${sortKeyRef.current}`;

    const runFetch = () => {
      resetAndLoadRef.current({
        filtersOverride: startingPayload,
        filtersKeyOverride: startingFiltersKey,
        sortOverride: sortRef.current,
        sortKeyOverride: sortKeyRef.current,
      });
    };

    // Defer scheduling so React StrictMode remounts cancel the first timer
    // before any network request starts (avoids overlapping SQLite writers).
    const delayMs = skipDebounceRef.current ? 0 : FILTER_DEBOUNCE_MS;
    const timer = setTimeout(() => {
      skipDebounceRef.current = false;
      runFetch();
    }, delayMs);
    return () => {
      clearTimeout(timer);
      if (resetAbortRef.current) {
        resetAbortRef.current.abort();
      }
    };
  }, [location.state?.filters, selectionKey]);

  const handleApplyFilters = useCallback(
    (nextFilters) => {
      if (applyInFlightRef.current) {
        return;
      }
      applyInFlightRef.current = true;
      const cloned = clonePublicationFilters(nextFilters);
      setDraftFilters(cloned);
      setAppliedFilters(cloned);
      appliedFiltersRef.current = cloned;
      const payload = toPublicationFiltersPayload(cloned);
      const key = publicationFiltersKey(cloned);
      filtersPayloadRef.current = payload;
      appliedFiltersKeyRef.current = key;
      requestKeyRef.current = `${selectionKeyRef.current}::${key}::${sortKeyRef.current}`;
      resetAndLoad({
        filtersOverride: payload,
        filtersKeyOverride: key,
        sortOverride: sortRef.current,
        sortKeyOverride: sortKeyRef.current,
        preserveExisting: true,
        forceRefresh: true,
        page: 1,
        resetPagination: true,
      });
    },
    [resetAndLoad],
  );

  const handleResetFilters = useCallback(() => {
    if (applyInFlightRef.current) {
      return;
    }
    applyInFlightRef.current = true;
    const empty = emptyPublicationFilters();
    setDraftFilters(empty);
    setAppliedFilters(empty);
    appliedFiltersRef.current = empty;
    const payload = toPublicationFiltersPayload(empty);
    filtersPayloadRef.current = payload;
    appliedFiltersKeyRef.current = EMPTY_FILTERS_KEY;
    requestKeyRef.current = `${selectionKeyRef.current}::${EMPTY_FILTERS_KEY}::${sortKeyRef.current}`;
    resetAndLoad({
      filtersOverride: payload,
      filtersKeyOverride: EMPTY_FILTERS_KEY,
      sortOverride: sortRef.current,
      sortKeyOverride: sortKeyRef.current,
      preserveExisting: true,
      forceRefresh: true,
      page: 1,
      resetPagination: true,
    });
  }, [resetAndLoad]);

  const handleRemoveChip = useCallback(
    (chip) => {
      if (applyInFlightRef.current) {
        return;
      }
      applyInFlightRef.current = true;
      const next = removeFilterChip(appliedFiltersRef.current, chip);
      const cloned = clonePublicationFilters(next);
      setDraftFilters(cloned);
      setAppliedFilters(cloned);
      appliedFiltersRef.current = cloned;
      const payload = toPublicationFiltersPayload(cloned);
      const key = publicationFiltersKey(cloned);
      filtersPayloadRef.current = payload;
      appliedFiltersKeyRef.current = key;
      requestKeyRef.current = `${selectionKeyRef.current}::${key}::${sortKeyRef.current}`;
      resetAndLoad({
        filtersOverride: payload,
        filtersKeyOverride: key,
        sortOverride: sortRef.current,
        sortKeyOverride: sortKeyRef.current,
        preserveExisting: true,
        forceRefresh: true,
        page: 1,
        resetPagination: true,
      });
    },
    [resetAndLoad],
  );

  const excludedWorkIdList = useMemo(
    () => [...excludedWorkIds].filter(Boolean).sort(),
    [excludedWorkIds],
  );

  const authorsForSavedSearch = useMemo(
    () => (activeAuthors.length > 0 ? activeAuthors : originalAuthors),
    [activeAuthors, originalAuthors],
  );

  const savedSearchLookupBody = useMemo(
    () =>
      buildAuthorSavedSearchBody({
        authors: authorsForSavedSearch,
        filters: appliedFiltersPayload,
        excludedWorkIds: excludedWorkIdList,
        mode,
      }),
    [appliedFiltersPayload, authorsForSavedSearch, excludedWorkIdList, mode],
  );

  useEffect(() => {
    if (authorsForSavedSearch.length === 0) {
      setMatchedSavedSearch(null);
      return undefined;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const match = await lookupSavedSearch(savedSearchLookupBody, {
          signal: controller.signal,
        });
        setMatchedSavedSearch(match);
      } catch (err) {
        if (err?.name === "CanceledError" || err?.code === "ERR_CANCELED") {
          return;
        }
        setMatchedSavedSearch(null);
      }
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [authorsForSavedSearch.length, savedSearchLookupBody]);

  const handleSaveSearch = useCallback(async () => {
    if (saveStatus.saving || authorsForSavedSearch.length === 0) {
      return;
    }
    if (matchedSavedSearch?.id) {
      setSaveStatus({ saving: true, message: null, severity: "success" });
      try {
        await deleteSavedSearch(matchedSavedSearch.id);
        setMatchedSavedSearch(null);
        setSaveStatus({ saving: false, message: "Unsaved", severity: "success" });
      } catch (err) {
        setSaveStatus({
          saving: false,
          message: err?.response?.data?.detail || "Could not unsave search.",
          severity: "error",
        });
      }
      return;
    }

    setSaveStatus({ saving: true, message: null, severity: "success" });
    try {
      const result = await saveSavedSearch(
        buildAuthorSavedSearchBody({
          authors: authorsForSavedSearch,
          filters: appliedFiltersPayload,
          excludedWorkIds: excludedWorkIdList,
          mode,
        }),
      );
      if (result?.outcome === "already_exists") {
        setMatchedSavedSearch(result);
        setSaveStatus({
          saving: false,
          message: "Already saved",
          severity: "info",
        });
      } else {
        setMatchedSavedSearch(result);
        setSaveStatus({ saving: false, message: "Saved", severity: "success" });
      }
    } catch (err) {
      setSaveStatus({
        saving: false,
        message: err?.response?.data?.detail || "Could not save search.",
        severity: "error",
      });
    }
  }, [
    appliedFiltersPayload,
    authorsForSavedSearch,
    excludedWorkIdList,
    matchedSavedSearch,
    mode,
    saveStatus.saving,
  ]);

  const selectedTableWorkIdList = useMemo(
    () => [...selectedTableWorkIds].filter(Boolean).sort(),
    [selectedTableWorkIds],
  );

  const handleTogglePublicationSelected = useCallback((workId) => {
    if (!workId) {
      return;
    }
    setSelectedTableWorkIds((current) => {
      const next = new Set(current);
      if (next.has(workId)) {
        next.delete(workId);
      } else {
        next.add(workId);
      }
      return next;
    });
  }, []);

  const handleToggleVisiblePublications = useCallback((visibleIds, checked) => {
    setSelectedTableWorkIds((current) => {
      const next = new Set(current);
      for (const id of visibleIds || []) {
        if (checked) {
          next.add(id);
        } else {
          next.delete(id);
        }
      }
      return next;
    });
  }, []);

  const handleExcludeSelected = useCallback(() => {
    if (selectedTableWorkIds.size === 0) {
      return;
    }
    setExcludedWorkIds((current) => {
      const next = new Set(current);
      selectedTableWorkIds.forEach((id) => next.add(id));
      return next;
    });
    setExcludedWorksById((current) => {
      const next = { ...current };
      for (const item of items) {
        const id = getWorkId(item);
        if (id && selectedTableWorkIds.has(id)) {
          next[id] = {
            title: item.title,
            publication_year: getWorkDate(item),
          };
        }
      }
      return next;
    });
    setSelectedTableWorkIds(new Set());
  }, [items, selectedTableWorkIds]);

  const handleRestoreExcluded = useCallback((workId) => {
    setExcludedWorkIds((current) => {
      const next = new Set(current);
      next.delete(workId);
      return next;
    });
  }, []);

  const handleRestoreAllExcluded = useCallback(() => {
    setExcludedWorkIds(new Set());
  }, []);

  const handleSortChange = useCallback(
    (nextSort) => {
      const normalized = normalizePublicationSort(nextSort);
      const nextSortKey = publicationSortKey(normalized);
      setPublicationSort(normalized);
      sortRef.current = normalized;
      sortKeyRef.current = nextSortKey;
      requestKeyRef.current = `${selectionKeyRef.current}::${appliedFiltersKeyRef.current}::${nextSortKey}`;
      setSelectedTableWorkIds(new Set());
      resetAndLoad({
        filtersOverride: filtersPayloadRef.current,
        filtersKeyOverride: appliedFiltersKeyRef.current,
        sortOverride: normalized,
        sortKeyOverride: nextSortKey,
        preserveExisting: false,
        forceRefresh: true,
        // Sort only reloads the table; keep corpus timeline/facets/counts.
        preserveCorpusStats: true,
        page: 1,
        resetPagination: true,
      });
    },
    [resetAndLoad],
  );

  // Once the verified corpus is ready, rebind the current page to stored works
  // so page/sort/filter share the same canonical set as timeline/facets.
  useEffect(() => {
    if (!corpusComplete) {
      boundToStoredCorpusRef.current = false;
      return;
    }
    if (!hasLoadedOnce || unsupported || boundToStoredCorpusRef.current) {
      return;
    }
    boundToStoredCorpusRef.current = true;
    pageCursorByPageRef.current = new Map([[1, null]]);
    resetAndLoadRef.current({
      filtersOverride: filtersPayloadRef.current,
      filtersKeyOverride: appliedFiltersKeyRef.current,
      sortOverride: sortRef.current,
      sortKeyOverride: sortKeyRef.current,
      preserveExisting: true,
      forceRefresh: true,
      preserveCorpusStats: true,
      page: pageRef.current,
      resetPagination: true,
    });
  }, [corpusComplete, hasLoadedOnce, unsupported]);

  const publicationRangeLabel = formatPublicationRange({
    page,
    pageSize: PAGE_SIZE,
    itemCount: items.length,
    matchedTotal,
    corpusTotalCount,
    providerTotalCount,
    corpusComplete,
  });

  const totalForPages =
    matchedTotal
    ?? (corpusComplete ? corpusTotalCount : null);
  const totalPages = totalForPages != null
    ? Math.max(1, Math.ceil(Number(totalForPages) / PAGE_SIZE))
    : Math.max(1, page + (hasMore ? 1 : 0));

  const uniqueCountForDedup =
    matchedTotal
    ?? (corpusComplete ? corpusTotalCount : null);
  const providerDedupCaption = formatProviderDedupCaption({
    uniqueCount: uniqueCountForDedup,
    providerTotalCount,
    providerLabel: providerDisplayLabel(activeAuthors),
  });

  const corpusStatus = deriveCorpusStatus({
    corpusComplete,
    statsLoading,
    statsError,
    statsProgress,
    hasLoadedOnce,
  });
  const corpusStatusText = corpusStatusLabel(corpusStatus);
  const statsProgressMessage = publicationStatsRequest.formatPublicationStatsProgressMessage(
    statsProgress,
  );
  const largeAuthorCohort = activeAuthors.length >= 20;
  const showStatsProgressSnackbar =
    statsLoading
    && !statsError
    && !largeAuthorCohort;
  const corpusStatusDetail =
    corpusStatus === CORPUS_STATUS.SYNCING
      ? statsProgressMessage
      : corpusStatus === CORPUS_STATUS.RATE_LIMITED || corpusStatus === CORPUS_STATUS.FAILED
        || corpusStatus === CORPUS_STATUS.PARTIAL
        ? (statsError || null)
        : null;
  const showInlineCorpusRetry =
    Boolean(statsError)
    && (corpusStatus === CORPUS_STATUS.FAILED
      || corpusStatus === CORPUS_STATUS.RATE_LIMITED
      || corpusStatus === CORPUS_STATUS.PARTIAL);
  const sortIsDefault = isDefaultPublicationSort(publicationSort);
  const showPublicationToolbar =
    !unsupported && (!loading || hasLoadedOnce) && !error && items.length > 0;

  const handleToggleAuthor = (authorId) => {
    setActiveAuthorIds((current) => toggleActiveAuthor(current, authorId));
  };

  const handleResetSort = () => {
    handleSortChange(DEFAULT_PUBLICATION_SORT);
  };

  const handleRetryStats = () => {
    setStatsRetryToken((value) => value + 1);
  };

  const handleBack = () => {
    navigate("/");
  };

  const handleOpenInsights = () => {
    const authorsForInsights = activeAuthors.length > 0 ? activeAuthors : originalAuthors;
    navigate("/analyze/authors/insights", {
      state: {
        originalAuthors,
        activeAuthors: authorsForInsights,
        authors: authorsForInsights,
        excludedWorkIds: excludedWorkIdList,
        excludedWorksById,
        filters: filtersPayloadRef.current,
      },
    });
  };

  const showFilters = originalAuthors.length > 0;

  const authorFilterSection = showFilters ? (
    <AuthorIncludedSelector
      authors={originalAuthors}
      activeAuthorIds={activeAuthorIds}
      onToggleAuthor={handleToggleAuthor}
      getDisabled={(authorId) => isAuthorCheckboxDisabled(activeAuthorIds, authorId)}
    />
  ) : null;

  if (originalAuthors.length === 0) {
    return (
      <Box sx={pageLayoutSx}>
        <Alert severity="info" sx={{ mb: 2 }}>
          Select one or more authors from search, then click Analyze.
        </Alert>
        <Button
          startIcon={<ArrowBackRoundedIcon />}
          onClick={handleBack}
          sx={{ textTransform: "none" }}
        >
          Return to author search
        </Button>
      </Box>
    );
  }

  return (
    <AuthorInfoPopoverProvider>
      <Box sx={pageLayoutSx}>
        <Box
          sx={{
            display: "flex",
            alignItems: { xs: "flex-start", md: "center" },
            justifyContent: "space-between",
            flexDirection: { xs: "column", md: "row" },
            gap: { xs: 1, md: 1.5 },
            mb: 1.25,
          }}
        >
          <Typography
            variant="h4"
            component="h1"
            fontWeight={700}
            sx={{ minWidth: 0, flex: "1 1 auto", wordBreak: "break-word" }}
          >
            {title}
          </Typography>
          <Box
            data-testid="author-analysis-page-actions"
            sx={{
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              justifyContent: { xs: "flex-start", md: "flex-end" },
              gap: 1,
              flexShrink: 0,
              alignSelf: { xs: "flex-start", md: "center" },
            }}
          >
            <Button
              startIcon={<ArrowBackRoundedIcon />}
              onClick={handleBack}
              sx={{
                textTransform: "none",
                color: "text.secondary",
                px: 0.5,
                whiteSpace: "nowrap",
                "&:hover": { bgcolor: "action.hover", color: "text.primary" },
              }}
            >
              Back to author selection
            </Button>
            <Button
              variant="outlined"
              startIcon={<InsightsOutlinedIcon />}
              onClick={handleOpenInsights}
              data-testid="open-author-insights"
              sx={{
                textTransform: "none",
                borderRadius: 999,
                flexShrink: 0,
                whiteSpace: "nowrap",
              }}
            >
              Insight
            </Button>
            {!unsupported ? (
              <DownloadCsvButton
                compact
                disabled={
                  loading ||
                  !hasLoadedOnce ||
                  unsupported ||
                  activeAuthors.length === 0 ||
                  !corpusComplete ||
                  items.length === 0
                }
                onExport={handleExportCsv}
              />
            ) : null}
            {!unsupported ? (
              <Button
                size="small"
                variant={matchedSavedSearch ? "contained" : "outlined"}
                color={matchedSavedSearch ? "primary" : "inherit"}
                disableElevation
                startIcon={
                  matchedSavedSearch ? (
                    saveStatus.saving ? (
                      <BookmarkRemoveRoundedIcon fontSize="small" />
                    ) : (
                      <BookmarkAddedRoundedIcon fontSize="small" />
                    )
                  ) : (
                    <BookmarkAddRoundedIcon fontSize="small" />
                  )
                }
                onClick={handleSaveSearch}
                disabled={
                  saveStatus.saving || authorsForSavedSearch.length === 0
                }
                sx={{ textTransform: "none", whiteSpace: "nowrap", flexShrink: 0 }}
              >
                {saveStatus.saving
                  ? matchedSavedSearch
                    ? "Unsaving..."
                    : "Saving..."
                  : matchedSavedSearch
                    ? "Saved"
                    : "Save search"}
              </Button>
            ) : null}
          </Box>
        </Box>

        {authorFilterSection}

        <Collapse in={Boolean(corpusStatusText)} timeout="auto" unmountOnExit={false}>
          <Stack
            direction={{ xs: "column", sm: "row" }}
            spacing={1}
            alignItems={{ xs: "flex-start", sm: "center" }}
            sx={{ mb: 1.25 }}
            data-testid="publication-corpus-status"
          >
            <Fade in={Boolean(corpusStatusText)}>
              <Chip
                size="small"
                variant="outlined"
                color={CORPUS_STATUS_CHIP_SX[corpusStatus]?.color || "default"}
                label={corpusStatusText}
                sx={{ fontWeight: 600 }}
              />
            </Fade>
            {corpusStatusDetail ? (
              <Typography
                variant="body2"
                color="text.secondary"
                sx={{ lineHeight: 1.4, flex: 1, minWidth: 0 }}
                data-testid="publication-corpus-status-detail"
              >
                {corpusStatusDetail}
              </Typography>
            ) : null}
            {showInlineCorpusRetry ? (
              <Button
                size="small"
                color="inherit"
                onClick={handleRetryStats}
                sx={{ textTransform: "none", flexShrink: 0 }}
              >
                Retry
              </Button>
            ) : null}
          </Stack>
        </Collapse>

        {selectedTableWorkIdList.length > 0 ? (
          <Paper
            elevation={0}
            data-testid="publication-selection-actions"
            sx={{
              mb: 1.5,
              p: 1.25,
              border: "1px solid",
              borderColor: "divider",
              borderRadius: "12px",
              display: "flex",
              alignItems: "center",
              gap: 1,
              flexWrap: "wrap",
            }}
          >
            <Typography variant="body2" fontWeight={600}>
              {selectedTableWorkIdList.length} selected
            </Typography>
            <Button
              size="small"
              variant="contained"
              disableElevation
              onClick={handleExcludeSelected}
              sx={{ textTransform: "none", borderRadius: 999 }}
            >
              Exclude from Insights
            </Button>
          </Paper>
        ) : null}

        <PublicationExclusionManager
          excludedWorkIds={excludedWorkIdList}
          excludedWorksById={excludedWorksById}
          onRestore={handleRestoreExcluded}
          onRestoreAll={handleRestoreAllExcluded}
        />

        {!unsupported ? (
          <AuthorPublicationTrendChart
            timeline={timeline}
            loading={statsLoading}
            mode={mode}
            error={null}
            pageLocal={false}
            corpusComplete={corpusComplete}
            corpusTotalCount={corpusTotalCount}
            providerTotalCount={providerTotalCount}
          />
        ) : null}

        <Snackbar
          open={showStatsProgressSnackbar}
          anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
          data-testid="publication-stats-progress-snackbar"
        >
          <Alert
            severity="info"
            variant="outlined"
            icon={<CircularProgress size={18} color="inherit" />}
            sx={{ alignItems: "center", bgcolor: "background.paper" }}
          >
            {statsProgressMessage}
          </Alert>
        </Snackbar>
        <Snackbar
          open={statsReadySnackbarOpen && corpusComplete && !statsLoading}
          autoHideDuration={3500}
          onClose={() => setStatsReadySnackbarOpen(false)}
          anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
          data-testid="publication-stats-ready-snackbar"
        >
          <Alert
            severity="success"
            variant="outlined"
            onClose={() => setStatsReadySnackbarOpen(false)}
            sx={{ bgcolor: "background.paper" }}
          >
            Complete publication statistics ready
          </Alert>
        </Snackbar>

        {!loading && unsupported ? (
          <Paper
            elevation={0}
            sx={{
              p: 3,
              border: "1px solid",
              borderColor: "divider",
              borderRadius: "18px",
            }}
          >
            <Typography variant="h6" fontWeight={600} sx={{ mb: 1 }}>
              Analysis not supported
            </Typography>
            <Typography color="text.secondary" sx={{ mb: 2, lineHeight: 1.6 }}>
              {unsupportedReason ||
                "These author profiles cannot be analyzed with the available sources."}
            </Typography>
            <Button
              variant="contained"
              color="inherit"
              disableElevation
              onClick={handleBack}
              sx={{ textTransform: "none", borderRadius: 999 }}
            >
              Return to author search
            </Button>
          </Paper>
        ) : null}

        {!unsupported ? (
          <Paper
            elevation={0}
            data-testid="publications-panel"
            sx={{
              border: "1px solid",
              borderColor: "divider",
              borderRadius: "18px",
              overflow: "hidden",
              mb: 1.5,
            }}
          >
            <Box sx={{ px: { xs: 1.5, sm: 2 }, pt: 1.5, pb: 1 }}>
              <AuthorPublicationFilters
                authors={activeAuthors}
                draftFilters={draftFilters}
                appliedFilters={appliedFilters}
                onDraftChange={setDraftFilters}
                onApply={handleApplyFilters}
                onReset={handleResetFilters}
                onRemoveChip={handleRemoveChip}
                facets={facets}
                showLoadedSampleHint={false}
                corpusComplete={corpusComplete}
                corpusTotalCount={corpusTotalCount}
                facetsLoading={statsLoading}
                disabled={unsupported || activeAuthors.length === 0}
                applying={loading && hasLoadedOnce}
              />
              {!sortIsDefault ? (
                <Chip
                  component="div"
                  size="small"
                  label={publicationSortChipLabel(publicationSort)}
                  onDelete={handleResetSort}
                  data-testid="publication-sort-chip"
                  sx={{ mt: 0.75 }}
                />
              ) : null}
            </Box>

            {showPublicationToolbar ? (
              <Box
                data-testid="publications-table-toolbar"
                sx={{
                  px: { xs: 1.5, sm: 2 },
                  py: 1,
                  borderTop: "1px solid",
                  borderColor: "divider",
                  display: "flex",
                  flexWrap: "wrap",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 1,
                  bgcolor: "action.hover",
                }}
              >
                <Box sx={{ minWidth: 0, flex: "1 1 220px" }}>
                  <Typography
                    variant="body2"
                    color="text.secondary"
                    data-testid="publications-range-label"
                    sx={{ fontWeight: 600 }}
                  >
                    {publicationRangeLabel}
                  </Typography>
                  {providerDedupCaption ? (
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      data-testid="publications-dedup-caption"
                      sx={{ display: "block", mt: 0.25, lineHeight: 1.35 }}
                    >
                      {providerDedupCaption}
                    </Typography>
                  ) : null}
                </Box>
                {totalPages > 1 ? (
                  <Pagination
                    color="primary"
                    size="small"
                    page={page}
                    count={totalPages}
                    disabled={loading}
                    onChange={handlePageChange}
                    siblingCount={0}
                    boundaryCount={1}
                    showFirstButton
                    showLastButton={totalForPages != null}
                    data-testid="publications-pagination"
                    sx={{ flexShrink: 0 }}
                  />
                ) : null}
              </Box>
            ) : null}

            <AuthorPublicationsTable
              works={items}
              loading={loading}
              error={error}
              mode={mode}
              emptyCopy={emptyCopy}
              initialEmpty={initialEmpty}
              selectedWorkIds={selectedTableWorkIds}
              excludedWorkIds={excludedWorkIds}
              onToggleSelected={handleTogglePublicationSelected}
              onToggleVisible={handleToggleVisiblePublications}
              sort={publicationSort}
              onSortChange={handleSortChange}
              embedded
            />

            {showPublicationToolbar && totalPages > 1 ? (
              <Box
                sx={{
                  px: { xs: 1.5, sm: 2 },
                  py: 1,
                  borderTop: "1px solid",
                  borderColor: "divider",
                  display: "flex",
                  justifyContent: "flex-end",
                }}
              >
                <Pagination
                  color="primary"
                  size="small"
                  page={page}
                  count={totalPages}
                  disabled={loading}
                  onChange={handlePageChange}
                  siblingCount={0}
                  boundaryCount={1}
                  showFirstButton
                  showLastButton={totalForPages != null}
                  data-testid="publications-pagination-footer"
                />
              </Box>
            ) : null}
          </Paper>
        ) : null}

        <Snackbar
          open={Boolean(saveStatus.message)}
          autoHideDuration={3000}
          onClose={() =>
            setSaveStatus((current) => ({ ...current, message: null }))
          }
        >
          <Alert
            severity={saveStatus.severity}
            variant="filled"
            onClose={() =>
              setSaveStatus((current) => ({ ...current, message: null }))
            }
          >
            {saveStatus.message}
          </Alert>
        </Snackbar>
      </Box>
    </AuthorInfoPopoverProvider>
  );
}

export default AuthorAnalysisPage;
