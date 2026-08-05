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

function formatUpdatedAt(value) {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function formatInstitutionYears(years) {
  if (!years) {
    return null;
  }
  const from = years.from ?? years.from_;
  const to = years.to;
  if (from != null && to != null && from !== to) {
    return `${from}–${to}`;
  }
  if (from != null) {
    return String(from);
  }
  if (to != null) {
    return String(to);
  }
  return null;
}

function MetricRow({ label, value }) {
  if (value == null || value === "") {
    return null;
  }
  return (
    <Typography variant="body2" color="text.secondary">
      <Box component="span" sx={{ color: "text.primary", fontWeight: 500 }}>
        {label}:
      </Box>{" "}
      {typeof value === "number" ? value.toLocaleString() : value}
    </Typography>
  );
}

function AuthorSummaryContent({ summary, loading, error, unresolved }) {
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

  if (!summary) {
    return (
      <Box sx={{ display: "grid", gap: 0.5 }}>
        <Typography variant="body2" color="text.secondary">
          No additional author information available
        </Typography>
        {unresolved ? (
          <Typography variant="caption" color="text.secondary">
            Metadata matched experimentally from provider records.
          </Typography>
        ) : null}
      </Box>
    );
  }

  const institutions = Array.isArray(summary.institutions) ? summary.institutions : [];
  const currentInstitutions = institutions.filter((row) => row.current);
  const otherInstitutions = institutions.filter((row) => !row.current);
  const primaryInstitution = currentInstitutions[0] || institutions[0] || null;
  const aliases = (summary.aliases || []).filter(
    (alias) => alias && alias !== summary.display_name,
  );
  const topics = summary.topics || [];
  const providers = summary.providers || [];
  const updatedAt = formatUpdatedAt(summary.updated_at);

  const hasDetails =
    primaryInstitution ||
    otherInstitutions.length > 0 ||
    aliases.length > 0 ||
    topics.length > 0 ||
    summary.orcid ||
    summary.works_count != null ||
    summary.citation_count != null ||
    summary.h_index != null ||
    providers.length > 0;

  if (!hasDetails) {
    return (
      <Box sx={{ display: "grid", gap: 0.5 }}>
        <Typography variant="body2" color="text.secondary">
          No additional author information available
        </Typography>
        {summary.unresolved || unresolved ? (
          <Typography variant="caption" color="text.secondary">
            Metadata matched experimentally from provider records.
          </Typography>
        ) : null}
      </Box>
    );
  }

  return (
    <Box sx={{ display: "grid", gap: 0.75 }}>
      <Typography variant="subtitle2" fontWeight={600}>
        {summary.display_name}
      </Typography>

      {primaryInstitution ? (
        <Box>
          <Typography variant="body2" fontWeight={500}>
            {primaryInstitution.name}
          </Typography>
          {primaryInstitution.department ? (
            <Typography variant="body2" color="text.secondary">
              {primaryInstitution.department}
            </Typography>
          ) : null}
          {primaryInstitution.country_code ? (
            <Typography variant="caption" color="text.secondary">
              {primaryInstitution.country_code}
            </Typography>
          ) : null}
        </Box>
      ) : null}

      {otherInstitutions.length > 0 ? (
        <Box>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.25 }}>
            Also affiliated with:
          </Typography>
          {otherInstitutions.map((institution) => {
            const years = formatInstitutionYears(institution.years);
            return (
              <Typography key={`${institution.id || institution.name}-${years || "na"}`} variant="body2">
                {institution.name}
                {years ? (
                  <Typography component="span" variant="body2" color="text.secondary">
                    {" "}
                    · {years}
                  </Typography>
                ) : null}
              </Typography>
            );
          })}
        </Box>
      ) : null}

      {aliases.length > 0 ? (
        <Typography variant="body2" color="text.secondary">
          <Box component="span" sx={{ color: "text.primary", fontWeight: 500 }}>
            Aliases:
          </Box>{" "}
          {aliases.join(", ")}
        </Typography>
      ) : null}

      {topics.length > 0 ? (
        <Typography variant="body2" color="text.secondary">
          <Box component="span" sx={{ color: "text.primary", fontWeight: 500 }}>
            Topics:
          </Box>{" "}
          {topics.join(", ")}
        </Typography>
      ) : null}

      <MetricRow label="ORCID" value={summary.orcid} />
      <MetricRow label="Works" value={summary.works_count} />
      <MetricRow label="Citations" value={summary.citation_count} />
      <MetricRow label="h-index" value={summary.h_index} />

      {providers.length > 0 ? (
        <Typography variant="body2" color="text.secondary">
          <Box component="span" sx={{ color: "text.primary", fontWeight: 500 }}>
            Sources:
          </Box>{" "}
          {providers.join(", ")}
        </Typography>
      ) : null}

      {updatedAt ? (
        <Typography variant="caption" color="text.secondary">
          Updated {updatedAt}
        </Typography>
      ) : null}

      {summary.unresolved || unresolved ? (
        <Typography variant="caption" color="text.secondary">
          Metadata matched experimentally from provider records.
        </Typography>
      ) : null}
    </Box>
  );
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
