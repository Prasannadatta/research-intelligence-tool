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
  CircularProgress,
  Popover,
  Typography,
} from "@mui/material";

import {
  fetchAuthorSummary,
  getAuthorLookupKey,
  getAuthorSummaryCacheKey,
  getCachedAuthorSummary,
} from "./authorSummaryCache";

const OPEN_DELAY_MS = 250;
const CLOSE_DELAY_MS = 250;

const AuthorInfoPopoverContext = createContext(null);

function cleanText(value) {
  if (value == null) {
    return null;
  }
  const text = String(value).replace(/\s+/g, " ").trim();
  return text || null;
}

function normalizeComparableText(value) {
  return cleanText(value)?.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim() || "";
}

function buildPublicationInstitution(author) {
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

function getCurrentInstitution(summary) {
  const institutions = Array.isArray(summary?.institutions) ? summary.institutions : [];
  return institutions.find((row) => row?.current) || institutions[0] || null;
}

function formatProvider(value) {
  const text = cleanText(value);
  if (!text) {
    return null;
  }
  const labels = {
    openalex: "OpenAlex",
    arxiv: "arXiv",
  };
  return labels[text.toLowerCase()] || text;
}

function providerFromAuthor(author) {
  if (!author || typeof author !== "object") {
    return null;
  }
  if (author.provider) {
    return formatProvider(author.provider);
  }
  if (author.providerIds?.openalex?.length > 0) {
    return "OpenAlex";
  }
  if (author.providerIds?.arxiv?.length > 0) {
    return "arXiv";
  }
  return null;
}

function formatNumberValue(value) {
  if (value == null || value === "") {
    return "—";
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "—";
  }
  return numeric.toLocaleString();
}

function formatTextValue(value) {
  return cleanText(value) || "N/A";
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
      ? summary.providers.map(formatProvider).filter(Boolean).join(", ")
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

function AuthorSummaryContent({ summary, loading, error, activeAuthor }) {
  if (loading) {
    return (
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.25, py: 0.5 }}>
        <CircularProgress size={16} aria-hidden="true" />
        <Typography variant="body2" color="text.secondary">
          Loading author details…
        </Typography>
      </Box>
    );
  }

  if (error) {
    return (
      <Typography variant="body2" color="error">
        {error}
      </Typography>
    );
  }

  return <CompactAuthorSummary summary={summary} activeAuthor={activeAuthor} />;
}

function useAuthorInfoPopover() {
  return useContext(AuthorInfoPopoverContext);
}

export function AuthorInfoPopoverProvider({ children }) {
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

    const cached = getCachedAuthorSummary(author);
    if (cached) {
      setSummary(cached);
      setLoading(false);
      setError(null);
      return undefined;
    }

    setSummary(null);
    setLoading(true);
    setError(null);

    const controller = new AbortController();

    fetchAuthorSummary(author, { signal: controller.signal })
      .then((data) => {
        if (fetchAuthorKeyRef.current !== activeAuthorKey) {
          return;
        }
        setSummary(data);
        setLoading(false);
      })
      .catch((err) => {
        if (fetchAuthorKeyRef.current !== activeAuthorKey) {
          return;
        }
        if (err?.name === "CanceledError" || err?.code === "ERR_CANCELED") {
          return;
        }
        setError("Author information could not be loaded");
        setLoading(false);
      });

    return () => {
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
          unresolved={Boolean(activeAuthor?.unresolved)}
          activeAuthor={activeAuthor}
        />
      </Popover>
    </AuthorInfoPopoverContext.Provider>
  );
}

export function AuthorNameLink({ author, name }) {
  const popover = useAuthorInfoPopover();
  const navigate = useNavigate();
  const displayName = name || author?.name || "Unknown author";
  const href = author?.canonicalAuthorId ? `/authors/${author.canonicalAuthorId}` : null;
  const authorKey = getAuthorLookupKey(author);

  const handleClick = (event) => {
    if (!href) {
      return;
    }
    event.preventDefault();
    navigate(href);
  };

  return (
    <Box
      component="button"
      type="button"
      data-author-key={authorKey}
      className="author-name-interactive"
      aria-label={href ? `View profile for ${displayName}` : `Author details for ${displayName}`}
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
