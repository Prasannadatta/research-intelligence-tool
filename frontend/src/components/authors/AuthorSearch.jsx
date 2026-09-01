import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  forwardRef,
} from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Autocomplete,
  Avatar,
  Box,
  CircularProgress,
  IconButton,
  InputBase,
  MenuItem,
  Paper,
  Select,
  Typography,
} from "@mui/material";
import SearchRoundedIcon from "@mui/icons-material/SearchRounded";

import {
  ENTITY_PLACEHOLDERS,
  ENTITY_TYPES,
  FALLBACK_CAPABILITIES,
  SEARCH_SOURCES,
  buildSearchCacheKey,
  fetchSearchCapabilities,
  minQueryLengthForEntity,
  normalizeSearchQuery,
  resolveCompatibleSource,
  unifiedSearch,
} from "../../api/searchApi";
import {
  GRANT_SUGGESTION_LIMIT,
  buildGrantPublicationsPath,
  fetchGrantSuggestions,
  grantSuggestionKey,
  isValidGrantNavigationInput,
  normalizeGrantInput,
} from "../../api/grantsApi";
import WorkCard from "../works/WorkCard";
import AuthorFilters from "./AuthorFilters";
import SourceSelector from "./SourceSelector";

const DEBOUNCE_MS = 400;
const GRANT_DEBOUNCE_MS = 300;
const PAGE_SIZE = 20;
const SEARCH_ERROR_MESSAGE =
  "Search is temporarily unavailable. Please try again.";
const ARXIV_SEARCH_ERROR_MESSAGE =
  "arXiv search is temporarily unavailable. Please try again.";
const ARXIV_WORKS_NO_RESULTS_MESSAGE =
  "No matching arXiv papers were found.";
const ARXIV_AUTHORS_NO_RESULTS_MESSAGE =
  "No matching author names were found in arXiv paper metadata.";
const AUTHOR_MIN_CHARS_MESSAGE =
  "Enter at least 3 characters of an author’s name.";
const FILTERS_STALE_MESSAGE =
  "Search again to apply updated filters.";

