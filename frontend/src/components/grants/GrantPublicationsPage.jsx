import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Snackbar,
  Typography,
} from "@mui/material";
import ArrowBackRoundedIcon from "@mui/icons-material/ArrowBackRounded";
import BookmarkAddRoundedIcon from "@mui/icons-material/BookmarkAddRounded";

import {
  GRANT_PUBLICATIONS_PAGE_SIZE,
  buildGrantPublicationsCacheKey,
  exportGrantPublicationsCsv,
  fetchGrantPublicationFacets,
  fetchGrantPublications,
  normalizeGrantInput,
  searchGrantPublicationAuthors,
  searchGrantPublicationVenues,
} from "../../api/grantsApi";
import AuthorPublicationsTable from "../authors/AuthorPublicationsTable";
import AuthorPublicationTrendChart from "../authors/AuthorPublicationTrendChart";
import AuthorPublicationFilters from "../authors/AuthorPublicationFilters";
import usePublicationFacetPreview from "../authors/usePublicationFacetPreview";
import DownloadCsvButton, {
  downloadCsvFromResponse,
} from "../authors/DownloadCsvButton";
import { AuthorInfoPopoverProvider } from "../authors/AuthorInfoPopover";
import {
  emptyFacets,
  emptyPublicationFilters,
  clonePublicationFilters,
  hasActivePublicationFilters,
  publicationFiltersKey,
  removeFilterChip,
  toPublicationFiltersPayload,
} from "../authors/publicationFilters";
import {
  DEFAULT_PUBLICATION_SORT,
  normalizePublicationSort,
  publicationSortKey,
} from "../authors/publicationSorting";
import { analysisPageLayoutSx } from "../../layout/pageLayout";
import { saveSavedSearch } from "../../features/savedSearches/savedSearchesApi";

const PAGE_SIZE = GRANT_PUBLICATIONS_PAGE_SIZE;
const EMPTY_FILTERS_KEY = publicationFiltersKey(emptyPublicationFilters());

const publicationsPageCache = new Map();

// eslint-disable-next-line react-refresh/only-export-components -- Tests clear this module-level page cache between route renders.
export function clearGrantPublicationsPageCache() {
  publicationsPageCache.clear();
}

const pageLayoutSx = analysisPageLayoutSx;

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
    grants: [],
    authors: Array.isArray(filters?.authors)
      ? filters.authors.map((value) => ({ value, label: value }))
      : [],
  };
}

function GrantPublicationsPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { grantNumber: grantNumberParam } = useParams();
  const [searchParams] = useSearchParams();

  const grantNumber = useMemo(() => {
    const raw = grantNumberParam || "";
    try {
      return normalizeGrantInput(decodeURIComponent(raw));
    } catch {
      return normalizeGrantInput(raw);
    }
  }, [grantNumberParam]);
  const provider = useMemo(() => {
    const raw = searchParams.get("provider") || "openalex";
    return String(raw).toLowerCase();
  }, [searchParams]);

  const grantKey = useMemo(
    () => `${compactProvider(provider)}::${grantNumber}`,
    [grantNumber, provider],
  );

  const [draftFilters, setDraftFilters] = useState(emptyPublicationFilters);
  const [appliedFilters, setAppliedFilters] = useState(emptyPublicationFilters);
  const [publicationSort, setPublicationSort] = useState(DEFAULT_PUBLICATION_SORT);
  const [facets, setFacets] = useState(emptyFacets);

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
  const [meta, setMeta] = useState({
    funder_name: null,
    verified: provider === "openalex",
    match_type: null,
  });
  const [nextCursor, setNextCursor] = useState(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);
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
  const grantKeyRef = useRef(grantKey);
  const sortRef = useRef(publicationSort);
  const sortKeyRef = useRef(sortKey);
  const requestKeyRef = useRef(`${grantKey}::${appliedFiltersKey}::${sortKey}`);
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
    error: null,
  });

  /* eslint-disable react-hooks/refs -- This page keeps request guards in refs so async pagination callbacks see the latest state. */
  grantKeyRef.current = grantKey;
  sortRef.current = publicationSort;
  sortKeyRef.current = sortKey;
  appliedFiltersKeyRef.current = appliedFiltersKey;
  appliedFiltersRef.current = appliedFilters;
  filtersPayloadRef.current = appliedFiltersPayload;
  requestKeyRef.current = `${grantKey}::${appliedFiltersKey}::${sortKey}`;
  paginationStateRef.current = {
    hasMore,
    nextCursor,
    loading,
    loadingMore,
    error,
  };
  /* eslint-enable react-hooks/refs */

  const lookupContext = useMemo(
    () => ({ grantNumber, provider }),
    [grantNumber, provider],
  );

  const searchVenues = useCallback(
    (args) => searchGrantPublicationVenues(args),
    [],
  );
  const searchAuthors = useCallback(
    (args) => searchGrantPublicationAuthors(args),
    [],
  );

  const markLoadedOnce = useCallback((value) => {
    hasLoadedOnceRef.current = value;
    setHasLoadedOnce(value);
  }, []);

  const emptyCopy = useMemo(() => {
    if (hasActivePublicationFilters(appliedFilters)) {
      return {
        heading: "No publications match these filters",
        body: "Try adjusting the year range, source, institution, venue, or author filters.",
      };
    }
    return {
      heading: "No publications found",
      body:
        provider === "arxiv"
          ? "We could not find any searchable arXiv metadata matches for this exact grant number."
          : "We could not find publications related to this exact grant number from the selected source.",
    };
  }, [appliedFilters, provider]);

  const resetAndLoad = useCallback(
    async ({
      filtersOverride,
      filtersKeyOverride,
      sortOverride,
      sortKeyOverride,
      preserveExisting: preserveExistingOption,
      forceRefresh = false,
    } = {}) => {
      if (!grantNumber || grantNumber.length < 2) {
        setItems([]);
        setTimeline(null);
        setTimelineError(null);
        setFacets(emptyFacets());
        setNextCursor(null);
        setHasMore(false);
        setLoadingMore(false);
        loadMoreInFlightRef.current = false;
        applyInFlightRef.current = false;
        setInitialEmpty(false);
        setError("Invalid grant number.");
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
      const fetchRequestKey = `${grantKeyRef.current}::${filtersKeyForCache}::${sortKeyForCache}`;

      filtersPayloadRef.current = filtersForRequest;
      appliedFiltersKeyRef.current = filtersKeyForCache;
      sortRef.current = sortForRequest;
      sortKeyRef.current = sortKeyForCache;
      requestKeyRef.current = fetchRequestKey;

      const preserveExisting =
        preserveExistingOption !== undefined
          ? preserveExistingOption
          : hasLoadedOnceRef.current;

      const cacheKey = buildGrantPublicationsCacheKey({
        grantNumber,
        provider,
        filtersKey: filtersKeyForCache,
        sortKey: sortKeyForCache,
        cursor: "*",
        limit: PAGE_SIZE,
      });

      const cached = forceRefresh ? null : publicationsPageCache.get(cacheKey);
      if (cached) {
        seenIdsRef.current = new Set(
          (cached.items || [])
            .map((item) => item.id || item.result_id)
            .filter(Boolean),
        );
        setItems(cached.items || []);
        setTimeline(cached.timeline ?? null);
        setTimelineError(null);
        setFacets(cached.facets || emptyFacets());
        setNextCursor(cached.next_cursor ?? null);
        setHasMore(Boolean(cached.has_more));
        setMeta({
          funder_name: cached.funder_name ?? null,
          verified: Boolean(cached.verified),
          match_type: cached.match_type ?? null,
        });
        setInitialEmpty(Array.isArray(cached.items) && cached.items.length === 0);
        setError(null);
        setLoading(false);
        markLoadedOnce(true);
        applyInFlightRef.current = false;
        return;
      }

      setLoading(true);
      setError(null);
      setTimelineError(null);
      setInitialEmpty(false);
      if (!preserveExisting) {
        setItems([]);
        setTimeline(null);
      }
      setNextCursor(null);
      setHasMore(false);
      seenIdsRef.current = new Set();

      try {
        const response = await fetchGrantPublications({
          grantNumber,
          provider,
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
          timeline: response.timeline ?? null,
          facets: response.facets || emptyFacets(),
          next_cursor: response.next_cursor,
          has_more: response.has_more,
          funder_name: response.funder_name,
          verified: response.verified,
          match_type: response.match_type,
        });

        setItems(pageItems);
        setTimeline(response.timeline ?? null);
        setTimelineError(null);
        setFacets(response.facets || emptyFacets());
        setNextCursor(response.next_cursor);
        setHasMore(Boolean(response.has_more));
        setMeta({
          funder_name: response.funder_name ?? null,
          verified: Boolean(response.verified),
          match_type: response.match_type ?? null,
        });
        setInitialEmpty(pageItems.length === 0);
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
            "Grant publications are temporarily unavailable. Please try again.",
        );
        if (!preserveExisting) {
          setItems([]);
          setTimeline(null);
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
    [grantNumber, markLoadedOnce, provider],
  );

  const loadMore = useCallback(async () => {
    const state = paginationStateRef.current;
    if (
      !state.hasMore ||
      !state.nextCursor ||
      state.loading ||
      state.loadingMore ||
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

    const cacheKey = buildGrantPublicationsCacheKey({
      grantNumber,
      provider,
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
      const response = await fetchGrantPublications({
        grantNumber,
        provider,
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
        funder_name: response.funder_name,
        verified: response.verified,
        match_type: response.match_type,
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
  }, [grantNumber, provider]);

  const loadMoreRef = useRef(loadMore);
  /* eslint-disable react-hooks/refs -- IntersectionObserver callbacks call the latest pagination functions. */
  loadMoreRef.current = loadMore;

  const resetAndLoadRef = useRef(resetAndLoad);
  resetAndLoadRef.current = resetAndLoad;
  /* eslint-enable react-hooks/refs */

  // Grant identity drives the main fetch. Draft filter edits never fetch here.
  useEffect(() => {
    const startingFilters = location.state?.filters
      ? filtersDraftFromPayload(location.state.filters)
      : emptyPublicationFilters();
    /* eslint-disable react-hooks/set-state-in-effect -- Grant route changes reset the page-owned filter state. */
    setDraftFilters(startingFilters);
    setAppliedFilters(startingFilters);
    setFacets(emptyFacets());
    /* eslint-enable react-hooks/set-state-in-effect */

    const startingPayload = toPublicationFiltersPayload(startingFilters);
    const startingFiltersKey = publicationFiltersKey(startingFilters);
    filtersPayloadRef.current = startingPayload;
    appliedFiltersKeyRef.current = startingFiltersKey;
    appliedFiltersRef.current = startingFilters;
    requestKeyRef.current = `${grantKey}::${startingFiltersKey}::${sortKeyRef.current}`;
    markLoadedOnce(false);

    resetAndLoadRef.current({
      filtersOverride: startingPayload,
      filtersKeyOverride: startingFiltersKey,
      sortOverride: sortRef.current,
      sortKeyOverride: sortKeyRef.current,
    });

    return () => {
      if (resetAbortRef.current) {
        resetAbortRef.current.abort();
      }
      if (loadMoreAbortRef.current) {
        loadMoreAbortRef.current.abort();
      }
      loadMoreInFlightRef.current = false;
    };
  }, [grantKey, location.state?.filters, markLoadedOnce]);

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
      requestKeyRef.current = `${grantKeyRef.current}::${key}::${sortKeyRef.current}`;
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
    requestKeyRef.current = `${grantKeyRef.current}::${EMPTY_FILTERS_KEY}::${sortKeyRef.current}`;
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
      requestKeyRef.current = `${grantKeyRef.current}::${key}::${sortKeyRef.current}`;
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

  const handleExportCsv = useCallback(async () => {
    const response = await exportGrantPublicationsCsv({
      grantNumber,
      provider,
      filters: appliedFiltersPayload,
    });
    await downloadCsvFromResponse(
      response,
      `grant-${grantNumber || "export"}-publications.csv`,
    );
  }, [appliedFiltersPayload, grantNumber, provider]);

  const handleSaveSearch = useCallback(async () => {
    if (saveStatus.saving || !grantNumber) {
      return;
    }
    setSaveStatus({ saving: true, message: null, severity: "success" });
    try {
      await saveSavedSearch({
        search_type: "grant",
        payload: {
          grant_number: grantNumber,
          provider,
          filters: appliedFiltersPayload,
        },
        applied_filters: appliedFiltersPayload,
        provider_context: { provider },
        metadata: {
          funder_name: meta.funder_name,
          verified: meta.verified,
          match_type: meta.match_type,
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
    appliedFiltersPayload,
    grantNumber,
    meta.funder_name,
    meta.match_type,
    meta.verified,
    provider,
    saveStatus.saving,
  ]);

  const fetchFacetPreview = useCallback(
    ({ filters, signal }) =>
      fetchGrantPublicationFacets({
        grantNumber,
        provider,
        filters,
        signal,
      }),
    [grantNumber, provider],
  );

  usePublicationFacetPreview({
    enabled: hasLoadedOnce && Boolean(grantNumber),
    requestKey: grantKey,
    draftFilters,
    fetchFacets: fetchFacetPreview,
    onFacets: setFacets,
  });

  const handleSortChange = useCallback(
    (nextSort) => {
      const normalized = normalizePublicationSort(nextSort);
      const nextSortKey = publicationSortKey(normalized);
      setPublicationSort(normalized);
      sortRef.current = normalized;
      sortKeyRef.current = nextSortKey;
      requestKeyRef.current = `${grantKeyRef.current}::${appliedFiltersKeyRef.current}::${nextSortKey}`;
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
    if (!node || error) {
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
  }, [error, hasMore, loading, items.length]);

  const handleBack = () => {
    navigate("/");
  };

  const statusLabel = meta.verified
    ? "Verified award relationship"
    : "Experimental metadata match";

  const showInitialLoading = loading && !hasLoadedOnce;
  const applying = loading && hasLoadedOnce;

  return (
    <AuthorInfoPopoverProvider>
      <Box sx={pageLayoutSx}>
        <Button
          startIcon={<ArrowBackRoundedIcon />}
          onClick={handleBack}
          sx={{
            textTransform: "none",
            color: "text.secondary",
            mb: 2.5,
            px: 0.5,
            "&:hover": { bgcolor: "action.hover", color: "text.primary" },
          }}
        >
          Return to search
        </Button>

        <Typography variant="h4" component="h1" fontWeight={700} sx={{ mb: 0.75 }}>
          Publications for {grantNumber || "grant"}
        </Typography>

        <Typography color="text.secondary" sx={{ mb: 2.5, lineHeight: 1.6 }}>
          {[
            meta.funder_name,
            provider === "openalex" ? "OpenAlex" : provider === "arxiv" ? "arXiv" : provider,
            statusLabel,
          ]
            .filter(Boolean)
            .join(" · ")}
        </Typography>

        <AuthorPublicationFilters
          filterMode="grant"
          lookupContext={lookupContext}
          venueSearchFn={searchVenues}
          secondarySearchFn={searchAuthors}
          draftFilters={draftFilters}
          appliedFilters={appliedFilters}
          onDraftChange={setDraftFilters}
          onApply={handleApplyFilters}
          onReset={handleResetFilters}
          onRemoveChip={handleRemoveChip}
          facets={facets}
          disabled={!grantNumber}
          applying={applying}
        />

        <AuthorPublicationTrendChart
          timeline={timeline}
          loading={showInitialLoading}
          mode="grant"
          title="Publications over time"
          error={timelineError}
        />

        {!showInitialLoading && !error && items.length > 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {items.length}
            {hasMore ? "+" : ""} publication{items.length === 1 ? "" : "s"}
            {applying ? (
              <CircularProgress size={12} sx={{ ml: 1, verticalAlign: "middle" }} />
            ) : null}
          </Typography>
        ) : (
          <Box sx={{ mb: 2 }} />
        )}

        {error && !items.length ? (
          <Alert severity="error" sx={{ mb: 2 }}>
            {typeof error === "string" ? error : "Failed to load grant publications."}
          </Alert>
        ) : null}

        <AuthorPublicationsTable
          works={items}
          loading={showInitialLoading}
          loadingMore={loadingMore}
          error={items.length > 0 ? null : error}
          mode="single_author"
          sentinelRef={sentinelRef}
          emptyCopy={emptyCopy}
          initialEmpty={initialEmpty}
          searchedGrantNumber={grantNumber}
          grantProvider={provider}
          sort={publicationSort}
          onSortChange={handleSortChange}
        />

        <DownloadCsvButton
          disabled={
            showInitialLoading ||
            !hasLoadedOnce ||
            !grantNumber ||
            items.length === 0
          }
          onExport={handleExportCsv}
        />

        <Box sx={{ mt: 1, mb: 1 }}>
          <Button
            size="small"
            variant="outlined"
            color="inherit"
            startIcon={<BookmarkAddRoundedIcon fontSize="small" />}
            onClick={handleSaveSearch}
            disabled={saveStatus.saving || !grantNumber}
            sx={{ textTransform: "none" }}
          >
            {saveStatus.saving ? "Saving..." : "Save search"}
          </Button>
        </Box>

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

function compactProvider(provider) {
  return String(provider || "openalex").toLowerCase();
}

export default GrantPublicationsPage;
