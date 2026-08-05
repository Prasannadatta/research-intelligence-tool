/** Session-scoped cache for author publication analysis pages. */
export const publicationsPageCache = new Map();

export function clearPublicationsPageCache() {
  publicationsPageCache.clear();
}
