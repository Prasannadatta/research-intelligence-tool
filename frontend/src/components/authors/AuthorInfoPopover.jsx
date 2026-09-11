import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";
import {
  Box,
  Button,
  CircularProgress,
  Popover,
  Typography,
} from "@mui/material";

import {
  enrichAuthorSummary,
  fetchAuthorSummary,
  getAuthorLookupKey,
  getAuthorSummaryCacheKey,
  getCachedAuthorSummary,
} from "./authorSummaryCache";
import {
  buildPublicationInstitution,
  formatNumberValue,
  formatProviderLabel,
  formatTextValue,
  getCurrentInstitution,
} from "./authorSummaryDisplay";

const OPEN_DELAY_MS = 250;
const CLOSE_DELAY_MS = 250;

const AuthorInfoPopoverContext = createContext(null);

function normalizeComparableText(value) {
  return formatTextValue(value, "")
    ?.toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim() || "";
}

function providerFromAuthor(author) {
  if (!author || typeof author !== "object") {
    return null;
  }
  if (author.provider) {
    return formatProviderLabel(author.provider);
  }
  if (author.providerIds?.openalex?.length > 0) {
    return "OpenAlex";
  }
  if (author.providerIds?.arxiv?.length > 0) {
    return "arXiv";
  }
  return null;
}

function resolveCanonicalAuthorId(summary, activeAuthor) {
  const fromSummary = summary?.id ? String(summary.id).trim() : "";
  if (fromSummary) {
    return fromSummary;
  }
  const fromAuthor = activeAuthor?.canonicalAuthorId
    ? String(activeAuthor.canonicalAuthorId).trim()
    : "";
  return fromAuthor || null;
}

function DetailRow({ label, value, text = false }) {
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: "88px 1fr",
        columnGap: 1.25,
        alignItems: "baseline",
      }}
    >
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body2" color="text.primary" sx={{ minWidth: 0, overflowWrap: "anywhere" }}>
        {text ? formatTextValue(value) : formatNumberValue(value)}
      </Typography>
    </Box>
  );
}

function buildCompactSummary(summary, activeAuthor) {
  const publicationInstitution = buildPublicationInstitution(activeAuthor);
  const currentInstitution = getCurrentInstitution(summary);
  const primaryInstitution = publicationInstitution || currentInstitution;
  const provider =
    (Array.isArray(summary?.providers) && summary.providers.length > 0
      ? summary.providers.map(formatProviderLabel).filter(Boolean).join(", ")
      : null)
    || providerFromAuthor(activeAuthor);

  const publicationName = normalizeComparableText(publicationInstitution?.name);
  const currentName = normalizeComparableText(currentInstitution?.name);
  const showCurrentInstitution = Boolean(
    publicationInstitution
      && currentInstitution?.name
      && publicationName
      && currentName
      && publicationName !== currentName,
  );

  return {
    displayName: formatTextValue(summary?.display_name || activeAuthor?.name),
    institution: formatTextValue(primaryInstitution?.name),
    department: formatTextValue(primaryInstitution?.department),
    country: formatTextValue(primaryInstitution?.country_code),
    currentInstitution: showCurrentInstitution ? currentInstitution.name : null,
    worksCount: summary?.works_count,
    citationCount: summary?.citation_count,
    hIndex: summary?.h_index,
    orcid: summary?.orcid || activeAuthor?.orcid,
    provider,
  };
}

function CompactAuthorSummary({ summary, activeAuthor }) {
  const details = buildCompactSummary(summary, activeAuthor);

  return (
    <Box sx={{ display: "grid", gap: 0.25 }}>
      <DetailRow label="Author" value={details.displayName} text />
      <DetailRow label="Institution" value={details.institution} text />
      <DetailRow label="Department" value={details.department} text />
      <DetailRow label="Country" value={details.country} text />
      {details.currentInstitution ? (
        <DetailRow label="Current" value={details.currentInstitution} text />
      ) : null}
      <DetailRow label="Works" value={details.worksCount} />
      <DetailRow label="Citations" value={details.citationCount} />
      <DetailRow label="h-index" value={details.hIndex} />
      <DetailRow label="ORCID" value={details.orcid} text />
      <DetailRow label="Source" value={details.provider} text />
    </Box>
  );
}

