"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, cacheGet, cacheSet, deadlineInfo, DECISIONS, fmtDateTime, GATE_LABELS, slaCountdown, slaIsOverdue } from "../../lib/api";
import BrandLoader from "../../components/Loading";

const PAGE_SIZE = 50;

export default function ReviewPage() {
  const [gates, setGates] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("PENDING,OVERDUE");
  const [role, setRole] = useState("");
  const [comments, setComments] = useState({});
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const hydrated = useRef(false);

  const load = useCallback(() => {
    const params = new URLSearchParams({
      status,
      limit: String(PAGE_SIZE),
      offset: String((page - 1) * PAGE_SIZE),
    });
    if (role) params.set("role", role);
    const gatesUrl = `/api/gates?${params.toString()}`;
    if (!hydrated.current) {
      const cached = cacheGet(gatesUrl);
      if (cached) {
        setGates(cached);
        setLoading(false);
      }
      hydrated.current = true;
    }
    api(gatesUrl)
      .then((data) => {
        setGates(data);
        cacheSet(gatesUrl, data);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
    const countParams = new URLSearchParams({ status });
    if (role) countParams.set("role", role);
    const countUrl = `/api/gates/count?${countParams.toString()}`;
    api(countUrl)
      .then((data) => {
        setTotal(data.total || 0);
        cacheSet(countUrl, data);
      })
      .catch(() => setTotal(0));
  }, [status, role, page]);

  // A new filter is a new view, so it starts at the first page.
  useEffect(() => {
    setPage(1);
  }, [status, role]);

  useEffect(() => {
    load();
  }, [load]);

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const first = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const last = Math.min(page * PAGE_SIZE, total);

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

  if (loading && !error) return <BrandLoader />;

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
      {total > 0 ? (
        <div className="pager">
          <p className="muted mb-14">
            Showing {first}–{last} of {total} gate(s).{" "}
            {total > PAGE_SIZE
              ? "Use the buttons below, or narrow the view by status or owner role."
              : null}
          </p>
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

      {gates.map((g) => {
        const dl = deadlineInfo(g.opportunity?.submission_deadline);
        return (
        <div className="card section-card" key={g.id}>
          <div className="section-title">
            <h3 style={{ textTransform: "none", fontSize: 14 }}>
              <span className={g.status === "OVERDUE" ? "badge badge-red" : "badge badge-amber"}>{GATE_LABELS[g.gate] || `G${g.gate}`}</span>{" "}
              {g.title}
            </h3>
            <span className={g.status === "OVERDUE" ? "badge badge-red" : "badge"}>{g.status}</span>
          </div>
          <p className="muted">
            Owner: {g.owner_role} · Review SLA {g.sla_hours}h{" "}
            <span className={slaIsOverdue(g.due_at) ? "score-low" : ""}>
              ({slaCountdown(g.due_at)})
            </span>{" "}
            ·{" "}
            {g.opportunity ? <Link href={`/opportunities/${g.opportunity_id}`}>{g.opportunity.title.slice(0, 90)} ({g.opportunity.buyer_name})</Link> : `opportunity #${g.opportunity_id}`}
          </p>
          {g.opportunity ? (
            <p className={dl.urgent ? "score-low" : "muted"}>
              <strong>Tender closes {dl.label}</strong>{" "}
              {dl.days !== null ? `(${dl.countdown})` : ""}
              {dl.urgent ? " — prioritise this gate" : ""}
            </p>
          ) : null}

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
        );
      })}
    </>
  );
}
