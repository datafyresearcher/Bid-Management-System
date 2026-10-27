/**
 * A small in-memory cache for fetched data, so moving between tabs shows the
 * last content instantly and revalidates in the background instead of
 * collapsing to a loading screen every time.
 *
 * It lives only for the lifetime of the page (a hard refresh or sign-out
 * clears it), so nothing survives between users on a shared machine.
 */
const store = new Map();

export function cacheGet(key) {
  return store.get(key);
}

export function cacheSet(key, value) {
  store.set(key, value);
  return value;
}

export function cacheClear() {
  store.clear();
}
