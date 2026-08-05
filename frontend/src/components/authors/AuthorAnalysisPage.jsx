import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  Paper,
  Typography,
} from "@mui/material";
import ArrowBackRoundedIcon from "@mui/icons-material/ArrowBackRounded";
import InsightsOutlinedIcon from "@mui/icons-material/InsightsOutlined";

import {
  analysisModeForAuthors,
  buildAuthorPublicationsCacheKey,
  exportAuthorPublicationsCsv,
  fetchAuthorPublications,
  toAnalysisAuthorPayload,
} from "../../api/analysisApi";
import AuthorPublicationsTable from "./AuthorPublicationsTable";
import AuthorPublicationTrendChart from "./AuthorPublicationTrendChart";
import AuthorPublicationFilters from "./AuthorPublicationFilters";
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

const PAGE_SIZE = 20;
const EMPTY_FILTERS_KEY = publicationFiltersKey(emptyPublicationFilters());

const pageLayoutSx = {
  width: "100%",
  maxWidth: "none",
  px: { xs: 2, sm: 3, md: 6 },
  py: 3,
  boxSizing: "border-box",
  textAlign: "left",
};

function AuthorAnalysisPage() {
  const navigate = useNavigate();
  const location = useLocation();

  const originalAuthors = useMemo(() => {
    const fromState = location.state?.authors;
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
    getInitialActiveAuthorIds(originalAuthors),
  );

  const skipDebounceRef = useRef(true);

  useEffect(() => {
    skipDebounceRef.current = true;
    setActiveAuthorIds(getInitialActiveAuthorIds(originalAuthors));
  }, [originalAuthors]);

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
  const [nextCursor, setNextCursor] = useState(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);
  const [unsupported, setUnsupported] = useState(false);
  const [unsupportedReason, setUnsupportedReason] = useState(null);
  const [initialEmpty, setInitialEmpty] = useState(false);
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);

  const requestIdRef = useRef(0);
  const resetAbortRef = useRef(null);
  const loadMoreAbortRef = useRef(null);
  const loadMoreInFlightRef = useRef(false);
  const applyInFlightRef = useRef(false);
  const selectionKeyRef = useRef(selectionKey);
  const requestKeyRef = useRef(`${selectionKey}::${appliedFiltersKey}`);
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

  selectionKeyRef.current = selectionKey;
  appliedFiltersKeyRef.current = appliedFiltersKey;
  appliedFiltersRef.current = appliedFilters;
  filtersPayloadRef.current = appliedFiltersPayload;
  requestKeyRef.current = `${selectionKey}::${appliedFiltersKey}`;
  paginationStateRef.current = {
    hasMore,
    nextCursor,
    loading,
    loadingMore,
    unsupported,
    error,
  };

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
        body: "Try adjusting the year range, source, venue, or grant filters.",
      };
    }
    return base;
  }, [mode, appliedFilters]);

  const resetAndLoad = useCallback(
    async ({
      filtersOverride,
      filtersKeyOverride,
      preserveExisting: preserveExistingOption,
      forceRefresh = false,
    } = {}) => {
      if (activeAuthors.length === 0) {
        setItems([]);
        setTimeline(null);
        setTimelineError(null);
        setFacets(emptyFacets());
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
      const fetchRequestKey = `${selectionKeyRef.current}::${filtersKeyForCache}`;

      filtersPayloadRef.current = filtersForRequest;
      appliedFiltersKeyRef.current = filtersKeyForCache;
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
        setTimeline(cached.timeline ?? null);
        setTimelineError(null);
        setFacets(cached.facets || emptyFacets());
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
      }
      setNextCursor(null);
      setHasMore(false);
      seenIdsRef.current = new Set();

      try {
        const response = await fetchAuthorPublications({
          authors: activeAuthors,
          originalAuthorIds,
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
          unsupported: response.unsupported,
          unsupported_reason: response.unsupported_reason,
        });

        setItems(pageItems);
        setTimeline(response.timeline ?? null);
        setTimelineError(null);
        setFacets(response.facets || emptyFacets());
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
  loadMoreRef.current = loadMore;

  const resetAndLoadRef = useRef(resetAndLoad);
  resetAndLoadRef.current = resetAndLoad;

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

  // Author selection drives the main fetch. Draft filter edits never fetch here.
  useEffect(() => {
    const emptyFilters = emptyPublicationFilters();
    setDraftFilters(emptyFilters);
    setAppliedFilters(emptyFilters);
    setFacets(emptyFacets());

    const emptyPayload = toPublicationFiltersPayload(emptyFilters);
    filtersPayloadRef.current = emptyPayload;
    appliedFiltersKeyRef.current = EMPTY_FILTERS_KEY;
    appliedFiltersRef.current = emptyFilters;
    requestKeyRef.current = `${selectionKey}::${EMPTY_FILTERS_KEY}`;

    const runFetch = () => {
      resetAndLoadRef.current({
        filtersOverride: emptyPayload,
        filtersKeyOverride: EMPTY_FILTERS_KEY,
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
  }, [selectionKey]);

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
      requestKeyRef.current = `${selectionKeyRef.current}::${key}`;
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
    requestKeyRef.current = `${selectionKeyRef.current}::${EMPTY_FILTERS_KEY}`;
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
      requestKeyRef.current = `${selectionKeyRef.current}::${key}`;
      resetAndLoad({
        filtersOverride: payload,
        filtersKeyOverride: key,
        preserveExisting: true,
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
    navigate("/analyze/authors/insights", {
      state: {
        authors: activeAuthors.length > 0 ? activeAuthors : originalAuthors,
        authorNames: (activeAuthors.length > 0 ? activeAuthors : originalAuthors).map(
          (author) => author.display_name,
        ),
      },
    });
  };

  const showFilters = originalAuthors.length > 0;

  const authorFilterSection = showFilters ? (
    <Box sx={{ mb: 2.5 }}>
      <Box
        sx={{
          display: "flex",
          flexWrap: "wrap",
          gap: { xs: 0.5, sm: 1 },
          alignItems: "center",
        }}
      >
        {originalAuthors.map((author) => {
          const authorId = author.canonical_author_id;
          const checked = activeAuthorIds.has(authorId);
          const disabled = isAuthorCheckboxDisabled(activeAuthorIds, authorId);
          return (
            <FormControlLabel
              key={authorId}
              control={
                <Checkbox
                  size="small"
                  checked={checked}
                  disabled={disabled}
                  onChange={() => handleToggleAuthor(authorId)}
                  inputProps={{ "aria-label": author.display_name }}
                  sx={{ py: 0.25 }}
                />
              }
              label={
                <Typography variant="body2" sx={{ lineHeight: 1.4 }}>
                  {author.display_name}
                </Typography>
              }
              sx={{
                m: 0,
                mr: 1,
                "& .MuiFormControlLabel-label": {
                  color: checked ? "text.primary" : "text.secondary",
                },
              }}
            />
          );
        })}
      </Box>
    </Box>
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
          Return to author search
        </Button>

        <Box
          sx={{
            display: "flex",
            alignItems: { xs: "stretch", sm: "center" },
            justifyContent: "space-between",
            flexDirection: { xs: "column", sm: "row" },
            gap: 1.5,
            mb: 1.5,
          }}
        >
          <Typography variant="h4" component="h1" fontWeight={600}>
            {title}
          </Typography>
          <Button
            variant="outlined"
            startIcon={<InsightsOutlinedIcon />}
            onClick={handleOpenInsights}
            data-testid="open-author-insights"
            sx={{
              textTransform: "none",
              borderRadius: 999,
              alignSelf: { xs: "flex-start", sm: "center" },
              flexShrink: 0,
            }}
          >
            Analysis
          </Button>
        </Box>

        {authorFilterSection}

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
            disabled={unsupported || activeAuthors.length === 0}
            applying={loading && hasLoadedOnce}
          />
        ) : null}

        {!unsupported ? (
          <AuthorPublicationTrendChart
            timeline={timeline}
            loading={loading}
            mode={mode}
            error={timelineError}
          />
        ) : null}

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
      </Box>
    </AuthorInfoPopoverProvider>
  );
}

export default AuthorAnalysisPage;
