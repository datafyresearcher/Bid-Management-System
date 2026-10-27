"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, deadlineInfo, fmtDate, fmtDateTime, fmtMoney, GATE_LABELS, getUser, severityClass, slaCountdown, slaIsOverdue, stateClass, urlHost, urlHostPath } from "../lib/api";
import SourceTag, { sourceHealthClass, sourceLink, sourceName, tierClass } from "../components/SourceTag";
import { DashboardSkeleton } from "../components/Loading";

export default function DashboardPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [scanning, setScanning] = useState(null);
  const [scanNote, setScanNote] = useState("");

  const load = () => {
    api("/api/dashboard").then(setData).catch((e) => setError(e.message));
  };

  useEffect(() => {
    load();
  }, []);

  if (error) return <div className="notice err">{error}</div>;
  if (!data) return <DashboardSkeleton />;

  // Counts come from the server so the tiles and the pipeline always agree.
  const activeCount = data.active_count ?? 0;
  const screenedOutCount = data.screened_out_count ?? 0;
  const submittedCount = data.submitted_count ?? 0;

  const markRead = async () => {
    await api("/api/dashboard/notifications/read", { method: "POST" });
    load();
  };

  // Reading a portal takes the time the portal takes. The button stays busy
  // until the connector comes back, and says what happened either way.
  const runScan = async (source) => {
    setScanning(source.code);
    setScanNote("");
    try {
      const result = await api(`/api/sources/${source.id}/scan`, { method: "POST" });
      const scored = result.scored ? `, ${result.scored} scored and waiting for a decision` : "";
      setScanNote(`${source.name}: read ${result.notices} notices, ${result.new} new${scored}.`);
      load();
    } catch (err) {
      setScanNote(`${source.name}: could not be read — ${err.message}`);
    } finally {
      setScanning(null);
    }
  };

  const canScan = ["admin", "bid_manager"].includes(getUser()?.role);

  // The banner has to say what the feed is really doing. A system switched to
  // live reading has not read anything until a portal has answered, and a
  // feed that stopped talking to its portals is not live in any sense.
  const feed = data.feed_status || {};
  const banner = (() => {
    if (feed.mode !== "live") {
      return {
        tone: "info",
        text: "Connectors are reading saved captures of the official portals listed below — every reference and notice link still points at the authority's own site.",
      };
    }
    if (!feed.portals_read_live) {
      return {
        tone: "err",
        text: "Live reading is switched on, but no portal has been read yet — what is on screen is the seeded demo data, not live tenders. Run a scan from the source register below.",
      };
    }
    const when = feed.last_scan_at ? fmtDateTime(feed.last_scan_at) : "an unknown time ago";
    const read = `${feed.portals_read_live} of ${feed.portals_total} portals were read directly, ${when}.`;
    const count = `${feed.records_live ?? 0} of ${feed.records_total ?? 0} records came from those reads.`;
    const other = feed.records_other
      ? ` The other ${feed.records_other} are seeded demo records, not live tenders.`
      : "";
    if (feed.portals_unreachable) {
      // A host this deployment cannot reach is not going to be fixed by
      // pressing Scan again, so the banner must not suggest that it would.
      return {
        tone: "err",
        text: `Live reading: ${read} ${count}${other} ${feed.portals_unreachable} portal(s) cannot be reached from this deployment (${feed.unreachable_names.join(", ")}) — their tenders are missing from this view. Scanning again will not help until the API runs where that host is reachable.`,
      };
    }
    if (feed.portals_failed) {
      return {
        tone: "err",
        text: `Live reading: ${read} ${count}${other} ${feed.portals_failed} could not be read (${feed.failed_names.join(", ")}) — their tenders are missing from this view.`,
      };
    }
    if (feed.portals_never_read) {
      return {
        tone: "info",
        text: `Live reading: ${read} ${count}${other} ${feed.portals_never_read} portal(s) have not been read yet — press Scan in the source register to read them.`,
      };
    }
    if (feed.stale) {
      return {
        tone: "err",
        text: `Live reading: ${read} ${count}${other} That is more than a day old, so this view may miss tenders published since.`,
      };
    }
    return {
      tone: "ok",
      text: `Live reading: ${read} ${count}${other} Every reference and notice link points at the authority's own site.`,
    };
  })();

  return (
    <>
      <h2 className="page-title">Dashboard</h2>
      <p className="page-sub">Live view of discovery, screening and gate activity.</p>

      <div className={`notice ${banner.tone} src-banner`}>
        <strong>Where this data comes from.</strong>{" "}
        {banner.text}{" "}
        <a href="#data-sources">See the source register</a>.
      </div>

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
            <Link href="/review" className="btn small">
              Open review queue{data.pending_gates_total ? ` (${data.pending_gates_total})` : ""}
            </Link>
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
                          <SourceTag source={g.opportunity?.source} />
                        </td>
                        <td data-label="Tender closes" className={`nowrap ${dl.className}`}>
                          {dl.label}
                          {dl.days !== null ? <div className="muted">{dl.countdown}</div> : null}
                        </td>
                        <td data-label="Review SLA" className={`nowrap ${slaIsOverdue(g.due_at) ? "score-low" : "muted"}`}>
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
          {data.pending_gates_total > data.pending_gates.length ? (
            <p className="muted mt-14">
              Showing the {data.pending_gates.length} most urgent of {data.pending_gates_total}. The
              review queue pages through the rest, and the tender inbox lists every captured tender.
            </p>
          ) : null}
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
                        <SourceTag source={o.source} />
                      </td>
                      <td data-label="Deadline" className="nowrap">{fmtDate(o.submission_deadline)}</td>
                      <td data-label="State" className="nowrap"><span className={stateClass(o.state)}>{o.state}</span></td>
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
                      <td data-label="Score" className="nowrap"><span className={`score-pill ${o.score_total >= 70 ? "score-good" : o.score_total >= 55 ? "score-mid" : "score-low"}`}>{Math.round(o.score_total || 0)}</span></td>
                      <td data-label="Tender">
                        <Link href={`/opportunities/${o.id}`}>{o.title.slice(0, 65)}</Link>
                        <div className="muted">{o.buyer_name}</div>
                        <SourceTag source={o.source} />
                      </td>
                      <td data-label="Value" className="nowrap">{fmtMoney(o.estimated_value, o.currency)}</td>
                      <td data-label="State" className="nowrap"><span className={stateClass(o.state)}>{o.state}</span></td>
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

      <div className="card mt-14" id="data-sources">
        <div className="section-title">
          <h3>Data sources &amp; provenance</h3>
          <span className="muted">{data.sources.length} authorized channels</span>
        </div>
        <p className="muted src-note">
          Every tender in this system is captured from one of the channels below. Each one is an
          official publication by the body that owns the tender, or one of our own desks — no
          aggregator, no scraped mirror. The reference number shown against a record is the one
          the authority published it under, so it can be traced back to the source.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Source</th>
                <th>Tier</th>
                <th>Records</th>
                <th>Official portal</th>
                <th>Notice listing</th>
                <th>Access</th>
                <th>Last scan</th>
                <th>Health</th>
                {canScan ? <th>Read now</th> : null}
              </tr>
            </thead>
            <tbody>
              {data.sources.map((s) => (
                <tr key={s.id}>
                  <td data-label="Source">
                    <strong>{s.name}</strong>
                    <div className="muted">{s.code}</div>
                    {s.authority ? <div className="muted src-authority">{s.authority}</div> : null}
                  </td>
                  <td data-label="Tier">{s.tier ? <span className={tierClass(s.tier)}>Tier {s.tier}</span> : <span className="muted">—</span>}</td>
                  <td data-label="Records">{s.records ?? 0}</td>
                  <td data-label="Official portal">
                    {s.url ? (
                      <a href={s.url} target="_blank" rel="noreferrer noopener" className="src-portal">{urlHost(s.url)} ↗</a>
                    ) : (
                      <span className="muted">internal desk</span>
                    )}
                  </td>
                  <td data-label="Notice listing">
                    {s.listing_url ? (
                      <a href={s.listing_url} target="_blank" rel="noreferrer noopener" className="src-portal">{urlHostPath(s.listing_url)} ↗</a>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td data-label="Access"><span className="badge badge-gray">{s.access || "—"}</span></td>
                  <td data-label="Last scan">
                    {s.last_scan_at ? fmtDateTime(s.last_scan_at) : <span className="muted">never</span>}
                    {s.last_scan_stats?.mode ? <div className="muted">{s.last_scan_stats.mode}</div> : null}
                    {s.last_scan_stats?.error ? (
                      <div className="muted" title={s.last_scan_stats.error}>
                        {(s.last_scan_stats.error || "").slice(0, 110)}
                      </div>
                    ) : null}
                  </td>
                  <td data-label="Health"><span className={sourceHealthClass(s.health)}>{s.health}</span></td>
                  {canScan ? (
                    <td data-label="Read now">
                      {s.type === "portal" ? (
                        <button
                          className="btn small"
                          disabled={scanning !== null}
                          onClick={() => runScan(s)}
                        >
                          {scanning === s.code ? "Reading…" : "Scan"}
                        </button>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
          {scanNote ? <p className="muted src-note">{scanNote}</p> : null}
        </div>
      </div>

      <div className="grid cols-2 mt-14">
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
          {Object.keys(data.ai_quality.llm_by_model || {}).length ? (
            <div className="mt-14">
              <h4 className="muted" style={{ marginBottom: 6 }}>
                Models that answered
              </h4>
              <p className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
                A router picks the model per call, so this is the list that actually served the
                work — not the model that was asked for.
              </p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>Model</th><th>Calls</th><th>Invalid</th><th>Valid rate</th><th>Avg latency</th></tr>
                  </thead>
                  <tbody>
                    {Object.entries(data.ai_quality.llm_by_model || {}).map(([model, m]) => (
                      <tr key={model}>
                        <td data-label="Model">{model}</td>
                        <td data-label="Calls">{m.calls}</td>
                        <td data-label="Invalid">{m.invalid}</td>
                        <td data-label="Valid rate">{Math.round((m.valid_rate || 0) * 100)}%</td>
                        <td data-label="Avg latency">{m.avg_latency_ms} ms</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </>
  );
}