function AuthorSummaryContent({
  summary,
  loading,
  error,
  activeAuthor,
  onViewDetails,
}) {
  const canonicalAuthorId = resolveCanonicalAuthorId(summary, activeAuthor);
  const showViewDetails = Boolean(canonicalAuthorId && onViewDetails);

  let body = null;
  if (loading) {
    body = (
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.25, py: 0.5 }}>
        <CircularProgress size={16} aria-hidden="true" />
        <Typography variant="body2" color="text.secondary">
          Loading author details…
        </Typography>
      </Box>
    );
  } else if (error) {
    body = (
      <Typography variant="body2" color="error">
        {error}
      </Typography>
    );
  } else {
    body = <CompactAuthorSummary summary={summary} activeAuthor={activeAuthor} />;
  }

  return (
    <Box sx={{ display: "grid", gap: 1 }}>
      {body}
      {showViewDetails ? (
        <Box sx={{ display: "flex", justifyContent: "flex-end", pt: 0.25 }}>
          <Button
            size="small"
            variant="text"
            onClick={() => onViewDetails(canonicalAuthorId)}
            aria-label="View details"
            sx={{
              minWidth: 0,
              px: 0.75,
              py: 0.25,
              textTransform: "none",
              fontWeight: 600,
              lineHeight: 1.3,
            }}
          >
            View details
          </Button>
        </Box>
      ) : null}
    </Box>
  );
}

function useAuthorInfoPopover() {
  return useContext(AuthorInfoPopoverContext);
}

