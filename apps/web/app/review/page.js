"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, DECISIONS, fmtDateTime, GATE_LABELS } from "../../lib/api";

export default function ReviewPage() {
  const [gates, setGates] = useState([]);
  const [status, setStatus] = useState("PENDING,OVERDUE");
  const [role, setRole] = useState("");
  const [comments, setComments] = useState({});
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    const params = new URLSearchParams({ status });
    if (role) params.set("role", role);
    api(`/api/gates?${params.toString()}`).then(setGates).catch((e) => setError(e.message));
  }, [status, role]);

  useEffect(() => {
    load();
  }, [load]);

  const decide = async (gate, decision) => {
    setBusy(true);
    setError("");
    setInfo("");
    try {
      await api(`/api/gates/${gate.id}/decide`, {
        method: "POST",
        body: JSON.stringify({ decision, comment: comments[gate.id] || "" }),
      });
      setInfo(`Gate ${gate.gate} decision recorded: ${decision}`);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h2 className="page-title">Review Queue</h2>
      <p className="page-sub">Every gate decision is recorded with actor, timestamp and comment in the audit trail.</p>

      {error ? <div className="notice err">{error}</div> : null}
      {info ? <div className="notice ok">{info}</div> : null}

      <div className="filters">
        <div>
          <label>Status</label>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="PENDING,OVERDUE">Open (pending + overdue)</option>
            <option value="OVERDUE">Overdue only</option>
            <option value="APPROVED">Approved</option>
            <option value="REJECTED">Rejected</option>
            <option value="CANCELLED">Cancelled</option>
            <option value="">All</option>
          </select>
        </div>
        <div>
          <label>Owner role</label>
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="">My role (auto)</option>
            <option value="bid_manager">Bid manager</option>
            <option value="proposal_engineer">Proposal engineer</option>
            <option value="management">Management</option>
          </select>
        </div>
        <button className="btn" onClick={load}>Refresh</button>
      </div>

      {gates.length === 0 ? <p className="muted">No gates in this view.</p> : null}

      {gates.map((g) => (
        <div className="card section-card" key={g.id}>
          <div className="section-title">
            <h3 style={{ textTransform: "none", fontSize: 14 }}>
              <span className={g.status === "OVERDUE" ? "badge badge-red" : "badge badge-amber"}>{GATE_LABELS[g.gate] || `G${g.gate}`}</span>{" "}
              {g.title}
            </h3>
            <span className={g.status === "OVERDUE" ? "badge badge-red" : "badge"}>{g.status}</span>
          </div>
          <p className="muted">
            Owner: {g.owner_role} · SLA {g.sla_hours}h · due {fmtDateTime(g.due_at)} ·{" "}
            {g.opportunity ? <Link href={`/opportunities/${g.opportunity_id}`}>{g.opportunity.title.slice(0, 90)} ({g.opportunity.buyer_name})</Link> : `opportunity #${g.opportunity_id}`}
          </p>

          {["PENDING", "OVERDUE"].includes(g.status) ? (
            <>
              {g.inputs_snapshot && Object.keys(g.inputs_snapshot).length ? (
                <details>
                  <summary className="muted">Gate inputs</summary>
                  <pre className="muted" style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{JSON.stringify(g.inputs_snapshot, null, 2)}</pre>
                </details>
              ) : null}
              <label>Comment / decision rationale (required for No-Go and Return)</label>
              <textarea value={comments[g.id] || ""} onChange={(e) => setComments({ ...comments, [g.id]: e.target.value })} />
              <div className="row-actions mt-14">
                {DECISIONS[g.gate].map(([value, label], idx) => (
                  <button
                    key={value}
                    className={idx === 0 ? "btn primary" : "btn danger"}
                    disabled={busy}
                    onClick={() => decide(g, value)}
                  >
                    {label}
                  </button>
                ))}
                <Link className="btn" href={`/opportunities/${g.opportunity_id}`}>Open bid room</Link>
              </div>
            </>
          ) : (
            <p className="muted">
              {g.decision ? `Decision: ${g.decision}` : ""} {g.decided_at ? `· ${fmtDateTime(g.decided_at)}` : ""} {g.comment ? `· “${g.comment}”` : ""}
            </p>
          )}
        </div>
      ))}
    </>
  );
}
