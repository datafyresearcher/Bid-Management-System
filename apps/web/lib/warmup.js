import { api, cacheGet, cacheSet } from "./api";

/**
 * Warm the session cache with every tab's default view.
 *
 * Without this, a user's first click on each tab pays the API's full
 * response time behind a loading screen. Firing these reads in the
 * background right after sign-in means the data is usually already in the
 * cache when the tab is opened — the click renders instantly and the page's
 * own revalidation keeps it fresh.
 *
 * The URLs below must build the exact same strings the pages use as cache
 * keys (same URLSearchParams code, same order), or the warm entries would
 * never be read. Keep in sync with:
 *   app/inbox/page.js · app/pipeline/page.js · app/review/page.js ·
 *   app/leads/page.js · app/kb/page.js · app/admin/page.js
 */
function defaultUrls(role) {
  const inbox = new URLSearchParams({ page: "1", page_size: "50" });

  const pipelineState =
    "GATE1,GATE2,GATE3,GATE4,GATE5,DOCS_FETCHED,ANALYZED,DRAFTING,ASSEMBLY,READY_TO_SUBMIT,SUBMITTED,EVALUATION";
  const pipeline = new URLSearchParams({ page: "1", page_size: "100", sort: "deadline" });
  pipeline.set("state", pipelineState);

  const review = new URLSearchParams({ status: "PENDING,OVERDUE", limit: "50", offset: "0" });
  const reviewCount = new URLSearchParams({ status: "PENDING,OVERDUE" });

  const urls = [
    `/api/opportunities?${inbox.toString()}`, // Tender Inbox
    `/api/opportunities?${pipeline.toString()}`, // Bid Pipeline
    `/api/gates?${review.toString()}`, // Review Queue
    `/api/gates/count?${reviewCount.toString()}`,
    `/api/leads?${new URLSearchParams().toString()}`, // Leads Radar
    "/api/kb/company", // Knowledge Base opens on the Company tab
  ];
  if (role === "admin") {
    urls.push(
      "/api/admin/users",
      "/api/admin/category-mappings",
      "/api/admin/ai-quality",
      "/api/admin/audit?limit=150"
    );
  }
  return urls;
}

let warmed = false;

export function warmCache(role) {
  if (warmed) return;
  warmed = true;
  for (const url of defaultUrls(role)) {
    // A tab the user has already opened has fresher data than a re-read
    // would produce; skip those and warm only the untouched ones.
    if (cacheGet(url)) continue;
    api(url)
      .then((data) => cacheSet(url, data))
      .catch(() => {
        // A failed warm-up costs nothing: the tab fetches for itself when
        // its cache is empty, exactly as before.
      });
  }
}
