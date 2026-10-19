const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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

export function daysTo(value) {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return Math.ceil((d.getTime() - Date.now()) / (1000 * 60 * 60 * 24));
}

export const GATE_LABELS = {
  1: "G1 Go/No-Go",
  2: "G2 Eligibility",
  3: "G3 Draft review",
  4: "G4 Final approval",
  5: "G5 Submission",
};

export const DECISIONS = {
  1: [
    ["GO", "Go"],
    ["NO_GO", "No-Go"],
  ],
  2: [
    ["CONFIRMED", "Confirm"],
    ["NOT_CONFIRMED", "Not confirmed"],
  ],
  3: [
    ["APPROVED", "Approve"],
    ["RETURNED", "Return"],
  ],
  4: [
    ["APPROVED", "Approve"],
    ["RETURNED", "Return"],
  ],
  5: [
    ["SUBMITTED", "Submitted"],
    ["BLOCKED", "Blocked"],
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
