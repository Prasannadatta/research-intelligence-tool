import { ENTITY_TYPES } from "../api/searchApi";

export const ENTITY_QUERY_PARAM = "entity";

export const SEARCH_HOME_PATH = "/";

const VALID_ENTITIES = new Set([
  ENTITY_TYPES.AUTHORS,
  ENTITY_TYPES.GRANTS,
  ENTITY_TYPES.WORKS,
]);

export function parseEntityParam(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (VALID_ENTITIES.has(normalized)) {
    return normalized;
  }
  return ENTITY_TYPES.AUTHORS;
}

export function isSearchHomePath(pathname) {
  return pathname === SEARCH_HOME_PATH || pathname === "/search";
}

export function buildSearchHomePath(entity) {
  const parsed = parseEntityParam(entity);
  return `${SEARCH_HOME_PATH}?${ENTITY_QUERY_PARAM}=${parsed}`;
}

export function getActiveSearchMenuEntity(pathname, searchParams) {
  if (pathname.startsWith("/analyze/authors")) {
    return ENTITY_TYPES.AUTHORS;
  }
  if (pathname.startsWith("/grants/")) {
    return ENTITY_TYPES.GRANTS;
  }
  if (pathname.startsWith("/works/")) {
    return ENTITY_TYPES.WORKS;
  }
  if (isSearchHomePath(pathname)) {
    return parseEntityParam(searchParams?.get(ENTITY_QUERY_PARAM));
  }
  return null;
}

export function clearSelectionsForEntity(entity, setters) {
  const parsed = parseEntityParam(entity);
  if (parsed === ENTITY_TYPES.AUTHORS) {
    setters.setSelectedWorks([]);
  } else {
    setters.setSelectedAuthors([]);
  }
}
