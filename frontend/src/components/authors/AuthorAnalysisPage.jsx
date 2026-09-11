import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Paper,
  Snackbar,
  Typography,
} from "@mui/material";
import ArrowBackRoundedIcon from "@mui/icons-material/ArrowBackRounded";
import InsightsOutlinedIcon from "@mui/icons-material/InsightsOutlined";
import BookmarkAddRoundedIcon from "@mui/icons-material/BookmarkAddRounded";

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
  activeAuthorIdsKey,
  analysisTitleForAuthors,
  emptyStateCopy,
  getActiveAuthors,
  getInitialActiveAuthorIds,
  isAuthorCheckboxDisabled,
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
  normalizePublicationSort,
  publicationSortKey,
} from "./publicationSorting";
import { getWorkDate, getWorkId } from "./authorPublicationHelpers";
import PublicationExclusionManager from "../../features/authorAnalysis/components/PublicationExclusionManager";
import { saveSavedSearch } from "../../features/savedSearches/savedSearchesApi";
import { analysisPageLayoutSx } from "../../layout/pageLayout";
import * as publicationStatsRequest from "./publicationStatsRequest";

const PAGE_SIZE = 20;

function asProviderTotalCount(value) {
  if (value == null || value === "") {
    return null;
  }
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : null;
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
  const [nextCursor, setNextCursor] = useState(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
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

  const requestIdRef = useRef(0);
  const resetAbortRef = useRef(null);
  const loadMoreAbortRef = useRef(null);
  const loadMoreInFlightRef = useRef(false);
  const applyInFlightRef = useRef(false);
  const selectionKeyRef = useRef(selectionKey);
  const sortRef = useRef(publicationSort);
  const sortKeyRef = useRef(sortKey);
  const requestKeyRef = useRef(`${selectionKey}::${appliedFiltersKey}::${sortKey}`);
  const filtersPayloadRef = useRef(appliedFiltersPayload);
  const appliedFiltersKeyRef = useRef(appliedFiltersKey);
  const appliedFiltersRef = useRef(appliedFilters);
  const hasLoadedOnceRef = useRef(false);
  const sentinelRef = useRef(null);
  const seenIdsRef = useRef(new Set());
  const paginationStateRef = useRef({
    hasMore: false,
    nextCursor: null,
    loading: false,
    loadingMore: false,
    unsupported: false,
    error: null,
  });

  /* eslint-disable react-hooks/refs -- This page keeps request guards in refs so async pagination callbacks see the latest state. */
  selectionKeyRef.current = selectionKey;
  sortRef.current = publicationSort;
  sortKeyRef.current = sortKey;
  appliedFiltersKeyRef.current = appliedFiltersKey;
  appliedFiltersRef.current = appliedFilters;
  filtersPayloadRef.current = appliedFiltersPayload;
  requestKeyRef.current = `${selectionKey}::${appliedFiltersKey}::${sortKey}`;
  paginationStateRef.current = {
    hasMore,
    nextCursor,
    loading,
    loadingMore,
    unsupported,
    error,
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
    } = {}) => {
      if (activeAuthors.length === 0) {
        setItems([]);
        setTimeline(null);
        setTimelineError(null);
        setFacets(emptyFacets());
        setProviderTotalCount(null);
        setNextCursor(null);
        setHasMore(false);
        setLoadingMore(false);
        loadMoreInFlightRef.current = false;
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
      if (loadMoreAbortRef.current) {
        loadMoreAbortRef.current.abort();
      }
      loadMoreInFlightRef.current = false;
      setLoadingMore(false);

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

      filtersPayloadRef.current = filtersForRequest;
      appliedFiltersKeyRef.current = filtersKeyForCache;
      sortRef.current = sortForRequest;
      sortKeyRef.current = sortKeyForCache;
      requestKeyRef.current = fetchRequestKey;

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
        cursor: "*",
        limit: PAGE_SIZE,
      });

      const cached = forceRefresh
        ? null
        : publicationsPageCache.get(cacheKey);
      if (cached) {
        seenIdsRef.current = new Set(
          (cached.items || [])
            .map((item) => item.id || item.result_id)
            .filter(Boolean),
        );
        setItems(cached.items || []);
        setTimeline(null);
        setTimelineError(null);
        setFacets(emptyFacets());
        setCorpusComplete(false);
        setCorpusTotalCount(null);
        setStatsError(null);
        setProviderTotalCount(asProviderTotalCount(cached.provider_total_count));
        setNextCursor(cached.next_cursor ?? null);
        setHasMore(Boolean(cached.has_more));
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
        setTimeline(null);
        setProviderTotalCount(null);
        setFacets(emptyFacets());
        setCorpusComplete(false);
        setCorpusTotalCount(null);
        setStatsError(null);
      }
      setNextCursor(null);
      setHasMore(false);
      seenIdsRef.current = new Set();

      try {
        const response = await fetchAuthorPublications({
          authors: activeAuthors,
          originalAuthorIds,
          filters: filtersForRequest,
          sortBy: sortForRequest.sortBy,
          sortDirection: sortForRequest.sortDirection,
          limit: PAGE_SIZE,
          cursor: null,
          signal: controller.signal,
        });

        if (
          requestId !== requestIdRef.current ||
          fetchRequestKey !== requestKeyRef.current
        ) {
          return;
        }

        const pageItems = Array.isArray(response.items) ? response.items : [];
        seenIdsRef.current = new Set(
          pageItems.map((item) => item.id || item.result_id).filter(Boolean),
        );

        publicationsPageCache.set(cacheKey, {
          items: pageItems,
          timeline: null,
          facets: emptyFacets(),
          provider_total_count: asProviderTotalCount(response.provider_total_count),
          next_cursor: response.next_cursor,
          has_more: response.has_more,
          unsupported: response.unsupported,
          unsupported_reason: response.unsupported_reason,
        });

        setItems(pageItems);
        setTimeline(null);
        setTimelineError(null);
        setFacets(emptyFacets());
        setCorpusComplete(false);
        setCorpusTotalCount(null);
        setStatsError(null);
        setProviderTotalCount(asProviderTotalCount(response.provider_total_count));
        setNextCursor(response.next_cursor);
        setHasMore(Boolean(response.has_more));
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
          setTimeline(null);
          setProviderTotalCount(null);
        }
        setTimelineError(null);
        setHasMore(false);
        setNextCursor(null);
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

  const loadMore = useCallback(async () => {
    const state = paginationStateRef.current;
    if (
      !state.hasMore ||
      !state.nextCursor ||
      state.loading ||
      state.loadingMore ||
      state.unsupported ||
      loadMoreInFlightRef.current
    ) {
      return;
    }

    const fetchRequestKey = requestKeyRef.current;
    const pageCursor = state.nextCursor;
    loadMoreInFlightRef.current = true;

    if (loadMoreAbortRef.current) {
      loadMoreAbortRef.current.abort();
    }
    const controller = new AbortController();
    loadMoreAbortRef.current = controller;

    const cacheKey = buildAuthorPublicationsCacheKey({
      mode,
      canonicalAuthorIds: authorIds,
      providerRecordsKey: recordsKey,
      filtersKey: appliedFiltersKeyRef.current,
      sortKey: sortKeyRef.current,
      cursor: pageCursor,
      limit: PAGE_SIZE,
    });

    const cached = publicationsPageCache.get(cacheKey);
    if (cached) {
      const appended = [];
      for (const item of cached.items || []) {
        const key = item.id || item.result_id;
        if (!key || seenIdsRef.current.has(key)) {
          continue;
        }
        seenIdsRef.current.add(key);
        appended.push(item);
      }
      if (fetchRequestKey === requestKeyRef.current) {
        setItems((current) => [...current, ...appended]);
        setNextCursor(cached.next_cursor ?? null);
        setHasMore(Boolean(cached.has_more));
      }
      loadMoreInFlightRef.current = false;
      return;
    }

    setLoadingMore(true);
    try {
      const response = await fetchAuthorPublications({
        authors: activeAuthors,
        originalAuthorIds,
        filters: filtersPayloadRef.current,
        sortBy: sortRef.current.sortBy,
        sortDirection: sortRef.current.sortDirection,
        limit: PAGE_SIZE,
        cursor: pageCursor,
        signal: controller.signal,
      });

      if (fetchRequestKey !== requestKeyRef.current) {
        return;
      }

      const pageItems = Array.isArray(response.items) ? response.items : [];
      publicationsPageCache.set(cacheKey, {
        items: pageItems,
        next_cursor: response.next_cursor,
        has_more: response.has_more,
        unsupported: response.unsupported,
        unsupported_reason: response.unsupported_reason,
      });

      const appended = [];
      for (const item of pageItems) {
        const key = item.id || item.result_id;
        if (!key || seenIdsRef.current.has(key)) {
          continue;
        }
        seenIdsRef.current.add(key);
        appended.push(item);
      }

      setItems((current) => [...current, ...appended]);
      setNextCursor(response.next_cursor);
      setHasMore(Boolean(response.has_more));
    } catch (err) {
      if (err?.name === "CanceledError" || err?.code === "ERR_CANCELED") {
        return;
      }
      if (fetchRequestKey !== requestKeyRef.current) {
        return;
      }
      setError(
        err?.response?.data?.detail ||
          "Could not load more publications. Please try again.",
      );
    } finally {
      loadMoreInFlightRef.current = false;
      if (fetchRequestKey === requestKeyRef.current) {
        setLoadingMore(false);
      }
    }
  }, [activeAuthors, authorIds, mode, originalAuthorIds, recordsKey]);

  const loadMoreRef = useRef(loadMore);
  /* eslint-disable react-hooks/refs -- IntersectionObserver callbacks call the latest pagination functions. */
  loadMoreRef.current = loadMore;

  const resetAndLoadRef = useRef(resetAndLoad);
  resetAndLoadRef.current = resetAndLoad;
  /* eslint-enable react-hooks/refs */

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
        signal: controller.signal,
        onProgress: (job) => {
          if (requestId !== statsRequestIdRef.current) {
            return;
          }
          setStatsProgress({
            status: job.status || "running",
            stage: job.progress_stage || job.progressStage || "Preparing",
            percent: Number(job.progress_percent ?? job.progressPercent ?? 0),
            detail: job.progress_detail || job.progressDetail || null,
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
      if (loadMoreAbortRef.current) {
        loadMoreAbortRef.current.abort();
      }
      loadMoreInFlightRef.current = false;
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
      });
    },
    [resetAndLoad],
  );

  const excludedWorkIdList = useMemo(
    () => [...excludedWorkIds].filter(Boolean).sort(),
    [excludedWorkIds],
  );

  const handleSaveSearch = useCallback(async () => {
    if (saveStatus.saving || originalAuthors.length === 0) {
      return;
    }
    setSaveStatus({ saving: true, message: null, severity: "success" });
    try {
      const authorsToSave = activeAuthors.length > 0 ? activeAuthors : originalAuthors;
      const activeIdsToSave = authorsToSave
        .map((author) => author.canonical_author_id)
        .filter(Boolean);
      const providerContext = {
        providers: [
          ...new Set(
            authorsToSave
              .map((author) => String(author.provider || "").toLowerCase())
              .filter(Boolean),
          ),
        ],
        mode,
      };
      await saveSavedSearch({
        search_type: "authors",
        payload: {
          authors: authorsToSave.map((author) => ({
            canonical_author_id: author.canonical_author_id,
            display_name: author.display_name,
            provider: author.provider,
            provider_author_id: author.provider_author_id,
          })),
          active_author_ids: activeIdsToSave,
          filters: appliedFiltersPayload,
          excluded_work_ids: excludedWorkIdList,
          provider_context: providerContext,
        },
        applied_filters: appliedFiltersPayload,
        provider_context: providerContext,
        excluded_work_ids: excludedWorkIdList,
        metadata: {
          author_count: authorsToSave.length,
          active_author_count: authorsToSave.length,
        },
      });
      setSaveStatus({ saving: false, message: "Saved", severity: "success" });
    } catch (err) {
      setSaveStatus({
        saving: false,
        message: err?.response?.data?.detail || "Could not save search.",
        severity: "error",
      });
    }
  }, [
    activeAuthors,
    appliedFiltersPayload,
    excludedWorkIdList,
    mode,
    originalAuthors,
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
      });
    },
    [resetAndLoad],
  );

  useEffect(() => {
    const node = sentinelRef.current;
    if (!node || unsupported || error) {
      return undefined;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) {
          return;
        }
        const state = paginationStateRef.current;
        if (
          !state.hasMore ||
          !state.nextCursor ||
          state.loading ||
          state.loadingMore ||
          state.unsupported ||
          loadMoreInFlightRef.current
        ) {
          return;
        }
        loadMoreRef.current();
      },
      { root: null, rootMargin: "240px", threshold: 0 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [error, hasMore, loading, unsupported, items.length]);

  const handleToggleAuthor = (authorId) => {
    setActiveAuthorIds((current) => toggleActiveAuthor(current, authorId));
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
            gap: { xs: 1, md: 2 },
            mb: 1.5,
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
            sx={{
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              justifyContent: { xs: "flex-start", md: "flex-end" },
              gap: 1.5,
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
          </Box>
        </Box>

        {authorFilterSection}

        {selectedTableWorkIdList.length > 0 ? (
          <Paper
            elevation={0}
            data-testid="publication-selection-actions"
            sx={{
              mb: 2,
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
        ) : null}

        {!unsupported ? (
          <AuthorPublicationTrendChart
            timeline={timeline}
            loading={statsLoading}
            mode={mode}
            error={statsError || timelineError}
            pageLocal={false}
            corpusComplete={corpusComplete}
            corpusTotalCount={corpusTotalCount}
            providerTotalCount={providerTotalCount}
            onRetry={
              statsError
                ? () => {
                    setStatsRetryToken((value) => value + 1);
                  }
                : undefined
            }
          />
        ) : null}

        <Snackbar
          open={statsLoading && !statsError}
          anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
          data-testid="publication-stats-progress-snackbar"
        >
          <Alert
            severity="info"
            variant="filled"
            icon={<CircularProgress size={18} color="inherit" />}
            sx={{ alignItems: "center" }}
          >
            {publicationStatsRequest.formatPublicationStatsProgressMessage(statsProgress)}
          </Alert>
        </Snackbar>
        <Snackbar
          open={statsReadySnackbarOpen && corpusComplete && !statsLoading}
          autoHideDuration={4000}
          onClose={() => setStatsReadySnackbarOpen(false)}
          anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
          data-testid="publication-stats-ready-snackbar"
        >
          <Alert
            severity="success"
            variant="filled"
            onClose={() => setStatsReadySnackbarOpen(false)}
          >
            Complete publication statistics ready
          </Alert>
        </Snackbar>

        <Snackbar
          open={Boolean(statsError)}
          anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
          data-testid="publication-stats-error-snackbar"
          onClose={() => setStatsError(null)}
        >
          <Alert
            severity={/rate limit/i.test(String(statsError || "")) ? "warning" : "error"}
            variant="filled"
            onClose={() => setStatsError(null)}
            action={
              <Button
                color="inherit"
                size="small"
                onClick={() => {
                  setStatsRetryToken((value) => value + 1);
                }}
              >
                Retry
              </Button>
            }
          >
            {statsError}
          </Alert>
        </Snackbar>

        {!loading && !error && !unsupported && items.length > 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {items.length}
            {hasMore ? "+" : ""} publication{items.length === 1 ? "" : "s"}
          </Typography>
        ) : (
          <Box sx={{ mb: 2 }} />
        )}

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
          <AuthorPublicationsTable
            works={items}
            loading={loading}
            loadingMore={loadingMore}
            error={error}
            mode={mode}
            sentinelRef={sentinelRef}
            emptyCopy={emptyCopy}
            initialEmpty={initialEmpty}
            selectedWorkIds={selectedTableWorkIds}
            excludedWorkIds={excludedWorkIds}
            onToggleSelected={handleTogglePublicationSelected}
            onToggleVisible={handleToggleVisiblePublications}
            sort={publicationSort}
            onSortChange={handleSortChange}
          />
        ) : null}

        {!unsupported ? (
          <DownloadCsvButton
            disabled={
              loading ||
              !hasLoadedOnce ||
              unsupported ||
              activeAuthors.length === 0 ||
              items.length === 0
            }
            onExport={handleExportCsv}
          />
        ) : null}

        {!unsupported ? (
          <Box sx={{ mt: 1, mb: 1 }}>
            <Button
              size="small"
              variant="outlined"
              color="inherit"
              startIcon={<BookmarkAddRoundedIcon fontSize="small" />}
              onClick={handleSaveSearch}
              disabled={saveStatus.saving || originalAuthors.length === 0}
              sx={{ textTransform: "none" }}
            >
              {saveStatus.saving ? "Saving..." : "Save search"}
            </Button>
          </Box>
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
