"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, daysTo, fmtDate, fmtMoney, GATE_LABELS, severityClass, stateClass } from "../lib/api";

export default function DashboardPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  const load = () => {
    api("/api/dashboard").then(setData).catch((e) => setError(e.message));
  };

  useEffect(() => {
    load();
  }, []);

  if (error) return <div className="notice err">{error}</div>;
  if (!data) return <p className="muted">Loading dashboard…</p>;

  const activeCount = Object.entries(data.state_counts)
    .filter(([s]) => !["WON", "LOST", "REJECTED", "ABANDONED"].includes(s))
    .reduce((acc, [, n]) => acc + n, 0);

  const markRead = async () => {
    await api("/api/dashboard/notifications/read", { method: "POST" });
    load();
  };

  return (
    <>
      <h2 className="page-title">Dashboard</h2>
      <p className="page-sub">Live view of discovery, screening and gate activity.</p>

      <div className="grid cols-4 mb-14">
        <div className="card">
          <h3>Active opportunities</h3>
          <div className="metric">{activeCount}</div>
        </div>
        <div className="card">
          <h3>Pending gates</h3>
          <div className="metric">{data.pending_gates_total}</div>
        </div>
        <div className="card">
          <h3>Screened out</h3>
          <div className="metric">{(data.state_counts.SCREENED_OUT || 0) + (data.state_counts.AUTO_ARCHIVED || 0)}</div>
        </div>
        <div className="card">
          <h3>Submitted / Evaluation</h3>
          <div className="metric">{(data.state_counts.SUBMITTED || 0) + (data.state_counts.EVALUATION || 0)}</div>
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <div className="section-title">
            <h3>Your gate queue</h3>
            <Link href="/review" className="btn small">Open review queue</Link>
          </div>
          {data.pending_gates.length === 0 ? (
            <p className="muted">No pending gates for your role.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Gate</th>
                  <th>Opportunity</th>
                  <th>Due</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {data.pending_gates.map((g) => {
                  const d = daysTo(g.due_at);
                  return (
                    <tr key={g.id}>
                      <td><span className="badge badge-amber">{GATE_LABELS[g.gate] || `G${g.gate}`}</span></td>
                      <td>
                        <Link href={`/opportunities/${g.opportunity_id}`}>
                          {(g.opportunity && g.opportunity.title) ? g.opportunity.title.slice(0, 70) : `#${g.opportunity_id}`}
                        </Link>
                        {g.opportunity ? <div className="muted">{g.opportunity.buyer_name}</div> : null}
                      </td>
                      <td className={d !== null && d <= 0 ? "score-low" : ""}>{fmtDate(g.due_at)}{d !== null ? ` (${d}d)` : ""}</td>
                      <td><Link className="btn small" href={`/opportunities/${g.opportunity_id}`}>Open</Link></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <div className="section-title">
            <h3>Closing soon (7 days)</h3>
            <Link href="/pipeline" className="btn small">Pipeline</Link>
          </div>
          {data.closing_soon.length === 0 ? (
            <p className="muted">No deadlines in the next 7 days.</p>
          ) : (
            <table>
              <thead>
                <tr><th>Tender</th><th>Deadline</th><th>State</th></tr>
              </thead>
              <tbody>
                {data.closing_soon.map((o) => (
                  <tr key={o.id}>
                    <td>
                      <Link href={`/opportunities/${o.id}`}>{o.title.slice(0, 70)}</Link>
                      <div className="muted">{o.buyer_name}</div>
                    </td>
                    <td>{fmtDate(o.submission_deadline)}</td>
                    <td><span className={stateClass(o.state)}>{o.state}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="grid cols-2 mt-14">
        <div className="card">
          <div className="section-title">
            <h3>Top scored opportunities</h3>
            <Link href="/inbox" className="btn small">Inbox</Link>
          </div>
          {data.top_opportunities.length === 0 ? (
            <p className="muted">Nothing scored yet.</p>
          ) : (
            <table>
              <thead>
                <tr><th>Score</th><th>Tender</th><th>Value</th><th>State</th></tr>
              </thead>
              <tbody>
                {data.top_opportunities.map((o) => (
                  <tr key={o.id}>
                    <td><span className={`score-pill ${o.score_total >= 70 ? "score-good" : o.score_total >= 55 ? "score-mid" : "score-low"}`}>{Math.round(o.score_total || 0)}</span></td>
                    <td>
                      <Link href={`/opportunities/${o.id}`}>{o.title.slice(0, 65)}</Link>
                      <div className="muted">{o.buyer_name}</div>
                    </td>
                    <td>{fmtMoney(o.estimated_value, o.currency)}</td>
                    <td><span className={stateClass(o.state)}>{o.state}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <div className="section-title">
            <h3>Notifications</h3>
            <button className="btn small" onClick={markRead}>Mark all read</button>
          </div>
          {data.notifications.length === 0 ? (
            <p className="muted">No notifications.</p>
          ) : (
            <ul className="timeline">
              {data.notifications.map((n) => (
                <li key={n.id}>
                  <div>
                    <span className={n.severity === "warning" ? "badge badge-amber" : "badge badge-blue"}>{n.type}</span>{" "}
                    {n.opportunity_id ? (
                      <Link href={`/opportunities/${n.opportunity_id}`}>{n.title}</Link>
                    ) : (
                      n.title
                    )}
                  </div>
                  <div className="t-meta">{fmtDate(n.created_at)}{n.read ? " · read" : " · unread"}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="grid cols-2 mt-14">
        <div className="card">
          <h3>Source health</h3>
          <table>
            <thead>
              <tr><th>Source</th><th>Adapter</th><th>Health</th><th>Last scan</th></tr>
            </thead>
            <tbody>
              {data.sources.map((s) => (
                <tr key={s.id}>
                  <td>{s.name}<div className="muted">{s.code}</div></td>
                  <td>{s.adapter}</td>
                  <td>
                    <span className={s.health === "ok" ? "badge badge-green" : s.health === "error" ? "badge badge-red" : "badge badge-gray"}>
                      {s.health}
                    </span>
                  </td>
                  <td>{s.last_scan_at ? fmtDate(s.last_scan_at) : "never"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h3>AI quality</h3>
          <div className="kv">
            <dt>Scores recorded</dt><dd>{data.ai_quality.scores_total}</dd>
            <dt>Screening overrides</dt><dd>{data.ai_quality.screening_overrides} ({Math.round((data.ai_quality.override_rate || 0) * 100)}%)</dd>
            <dt>Gate approvals</dt><dd>{data.ai_quality.gate_approvals}</dd>
            <dt>Gate returns</dt><dd>{data.ai_quality.gate_returns}</dd>
            <dt>Approval rate</dt><dd>{Math.round((data.ai_quality.gate_approval_rate || 0) * 100)}%</dd>
          </div>
          <div className="mt-14">
            <table>
              <thead>
                <tr><th>Task</th><th>Calls</th><th>Invalid</th><th>Avg latency</th></tr>
              </thead>
              <tbody>
                {Object.entries(data.ai_quality.llm_by_task || {}).map(([task, m]) => (
                  <tr key={task}>
                    <td>{task}</td>
                    <td>{m.calls}</td>
                    <td>{m.invalid}</td>
                    <td>{m.avg_latency_ms} ms</td>
                  </tr>
                ))}
                {Object.keys(data.ai_quality.llm_by_task || {}).length === 0 ? (
                  <tr><td colSpan="4" className="muted">No LLM calls (deterministic mode).</td></tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}
