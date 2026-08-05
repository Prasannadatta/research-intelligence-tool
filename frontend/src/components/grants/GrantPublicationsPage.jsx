import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Typography,
} from "@mui/material";
import ArrowBackRoundedIcon from "@mui/icons-material/ArrowBackRounded";

import {
  GRANT_PUBLICATIONS_PAGE_SIZE,
  buildGrantPublicationsCacheKey,
  exportGrantPublicationsCsv,
  fetchGrantPublications,
  normalizeGrantInput,
  searchGrantPublicationAuthors,
  searchGrantPublicationVenues,
} from "../../api/grantsApi";
import AuthorPublicationsTable from "../authors/AuthorPublicationsTable";
import AuthorPublicationTrendChart from "../authors/AuthorPublicationTrendChart";
import AuthorPublicationFilters from "../authors/AuthorPublicationFilters";
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

const PAGE_SIZE = GRANT_PUBLICATIONS_PAGE_SIZE;
const EMPTY_FILTERS_KEY = publicationFiltersKey(emptyPublicationFilters());

const publicationsPageCache = new Map();

export function clearGrantPublicationsPageCache() {
  publicationsPageCache.clear();
}

const pageLayoutSx = {
  width: "100%",
  maxWidth: "none",
  px: { xs: 2, sm: 3, md: 6 },
  py: 3,
  boxSizing: "border-box",
  textAlign: "left",
};

function GrantPublicationsPage() {
  const navigate = useNavigate();
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
  const [facets, setFacets] = useState(emptyFacets);

  const appliedFiltersKey = useMemo(
    () => publicationFiltersKey(appliedFilters),
    [appliedFilters],
  );
  const appliedFiltersPayload = useMemo(
    () => toPublicationFiltersPayload(appliedFilters),
    [appliedFilters],
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

  const requestIdRef = useRef(0);
  const resetAbortRef = useRef(null);
  const loadMoreAbortRef = useRef(null);
  const loadMoreInFlightRef = useRef(false);
  const applyInFlightRef = useRef(false);
  const grantKeyRef = useRef(grantKey);
  const requestKeyRef = useRef(`${grantKey}::${appliedFiltersKey}`);
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

  grantKeyRef.current = grantKey;
  appliedFiltersKeyRef.current = appliedFiltersKey;
  appliedFiltersRef.current = appliedFilters;
  filtersPayloadRef.current = appliedFiltersPayload;
  requestKeyRef.current = `${grantKey}::${appliedFiltersKey}`;
  paginationStateRef.current = {
    hasMore,
    nextCursor,
    loading,
    loadingMore,
    error,
  };

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
        body: "Try adjusting the year range, source, venue, or author filters.",
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
      const fetchRequestKey = `${grantKeyRef.current}::${filtersKeyForCache}`;

      filtersPayloadRef.current = filtersForRequest;
      appliedFiltersKeyRef.current = filtersKeyForCache;
      requestKeyRef.current = fetchRequestKey;

      const preserveExisting =
        preserveExistingOption !== undefined
          ? preserveExistingOption
          : hasLoadedOnceRef.current;

      const cacheKey = buildGrantPublicationsCacheKey({
        grantNumber,
        provider,
        filtersKey: filtersKeyForCache,
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
  loadMoreRef.current = loadMore;

  const resetAndLoadRef = useRef(resetAndLoad);
  resetAndLoadRef.current = resetAndLoad;

  // Grant identity drives the main fetch. Draft filter edits never fetch here.
  useEffect(() => {
    const emptyFilters = emptyPublicationFilters();
    setDraftFilters(emptyFilters);
    setAppliedFilters(emptyFilters);
    setFacets(emptyFacets());

    const emptyPayload = toPublicationFiltersPayload(emptyFilters);
    filtersPayloadRef.current = emptyPayload;
    appliedFiltersKeyRef.current = EMPTY_FILTERS_KEY;
    appliedFiltersRef.current = emptyFilters;
    requestKeyRef.current = `${grantKey}::${EMPTY_FILTERS_KEY}`;
    markLoadedOnce(false);

    resetAndLoadRef.current({
      filtersOverride: emptyPayload,
      filtersKeyOverride: EMPTY_FILTERS_KEY,
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
  }, [grantKey, markLoadedOnce]);

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
      requestKeyRef.current = `${grantKeyRef.current}::${key}`;
      resetAndLoad({
        filtersOverride: payload,
        filtersKeyOverride: key,
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
    requestKeyRef.current = `${grantKeyRef.current}::${EMPTY_FILTERS_KEY}`;
    resetAndLoad({
      filtersOverride: payload,
      filtersKeyOverride: EMPTY_FILTERS_KEY,
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
      requestKeyRef.current = `${grantKeyRef.current}::${key}`;
      resetAndLoad({
        filtersOverride: payload,
        filtersKeyOverride: key,
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

        <Typography variant="h4" component="h1" fontWeight={600} sx={{ mb: 0.75 }}>
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
      </Box>
    </AuthorInfoPopoverProvider>
  );
}

function compactProvider(provider) {
  return String(provider || "openalex").toLowerCase();
}

export default GrantPublicationsPage;