const clampOneLine = {
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const clampTwoLines = {
  overflow: "hidden",
  display: "-webkit-box",
  WebkitBoxOrient: "vertical",
  WebkitLineClamp: 2,
};

/** Session-scoped page cache. Key includes cursor. Not persisted. */
const searchPageCache = new Map();

function getInitials(name = "") {
  return String(name)
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

function formatCount(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return null;
  }
  return Number(value).toLocaleString();
}

function getResultKey(item) {
  if (item?.grant_number || item?.result_type === "grant_suggestion") {
    return grantSuggestionKey(item);
  }
  return item?.result_id || "";
}

function getPrimaryLabel(item) {
  if (!item) {
    return "";
  }
  if (item.grant_number || item.result_type === "grant_suggestion") {
    return item.grant_number || "";
  }
  if (item.result_type === "work") {
    return item.title || "";
  }
  return item.display_name || item.title || "";
}

function mergeAuthorResolutionOptions(existing, payload, selectedIds) {
  const selected = new Set((selectedIds || []).filter(Boolean));
  const byId = new Map();
  const order = [];

  for (const item of existing || []) {
    const id = getResultKey(item);
    if (!id) {
      continue;
    }
    byId.set(id, item);
    order.push(id);
  }

  for (const update of payload.updates || []) {
    const author = update?.author;
    const id = update?.canonical_author_id || getResultKey(author);
    if (!id || !author || !byId.has(id)) {
      continue;
    }
    byId.set(id, author);
  }

  const insertAuthors = Array.isArray(payload.items) && payload.items.length > 0
    ? payload.items
        .filter((entry) => entry?.operation === "insert" && entry.author)
        .map((entry) => entry.author)
    : Array.isArray(payload.results)
      ? payload.results
      : [];

  for (const author of insertAuthors) {
    const id = getResultKey(author);
    if (!id || selected.has(id) || byId.has(id)) {
      continue;
    }
    byId.set(id, author);
    order.push(id);
  }

  return order.map((id) => byId.get(id)).filter(Boolean);
}

function appendUniqueByResultId(existing, incoming) {
  const seen = new Set(existing.map(getResultKey).filter(Boolean));
  const merged = [...existing];
  for (const item of incoming) {
    const key = getResultKey(item);
    if (!key || seen.has(key)) {
      continue;
    }
    seen.add(key);
    merged.push(item);
  }
  return merged;
}

function AuthorResultsPaper({ children, ...other }, ref) {
  return (
    <Paper
      ref={ref}
      elevation={0}
      {...other}
      sx={{
        mt: 1,
        border: "1px solid",
        borderColor: "divider",
        borderRadius: "16px",
        bgcolor: "background.paper",
        overflow: "hidden",
        // Shadow stays on non-scrolling parent only.
        boxShadow: (theme) =>
          theme.palette.mode === "dark"
            ? "0 10px 28px rgba(0,0,0,0.32)"
            : "0 10px 28px rgba(15,23,42,0.08)",
      }}
    >
      {children}
    </Paper>
  );
}

const AuthorResultsPaperForward = forwardRef(AuthorResultsPaper);

const SearchListbox = memo(
  forwardRef(function SearchListbox(props, ref) {
    const {
      children,
      loadingMore = false,
      showEnd = false,
      onNearEnd,
      playEntranceFade = false,
      onEntranceFadeEnd,
      ownerState: _ownerState,
      ...other
    } = props;

    const rootRef = useRef(null);
    const sentinelRef = useRef(null);
    const onNearEndRef = useRef(onNearEnd);
    onNearEndRef.current = onNearEnd;

    const setRefs = useCallback(
      (node) => {
        rootRef.current = node;
        if (typeof ref === "function") {
          ref(node);
        } else if (ref) {
          ref.current = node;
        }
      },
      [ref],
    );

    useEffect(() => {
      const root = rootRef.current;
      const sentinel = sentinelRef.current;
      if (!root || !sentinel || typeof IntersectionObserver === "undefined") {
        return undefined;
      }

      const observer = new IntersectionObserver(
        (entries) => {
          if (entries.some((entry) => entry.isIntersecting)) {
            onNearEndRef.current?.();
          }
        },
        {
          root,
          rootMargin: "0px 0px 160px 0px",
          threshold: 0,
        },
      );

      observer.observe(sentinel);
      return () => {
        observer.disconnect();
      };
    }, []);

    return (
      <Box
        component="ul"
        ref={setRefs}
        {...other}
        onAnimationEnd={(event) => {
          if (event.target === rootRef.current) {
            onEntranceFadeEnd?.();
          }
        }}
        sx={{
          maxHeight: 320,
          py: 0.75,
          px: 0.5,
          m: 0,
          listStyle: "none",
          overflowY: "auto",
          overscrollBehavior: "contain",
          scrollbarGutter: "stable",
          touchAction: "pan-y",
          contain: "layout paint",
          bgcolor: "background.paper",
          animation: playEntranceFade
            ? "searchResultsFadeIn 140ms ease"
            : "none",
          "@keyframes searchResultsFadeIn": {
            from: { opacity: 0 },
            to: { opacity: 1 },
          },
        }}
      >
        {children}
        <Box
          component="li"
          ref={sentinelRef}
          aria-hidden
          sx={{
            listStyle: "none",
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            py: 1,
            minHeight: 36,
          }}
        >
          {loadingMore ? (
            <CircularProgress
              size={16}
              thickness={5}
              sx={{ color: "text.secondary" }}
              aria-label="Loading more results"
            />
          ) : showEnd ? (
            <Typography variant="caption" color="text.disabled">
              End of results
            </Typography>
          ) : (
            <Box sx={{ height: 8, width: 8 }} />
          )}
        </Box>
      </Box>
    );
  }),
);

const AuthorResultRow = memo(function AuthorResultRow({
  option,
  selectedInstitutionId,
  selectedTopicId,
}) {
  const institutionName =
    option.primary_institution?.name?.trim() || "Institution unavailable";
  const institutionMatched =
    Boolean(selectedInstitutionId) &&
    option.primary_institution?.id === selectedInstitutionId;

  const topics = Array.isArray(option.topics) ? option.topics : [];
  const topicNames = topics
    .map((topic) => topic?.name)
    .filter(Boolean)
    .slice(0, 2);
  const matchedTopicId = selectedTopicId || null;

  const works = formatCount(option.works_count);
  const citations = formatCount(option.cited_by_count);
  const meta = [
    works != null ? `${works} works` : null,
    citations != null ? `${citations} citations` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const grantLine =
    option.match_reason === "grant_number" &&
    option.matching_funded_works_count != null
      ? `${Number(option.matching_funded_works_count).toLocaleString()} paper${
          Number(option.matching_funded_works_count) === 1 ? "" : "s"
        } funded by ${
          option.matched_grant?.award_id ||
          option.matched_grant?.display_name ||
          "this grant"
        }`
      : "";

  return (
    <Box
      sx={{
        display: "flex",
        alignItems: "flex-start",
        gap: 1.5,
        minHeight: 84,
      }}
    >
      <Avatar
        alt=""
        aria-hidden
        sx={{
          width: 38,
          height: 38,
          mt: 0.15,
          fontSize: "0.85rem",
          fontWeight: 600,
          bgcolor: "action.selected",
          color: "text.primary",
          flexShrink: 0,
        }}
      >
        {getInitials(option.display_name)}
      </Avatar>
      <Box sx={{ minWidth: 0, textAlign: "left", flex: 1 }}>
        <Typography
          variant="body1"
          fontWeight={600}
          sx={{ lineHeight: 1.35, ...clampOneLine }}
        >
          {option.display_name}
        </Typography>
        <Typography
          variant="body2"
          sx={{
            lineHeight: 1.4,
            mt: 0.15,
            minHeight: 20,
            fontWeight: institutionMatched ? 600 : 400,
            color: institutionMatched ? "text.primary" : "text.secondary",
            ...clampOneLine,
          }}
        >
          {institutionName}
        </Typography>
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: "block", lineHeight: 1.4, mt: 0.15, minHeight: 18, ...clampOneLine }}
        >
          {topicNames.map((name, index) => {
            const topic = topics.find((item) => item?.name === name);
            const emphasize = matchedTopicId && topic?.id === matchedTopicId;
            return (
              <Box
                component="span"
                key={`${option.result_id}-topic-${name}`}
                sx={{
                  fontWeight: emphasize ? 600 : 400,
                  color: emphasize ? "text.primary" : "inherit",
                }}
              >
                {index > 0 ? " · " : ""}
                {name}
              </Box>
            );
          })}
        </Typography>
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: "block", lineHeight: 1.4, mt: 0.15, minHeight: 18, ...clampOneLine }}
        >
          {meta}
        </Typography>
        {option.identity_resolution?.status === "merged" ? (
          <Typography
            variant="caption"
            color="text.disabled"
            sx={{ display: "block", lineHeight: 1.35, mt: 0.1, ...clampOneLine }}
          >
            Linked identity
            {Array.isArray(option.source_records) && option.source_records.length > 1
              ? ` · ${option.source_records.length} source records`
              : ""}
          </Typography>
        ) : null}
        <Typography
          variant="caption"
          color="text.disabled"
          sx={{ display: "block", lineHeight: 1.35, mt: 0.1, minHeight: 16, ...clampOneLine }}
        >
          {grantLine}
        </Typography>
      </Box>
    </Box>
  );
});