export function AuthorInfoPopoverProvider({ children }) {
  const navigate = useNavigate();
  const [anchorEl, setAnchorEl] = useState(null);
  const [activeAuthorKey, setActiveAuthorKey] = useState(null);
  const [activeAuthor, setActiveAuthor] = useState(null);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const triggerHoveredRef = useRef(false);
  const popoverHoveredRef = useRef(false);
  const triggerFocusedRef = useRef(false);
  const openTimerRef = useRef(null);
  const closeTimerRef = useRef(null);
  const activeAuthorRef = useRef(null);
  const popoverPaperRef = useRef(null);
  const fetchAuthorKeyRef = useRef(null);
  const anchorElRef = useRef(null);

  const open = Boolean(anchorEl && activeAuthorKey);

  const clearOpenTimer = useCallback(() => {
    if (openTimerRef.current) {
      clearTimeout(openTimerRef.current);
      openTimerRef.current = null;
    }
  }, []);

  const clearCloseTimer = useCallback(() => {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  }, []);

  const resetOpenState = useCallback(() => {
    setAnchorEl(null);
    setActiveAuthorKey(null);
    setActiveAuthor(null);
    activeAuthorRef.current = null;
    anchorElRef.current = null;
  }, []);

  const closeImmediately = useCallback(() => {
    clearOpenTimer();
    clearCloseTimer();
    triggerHoveredRef.current = false;
    popoverHoveredRef.current = false;
    triggerFocusedRef.current = false;
    resetOpenState();
  }, [clearCloseTimer, clearOpenTimer, resetOpenState]);

  const scheduleClose = useCallback(() => {
    clearCloseTimer();
    closeTimerRef.current = setTimeout(() => {
      closeTimerRef.current = null;
      if (
        triggerHoveredRef.current
        || popoverHoveredRef.current
        || triggerFocusedRef.current
      ) {
        return;
      }
      resetOpenState();
    }, CLOSE_DELAY_MS);
  }, [clearCloseTimer, resetOpenState]);

  const openPopoverNow = useCallback((anchorNode, author, authorKey) => {
    if (!anchorNode || !author || !authorKey) {
      return;
    }

    activeAuthorRef.current = author;
    anchorElRef.current = anchorNode;
    setAnchorEl(anchorNode);
    setActiveAuthorKey(authorKey);
    setActiveAuthor(author);
  }, []);

  const handleAuthorMouseEnter = useCallback((event, author) => {
    const anchorNode = event.currentTarget;
    const authorKey = getAuthorLookupKey(author);

    triggerHoveredRef.current = true;
    clearCloseTimer();

    clearOpenTimer();
    openTimerRef.current = setTimeout(() => {
      openTimerRef.current = null;
      if (!triggerHoveredRef.current) {
        return;
      }
      openPopoverNow(anchorNode, author, authorKey);
    }, OPEN_DELAY_MS);
  }, [clearCloseTimer, clearOpenTimer, openPopoverNow]);

  const handleAuthorMouseLeave = useCallback(() => {
    triggerHoveredRef.current = false;
    clearOpenTimer();
    scheduleClose();
  }, [clearOpenTimer, scheduleClose]);

  const handleAuthorFocus = useCallback((event, author) => {
    const anchorNode = event.currentTarget;
    const authorKey = getAuthorLookupKey(author);

    clearCloseTimer();
    clearOpenTimer();
    triggerFocusedRef.current = true;
    openPopoverNow(anchorNode, author, authorKey);
  }, [clearCloseTimer, clearOpenTimer, openPopoverNow]);

  const handleAuthorBlur = useCallback((event) => {
    const relatedTarget = event.relatedTarget;
    if (
      relatedTarget
      && popoverPaperRef.current
      && popoverPaperRef.current.contains(relatedTarget)
    ) {
      return;
    }
    triggerFocusedRef.current = false;
    scheduleClose();
  }, [scheduleClose]);

  const handlePopoverMouseEnter = useCallback(() => {
    popoverHoveredRef.current = true;
    clearCloseTimer();
  }, [clearCloseTimer]);

  const handlePopoverMouseLeave = useCallback(() => {
    popoverHoveredRef.current = false;
    scheduleClose();
  }, [scheduleClose]);

  const handlePopoverFocusCapture = useCallback(() => {
    popoverHoveredRef.current = true;
    clearCloseTimer();
  }, [clearCloseTimer]);

  const handlePopoverBlurCapture = useCallback((event) => {
    if (event.currentTarget.contains(event.relatedTarget)) {
      return;
    }
    popoverHoveredRef.current = false;
    scheduleClose();
  }, [scheduleClose]);

  const handleViewDetails = useCallback((canonicalAuthorId) => {
    const id = String(canonicalAuthorId || "").trim();
    if (!id) {
      return;
    }
    closeImmediately();
    navigate(`/authors/${id}`);
  }, [closeImmediately, navigate]);

  useEffect(() => {
    if (!open || !activeAuthorKey || !anchorElRef.current) {
      return;
    }
    if (anchorElRef.current.isConnected) {
      return;
    }

    const escaped = typeof CSS !== "undefined" && CSS.escape
      ? CSS.escape(activeAuthorKey)
      : activeAuthorKey.replace(/"/g, '\\"');
    const replacement = document.querySelector(`[data-author-key="${escaped}"]`);
    if (
      replacement
      && replacement !== anchorElRef.current
      && replacement.isConnected
    ) {
      anchorElRef.current = replacement;
      setAnchorEl(replacement);
    }
  }, [open, activeAuthorKey]);

  useEffect(() => {
    if (!activeAuthorKey) {
      return undefined;
    }

    const author = activeAuthorRef.current;
    if (!author) {
      return undefined;
    }

    fetchAuthorKeyRef.current = activeAuthorKey;

    const cacheKey = getAuthorSummaryCacheKey(author);
    if (!cacheKey) {
      if (import.meta.env.DEV) {
        console.warn("[AuthorInfoPopover] Author has no usable ID:", author);
      }
      setSummary(null);
      setLoading(false);
      setError(null);
      return undefined;
    }

    let cancelled = false;
    const authorKeyAtStart = activeAuthorKey;

    const applySummary = (data) => {
      if (cancelled || fetchAuthorKeyRef.current !== authorKeyAtStart) {
        return;
      }
      setSummary(data);
      setLoading(false);
      setError(null);
    };

    const maybeEnrich = (data) => {
      if (!data?.enrichment?.pending?.length) {
        return;
      }
      // Do not abort enrichment on hover leave — warms cache for the next open.
      enrichAuthorSummary(author, { summary: data }).then((enriched) => {
        if (!enriched || cancelled || fetchAuthorKeyRef.current !== authorKeyAtStart) {
          return;
        }
        setSummary(enriched);
      });
    };

    const cached = getCachedAuthorSummary(author);
    if (cached) {
      applySummary(cached);
      maybeEnrich(cached);
      return () => {
        cancelled = true;
      };
    }

    setSummary(null);
    setLoading(true);
    setError(null);

    const controller = new AbortController();

    fetchAuthorSummary(author, { signal: controller.signal })
      .then((data) => {
        applySummary(data);
        maybeEnrich(data);
      })
      .catch((err) => {
        if (cancelled || fetchAuthorKeyRef.current !== authorKeyAtStart) {
          return;
        }
        if (err?.name === "CanceledError" || err?.code === "ERR_CANCELED") {
          return;
        }
        setError("Author information could not be loaded");
        setLoading(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [activeAuthorKey]);

  useEffect(() => () => closeImmediately(), [closeImmediately]);

  const contextValue = useMemo(
    () => ({
      handleAuthorMouseEnter,
      handleAuthorMouseLeave,
      handleAuthorFocus,
      handleAuthorBlur,
    }),
    [handleAuthorBlur, handleAuthorFocus, handleAuthorMouseEnter, handleAuthorMouseLeave],
  );

  return (
    <AuthorInfoPopoverContext.Provider value={contextValue}>
      {children}
      <Popover
        open={open}
        anchorEl={anchorEl}
        onClose={closeImmediately}
        disableRestoreFocus
        disableAutoFocus
        disableEnforceFocus
        hideBackdrop
        transitionDuration={0}
        anchorOrigin={{ vertical: "bottom", horizontal: "left" }}
        transformOrigin={{ vertical: "top", horizontal: "left" }}
        slotProps={{
          root: {
            sx: {
              pointerEvents: "none",
            },
          },
          paper: {
            ref: popoverPaperRef,
            tabIndex: -1,
            onMouseEnter: handlePopoverMouseEnter,
            onMouseLeave: handlePopoverMouseLeave,
            onFocusCapture: handlePopoverFocusCapture,
            onBlurCapture: handlePopoverBlurCapture,
            sx: {
              p: 1.5,
              maxWidth: 360,
              pointerEvents: "auto",
              zIndex: (theme) => theme.zIndex.tooltip,
              border: "1px solid",
              borderColor: "divider",
              boxShadow: (theme) => theme.shadows[3],
            },
          },
        }}
      >
        <AuthorSummaryContent
          summary={summary}
          loading={loading}
          error={error}
          activeAuthor={activeAuthor}
          onViewDetails={handleViewDetails}
        />
      </Popover>
    </AuthorInfoPopoverContext.Provider>
  );
}

export function AuthorNameLink({ author, name }) {
  const popover = useAuthorInfoPopover();
  const displayName = name || author?.name || "Unknown author";
  const authorKey = getAuthorLookupKey(author);

  const handleClick = (event) => {
    // Names no longer navigate; click only opens the hover card immediately.
    event.preventDefault();
    popover?.handleAuthorFocus?.(event, author);
  };

  return (
    <Box
      component="button"
      type="button"
      data-author-key={authorKey}
      className="author-name-interactive"
      aria-label={`Author details for ${displayName}`}
      onMouseEnter={(event) => popover?.handleAuthorMouseEnter(event, author)}
      onMouseLeave={() => popover?.handleAuthorMouseLeave()}
      onFocus={(event) => popover?.handleAuthorFocus(event, author)}
      onBlur={(event) => popover?.handleAuthorBlur(event)}
      onClick={handleClick}
      sx={{
        display: "inline",
        p: 0,
        m: 0,
        border: 0,
        background: "none",
        color: "inherit",
        font: "inherit",
        fontWeight: 500,
        lineHeight: "inherit",
        cursor: "pointer",
        textAlign: "left",
        userSelect: "none",
        WebkitUserSelect: "none",
        textDecoration: "none",
        "&:hover": {
          textDecoration: "underline",
          textUnderlineOffset: "2px",
        },
        "&:focus-visible": {
          outline: "2px solid",
          outlineColor: "primary.main",
          outlineOffset: 2,
          borderRadius: "2px",
        },
      }}
    >
      {displayName}
    </Box>
  );
}

export default AuthorInfoPopoverProvider;
