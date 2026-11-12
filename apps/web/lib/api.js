import { cacheClear } from "./cache";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Pages read and fill the session cache through this module, so the fetch
// helper and its cache travel together.
export { cacheGet, cacheSet } from "./cache";

export function getToken() {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("bms_token");
}

export function getUser() {
  if (typeof window === "undefined") return null;
  try {
    return JSON.parse(window.localStorage.getItem("bms_user") || "null");
  } catch {
    return null;
  }
}

export function setSession(token, user) {
  window.localStorage.setItem("bms_token", token);
  window.localStorage.setItem("bms_user", JSON.stringify(user));
}

export function clearSession() {
  window.localStorage.removeItem("bms_token");
  window.localStorage.removeItem("bms_user");
  // Cached page data belongs to the signed-in user; drop it so the next
  // sign-in on this browser starts clean.
  cacheClear();
}

export async function api(path, options = {}) {
  const token = getToken();
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const resp = await fetch(API + path, { ...options, headers });
  if (resp.status === 401) {
    clearSession();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    throw new Error("Unauthorized");
  }
  const text = await resp.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!resp.ok) {
    const detail = data && data.detail ? data.detail : resp.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

export function fmtMoney(value, currency = "PKR") {
  if (value === null || value === undefined || value === "") return "—";
  const num = Number(value);
  if (Number.isNaN(num)) return "—";
  return `${currency} ${num.toLocaleString("en-PK", { maximumFractionDigits: 0 })}`;
}

export function fmtDate(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export function fmtDateTime(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return `${d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" })} ${d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`;
}

/**
 * The bare host of a URL.
 *
 * Source links point at government portals, and the host is the part that
 * tells a reader whether the link really goes to the authority that
 * publishes the tender — the path and query are noise at a glance.
 */
export function urlHost(url) {
  if (!url) return "";
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/**
 * Host plus path.
 *
 * A portal home page and the listing page inside it share a domain, so the
 * host alone makes two different destinations look identical. Keeping the
 * path shows which page on the authority's site the link actually opens.
 */
export function urlHostPath(url) {
  if (!url) return "";
  try {
    const u = new URL(url);
    return `${u.host}${u.pathname === "/" ? "" : u.pathname}`;
  } catch {
    return url;
  }
}

export function daysTo(value) {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return Math.ceil((d.getTime() - Date.now()) / (1000 * 60 * 60 * 24));
}

/**
 * The real tender closing date, with a countdown and an urgency class.
 *
 * This is deliberately separate from the gate SLA. The SLA is an internal
 * review deadline we set; the tender deadline is the date the buyer closes
 * the bid. They are different clocks, and conflating them is how a bid
 * manager misses a close date.
 */
export function deadlineInfo(deadline) {
  if (!deadline) return { label: "—", days: null, countdown: "no date", className: "", urgent: false };
  const d = new Date(deadline);
  if (Number.isNaN(d.getTime())) return { label: "—", days: null, countdown: "no date", className: "", urgent: false };
  const days = daysTo(deadline);
  let className = "";
  let urgent = false;
  if (days < 0) {
    className = "score-low";
    urgent = true;
  } else if (days <= 7) {
    className = "score-low";
    urgent = true;
  } else if (days <= 21) {
    className = "score-mid";
  }
  return {
    label: fmtDate(deadline),
    days,
    countdown: days < 0 ? "closed" : `${days}d left`,
    className,
    urgent,
  };
}

/**
 * The review SLA countdown.
 *
 * Gate SLAs are measured in hours, so a day-granularity counter is not
 * enough: a gate 15 hours overdue is not "0d left". Anything inside 24 hours
 * is reported in hours, and anything past its due time is reported as
 * overdue rather than as a zero.
 */
export function slaCountdown(dueAt) {
  if (!dueAt) return "—";
  const due = new Date(dueAt);
  if (Number.isNaN(due.getTime())) return "—";
  const ms = due.getTime() - Date.now();
  const hours = Math.ceil(ms / (1000 * 60 * 60));
  if (hours < 0) {
    const overdue = Math.abs(hours);
    return overdue < 24 ? `${overdue}h overdue` : `${Math.ceil(overdue / 24)}d overdue`;
  }
  if (hours < 24) return `${hours}h left`;
  return `${Math.ceil(hours / 24)}d left`;
}

/** True when a review SLA has already expired. */
export function slaIsOverdue(dueAt) {
  if (!dueAt) return false;
  const due = new Date(dueAt);
  if (Number.isNaN(due.getTime())) return false;
  return due.getTime() < Date.now();
}

/* ------------------------------------------------------------------
 * Wording
 *
 * The bid team reads these pages, not the engineers who built them. The
 * words on screen are theirs: a "gate" is a stage a bid moves through, and
 * an "AI rationale" is an assessment of how well the tender fits us.
 * ------------------------------------------------------------------ */

/**
 * The five stages a bid moves through.
 *
 * The stage is where a person decides whether the bid goes on. The number
 * is kept because the stages are always referred to in order.
 */
export const STAGE_LABELS = {
  1: "Stage 1 — Go / No-Go",
  2: "Stage 2 — Eligibility check",
  3: "Stage 3 — Draft review",
  4: "Stage 4 — Final approval",
  5: "Stage 5 — Submission",
};

/** The stage name on its own, without the number. */
export const STAGE_NAMES = {
  1: "Go / No-Go",
  2: "Eligibility check",
  3: "Draft review",
  4: "Final approval",
  5: "Submission",
};

/**
 * What each workflow state means to the reader.
 *
 * The states are the system's internal vocabulary; these are the words the
 * bid team reads.
 */
export const STATE_LABELS = {
  NEW: "New",
  NORMALIZED: "Waiting to be reviewed",
  SCORED: "Scored",
  SCREENED_OUT: "Screened out",
  AUTO_ARCHIVED: "Archived automatically",
  GATE1: "Stage 1 — Go / No-Go",
  GATE2: "Stage 2 — Eligibility check",
  GATE3: "Stage 3 — Draft review",
  GATE4: "Stage 4 — Final approval",
  GATE5: "Stage 5 — Submission",
  DOCS_FETCHED: "Fetching the tender documents",
  ANALYZED: "Document analysis complete",
  DRAFTING: "Drafting the proposal",
  ASSEMBLY: "Assembling the submission pack",
  READY_TO_SUBMIT: "Ready to submit",
  SUBMITTED: "Submitted",
  EVALUATION: "Under evaluation",
  WON: "Won",
  LOST: "Lost",
  REJECTED: "Rejected",
  ABANDONED: "Abandoned",
};

/** The reader-facing name of a workflow state. */
export function stateLabel(state) {
  if (!state) return "—";
  return STATE_LABELS[state] || state;
}

/**
 * The three states a submission checklist item can be in.
 */
export const CHECKLIST_STATUSES = [
  ["pending", "Pending"],
  ["complete", "Complete"],
  ["not_applicable", "Not applicable"],
];

/** The reader-facing name of a checklist status. */
export function checklistStatusLabel(status) {
  const found = CHECKLIST_STATUSES.find(([value]) => value === status);
  return found ? found[1] : "Pending";
}

/** What the related document is called, in the reader's words. */
export const RELATED_KIND_LABELS = {
  clarification: "Clarification",
  amendment: "Amendment",
  corrigendum: "Corrigendum",
  evaluation: "Evaluation result",
  notice: "Tender notice",
  related: "Related document",
};

export const DECISIONS = {
  1: [
    ["GO", "Go — pursue this tender"],
    ["NO_GO", "No-Go — do not pursue"],
  ],
  2: [
    ["CONFIRMED", "Confirm — we are eligible"],
    ["NOT_CONFIRMED", "Not confirmed — we are not eligible"],
  ],
  3: [
    ["APPROVED", "Approve the draft"],
    ["RETURNED", "Return for changes"],
  ],
  4: [
    ["APPROVED", "Approve for submission"],
    ["RETURNED", "Return for changes"],
  ],
  5: [
    ["SUBMITTED", "Submitted"],
    ["BLOCKED", "Blocked — not submitted"],
  ],
};

export function stateClass(state) {
  if (!state) return "badge";
  if (["WON"].includes(state)) return "badge badge-green";
  if (["LOST", "REJECTED", "ABANDONED", "SCREENED_OUT", "AUTO_ARCHIVED"].includes(state)) return "badge badge-gray";
  if (["GATE1", "GATE2", "GATE3", "GATE4", "GATE5"].includes(state)) return "badge badge-amber";
  if (["SUBMITTED", "EVALUATION"].includes(state)) return "badge badge-blue";
  return "badge badge-blue";
}

export function severityClass(severity) {
  if (severity === "High") return "badge badge-red";
  if (severity === "Medium") return "badge badge-amber";
  return "badge badge-gray";
}
