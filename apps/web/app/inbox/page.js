"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, fmtDate, fmtMoney, stateClass } from "../../lib/api";
import SourceTag, { sourceLink, sourceName } from "../../components/SourceTag";
import { ListSkeleton } from "../../components/Loading";

const STATES = [
  ["", "Everything (every captured tender)"],
  ["GATE1", "Gate 1 open"],
  ["NORMALIZED,SCORED,SCREENED_OUT,AUTO_ARCHIVED", "All triage states"],
  ["NORMALIZED", "New (not scored)"],
  ["SCORED,GATE1", "Passed screening"],
  ["SCREENED_OUT", "Screened out"],
  ["AUTO_ARCHIVED", "Auto archived"],
];

/**
 * The tender title opens the notice on the portal it was published on.
 *
 * A bid manager reads the tender where the authority published it — that is
 * the document they are bidding on. The system keeps the reference number and
 * the notice link together so the original is always one click away, and the
 * internal bid room stays reachable from the Open button on the same row.
 */
function TenderTitle({ o }) {
  const href = sourceLink(o.source);
  const label = o.title.slice(0, 90);
  if (!href) {
    return <Link href={`/opportunities/${o.id}`}>{label}</Link>;
  }
  return (
    <a href={href} target="_blank" rel="noreferrer noopener" title={`Open on ${sourceName(o.source) || "the source portal"}`}>
      {label}
    </a>
  );
}

export default function InboxPage() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [state, setState] = useState(STATES[0][0]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  // True until the first fetch answers; the list then renders in place on
  // every later refresh instead of collapsing to a skeleton again.
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });
    if (state) params.set("state", state);
    if (q) params.set("q", q);
    api(`/api/opportunities?${params.toString()}`)
      .then((data) => {
        setItems(data.items);
        setTotal(data.total);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [state, q, page, pageSize]);

  // A new filter is a new view, so it starts at the first page.
  useEffect(() => {
    setPage(1);
  }, [state, q, pageSize]);

  useEffect(() => {
    load();
  }, [load]);

  const pages = Math.max(1, Math.ceil(total / pageSize));
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);

  const score = async (id) => {
    setBusy(true);
    setError("");
    setInfo("");
    try {
      const res = await api(`/api/opportunities/${id}/score`, { method: "POST" });
      setInfo(`Scored ${Math.round(res.score_total)} → ${res.state}`);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const override = async (id) => {
    const comment = window.prompt("Override reason (recorded in audit):");
    if (!comment) return;
    setBusy(true);
    try {
      await api(`/api/opportunities/${id}/override`, { method: "POST", body: JSON.stringify({ comment }) });
      setInfo("Override recorded — Gate 1 opened");
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const scoreAll = async () => {
    setBusy(true);
    setError("");
    setInfo("");
    try {
      const res = await api("/api/opportunities/score-pending", { method: "POST" });
      setInfo(
        res.scored
          ? `Scored ${res.scored} waiting tender(s) — the ones that cleared screening are now in the review queue.`
          : "Nothing was waiting for a score."
      );
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (loading && !error) {
    return (
      <ListSkeleton
        title="Tender Inbox"
        sub="Raw and screened tenders from all sources. Score new items or override screening decisions."
      />
    );
  }

  return (
    <>
      <h2 className="page-title">Tender Inbox</h2>
      <p className="page-sub">Raw and screened tenders from all sources. Score new items or override screening decisions.</p>

      {error ? <div className="notice err">{error}</div> : null}
      {info ? <div className="notice ok">{info}</div> : null}

      <div className="filters">
        <div className="grow">
          <label>Search (title, buyer, reference)</label>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. 132kV grid station" />
        </div>
        <div>
          <label>State</label>
          <select value={state} onChange={(e) => setState(e.target.value)}>
            {STATES.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </div>
        <div>
          <label>Per page</label>
          <select value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))}>
            {[25, 50, 100].map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </div>
        <button className="btn" onClick={load}>Refresh</button>
        <button className="btn primary" disabled={busy} onClick={scoreAll}>Score all waiting</button>
      </div>

      {total > 0 ? (
        <div className="pager">
          <p className="muted mb-14">Showing {first}–{last} of {total} tender(s).</p>
          <div className="row-actions">
            <button className="btn" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
              ← Previous
            </button>
            <span className="muted">
              Page {page} of {pages}
            </span>
            <button className="btn" disabled={page >= pages} onClick={() => setPage((p) => Math.min(pages, p + 1))}>
              Next →
            </button>
            {page < pages ? (
              <button className="btn" onClick={() => setPage(pages)}>
                Last page
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Score</th>
              <th>Tender</th>
              <th>Category</th>
              <th>Value</th>
              <th>Deadline</th>
              <th>State</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((o) => (
              <tr key={o.id}>
                <td data-label="Score">
                  <span className={`score-pill ${o.score_total >= 70 ? "score-good" : o.score_total >= 55 ? "score-mid" : "score-low"}`}>
                    {o.score_total !== null && o.score_total !== undefined ? Math.round(o.score_total) : "—"}
                  </span>
                </td>
                <td data-label="Tender">
                  <TenderTitle o={o} />
                  <div className="muted">{o.buyer_name} {o.buyer_ref ? `· ${o.buyer_ref}` : ""}</div>
                  <SourceTag source={o.source} />
                  {o.hard_gate_result && !o.hard_gate_result.passed && o.hard_gate_result.failures && o.hard_gate_result.failures.length ? (
                    <div className="muted">Gate failed: {o.hard_gate_result.failures.map((f) => f.reason).join("; ")}</div>
                  ) : null}
                </td>
                <td data-label="Category">{o.category_internal}<div className="muted">{o.tender_type}</div></td>
                <td data-label="Value">{fmtMoney(o.estimated_value, o.currency)}<div className="muted">{o.value_band}</div></td>
                <td data-label="Deadline">{fmtDate(o.submission_deadline)}</td>
                <td data-label="State"><span className={stateClass(o.state)}>{o.state}</span></td>
                <td data-label="">
                  <div className="row-actions">
                    {o.state === "NORMALIZED" ? (
                      <button className="btn small primary" disabled={busy} onClick={() => score(o.id)}>Score</button>
                    ) : null}
                    {["SCREENED_OUT", "AUTO_ARCHIVED"].includes(o.state) ? (
                      <button className="btn small" disabled={busy} onClick={() => override(o.id)}>Override</button>
                    ) : null}
                    <Link className="btn small" href={`/opportunities/${o.id}`}>Open</Link>
                  </div>
                </td>
              </tr>
            ))}
            {items.length === 0 ? (
              <tr><td colSpan="7" data-label="" className="muted">No opportunities match the filter.</td></tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </>
  );
}
