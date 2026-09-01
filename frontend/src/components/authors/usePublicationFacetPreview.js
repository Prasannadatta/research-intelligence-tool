import { useEffect, useMemo, useRef } from "react";

import {
  PUBLICATION_FILTER_DEBOUNCE_MS,
  publicationFiltersKey,
  toPublicationFiltersPayload,
} from "./publicationFilters";

function isAbortError(error) {
  return (
    error?.name === "AbortError" ||
    error?.name === "CanceledError" ||
    error?.code === "ERR_CANCELED"
  );
}

export default function usePublicationFacetPreview({
  enabled,
  requestKey,
  draftFilters,
  fetchFacets,
  onFacets,
  delayMs = PUBLICATION_FILTER_DEBOUNCE_MS,
}) {
  const sequenceRef = useRef(0);
  const filtersKey = useMemo(
    () => publicationFiltersKey(draftFilters),
    [draftFilters],
  );
  const filtersPayload = useMemo(
    () => toPublicationFiltersPayload(draftFilters),
    [draftFilters],
  );
  const stableRequestKey = `${requestKey || "none"}::${filtersKey}`;

  useEffect(() => {
    if (!enabled || !requestKey || typeof fetchFacets !== "function") {
      sequenceRef.current += 1;
      return undefined;
    }

    const sequence = ++sequenceRef.current;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const nextFacets = await fetchFacets({
          filters: filtersPayload,
          signal: controller.signal,
        });
        if (sequenceRef.current === sequence) {
          onFacets(nextFacets);
        }
      } catch (error) {
        if (!isAbortError(error)) {
          // Keep the last known facet set; main Apply still owns visible data errors.
        }
      }
    }, delayMs);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [
    delayMs,
    enabled,
    fetchFacets,
    filtersPayload,
    onFacets,
    requestKey,
    stableRequestKey,
  ]);
}
