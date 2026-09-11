/**
 * Convert a main Author Search hit into a saved-search author row.
 * Uses the same resolve-on-select path as the search home.
 */

import { toAnalysisAuthorPayload } from "../../api/analysisApi";
import { resolveAuthorSelection } from "../../api/authorResolveApi";
import {
  isAuthorAlreadySelected,
  selectedAuthorIdentityKeySet,
} from "../../api/authorSearchIdentity";

export async function savedSearchAuthorFromSearchHit(hit) {
  if (!hit || typeof hit !== "object") {
    return null;
  }
  let resolved = hit;
  try {
    resolved = await resolveAuthorSelection(hit);
  } catch {
    resolved = hit;
  }
  return toAnalysisAuthorPayload(resolved);
}

export function appendUniqueSavedSearchAuthor(authors, nextAuthor) {
  if (!nextAuthor?.canonical_author_id) {
    return authors;
  }
  const selectedKeys = selectedAuthorIdentityKeySet(authors);
  if (isAuthorAlreadySelected(nextAuthor, selectedKeys)) {
    return authors;
  }
  return [...authors, nextAuthor];
}

export function removeSavedSearchAuthor(authors, canonicalAuthorId) {
  const id = String(canonicalAuthorId || "").trim();
  if (!id) {
    return authors;
  }
  return (Array.isArray(authors) ? authors : []).filter(
    (author) => author.canonical_author_id !== id,
  );
}