const WorkResultRow = WorkCard;

const ArxivAuthorNameResultRow = memo(function ArxivAuthorNameResultRow({
  option,
}) {
  const sampleTitles = (Array.isArray(option.sample_papers)
    ? option.sample_papers
    : []
  )
    .map((paper) => paper?.title)
    .filter(Boolean)
    .slice(0, 2);
  const paperCount =
    option.matching_papers_count != null
      ? Number(option.matching_papers_count).toLocaleString()
      : null;

  return (
    <Box sx={{ minWidth: 0, textAlign: "left", minHeight: 84 }}>
      <Box sx={{ display: "flex", alignItems: "flex-start", gap: 0.75 }}>
        <Typography
          variant="body1"
          fontWeight={600}
          sx={{ lineHeight: 1.35, flex: 1, minWidth: 0, ...clampOneLine }}
        >
          {option.display_name}
        </Typography>
        <Typography
          variant="caption"
          sx={{
            flexShrink: 0,
            mt: 0.2,
            px: 0.6,
            py: 0.1,
            borderRadius: 1,
            bgcolor: "action.hover",
            color: "text.secondary",
            fontWeight: 600,
          }}
        >
          arXiv metadata
        </Typography>
      </Box>
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ display: "block", lineHeight: 1.4, mt: 0.2, ...clampOneLine }}
      >
        From arXiv paper metadata
        {paperCount != null
          ? ` · ${paperCount} matching paper${
              Number(option.matching_papers_count) === 1 ? "" : "s"
            }`
          : ""}
      </Typography>
      <Typography
        variant="caption"
        color="warning.main"
        sx={{ display: "block", lineHeight: 1.35, mt: 0.15, fontWeight: 500 }}
        title="Names are extracted from paper metadata and are not verified researcher profiles."
      >
        Unverified author identity
      </Typography>
      {sampleTitles.map((title) => (
        <Typography
          key={`${option.result_id}-${title}`}
          variant="caption"
          color="text.disabled"
          sx={{ display: "block", lineHeight: 1.35, mt: 0.1, ...clampOneLine }}
        >
          {title}
        </Typography>
      ))}
    </Box>
  );
});

const GrantResultRow = memo(function GrantResultRow({ option }) {
  const years =
    option.start_year || option.end_year
      ? [option.start_year, option.end_year].filter((v) => v != null).join("–")
      : null;
  const secondary = option.funder_name || "";
  const tertiary = [option.lead_investigator, years].filter(Boolean).join(" · ");

  return (
    <Box sx={{ minWidth: 0, textAlign: "left", minHeight: 78 }}>
      <Typography
        variant="body1"
        fontWeight={600}
        sx={{ lineHeight: 1.35, ...clampTwoLines }}
      >
        {option.display_name || "Untitled grant"}
      </Typography>
      <Typography
        variant="body2"
        color="text.primary"
        sx={{ lineHeight: 1.4, mt: 0.15, fontWeight: 600, minHeight: 20, ...clampOneLine }}
      >
        {option.funder_award_id || " "}
      </Typography>
      <Typography
        variant="body2"
        color="text.secondary"
        sx={{ lineHeight: 1.4, mt: 0.15, minHeight: 20, ...clampOneLine }}
      >
        {secondary}
      </Typography>
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ display: "block", lineHeight: 1.4, mt: 0.15, minHeight: 18, ...clampOneLine }}
      >
        {tertiary}
      </Typography>
    </Box>
  );
});

const GrantSuggestionRow = memo(function GrantSuggestionRow({ option }) {
  const count =
    option.publication_count != null && !Number.isNaN(Number(option.publication_count))
      ? Number(option.publication_count)
      : null;
  const secondary = [
    option.funder_name || null,
    count != null
      ? `${count.toLocaleString()} publication${count === 1 ? "" : "s"}`
      : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <Box sx={{ minWidth: 0, textAlign: "left", minHeight: 56 }}>
      <Typography
        variant="body1"
        fontWeight={600}
        sx={{ lineHeight: 1.35, ...clampOneLine }}
      >
        {option.grant_number}
      </Typography>
      <Typography
        variant="body2"
        color="text.secondary"
        sx={{ lineHeight: 1.4, mt: 0.2, minHeight: 20, ...clampOneLine }}
      >
        {secondary || (option.verified ? "Verified grant" : "Grant number")}
      </Typography>
    </Box>
  );
});

