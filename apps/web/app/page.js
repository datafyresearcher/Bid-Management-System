"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, deadlineInfo, fmtDate, fmtMoney, GATE_LABELS, severityClass, slaCountdown, slaIsOverdue, stateClass } from "../lib/api";

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

  // Counts come from the server so the tiles and the pipeline always agree.
  const activeCount = data.active_count ?? 0;
  const screenedOutCount = data.screened_out_count ?? 0;
  const submittedCount = data.submitted_count ?? 0;

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
          <div className="metric">{screenedOutCount}</div>
        </div>
        <div className="card">
          <h3>Submitted / Evaluation</h3>
          <div className="metric">{submittedCount}</div>
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
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Gate</th>
                    <th>Opportunity</th>
                    <th>Tender closes</th>
                    <th>Review SLA</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {data.pending_gates.map((g) => {
                    const dl = deadlineInfo(g.opportunity?.submission_deadline);
                    return (
                      <tr key={g.id}>
                        <td data-label="Gate"><span className="badge badge-amber">{GATE_LABELS[g.gate] || `G${g.gate}`}</span></td>
                        <td data-label="Opportunity">
                          <Link href={`/opportunities/${g.opportunity_id}`}>
                            {(g.opportunity && g.opportunity.title) ? g.opportunity.title.slice(0, 70) : `#${g.opportunity_id}`}
                          </Link>
                          {g.opportunity ? <div className="muted">{g.opportunity.buyer_name}</div> : null}
                        </td>
                        <td data-label="Tender closes" className={dl.className}>
                          {dl.label}
                          {dl.days !== null ? <div className="muted">{dl.countdown}</div> : null}
                        </td>
                        <td data-label="Review SLA" className={slaIsOverdue(g.due_at) ? "score-low" : "muted"}>
                          {slaCountdown(g.due_at)}
                          <div className="muted">internal</div>
                        </td>
                        <td data-label=""><Link className="btn small" href={`/opportunities/${g.opportunity_id}`}>Open</Link></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
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
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Tender</th><th>Deadline</th><th>State</th></tr>
                </thead>
                <tbody>
                  {data.closing_soon.map((o) => (
                    <tr key={o.id}>
                      <td data-label="Tender">
                        <Link href={`/opportunities/${o.id}`}>{o.title.slice(0, 70)}</Link>
                        <div className="muted">{o.buyer_name}</div>
                      </td>
                      <td data-label="Deadline">{fmtDate(o.submission_deadline)}</td>
                      <td data-label="State"><span className={stateClass(o.state)}>{o.state}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Score</th><th>Tender</th><th>Value</th><th>State</th></tr>
                </thead>
                <tbody>
                  {data.top_opportunities.map((o) => (
                    <tr key={o.id}>
                      <td data-label="Score"><span className={`score-pill ${o.score_total >= 70 ? "score-good" : o.score_total >= 55 ? "score-mid" : "score-low"}`}>{Math.round(o.score_total || 0)}</span></td>
                      <td data-label="Tender">
                        <Link href={`/opportunities/${o.id}`}>{o.title.slice(0, 65)}</Link>
                        <div className="muted">{o.buyer_name}</div>
                      </td>
                      <td data-label="Value">{fmtMoney(o.estimated_value, o.currency)}</td>
                      <td data-label="State"><span className={stateClass(o.state)}>{o.state}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Source</th><th>Adapter</th><th>Health</th><th>Last scan</th></tr>
              </thead>
              <tbody>
                {data.sources.map((s) => (
                  <tr key={s.id}>
                    <td data-label="Source">{s.name}<div className="muted">{s.code}</div></td>
                    <td data-label="Adapter">{s.adapter}</td>
                    <td data-label="Health">
                      <span className={s.health === "ok" ? "badge badge-green" : s.health === "error" ? "badge badge-red" : "badge badge-gray"}>
                        {s.health}
                      </span>
                    </td>
                    <td data-label="Last scan">{s.last_scan_at ? fmtDate(s.last_scan_at) : "never"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <h3>AI quality</h3>
          <div className="kv">
            <dt>Provider</dt>
            <dd>
              {data.ai_quality.provider?.provider} · {data.ai_quality.provider?.model}
              {data.ai_quality.provider?.simulated ? <span className="badge badge-gray">simulated</span> : null}
            </dd>
            <dt>Scores recorded</dt><dd>{data.ai_quality.scores_total}</dd>
            <dt>Screening overrides</dt><dd>{data.ai_quality.screening_overrides} ({Math.round((data.ai_quality.override_rate || 0) * 100)}%)</dd>
            <dt>Gate approvals</dt><dd>{data.ai_quality.gate_approvals}</dd>
            <dt>Gate returns</dt><dd>{data.ai_quality.gate_returns}</dd>
            <dt>Approval rate</dt><dd>{Math.round((data.ai_quality.gate_approval_rate || 0) * 100)}%</dd>
            <dt>Bids decided</dt><dd>{data.ai_quality.outcomes_total}</dd>
            <dt>Win rate</dt>
            <dd>
              {data.ai_quality.outcomes_total
                ? `${Math.round((data.ai_quality.win_rate || 0) * 100)}% (${data.ai_quality.outcomes_won} won / ${data.ai_quality.outcomes_lost} lost)`
                : "no outcomes recorded yet"}
            </dd>
            <dt>Avg extraction confidence</dt>
            <dd>
              {data.ai_quality.avg_extraction_confidence !== null && data.ai_quality.avg_extraction_confidence !== undefined
                ? `${Math.round(data.ai_quality.avg_extraction_confidence * 100)}%`
                : "—"}
            </dd>
            <dt>Proposal sections with gaps</dt>
            <dd>
              {data.ai_quality.proposal_sections_with_gaps} of {data.ai_quality.proposal_sections_total}
              {data.ai_quality.proposal_sections_total
                ? ` (${Math.round((data.ai_quality.gap_rate || 0) * 100)}%)`
                : ""}
            </dd>
          </div>
          {data.ai_quality.score_band_performance?.length ? (
            <div className="mt-14">
              <h4 className="muted" style={{ marginBottom: 6 }}>Does a higher score mean more wins?</h4>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Score band</th><th>Decided</th><th>Won</th><th>Win rate</th></tr></thead>
                  <tbody>
                    {data.ai_quality.score_band_performance.map((b) => (
                      <tr key={b.band}>
                        <td data-label="Score band">{b.band}</td>
                        <td data-label="Decided">{b.decided}</td>
                        <td data-label="Won">{b.wins}</td>
                        <td data-label="Win rate">{b.decided ? `${Math.round(b.win_rate * 100)}%` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}
          <div className="mt-14">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Task</th><th>Calls</th><th>Invalid</th><th>Avg latency</th></tr>
                </thead>
                <tbody>
                  {Object.entries(data.ai_quality.llm_by_task || {}).map(([task, m]) => (
                    <tr key={task}>
                      <td data-label="Task">{task}</td>
                      <td data-label="Calls">{m.calls}</td>
                      <td data-label="Invalid">{m.invalid}</td>
                      <td data-label="Avg latency">{m.avg_latency_ms} ms</td>
                    </tr>
                  ))}
                  {Object.keys(data.ai_quality.llm_by_task || {}).length === 0 ? (
                    <tr><td colSpan="4" data-label="" className="muted">No LLM calls yet.</td></tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
