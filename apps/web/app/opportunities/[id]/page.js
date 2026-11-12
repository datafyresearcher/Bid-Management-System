"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  api, cacheGet, cacheSet, CHECKLIST_STATUSES, checklistStatusLabel, daysTo, DECISIONS, fmtDate, fmtDateTime,
  fmtMoney, RELATED_KIND_LABELS, severityClass, stateClass, stateLabel, STAGE_LABELS,
} from "../../../lib/api";
import { tierClass } from "../../../components/SourceTag";
import BrandLoader from "../../../components/Loading";

export default function OpportunityPage() {
  const params = useParams();
  const id = params.id;
  const [opp, setOpp] = useState(null);
  const [proposal, setProposal] = useState(null);
  const [submission, setSubmission] = useState(null);
  const [sharedDocs, setSharedDocs] = useState([]);
  const [tab, setTab] = useState("overview");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);
  const [comments, setComments] = useState({});
  const [files, setFiles] = useState([]);
  const [savingSection, setSavingSection] = useState(null);
  const [outcomeForm, setOutcomeForm] = useState({ result: "WON", reason_code: "", comment: "", award_value: "" });
  const hydrated = useRef(false);

  const load = useCallback(() => {
    const endpoints = [
      [`/api/opportunities/${id}`, setOpp, (e) => setError(e.message)],
      [`/api/proposals/${id}`, setProposal, () => setProposal(null)],
      // A missing submission comes back as an empty object; the page wants null.
      [`/api/proposals/${id}/submission`, (s) => setSubmission(s && s.id ? s : null), () => setSubmission(null)],
      [
        `/api/proposals/${id}/knowledge-documents`,
        (d) => setSharedDocs((d && d.documents) || []),
        () => setSharedDocs([]),
      ],
    ];
    if (!hydrated.current) {
      for (const [url, setState] of endpoints) {
        const cached = cacheGet(url);
        if (cached) setState(cached);
      }
      hydrated.current = true;
    }
    for (const [url, setState, onErr] of endpoints) {
      api(url)
        .then((data) => {
          setState(data);
          cacheSet(url, data);
        })
        .catch(onErr);
    }
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
  if (!opp) return <BrandLoader />;

  const pendingGate = (opp.gates || []).find((g) => ["PENDING", "OVERDUE"].includes(g.status));
  const closeStates = ["WON", "LOST", "REJECTED", "ABANDONED", "SCREENED_OUT", "AUTO_ARCHIVED"];
  const d = daysTo(opp.submission_deadline);
  const expired = opp.deadline_status === "expired";

  const decide = (gate) => {
    const decision = window.prompt(
      `Decision for ${STAGE_LABELS[gate]}: ${DECISIONS[gate].map(([v]) => v).join(" / ")}`,
      DECISIONS[gate][0][0]
    );
    if (!decision) return;
    act(
      () => api(`/api/gates/${gate.id}/decide`, {
        method: "POST",
        body: JSON.stringify({ decision: decision.trim().toUpperCase().replace("-", "_"), comment: comments[gate.id] || "" }),
      }),
      `Stage ${gate} decided: ${decision}`
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

  const markChecklistItem = (index, status) => {
    act(
      () => api(`/api/opportunities/${id}/checklist`, {
        method: "PUT",
        body: JSON.stringify({ index, status }),
      }),
      `Marked ${checklistStatusLabel(status).toLowerCase()}`
    );
  };

  const toggleSharedDoc = (doc) => {
    act(
      () => api(`/api/proposals/${id}/knowledge-documents`, {
        method: "PUT",
        body: JSON.stringify({ id: doc.id, included: !doc.included }),
      }),
      doc.included ? "Removed from this proposal" : "Added to this proposal"
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
        {opp.buyer_name} {opp.buyer_ref ? `· Ref ${opp.buyer_ref}` : ""} · <span className={stateClass(opp.state)}>{stateLabel(opp.state)}</span>{" "}
        {opp.score_total !== null && opp.score_total !== undefined ? `· Score ${Math.round(opp.score_total)}` : ""}
        {d !== null ? ` · ${expired ? "deadline passed" : `${d} day(s) to deadline`}` : ""}
      </p>

      {expired ? (
        <div className="notice info mb-14">
          The submission deadline for this tender has passed, so it can no longer be bid. The record
          is kept and everything on it stays readable.
        </div>
      ) : null}

      {error ? <div className="notice err">{error}</div> : null}
      {info ? <div className="notice ok">{info}</div> : null}

      <div className="row-actions mb-14">
        {opp.state === "NORMALIZED" ? (
          <button className="btn primary small" disabled={busy} onClick={() => act(() => api(`/api/opportunities/${id}/score`, { method: "POST" }), "Scored")}>
            Score this tender
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
              const reason = window.prompt("Reason for not pursuing this tender:", "manual");
              if (!reason) return;
              act(() => api(`/api/opportunities/${id}/abandon`, { method: "POST", body: JSON.stringify({ reason_code: reason, comment: "" }) }), "No longer pursuing");
            }}
          >
            Not pursuing
          </button>
        ) : null}
      </div>

      <div className="tabs">
        {[
          ["overview", "Overview"],
          ["analysis", "Requirements & Risk"],
          ["documents", "Documents"],
          ["checklist", `Submission checklist${(opp.checklist || []).length ? ` (${opp.checklist.length})` : ""}`],
          ["gates", `Stages${pendingGate ? " (1 waiting)" : ""}`],
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
              <dt>Implied BOQ value</dt>
              <dd>
                {opp.estimated_boq_value ? (
                  <>
                    {fmtMoney(opp.estimated_boq_value, opp.currency)}
                    <div className="muted">
                      Indicative — worked out from the bid security at {opp.bid_security_percent}% of the
                      estimated value. Confirm against the tender document before pricing.
                    </div>
                  </>
                ) : (
                  <>
                    —
                    {opp.boq_estimate_note ? <div className="muted">{opp.boq_estimate_note}</div> : null}
                  </>
                )}
              </dd>
              <dt>Published</dt><dd>{fmtDate(opp.published_at)}</dd>
              <dt>Clarification deadline</dt><dd>{fmtDate(opp.clarification_deadline)}</dd>
              <dt>Submission deadline</dt><dd>{fmtDate(opp.submission_deadline)}</dd>
              <dt>Opening</dt><dd>{fmtDate(opp.opening_at)}</dd>
              <dt>PEC required</dt><dd>{opp.pec_category_required || "—"}</dd>
              <dt>Prequalification</dt><dd>{opp.prequal_required ? "Yes" : "No"}</dd>
              <dt>Bid security</dt>
              <dd>
                {fmtMoney(opp.bid_security_amount, opp.currency)}
                {opp.bid_security_form ? ` (${opp.bid_security_form})` : ""}
                {opp.bid_security_percent ? ` — ${opp.bid_security_percent}% of the estimated value` : ""}
              </dd>
              <dt>Tender fee</dt><dd>{fmtMoney(opp.tender_fee, opp.currency)}</dd>
              <dt>Documents</dt><dd>{opp.documents_status}</dd>
              <dt>Submission mode</dt><dd>{opp.submission_mode}</dd>
            </dl>
            {opp.source ? (
              <>
                <label>Source</label>
                <div className="src-detail">
                  <div className="src-line">
                    <span className="badge badge-blue">{opp.source.name || opp.source.code}</span>
                    {opp.source.tier ? <span className={tierClass(opp.source.tier)}>Tier {opp.source.tier}</span> : null}
                  </div>
                  <dl className="kv">
                    <dt>Published by</dt><dd>{opp.source.authority || "—"}</dd>
                    <dt>Reference</dt><dd>{opp.source.reference || "—"}</dd>
                    <dt>Access</dt><dd>{opp.source.access || "—"}</dd>
                    <dt>Last scanned</dt><dd>{opp.source.last_scan_at ? fmtDateTime(opp.source.last_scan_at) : "never"}</dd>
                  </dl>
                  {opp.document_link ? (
                    <a className="src-link" href={opp.document_link} target="_blank" rel="noreferrer noopener">
                      Download the bidding document from the source portal ↗
                    </a>
                  ) : null}
                  {opp.source.notice_url ? (
                    <a className="src-link" href={opp.source.notice_url} target="_blank" rel="noreferrer noopener">
                      Open the notice on the source portal ↗
                    </a>
                  ) : opp.source.portal_url ? (
                    <a className="src-link" href={opp.source.portal_url} target="_blank" rel="noreferrer noopener">
                      Open the source portal ↗
                    </a>
                  ) : null}
                </div>
              </>
            ) : null}
            {opp.description ? <><label>Description</label><p className="muted">{opp.description}</p></> : null}
          </div>
          <div>
            <div className="card mb-14">
              <h3>Bid fit assessment</h3>
              <p className="muted">
                How this tender scores against our capacity, and what to check before deciding. The
                figures are worked out from the tender document; the wording is the system&apos;s reading
                of it.
              </p>
              {opp.bid_summary && opp.bid_summary.sections ? (
                opp.bid_summary.sections.map((section) => (
                  <div key={section.key} className="card section-card">
                    <div className="section-title">
                      <h4 style={{ textTransform: "none", fontSize: 14, margin: 0 }}>{section.label}</h4>
                    </div>
                    {section.available ? (
                      <ul className="timeline">
                        {section.points.map((point, i) => (
                          <li key={i}>
                            <div>{point.text}</div>
                            <div className="t-meta">{point.source}{point.anchor ? ` · ${point.anchor}` : ""}</div>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="muted">Nothing stated for this tender.</p>
                    )}
                  </div>
                ))
              ) : (
                <p>{opp.ai_rationale || "Not scored yet."}</p>
              )}
              {opp.ai_confidence !== null && opp.ai_confidence !== undefined ? (
                <p className="muted">
                  Confidence {Math.round(opp.ai_confidence * 100)}% — how much of this score rests on
                  evidence in the knowledge base rather than on absent data.
                </p>
              ) : null}
              {opp.extraction_grade ? (
                <p className="muted">
                  Document analysis quality <strong>{opp.extraction_grade}</strong> — A: all key fields
                  found, D: nothing could be read from the document.
                </p>
              ) : null}
              {opp.hard_gate_result ? (
                <p className="muted">
                  Automatic eligibility checks: {opp.hard_gate_result.passed ? "passed" : "failed"}
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
                    <div>{stateLabel(e.from_state) || "—"} → <strong>{stateLabel(e.to_state)}</strong> <span className="muted">({e.trigger})</span></div>
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
            <h3>Requirements found in the tender ({opp.requirements.length})</h3>
            <ul className="timeline">
              {opp.requirements.map((r) => (
                <li key={r.id}>
                  <div><span className="badge">{r.category}</span> {r.text}</div>
                  <div className="t-meta">from {r.anchor} {r.mandatory ? "· mandatory" : ""}</div>
                </li>
              ))}
              {opp.requirements.length === 0 ? <p className="muted">No analysis yet — decide Stage 1, or press “Re-run analysis”.</p> : null}
            </ul>
          </div>
          <div>
            <div className="card mb-14">
              <h3>Risks spotted ({opp.risk_flags.length})</h3>
              {opp.risk_flags.map((r) => (
                <div key={r.id} className={`card section-card ${r.severity === "High" ? "risk-high" : r.severity === "Medium" ? "risk-med" : "risk-low"}`}>
                  <div><span className={severityClass(r.severity)}>{r.severity}</span> <strong>{r.title}</strong></div>
                  <div className="muted">{r.detail}</div>
                  {r.suggested_action ? <div className="muted">What to do: {r.suggested_action}</div> : null}
                </div>
              ))}
              {opp.risk_flags.length === 0 ? <p className="muted">No risks spotted.</p> : null}
            </div>
            <div className="card">
              <h3>Compliance matrix ({opp.compliance.length})</h3>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Requirement</th><th>Evidence</th><th>Status</th></tr></thead>
                  <tbody>
                    {opp.compliance.map((c) => (
                      <tr key={c.id}>
                        <td data-label="Requirement">{c.requirement.slice(0, 120)}<div className="muted">{c.category}</div></td>
                        <td data-label="Evidence">{c.evidence_ref || c.evidence_type}</td>
                        <td data-label="Status"><span className="badge">{c.status}</span></td>
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
          {opp.document_link ? (
            <p>
              <a className="src-link" href={opp.document_link} target="_blank" rel="noreferrer noopener">
                Download the bidding document from {opp.source?.name || "the source portal"} ↗
              </a>
              <div className="muted">
                This is the file on the authority&apos;s own site. If it could not be fetched into the
                system, the link is still here so you can open it yourself.
              </div>
            </p>
          ) : (
            <p className="muted">No direct link to the bidding document was captured for this tender.</p>
          )}

          {opp.related_documents && opp.related_documents.length ? (
            <>
              <h4 className="mt-14">Clarifications, amendments and other related documents</h4>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Document</th><th>Type</th><th>Date</th><th></th></tr></thead>
                  <tbody>
                    {opp.related_documents.map((rel) => (
                      <tr key={rel.url}>
                        <td data-label="Document">{rel.title}</td>
                        <td data-label="Type"><span className="badge">{RELATED_KIND_LABELS[rel.kind] || "Related document"}</span></td>
                        <td data-label="Date">{rel.date ? fmtDate(rel.date) : "—"}</td>
                        <td data-label="">
                          <a className="src-link" href={rel.url} target="_blank" rel="noreferrer noopener">Open ↗</a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}

          <div className="inline-form">
            <div className="wide">
              <label>Upload a tender document (PDF, DOCX, TXT, HTML)</label>
              <input type="file" onChange={(e) => setFiles(e.target.files)} />
            </div>
            <button className="btn primary" disabled={busy || !files.length} onClick={upload}>Upload & parse</button>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>File</th><th>Type</th><th>Size</th><th>Pages</th><th>Read</th><th>Added</th></tr></thead>
              <tbody>
                {opp.documents.map((doc) => (
                  <tr key={doc.id}>
                    <td data-label="File">{doc.filename}</td>
                    <td data-label="Type">{doc.doc_type}</td>
                    <td data-label="Size">{Math.round((doc.size || 0) / 1024)} KB</td>
                    <td data-label="Pages">{doc.pages || "—"}</td>
                    <td data-label="Read">{doc.parsed ? "yes" : `no — ${doc.parse_status || ""}`}</td>
                    <td data-label="Added">{fmtDate(doc.created_at)}</td>
                  </tr>
                ))}
                {opp.documents.length === 0 ? <tr><td colSpan="6" data-label="" className="muted">No documents yet.</td></tr> : null}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {tab === "checklist" ? (
        <div className="card">
          <div className="section-title">
            <h3>Submission checklist ({(opp.checklist || []).length})</h3>
          </div>
          <p className="muted">
            Everything this tender asks the bidder to produce, read out of the bidding document. Mark
            each item as you go. Where the document names a clause, it is shown so you can turn to it.
          </p>
          {(opp.checklist || []).length === 0 ? (
            <p className="muted">
              No checklist yet — the bidding document has to be downloaded and read first. Press
              “Re-run analysis” once the documents are on file.
            </p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>What to submit</th><th>Where it is asked for</th><th>Status</th></tr></thead>
                <tbody>
                  {opp.checklist.map((item, index) => (
                    <tr key={index}>
                      <td data-label="What to submit">
                        {item.item}
                        <div className="muted">
                          {item.category_label || item.category}
                          {item.mandatory ? " · required" : ""}
                        </div>
                      </td>
                      <td data-label="Where it is asked for">
                        {item.clause || (item.page ? `page ${item.page}` : "—")}
                      </td>
                      <td data-label="Status">
                        <div className="row-actions">
                          {CHECKLIST_STATUSES.map(([value, label]) => (
                            <button
                              key={value}
                              className={item.status === value ? "btn small primary" : "btn small"}
                              disabled={busy}
                              onClick={() => markChecklistItem(index, value)}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : null}

      {tab === "gates" ? (
        <div className="grid cols-2">
          <div className="card">
            <h3>Waiting for a decision</h3>
            {pendingGate ? (
              <>
                <p><span className="badge badge-amber">{STAGE_LABELS[pendingGate.gate]}</span> {pendingGate.title}</p>
                <p className="muted">Owner role: {pendingGate.owner_role} · due {fmtDateTime(pendingGate.due_at)}</p>
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
                          `Stage ${pendingGate.gate}: ${label}`
                        )
                      }
                    >
                      {label}
                    </button>
                  ))}
                  <button className="btn small" disabled={busy} onClick={() => decide(pendingGate.gate)}>Another decision…</button>
                </div>
              </>
            ) : (
              <p className="muted">Nothing is waiting for a decision. The next stage opens automatically.</p>
            )}
          </div>
          <div className="card">
            <h3>Stage history</h3>
            <ul className="timeline">
              {(opp.gates || []).map((g) => (
                <li key={g.id}>
                  <div><span className="badge">{STAGE_LABELS[g.gate]}</span> <strong>{g.status}</strong> {g.decision ? `· ${g.decision}` : ""}</div>
                  <div className="t-meta">
                    owner {g.owner_role} · due {fmtDateTime(g.due_at)}
                    {g.decided_at ? ` · decided ${fmtDateTime(g.decided_at)}` : ""}
                    {g.comment ? ` · “${g.comment}”` : ""}
                  </div>
                </li>
              ))}
              {(opp.gates || []).length === 0 ? <p className="muted">No stages yet.</p> : null}
            </ul>
          </div>
        </div>
      ) : null}

      {tab === "proposal" ? (
        <div>
          <div className="card mb-14">
            <div className="section-title">
              <h3>Shared documents for this proposal</h3>
            </div>
            <p className="muted">
              These are held once in the knowledge base rather than uploaded for every tender. Tick the
              ones this bid carries; the ones you leave out are not packed with it. A locked document is
              the master copy and always travels with the proposal.
            </p>
            {sharedDocs.length === 0 ? (
              <p className="muted">
                No shared documents in the knowledge base yet. Add them under Knowledge Base → Shared
                documents.
              </p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Include</th><th>Document</th><th>Type</th><th>Valid until</th></tr></thead>
                  <tbody>
                    {sharedDocs.map((doc) => (
                      <tr key={doc.id}>
                        <td data-label="Include">
                          <label>
                            <input
                              type="checkbox"
                              checked={!!doc.included}
                              disabled={busy || doc.locked}
                              onChange={() => toggleSharedDoc(doc)}
                            />
                            {doc.locked ? <span className="muted"> locked</span> : null}
                          </label>
                        </td>
                        <td data-label="Document">{doc.title}</td>
                        <td data-label="Type">{doc.category}</td>
                        <td data-label="Valid until">{doc.valid_until || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
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
            {!proposal ? <p className="muted">Drafting starts automatically once Stage 2 is confirmed (or generate now).</p> : null}
            {(proposal ? proposal.sections : []).map((section) => (
              <SectionEditor key={section.id} section={section} busy={savingSection === section.id} onSave={saveSection} />
            ))}
          </div>
        </div>
      ) : null}

      {tab === "submission" ? (
        <div className="grid cols-2">
          <div className="card">
            <div className="section-title">
              <h3>Submission pack {submission ? `(${submission.status})` : ""}</h3>
            </div>
            {submission && submission.checklist ? (
              <>
                {submission.checklist.map((item, index) => (
                  <div className="checklist-item" key={index}>
                    <div>
                      {item.item}
                      <div className="muted">{item.category}{item.owner ? ` · owner ${item.owner}` : ""}{item.mandatory ? " · required" : ""}</div>
                    </div>
                    <button className={item.status === "ready" ? "btn small primary" : "btn small"} disabled={busy} onClick={() => toggleChecklist(index, item.status)}>
                      {item.status === "ready" ? "Ready" : "Outstanding"}
                    </button>
                  </div>
                ))}
                {submission.portal_note ? <div className="notice info mt-14">{submission.portal_note}</div> : null}
                {submission.pack_files ? <p className="muted">Pack files: {submission.pack_files.join(", ")}</p> : null}
                {submission.submitted_at ? <p className="muted">Submitted at {fmtDateTime(submission.submitted_at)}</p> : null}
              </>
            ) : (
              <p className="muted">The submission pack is put together at Stage 4 approval.</p>
            )}
          </div>
          <div className="card">
            <h3>Record the result</h3>
            <p className="muted">Available once the bid has been submitted.</p>
            <label>Result</label>
            <select value={outcomeForm.result} onChange={(e) => setOutcomeForm({ ...outcomeForm, result: e.target.value })}>
              <option value="WON">Won</option>
              <option value="LOST">Lost</option>
              <option value="REJECTED">Rejected</option>
            </select>
            <label>Reason code (e.g. price, eligibility, technical)</label>
            <input value={outcomeForm.reason_code} onChange={(e) => setOutcomeForm({ ...outcomeForm, reason_code: e.target.value })} />
            <label>Award value (optional)</label>
            <input value={outcomeForm.award_value} onChange={(e) => setOutcomeForm({ ...outcomeForm, award_value: e.target.value })} />
            <label>Comment / competitor notes</label>
            <textarea value={outcomeForm.comment} onChange={(e) => setOutcomeForm({ ...outcomeForm, comment: e.target.value })} />
            <div className="mt-14">
              <button className="btn primary" disabled={busy || !["SUBMITTED", "EVALUATION"].includes(opp.state)} onClick={recordOutcome}>
                Record the result
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
        <p className="muted">References: {section.citations.map((c) => `${c.type}:${c.ref}`).join(", ")}</p>
      ) : null}
    </div>
  );
}
