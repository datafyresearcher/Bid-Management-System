"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, fmtDate, fmtMoney, stateClass } from "../../lib/api";

const STATES = [
  ["NORMALIZED,SCORED,SCREENED_OUT,AUTO_ARCHIVED", "All triage states"],
  ["NORMALIZED", "New (not scored)"],
  ["SCORED,GATE1", "Passed screening"],
  ["SCREENED_OUT", "Screened out"],
  ["AUTO_ARCHIVED", "Auto archived"],
];

export default function InboxPage() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [state, setState] = useState(STATES[0][0]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const load = useCallback(() => {
    const params = new URLSearchParams();
    if (state) params.set("state", state);
    if (q) params.set("q", q);
    api(`/api/opportunities?${params.toString()}`)
      .then((data) => {
        setItems(data.items);
        setTotal(data.total);
      })
      .catch((e) => setError(e.message));
  }, [state, q]);

  useEffect(() => {
    load();
  }, [load]);

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
        <button className="btn" onClick={load}>Refresh</button>
      </div>

      <p className="muted mb-14">{total} item(s)</p>

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
                <td>
                  <span className={`score-pill ${o.score_total >= 70 ? "score-good" : o.score_total >= 55 ? "score-mid" : "score-low"}`}>
                    {o.score_total !== null && o.score_total !== undefined ? Math.round(o.score_total) : "—"}
                  </span>
                </td>
                <td>
                  <Link href={`/opportunities/${o.id}`}>{o.title.slice(0, 90)}</Link>
                  <div className="muted">{o.buyer_name} {o.buyer_ref ? `· ${o.buyer_ref}` : ""}</div>
                  {o.hard_gate_result && !o.hard_gate_result.passed && o.hard_gate_result.failures && o.hard_gate_result.failures.length ? (
                    <div className="muted">Gate failed: {o.hard_gate_result.failures.map((f) => f.reason).join("; ")}</div>
                  ) : null}
                </td>
                <td>{o.category_internal}<div className="muted">{o.tender_type}</div></td>
                <td>{fmtMoney(o.estimated_value, o.currency)}<div className="muted">{o.value_band}</div></td>
                <td>{fmtDate(o.submission_deadline)}</td>
                <td><span className={stateClass(o.state)}>{o.state}</span></td>
                <td>
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
              <tr><td colSpan="7" className="muted">No opportunities match the filter.</td></tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </>
  );
}
