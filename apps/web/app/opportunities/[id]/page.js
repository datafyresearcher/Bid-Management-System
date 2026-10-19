"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  api, daysTo, DECISIONS, fmtDate, fmtDateTime, fmtMoney, GATE_LABELS, severityClass, stateClass,
} from "../../../lib/api";

export default function OpportunityPage() {
  const params = useParams();
  const id = params.id;
  const [opp, setOpp] = useState(null);
  const [proposal, setProposal] = useState(null);
  const [submission, setSubmission] = useState(null);
  const [tab, setTab] = useState("overview");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);
  const [comments, setComments] = useState({});
  const [files, setFiles] = useState([]);
  const [savingSection, setSavingSection] = useState(null);
  const [outcomeForm, setOutcomeForm] = useState({ result: "WON", reason_code: "", comment: "", award_value: "" });

  const load = useCallback(() => {
    api(`/api/opportunities/${id}`).then(setOpp).catch((e) => setError(e.message));
    api(`/api/proposals/${id}`).then(setProposal).catch(() => setProposal(null));
    api(`/api/proposals/${id}/submission`).then((s) => setSubmission(s && s.id ? s : null)).catch(() => setSubmission(null));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const act = async (fn, message) => {
    setBusy(true);
    setError("");
    setInfo("");
    try {
      await fn();
      setInfo(message || "Done");
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (error && !opp) return <div className="notice err">{error}</div>;
  if (!opp) return <p className="muted">Loading bid room…</p>;

  const pendingGate = (opp.gates || []).find((g) => ["PENDING", "OVERDUE"].includes(g.status));
  const closeStates = ["WON", "LOST", "REJECTED", "ABANDONED", "SCREENED_OUT", "AUTO_ARCHIVED"];
  const d = daysTo(opp.submission_deadline);

  const decide = (gate) => {
    const decision = window.prompt(
      `Decision for ${GATE_LABELS[gate]}: ${DECISIONS[gate].map(([v]) => v).join(" / ")}`,
      DECISIONS[gate][0][0]
    );
    if (!decision) return;
    act(
      () => api(`/api/gates/${gate.id}/decide`, {
        method: "POST",
        body: JSON.stringify({ decision: decision.trim().toUpperCase().replace("-", "_"), comment: comments[gate.id] || "" }),
      }),
      `Gate ${gate} decided: ${decision}`
    );
  };

  const upload = async () => {
    if (!files.length) return;
    const form = new FormData();
    form.append("file", files[0]);
    await act(
      () => api(`/api/opportunities/${id}/documents`, { method: "POST", body: form }),
      "Document uploaded and parsed"
    );
    setFiles([]);
  };

  const saveSection = async (section, content) => {
    setSavingSection(section.id);
    try {
      await api(`/api/proposals/sections/${section.id}`, { method: "PUT", body: JSON.stringify({ content }) });
      setInfo("Section saved");
    } catch (e) {
      setError(e.message);
    } finally {
      setSavingSection(null);
    }
  };

  const toggleChecklist = (index, current) => {
    act(
      () => api(`/api/proposals/${id}/submission/checklist`, {
        method: "PUT",
        body: JSON.stringify({ index, status: current === "ready" ? "open" : "ready" }),
      }),
      "Checklist updated"
    );
  };

  const recordOutcome = () =>
    act(
      () => api(`/api/opportunities/${id}/outcome`, {
        method: "POST",
        body: JSON.stringify({
          result: outcomeForm.result,
          reason_code: outcomeForm.reason_code,
          comment: outcomeForm.comment,
          award_value: outcomeForm.award_value ? Number(outcomeForm.award_value) : null,
        }),
      }),
      "Outcome recorded"
    );

  return (
    <>
      <p className="muted mb-14"><Link href="/pipeline">← Pipeline</Link> · <Link href="/inbox">Inbox</Link></p>
      <h2 className="page-title">{opp.title}</h2>
      <p className="page-sub">
        {opp.buyer_name} {opp.buyer_ref ? `· Ref ${opp.buyer_ref}` : ""} · <span className={stateClass(opp.state)}>{opp.state}</span>{" "}
        {opp.score_total !== null && opp.score_total !== undefined ? `· Score ${Math.round(opp.score_total)}` : ""}
        {d !== null ? ` · ${d} day(s) to deadline` : ""}
      </p>

      {error ? <div className="notice err">{error}</div> : null}
      {info ? <div className="notice ok">{info}</div> : null}

      <div className="row-actions mb-14">
        {opp.state === "NORMALIZED" ? (
          <button className="btn primary small" disabled={busy} onClick={() => act(() => api(`/api/opportunities/${id}/score`, { method: "POST" }), "Scored")}>
            Run AI scoring
          </button>
        ) : null}
        <button className="btn small" disabled={busy} onClick={() => act(() => api(`/api/opportunities/${id}/analyze`, { method: "POST" }), "Analysis rerun")}>
          Re-run analysis
        </button>
        {!closeStates.includes(opp.state) ? (
          <button
            className="btn danger small"
            disabled={busy}
            onClick={() => {
              const reason = window.prompt("Abandon reason code:", "manual");
              if (!reason) return;
              act(() => api(`/api/opportunities/${id}/abandon`, { method: "POST", body: JSON.stringify({ reason_code: reason, comment: "" }) }), "Abandoned");
            }}
          >
            Abandon
          </button>
        ) : null}
      </div>

      <div className="tabs">
        {[
          ["overview", "Overview"],
          ["analysis", "Requirements & Risk"],
          ["documents", "Documents"],
          ["gates", `Gates${pendingGate ? " (1 pending)" : ""}`],
          ["proposal", "Proposal"],
          ["submission", "Submission & Outcome"],
        ].map(([key, label]) => (
          <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}>{label}</button>
        ))}
      </div>

      {tab === "overview" ? (
        <div className="grid cols-2">
          <div className="card">
            <h3>Details</h3>
            <dl className="kv">
              <dt>Category</dt><dd>{opp.category_internal} {opp.category_source ? `(${opp.category_source})` : ""}</dd>
              <dt>Tender type</dt><dd>{opp.tender_type}</dd>
              <dt>Regime</dt><dd>{opp.procurement_regime || "—"}</dd>
              <dt>Contract family</dt><dd>{opp.contract_family || "—"}</dd>
              <dt>Estimated value</dt><dd>{fmtMoney(opp.estimated_value, opp.currency)} ({opp.value_band})</dd>
              <dt>Published</dt><dd>{fmtDate(opp.published_at)}</dd>
              <dt>Clarification deadline</dt><dd>{fmtDate(opp.clarification_deadline)}</dd>
              <dt>Submission deadline</dt><dd>{fmtDate(opp.submission_deadline)}</dd>
              <dt>Opening</dt><dd>{fmtDate(opp.opening_at)}</dd>
              <dt>PEC required</dt><dd>{opp.pec_category_required || "—"}</dd>
              <dt>Prequalification</dt><dd>{opp.prequal_required ? "Yes" : "No"}</dd>
              <dt>Bid security</dt><dd>{fmtMoney(opp.bid_security_amount, opp.currency)} {opp.bid_security_form ? `(${opp.bid_security_form})` : ""}</dd>
              <dt>Tender fee</dt><dd>{fmtMoney(opp.tender_fee, opp.currency)}</dd>
              <dt>Documents</dt><dd>{opp.documents_status}</dd>
              <dt>Submission mode</dt><dd>{opp.submission_mode}</dd>
            </dl>
            {opp.description ? <><label>Description</label><p className="muted">{opp.description}</p></> : null}
          </div>
          <div>
            <div className="card mb-14">
              <h3>AI rationale</h3>
              <p>{opp.ai_rationale || "Not scored yet."}</p>
              {opp.hard_gate_result ? (
                <p className="muted">
                  Hard gates: {opp.hard_gate_result.passed ? "passed" : "failed"}
                  {opp.hard_gate_result.failures && opp.hard_gate_result.failures.length
                    ? ` — ${opp.hard_gate_result.failures.map((f) => f.reason).join("; ")}`
                    : ""}
                </p>
              ) : null}
            </div>
            <div className="card">
              <h3>Workflow timeline</h3>
              <ul className="timeline">
                {(opp.timeline || []).map((e, i) => (
                  <li key={i}>
                    <div>{e.from_state || "—"} → <strong>{e.to_state}</strong> <span className="muted">({e.trigger})</span></div>
                    <div className="t-meta">{e.actor} · {fmtDateTime(e.created_at)} {e.detail ? `· ${e.detail}` : ""}</div>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      ) : null}

      {tab === "analysis" ? (
        <div className="grid cols-2">
          <div className="card">
            <h3>Extracted requirements ({opp.requirements.length})</h3>
            <ul className="timeline">
              {opp.requirements.map((r) => (
                <li key={r.id}>
                  <div><span className="badge">{r.category}</span> {r.text}</div>
                  <div className="t-meta">anchor: {r.anchor} {r.mandatory ? "· mandatory" : ""}</div>
                </li>
              ))}
              {opp.requirements.length === 0 ? <p className="muted">No analysis yet — decide Gate 1 GO or hit “Re-run analysis”.</p> : null}
            </ul>
          </div>
          <div>
            <div className="card mb-14">
              <h3>Risk flags ({opp.risk_flags.length})</h3>
              {opp.risk_flags.map((r) => (
                <div key={r.id} className={`card section-card ${r.severity === "High" ? "risk-high" : r.severity === "Medium" ? "risk-med" : "risk-low"}`}>
                  <div><span className={severityClass(r.severity)}>{r.severity}</span> <strong>{r.title}</strong></div>
                  <div className="muted">{r.detail}</div>
                  {r.suggested_action ? <div className="muted">Action: {r.suggested_action}</div> : null}
                </div>
              ))}
              {opp.risk_flags.length === 0 ? <p className="muted">No risk flags.</p> : null}
            </div>
            <div className="card">
              <h3>Compliance matrix ({opp.compliance.length})</h3>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Requirement</th><th>Evidence</th><th>Status</th></tr></thead>
                  <tbody>
                    {opp.compliance.map((c) => (
                      <tr key={c.id}>
                        <td>{c.requirement.slice(0, 120)}<div className="muted">{c.category}</div></td>
                        <td>{c.evidence_ref || c.evidence_type}</td>
                        <td><span className="badge">{c.status}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {tab === "documents" ? (
        <div className="card">
          <div className="section-title">
            <h3>Documents ({opp.documents.length}) — status: {opp.documents_status}</h3>
          </div>
          <div className="inline-form">
            <div className="wide">
              <label>Upload tender document (PDF, DOCX, TXT, HTML)</label>
              <input type="file" onChange={(e) => setFiles(e.target.files)} />
            </div>
            <button className="btn primary" disabled={busy || !files.length} onClick={upload}>Upload & parse</button>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>File</th><th>Type</th><th>Size</th><th>Parsed</th><th>Uploaded</th></tr></thead>
              <tbody>
                {opp.documents.map((doc) => (
                  <tr key={doc.id}>
                    <td>{doc.filename}</td>
                    <td>{doc.doc_type}</td>
                    <td>{Math.round((doc.size || 0) / 1024)} KB</td>
                    <td>{doc.parsed ? "yes" : `no — ${doc.parse_status || ""}`}</td>
                    <td>{fmtDate(doc.created_at)}</td>
                  </tr>
                ))}
                {opp.documents.length === 0 ? <tr><td colSpan="5" className="muted">No documents yet.</td></tr> : null}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {tab === "gates" ? (
        <div className="grid cols-2">
          <div className="card">
            <h3>Pending decision</h3>
            {pendingGate ? (
              <>
                <p><span className="badge badge-amber">{GATE_LABELS[pendingGate.gate]}</span> {pendingGate.title}</p>
                <p className="muted">Owner role: {pendingGate.owner_role} · SLA {pendingGate.sla_hours}h · due {fmtDateTime(pendingGate.due_at)}</p>
                {pendingGate.inputs_snapshot ? (
                  <pre className="muted" style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{JSON.stringify(pendingGate.inputs_snapshot, null, 2)}</pre>
                ) : null}
                <label>Comment</label>
                <textarea value={comments[pendingGate.id] || ""} onChange={(e) => setComments({ ...comments, [pendingGate.id]: e.target.value })} />
                <div className="row-actions mt-14">
                  {DECISIONS[pendingGate.gate].map(([value, label]) => (
                    <button
                      key={value}
                      className={value === DECISIONS[pendingGate.gate][0][0] ? "btn primary" : "btn danger"}
                      disabled={busy}
                      onClick={() =>
                        act(
                          () => api(`/api/gates/${pendingGate.id}/decide`, {
                            method: "POST",
                            body: JSON.stringify({ decision: value, comment: comments[pendingGate.id] || "" }),
                          }),
                          `Gate ${pendingGate.gate}: ${label}`
                        )
                      }
                    >
                      {label}
                    </button>
                  ))}
                  <button className="btn small" disabled={busy} onClick={() => decide(pendingGate.gate)}>Custom decision…</button>
                </div>
              </>
            ) : (
              <p className="muted">No pending gate. The workflow will open the next gate automatically.</p>
            )}
          </div>
          <div className="card">
            <h3>Gate history</h3>
            <ul className="timeline">
              {(opp.gates || []).map((g) => (
                <li key={g.id}>
                  <div><span className="badge">{GATE_LABELS[g.gate]}</span> <strong>{g.status}</strong> {g.decision ? `· ${g.decision}` : ""}</div>
                  <div className="t-meta">
                    owner {g.owner_role} · due {fmtDateTime(g.due_at)}
                    {g.decided_at ? ` · decided ${fmtDateTime(g.decided_at)}` : ""}
                    {g.comment ? ` · “${g.comment}”` : ""}
                  </div>
                </li>
              ))}
              {(opp.gates || []).length === 0 ? <p className="muted">No gates yet.</p> : null}
            </ul>
          </div>
        </div>
      ) : null}

      {tab === "proposal" ? (
        <div className="card">
          <div className="section-title">
            <h3>Proposal {proposal ? `(${proposal.status}, v${proposal.version})` : "(not drafted)"}</h3>
            <div className="row-actions">
              <button className="btn small primary" disabled={busy} onClick={() => act(() => api(`/api/proposals/${id}/generate`, { method: "POST" }), "Proposal generated")}>
                {proposal ? "Regenerate" : "Generate draft"}
              </button>
              <button className="btn small" disabled={busy || !proposal} onClick={() => act(() => api(`/api/proposals/${id}/export`, { method: "POST" }), "Pack exported to storage")}>
                Export pack
              </button>
            </div>
          </div>
          {!proposal ? <p className="muted">Drafting starts automatically after Gate 2 confirmation (or generate now).</p> : null}
          {(proposal ? proposal.sections : []).map((section) => (
            <SectionEditor key={section.id} section={section} busy={savingSection === section.id} onSave={saveSection} />
          ))}
        </div>
      ) : null}

      {tab === "submission" ? (
        <div className="grid cols-2">
          <div className="card">
            <div className="section-title">
              <h3>Submission checklist {submission ? `(${submission.status})` : ""}</h3>
            </div>
            {submission && submission.checklist ? (
              <>
                {submission.checklist.map((item, index) => (
                  <div className="checklist-item" key={index}>
                    <div>
                      {item.item}
                      <div className="muted">{item.category}{item.owner ? ` · owner ${item.owner}` : ""}{item.mandatory ? " · mandatory" : ""}</div>
                    </div>
                    <button className={item.status === "ready" ? "btn small primary" : "btn small"} disabled={busy} onClick={() => toggleChecklist(index, item.status)}>
                      {item.status}
                    </button>
                  </div>
                ))}
                {submission.portal_note ? <div className="notice info mt-14">{submission.portal_note}</div> : null}
                {submission.pack_files ? <p className="muted">Pack files: {submission.pack_files.join(", ")}</p> : null}
                {submission.submitted_at ? <p className="muted">Submitted at {fmtDateTime(submission.submitted_at)}</p> : null}
              </>
            ) : (
              <p className="muted">Checklist is generated at Gate 3 approval.</p>
            )}
          </div>
          <div className="card">
            <h3>Record outcome</h3>
            <p className="muted">Available after submission (state SUBMITTED or EVALUATION).</p>
            <label>Result</label>
            <select value={outcomeForm.result} onChange={(e) => setOutcomeForm({ ...outcomeForm, result: e.target.value })}>
              <option value="WON">WON</option>
              <option value="LOST">LOST</option>
              <option value="REJECTED">REJECTED</option>
            </select>
            <label>Reason code (e.g. price, eligibility, technical)</label>
            <input value={outcomeForm.reason_code} onChange={(e) => setOutcomeForm({ ...outcomeForm, reason_code: e.target.value })} />
            <label>Award value (optional)</label>
            <input value={outcomeForm.award_value} onChange={(e) => setOutcomeForm({ ...outcomeForm, award_value: e.target.value })} />
            <label>Comment / competitor notes</label>
            <textarea value={outcomeForm.comment} onChange={(e) => setOutcomeForm({ ...outcomeForm, comment: e.target.value })} />
            <div className="mt-14">
              <button className="btn primary" disabled={busy || !["SUBMITTED", "EVALUATION"].includes(opp.state)} onClick={recordOutcome}>
                Record outcome
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

function SectionEditor({ section, busy, onSave }) {
  const [content, setContent] = useState(section.content || "");
  useEffect(() => {
    setContent(section.content || "");
  }, [section.content]);

  return (
    <div className="card section-card">
      <div className="section-title">
        <h3 style={{ textTransform: "none", fontSize: 14 }}>
          {section.title} <span className={section.status === "GAPS" ? "badge badge-amber" : "badge badge-green"}>{section.status}</span>
        </h3>
        <button className="btn small" disabled={busy || content === section.content} onClick={() => onSave(section, content)}>
          {busy ? "Saving…" : "Save"}
        </button>
      </div>
      <textarea value={content} onChange={(e) => setContent(e.target.value)} />
      {section.citations && section.citations.length ? (
        <p className="muted">Citations: {section.citations.map((c) => `${c.type}:${c.ref}`).join(", ")}</p>
      ) : null}
    </div>
  );
}