function AuthorSearch({
  entityType = ENTITY_TYPES.AUTHORS,
  onEntityTypeChange,
  onResultSelected,
  selectedResultIds = [],
}) {
  const navigate = useNavigate();
  const [inputValue, setInputValue] = useState("");
  const [options, setOptions] = useState([]);
  const [initialLoading, setInitialLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [nextCursor, setNextCursor] = useState(null);
  const [hasMore, setHasMore] = useState(false);
  const [searchSessionId, setSearchSessionId] = useState(null);
  const [playEntranceFade, setPlayEntranceFade] = useState(false);
  const [institutionFilter, setInstitutionFilter] = useState(null);
  const [topicFilter, setTopicFilter] = useState(null);
  // Committed values actually used for GET /api/search (authors).
  const [committedSearch, setCommittedSearch] = useState(null);
  const [resultsAreStale, setResultsAreStale] = useState(false);
  const [validationMessage, setValidationMessage] = useState(null);
  const [capabilities, setCapabilities] = useState(FALLBACK_CAPABILITIES);
  const [source, setSource] = useState(SEARCH_SOURCES.ALL);

  const requestIdRef = useRef(0);
  const abortControllerRef = useRef(null);
  const activeRequestRef = useRef(false);
  const loadingMoreRef = useRef(false);
  const loadedCursorsRef = useRef(new Set());
  const selectedIdsRef = useRef(selectedResultIds);
  const entityTypeRef = useRef(entityType);
  const sourceRef = useRef(source);
  const nextCursorRef = useRef(null);
  const hasMoreRef = useRef(false);
  const searchSessionIdRef = useRef(null);
  const normalizedQueryRef = useRef("");
  const committedSearchRef = useRef(null);
  const resultsAreStaleRef = useRef(false);
  const debounceTimeoutRef = useRef(null);
  const institutionFilterRef = useRef(null);
  const topicFilterRef = useRef(null);
  const optionsRef = useRef([]);

  selectedIdsRef.current = selectedResultIds;
  entityTypeRef.current = entityType;
  sourceRef.current = source;
  nextCursorRef.current = nextCursor;
  hasMoreRef.current = hasMore;
  searchSessionIdRef.current = searchSessionId;
  loadingMoreRef.current = loadingMore;
  committedSearchRef.current = committedSearch;
  resultsAreStaleRef.current = resultsAreStale;
  institutionFilterRef.current = institutionFilter;
  topicFilterRef.current = topicFilter;
  optionsRef.current = options;

  const normalizedQuery = normalizeSearchQuery(inputValue, entityType);
  normalizedQueryRef.current = normalizedQuery;
  const isAuthors = entityType === ENTITY_TYPES.AUTHORS;
  const isGrants = entityType === ENTITY_TYPES.GRANTS;
  const isOpenAlex = source === SEARCH_SOURCES.OPENALEX;
  const usesAuthorFilters =
    isOpenAlex || source === SEARCH_SOURCES.ALL;
  const isArxiv = source === SEARCH_SOURCES.ARXIV;
  const minQueryLength = minQueryLengthForEntity(entityType);
  const canSearch = normalizedQuery.length >= minQueryLength;
  const showAuthorFilters = isAuthors && usesAuthorFilters;


  const selectedIdSet = useMemo(
    () => new Set(selectedResultIds.filter(Boolean)),
    [selectedResultIds],
  );

  const availableOptions = useMemo(
    () => options.filter((item) => !selectedIdSet.has(getResultKey(item))),
    [options, selectedIdSet],
  );

  const cancelActiveRequest = useCallback(() => {
    requestIdRef.current += 1;
    activeRequestRef.current = false;
    loadingMoreRef.current = false;
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  }, []);

  const resetResultsState = useCallback(() => {
    setOptions([]);
    setNextCursor(null);
    setHasMore(false);
    setSearchSessionId(null);
    setHasSearched(false);
    setError(null);
    setInitialLoading(false);
    setLoadingMore(false);
    loadingMoreRef.current = false;
    setPlayEntranceFade(false);
    loadedCursorsRef.current = new Set();
    setCommittedSearch(null);
    setResultsAreStale(false);
    setValidationMessage(null);
  }, []);

  const markAuthorResultsStale = useCallback(() => {
    // Keep existing rows visible, but stop pagination until a new committed search.
    setResultsAreStale(true);
    setNextCursor(null);
    setHasMore(false);
    setSearchSessionId(null);
    loadedCursorsRef.current = new Set();
  }, []);

  const applyPagePayload = useCallback(
    ({ payload, append, requestCursor, isFirstPage, entityType: pageEntity }) => {
      const isAuthorsPage = pageEntity === ENTITY_TYPES.AUTHORS;

      setOptions((current) => {
        if (isAuthorsPage) {
          const base = append ? current : [];
          return mergeAuthorResolutionOptions(
            base,
            payload,
            selectedIdsRef.current,
          );
        }

        const pageResults = Array.isArray(payload.results) ? payload.results : [];
        const filtered = pageResults.filter(
          (item) => !selectedIdsRef.current.includes(getResultKey(item)),
        );
        return append ? appendUniqueByResultId(current, filtered) : filtered;
      });
      setNextCursor(payload.next_cursor ?? null);
      setHasMore(Boolean(payload.has_more));
      if (payload.search_session_id) {
        setSearchSessionId(payload.search_session_id);
      }
      setHasSearched(true);
      setError(null);
      if (isFirstPage) {
        setPlayEntranceFade(true);
      }
      loadedCursorsRef.current.add(requestCursor || "*");
    },
    [],
  );

  const fetchPage = useCallback(
    async ({
      query,
      type,
      source: requestSource,
      cursor,
      append,
      requestId,
      isFirstPage,
      institutionId = "",
      topicId = "",
      knownAuthorIds = [],
      searchSessionId: requestSessionId,
    }) => {
      const requestCursor = cursor == null || cursor === "" ? "*" : cursor;
      if (loadedCursorsRef.current.has(requestCursor) && append) {
        return;
      }
      if ((activeRequestRef.current || loadingMoreRef.current) && append) {
        return;
      }

      const cacheKey = buildSearchCacheKey({
        source: requestSource,
        entityType: type,
        query,
        cursor: requestCursor,
        institutionId,
        topicId,
      });
      const cached = searchPageCache.get(cacheKey);
      if (cached) {
        applyPagePayload({
          payload: cached,
          append,
          requestCursor,
          isFirstPage: Boolean(isFirstPage && !append),
          entityType: type,
        });
        setInitialLoading(false);
        setLoadingMore(false);
        loadingMoreRef.current = false;
        activeRequestRef.current = false;
        return;
      }

      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      const controller = new AbortController();
      abortControllerRef.current = controller;
      activeRequestRef.current = true;

      if (append) {
        loadingMoreRef.current = true;
        setLoadingMore(true);
      } else {
        setInitialLoading(true);
        setError(null);
      }

      try {
        const payload = await unifiedSearch({
          query,
          entityType: type,
          source: requestSource,
          limit: PAGE_SIZE,
          cursor: requestCursor,
          institutionId:
            (requestSource === SEARCH_SOURCES.OPENALEX ||
              requestSource === SEARCH_SOURCES.ALL) &&
            type === ENTITY_TYPES.AUTHORS
              ? institutionId
              : "",
          topicId:
            (requestSource === SEARCH_SOURCES.OPENALEX ||
              requestSource === SEARCH_SOURCES.ALL) &&
            type === ENTITY_TYPES.AUTHORS
              ? topicId
              : "",
          knownAuthorIds:
            type === ENTITY_TYPES.AUTHORS ? knownAuthorIds : [],
          searchSessionId:
            type === ENTITY_TYPES.WORKS || type === ENTITY_TYPES.GRANTS
              ? requestSessionId || undefined
              : undefined,
          signal: controller.signal,
        });

        if (requestId !== requestIdRef.current) {
          return;
        }

        searchPageCache.set(cacheKey, payload);
        applyPagePayload({
          payload,
          append,
          requestCursor,
          isFirstPage: Boolean(isFirstPage && !append),
          entityType: type,
        });
        setOpen(true);
      } catch (err) {
        if (
          requestId !== requestIdRef.current ||
          err?.code === "ERR_CANCELED" ||
          err?.name === "CanceledError" ||
          err?.name === "AbortError"
        ) {
          return;
        }
        if (!append) {
          setOptions([]);
          setNextCursor(null);
          setHasMore(false);
          setSearchSessionId(null);
          setOpen(false);
        }
        setHasSearched(true);
        setError(
          requestSource === SEARCH_SOURCES.ARXIV
            ? ARXIV_SEARCH_ERROR_MESSAGE
            : SEARCH_ERROR_MESSAGE,
        );
      } finally {
        if (requestId === requestIdRef.current) {
          activeRequestRef.current = false;
          loadingMoreRef.current = false;
          setInitialLoading(false);
          setLoadingMore(false);
        }
      }
    },
    [applyPagePayload],
  );

  const startFirstPageSearch = useCallback(
    ({
      query,
      type,
      source: requestSource,
      institutionId = "",
      topicId = "",
    }) => {
      cancelActiveRequest();
      loadedCursorsRef.current = new Set();
      setNextCursor(null);
      setHasMore(false);
      setSearchSessionId(null);
      setResultsAreStale(false);
      setValidationMessage(null);
      setError(null);

      const committed = {
        query,
        source: requestSource,
        institutionId:
          (requestSource === SEARCH_SOURCES.OPENALEX ||
            requestSource === SEARCH_SOURCES.ALL) &&
          type === ENTITY_TYPES.AUTHORS
            ? institutionId || ""
            : "",
        topicId:
          (requestSource === SEARCH_SOURCES.OPENALEX ||
            requestSource === SEARCH_SOURCES.ALL) &&
          type === ENTITY_TYPES.AUTHORS
            ? topicId || ""
            : "",
      };
      setCommittedSearch(committed);
      committedSearchRef.current = committed;

      const requestId = ++requestIdRef.current;
      setOpen(true);
      fetchPage({
        query,
        type,
        source: requestSource,
        cursor: "*",
        append: false,
        requestId,
        isFirstPage: true,
        institutionId: committed.institutionId,
        topicId: committed.topicId,
        knownAuthorIds: [],
        searchSessionId: null,
      });
    },
    [cancelActiveRequest, fetchPage],
  );

  useEffect(() => {
    let cancelled = false;
    fetchSearchCapabilities().then((payload) => {
      if (cancelled) {
        return;
      }
      setCapabilities(payload);
      setSource((current) =>
        resolveCompatibleSource(payload, entityTypeRef.current, current),
      );
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (
      entityType !== ENTITY_TYPES.AUTHORS ||
      (source !== SEARCH_SOURCES.OPENALEX && source !== SEARCH_SOURCES.ALL)
    ) {
      setInstitutionFilter(null);
      setTopicFilter(null);
    }
  }, [entityType, source]);

  // When entity changes, auto-correct incompatible sources.
  useEffect(() => {
    const nextSource = resolveCompatibleSource(capabilities, entityType, source);
    if (nextSource !== source) {
      setSource(nextSource);
    }
  }, [capabilities, entityType, source]);

  // Debounced search / grant suggestions: query / entity / source.
  useEffect(() => {
    cancelActiveRequest();

    if (debounceTimeoutRef.current) {
      window.clearTimeout(debounceTimeoutRef.current);
      debounceTimeoutRef.current = null;
    }

    if (normalizedQuery.length < minQueryLength) {
      resetResultsState();
      setOpen(false);
      return undefined;
    }

    const type = entityType;
    const requestSource = source;
    setValidationMessage(null);

    const delay =
      type === ENTITY_TYPES.GRANTS ? GRANT_DEBOUNCE_MS : DEBOUNCE_MS;

    debounceTimeoutRef.current = window.setTimeout(() => {
      debounceTimeoutRef.current = null;

      if (type === ENTITY_TYPES.GRANTS) {
        const requestId = ++requestIdRef.current;
        const controller = new AbortController();
        abortControllerRef.current = controller;
        activeRequestRef.current = true;
        setInitialLoading(true);
        setError(null);
        setHasSearched(true);
        setHasMore(false);
        setNextCursor(null);
        setOpen(true);

        fetchGrantSuggestions({
          q: normalizedQuery,
          provider: requestSource,
          limit: GRANT_SUGGESTION_LIMIT,
          signal: controller.signal,
        })
          .then((payload) => {
            if (requestId !== requestIdRef.current) {
              return;
            }
            const items = (Array.isArray(payload.items) ? payload.items : []).map(
              (item) => ({
                ...item,
                result_type: "grant_suggestion",
                result_id: grantSuggestionKey(item),
              }),
            );
            setOptions(items.slice(0, GRANT_SUGGESTION_LIMIT));
            setHasMore(false);
            setNextCursor(null);
          })
          .catch((err) => {
            if (err?.name === "CanceledError" || err?.code === "ERR_CANCELED") {
              return;
            }
            if (requestId !== requestIdRef.current) {
              return;
            }
            setOptions([]);
            setError(
              err?.response?.data?.detail ||
                "Grant suggestions are temporarily unavailable. Please try again.",
            );
          })
          .finally(() => {
            if (requestId === requestIdRef.current) {
              activeRequestRef.current = false;
              setInitialLoading(false);
            }
          });
        return;
      }

      const institutionId =
        (requestSource === SEARCH_SOURCES.OPENALEX ||
          requestSource === SEARCH_SOURCES.ALL) &&
        type === ENTITY_TYPES.AUTHORS
          ? institutionFilterRef.current?.id || ""
          : "";
      const topicId =
        (requestSource === SEARCH_SOURCES.OPENALEX ||
          requestSource === SEARCH_SOURCES.ALL) &&
        type === ENTITY_TYPES.AUTHORS
          ? topicFilterRef.current?.id || ""
          : "";
      startFirstPageSearch({
        query: normalizedQuery,
        type,
        source: requestSource,
        institutionId,
        topicId,
      });
    }, delay);

    return () => {
      if (debounceTimeoutRef.current) {
        window.clearTimeout(debounceTimeoutRef.current);
        debounceTimeoutRef.current = null;
      }
    };
  }, [
    normalizedQuery,
    entityType,
    source,
    minQueryLength,
    cancelActiveRequest,
    resetResultsState,
    startFirstPageSearch,
  ]);

  const loadMore = useCallback(() => {
    if (
      resultsAreStaleRef.current ||
      !hasMoreRef.current ||
      activeRequestRef.current ||
      loadingMoreRef.current
    ) {
      return;
    }
    const cursor = nextCursorRef.current;
    if (!cursor || loadedCursorsRef.current.has(cursor)) {
      return;
    }

    const committed = committedSearchRef.current;
    if (!committed?.query) {
      return;
    }

    const requestId = ++requestIdRef.current;
    fetchPage({
      query: committed.query,
      type: entityTypeRef.current,
      source: committed.source || sourceRef.current,
      cursor,
      append: true,
      requestId,
      isFirstPage: false,
      institutionId: committed.institutionId || "",
      topicId: committed.topicId || "",
      knownAuthorIds: optionsRef.current.map(getResultKey).filter(Boolean),
      searchSessionId: searchSessionIdRef.current,
    });
  }, [fetchPage]);

  const handleEntranceFadeEnd = useCallback(() => {
    setPlayEntranceFade(false);
  }, []);

  const showDropdown =
    open &&
    (canSearch || hasSearched) &&
    (initialLoading || hasSearched || availableOptions.length > 0);

  const clearSearchState = useCallback(() => {
    cancelActiveRequest();
    setInputValue("");
    resetResultsState();
    setOpen(false);
  }, [cancelActiveRequest, resetResultsState]);

  const openGrant = useCallback(
    (grant) => {
      const grantNumber =
        typeof grant === "string"
          ? normalizeGrantInput(grant)
          : normalizeGrantInput(grant?.grant_number);
      if (!isValidGrantNavigationInput(grantNumber)) {
        return;
      }
      const path = buildGrantPublicationsPath(grantNumber, source);
      if (!path) {
        return;
      }
      cancelActiveRequest();
      setInputValue("");
      resetResultsState();
      setOpen(false);
      navigate(path);
    },
    [cancelActiveRequest, navigate, resetResultsState, source],
  );

  const handleEntityTypeChange = useCallback(
    (event) => {
      const nextType = event.target.value;
      cancelActiveRequest();
      resetResultsState();
      setOpen(false);
      if (nextType !== ENTITY_TYPES.AUTHORS) {
        setInstitutionFilter(null);
        setTopicFilter(null);
      }
      const nextSource = resolveCompatibleSource(capabilities, nextType, source);
      if (nextSource !== source) {
        setSource(nextSource);
      }
      onEntityTypeChange?.(nextType);
    },
    [
      cancelActiveRequest,
      capabilities,
      onEntityTypeChange,
      resetResultsState,
      source,
    ],
  );

  const handleSourceChange = useCallback(
    (nextSource) => {
      if (!nextSource || nextSource === source) {
        return;
      }
      cancelActiveRequest();
      resetResultsState();
      setOpen(false);
      setSource(nextSource);
      // Debounce effect re-runs on source change and searches if query is valid.
    },
    [cancelActiveRequest, resetResultsState, source],
  );

  const handleInstitutionChange = useCallback(
    (next) => {
      setInstitutionFilter(next);
      if (hasSearched || availableOptions.length > 0 || committedSearch) {
        markAuthorResultsStale();
      }
    },
    [availableOptions.length, committedSearch, hasSearched, markAuthorResultsStale],
  );

  const handleTopicChange = useCallback(
    (next) => {
      setTopicFilter(next);
      if (hasSearched || availableOptions.length > 0 || committedSearch) {
        markAuthorResultsStale();
      }
    },
    [availableOptions.length, committedSearch, hasSearched, markAuthorResultsStale],
  );

  const handleExplicitSearch = useCallback(() => {
    if (isGrants) {
      openGrant(normalizedQuery);
      return;
    }

    if (normalizedQuery.length < minQueryLength) {
      if (isAuthors) {
        setValidationMessage(AUTHOR_MIN_CHARS_MESSAGE);
      }
      return;
    }

    if (debounceTimeoutRef.current) {
      window.clearTimeout(debounceTimeoutRef.current);
      debounceTimeoutRef.current = null;
    }

    startFirstPageSearch({
      query: normalizedQuery,
      type: entityType,
      source,
      institutionId:
        isAuthors && usesAuthorFilters ? institutionFilter?.id || "" : "",
      topicId: isAuthors && usesAuthorFilters ? topicFilter?.id || "" : "",
    });
  }, [
    entityType,
    institutionFilter?.id,
    isAuthors,
    isGrants,
    usesAuthorFilters,
    minQueryLength,
    normalizedQuery,
    openGrant,
    source,
    startFirstPageSearch,
    topicFilter?.id,
  ]);

  const handleSearchKeyDown = useCallback(
    (event) => {
      if (event.key !== "Enter") {
        return;
      }
      // Explicit submit — do not rely on Autocomplete option activation.
      event.preventDefault();
      event.stopPropagation();
      handleExplicitSearch();
    },
    [handleExplicitSearch],
  );

  const handleResultSelected = useCallback(
    (_event, item) => {
      if (!item) {
        return;
      }
      if (isGrants || item.result_type === "grant_suggestion" || item.grant_number) {
        openGrant(item);
        return;
      }
      if (!getResultKey(item)) {
        return;
      }
      onResultSelected?.(item);
      clearSearchState();
    },
    [clearSearchState, isGrants, onResultSelected, openGrant],
  );

  const listboxSlotProps = useMemo(
    () => ({
      loadingMore: isGrants || resultsAreStale ? false : loadingMore,
      showEnd:
        !isGrants &&
        !resultsAreStale &&
        !hasMore &&
        hasSearched &&
        availableOptions.length > 0 &&
        !initialLoading,
      onNearEnd: isGrants || resultsAreStale ? undefined : loadMore,
      playEntranceFade,
      onEntranceFadeEnd: handleEntranceFadeEnd,
    }),
    [
      isGrants,
      resultsAreStale,
      loadingMore,
      hasMore,
      hasSearched,
      availableOptions.length,
      initialLoading,
      loadMore,
      playEntranceFade,
      handleEntranceFadeEnd,
    ],
  );

  // Highlight affiliations/topics from the committed search, not pending filter edits.
  const selectedInstitutionId = committedSearch?.institutionId || null;
  const selectedTopicId = committedSearch?.topicId || null;

  const renderOption = useCallback(
    (props, option) => {
      const { key, ...optionProps } = props;
      const resultId = getResultKey(option);

      return (
        <Box
          component="li"
          key={resultId || key}
          {...optionProps}
          sx={{
            display: "block !important",
            mx: 0.25,
            px: 1.25,
            py: 1.1,
            borderRadius: 2,
            "&.Mui-focused": {
              bgcolor: "action.selected",
            },
            "&:hover": {
              bgcolor: "action.hover",
            },
          }}
        >
          {option.result_type === "grant_suggestion" ||
          (isGrants && option.grant_number) ? (
            <GrantSuggestionRow option={option} />
          ) : option.result_type === "author_name" ? (
            <ArxivAuthorNameResultRow option={option} />
          ) : option.result_type === "work" ? (
            <WorkResultRow option={option} />
          ) : option.result_type === "grant" ? (
            <GrantResultRow option={option} />
          ) : (
            <AuthorResultRow
              option={option}
              selectedInstitutionId={selectedInstitutionId}
              selectedTopicId={selectedTopicId}
            />
          )}
        </Box>
      );
    },
    [isGrants, selectedInstitutionId, selectedTopicId],
  );

  const noResultsMessage = isGrants
    ? isArxiv
      ? "No matching grant numbers found in stored arXiv grant matches."
      : "No matching grant numbers found."
    : isArxiv
      ? isAuthors
        ? ARXIV_AUTHORS_NO_RESULTS_MESSAGE
        : ARXIV_WORKS_NO_RESULTS_MESSAGE
      : "No OpenAlex matches found.";

  return (
    <Box sx={{ width: "100%", textAlign: "left" }}>
      <SourceSelector
        sources={capabilities.sources}
        value={source}
        entityType={entityType}
        onChange={handleSourceChange}
      />

      <Autocomplete
        fullWidth
        open={showDropdown}
        options={availableOptions}
        loading={initialLoading}
        value={null}
        inputValue={inputValue}
        filterOptions={(x) => x}
        forcePopupIcon={false}
        disableClearable
        clearOnBlur={false}
        slots={{
          paper: AuthorResultsPaperForward,
          listbox: SearchListbox,
        }}
        slotProps={{
          listbox: listboxSlotProps,
        }}
        isOptionEqualToValue={(option, value) =>
          getResultKey(option) === getResultKey(value)
        }
        getOptionLabel={(option) => getPrimaryLabel(option)}
        getOptionKey={(option) => getResultKey(option)}
        loadingText={
          <Box sx={{ py: 1.75, textAlign: "center" }}>
            <Typography variant="body2" color="text.secondary">
              Searching…
            </Typography>
          </Box>
        }
        noOptionsText={
          <Box sx={{ py: 1.75, textAlign: "center" }}>
            <Typography variant="body2" color="text.secondary">
              {noResultsMessage}
            </Typography>
          </Box>
        }
        onOpen={() => {
          if (
            (canSearch || hasSearched) &&
            (initialLoading || hasSearched || availableOptions.length > 0)
          ) {
            setOpen(true);
          }
        }}
        onClose={() => setOpen(false)}
        onInputChange={(_event, newInputValue, reason) => {
          if (reason === "reset") {
            return;
          }
          setInputValue(newInputValue);
          setValidationMessage(null);
          if (reason === "clear" || newInputValue.trim().length === 0) {
            cancelActiveRequest();
            resetResultsState();
            setOpen(false);
          }
        }}
        onChange={handleResultSelected}
        renderOption={renderOption}
        renderInput={(params) => {
          const inputSlot = params.slotProps?.input ?? {};
          const htmlInputSlot = params.slotProps?.htmlInput ?? {};

          return (
            <Paper
              elevation={0}
              ref={inputSlot.ref}
              className={inputSlot.className}
              onMouseDown={inputSlot.onMouseDown}
              sx={{
                display: "flex",
                alignItems: "center",
                width: "100%",
                px: 1.25,
                py: 1.1,
                border: "1px solid",
                borderColor: "divider",
                borderRadius: 4,
                bgcolor: "background.paper",
                boxShadow: "none",
                transition: "box-shadow 120ms ease, border-color 120ms ease",
                "&:focus-within": {
                  boxShadow: (theme) =>
                    theme.palette.mode === "dark"
                      ? "0 8px 24px rgba(0,0,0,0.28)"
                      : "0 8px 24px rgba(15,23,42,0.08)",
                },
              }}
            >
              <Select
                value={entityType}
                onChange={handleEntityTypeChange}
                onMouseDown={(event) => event.stopPropagation()}
                variant="standard"
                disableUnderline
                inputProps={{ "aria-label": "Search entity type" }}
                sx={{
                  mr: 0.75,
                  ml: 0.25,
                  minWidth: 96,
                  fontSize: "0.875rem",
                  fontWeight: 600,
                  color: "text.secondary",
                  "& .MuiSelect-select": {
                    py: 0.75,
                    pr: "28px !important",
                  },
                }}
              >
                <MenuItem value={ENTITY_TYPES.AUTHORS}>Authors</MenuItem>
                <MenuItem value={ENTITY_TYPES.WORKS}>Works</MenuItem>
                <MenuItem value={ENTITY_TYPES.GRANTS}>Grants</MenuItem>
              </Select>

              <Box
                sx={{
                  width: "1px",
                  alignSelf: "stretch",
                  bgcolor: "divider",
                  my: 0.5,
                  mr: 1,
                  flexShrink: 0,
                }}
              />

              <IconButton
                size="small"
                aria-label="Search"
                onMouseDown={(event) => event.preventDefault()}
                onClick={handleExplicitSearch}
                sx={{ color: "text.secondary", flexShrink: 0 }}
              >
                <SearchRoundedIcon fontSize="small" />
              </IconButton>

              <InputBase
                fullWidth
                placeholder={ENTITY_PLACEHOLDERS[entityType]}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    if (isGrants) {
                      // Let Autocomplete select a highlighted suggestion first.
                      htmlInputSlot.onKeyDown?.(event);
                      if (event.defaultPrevented) {
                        return;
                      }
                      event.preventDefault();
                      event.stopPropagation();
                      openGrant(normalizedQuery);
                      return;
                    }
                    handleSearchKeyDown(event);
                    return;
                  }
                  htmlInputSlot.onKeyDown?.(event);
                }}
                inputProps={{
                  ...htmlInputSlot,
                  "aria-label": "Search",
                }}
                sx={{
                  fontSize: "1rem",
                  py: 0.5,
                  ml: 0.5,
                  mr: 1,
                }}
              />

              {initialLoading ? (
                <CircularProgress
                  color="inherit"
                  size={18}
                  sx={{ color: "text.secondary", mr: 0.5, flexShrink: 0 }}
                  aria-label="Searching"
                />
              ) : null}
            </Paper>
          );
        }}
      />

      {showAuthorFilters ? (
        <AuthorFilters
          institution={institutionFilter}
          topic={topicFilter}
          onInstitutionChange={handleInstitutionChange}
          onTopicChange={handleTopicChange}
        />
      ) : null}

      {showAuthorFilters && resultsAreStale && hasSearched ? (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: "block", mt: 0.75, ml: 0.25 }}
        >
          {FILTERS_STALE_MESSAGE}
        </Typography>
      ) : null}

      {validationMessage ? (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: "block", mt: 0.75, ml: 0.25 }}
          role="status"
        >
          {validationMessage}
        </Typography>
      ) : null}

      {error ? (
        <Alert
          severity="error"
          sx={{
            mt: 1.25,
            py: 0,
            borderRadius: 2,
            alignItems: "center",
          }}
          role="alert"
        >
          {error}
        </Alert>
      ) : null}
    </Box>
  );
}

export default AuthorSearch;
