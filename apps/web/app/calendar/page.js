"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, cacheGet, cacheSet, daysTo, fmtMoney } from "../../lib/api";
import BrandLoader from "../../components/Loading";

/**
 * The tender schedule: a month at a glance.
 *
 * The bidding team asked for a visual overview of the tenders worth
 * pursuing — the ones scoring above 70 for AHTE — placed on the calendar
 * at the date each one closes, so the coming weeks' workload can be seen
 * rather than read off a list.
 *
 * The tenders shown are the active ones (still inside their submission
 * window, not screened out or decided) whose score clears the threshold.
 * A tender the portals published without a closing date cannot be placed
 * on any day — those carry the "No closing date on file" marker in the
 * Pipeline, and are counted below rather than silently dropped.
 */

// The states that make a tender one the team can still act on. A scored
// tender carries a score; unscored ones are excluded by the score filter.
const ACTIVE_STATES =
  "NEW,NORMALIZED,SCORED,GATE1,GATE2,GATE3,GATE4,GATE5,DOCS_FETCHED,ANALYZED,DRAFTING,ASSEMBLY,READY_TO_SUBMIT,SUBMITTED,EVALUATION";

const THRESHOLDS = [
  { value: "70", label: "Scoring above 70" },
  { value: "60", label: "Scoring above 60" },
  { value: "80", label: "Scoring above 80" },
  { value: "any", label: "All scored tenders" },
];

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function dateKey(value) {
  // The local calendar day a closing timestamp lands on. Grouping is done
  // in the reader's own timezone, so a tender closing at 00:30 UTC reads
  // on the day the team actually works it.
  const d = new Date(value);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export default function CalendarPage() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [threshold, setThreshold] = useState("70");
  const [view, setView] = useState(() => {
    // The month is held as the first of the month at noon — noon keeps the
    // month stable when a timezone shifts the date by a few hours.
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), 1, 12, 0, 0);
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const hydrated = useRef(false);

  const load = useCallback(() => {
    const params = new URLSearchParams({
      page: "1",
      page_size: "100",
      deadline: "open",
      sort: "deadline",
      state: ACTIVE_STATES,
    });
    if (threshold !== "any") params.set("min_score", threshold);
    const url = `/api/opportunities?${params.toString()}`;
    if (!hydrated.current) {
      const cached = cacheGet(url);
      if (cached) {
        setItems(cached.items || []);
        setTotal(cached.total || 0);
        setLoading(false);
      }
      hydrated.current = true;
    }
    api(url)
      .then((data) => {
        setItems(data.items || []);
        setTotal(data.total || 0);
        cacheSet(url, data);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [threshold]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !error) return <BrandLoader />;

  // Group the tenders by the local day they close on, keeping only the
  // days inside the month being viewed.
  const year = view.getFullYear();
  const month = view.getMonth();
  const monthStart = new Date(year, month, 1, 12, 0, 0);
  const monthEnd = new Date(year, month + 1, 0, 12, 0, 0);
  const inView = items.filter((o) => {
    if (!o.submission_deadline) return false;
    const d = new Date(o.submission_deadline);
    return d >= monthStart && d <= monthEnd;
  });
  const byDay = {};
  for (const o of inView) {
    const key = dateKey(o.submission_deadline);
    (byDay[key] = byDay[key] || []).push(o);
  }

  const firstWeekday = (monthStart.getDay() + 6) % 7; // Monday = 0
  const daysInMonth = monthEnd.getDate();
  const cells = [];
  for (let i = 0; i < firstWeekday; i += 1) cells.push(null);
  for (let day = 1; day <= daysInMonth; day += 1) cells.push(day);
  while (cells.length % 7 !== 0) cells.push(null);

  const today = new Date();
  const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  const shiftMonth = (delta) => {
    setView(new Date(year, month + delta, 1, 12, 0, 0));
  };

  const noDate = items.filter((o) => !o.submission_deadline).length;
  const monthLabel = `${MONTHS[month]} ${year}`;
  const scorePill = (score) =>
    `score-pill ${score >= 70 ? "score-good" : score >= 55 ? "score-mid" : "score-low"}`;

  return (
    <>
      <h2 className="page-title">Tender Schedule</h2>
      <p className="page-sub">
        The month at a glance — every active tender scoring above 70 for AHTE, on the
        day it closes. This is the workload ahead, not the archive.
      </p>

      {error ? <div className="notice err">{error}</div> : null}

      <div className="filters">
        <div>
          <label>Show</label>
          <select value={threshold} onChange={(e) => setThreshold(e.target.value)}>
            {THRESHOLDS.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </div>
        <div className="row-actions">
          <button className="btn" onClick={() => shiftMonth(-1)}>← Previous</button>
          <button className="btn" onClick={() => setView(new Date(today.getFullYear(), today.getMonth(), 1, 12, 0, 0))}>
            This month
          </button>
          <button className="btn" onClick={() => shiftMonth(1)}>Next →</button>
        </div>
        <span className="muted">
          {monthLabel} · {inView.length} tender(s) closing{threshold !== "any" ? `, ${items.length} above the threshold in total` : ""}
        </span>
        <button className="btn" onClick={load}>Refresh</button>
      </div>

      {noDate > 0 ? (
        <div className="notice info mb-14">
          {noDate} further tender(s) above the threshold are waiting on a closing date — the
          portals published none, so they cannot be placed on a calendar until the bidding
          document has been read. They carry the “No closing date on file” marker in the Pipeline.
        </div>
      ) : null}

      <div className="card">
        <div className="calendar-head">
          <strong>{monthLabel}</strong>
          <span className="muted">each entry links to its bid room</span>
        </div>
        <div className="calendar-grid">
          {WEEKDAYS.map((d) => (
            <div key={d} className="calendar-weekday">{d}</div>
          ))}
          {cells.map((day, index) => {
            if (day === null) return <div key={`e${index}`} className="calendar-day calendar-empty" />;
            const key = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
            const dayItems = byDay[key] || [];
            const isToday = key === todayKey;
            const isPast = new Date(year, month, day, 23, 59, 59) < today;
            return (
              <div key={key} className={`calendar-day${isToday ? " calendar-today" : ""}${isPast ? " calendar-past" : ""}`}>
                <div className="calendar-date">{day}</div>
                {dayItems.slice(0, 3).map((o) => (
                  <Link key={o.id} href={`/opportunities/${o.id}`} className="calendar-entry" title={o.title}>
                    <span className={scorePill(o.score_total || 0)}>{Math.round(o.score_total || 0)}</span>
                    <span className="calendar-title">{o.title.slice(0, 44)}</span>
                  </Link>
                ))}
                {dayItems.length > 3 ? (
                  <div className="calendar-more">+{dayItems.length - 3} more</div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>

      {total > 100 ? (
        <p className="muted mt-14">
          Showing the 100 soonest of {total} tenders above the threshold. Narrow the view with
          the score filter, or work from the Pipeline for the full list.
        </p>
      ) : null}

      {inView.length === 0 ? (
        <p className="muted mt-14">
          Nothing above the threshold closes in {monthLabel}. Move to another month, or lower
          the threshold — the Pipeline's "Awaiting a decision" view lists everything waiting.
        </p>
      ) : null}
    </>
  );
}
